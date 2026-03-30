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
- Critical or high severity vulnerabilities (from security scans)
- Secrets detected in code
- Lint failures
- Build failures

Additional gates (code coverage thresholds, license compliance) are determined during the interview.

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

## Agentic CI feedback loop

Tasks that push code and iterate on CI failures MUST be tagged `[needs: gh, ci-loop]` in tasks.md. This activates a runner-managed debug cycle that uses separate sub-agents instead of one long-running context:

### How it works

1. **Runner pushes** the current branch
2. **Runner polls CI** in the main thread (no agent context burned) via `gh run list` / `gh run view`
3. **On cancellation**: if the CI run was cancelled (not failed), the runner re-pushes to trigger a fresh run — it does NOT spawn diagnosis or fix agents. A cancelled run is not a code failure.
4. **On failure**: runner downloads logs to `ci-debug/<task_id>/attempt-N-logs.txt`, then:
   - Spawns a **diagnosis sub-agent** that reads the logs + prior history and writes `attempt-N-diagnosis.md`
   - Runs a **local fix-validate loop** (up to 20 iterations):
     1. Spawns a **fix sub-agent** that reads the diagnosis, applies the fix, and commits (does NOT push)
     2. Spawns a **validation sub-agent** that runs the SAME commands CI runs locally and writes a PASS/FAIL result
     3. If FAIL → spawns another fix agent, then another validation agent, repeating up to 20 times
     4. If PASS → runner pushes the fix
   - This catches failures locally instead of burning 10-30 min CI cycles per iteration
5. **Loop**: runner polls CI again for the pushed fix, repeats until green or attempt cap (50) is hit
6. **On success**: spawns a **finalize sub-agent** to create the PR and mark the task complete

### CI parity in local validation

The validation agent reads `.github/workflows/ci.yml` to discover commands rather than using a hardcoded list. It runs every `run:` command from the CI workflow, skipping only GitHub Actions-specific steps and CI-only secrets. This ensures local validation catches the same failures CI would, including:

- NixOS VM tests (`nix flake check --print-build-logs`)
- Full test suites with race detection (`go test -race`)
- Linters and formatters (`golangci-lint`, `nixfmt`)
- Security scanners (when available locally)

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
