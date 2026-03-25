# CI/CD Pipeline

Every project MUST include a working CI/CD pipeline committed to the repository.

## Pipeline stages

The standard pipeline structure, in order:

1. **Lint** — code style, formatting, static analysis
2. **Build** — compile, bundle, generate artifacts
3. **Unit test** — fast, isolated tests
4. **Integration test** — multi-component tests with real services
5. **Security scan** — SAST (Semgrep), SCA (Trivy + ecosystem tools), secret scanning (Gitleaks, TruffleHog), SBOM generation
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
