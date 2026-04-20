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

3. **Read the task list** — Parse the task list to identify incomplete tasks (`- [ ]`). Skip blocked (`- [?]`) and completed (`- [x]`) tasks. For each incomplete task, also parse its header line for a `[needs: X, Y, Z]` tag (comma-separated list of dependency names); this drives the **Dependency resolution** step below. Tasks with no `[needs:]` tag skip that path entirely.

4. **Load the dependency registry** — If `.claude/task-deps.json` exists in the project root, read it once and cache it for the whole run. If it does not exist, any `[needs:]` tag the runner encounters is treated as unknown (warn and proceed — see Dependency resolution). Do not fail the run for a missing registry; it is opt-in.

5. **Detect project stack** — Before executing any tasks, determine the project's tech stack so the review gate (if enabled) can select the right code-review variant. Spawn a quick research sub-agent (model: "haiku") to check for `package.json`, framework imports, and file extensions, then return one of: `react`, `node`, or `generic`. Cache the result — do not re-detect per task.

6. **Tag the pre-task state** — Before each task sub-agent runs, record the current git commit SHA: run `git rev-parse HEAD` and store it as `pre_task_sha`. This is the baseline for the review gate's diff.

7. **Start registered dependencies** — If the task has a `[needs:]` tag, resolve each listed dep via the registry, verify prereqs, run each registered `start` script, and capture any JSON output. See **Dependency resolution** for the full contract. Keep the captured start-output keyed by tag name so it can be threaded into the sub-agent prompt and preserved across the per-task fix loop.

8. **Execute tasks sequentially** — For each incomplete task, spawn an Opus sub-agent using the Agent tool with `model: "opus"`. The sub-agent does ALL the heavy reading and work. If the task has deps with non-null start scripts, include a **Live dependencies** section in the prompt (see template below) listing each tag plus the fields captured from the start script's JSON output.

9. **On sub-agent failure, run the per-task fix loop** — If the sub-agent reports failure (build/test broken, validation failed, "Done when" criteria not satisfied), run the **Per-task fix loop** (see below) up to 10 total iterations. Deps stay live across iterations; do not stop+restart between iterations unless the loop explicitly requests it. If the loop exhausts its budget, mark the task `[blocked]` (`- [?]`) with a written summary and move on.

10. **Stop registered dependencies** — After the sub-agent completes (success OR failure, including after the fix loop terminates for any reason), run each resolved dep's `stop` script. This is cleanup; it MUST run. Log stop-script failures but do not propagate them to task status.

11. **Between tasks** — After each sub-agent completes and deps are stopped:
    - Re-read the task list only (the sub-agent may have updated it)
    - If a task was marked `[?]` (blocked), stop and ask the user for input
    - If the sub-agent reports a build/test failure it couldn't resolve AND the per-task fix loop didn't cover it (e.g. it was a bare build failure outside a `[needs:]` task), try the **fix-build escalation** (see below) before giving up
    - If the review gate is enabled, run the **review gate** (see below) before reporting progress
    - Report progress to the user

12. **Continue until done** — Keep dispatching until all tasks are complete, one is blocked, or a failure occurs.

## Dependency resolution

Tasks can declare runtime dependencies via a `[needs: X, Y, Z]` tag in the task header line, e.g.:

```
- [ ] T096 Wire Stripe webhook secret propagation [needs: stripe-listen, e2e-loop]
```

Each name resolves through the project's `.claude/task-deps.json` registry. The runner starts each resolved dep before dispatching the task sub-agent, threads any structured output into the sub-agent prompt, and stops the dep afterward.

### Registry schema (`.claude/task-deps.json`)

The registry lives at the repo root. Top-level shape:

```json
{
  "version": 1,
  "deps": {
    "<tag-name>": {
      "description": "human-readable one-liner",
      "start": "path/to/start.sh",          // or null for no-op
      "stop":  "path/to/stop.sh",           // or null for no-op
      "prereqs": ["things that must be true", "..."],
      "start_output_format": "json",        // optional: "json" | "text" | omitted
      "start_output_schema": { "pid": "number", "secret": "string", ... },
      "post_start_requires_api_restart": true,  // optional
      "post_start_notes": "free-form guidance surfaced to the sub-agent"
    }
  }
}
```

A reference registry lives at `.claude/task-deps.json` in the kanix repo (tag names: `stripe-listen`, `mcp-browser`, `mcp-android`, `e2e-loop`).

### Contract for start/stop scripts

Any script referenced from the registry MUST obey:

- **start**: idempotent (reusing a live instance is fine), exits 0 on success. If `start_output_format == "json"`, print a single JSON object on stdout matching the declared schema (e.g. `{"pid": 12345, "secret": "whsec_...", "forward_to": "localhost:3000/webhooks/stripe", "log": "/path/to/log", "reused": false}`). Non-zero exit means the dep is unavailable — fail the task's dispatch with a clear error.
- **stop**: safe no-op if nothing is running, exits 0. The runner invokes stop even if the task errored.

### Resolution flow (per task)

1. **Parse the task header** for `[needs: ...]`. Split on commas, trim whitespace. Empty or missing tag → skip dep resolution entirely (backward compatible).
2. **Look up each tag** in the cached registry.
   - Unknown tag → log `warning: [needs: <tag>] not found in .claude/task-deps.json; proceeding without it` and continue. Do not block the task.
   - Tag found but `start == null` → treat as a documentation-only dep; record its prereqs/notes but do not run anything.
3. **Verify prereqs** before running start. For each string in `prereqs`, the runner cannot mechanically check arbitrary natural-language prereqs — instead, include them verbatim in the sub-agent prompt's **Live dependencies** section as expectations the sub-agent must assume true. If a start script itself checks prereqs and fails (exit non-zero), that surfaces as a fail-fast error.
4. **Run start**. Execute via Bash, capture stdout + exit code.
   - Non-zero exit → abort this task, mark `[?]` with the error summary, run the stop scripts for any deps already started, and move on.
   - Exit 0 with `start_output_format: "json"` → parse stdout as JSON; if parse fails, log a warning and treat start_output as `{}`.
5. **Post-start hook**. If the dep has `post_start_requires_api_restart: true`, the runner does not itself manage the API (the project's dev orchestration owns that), so the sub-agent prompt MUST include an explicit instruction: "The <tag> dep was (re)started; ensure the API has loaded the latest .env before proceeding (e.g., restart `pnpm dev` or the equivalent) and wait for it to be healthy."
6. **Dispatch the task sub-agent**, threading the captured start_output per tag into the **Live dependencies** section of the prompt.
7. **After the task finishes** (success, failure, or fix-loop exhaustion), run stop for each started dep, in reverse start order. Capture exit codes but never fail the task on stop errors; log them and continue.

### Threading start-output into sub-agent prompts

For every tag whose start script produced JSON, include a block like this in the **Live dependencies** section (see the updated sub-agent template below):

```
- stripe-listen: pid=12345 secret=whsec_ABC forward_to=localhost:3000/webhooks/stripe log=/abs/path/.dev/stripe-listen.log reused=false
  post_start_notes: API must be (re)started after start so it reads the new STRIPE_WEBHOOK_SECRET from .env
  prereqs (assumed true): stripe CLI must be on PATH (nix develop); stripe login completed; root .env has STRIPE_SECRET_KEY set
```

Sub-agents then have everything they need (URLs, secrets already written, PIDs for debugging) without having to call the start script themselves.

## Per-task fix loop

When a task sub-agent reports failure — build/test broken, validation failed, or "Done when" criteria not met — the runner enters a bounded fix loop before giving up. The loop runs at most **10 iterations** per task and preserves any live `[needs:]` deps across iterations.

### Structure of one iteration

Each iteration spawns a single `evaluate-research-fix-validate` sub-agent (`model: "opus"`) that internally performs all four phases and reports back. This keeps the orchestrator lightweight (it does not itself read code or logs) and lets the sub-agent amortize project-context reads across phases.

The sub-agent's mandate per iteration:

1. **Evaluate** — read the failing sub-agent's final message and the task definition from the task list; identify the concrete failure mode.
2. **Research** — read the relevant code, recent logs (`.dev/*.log`, test output files), and any artifact the previous sub-agent referenced. Find the root cause.
3. **Fix** — apply the minimal change required. For larger fixes, the sub-agent MAY itself spawn a child Opus sub-agent via the Agent tool, but must wait on the child and integrate its result.
4. **Validate** — re-run the task's validation (tests, the "Done when" / acceptance criteria from the task header, any commands referenced in the task body). If validation passes cleanly, mark the task `- [x]` in the task list and return `PASS` plus a one-paragraph summary. If it still fails, return `FAIL` with a crisp error summary and whatever diagnostics it collected — the orchestrator will feed those into the next iteration.

### Loop control

- **Cap**: 10 total iterations per task (attempt 1 = original sub-agent dispatch; attempts 2-10 = fix-loop iterations).
- **Deps**: live deps from the `[needs:]` tag stay running across iterations. Do NOT stop and restart them between iterations — it wastes time and can churn webhook secrets / PIDs.
- **Dep restart opt-in**: a fix-loop sub-agent CAN request a dep restart by returning `RESTART_DEP: <tag>` on its own line at the end of its response. The orchestrator then runs that dep's stop followed by its start, re-captures the JSON output, and threads the fresh values into the next iteration's prompt. Use sparingly (e.g. secrets rotated, listener crashed).
- **Exit conditions**:
  - `PASS` from an iteration → task complete; exit loop and proceed to the review gate.
  - 10 iterations with no `PASS` → mark the task `- [?]` with a written summary of what was tried (one bullet per iteration: what failed, what was attempted, what error remained). Log the blocker to the notes file. Move on to the next task.
  - Hard error (sub-agent crashed, Agent tool returned an exception) → do not count against the 10; retry once, then mark `[?]` with the error.

### Fix-loop sub-agent prompt template

```
You are running iteration <N>/10 of the per-task fix loop for an agent-framework task.
A previous sub-agent tried to execute this task and reported failure. Your job is to
evaluate → research → fix → validate in one pass, then report PASS or FAIL.

Read these files for project context:
- Prompt file (project spec): <prompt file path>
- Task list: <task list path>
- Notes & context: <notes file path>

## Task
<the specific task description, including any "Done when" / acceptance criteria>

## Previous failure
<prior sub-agent's final message, verbatim; include the specific command(s) that failed
and any error output they surfaced>

## Prior fix-loop iterations (if N > 1)
<one bullet per prior iteration: what was tried, what error remained>

## Live dependencies
<same Live dependencies block as the original task sub-agent; same live values>

## Your process
1. Evaluate: identify the concrete failure mode from the previous output.
2. Research: read relevant code, logs, and test output to find the root cause.
3. Fix: apply the minimal change. You MAY spawn a child sub-agent via the Agent tool
   for a larger fix; wait for it and integrate its result.
4. Validate: re-run the task's validation (tests, "Done when" criteria, commands
   referenced in the task). Run commands to completion — do not skip or time out.

## Rules
- Do NOT stop the live dependencies. They are managed by the orchestrator.
- If you need a dependency restarted, end your response with a single line:
  RESTART_DEP: <tag-name>
- Make minimal, targeted fixes. Do not refactor unrelated code.
- Test your work before reporting PASS.

## Required response shape
On success, end with exactly:
  RESULT: PASS
  <one-paragraph summary of what you changed and why it now passes>

On failure, end with exactly:
  RESULT: FAIL
  <one-paragraph summary of the remaining error and what you tried>
```

### Blocked-task summary format

When the 10-iteration budget is exhausted, update the task list entry like so:

```
- [?] T096 Wire Stripe webhook secret propagation [needs: stripe-listen, e2e-loop]
  Blocked after 10 fix-loop iterations:
    1. <what failed / what was tried / residual error>
    2. ...
   10. <final residual error>
  See notes for full logs.
```

Append the full per-iteration transcript summary to the notes file too.

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

## Live dependencies
<OMIT this section entirely if the task has no [needs:] tag or all its deps have null start scripts>
<For each dep with a non-null start script that the orchestrator launched for you, include:>
- <tag>: <space-separated key=value pairs from the start script's JSON output>
  post_start_notes: <registry post_start_notes, if present>
  prereqs (assumed true): <semicolon-joined prereqs from the registry>

<If ANY dep has post_start_requires_api_restart: true, also include:>
IMPORTANT: The <tag> dep was (re)started and may have written new values (e.g. secrets)
to .env. Ensure the API has loaded the latest .env before proceeding — restart
`pnpm dev` (or the project's equivalent dev command) and wait for it to be healthy
before running anything that depends on the dep.

<Always include this closing line if the section is present:>
The orchestrator will run each dep's stop script after you finish. Do NOT stop them yourself.

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
- If a build or test command fails and you cannot fix it, report the exact command that failed and the error summary in your final response so the orchestrator can escalate to fix-build or the per-task fix loop.
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
  Deps: stripe-listen (started, stopped), e2e-loop (doc-only)   # omit line if no [needs:] tag
  Fix loop: passed on iteration 3/10                            # omit line if task passed on first try
  Summary: <sub-agent's result summary>
  Review: No issues found (or: Fixed 1 P0, 1 P1 in 1 round)
  Next: "Build X service layer"
```

If the review gate is disabled, omit the Review line. If the task was blocked after the fix loop:

```
[2/14] Blocked: "Wire webhook secret propagation"
  Deps: stripe-listen (started, stopped)
  Fix loop: exhausted 10/10 iterations
  Residual error: <one-line summary>
  See: task list entry + notes file for full transcript.
```

If all tasks complete:
```
All tasks complete! Review the final state:
- Task list: agent-work/<project>-tasks.md
- Notes: agent-work/<project>-notes.md
```

## Error handling

- If a sub-agent errors (not a timeout), report the failure and stop. Use generous timeouts (up to 10 minutes) for sub-agents — builds can be slow and that's expected. Before stopping, run the `stop` script for every live dep started for the current task — teardown must happen even on orchestrator error.
- If the task list or notes file can't be found, ask the user for the correct paths.
- If the prompt file references files that don't exist yet (greenfield project), note this in the sub-agent prompt so it knows to create them.
- If `.claude/task-deps.json` is malformed (invalid JSON, version mismatch), log a clear error and skip dep resolution for the whole run (tasks with `[needs:]` tags proceed without their deps, which will likely fail and land in the fix loop — that's acceptable, but make the registry error visible in the first progress report).
- If a `start` script fails its prereqs or exits non-zero, do NOT dispatch the task sub-agent. Mark the task `- [?]` with the failing command + error output, run stop for any deps already started in this task, and move on.
