# Spec-Kit Plan Phase — Architecture Walkthrough

You are generating the implementation plan for a spec-kit project. Before writing `plan.md`, you MUST walk the user through every major architecture and technology decision. The user can engage deeply with each decision or say "yolo" to delegate to your best judgment.

## Preset awareness

Read `interview-notes.md` for the `preset:` line. Then read the corresponding preset file from `presets/<preset>.md` (relative to the spec-kit skill directory). The preset overrides the plan requirements below — it tells you which foundational phases to skip, which documentation depth to require, and which sections are optional. **Follow the preset overrides.** The checklist below is the full enterprise list; the preset narrows it.

## Your Approach

1. **Read the inputs** — Read these from the spec directory:
   - `spec.md` — requirements and all decisions from the interview
   - `interview-notes.md` — key decisions, user pushbacks, preset, Nix availability
   - `learnings.md` (if it exists from a prior feature) — gotchas and patterns from previous implementations that may inform architecture decisions

2. **Read the plan template** — Read the plan template from `.specify/commands/` or `.specify/templates/` to understand the expected output format.

3. **Research phase** — Before presenting decisions to the user, do your homework:
   - Read the constitution (`.specify/memory/constitution.md`) for architectural principles
   - Research the tech stack: best practices, library comparisons, performance benchmarks
   - Look at the spec's enterprise infrastructure decisions from the interview
   - Identify every decision point that affects architecture

4. **Walk through every decision** — Present each architecture and technology decision to the user one at a time (or in logical groups). For each decision:
   - State what needs to be decided
   - Present your recommendation with specific rationale
   - List alternatives you considered and why you'd reject them
   - Note any constitution principles that apply
   - Ask: "Does this work, or would you like to go a different direction?"

5. **Accept "yolo"** — If the user says "yolo", "you pick", "whatever you think is best", or similar:
   - Acknowledge it
   - Use your best judgment for ALL remaining decisions
   - Document that the user delegated the decision (not that they chose it)
   - Continue presenting decisions briefly (one-liner each) so the user can interrupt if they care about a specific one

6. **Write the plan** — Once all decisions are made, generate the full plan with all required sections.

---

## Decision Walkthrough Checklist

Present these in order. Skip items marked N/A in the spec.

### Technology stack
- **Language/runtime version** — Confirm or adjust what was decided in the interview
- **Package manager** — npm, yarn, pnpm, uv, cargo, etc.
- **Build tooling** — Compiler, bundler, dev server
- **Framework** (if any) — Present alternatives with trade-offs

### Data layer
- **Storage backend** — Database, filesystem, in-memory, hybrid
- **ORM/query layer** — Direct queries, query builder, ORM — with rationale
- **Migration library** — Confirm the interview decision
- **Caching strategy** — If applicable

### API layer
- **HTTP framework** (or decision to go frameworkless) — Present alternatives
- **API style** — REST, GraphQL, RPC, hybrid
- **Serialization** — JSON, Protocol Buffers, MessagePack
- **Real-time** — WebSocket library, SSE, polling strategy

### Infrastructure decisions
- **Logging** — Confirm library from interview, present any adjustments
- **Error handling** — Present the error hierarchy customized for this project
- **Config management** — Config file format, secret management approach
- **Auth** — Confirm strategy, present implementation approach (library, middleware pattern)
- **Security headers** — Present the baseline set, note any project-specific additions
- **Graceful shutdown** — Confirm timeout, present the cleanup order for this specific project
- **Health checks** — Confirm active vs. cached probes, dependency list

### Testing strategy
- **Test runner** — Native test runner, Jest, Vitest, pytest, etc.
- **Custom reporter** — For structured test output (required by fix-validate loop)
- **Test tiers** — Unit, integration, contract, e2e — what goes where
- **Test fixtures** — Real servers, test databases, mock boundaries
- **Concurrency** — Parallel unit tests, sequential integration tests

### CI/CD
- **Pipeline structure** — Confirm stages from interview
- **Security scanning tools** — Confirm tier selection
- **Quality gates** — What blocks merges
- **Agentic CI feedback** — How agents access CI logs, auto-push policy
- **SBOM format** — CycloneDX or SPDX

### Deployment (if applicable)
- **Target environment** — Bare metal, containers, serverless, etc.
- **Container strategy** — Dockerfile, multi-stage builds, base images
- **Orchestration** — Kubernetes, Docker Compose, systemd, etc.

### Project structure
- **Directory layout** — Present the tree, explain the reasoning
- **Module boundaries** — How code is organized (by feature, by layer, hybrid)
- **Shared code** — How utilities/helpers are organized

### Observability
- **Metrics library** — Confirm from interview
- **Trace propagation** — Header format, context passing strategy
- **Error reporting** — Sentry, log-based, or hybrid
- **Dashboard** — Where metrics/traces are visualized

### Versioning
- **API versioning** — Confirm URL path versioning + latest alias
- **Semver policy** — How agents determine patch/minor/major
- **Changelog** — Auto-generated or manual

---

## Constitution compliance check

After all decisions are made but before writing the plan:

1. Review every decision against the constitution principles
2. Flag any violations
3. For each violation, add a row to the Complexity Tracking table with justification
4. Present violations to the user: "This decision violates Constitution principle X because Y. Here's why I think it's justified: Z. Agree?"

---

## Plan output requirements

**MANDATORY: Load the reference file BEFORE writing each plan section.** The reference files define the minimum depth and required structure for each output artifact. Writing a plan section without loading its reference will produce shallow output that downstream agents can't implement from.

| Plan section | Reference file | Load BEFORE writing |
|-------------|---------------|---------------------|
| Test infrastructure / fix-validate strategy | `reference/testing.md` | Phase 1 plan section |
| Foundational infrastructure: logging | `reference/logging.md` | Phase 2 logging task description |
| Foundational infrastructure: error handling | `reference/errors.md` | Phase 2 error handling task description |
| Foundational infrastructure: config | `reference/config.md` | Phase 2 config task description |
| Foundational infrastructure: shutdown | `reference/shutdown.md` | Phase 2 graceful shutdown task description |
| Foundational infrastructure: health checks | `reference/health.md` | Phase 2 health check task description |
| Foundational infrastructure: CI/CD | `reference/cicd.md` | Phase 2 CI/CD task description |
| Foundational infrastructure: security scanning | `reference/security.md` | Phase 2 security task description |
| Foundational infrastructure: DX tooling | `reference/dx.md` | Phase 2 DX task description |
| Data model documentation | `reference/data-model.md` | `data-model.md` generation |
| API contracts | `reference/api-contracts.md` | Contract documentation generation |
| Phase dependencies | `reference/phase-deps.md` | Phase Dependencies section |
| Complexity tracking | `reference/complexity.md` | Complexity Tracking table |
| Idempotency & readiness | `reference/idempotency.md` | Setup task descriptions |
| Edge case → test mapping | `reference/edge-cases.md` | Mapping enumerated edge cases to test scenarios |
| Traceability | `reference/traceability.md` | Grouping plan by user story/FR for downstream task traceability |

**Conditional loads — check the spec and load only if applicable:**
- **If the project has a UI**: load `reference/ui-flow.md` before planning UI phases. Include UI_FLOW.md creation as an early task and incremental updates per phase.
- **If the project has persistent state** (database, filesystem, in-memory with durability): load `reference/data-model.md` before writing `data-model.md`. Skip if no persistence.
- **If the project has an API, IPC protocol, or real-time channels**: load `reference/api-contracts.md` before writing contract documentation. Skip if no external interfaces.
- **If the project spawns external processes** (CLI tools, agents, child workers): load `reference/testing.md` and include stub-process creation and integration tests for the spawn → stdin → stdout → exit lifecycle. Check the spec's functional requirements for external process interfaces.
- **If the project has external service dependencies** (databases, emulators, message queues): load `reference/idempotency.md` and plan readiness-check scripts for each dependency.

**Skip reference loads for topics the preset says to skip.** But for any section you're writing, the reference defines the quality bar — load it first.

The generated plan MUST include (subject to preset overrides):

- **Phase Dependencies** section with dependency graph and parallelization strategy
- **`research.md`** with every decision, rationale, and rejected alternatives (see "Architecture Rationale Depth" below)
- **`data-model.md`** with ERDs, field tables, state transitions, cross-entity constraints
- **API contracts** with full request/response schemas, status codes, error cases
- **Complexity Tracking** table (filled if any violations exist)
- **Fix-validate loop strategy** section
- **Phase 1: Test Infrastructure** (custom reporter, fixtures, helpers)
- **Smoke test phase** early — confirm the most basic thing works (server boots, app loads) before diving into test suites
- **Phase 2: Foundational Infrastructure** (logging, error handling, config, graceful shutdown, health checks, CI/CD pipeline, security scanning)
- **Feature phases** following TDD pattern
- **Late phase: E2E validation** — exercise real flows after all unit/integration tests pass. UI_FLOW.md verification if UI project

---

## Downstream agent effectiveness

The plan you produce is the primary input for task generation and implementation. Decisions and rationale captured here prevent implementing agents from guessing, over-engineering, or writing BLOCKED.md.

### Architecture Rationale Depth — what `research.md` MUST contain

For every major decision (framework, database, auth strategy, deployment model, IPC mechanism, UI framework, test runner, logging library, etc.):

1. **The decision**: What was chosen (e.g., "Raw `http.createServer` with route Map")
2. **Rationale**: Why it was chosen, with specific reasoning tied to project constraints (e.g., "API surface is ~16 endpoints; a framework adds unnecessary abstraction and violates Constitution V: Simplicity")
3. **Alternatives rejected**: At least one alternative considered and why (e.g., "Express: unnecessary middleware overhead for this API surface; Fastify: adds dependency for no measurable benefit")

**How different agent roles use `research.md`:**
- **Implementing agents**: Before reaching for a library or pattern not mentioned in the plan, check `research.md` to see if it was already considered and rejected
- **Fix-validate agents**: Before changing an architectural approach to fix a test failure, check `research.md` to understand *why* the current approach was chosen. Fix within the chosen architecture unless the rationale is provably wrong
- **Code review agents**: Flag deviations from `research.md` decisions as potential issues

### Auto-unblocking context
Implementing agents consult `research.md` and `interview-notes.md` before attempting to resolve blockers autonomously (see `phases/implement.md`). This means `research.md` must also document:
- **User preferences and pushbacks** from the interview — agents filter candidate solutions against these
- **Constraint reasoning** — not just "we chose X" but "we chose X because the user said Y and the constitution requires Z"

### Complexity tracking
Any design decision that introduces abstraction beyond the simplest approach MUST either confirm it doesn't violate constitution principles, or add a row to the Complexity Tracking table. Don't gate this behind "violations only" — proactively evaluate every abstraction, interface, and indirection layer.

### External process boundary testing
If the project spawns external processes, the plan MUST include tasks for stub-process creation and integration tests that exercise the spawn → stdin → stdout → exit lifecycle. See `reference/testing.md`.

### UI_FLOW.md
If the project has a UI, the plan MUST include: creation of `UI_FLOW.md` as an early task, incremental updates as each phase adds screens/routes, and a late-phase task to verify all flows have e2e tests. See `reference/ui-flow.md`.

### Specification traceability
Every task generated from this plan must reference the FR/SC it implements. The plan should group work by user story or functional requirement to make this mapping natural. See `reference/traceability.md`.

---

## Nix-first coordination

Check `interview-notes.md` for `Nix available: yes/no`. If Nix is available:
- **Phase 1 (Setup) MUST include a `flake.nix` creation task** with `devShells.default` providing all tools, runtimes, and backing services
- `.envrc` with `use flake` for auto-activation; `.direnv/` gitignored
- Prefer `process-compose` or `devenv` over Docker Compose for backing services
- All tool installations go in `flake.nix` — no `nvm`, `pyenv`, `rbenv`, etc.
- `flake.lock` committed for reproducibility

If Nix is NOT available: fall back to Docker/devcontainers.

## Blocker handling during planning

If you encounter ambiguity or contradiction in the spec during planning:
1. **Check `interview-notes.md`** for the user's stated preferences — they may resolve the ambiguity
2. **Check `research.md`** (if it exists from a prior iteration) for rejected alternatives
3. **Ask the user directly** — planning is interactive, so ambiguities can be resolved in conversation
4. **Document the resolution** in `research.md` with rationale so implementing agents don't re-encounter it

Do NOT write BLOCKED.md during the plan phase — you have the user in the conversation.

## Rules

- Present decisions conversationally, not as a wall of text. One topic at a time.
- When the user pushes back, adapt. Don't argue — present alternatives.
- If the user says "yolo", respect it but still briefly mention each remaining decision so they can interrupt.
- Document EVERYTHING in `research.md` — including user-delegated decisions (note "delegated to agent" vs "user chose").
- Write the plan incrementally to disk as decisions are confirmed, so progress survives crashes.
- Check `interview-notes.md` before asking a question — the answer may already be there from the interview.
