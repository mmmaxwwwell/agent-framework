# Proof discipline

Every claim of "X passed" MUST be accompanied by the raw artifact that proves X executed and produced the claimed outcome. The verifier reads the artifacts, not the claims. The runner refuses to mark a phase complete if the artifacts are missing, vacuous, or contradict the claims.

This file is the canonical reference for what counts as a proof artifact, how to produce one, how the verifier consumes one, and the failure modes that motivated the discipline.

## Why this exists — the May 22 incident

In May 2026 a spec-kit run completed a 12-phase feature (`belt-editor`) with every agent reporting success. The final integration commit was titled `test(T367): final pre-PR CI gate run — all gates pass`. When the user loaded the resulting page, content appeared for one second and then disappeared. The error was an uncaught `Invalid type passed to createElement(): [object Object]` from the hydrated Preact editor island.

Reconstruction of the run revealed:

1. The project's `test:e2e` wrapper script (`run-e2e.sh`) was coded to `exit 0` when required services weren't reachable. The pre-PR gate invoked it without starting those services, so the gate reported "E2E passed" while running zero tests.
2. The integration agent's commit body literally said `e2e skip` next to `all gates pass`. The verifier accepted the commit's claim without re-reading the underlying artifact.
3. The four spec files that *did* run (visual regression) used `javaScriptEnabled: false`, sidestepping hydration entirely — exactly the surface the bug lived on.
4. Every other E2E spec was hardcoded to `/loadouts/trainer/`. The bug surfaced on `/loadouts/pro/`. No spec parametrized across the four preset routes.
5. CI ran `npx playwright test` immediately after `npm run build` with no `astro preview` server started — every spec that did `page.goto` would have hit connection-refused, but the run was never inspected for that signal.

Every individual rule already on the books — no vacuous tests, behavioral testing, zero-skips, coverage proof — was satisfied by the *artifacts* the agents produced. The bug landed because the artifacts described work that did not happen. The rules audited form; nothing audited the substrate.

The proof-discipline rules below name the substrate as the load-bearing thing. An agent can satisfy every adjacent rule and still fail proof discipline if its proof artifact shows zero work or contradicts the claim. There is no skill-level fix for the failure modes above other than this: claims are advertising, artifacts are state. The verifier reads state.

## Rules

### 1. Every step that gates a phase MUST produce a proof artifact

A step gates a phase iff (a) its failure should block phase completion, and (b) the runner reads its outcome programmatically. Examples in scope: build, unit tests, integration tests, E2E tests, lint, type-check, security scan, size check, link check, preflight tool check.

For each such step, the project's runner/wrapper MUST write a single JSON artifact at a stable path. The artifact MUST contain:

- `status: "pass" | "fail" | "empty"` — "empty" is when the step ran zero work units (zero tests collected, zero files scanned, zero builds attempted). `empty` is **always** a failure for gating purposes.
- `executed: number` — count of the work units actually run.
- `passed: number`, `failed: number`, `skipped: number` — break down `executed` (skipped is not part of executed; it counts separately).
- `reason_if_zero: string` — empty when `executed > 0`; otherwise the exact reason the runner ran nothing (`"Astro not running"`, `"testMatch matched 0 files"`, `"--grep filter excluded all tests"`).
- Any step-specific fields needed for cross-checks (e.g. expected spec count for E2E, expected build outputs for build, byte sizes for size-check).

The artifact MUST be emitted **unconditionally** — including when the step short-circuits, when a precondition fails, and when the step does no work. The artifact is the contract between the step and the verifier; if it isn't written, the verifier MUST assume the step failed.

### 2. Skip without a runs-in-the-gate replacement = FAIL

A wrapper script that exits 0 because a precondition was missing is a silent skip. Silent skips are the failure mode that produced the May 22 incident. They are banned in gated steps without exception.

The correct behavior when a precondition is missing:

- **In CI or under a gate**: fail loudly. Either start the required service yourself (preferred — Playwright's `webServer` block, `process-compose up -d`, a Make target) or exit non-zero with a precise message naming the missing precondition.
- **In interactive dev**: an opt-in `--allow-skip` flag MAY allow exit 0. This flag MUST be ignored when `CI=1` or when the wrapper is called from `pre-pr`. The artifact MUST still be emitted with `status: "empty"`.

The verifier reads `status: "empty"` as a failure regardless of exit code. Exit code is necessary but not sufficient for "pass."

### 3. Proof artifact MUST be cross-checkable

For every gated step where the universe of expected work units is knowable (number of test files, number of build targets, number of badges), the runner MUST capture the expected count to a separate file at config-load time, and the verifier MUST cross-check `executed >= expected` (or `executed == expected` where exact equality is required).

Concrete forms:

- **Playwright**: emit `test-logs/e2e/expected-spec-count.txt` containing `find tests/e2e -name '*.spec.ts' | wc -l` at config-load time. The post-run verifier rejects the run if `executed < expected_count` — that means a filter excluded specs.
- **Build outputs**: a project that builds N artifacts MUST verify all N exist after the build step. A build that succeeds but produces M < N artifacts is FAIL.
- **CI badges**: a README with N badges MUST verify all N return 200 with valid content.

A step whose universe of expected work units is genuinely unknowable (an open-ended grep, a discovery scan) is exempt from the cross-check but MUST still emit `executed > 0`.

### 4. Build artifacts MUST be cross-checked against package manifest

Build steps that produce installable artifacts (npm package, AAR, APK, vsix, container image, Nix package) MUST verify the artifact contains real implementation code by:

1. Listing the artifact contents (`jar tf`, `unzip -l`, `tar tzf`, `nm -D`).
2. Confirming expected entries are present (native libraries, compiled classes, asset files).
3. Confirming file size is non-trivial. A `.so` of <10KB is almost certainly a stub.
4. Exercising at least one cross-language code path if the artifact crosses a language boundary.

This is already covered in `phases/implement.md` § "Cross-language artifact verification." Repeated here because it is a form of proof discipline: the artifact-shape check IS the proof.

### 5. Coverage matrix MUST be in the verification record

Every phase that exposes a user-visible surface MUST produce a coverage matrix listing every route / screen / feature that was modified or added in that phase, and naming the test that exercises each. A route in the matrix without a test is FAIL.

The verifier checks the matrix mechanically: parse the diff for new/modified route definitions, parse the test diff for `page.goto(...)` strings, and assert every route in the first set appears in the second set.

If a phase adds routes A, B, C, D and only test files for A exist, the verifier flags B, C, D as coverage gaps and the phase is FAIL. This is the mechanical version of "we only tested trainer, not pro."

### 6. Verifier reads artifacts, NOT claims

The independent verification agent's input MUST NOT include:

- The previous agent's `completion-<task_id>.json` (it describes intent, not state).
- The integration agent's commit messages (advertising, not state).
- Any markdown the agent wrote summarizing its work.
- Prior `validate/<phase>/N.md` records describing past attempts.

The verifier's input MUST include:

- The task spec from `tasks.md` (what was demanded).
- The git diff for the phase (what was actually changed).
- The proof artifacts on disk (what actually ran).
- The ability to re-execute commands (so claims about exit codes can be re-derived).

When the runner spawns the verifier, the runner strips the agent-authored summaries from the prompt and passes only the substrate. The verifier reconstructs state from artifacts every time.

### 7. Verifier prompt MUST be adversarial

The verifier's opening instruction MUST frame the task as finding the lie, not confirming the claim. Concretely:

> You are looking for the case where a previous agent claimed success without doing the work. Assume that case. Find the evidence. The previous agents' completion claims are NOT available to you — you must derive state from artifacts and code alone. Specific failure patterns to look for:
>
> - **Silent skip**: a wrapper script that exited 0 because a precondition was missing. Look at the proof JSON's `executed` and `reason_if_zero` fields; if `executed == 0`, this is FAIL regardless of exit code.
> - **Anchored claim**: a result that seems plausible because a previous agent said so. Re-derive every claim from the artifact, not from any text.
> - **Pattern-matched rule satisfaction**: tests that exist but don't run, tests that run but don't assert, tests that assert but on irrelevant surfaces. Verify by running the tests and reading what executed, not by reading the file.
> - **Coverage shortcut**: tests parametrized over one representative case when the user clearly needs all cases. Read the route set from the diff and the test set from the test files; the latter MUST cover the former.
>
> When the artifact and the claim disagree, the artifact wins.

The verifier MUST output a `verification.json` with: commands it ran, raw output excerpts (not summaries), and yes/no per task on whether the artifact matches the demand.

### 8. verification.json schema

```json
{
  "phase": "phase12-polish-docs-and-release",
  "verifier_version": "1.0",
  "timestamp": "ISO-8601",
  "tasks_verified": [
    {
      "task_id": "T367",
      "demand_summary": "what tasks.md asked for, in the verifier's own words",
      "commands_run": [
        {"command": "...", "exit_code": 0, "stdout_excerpt": "..."},
        ...
      ],
      "artifacts_inspected": [
        {"path": "test-logs/e2e/run-summary.json", "key_fields": {"status": "pass", "executed": 29}},
        ...
      ],
      "verdict": "satisfied | unsatisfied | inconclusive",
      "evidence": "concrete evidence supporting verdict — file paths, line numbers, output excerpts",
      "lie_check": "what the verifier looked for to detect a lie, and what it found"
    }
  ],
  "overall_verdict": "pass | fail",
  "blocking_failures": ["task IDs whose verdict was unsatisfied"]
}
```

A `verification.json` without `commands_run`, `artifacts_inspected`, or `lie_check` per task is itself a vacuous artifact. The runner rejects vacuous verification records and re-spawns the verifier with a stronger prompt.

### 9. The runner refuses phases where any proof artifact says executed: 0

After every phase the runner reads every proof artifact under `test-logs/` and rejects the phase if any has `executed == 0` AND the diff modifies code that that proof was supposed to cover. The mapping is by file extension (e.g. `tests/e2e/**/*.spec.ts` exists → `test-logs/e2e/run-summary.json` must have `executed > 0`).

The runner does NOT trust the agent's claim that "the proof is fine"; it reads the JSON.

## Concrete patterns to emit/consume

### Emitting a proof artifact (shell)

```bash
emit_proof() {
  python3 -c "
import json, sys
json.dump({
  'status': sys.argv[1],
  'reason_if_zero': sys.argv[2],
  'executed': int(sys.argv[3]),
  'passed': int(sys.argv[4]),
  'failed': int(sys.argv[5]),
  'skipped': int(sys.argv[6]),
}, open(sys.argv[7],'w'), indent=2)
" "$@"
}
```

### Emitting a proof artifact (Node)

```javascript
import { writeFileSync } from "node:fs";
writeFileSync(
  proofPath,
  JSON.stringify({
    status, reason_if_zero: reason, executed, passed, failed, skipped,
  }, null, 2),
);
```

### Consuming a proof artifact (Python — runner side)

```python
import json, pathlib

def assert_proof_valid(path: pathlib.Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"proof artifact missing: {path}"
    data = json.loads(path.read_text())
    if data.get("status") != "pass":
        return False, f"status={data.get('status')}: {data.get('reason_if_zero','')}"
    if data.get("executed", 0) == 0:
        return False, f"executed=0: {data.get('reason_if_zero','')}"
    return True, ""
```

## Cross-references

- `reference/validate-review.md` — Part 1 (validation) must check every proof artifact before writing PASS.
- `reference/verification.md` — the per-task verifier is the runner-side checker described in rule #6.
- `reference/e2e-failure-patterns.md` — many of the failure patterns there are special cases of "the proof artifact lied."
- `phases/implement.md` § "Validation coverage proof" — the existing coverage-proof rule is consonant with rule #5; this file generalizes it.
