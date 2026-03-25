# Preset: Single-User Public-Facing

**Goal**: Build a reliable application for one user that is exposed to the internet. No multi-user auth, but hardened against public exposure — input validation, security headers, rate limiting, and HTTPS.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Authentication & authorization (none — single user, but note: if admin endpoints exist, recommend basic auth or API key)
- Observability (skip metrics/tracing — structured logging is sufficient)
- Process architecture & statefulness (single process is fine at single-user scale)
- Config versioning (skip)
- API versioning (none — single consumer)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: structured JSON logger, INFO level, correlation IDs on requests
- Error handling: full error hierarchy with HTTP status mapping (public-facing errors must be sanitized)
- Configuration: single config module, env vars for secrets, fail-fast validation
- CORS: restrictive (specific origin — the user's domain)
- Security headers: full baseline set (HSTS, CSP, X-Content-Type-Options, etc.)
- Rate limiting: basic per-IP rate limit on all endpoints (prevent abuse from bots/crawlers)
- Graceful shutdown: yes, 30s timeout
- Health checks: `/health` endpoint only (no `/ready` — single instance, no load balancer)
- Security scanning: Tier 1 only (free tools — Trivy, Semgrep, Gitleaks, ecosystem audit)
- CI/CD: GitHub Actions with lint + test + security scan. No deployment pipeline (user deploys manually or asks later).
- Migration: structured migrations with a library. Seed script for dev bootstrapping.

**Still ask about**:
- Core functionality, user workflows, data model
- API design and real-time requirements
- UI flows (if applicable)
- Edge cases — focus on: invalid input, network failure, resource exhaustion, duplicate operations
- Persistence strategy and backup approach (single user = data loss is catastrophic)
- Deployment target (VPS, container, serverless)
- Domain and HTTPS strategy (Let's Encrypt, Cloudflare, etc.)
- Branching strategy — present both options: feature branches with PRs (review checkpoints, easy rollback) vs direct-to-main (faster for solo). Recommend feature branches since this is public-facing, but accept main-branch if the user prefers.
- DX tooling — confirm task runner, dev server details (proxy config if separate frontend/backend, HTTPS dev certs if OAuth/service workers), codegen pipeline if applicable. Full script inventory.

**Interview style**: 8-12 questions. Focus on core features, security posture, and data durability. Present security defaults as non-negotiable ("since this is public-facing, I'm including X") and let the user push back if they want.

## Spec phase overrides

- **FR/SC numbering**: required
- **Enterprise Infrastructure section**: include, but only for: logging, error handling, config, security (headers + input validation + scanning), rate limiting, graceful shutdown, health check, CI/CD. Skip observability, process architecture.
- **Edge Cases & Failure Modes**: include — public-facing apps encounter hostile input. Focus on: invalid input, injection attempts, timeout, crash recovery, resource exhaustion, duplicate operations.
- **Testing section**: full — unit, integration, and contract tests. Skip e2e unless the project has a UI. Include input validation and security header tests.
- **Security warnings**: yes — if the user tries to skip input validation or security headers, warn about specific attack vectors.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: include — structured test output helps the fix-validate loop
- **Phase 2 Foundational**: include error hierarchy, config module, security headers middleware, input validation middleware, rate limiting, graceful shutdown, health endpoint, CI/CD pipeline, basic security scanning. Skip observability infrastructure.
- **research.md**: include — document security and architecture decisions
- **data-model.md**: include with full depth
- **API contract depth**: include — public APIs need clear contracts
- **Complexity Tracking**: include
- **Phase Dependencies**: include

## Task phase overrides

- **Fix-validate loop**: required
- **`[P]` parallel markers**: include if applicable
- **FR/Story traceability**: required
- **learnings.md**: include
- **Code review**: include — full auto-implement + REVIEW-TODO.md + fix-validate loop. Security findings are especially important for public-facing apps.
- **Approach note**: `Approach: TDD with fix-validate loop. Public-facing hardening: input validation, security headers, rate limiting, sanitized error responses. Single-user, no auth.`

## What the agent should still know

The full SKILL.md is loaded. This preset is one step below enterprise — it has security hardening but skips multi-user auth, observability, and advanced CI/CD. If the user later needs auth or multi-user support, the agent can reference the enterprise sections. The key principle: **anything exposed to the internet gets input validation, security headers, and rate limiting — no exceptions.**
