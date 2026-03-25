# Preset: Single-User Local Tooling

**Goal**: Build reliable local-only software for one user. No network exposure, no auth, but solid enough for daily use.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Authentication & authorization (none — single local user)
- CORS policy (not applicable — no web server, or localhost-only)
- Rate limiting & backpressure (not applicable)
- Security headers (not applicable — no HTTP server, or localhost-only)
- Security scanning tiers (skip Tier 2/3 — use only ecosystem-native: `npm audit` / `pip audit` etc.)
- API versioning (none — single consumer)
- Graceful shutdown (skip for CLIs; include for long-running daemons only if applicable)
- Health checks (skip for CLIs; `--check` flag for daemons)
- Observability (skip metrics/tracing — logging is sufficient)
- Process architecture & statefulness (single process, local state is fine)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: language-default structured logger at INFO level, stderr output. No correlation IDs.
- Error handling: simple error hierarchy (AppError → ValidationError, NotFoundError, InternalError). No HTTP status mapping.
- Configuration: single config file + env var overrides. No secret management (no secrets in a local tool).
- Migration: auto-create schema on first run if using a database. Simple version check + auto-migrate.
- CI/CD: none (recommend GitHub Actions lint + test if user asks)
- Branching: direct-to-main — no feature branches, no PRs. Solo developer workflow.
- DX tooling: first-class. Full script inventory (`dev`, `test`, `test:unit`, `test:integration`, `lint`, `lint:fix`, `typecheck`, `build`, `clean`, `clean:all`, `check`, plus `db:*` and `codegen` if applicable). `.env.example`. VS Code `launch.json` with debugger configs. Environment isolation (Nix/devcontainer if the user uses them). CLAUDE.md development section. Skip HTTPS dev certs and proxy config unless the project has separate frontend/backend.

**Still ask about**:
- Core functionality, user workflows, data model
- Edge cases for data loss scenarios (local tools can't recover from cloud backup)
- Persistence strategy (SQLite, filesystem, in-memory)
- CLI UX (flags, subcommands, interactive prompts, output formatting)
- Platform compatibility (Linux only? macOS? Windows?)

**Interview style**: 5-10 questions. Focus on UX, data integrity, and workflows. Propose sensible defaults and confirm.

## Spec phase overrides

- **FR/SC numbering**: use it — local tools benefit from clear requirements
- **Enterprise Infrastructure section**: minimal — only document logging and error handling decisions
- **Edge Cases & Failure Modes**: include for data loss, corrupt state, concurrent access (if the tool uses file locks or a database). Skip network/auth/rate-limit categories.
- **Testing section**: unit tests for core logic, integration tests for data persistence and CLI behavior. Skip contract/e2e/security test requirements.
- **UI_FLOW.md**: include if the project has a UI (desktop app, TUI with multiple screens). Skip for pure CLIs with no interactive UI.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: lightweight — use the test runner's built-in reporter. Skip custom structured reporter and test-logs/ directory unless the project is complex enough to warrant it.
- **Phase 2 Foundational**: include error hierarchy and config module. Skip graceful shutdown, health checks, CI/CD, security scanning.
- **research.md**: include but keep brief — document key technology choices only
- **data-model.md**: include — local tools need clear schemas, especially for SQLite/filesystem state
- **API contract depth**: skip unless the tool has an IPC/plugin API
- **Complexity Tracking**: include (local tools should stay simple)
- **Phase Dependencies**: include if >3 phases, otherwise skip

## Task phase overrides

- **Fix-validate loop**: use it — local tools benefit from solid tests
- **`[P]` parallel markers**: include if applicable
- **FR/Story traceability**: include
- **learnings.md**: include
- **Code review**: include — auto-implement necessary fixes, write REVIEW-TODO.md, run fix-validate loop after
- **Approach note**: `Approach: TDD for core logic. Fix-validate loop per phase. No auth, no network hardening — local single-user tool.`

## What the agent should still know

The full SKILL.md is loaded. If the user later says "actually this needs to be a web service" or "I want to add multi-user support", the agent can reference the enterprise sections and guide the transition. For now, optimize for a robust local tool with good tests and clear error messages.
