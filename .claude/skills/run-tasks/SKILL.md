---
name: run-tasks
description: Process agent-framework task lists by spawning Opus sub-agents to execute each incomplete task autonomously. Use when the user wants to run tasks from a project or feature prompt.
user-invocable: true
allowed-tools: Read, Glob, Agent
argument-hint: [prompt-file]
---

# Run Tasks — Agent Framework Task Runner

You are a lightweight orchestrator. Your job is to dispatch sub-agents to execute tasks. **You do not read project files, notes, or code.** You only read what you need to make routing decisions.

## Context discipline

**You MUST keep your context minimal.** Follow these rules strictly:

- **DO read**: the task list file (to know what to run next)
- **DO read**: the prompt file (only to find the paths to the task list and notes file)
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

4. **Execute tasks sequentially** — For each incomplete task, spawn an Opus sub-agent using the Agent tool with `model: "opus"`. The sub-agent does ALL the heavy reading and work.

5. **Between tasks** — After each sub-agent completes:
   - Re-read the task list only (the sub-agent may have updated it)
   - Report progress to the user
   - If a task was marked `[?]` (blocked), stop and ask the user for input
   - If the sub-agent reports a build/test failure it couldn't resolve, try the **fix-build escalation** (see below) before giving up

6. **Continue until done** — Keep dispatching until all tasks are complete, one is blocked, or a failure occurs.

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
- Test your work before marking complete.
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
  Next: "Build X service layer"
```

If all tasks complete:
```
All tasks complete! Review the final state:
- Task list: agent-work/<project>-tasks.md
- Notes: agent-work/<project>-notes.md
```

## Error handling

- If a sub-agent times out or errors, report the failure and stop
- If the task list or notes file can't be found, ask the user for the correct paths
- If the prompt file references files that don't exist yet (greenfield project), note this in the sub-agent prompt so it knows to create them
