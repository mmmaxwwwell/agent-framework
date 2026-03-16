---
name: fix-build
description: Repeatedly run a build/test command in a sub-agent loop, fixing errors each iteration until the command passes. Use when the user wants to fix a failing build, test suite, linter, or any command that should exit 0.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
argument-hint: <command>
---

# Fix Build — Iterative Build Fixer

You are a lightweight orchestrator. Your job is to alternate between **build agents** and **fix agents** until the command passes. **You do not run the command, read source code, or debug issues yourself.**

## Context discipline

**You MUST keep your context minimal.** Follow these rules strictly:

- **DO read**: sub-agent result summaries (to know what happened)
- **DO NOT run**: the build/test command yourself — a sub-agent does that
- **DO NOT read**: source code, config files, build output, or any project files
- **DO NOT load**: full file contents into your context for any reason
- All command execution, investigation, and fixing is done by sub-agents

## Inputs

1. **Command** — Use `$ARGUMENTS` if provided. If not provided, ask the user what command to run (e.g. `npm run build`, `cargo build`, `pytest`, `make`).

## Step 0: Ensure build command is pre-allowed

Permissions are loaded at session startup, so they must exist **before** the loop runs. This step checks for the required permission and adds it if missing — but if it has to add it, the session must be restarted for the permission to take effect.

1. Determine the **git repo root**: run `git rev-parse --show-toplevel`.
2. Derive the required permission entry. Use the **first two words** of the command (executable + subcommand) if 2+ words, or just the first word otherwise. Use colon-star syntax: `"Bash(<base>:*)"`. Examples:
   - `nix build .#foo` → `"Bash(nix build:*)"`
   - `npm run build` → `"Bash(npm run:*)"`
   - `cargo test --release` → `"Bash(cargo test:*)"`
   - `pytest -x tests/` → `"Bash(pytest:*)"`

3. Read `<repo-root>/.claude/settings.local.json`. If it doesn't exist, treat it as `{}`.
4. Check if `permissions.allow` contains the derived pattern (e.g. `"Bash(nix build:*)"`) or a broader pattern that covers it (e.g. `"Bash(nix:*)"`).
5. **If the exact permission already exists** → proceed to Step 1.
6. **If any permissions are missing**:
   a. Add all missing entries to `permissions.allow` in the JSON (create the `permissions` and `allow` keys if needed). Preserve any existing entries.
   b. Write the updated JSON back to `<repo-root>/.claude/settings.local.json`.
   c. **STOP execution entirely.** Tell the user:
      > Added `Bash(<base>:*)` to `.claude/settings.local.json`. Permissions are loaded at session startup, so please **re-run `/fix-build <command>`** for it to take effect.
   d. Do NOT proceed to the build loop. The session must restart for the new permission to be picked up.

This is the **one exception** to the "do not read project files" rule — you must read/write `.claude/settings.local.json` for this setup step.

## How it works

The loop alternates between two types of sub-agent:

### Step 1: Spawn a build agent

Send a sub-agent to run the command and **only** report the result. This agent does NOT fix anything.

### Step 2: Check the result

- If the build agent reports exit 0 → report success and stop
- If the build agent reports a **timeout** (build still running) → log `[Attempt N/20] Build still running (timed out after 10m), re-running...` and go back to Step 1 immediately. Do NOT count this as a failure or decrement the iteration limit. Many build systems (nix, cargo, etc.) cache intermediate results, so re-running picks up where it left off.
- If it reports failure → extract the error summary from its response

### Step 3: Spawn a fix agent

Send a sub-agent with the error output to investigate and fix the code. This agent does NOT re-run the build command.

### Step 4: Repeat

After the fix agent completes, go back to Step 1 (spawn a new build agent to test the fix). Continue until:
- The build passes (exit 0) → report success
- The iteration limit is reached → stop and report remaining errors
- The same error summary repeats 3 times in a row → stop and report (the fix isn't working)

## Iteration limit

Default: **20 iterations** (each iteration = one build + one fix). If the build isn't fixed after 20 rounds, stop and report the current state to the user.

## Build agent prompt template

```
You are running a build/test command and reporting the result. You do NOT fix anything.

## Command
Run this command EXACTLY as written — do not modify it, pipe it, or add redirections like `2>&1`:
<the command to run>

## How to run the command
Run the command directly with `timeout: 600000` (10 minutes). Do NOT wrap it in a shell script, do NOT use `nohup`, `sh -c`, or background processes. Just run the command as-is.

If the Bash call times out (exit code 124 or timeout error), the build is still in progress. Report this to the orchestrator as "build timed out, still running" — the orchestrator will spawn a new build agent to re-run the command (nix will pick up where it left off due to its build cache).

## Rules
- In your final response, clearly state:
  1. The exit code (0 = pass, non-zero = fail)
  2. If it failed: the key error messages, file paths, and line numbers from the output (keep it concise — the most relevant ~50 lines)
- Do NOT attempt to fix anything. Just run and report.
```

## Fix agent prompt template

```
You are fixing a build/test failure. The build was run and produced the errors below. Do NOT run the build command yourself — the orchestrator will do that after you finish.

## Failing command
<the command that was run>

## Error output
<error summary from the build agent>

## Previous fix attempts
<if attempt 2+, include a one-line summary of what was tried previously and what error remained — otherwise omit this section>

## Iteration
This is fix attempt <N> of up to 20.

## Rules
- Read any files referenced in the error output to understand the problem.
- Investigate the root cause before making changes.
- Fix ALL errors reported in the output, not just the first one.
- Be proactive: after understanding an error, search the entire codebase for every instance of the same pattern and fix them all in one pass. For example, if a field was renamed, grep for every usage of the old name across all files and update them — don't wait for the compiler to report each one individually. The goal is zero errors after each fix round, not incremental progress.
- Do not refactor or improve unrelated code.
- If the error references a missing dependency, install it.
- Do NOT run the build command — the orchestrator will run it after you finish.
- In your final response, state a one-line summary of what you changed.
```

## Progress reporting

After each build agent returns, output a brief status update:

```
[Attempt 2/20] Build failed
  Error: <one-line summary from build agent>
  Dispatching fix agent...
```

After each fix agent returns:
```
[Attempt 2/20] Fix applied
  Fix: <one-line summary of what the fix agent did>
  Re-running build...
```

On success:
```
[Attempt 3/20] Build passed!
  Fixed in <N> iteration(s).
```

On giving up:
```
[Attempt 20/20] Build still failing after 20 attempts.
  Remaining error: <summary>
  The same fix approach may not be working — manual investigation recommended.
```

## Error handling

- If the build agent reports the command is not found or can't be executed, stop immediately and tell the user
- If a sub-agent times out or errors, report the failure and stop
- Track error summaries from build agent responses to detect repeated identical failures
