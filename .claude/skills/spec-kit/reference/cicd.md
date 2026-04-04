# CI/CD Pipeline

Every project MUST include a working CI/CD pipeline committed to the repository.

## Pipeline stages

The standard pipeline structure, in order:

1. **Lint** — code style, formatting, static analysis
2. **Build** — compile, bundle, generate artifacts
3. **Unit test** — fast, isolated tests
4. **Integration test** — multi-component tests with real services
5. **Security scan** — SAST (Semgrep), SCA (Trivy + ecosystem tools + Snyk for open-source repos), secret scanning (Gitleaks, TruffleHog), SBOM generation
6. **Contract test** — API compliance (if applicable)
7. **E2E test** — full user flow tests (if applicable)
8. **Deploy** — staging/production deployment (if applicable)

## Build, release, run separation

The pipeline MUST enforce strict separation between three stages:
- **Build**: Convert source code into an executable artifact. Deterministic and reproducible from a specific commit.
- **Release**: Combine the build artifact with environment-specific config. Every release gets a unique identifier. Releases are immutable.
- **Run**: Execute the release in the target environment. Minimal complexity, no code changes.

## Pipeline as code

The CI configuration MUST be committed to the repository:
- `.github/workflows/` for GitHub Actions
- `.gitlab-ci.yml` for GitLab CI

## Quality gates

The pipeline MUST block merges on:
- Test failures (unit, integration, contract, e2e)
- **Vacuous passes** (0 tests ran, 0 results found — see "Non-vacuous CI validation" below)
- Critical or high severity vulnerabilities (from security scans)
- Secrets detected in code
- Lint failures
- Build failures

Additional gates (code coverage thresholds, license compliance) are determined during the interview.

## Non-vacuous CI validation

A CI job that reports 0 passed / 0 failed and exits green is **worse than a failure** — it gives false confidence that code is tested when nothing actually ran. This is a common class of silent CI rot: the build tool isn't found, the test directory is wrong, a prerequisite step failed silently, or test results are parsed from an empty directory.

**Every CI job that runs tests MUST assert that a non-zero number of tests actually executed.** A job that finds zero test results MUST exit non-zero.

### Implementation pattern

After the test step, add a verification step that counts results and fails if none were found:

```yaml
# For JUnit XML results (Android/JVM, pytest, etc.)
- name: Verify tests ran
  if: always()
  run: |
    COUNT=$(find path/to/test-results -name '*.xml' 2>/dev/null | wc -l)
    if [ "$COUNT" -eq 0 ]; then
      echo "::error::No test results found — tests did not run"
      exit 1
    fi
    # Optional: extract total test count from XML and assert > 0
    TESTS=$(grep -roh 'tests="[0-9]*"' path/to/test-results/ | grep -o '[0-9]*' | paste -sd+ | bc)
    if [ "${TESTS:-0}" -eq 0 ]; then
      echo "::error::Test results found but 0 tests reported — build may have failed before tests"
      exit 1
    fi

# For Go test -json output (piped through a reporter)
- name: Verify tests ran
  if: always()
  run: |
    if [ -f test-logs/summary.json ]; then
      TOTAL=$(jq '.passed + .failed' test-logs/summary.json)
      if [ "${TOTAL:-0}" -eq 0 ]; then
        echo "::error::Test reporter found 0 tests — something is misconfigured"
        exit 1
      fi
    else
      echo "::error::No test summary found — test reporter did not run"
      exit 1
    fi

# For security scanners
- name: Verify scanners ran
  if: always()
  run: |
    for scanner in trivy semgrep gitleaks govulncheck; do
      if [ ! -f "test-logs/security/${scanner}.json" ]; then
        echo "::error::Scanner ${scanner} produced no output"
        exit 1
      fi
      SIZE=$(wc -c < "test-logs/security/${scanner}.json")
      if [ "$SIZE" -lt 10 ]; then
        echo "::error::Scanner ${scanner} output is empty/trivial (${SIZE} bytes)"
        exit 1
      fi
    done
```

### What to guard

Apply non-vacuous validation to **every** CI job that produces countable results:

| Job type | What to count | Minimum |
|----------|--------------|---------|
| Unit/integration tests | Test count from runner output or result XML | > 0 |
| Android tests | JUnit XML files in `build/test-results/` | > 0 files, > 0 tests |
| Security scans | JSON output files per scanner | > 0 bytes per scanner |
| Lint | Files checked (or at least: tool ran without "no files found") | > 0 |
| Build | Output artifact exists | file exists and > 0 bytes |
| Coverage | Coverage report file exists | file exists |

### Why the job summary isn't enough

A common anti-pattern (and what caused this rule): the job summary step parses test results from a directory, finds nothing, reports "0 passed / 0 failed", and the job exits 0 because no step actually failed. The summary is cosmetically green. Branch protection sees a green check. The test suite has been silently broken for weeks.

The fix is structural: **the verification step must be a separate step with `exit 1`**, not part of a summary step that only writes markdown. Summary steps exist for humans reading the Actions UI. Verification steps exist for the merge gate.

## Security scan reporting

- **SARIF uploads** to the GitHub Security tab for unified findings
- **PR annotations** from scanning tools
- **README badges** for build status, vulnerability count, code coverage, license compliance
- **SBOM** generated on every CI run and stored as a build artifact
- **Security summary in release notes** listing scan results

## Snyk integration (open-source repos)

If the project is public (or will be), add Snyk to the CI pipeline. Snyk's Open Source plan is free for public repos and provides reachability analysis, auto-fix PRs, and license compliance — features that Trivy doesn't cover.

### Setup

1. **Auth**: Store `SNYK_TOKEN` as a GitHub Actions secret. The user gets a free token from snyk.io by signing in with their GitHub account.
2. **GitHub Actions step** (add after the Trivy step in the security scan stage):

```yaml
- name: Snyk security scan
  uses: snyk/actions/node@master  # or /python, /golang, /docker, etc.
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
  with:
    args: --severity-threshold=high --sarif-file-output=snyk.sarif
  continue-on-error: true  # Don't block PRs on first integration — tighten after baseline is clean

- name: Upload Snyk SARIF
  if: always()
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: snyk.sarif
```

3. **`snyk monitor`** on main branch merges (tracks the project in the Snyk dashboard for continuous monitoring):

```yaml
- name: Snyk monitor (main only)
  if: github.ref == 'refs/heads/main'
  uses: snyk/actions/node@master
  env:
    SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
  with:
    command: monitor
```

### Quality gate

- Start with `continue-on-error: true` to establish a baseline
- Once the project is clean, switch to `continue-on-error: false` and set `--severity-threshold=high` to block PRs on high/critical vulnerabilities
- Snyk auto-fix PRs are enabled by default on the Snyk dashboard — review and merge them as they arrive

### When to skip

- Private repos without a Snyk paid plan — use Trivy + ecosystem audit only
- PoC preset — skip all security scanning

## CI credential setup documentation

The project README MUST include a **CI Setup** section documenting every secret/token the pipeline requires. Contributors and maintainers need to know how to configure the pipeline — a workflow that references `${{ secrets.SNYK_TOKEN }}` without explaining where to get it is broken documentation.

### What to document

For each CI tool that requires authentication, the README must include:

| Info | Example |
|------|---------|
| Secret name | `SNYK_TOKEN` |
| Where to get it | "Sign in at snyk.io with your GitHub account → Account Settings → API Token" |
| Where to store it | "GitHub repo → Settings → Secrets and variables → Actions → New repository secret" |
| Required scopes/permissions | "Read-only, no org admin needed" |
| Free tier eligibility | "Free for public repos (Snyk Open Source plan)" |

### Common CI secrets reference

Include this table (filtered to the tools actually used in the project):

| Secret | Tool | How to obtain |
|--------|------|---------------|
| `SNYK_TOKEN` | Snyk | snyk.io → Account Settings → API Token (free with GitHub SSO) |
| `SONAR_TOKEN` | SonarCloud | sonarcloud.io → My Account → Security → Generate Token (free for public repos) |
| `FOSSA_API_KEY` | FOSSA | fossa.com → Account Settings → API Tokens (free tier: 5 projects) |
| `CODECOV_TOKEN` | Codecov | codecov.io → repo settings (free for public repos, not required for public repos using GitHub Actions) |
| *(none needed)* | Trivy, Semgrep OSS, Gitleaks, TruffleHog, CodeQL, OSV-Scanner, OpenSSF Scorecard, Grype, Checkov | These tools require no authentication tokens |

### README template

The implementing agent MUST add a section like this to the project README:

```markdown
## CI Setup

The GitHub Actions pipeline runs automatically on PRs and pushes to main. Most tools require no setup, but some need API tokens:

| Secret | Required | How to get it |
|--------|----------|---------------|
| `SNYK_TOKEN` | For Snyk scans | [snyk.io](https://snyk.io) → sign in with GitHub → Account Settings → API Token |
| `SONAR_TOKEN` | For SonarCloud | [sonarcloud.io](https://sonarcloud.io) → My Account → Security → Generate Token |

**To add secrets**: Go to your GitHub repo → Settings → Secrets and variables → Actions → New repository secret.

Without these tokens, the corresponding scan steps will be skipped (they use `continue-on-error: true`).
```

Adjust the table to match the actual tools used in the project. Omit rows for tools that need no tokens.

## Artifact generation

Every CI run MUST produce:
- Test results (structured output per `reference/testing.md`)
- SBOM (CycloneDX or SPDX format)
- Security scan summary
- Code coverage report (if applicable)
- Build artifacts (if applicable)

### Pre-release artifact availability (develop/feature branches)

Every distributable artifact that the release workflow builds MUST also be buildable on non-release branches (develop, feature branches, PRs). This means:

1. **The CI workflow (`ci.yml` or equivalent) must build ALL artifacts** — not just run tests. If the release workflow builds a Go binary and an Android APK, the CI workflow must also build both (debug variants are fine — the point is verifying the build succeeds, not producing release-quality artifacts).
2. **Upload debug artifacts as GitHub Actions artifacts** on every PR/push to develop. This gives developers installable builds for manual testing without waiting for a release.
3. **The release workflow should ONLY add signing, versioning, and upload** — not be the first place an artifact is built. If an artifact only builds in the release workflow, build failures are discovered at release time instead of during development.

**Why:** If the APK only builds in the release workflow (triggered by push to main), a broken Gradle build goes undetected through the entire develop → PR → merge cycle. By the time someone tries to release, the build has been broken for weeks and the fix requires archaeology.

**Implementation pattern:**
```yaml
# In ci.yml (runs on every PR and push to develop)
build-artifacts:
  steps:
    - name: Build Go binary
      run: go build -o nix-key ./cmd/nix-key
    - name: Build Android APK (debug)
      run: cd android && ./gradlew assembleDebug
    - name: Upload debug APK
      uses: actions/upload-artifact@v4
      with:
        name: debug-apk
        path: android/app/build/outputs/apk/debug/app-debug.apk
```

This is language-agnostic — adapt the build commands to the project's tech stack. The principle is: **if it's built in the release workflow, it must also be built in the CI workflow.**

## Default branch readiness

Before creating a PR to the default branch, the agent MUST verify that the merge will bring everything external services and workflow triggers need. A project where all code lives on `develop` but the default branch (`main`) is empty or stale will have:
- **Broken badges**: GitHub Actions badges return 404 if the workflow doesn't exist on the default branch. Shields.io license badges show "not specified" if LICENSE isn't on the default branch.
- **Failed `workflow_run` triggers**: GitHub runs `workflow_run`-triggered workflows using the **default branch's version** of the workflow file. If the workflow only exists on a feature branch, GitHub uses a stale/nonexistent version from the default branch.
- **No release automation**: release-please and similar tools require their config files on the default branch.

### What to check

Before the PR is created, verify the default branch contains (or the PR will add):

| File/Directory | Why it's needed on the default branch |
|---------------|--------------------------------------|
| `.github/workflows/*.yml` | Workflow badges, `workflow_run` triggers, release automation |
| `LICENSE` | GitHub API license detection, shields.io license badge |
| `README.md` | Repository landing page, badge rendering |
| Release config (`release-please-config.json`, etc.) | Release automation on push to default branch |
| Package manifests (`go.mod`, `package.json`, etc.) | Dependency scanning services (Snyk, Dependabot) |

### `workflow_run` trigger validation

For every workflow that uses `workflow_run`:
1. Read the `workflows:` list in the trigger — these are workflow **names** (the `name:` field), not file names
2. Verify each referenced workflow exists on the default branch with a matching `name:` field
3. Verify the `branches:` filter in the `workflow_run` trigger matches branches where the triggering workflow actually runs
4. If the referenced workflow doesn't exist on the default branch, the `workflow_run` trigger will use a stale version (if one ever existed) or fail silently

## Observable output validation (post-CI)

After CI passes, the agent MUST validate the **observable outputs** of the project — everything a user, contributor, or automated service would see. Passing tests and green CI are necessary but not sufficient. This catches the class of bugs where the code works but the project appears broken from outside.

### Badge validation

For every badge URL in README.md:

1. Fetch with `curl -sI <url>` — verify HTTP 200
2. For shields.io badges: fetch the SVG body and check it doesn't contain error strings (`not found`, `not specified`, `invalid`, `no releases`)
3. For GitHub Actions badges: verify the badge shows a valid workflow status, not 404
4. Common failures and fixes:

| Badge shows | Cause | Fix |
|-------------|-------|-----|
| 404 | Workflow doesn't exist on default branch | Ensure PR brings the workflow file |
| "not specified" | File (LICENSE, etc.) not on default branch | Ensure PR brings the file |
| "no releases" | No GitHub releases exist | Verify release-please config; releases appear after first merge to default branch |
| "failing" | Workflow uses stale file from default branch | Ensure current workflow file reaches default branch |

### Artifact validation

After CI completes:

1. List artifacts: `gh run view <run_id> --json artifacts`
2. Cross-reference against every `actions/upload-artifact` step in the workflow YAML
3. Download at least one artifact and verify it's non-empty
4. For missing artifacts: check `if:` conditions on the upload step, check if the producing build step ran (non-vacuous)

### Acceptance scenario verification

Parse the spec's acceptance scenarios (Given/When/Then) and classify:

- **Automatically verifiable**: URL fetches, CLI commands, file checks, API calls → execute and report PASS/FAIL
- **CI-verifiable**: examine CI run logs/artifacts for expected annotations, output, results
- **Manual**: list in completion report as requiring human verification

Execute all automatable scenarios. Fix-validate on failures (10 iterations per scenario).

## Local security scan validation (fix-validate loop)

Security scanning is part of the phase validation lifecycle — not a separate workflow. When the runner spawns a validation agent at a phase boundary, that agent runs **build → test → lint → security scan**. If any scanner finds issues, the standard fix-validate loop kicks in: the validation agent writes a FAIL record, a fix task is appended, a fresh fix agent reads the findings and patches the code, and the runner re-validates.

### How it works

1. **Phase completes** — all tasks marked `[x]`
2. **Validation agent spawns** — runs the project's test suite AND security scanners locally
3. **Scanners run with JSON output** — structured findings with file, line, rule ID, severity, description
4. **If findings exist** → validation FAIL, fix task appended to the phase
5. **Fix agent reads findings** — structured JSON from `test-logs/security/` (same directory pattern as test failures)
6. **Fix agent patches code** — addresses each finding, commits
7. **Re-validate** — runner spawns another validation agent, scanners run again
8. **Loop until clean** — same rules as test fix-validate: 10 attempts, then BLOCKED.md

### Scanner commands (local, JSON output)

The validation agent runs these commands and writes output to `test-logs/security/<scanner>.json`:

```bash
# SCA — dependency vulnerabilities
trivy fs --format json --severity CRITICAL,HIGH --output test-logs/security/trivy.json .

# SAST — static analysis
semgrep --json --config p/default --config p/golang --output test-logs/security/semgrep.json .

# Secrets — leaked credentials
gitleaks detect --report-format json --report-path test-logs/security/gitleaks.json --no-git

# Go vulnerabilities
govulncheck -format json ./... > test-logs/security/govulncheck.json
```

Adjust scanner configs per project (language-specific rulesets, severity thresholds). The scanner list comes from `reference/security.md` — use whatever scanners the project's CI pipeline runs, so local validation catches the same issues CI would.

### Security findings in structured output

Security scan results follow the same pattern as test failures — structured files that fix agents can parse without reading raw CLI output:

| File | Format | Content |
|------|--------|---------|
| `test-logs/security/<scanner>.json` | JSON | Raw scanner output (findings with file, line, rule, severity) |
| `test-logs/security/summary.json` | JSON | `{ "scanners": { "trivy": { "findings": 0 }, "semgrep": { "findings": 2 }, ... }, "total": 2, "pass": false }` |

The validation agent produces `summary.json` by aggregating scanner results. Fix agents read `summary.json` first (to understand scope), then drill into individual scanner JSON files for details.

### What fix agents do with findings

Fix agents classify each finding before acting:

| Category | Action |
|----------|--------|
| **Dependency vulnerability** | Update the dependency version in `go.mod` / `package.json` / `flake.nix`. Run `go mod tidy` or equivalent. |
| **SAST finding (code pattern)** | Read the flagged code, understand the rule, fix the pattern. Common: SQL injection, command injection, path traversal, hardcoded secrets. |
| **Secret detected** | Remove the secret from code, add to `.gitignore` if it's a file, rotate the credential if it was committed to history. |
| **False positive** | Write a suppression comment (e.g., `// nosemgrep: rule-id`, `#nosec`) with a justification. Record in `learnings.md` so future agents don't re-suppress. |

Fix agents MUST NOT suppress findings without justification. If a finding is genuinely a false positive, the suppression comment must explain why. If the agent can't determine whether it's a false positive, it fixes the code rather than suppressing.

### Integration with phase validation lifecycle

The phase validation state machine gains a new validation step:

```
Tasks complete → validate (build + test + lint + security scan) → review → clean
```

Security scan failure is treated identically to test failure — same fix task pattern, same iteration cap, same BLOCKED.md escalation. The validation agent writes a single PASS/FAIL record that covers all validation steps (tests AND security). A phase doesn't pass validation if any scanner has findings.

### Why local, not CI-only

Running scanners locally in the fix-validate loop catches issues **before pushing**. This avoids burning 10-30 minute CI cycles on code that has known vulnerabilities. The CI pipeline runs the same scanners as a final gate, but the local loop is the primary feedback mechanism for the implementing agent.

## Local CI workflow validation

When CI workflow files (`.github/workflows/*.yml`) are modified, the changes MUST be validated locally before pushing. Workflow syntax errors, wrong artifact paths, and broken `run:` commands waste 10-30 minutes per CI round-trip. Local validation catches them in seconds.

### What to validate

| Check | How | Tool |
|-------|-----|------|
| **YAML syntax** | Parse every workflow file, reject syntax errors | `actionlint` (GitHub Actions-specific linter, catches type mismatches, invalid action refs, expression errors) |
| **`run:` command reproducibility** | Extract every `run:` block from modified workflows, execute locally | Shell — just run the command |
| **Artifact path verification** | For every `actions/upload-artifact` step, run the producing build command, verify the file exists | Shell — run build, check path |
| **Secret references** | List all `${{ secrets.* }}` refs, verify documented in README CI Setup section | Grep + manual check |
| **Action version pins** | Warn on `@main`/`@master` instead of `@v4` or SHA pins | `actionlint` flags this |
| **`workflow_run` chain integrity** | Verify referenced workflow `name:` fields match actual workflow files | Grep workflow names across files |

### Tool: `actionlint`

`actionlint` is a static checker for GitHub Actions workflow files. It catches errors that YAML linters miss — invalid action inputs, type mismatches in expressions, deprecated syntax, unpinned action versions, and undefined secret references.

Add to the project's `flake.nix` devShell:
```nix
devShells.default = pkgs.mkShell {
  buildInputs = [ pkgs.actionlint /* ... other tools */ ];
};
```

Run on all workflow files:
```bash
actionlint .github/workflows/*.yml
```

### Integration with `pre-pr` gate

The `pre-pr` target (see `reference/pre-pr.md`) should run `actionlint` on modified workflow files. Only run this check when workflows have changed:

```bash
# Only lint workflows if they changed since origin/HEAD
if git diff --name-only origin/HEAD -- .github/workflows/ | grep -q '.'; then
  actionlint .github/workflows/*.yml
fi
```

### Integration with fix-validate loop

During implementation, the CI workflow local verification tasks (see `phases/tasks.md § CI workflow local verification`) run every `run:` command from modified workflows in parallel sub-agents. This is the same principle applied at implementation time — catch CI failures before burning CI cycles.

## Agentic CI feedback loop

Tasks that push code and iterate on CI failures MUST be tagged `[needs: gh, ci-loop]` in tasks.md. This activates a runner-managed debug cycle that uses separate sub-agents instead of one long-running context:

### How it works

1. **Local validation first** — before the first push, spawn parallel fix-validate subagents for every build system in the project (e.g., `make validate`, `nix flake check`, `make android-apk`). Each subagent loops until its command passes. Only push after ALL local validations pass. This catches the majority of failures in seconds/minutes instead of waiting 10-30 min CI round-trips.
2. **Runner pushes** the current branch
3. **Runner polls CI** in the main thread (no agent context burned) via `gh run list` / `gh run view`
4. **On cancellation**: if the CI run was cancelled (not failed), the runner re-pushes to trigger a fresh run — it does NOT spawn diagnosis or fix agents. A cancelled run is not a code failure.
5. **On failure**: runner downloads logs to `ci-debug/<task_id>/attempt-N-logs.txt`, then:
   - Spawns a **diagnosis sub-agent** that reads the logs + prior history and writes `attempt-N-diagnosis.md`
   - Runs a **local fix-validate loop** (up to 20 iterations):
     1. Spawns a **fix sub-agent** that reads the diagnosis, applies the fix, and commits (does NOT push)
     2. Spawns a **validation sub-agent** that runs the SAME commands CI runs locally and writes a PASS/FAIL result
     3. If FAIL → spawns another fix agent, then another validation agent, repeating up to 20 times
     4. If PASS → runner pushes the fix
   - This catches failures locally instead of burning 10-30 min CI cycles per iteration
6. **Loop**: runner polls CI again for the pushed fix, repeats until green or attempt cap (50) is hit
7. **On success**: spawns a **finalize sub-agent** to create the PR and mark the task complete

### CI parity in local validation

The validation agent reads ALL workflow files in `.github/workflows/` (not just `ci.yml`) to discover commands. It runs every `run:` command from every workflow, skipping only GitHub Actions-specific steps (action uses, SARIF uploads) and CI-only secrets. This ensures local validation catches the same failures CI would, including:

- NixOS VM tests (`nix flake check --print-build-logs`)
- Full test suites with race detection (`go test -race`)
- Linters and formatters (`golangci-lint`, `nixfmt`)
- Security scanners (when available locally)
- **ALL build commands from ALL workflows** — including release workflows. If `release.yml` runs `./gradlew assembleRelease`, the validation agent runs it locally too. A build command that only exists in the release workflow and has never been validated locally is a ticking time bomb.

**Multi-build-system rule:** The validation agent discovers build manifests in the project (see `phases/implement.md § Multi-build-system discovery`) and runs every build system's build+test commands. A project with `go.mod` and `android/build.gradle.kts` must pass both `go build ./...` AND `./gradlew assemble` — skipping either is a validation failure.

### Artifact directory

All CI debug artifacts live in `ci-debug/<task_id>/`:

| File | Purpose |
|------|---------|
| `state.json` | Resumable state — tracks all attempts |
| `attempt-N-ci-result.json` | CI poll result (status, conclusion, failed jobs, URL) |
| `attempt-N-logs.txt` | Raw CI failure logs |
| `attempt-N-diagnosis.md` | Diagnosis agent's analysis |
| `attempt-N-fix-notes.md` | Fix agent's notes (if it disagreed with diagnosis) |
| `attempt-N-local-M.md` | Local validation result for attempt N, iteration M (PASS/FAIL + command table) |

Sub-agents read prior attempt files for context without inflating their own context window.

### Resumability

The `state.json` file tracks completed attempts. If the runner is killed and restarted, it resumes from the last incomplete attempt.

### Task format

```
- [ ] T075 [needs: gh, ci-loop] CI/CD validation: push to develop, iterate until green, create PR
```

### Failure limit

After 50 failed CI attempts, the runner writes `BLOCKED.md` for human review. Within each CI attempt, up to 20 local fix-validate iterations run before pushing. The full history is preserved in `ci-debug/<task_id>/`.
