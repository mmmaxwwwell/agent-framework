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

## Agentic CI feedback loop

When the implementing agent pushes code and CI fails, the agent must diagnose and fix:

1. **Monitor CI run**: After pushing, monitor to completion (e.g., `gh run watch`)
2. **Retrieve failure logs**: On failure, pull logs (e.g., `gh run view <id> --log-failed`)
3. **Diagnose and fix**: Same fix-validate loop — read failure logs, fix code or CI config, push and re-monitor
4. **CI-specific learnings**: CI gotchas go into `learnings.md`
5. **Failure limit**: After 3 failed CI fix attempts, write `BLOCKED.md`
