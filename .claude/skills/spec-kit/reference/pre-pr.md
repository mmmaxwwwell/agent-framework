# Pre-PR Gate

Every project MUST include a single command that validates all quality gates before creating a pull request. This command is the developer's (and agent's) last line of defense — it catches failures locally before they burn CI cycles, block reviewers, or break the build for others.

The pre-PR gate is NOT the same as the fix-validate loop (which runs during initial implementation). The pre-PR gate is a **repeatable action** that runs on every future change — bug fixes, new features, dependency updates, refactors — long after the initial implementation is complete.

## The `pre-pr` target

Every project MUST have a `pre-pr` target in its task runner (Makefile, package.json scripts, Justfile, etc.):

```makefile
# Makefile example
pre-pr: validate e2e-local ci-lint-check
	@echo "All pre-PR checks passed"
```

```json
// package.json example
{
  "scripts": {
    "pre-pr": "npm run validate && npm run e2e:local && npm run ci:lint-check"
  }
}
```

The target runs these steps **in order** (fail-fast — stop on first failure):

| Step | What it does | Why |
|------|-------------|-----|
| 1. Build all stacks | Compile/build every artifact the project produces | Catch compile errors across all languages |
| 2. Run all tests | Unit + integration tests for every test suite | Catch regressions |
| 3. Lint | All linters for all languages | Catch style/quality issues |
| 4. Security scan | Local security scanners (Trivy, Semgrep, Gitleaks, ecosystem tools) | Catch vulnerabilities before push |
| 5. Non-vacuous check | Assert test counts > 0 for every test suite | Prevent empty test suites from passing silently |
| 6. E2E tests (if applicable) | Real-runtime E2E tests (emulator, browser, VM) | Catch integration failures with real runtimes |
| 7. CI workflow syntax check | Validate workflow YAML (if modified) | Catch CI config errors before push |

Steps 1-5 are MANDATORY for all presets except poc. Steps 6-7 are conditional — include them when the project has E2E tests or modified CI workflows.

## Multi-build-system discovery

The `pre-pr` target MUST discover and validate ALL build systems in the project. A project with `go.mod` at root and `build.gradle.kts` in `android/` must build and test BOTH. See `reference/testing.md` for the manifest-to-command mapping table.

The `pre-pr` script (or the targets it calls) should scan for build manifests and run the appropriate commands:

```bash
# Example: discover and validate all build systems
build_systems=()
[ -f go.mod ] && build_systems+=("go")
[ -f android/build.gradle.kts ] && build_systems+=("android")
[ -f Cargo.toml ] && build_systems+=("rust")
[ -f package.json ] && build_systems+=("node")
[ -f flake.nix ] && build_systems+=("nix")

for sys in "${build_systems[@]}"; do
  case "$sys" in
    go)     go build ./... && go test -race -count=1 ./... ;;
    android) cd android && ./gradlew assembleDebug testDebugUnitTest && cd .. ;;
    rust)   cargo build && cargo test ;;
    node)   npm run build && npm test ;;
    nix)    nix build && nix flake check ;;
  esac
done
```

## Non-vacuous assertion

After running tests, the `pre-pr` target MUST verify that a non-zero number of tests actually executed for EVERY test suite. This catches the silent failure mode where the test runner exits 0 but ran nothing (wrong directory, missing config, skipped suite).

```bash
# Go: check test-logs/summary.json
total=$(jq '.passed + .failed' test-logs/ci/latest/summary.json)
[ "${total:-0}" -gt 0 ] || { echo "ERROR: 0 Go tests ran"; exit 1; }

# Android: check JUnit XML
xml_count=$(find android/app/build/test-results -name '*.xml' 2>/dev/null | wc -l)
[ "$xml_count" -gt 0 ] || { echo "ERROR: 0 Android test result files"; exit 1; }

# Node: check coverage or reporter output
[ -f coverage/coverage-summary.json ] || { echo "ERROR: No coverage report"; exit 1; }

# Security: check scanner output
for scanner in trivy semgrep gitleaks; do
  [ -s "test-logs/security/${scanner}.json" ] || echo "WARN: ${scanner} produced no output"
done
```

## CI workflow validation (conditional)

When any `.github/workflows/*.yml` file has been modified since the last push (check with `git diff --name-only origin/HEAD -- .github/workflows/`), the `pre-pr` target MUST also validate the workflow:

1. **YAML syntax** — parse every workflow file and reject syntax errors
2. **Action version pins** — warn on unpinned actions (using `@main` instead of `@v4` or SHA)
3. **Command reproducibility** — for every `run:` block in the modified workflow, execute the command locally. If it fails locally, it will fail in CI.
4. **Artifact path verification** — for every `actions/upload-artifact` step, run the producing build command and verify the file exists at the expected path
5. **Secret references** — list all `${{ secrets.* }}` references and verify they're documented in the README's CI Setup section

Tools for local CI validation:
- **`actionlint`** — GitHub Actions workflow linter (catches syntax errors, invalid action references, type mismatches). Add to `flake.nix` devShell.
- **`act`** — runs GitHub Actions locally in Docker containers. Useful for complex workflows but heavy. Optional.
- **Manual command extraction** — for simpler projects, just grep `run:` blocks from modified workflows and execute them. This is what the CI workflow local verification tasks do during implementation.

## E2E tests in pre-PR (conditional)

If the project has real-runtime E2E tests (Android emulator, browser, iOS simulator, NixOS VM), include them in the `pre-pr` target with a timeout and retry wrapper:

```makefile
e2e-local:
	@echo "Running E2E tests (timeout: 20m, retries: 2)..."
	timeout 1200 ./test/e2e/run-e2e.sh --retry 2
```

E2E tests are slower and flakier than unit/integration tests. The `pre-pr` target should:
- Run them LAST (after all fast checks pass)
- Use a generous timeout (emulator boot can take minutes)
- Include a retry wrapper (1-2 retries for flakiness)
- Allow skipping with an env var for quick iterations: `SKIP_E2E=1 make pre-pr`

See `reference/e2e-runtime.md` for the E2E test infrastructure patterns.

## Relationship to CI

The `pre-pr` target runs the SAME checks as CI, in the SAME order, with the SAME tools. The only differences:

| Aspect | `pre-pr` (local) | CI (remote) |
|--------|-----------------|-------------|
| Environment | `nix develop` / local dev shell | CI runner with Nix or Docker |
| Secrets | Not available (skip token-gated scans) | Available via GitHub Secrets |
| SARIF uploads | Skip (no GitHub Security tab locally) | Upload to GitHub Security tab |
| Artifact uploads | Skip (files are on disk) | Upload via `actions/upload-artifact` |
| E2E hardware | KVM if available, software fallback | Depends on runner (KVM on ubuntu-latest) |
| Advisory scans | Skip Snyk/SonarCloud (need tokens) | Run with tokens |

The principle: **if it passes locally, it should pass in CI. If it fails in CI, reproduce it locally first.**

## Relationship to the fix-validate loop

During initial implementation (Phase 7), the parallel runner enforces per-phase validation automatically. The `pre-pr` target is what you run AFTER implementation — when you're making changes to an already-implemented project.

| Context | What runs validation | When |
|---------|---------------------|------|
| Initial implementation | Runner-managed fix-validate loop | Per-phase, automatic |
| Post-implementation changes | `make pre-pr` (developer/agent invokes manually) | Before every PR |

The `pre-pr` target subsumes the fix-validate loop's checks. If you can pass `make pre-pr`, you can pass CI.

## Preset behavior

| Preset | `pre-pr` scope |
|--------|---------------|
| **poc** | Skip — no `pre-pr` target. Just `make test` if tests exist. |
| **local** | Build + test + lint + security scan + non-vacuous check. No E2E unless project has emulator/browser tests. |
| **library** | Build + test (all target platforms) + lint + security scan + non-vacuous check + packaging test (install from built artifact). |
| **extension** | Build + test + lint + security scan + non-vacuous check + packaging test + host platform test (load extension in real host). |
| **public** | Full: build + test + lint + security scan + non-vacuous check + E2E (if applicable) + CI workflow check (if modified). |
| **enterprise** | Full: everything in public + contract tests + performance regression check. |

## What the spec and plan MUST include

- **Spec (Phase 2)**: Include a functional requirement for the `pre-pr` target — "System MUST provide a single command that validates all quality gates before creating a pull request."
- **Plan (Phase 5)**: Include `pre-pr` in the DX tooling section. Define which checks are included based on the preset. Reference this file for the implementation pattern.
- **Tasks (Phase 6)**: Include a task in the foundational phase to create the `pre-pr` target. Include a late-phase task to verify it catches real failures (intentionally break something, run `pre-pr`, verify it fails).

## Task generation guidance

```markdown
- [ ] T0XX Create `pre-pr` Makefile target (or equivalent): single command that runs build (all stacks) → test (all suites) → lint → security scan → non-vacuous assertion (test counts > 0). Add `SKIP_E2E=1` env var for quick iterations. Verify: intentionally break a test, run `make pre-pr`, confirm it fails. [DX, FR-xxx]
  Done when: `make pre-pr` exits 0 on clean code, exits non-zero on broken code, covers all build systems.
```

For projects with E2E tests, add the E2E step as a separate late-phase task after the E2E infrastructure is built:

```markdown
- [ ] T0XX Add E2E to pre-pr gate: wire `make e2e-local` into `make pre-pr` (runs after lint/security). Include timeout (20m) and retry wrapper (2 attempts). Add `SKIP_E2E=1` bypass. [DX, E2E]
  Done when: `make pre-pr` runs E2E tests when emulator/browser is available, skips gracefully when not.
```
