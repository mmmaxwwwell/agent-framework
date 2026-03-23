---
name: run-tasks
description: Process agent-framework task lists by spawning Opus sub-agents to execute each incomplete task autonomously. Use when the user wants to run tasks from a project or feature prompt.
user-invocable: true
allowed-tools: Read, Bash, Glob, Grep, Agent
argument-hint: [prompt-file]
---

# Run Tasks — Agent Framework Task Runner

You are a lightweight orchestrator. Your job is to dispatch sub-agents to execute tasks. **You do not read project files, notes, or code.** You only read what you need to make routing decisions.

## Context discipline

**You MUST keep your context minimal.** Follow these rules strictly:

- **DO read**: the task list file (to know what to run next)
- **DO read**: the prompt file (only to find the paths to the task list and notes file)
- **DO run**: `git rev-parse HEAD` to record pre-task SHAs for the review gate
- **DO NOT read**: the notes file, source code, or any other project files
- **DO NOT load**: full file contents into your context for any reason
- If you need information to make a decision, spawn a sub-agent to research it and return a concise summary (1-3 sentences)

## How it works

1. **Find the prompt file** — Use `$ARGUMENTS` if provided, otherwise glob for `*-prompt.md` files (excluding `generator-prompt.md` and `feature-prompt.md`). If multiple exist, list them and ask the user which one to run.

2. **Extract file paths** — Read the prompt file ONLY to identify:
   - The path to the task list (`*-tasks.md`)
   - The path to the notes file (`*-notes.md`)
   - The prompt file path itself
   Then stop reading. Do not absorb the project spec into your context.

3. **Read the task list** — Parse the task list to identify incomplete tasks (`- [ ]`). Skip blocked (`- [?]`) and completed (`- [x]`) tasks.

4. **Detect project stack** — Before executing any tasks, determine the project's tech stack so the review gate (if enabled) can select the right code-review variant. Spawn a quick research sub-agent (model: "haiku") to check for `package.json`, framework imports, and file extensions, then return one of: `react`, `node`, or `generic`. Cache the result — do not re-detect per task.

5. **Tag the pre-task state** — Before each task sub-agent runs, record the current git commit SHA: run `git rev-parse HEAD` and store it as `pre_task_sha`. This is the baseline for the review gate's diff.

6. **Execute tasks sequentially** — For each incomplete task, spawn an Opus sub-agent using the Agent tool with `model: "opus"`. The sub-agent does ALL the heavy reading and work.

7. **Between tasks** — After each sub-agent completes:
   - Re-read the task list only (the sub-agent may have updated it)
   - If a task was marked `[?]` (blocked), stop and ask the user for input
   - If the sub-agent reports a build/test failure it couldn't resolve, try the **fix-build escalation** (see below) before giving up
   - If the review gate is enabled, run the **review gate** (see below) before reporting progress
   - Report progress to the user

8. **Continue until done** — Keep dispatching until all tasks are complete, one is blocked, or a failure occurs.

## Fix-build escalation

If a sub-agent completes its work but reports that a build command, test suite, or linter is still failing:

1. **Extract the failing command** from the sub-agent's response (e.g. `npm run build`, `cargo test`, `nix build .#foo`)
2. **Spawn a fix-build loop** — use the fix-build skill's sub-agent pattern: dispatch an Opus sub-agent that runs the failing command, diagnoses the error, and fixes it. If it still fails, dispatch again with the previous error context. Repeat up to 5 iterations (shorter limit than standalone fix-build since this is mid-task).
3. **If fix-build succeeds** — continue to the next task as normal. Include a note in the progress report that fix-build resolved a build issue.
4. **If fix-build fails after 5 attempts** — mark the task `[?]` with the remaining error and stop.

The fix-build sub-agent prompt should include the project context files (prompt, task list, notes) so it understands the project, plus the failing command and error output. Use this template:

```
You are fixing a build/test failure that occurred while working on an agent-framework project.

Read these files for project context:
- Prompt file (project spec): <prompt file path>
- Task list: <task list path>
- Notes & context: <notes file path>

## Command
Run this command:
<the failing command>

## Previous attempts
<if attempt 2+, one-line summary of what was tried and what error remained>

## Rules
- Run the command EXACTLY as written above. Do not modify it, pipe it through other commands, or add redirections. Run it verbatim.
- Read any files referenced in the error output to understand the problem.
- Investigate the root cause before making changes.
- Make the minimal fix needed. Do not refactor unrelated code.
- After fixing, run the command again (exactly as written) to verify.
- In your final response, clearly state:
  1. Whether the command now passes or still fails
  2. A one-line summary of what you fixed (or what error remains)
```

## Review gate

The review gate runs a code-review sub-agent against each task's changes, then fixes any significant findings before moving on. This catches bugs, security issues, and quality problems early — when the diff is small and fixes are low-risk.

### When it runs

The review gate is **enabled by default**. The user can disable it by saying "skip reviews", "no reviews", or similar. If disabled, skip this section entirely.

### How it works

1. **Diff the task's changes** — Run `git diff <pre_task_sha>` (no `...HEAD` — this diffs the working tree + staged changes against the saved commit). If there's no diff (task made no code changes), skip the review.

2. **Spawn a review sub-agent** — Use the review sub-agent prompt template below. Use `model: "opus"`. Select the code-review variant based on the stack detected in step 4:
   - `react` → use the `code-review-react` checklist
   - `node` → use the `code-review-node` checklist
   - `generic` → use the base `code-review` checklist

3. **Evaluate findings** — Parse the review sub-agent's response:
   - **P0 or P1 findings** → spawn a review-fix sub-agent to address them (see template below)
   - **P2 only or no findings** → log any P2s in the notes file and continue to the next task

4. **Review-fix loop** — After the fix sub-agent completes, re-run the review (spawn a new review sub-agent diffing against the same `pre_task_sha`). Repeat up to **2 iterations** (review → fix → re-review → fix → final review). If P0/P1 findings persist after 2 fix rounds, log the remaining issues in the notes file and continue — do not block progress indefinitely.

### Review sub-agent prompt template

```
You are reviewing code changes made by a task sub-agent in an agent-framework project.

## Diff to review
Run this command to see the changes:
git diff <pre_task_sha>

## Task that was executed
<the specific task description>

## Project stack
<react | node | generic>

## Instructions
- Review ONLY the diff above. Do not review pre-existing code.
- Use the <react | node | generic> code-review checklist (see the corresponding code-review skill for the full checklist).
- Apply confidence scoring: discard anything below 70. Only P0/P1/P2 findings.
- Read the full files around changed code to understand context — don't review the diff in isolation.
- In your final response, output findings in this exact format:

### Findings

| # | Sev | Category | File:Line | Finding | Suggested fix | Confidence |
|---|-----|----------|-----------|---------|---------------|------------|

If no issues found, respond with exactly: NO_ISSUES_FOUND

### Summary
- P0: N | P1: N | P2: N
```

### Review-fix sub-agent prompt template

```
You are fixing code review findings in an agent-framework project. A review sub-agent identified issues in code that was just written by a task sub-agent.

Read these files for project context:
- Prompt file (project spec): <prompt file path>
- Task list: <task list path>
- Notes & context: <notes file path>

## Review findings to fix
<paste the findings table from the review sub-agent — only P0 and P1 rows>

## Rules
- Fix ALL P0 and P1 findings listed above.
- Read the files referenced in the findings to understand full context before making changes.
- Make minimal, targeted fixes. Do not refactor unrelated code.
- Do not introduce new functionality — only fix the identified issues.
- After fixing, run the project's build/test command if one is evident from the project context. If the build fails, fix that too.
- In your final response, state:
  1. Which findings you fixed and how (one line each)
  2. Whether the build still passes
```

## Sub-agent prompt template

Each sub-agent is fully autonomous. It reads everything it needs on its own. Construct the prompt like this:

```
You are executing a single task from an agent-framework project.

Read these files to get full context:
- Prompt file (project spec): <prompt file path>
- Task list: <task list path>
- Notes & context: <notes file path>

## Your Assignment
Execute ONLY this task:
<the specific task description>

## Rules
- Read the prompt file, task list, and notes file before starting work.
- Execute ONLY this one task. Do not skip ahead to other tasks.
- Read any files you need to understand the codebase before making changes.
- After completing the task, update the task list: mark this task `- [x]` with a brief note of what was done.
- Update the notes file with any new findings, decisions, or context discovered during implementation.
- If the task is blocked or unclear, mark it `- [?]` with the specific question and do NOT proceed.
- If the task turns out to be unnecessary, mark it `- [~]` with why.
- If you discover new tasks are needed, add them to the task list.
- Test your work before marking complete. Run builds, tests, and linters to completion no matter how long they take — do not skip, truncate, or time out on long-running commands. If a build takes 10 minutes, wait for it.
- If a build or test command fails and you cannot fix it, report the exact command that failed and the error summary in your final response so the orchestrator can escalate to fix-build.
- Prefer minimal changes. Don't refactor unrelated code.
```

## Parallel execution

Default to **sequential execution** unless the user explicitly asks for parallel runs. If the user requests parallel execution, only parallelize tasks that:
- Are in the same phase
- Touch completely different files
- Have no data dependencies on each other

When running in parallel, use separate worktrees (`isolation: "worktree"`) for each sub-agent and merge results afterward.

## Progress reporting

After each task completes, output a brief status update:

```
[2/14] Completed: "Create data model for X"
  Summary: <sub-agent's result summary>
  Review: No issues found (or: Fixed 1 P0, 1 P1 in 1 round)
  Next: "Build X service layer"
```

If the review gate is disabled:
```
[2/14] Completed: "Create data model for X"
  Summary: <sub-agent's result summary>
  Next: "Build X service layer"
```

If all tasks complete:
```
All tasks complete! Review the final state:
- Task list: agent-work/<project>-tasks.md
- Notes: agent-work/<project>-notes.md
```

## Error handling

- If a sub-agent errors (not a timeout), report the failure and stop. Use generous timeouts (up to 10 minutes) for sub-agents — builds can be slow and that's expected.
- If the task list or notes file can't be found, ask the user for the correct paths
- If the prompt file references files that don't exist yet (greenfield project), note this in the sub-agent prompt so it knows to create them
