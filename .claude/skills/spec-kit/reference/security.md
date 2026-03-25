# Security Baseline

**Core principle: secure by default.** Security decisions are made during the interview. The implementation MUST follow these non-negotiable rules.

## Input validation and sanitization

All external input MUST be validated and sanitized at the system boundary. This is non-negotiable.

- **Validate at the edge**: Every API endpoint, form handler, CLI argument parser, file reader, and message consumer validates input before processing
- **Type checking**: Reject wrong types
- **Length limits**: Maximum length for all string inputs
- **Format validation**: Schema validation for structured inputs
- **Encoding**: Sanitize for the output context — HTML-encode for web, parameterize for SQL, escape for shell
- **Trust internally**: Once input passes boundary validation, internal code can trust it

**Testing**: Boundary validation MUST be covered by integration tests. Include tests for: malformed input, boundary values, and injection attempts (SQL injection, XSS, command injection from OWASP).

## Authentication and authorization

When auth IS implemented:
- Passwords hashed with bcrypt/scrypt/argon2 (never MD5/SHA)
- Tokens have expiration times
- Failed auth attempts are rate-limited
- Auth errors don't leak information ("invalid credentials" not "user not found" vs "wrong password")

## CORS policy

Default MUST be restrictive (specific allowed origins), NOT `Access-Control-Allow-Origin: *`. If CORS is deferred, add a prominent WARNING in documentation.

## Secret management

- All secrets identified in the spec with their source and rotation strategy
- Secrets only from environment variables or secret managers (never in config files or code)
- `.gitignore` includes all secret-containing files (`.env`, `credentials.json`, `*.pem`)
- Pre-commit hook (Gitleaks) to prevent accidental secret commits

## Security headers

For HTTP servers, mandate these baseline headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Force HTTPS |
| `Content-Security-Policy` | Appropriate for the app | Prevent XSS |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME sniffing |
| `X-Frame-Options` | `DENY` or `SAMEORIGIN` | Prevent clickjacking |
| `X-XSS-Protection` | `0` | Disable legacy XSS filter (CSP is better) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Control referrer leakage |
| `Permissions-Policy` | Appropriate for the app | Restrict browser features |

## Security scanning pipeline

The scanning tools and tiers are selected during the interview. At minimum (Tier 1, free):

**Tier 1 — Mandatory (free, all tech stacks):**

| Category | Tool | Purpose |
|----------|------|---------|
| SCA (dependency vulns) | **Trivy** | All-in-one: dependencies, containers, IaC, licenses, SBOM |
| SCA (supplemental) | **OSV-Scanner v2** | Guided remediation, interactive reports |
| SCA (ecosystem) | `npm audit` / `pip audit` / `cargo audit` / `govulncheck` | Zero-config ecosystem checks |
| SAST (per-PR) | **Semgrep** (OSS) | Fast pattern-based scanning, 30+ languages |
| SAST (scheduled) | **CodeQL** | Deep data-flow analysis, free for public repos |
| Secrets (pre-commit) | **Gitleaks** | Millisecond pre-commit hook |
| Secrets (CI) | **TruffleHog** | Active credential verification |
| Secrets (platform) | **GitHub Secret Scanning** | Push protection (where available) |
| SBOM | **Trivy** | CycloneDX or SPDX on every CI run |

**Tier 2 — Recommended (paid):**

| Category | Tool | Purpose |
|----------|------|---------|
| SCA | **Snyk** | Reachability analysis (30-70% noise reduction), auto-fix PRs |
| SAST | **Semgrep Team** | Cross-file analysis, AI triage, Pro rules |
| License | **FOSSA** | Enterprise compliance, attribution docs |
| Quality | **SonarCloud** | Quality gates (bugs, smells, coverage) |

**Tier 3 — Ecosystem-specific (free):**

| Ecosystem | Tools |
|-----------|-------|
| Node.js | `eslint-plugin-security`, `eslint-plugin-no-unsanitized` |
| Python | `bandit` |
| Java | OWASP Dependency-Check |
