# Deterministic Task Verification

Task completion is verified by the runner, not self-reported by agents.
Agents propose completion; the framework verifies evidence before marking done.

**Read `reference/proof-discipline.md` FIRST.** It explains the substrate: claims are advertising, artifacts are state, and the verifier reads state. This file describes the runner-side mechanism that enforces proof-discipline at task and phase boundaries.

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

At phase boundaries, the runner spawns a read-only verification agent. Its prompt is **adversarial by default** — it is instructed to assume the previous agent lied and to find the lie. See `reference/proof-discipline.md` rule #7 for the exact opener.

The agent:

1. Has no Write/Edit tools — can only read and report
2. Receives **only** the substrate: task descriptions from `tasks.md`, the git diff, and the paths to proof artifacts under `test-logs/`. It does **NOT** receive any of:
   - prior `completion-<task_id>.json` files (they describe agent intent, not state)
   - prior `validate/<phase>/<N>.md` records (they describe prior agent reasoning, which the verifier MUST re-derive)
   - integration agents' commit messages (advertising, not state)
   - any markdown summary an agent wrote about their work

   The runner strips these from the verifier's prompt. See `parallel_runner.py:_verifier_prompt()` for the construction.

3. Checks each task's changes against its "Done when" criteria
4. Applies counterfactual analysis: "Would reverting this change break anything?"
5. Scans for rationalization patterns: "Partial", "environment issue", "known limitation"
6. Checks test files for vacuous assertions (`assertTrue(true)`, empty test bodies)
7. **Reads every proof artifact** under `test-logs/` produced by the phase. For each artifact:
   - If `status != "pass"`, the corresponding task is unsatisfied.
   - If `executed == 0`, the corresponding task is unsatisfied regardless of exit code.
   - If a coverage matrix gap is detectable (production routes added without matching test references), the corresponding task is unsatisfied.
8. **Writes `verification.json`** at `{spec_dir}/validate/{phase}/verification.json` with the schema in `reference/proof-discipline.md` § "verification.json schema". The record MUST contain, per task: commands actually run, raw output excerpts (not summaries), artifacts inspected with key fields read, verdict, evidence, and `lie_check` explaining what the verifier looked for to detect a lie and what it found.

The runner parses the verdict. Any task flagged as `unsatisfied` is unmarked and queued for rework. A `verification.json` missing `commands_run`, `artifacts_inspected`, or `lie_check` per task is itself a vacuous artifact — the runner rejects it and re-spawns the verifier.

This agent is false-negative-averse: rejecting good work ($2-5 retry cost) is far cheaper than accepting bad work (hours of wasted downstream effort).

## Concrete failure patterns to look for

The May 22 belt-editor incident enumerated the failure shapes the verifier MUST detect. Each is included here as a worked example so the verifier can pattern-match:

1. **Silent skip with green claim**. Commit message says `e2e skip — all gates pass`. Proof artifact (`test-logs/e2e/run-summary.json`) shows `executed: 0, reason_if_zero: "Astro not running on http://127.0.0.1:4321"`. Verdict: UNSATISFIED. Evidence: the proof artifact directly contradicts the claim.

2. **Anchored on prior agent's claim**. The phase has 12 tasks; the integration agent's commit says "all gates pass." Without re-deriving, the verifier accepts. Verdict: VACUOUS VERIFICATION. The verifier MUST re-run the gate commands and read the proof artifacts itself.

3. **Coverage shortcut**. The spec demands four preset routes (walker/hiker/trainer/pro). The diff shows tests parametrized only over `trainer`. Verdict: UNSATISFIED on coverage. Evidence: `grep -n 'loadouts/' tests/e2e/**/*.spec.ts` returns only `trainer` references; the production code defines all four routes.

4. **Test ran with hydration disabled**. The VR test sets `javaScriptEnabled: false` to "stabilize snapshots." The phase modified hydrated components. Verdict: UNSATISFIED. Evidence: the test cannot have exercised the hydration path; the modified code is untested.

5. **Pattern-matched rule**. Specs have `expect()` calls (passes the no-vacuous-tests rule) but every `expect` targets static literals (`expect(2+2).toBe(4)`) instead of observable state. Verdict: UNSATISFIED. Evidence: no `expect` references a value returned by `page.locator(...)`, `page.evaluate(...)`, or any I/O.

These examples are the verifier's training data, not an exhaustive list. The general rule: **re-derive every claim from the substrate; when the substrate disagrees with a claim, the substrate wins**.
