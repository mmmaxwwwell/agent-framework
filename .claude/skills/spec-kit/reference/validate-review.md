# Validate & Review — shared reference

This file holds the mandatory rules for phase-boundary validation and code review. Both the validate agent (Part 1) and the review agent (Part 2) MUST read this file before acting — the per-spawn prompt splices in only the phase-specific context (phase name, diff range, cycle #) and references this document for the rules.

This file lives at a stable path (`reference/validate-review.md`), so every spawn's Read of it hits the prompt cache.

## Part 1: Validate — four-step sequence

Run these steps **in order**, stopping at the first failure category. Do NOT skip steps — every step that has a command must run.

**Step 1 — Build**: Compile/transpile the project. If there's no explicit build step, skip.

**Step 2 — Test**: Run the full test suite. Capture all output.

**Step 3 — Lint**: Run the project's linter(s) (e.g. `eslint`, `golangci-lint`, `ruff`, `clippy`). Check `CLAUDE.md`, `package.json` scripts, and `Makefile` for the lint command. If a linter is configured but not in CLAUDE.md, still run it.

**Step 4 — Security scan**: Run any security scanners configured in the project (e.g. `npm audit`, `trivy`, `semgrep`, `bandit`). Write results to `test-logs/security/`. If no scanners are configured, skip.

**Short-circuit rule**: If Step 1 (build) fails, skip Steps 2-4. If Step 2 (test) fails, still run Step 3 (lint) — lint errors are cheap to find and the fix agent can address both in one pass. Skip Step 4 (security) if build or test failed.

**Code coverage is mandatory for every test suite in the project.** If the project's test commands do not already collect coverage, fix them — add the standard coverage tool for that language/framework (every mainstream ecosystem has one) and wire it into the test command. Coverage MUST produce both terminal output and a file report in `coverage/` (JSON, XML, LCOV, or equivalent). See `reference/testing.md` § Code coverage collection for details.

## Part 1.5: Hung-test detection

Whole-suite test invocations sometimes deadlock on a single bad test file (unawaited futures in `setUp`, platform-channel calls without mocks, coverage-collector deadlocks). Use these rules:

1. When a test suite has more than ~4 test files, **run them individually in sequence** rather than as one `<runner> test` invocation. Example (Flutter): `for f in test/*.dart; do flutter test --coverage "$f" > "logs/$(basename $f).log" 2>&1 || echo "FAIL: $f"; done`. Individual runs fail fast and isolate hanging files.
2. When you must run the whole suite in background, wrap the runner in `timeout`: `timeout 600 flutter test --coverage 2>&1`. Never use `TaskOutput` with a 600s timeout on an unbounded test process — the outer runner has its own watchdog and will kill you if your background task stops making progress.
3. If a prior attempt wrote `agent-<id>-<task>-*.hang.md` in `logs/`, read it first — it identifies exactly which command hung on the previous run. Don't repeat the same invocation.
4. If any single test file hangs (no output for 60 seconds), it's a bug in that test. Record it in the FAIL output with file path and append a fix task — don't keep retrying the whole suite.

## Part 1.6: Missing-tool recovery

**Fix missing tools before reporting failure.** If a build/test command fails because a tool is not installed (e.g. `eslint: command not found`, `tsc: not found`, missing npm packages), YOU MUST install it — do not skip it or call it a "pre-existing issue":

- Missing npm package (referenced in scripts but not in devDependencies) → `npm install --save-dev <package> --ignore-scripts` to add it, then `npm rebuild <pkg>` only if native compilation needed
- Already in devDependencies but not installed → `npm install --ignore-scripts`
- Missing Python package → `uv add --dev <pkg>` or `uv sync --dev`
- Missing system tool (not an npm/pip package) → add it to `flake.nix` devShell and commit the change. The runner detects flake.nix modifications and automatically restarts inside the updated `nix develop` shell.

Then re-run the command. Only report a failure if the command fails AFTER dependencies are installed.

## Part 1.7: CI workflow verification

**If `.github/workflows/` files were modified in this phase**:

```bash
git diff <base_sha>...HEAD --name-only -- .github/workflows/
```

If any were modified:

1. Parse the modified workflow files and extract every `run:` command from added/changed steps
2. Run each command locally (e.g., `./gradlew assembleDebug`, `nix build`, `go test ...`)
3. For each `actions/upload-artifact` step, verify the `path:` file exists after the build
4. For non-vacuous verification steps (counting JUnit XML, parsing summary.json), verify the expected output files exist and contain valid data (>0 tests, >0 bytes)
5. For multi-build-system projects: verify EVERY build system produced results, not just one. A project with `go.mod` and `android/build.gradle.kts` must pass both Go and Gradle builds.

Report any missing artifacts or failed commands as FAIL (same as test failure).

## Part 1.8: Hard FAIL rules

**Early phase exception (narrow):** A phase may pass with minimal validation ONLY if it modified no source code files — meaning every changed file has an extension like `.nix`, `.yml`, `.yaml`, `.toml`, `.json`, `.md`, `.lock`, `Makefile`, `.envrc`, or `.gitignore`. If the phase changed ANY source code (`.go`, `.kt`, `.java`, `.ts`, `.tsx`, `.js`, `.py`, `.rs`, `.c`, `.cpp`, `.swift`, etc.), the corresponding build system MUST be tested. This is a checkable condition, not a judgment call.

**Unable to validate = FAIL**: If a phase modifies source code in a build system but you cannot run that build system's tests (toolchain missing, SDK not available, emulator won't boot), that is a **FAIL**. Either fix the environment or write FAIL. A validation that only tests Go when the phase modified Kotlin is incomplete and MUST be FAIL.

**Zero test results = FAIL**: If you run a test command and it reports 0 passed, 0 failed, 0 skipped, that means the test runner found nothing to execute. This is NOT a pass — it means test discovery is broken (wrong directory, missing wrapper script, `| tee` swallowing exit codes). Zero results from a build system with changed source files is FAIL.

**Any skipped test = FAIL**: If `skip > 0` in the test summary, the phase is FAIL. No exceptions, no matter the reason. `describe.skip`, `t.Skip`, `pytest.mark.skipif`, `if (!canRun) return`, try/catch that swallows setup errors — all equivalent silent-skip loopholes. If the test didn't run, treat it as FAIL and fix it. Do NOT add more skip guards to "hide" the problem; the fix is to remove the guard and make the test run against live services. If a test physically cannot run in the target environment (iOS tests on Linux, emulator-only Android tests in a Linux-only runner), exclude it from the test list at list-building time (separate file pattern, separate npm script, CI matrix) — it must be absent, not skipped. See `reference/testing.md` § "Zero-skips rule" for the full pattern.

## Part 1.9: Stub detection (if relevant)

**If the phase implements interfaces, integrations, or external library wrappers**: Check DI modules, factory methods, and provider functions for implementations that return hardcoded values, only set boolean flags, or contain no calls to the external library they claim to wrap. Specifically:

- Grep production code (`src/main/`, `internal/`, `pkg/`, `cmd/`) for hardcoded sentinel values (e.g., `"100.100.100.100"`, `"TODO"`, `"stub"`, `"fake"`)
- If a task says "implement X using library Y," verify that library Y's package is imported AND its functions are called in production code — not just in the interface definition
- Test code (test doubles, mocks, fakes in test directories like `androidTest/`, `*_test.go`, `__tests__/`) is exempt — stubs there are expected
- A stub in production code is a FAIL, same as a test failure

## Part 1.10: Cross-boundary contract verification

**If the phase has tasks with `[produces:]`/`[consumes:]` tags, or any code where one system writes data another reads**:

For each cross-boundary seam (e.g., Nix module writes JSON that Go reads, Go server exposes API that Kotlin calls):

1. Read the producer's output format (struct JSON tags, proto field names, config keys, CLI output columns)
2. Read the consumer's input format (struct JSON tags, data class fields, parser keys)
3. Verify EVERY field name matches exactly between producer and consumer. A mismatch (e.g., Nix writes `clientCertPath` but Go reads `clientCert`) is a FAIL
4. If no integration test exercises the cross-boundary path, flag this as a coverage gap

## Part 1 output format

### If ANY step FAILS

Create `<validate_dir>/<N>.md` with:

```
# Phase <slug> — Validation #<N>: FAIL

**Date**: (current timestamp)

## Failure categories
- **Build**: PASS | FAIL | SKIPPED
- **Test**: PASS | FAIL | SKIPPED (N passed, M failed, K skipped)
- **Lint**: PASS | FAIL | SKIPPED (N errors, M warnings)
- **Security**: PASS | FAIL | SKIPPED (N findings)
- **Coverage**: COMPLETE | INCOMPLETE (list unvalidated build systems)

## Coverage proof
**Files changed**: N files
**Build systems modified**:
- [Build system]: N files changed → [command] → N passed, N failed
**Unvalidated build systems**:
- [Build system]: N files changed, NOT TESTED — [reason]

## Failed steps detail

### [Step name, e.g. "Test" or "Lint" or "Coverage"]
**Command**: (exact command run, or "N/A — toolchain unavailable" for coverage failures)
**Exit code**: (exit code)
**Root cause summary**: (1-2 sentence diagnosis — what is actually wrong, not just "tests failed")
**Failures**:
- (each distinct failure: file, line if available, what's wrong)

## Full output
(relevant portions of stdout/stderr, organized by step)
```

Fill in PASS/FAIL/SKIPPED for every category based on what you ran. Include Coverage: INCOMPLETE if any modified build system was not tested.

Do NOT modify `tasks.md` — the runner dispatches fix agents automatically. If attempt number >= 10, write `BLOCKED.md` with the full failure history. Do NOT proceed to any review step. Exit.

### If tests PASS

Before writing PASS, produce a **coverage proof**. This is mandatory — a PASS record without it is invalid.

1. Run `git diff <base_sha>...HEAD --name-only` to list all files changed in this phase.
2. Map each changed file to a build system by extension/directory (`.go` → Go, `.kt`/`.java` under `android/` → Android/Gradle, `.ts`/`.tsx`/`.js` → Node, `.py` → Python, `.rs` → Rust, `.nix` → Nix, `.yml` under `.github/workflows/` → CI).
3. For each build system with changed source files, confirm you ran its tests and got non-zero results.
4. If any build system has changed source files but was NOT tested, this is a FAIL — do not write PASS. Go back to the FAIL section above.

Write:

```
# Phase <slug> — Validation #<N>: PASS

**Date**: (current timestamp)
**Commands run**: (list every command)
**Result**: All checks passed.

## Coverage proof
**Files changed**: N files
**Build systems modified**:
- [Build system]: N files changed → [command] → N passed, N failed

**Unvalidated build systems**: None
```

If you cannot write "Unvalidated build systems: None" — if ANY modified build system was not tested — do NOT write PASS. Write FAIL instead.

## Part 2: Review — spec-conformance + test-depth + bug scan

**The review agent only runs when Part 1 wrote PASS.** The review agent's spawn is skipped entirely when the phase diff contains only trivial file types (docs, config, flake.nix, gitignore) — those phases auto-complete with REVIEW-CLEAN.

### Spec-conformance check (MANDATORY — do this BEFORE the bug scan)

Read `tasks.md` and for each task completed in this phase, cross-reference the implementation against the task description and "Done when" criteria:

1. **Exact names**: If the task says a CLI should show a `STATUS` column, verify the code uses the exact string `"STATUS"` — not `"STATE"`, `"SOURCE"`, or any synonym. Check struct field names, JSON tags, config keys, error messages, log messages, UI labels, and table column headers.
2. **All specified steps**: If the task describes a multi-step sequence (e.g., "5 log messages: initiated, stop, drain, hooks, complete"), count the steps in the implementation. If any are missing, that is a bug — fix it.
3. **Mechanism, not just behavior**: If the task says "validate using struct tags + custom validation," verify BOTH mechanisms exist. A custom-only approach that produces correct behavior is still a spec violation — the task specified the mechanism.
4. **Cross-boundary data contracts**: If the task involves one system writing data that another reads (Nix config → Go struct, Go API → Kotlin client), verify the field names match on BOTH sides. Read the producer's output format (JSON tags, proto fields) and the consumer's input format. Every key name must agree exactly.
5. **No stubs in production code**: If the task says "implement X using library Y," verify production code actually imports and calls library Y. Hardcoded return values where dynamic values are expected (e.g., returning `"100.100.100.100"` for a Tailscale IP) are stubs, not implementations — fix them.
6. **UI completeness**: If the task says "add loading states to screens X, Y, Z," verify ALL named screens have the loading state — not just some. Cross-reference the enumerated list in the task description against the actual code.

Any spec-conformance violation is a bug — fix it the same way you'd fix a null pointer or missing error check.

### Test depth audit (MANDATORY — do this BEFORE the bug scan)

Read every test file in the diff. Each of the following is a violation; fix violations by editing the test (or writing a missing one), not by waiving the rule:

1. **No skip guards of any kind.** Banned in committed code: `describe.skip`, `it.skip`, `test.skip`, `@pytest.mark.skipif`, `t.Skip(...)`, `const canRun = ...; describe = canRun ? describe : describe.skip`, `if (!svcUp) return;` inside `beforeAll` / `it` blocks, try/catch blocks in `beforeAll` that swallow setup errors and set a "gate" variable. A test that didn't run is a skip, and skips fail the build unconditionally. See `reference/testing.md` § "Zero-skips rule" for the full ban list and the correct `beforeAll(assert-deps)` replacement pattern.
2. **Correct tier placement.** A test that drives the mobile UI / browser belongs in the E2E tier (`test/e2e/` or `*.e2e.test.ts`) — not in `*.integration.test.ts`. A test that calls an API endpoint against a real DB belongs in the integration tier — not in a unit file with mocks. A test whose entire coverage comes from `vi.mock(...)` / `jest.mock(...)` of an internal module is a unit test at best and often vacuous. Miscategorized tests break the runner's gate ordering. See `reference/testing.md` § "Test tier taxonomy".
3. **Non-vacuous assertions.** Every test MUST assert specific observable behavior. Banned assertion shapes: `expect(x).toBeDefined()`, `expect(x).toBeTruthy()`, `expect(x).not.toThrow()` as the ONLY assertion, `expect(result.length).toBeGreaterThan(0)` without checking any element's content, bare `expect(typeof x).toBe("object")`. These pass when the code is broken as long as it returns *something*. Replace with concrete checks on field values, status codes, computed results.
4. **No mocking inside tier boundaries.** Integration tests must not mock the database, the auth server, or internal service-to-service calls — those are *inside* the integration boundary and mocking them defeats the point. Unit tests must not mock internal modules from the same package. Mocks are only appropriate at the *outer* edge of the tier (e.g. a unit test may mock an external HTTP client; an integration test may stub a paid third-party SaaS).
5. **Error-path coverage.** If the task adds a new endpoint, handler, or public function, the diff MUST include both a happy-path test AND at least one error-path test (invalid input, missing auth, not-found, conflict, timeout — whichever are reachable). A PR that adds a feature with only happy-path coverage is incomplete.
6. **Behavior, not implementation.** A test that asserts "function X was called with args Y" is fragile and brittle. Prefer asserting the resulting state change or externally observable response. Spy-based tests are acceptable only when there's no externally observable signal (e.g. verifying a log line was emitted, or a side-effect-only listener fired).
7. **Shared-runtime safety.** Read every integration/E2E test in the diff as if it were running concurrently alongside every sibling integration test in the repo. See `reference/testing.md` § "Shared-runtime review checks" for the full detection checklist. At minimum: flag hardcoded values that participate in uniqueness constraints (IDs, emails, slugs, topic/queue/bucket names, filesystem paths), position-based access on shared collections (`rows[0]` without a test-owned predicate), unscoped aggregates (`.length`/`COUNT(*)` without a filter on a test-owned ID), exact-equality deltas on non-owned metrics, cleanup that deletes by type/status/glob rather than by captured ID list, cross-case state dependencies within a file, literal names for shared external resources (filesystem/queue/cache), low-entropy uniqueness generators (`Date.now()` suffixes), and seed-data assumptions. These are the patterns that pass locally in isolation and fail the moment the test joins the shared-runtime suite — they cost multiple fix-validate cycles each, so fix them now, not after they blow up.

Any test-depth violation is a bug. The test is wrong until it covers real behavior. Fix the test in this review pass — do not defer to a follow-up task.

### Bug scan

After spec-conformance and test-depth, scan the ENTIRE diff systematically and find ALL issues that MUST be fixed: bugs, security vulnerabilities, correctness issues, broken error handling, missing input validation, and anything that would cause runtime failures or data loss.

**Be exhaustive in a single pass.** Each review cycle costs a full agent spawn — finding one issue per pass wastes tokens. Review every file in the diff before committing any fixes, so you have the full picture.

**Only fix things that are clearly wrong.** Do not refactor, rename, reorganize, or improve code style. Do not add tests beyond what the task specified (beyond the error-path coverage rule above — those ARE part of the task by definition). Do not add comments or documentation. The bar is: "would this cause a bug, security issue, data loss, or spec-conformance violation in production?"

### Re-run tests after fixes

If you made any code fixes, re-run the same test commands from Part 1 to verify your fixes don't break anything. If they do, fix the breakage before continuing.

## Part 2 output format

Write `<review_file>` with one of two outcomes.

**If you made fixes**:

```markdown
# Phase <slug> — Review #<cycle>: REVIEW-FIXES

**Date**: (timestamp)
**Fixes applied**:
- (list each fix: file, what was wrong, what you changed, commit SHA)

**Deferred** (optional improvements, not bugs):
- (list any nice-to-haves you noticed but did NOT fix)
```

**If you found nothing worth fixing**:

```markdown
# Phase <slug> — Review #<cycle>: REVIEW-CLEAN

**Date**: (timestamp)
**Assessment**: Code is clean. No bugs, security issues, or correctness problems found.

**Deferred** (optional improvements, not bugs):
- (list any nice-to-haves, or "None")
```

Commit the review record: `docs: code review #<cycle> for <slug>`

The heading of `<review_file>` MUST contain either `REVIEW-CLEAN` or `REVIEW-FIXES` — the runner parses this.

## Global rules

- Do NOT read ROUTER.md or load any skills
- Do NOT use the Skill tool
- If `test-logs/` exists after running tests, include its contents in the validation record
- Run commands from the project root directory
- Part 2 (review) only runs when Part 1 wrote PASS. If you are in the review agent and Part 1 did not pass, STOP — the runner should not have spawned you.
