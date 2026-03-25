# Preset: Single-User Public-Facing

**Goal**: Enterprise-grade engineering for a single-user application exposed to the internet. Same rigor as multi-user production systems — comprehensive tests, full CI/CD, structured logging, thorough documentation, complete security hardening — but scoped to a single-user context. No multi-user auth, no observability infrastructure, no complex process architecture.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Authentication & authorization (none — single user, but note: if admin endpoints exist, recommend basic auth or API key)
- Observability infrastructure (skip metrics/tracing — structured logging with correlation IDs is sufficient)
- Process architecture & statefulness (single process is fine at single-user scale)
- Config versioning (skip)
- API versioning (none — single consumer)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: structured JSON logger, INFO level, correlation IDs on requests
- Error handling: full error hierarchy with HTTP status mapping (public-facing errors must be sanitized — never leak stack traces, internal paths, or database details)
- Configuration: single config module, env vars for secrets, fail-fast validation on startup
- CORS: restrictive (specific origin — the user's domain)
- Security headers: full baseline set (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy)
- Input validation: at every system boundary — validate types, lengths, formats, and sanitize for output context
- Rate limiting: per-IP rate limit on all endpoints (prevent abuse from bots/crawlers)
- Graceful shutdown: yes, 30s timeout, clean up connections/file handles/database
- Health checks: `/health` endpoint (no `/ready` — single instance, no load balancer)
- Security scanning: Tier 1 + Tier 1.5 for public repos (Trivy, Semgrep, Gitleaks, Snyk, SonarCloud, OpenSSF Scorecard, ecosystem audit)
- CI/CD: GitHub Actions with lint, build, test (unit + integration + contract), security scan, SBOM generation. No deployment pipeline (user deploys manually or asks later).
- Migration: structured migrations with a library. Seed script for dev bootstrapping.
- Branching: recommend feature branches with PRs (review checkpoints, easy rollback) since this is public-facing, but accept direct-to-main if the user prefers solo workflow.
- DX tooling: full scope — one-command dev, complete script inventory, dev server with HMR, proxy config if separate frontend/backend, HTTPS dev certs if OAuth/service workers, VS Code `launch.json`, Nix flake environment isolation, CLAUDE.md development section.

**Still ask about**:
- Core functionality, user workflows, data model
- API design and real-time requirements
- UI flows (if applicable)
- Edge cases — focus on: invalid input, injection attempts, network failure, resource exhaustion, duplicate operations, crash recovery
- Persistence strategy and backup approach (single user = data loss is catastrophic)
- Deployment target (VPS, container, serverless)
- Domain and HTTPS strategy (Let's Encrypt, Cloudflare, etc.)

**Interview style**: 8-12 questions. Focus on core features, security posture, and data durability. Present security defaults as non-negotiable ("since this is public-facing, I'm including X") and let the user push back if they want.

## Spec phase overrides

- **FR/SC numbering**: required
- **Enterprise Infrastructure section**: full for: logging, error handling, config, security (headers + input validation + scanning), rate limiting, graceful shutdown, health check, CI/CD. Skip: observability infrastructure, process architecture.
- **Edge Cases & Failure Modes**: full coverage — public-facing apps encounter hostile input. Include: invalid input, injection attempts (SQL, XSS, command), timeout, crash recovery, resource exhaustion, duplicate operations, file upload abuse, malformed requests.
- **Testing section**: full — unit, integration, and contract tests. Include input validation tests and security header verification. Skip e2e unless the project has a UI. Skip dedicated security penetration tests (CI scanning covers this).
- **UI_FLOW.md**: include if the project has a UI — required for public-facing apps with screens/routes.
- **Security warnings**: yes — if the user tries to skip input validation or security headers, warn about specific attack vectors.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: full — custom structured reporter and test-logs/ directory. The fix-validate loop needs structured output.
- **Phase 2 Foundational**: full for: error hierarchy, config module, structured logging with correlation IDs, security headers middleware, input validation middleware, rate limiting, graceful shutdown, health endpoint, CI/CD pipeline with full security scanning, Gitleaks pre-commit hook. Skip: observability infrastructure (metrics, tracing, dashboards).
- **research.md**: full depth — document every decision with rationale and rejected alternatives. Security decisions especially need clear rationale so implementing agents don't weaken them.
- **data-model.md**: full depth — ERDs, field tables, state transitions, cross-entity constraints
- **API contract depth**: full — public APIs need clear contracts with request/response schemas, status codes, error cases, rate limit headers
- **Complexity Tracking**: required
- **Phase Dependencies**: required — with dependency graph and parallelization strategy

## Task phase overrides

- **Fix-validate loop**: required — per phase, runner-enforced
- **`[P]` parallel markers**: include where applicable
- **FR/Story traceability**: required on every task
- **learnings.md**: required
- **Code review**: full — auto-implement necessary fixes, write REVIEW-TODO.md, run fix-validate loop after. Security findings are especially important for public-facing apps.
- **Approach note**: `Approach: TDD with fix-validate loop per phase. Full CI/CD with Tier 1 + Tier 1.5 security scanning. Public-facing hardening: input validation, security headers, rate limiting, sanitized error responses. Enterprise-grade test infrastructure and documentation. Single-user, no multi-user auth.`

## What the agent should still know

The full SKILL.md is loaded. This preset is enterprise-grade with a narrower scope — it has full security hardening, comprehensive tests, and thorough documentation, but skips multi-user auth, observability infrastructure, and complex process architecture. If the user later needs auth or multi-user support, the agent can reference the enterprise sections and guide the transition. The key principle: **anything exposed to the internet gets the full security treatment — input validation, security headers, rate limiting, sanitized errors — no exceptions. The only thing we skip is infrastructure that only matters at multi-user scale.**
