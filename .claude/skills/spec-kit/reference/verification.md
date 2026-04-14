# Deterministic Task Verification

Task completion is verified by the runner, not self-reported by agents.
Agents propose completion; the framework verifies evidence before marking done.

## Why

LLM agents rationalize failures. They call fixable problems "environment issues,"
mark tasks done with "Partial" results, fall back to code review when live
validation is required, and write findings as "blocked" to avoid detection.
Prompt-based rules don't fix this — agents find new rationalizations.

Deterministic verification moves enforcement from the agent's reasoning to the
runner's Python code, where it cannot be overridden.

## Completion claim format

Agents write a JSON file instead of editing tasks.md checkboxes:

```
{spec_dir}/claims/completion-{task_id}.json
```

Schema:

```json
{
  "task_id": "T302",
  "status": "complete",
  "summary": "One-line description of what was done",
  "commands_run": [
    {"command": "make validate", "exit_code": 0},
    {"command": "./gradlew connectedDebugAndroidTest", "exit_code": 0}
  ],
  "files_created": [
    "android/app/src/androidTest/java/com/nixkey/e2e/regression/FooTest.kt"
  ],
  "files_modified": [
    "android/app/src/main/java/com/nixkey/ui/screens/KeyDetailScreen.kt"
  ],
  "screenshots": [
    "specs/003-comprehensive-e2e/validate/e2e/screenshots/T302-auth-screen.png"
  ],
  "mcp_interactions": 14
}
```

The runner reads the claim and verifies each field independently:
- `commands_run`: re-executes the commands; exit codes must match
- `files_created`: checks files exist on disk
- `screenshots`: checks files exist on disk (for MCP tasks)
- `mcp_interactions`: must be > 0 for `[needs: mcp-*]` tasks

## Verification rules by task type

### MCP exploration tasks (`[needs: mcp-android]`, `[needs: mcp-browser]`, etc.)

1. At least one screenshot must exist in the claim
2. `mcp_interactions` must be > 0
3. If the task's findings have zero live evidence, FAIL (MCP engagement check)

### Tasks with explicit verify commands (`**Verify**: ...`)

The runner extracts the command from the `**Verify**:` field in the task
description and executes it. Exit code 0 = pass. Non-zero = fail.

### Scripted tasks (e.g., "Add scenario to test script")

If the task description references a script path, the runner executes it
after the agent finishes. Syntax checking (`bash -n`) is not sufficient.

### Standard implementation tasks

1. If the agent reported `commands_run`, the runner re-executes them
2. If `files_created` lists test files (`*Test*`, `*_test*`, `test_*`),
   the runner runs the relevant test suite

## Runner-only completion

The agent MUST NOT edit tasks.md checkboxes. The runner:

1. Detects that an agent exited (process poll)
2. Reads `completion-{task_id}.json` if it exists
3. Runs type-specific verification
4. If verification passes: calls `_mark_task_done()` (writes `[x]`)
5. If verification fails: writes `rejection-{task_id}.md` with the reason,
   leaves task as `[ ]`, increments attempt count

If an agent writes `[x]` directly (legacy behavior), the runner reverts it
to `[ ]` and runs verification anyway. If verification passes, it re-marks
`[x]`. This is backwards-compatible but strictly more conservative.

## Independent verification agent

At phase boundaries, the runner spawns a read-only verification agent that:

1. Has no Write/Edit tools — can only read and report
2. Checks each task's changes against its "Done when" criteria
3. Applies counterfactual analysis: "Would reverting this change break anything?"
4. Scans for rationalization patterns: "Partial", "environment issue", "known limitation"
5. Checks test files for vacuous assertions (`assertTrue(true)`, empty test bodies)
6. Writes a structured verdict to `{spec_dir}/validate/{phase}/verifier.json`

The runner parses the verdict. Any task flagged as incomplete or rationalized
is unmarked and queued for rework.

This agent is false-negative-averse: rejecting good work ($2-5 retry cost) is
far cheaper than accepting bad work (hours of wasted downstream effort).
