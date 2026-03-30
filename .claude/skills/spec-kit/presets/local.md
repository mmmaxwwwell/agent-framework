# Preset: Single-User Local Tooling

**Goal**: Enterprise-grade engineering for software that runs locally. Same rigor as production multi-user systems — comprehensive tests, full CI/CD, structured logging, thorough documentation — but scoped to a single-user, non-networked context. No auth, no CORS, no security headers, no rate limiting.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Authentication & authorization (none — single local user)
- CORS policy (not applicable — no web server, or localhost-only)
- Rate limiting & backpressure (not applicable)
- Security headers (not applicable — no HTTP server, or localhost-only)
- Security scanning tiers beyond Tier 1 (skip Tier 2/3 — Tier 1 + Tier 1.5 for public repos included via CI/CD)
- API versioning (none — single consumer)
- Observability infrastructure (skip metrics/tracing — structured logging is sufficient for local tools)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: structured JSON logger at INFO level, stderr output. Include correlation IDs if the tool has multi-step operations or pipelines.
- Error handling: full error hierarchy with clear user-facing messages. No HTTP status mapping, but every error type should have an exit code and a human-readable explanation.
- Configuration: single config module with env var overrides, fail-fast validation on startup. No secret management (no secrets in a local tool).
- Migration: structured migrations with a library if using a database. Auto-migrate on startup with version check.
- Graceful shutdown: include for any long-running process (daemons, watch-mode tools, dev servers). Skip only for pure run-and-exit CLIs. When included, clean up temp files, flush logs, release file locks, close database connections.
- Health checks: `--check` flag for daemons and long-running tools. Skip for pure CLIs.
- CI/CD: GitHub Actions pipeline with lint, build, test (unit + integration), and Tier 1 security scanning (Trivy, Semgrep, Gitleaks, ecosystem audit). Add Snyk + SonarCloud if the repo is public. No deployment stage.
- Branching: direct-to-main — no feature branches, no PRs. Solo developer workflow.
- DX tooling: first-class. Full script inventory (`dev`, `test`, `test:unit`, `test:integration`, `lint`, `lint:fix`, `typecheck`, `build`, `clean`, `clean:all`, `check`, plus `db:*` and `codegen` if applicable). `.env.example`. VS Code `launch.json` with debugger configs. Environment isolation via Nix flake (if `nix` is available — `flake.nix`, `.envrc` with `use flake`, `.direnv/` gitignored); otherwise devcontainer. CLAUDE.md development section. Skip HTTPS dev certs and proxy config unless the project has separate frontend/backend.

**Still ask about**:
- Core functionality, user workflows, data model
- Non-goals — "anything this tool should deliberately NOT do?" Important for local tools where scope creep adds unnecessary complexity.
- Edge cases for data loss scenarios (local tools can't recover from cloud backup)
- Persistence strategy (SQLite, filesystem, in-memory)
- CLI UX (flags, subcommands, interactive prompts, output formatting)
- Platform compatibility (Linux only? macOS? Windows?)
- Process architecture (single process? spawns child processes? watch mode? daemon?)
- Operational workflows — for daemons and long-running tools: day-1 setup, day-2 operations (add/remove/restart/debug), failure recovery, admin processes. Skip for pure run-and-exit CLIs.

**Interview style**: 5-10 questions. Focus on UX, data integrity, and workflows. Propose sensible defaults and confirm.

## Spec phase overrides

- **FR/SC numbering**: required
- **Examples on FRs**: mandatory on any FR flagged during analyze; optional on clear FRs
- **Non-Goals section**: required — document intentional omissions with rationale
- **Operational workflows**: required for daemons/long-running tools; skip for pure CLIs
- **Enterprise Infrastructure section**: include for: logging, error handling, config, graceful shutdown (if applicable), CI/CD. Skip: auth, CORS, security headers, rate limiting, observability infrastructure.
- **Edge Cases & Failure Modes**: full coverage for: data loss, corrupt state, concurrent access, file system errors, invalid input, resource exhaustion (disk full, OOM), interrupted operations (Ctrl-C mid-write). Skip network/auth/rate-limit categories.
- **Testing section**: full — unit tests for core logic, integration tests for data persistence and CLI behavior, edge case tests for failure modes. Security scanning is handled by CI (Tier 1 tools), not custom security tests. Skip contract/e2e unless the tool has an IPC/plugin API or a UI.
- **UI_FLOW.md**: include if the project has a UI (desktop app, TUI with multiple screens). Skip for pure CLIs with no interactive UI.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: full — custom structured reporter and test-logs/ directory. The fix-validate loop needs structured output to diagnose failures efficiently, regardless of whether the tool is local or networked.
- **Phase 2 Foundational**: include error hierarchy, config module, structured logging, CI/CD pipeline (lint + test + Tier 1 security scan), Gitleaks pre-commit hook. Include graceful shutdown for long-running tools. Skip health checks (unless daemon), skip observability infrastructure.
- **research.md**: full depth — document every decision with rationale and rejected alternatives, same as enterprise. Local tools make just as many architecture decisions; cutting corners here means implementing agents guess.
- **data-model.md**: full depth — ERDs, field tables, state transitions, cross-entity constraints. Local tools often have complex local state (SQLite, filesystem hierarchies) that's harder to debug than a networked database.
- **API contract depth**: skip unless the tool has an IPC/plugin API or CLI subcommand interface complex enough to warrant formal contracts
- **Complexity Tracking**: required — local tools should stay simple; track every abstraction
- **Phase Dependencies**: required — with dependency graph and parallelization strategy
- **Interface contracts**: required for projects with 2+ tasks sharing state. Load `reference/interface-contracts.md`.
- **Runtime state machines**: required if the project has daemons, protocol handshakes, or connection management. Skip for pure CLIs.
- **Critical path (user perspective)**: required — identify the day-1 user flow and incremental integration checkpoints
- **Test plan matrix**: required — map every SC-xxx to test tier, fixture, assertion, infrastructure

## Task phase overrides

- **Fix-validate loop**: required — per phase, runner-enforced
- **`[P]` parallel markers**: include where applicable
- **Done criteria**: required on every task — verifiable, additive, 1-3 bullets
- **Interface contract tags**: required — `[produces: IC-xxx]` / `[consumes: IC-xxx]` on tasks that share state
- **Critical path checkpoints**: required — growing integration test tasks at critical-path phase boundaries
- **FR/Story traceability**: required on every task
- **Non-goals awareness**: reference spec's Non-Goals in approach note
- **Spec amendment process**: supported — agents write AMENDMENT files when spec premises are wrong
- **learnings.md**: required
- **Code review**: full — auto-implement necessary fixes, write REVIEW-TODO.md, run fix-validate loop after
- **Approach note**: `Approach: TDD with fix-validate loop per phase. Full CI/CD with Tier 1 security scanning. Enterprise-grade test infrastructure, structured logging, comprehensive error handling. No auth, no network hardening — local single-user tool. See Non-Goals for intentional omissions.`

## What the agent should still know

The full SKILL.md is loaded. If the user later says "actually this needs to be a web service" or "I want to add multi-user support", the agent can reference the enterprise/public sections and guide the transition. The principle: **local doesn't mean low quality — it means scoped. The engineering rigor is the same; only the scope of concerns is narrower.**
