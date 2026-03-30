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

Security scanning runs in two places: **locally during the fix-validate loop** (catching issues before push) and **in CI as a final gate** (with SARIF uploads for GitHub Security tab visibility). Both use the same scanners with the same severity thresholds.

### Local scanner commands (for fix-validate loop)

These commands produce JSON output that validation and fix agents can parse. Run them from the project root and write output to `test-logs/security/`:

```bash
mkdir -p test-logs/security

# SCA — dependency vulnerabilities (all ecosystems)
trivy fs --format json --severity CRITICAL,HIGH --output test-logs/security/trivy.json .

# SAST — static analysis (30+ languages)
semgrep --json --config p/default --output test-logs/security/semgrep.json .
# Add language-specific configs: --config p/golang, --config p/typescript, --config p/python, etc.

# Secrets — leaked credentials (scan working tree, not git history)
gitleaks detect --report-format json --report-path test-logs/security/gitleaks.json --no-git

# Go-specific: known vulnerabilities in dependencies
govulncheck -format json ./... > test-logs/security/govulncheck.json 2>&1 || true

# Python-specific: pip audit
pip-audit --format json --output test-logs/security/pip-audit.json || true

# Node-specific: npm audit
npm audit --json > test-logs/security/npm-audit.json 2>&1 || true

# Rust-specific: cargo audit
cargo audit --json > test-logs/security/cargo-audit.json 2>&1 || true
```

The validation agent selects which scanners to run based on the project's tech stack (check `flake.nix`, `package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`). Only run scanners relevant to the project.

After running scanners, the validation agent aggregates results into `test-logs/security/summary.json`:

```json
{
  "scanners": {
    "trivy": { "findings": 0, "exit_code": 0 },
    "semgrep": { "findings": 3, "exit_code": 1 },
    "gitleaks": { "findings": 0, "exit_code": 0 },
    "govulncheck": { "findings": 1, "exit_code": 0 }
  },
  "total_findings": 4,
  "pass": false
}
```

### SARIF output for CI (GitHub Security tab)

In CI, scanners output SARIF format and upload to GitHub's Code Scanning dashboard via `github/codeql-action/upload-sarif@v3`. This gives: PR annotations, finding deduplication, dismissal workflow, and trend tracking — all free.

**Required workflow permission**: `security-events: write`

**SARIF-capable scanners** (6 of 7 common tools):

| Scanner | SARIF Flag | Upload Category |
|---------|-----------|-----------------|
| Trivy | `format: sarif`, `output: trivy-results.sarif` | `trivy` |
| Semgrep | `--sarif --output semgrep-results.sarif` | `semgrep` |
| Gitleaks | `--report-format sarif --report-path gitleaks-results.sarif` | `gitleaks` |
| govulncheck | `-format sarif > govulncheck-results.sarif` | `govulncheck` |
| Snyk | `args: --sarif-file-output=snyk-results.sarif` | `snyk` |
| OpenSSF Scorecard | `results_format: sarif` | `scorecard` |

**SonarCloud** does NOT support SARIF natively — it pushes to its own dashboard. Don't try to convert it; use it as a complementary human-facing view.

**CI upload pattern** (add after each scanner step):

```yaml
- name: Upload <scanner> SARIF
  if: always()
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: <scanner>-results.sarif
    category: <scanner>
```

### Finding classification for fix agents

When the fix-validate loop triggers on security findings, fix agents classify each finding:

| Category | Action | Example |
|----------|--------|---------|
| **Dependency vulnerability** | Update version in lockfile/manifest. Run dependency update command. | `CVE-2024-XXXX in golang.org/x/net` → `go get golang.org/x/net@latest && go mod tidy` |
| **SAST code pattern** | Fix the vulnerable code pattern. | SQL injection → use parameterized queries |
| **Secret in code** | Remove secret, add file to `.gitignore`, document in `learnings.md`. | Hardcoded API key → move to env var |
| **False positive** | Add inline suppression with justification comment. Record in `learnings.md`. | `// nosemgrep: go.lang.security.audit.xss -- output is already HTML-escaped by template engine` |

**Suppression rules**:
- NEVER suppress without a justification comment explaining why it's safe
- NEVER suppress a finding the agent doesn't fully understand — fix it instead
- Record all suppressions in `learnings.md` so future agents and reviewers can audit them

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

**Tier 1.5 — Free for open-source / public repos:**

These tools offer full-featured free plans for public repositories. Include them when the repo is (or will be) open-source.

| Category | Tool | Purpose |
|----------|------|---------|
| SCA | **Snyk** (Open Source plan) | Reachability analysis (30-70% noise reduction), auto-fix PRs, license compliance. Complements Trivy — Trivy catches container/IaC issues, Snyk provides reachability filtering and auto-fix PRs. |
| Quality | **SonarCloud** | Quality gates (bugs, code smells, coverage, duplication). Unlimited LOC for public repos. |
| Supply chain | **OpenSSF Scorecard** | Rates project security posture (0-10) across supply chain practices. |
| Dependency PRs | **GitHub Dependency Review** | Blocks PRs that introduce vulnerable deps or disallowed licenses. |
| DAST | **OWASP ZAP** | Baseline (passive), full (active + spider), and API scan modes. Use for public-facing apps. |

**Tier 1.5 — Free tier (capped, any repo):**

| Category | Tool | Free tier limits | Purpose |
|----------|------|-----------------|---------|
| License | **FOSSA** | 5 projects, 25 devs | License compliance, attribution docs, SBOM management |
| SAST | **Semgrep AppSec Platform** | 10 contributors | Cross-file SAST with Pro rules, SCA with reachability, secrets |

**Tier 2 — Paid (private repos or above free caps):**

| Category | Tool | Purpose |
|----------|------|---------|
| SCA | **Snyk** (Team/Enterprise) | Same as above but for private repos, plus container scanning and IaC |
| SAST | **Semgrep Team** | Above 10-contributor cap |
| License | **FOSSA** (paid) | Above 5-project cap, enterprise compliance |
| Quality | **SonarCloud** (paid) | Private repos or advanced features |

**Tier 3 — Ecosystem-specific (free):**

| Ecosystem | Tools |
|-----------|-------|
| Node.js | `eslint-plugin-security`, `eslint-plugin-no-unsanitized` |
| Python | `bandit` |
| Java | OWASP Dependency-Check |
| Containers | **Grype** (image vuln scanner), **Syft** (SBOM generator), **Dockle** (CIS benchmark linter), **Hadolint** (Dockerfile linter) |
| IaC | **Checkov** (Terraform, K8s, Docker, CloudFormation — 2400+ policies), **KICS** (multi-framework IaC scanner) |
| Fuzzing | **OSS-Fuzz / CIFuzz** (free for accepted OSS projects), **ClusterFuzzLite** (self-hosted) |

## Fuzz testing

Fuzz testing explores the *unknown unknowns* — input combinations no developer anticipated. Unit tests cover expected inputs and known edge cases. SAST finds pattern-matched anti-patterns. Fuzzing generates millions of semi-random inputs and catches crashes, hangs, and correctness violations that neither approach finds.

### When fuzz testing is warranted

A component is a fuzz target when it: (a) accepts `[]byte` or `string` from an external source, (b) has branching logic based on input content, and (c) a crash or corruption would be a security or reliability issue.

**High-value targets (always fuzz):**
- **Wire protocol parsers** — anything that reads bytes off a network (gRPC, SSH agent protocol, TLS handshake, custom binary formats). These cross trust boundaries and accept attacker-controlled input.
- **Binary format deserializers** — protobuf, msgpack, CBOR, ASN.1, certificate parsers (PEM/DER). Structured input with length fields and type tags is where off-by-one and integer overflow bugs live.
- **Cryptographic surrounding code** — not the algorithms themselves (use known-answer tests), but certificate chain validation, key parsing, signature verification dispatch, nonce handling.
- **Input validators and sanitizers** — URL parsers, path canonicalization, anything that applies security policy based on string parsing.

**Secondary targets (fuzz when practical):**
- State machines with complex transition logic (connection negotiators, auth flows)
- Encoding/decoding round-trips (`decode(encode(x)) == x` properties)
- Configuration file parsers
- Any function where the expected behavior is "don't crash on any input"

### Language-specific tools

**Go — native fuzzing (`testing.F`):**

```go
func FuzzParseMessage(f *testing.F) {
    // Seed corpus from existing test cases
    f.Add([]byte("\x00\x01\x02"), uint8(1))
    f.Add([]byte("valid-msg"), uint8(0))

    f.Fuzz(func(t *testing.T, data []byte, msgType uint8) {
        msg, err := ParseMessage(data, msgType)
        if err != nil {
            return // invalid input is fine — just don't crash
        }
        // Property: re-encoding should round-trip
        encoded := msg.Encode()
        msg2, err := ParseMessage(encoded, msgType)
        if err != nil {
            t.Fatalf("round-trip failed: %v", err)
        }
        if !msg.Equal(msg2) {
            t.Fatalf("round-trip mismatch")
        }
    })
}
```

Corpus management:
- `f.Add(...)` provides inline seeds; file-based seeds go in `testdata/fuzz/FuzzXxx/`
- Without `-fuzz`, `go test` runs seed corpus as fast regression tests (deterministic)
- With `-fuzz` and `-fuzztime`, you get time-boxed generative fuzzing
- Commit `testdata/fuzz/` to the repo as regression corpus

**Rust — `cargo-fuzz` with libFuzzer:**

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = parse_message(data);
});
```

Use `arbitrary::Arbitrary` derive for structure-aware fuzzing. Run with `cargo +nightly fuzz run target -- -max_total_time=300`. Use `--sanitizer none` for pure safe Rust (much faster). Corpus in `fuzz/corpus/`.

**C/C++ — AFL++ or libFuzzer:** Instrument with `afl-clang-fast`, run with `afl-fuzz -V 3600 -i seeds/ -o findings/ -- ./target @@`. Use dictionaries for protocol fuzzing.

### CI integration strategy

The key constraint: fuzzing is open-ended. CI must be time-boxed.

| Trigger | Mode | Duration | Purpose |
|---------|------|----------|---------|
| Every PR | Regression only | Seconds | Run seed corpus — catch known-bad inputs |
| Every PR | Code-change fuzz | 5-10 min | Short generative run on changed code |
| Nightly | Generative fuzz | 30-60 min | Find new bugs with longer runs |
| Weekly | Deep fuzz | 2-8 hours | Thorough exploration, corpus growth |

**Go CI example:**
```yaml
jobs:
  fuzz-regression:
    # Runs seed corpus only — fast, deterministic
    steps:
      - run: go test ./...

  fuzz-generative:
    # Time-boxed generative fuzzing
    if: github.event_name == 'schedule'
    steps:
      - run: |
          for pkg in $(go list ./...); do
            fuzz_funcs=$(go test -list 'Fuzz.*' "$pkg" 2>/dev/null | grep '^Fuzz' || true)
            for func in $fuzz_funcs; do
              go test "$pkg" -fuzz="^${func}$" -fuzztime=60s
            done
          done
```

**ClusterFuzzLite (any language, self-hosted):**
```yaml
- uses: google/clusterfuzzlite/actions/run_fuzzers@v1
  with:
    fuzz-seconds: 600
    mode: code-change  # only fuzz code changed in the PR
```

### Crash handling

When a fuzzer finds a crash:
1. The failing input is saved automatically (`testdata/fuzz/` for Go, `fuzz/artifacts/` for Rust, `findings/crashes/` for AFL++)
2. In Go, the input becomes a regression test automatically — `go test` re-runs it on every future test run
3. Minimize the crashing input (`cargo fuzz tmin`, `afl-tmin`) before committing
4. Fix the bug, verify the regression test passes, commit the minimized input as a permanent regression test

### What fuzzing catches that other testing misses

Real-world examples from OSS-Fuzz, cargo-fuzz, and AFL++:
- **Integer overflows** in size calculations (length fields, allocation sizes)
- **Off-by-one errors** in buffer boundary checks
- **Unhandled enum/tag values** in binary format parsers
- **Denial of service** via algorithmic complexity (quadratic parsing, hash collision)
- **Memory safety at FFI boundaries** (Rust `unsafe`, Go CGo)
- **Round-trip correctness failures** (`decode(encode(x)) != x`)
- **Silent data corruption** in protocol parsers that accept malformed input without error

Google's AI-enhanced OSS-Fuzz found CVE-2024-9143 in OpenSSL — an out-of-bounds write present for ~20 years that "wouldn't have been discoverable with existing fuzz targets written by humans."

### Plan phase requirements

During the plan phase:
1. Identify all components that parse untrusted input at system boundaries
2. For each, decide: is it a fuzz target? Apply the criteria above.
3. Plan fuzz target functions alongside unit tests for each target component
4. Configure CI: regression corpus on every PR, time-boxed generative on schedule
5. Add `testdata/fuzz/` (Go) or `fuzz/corpus/` (Rust) to the project structure
