# Spec-Kit Plan Phase — Architecture Walkthrough

You are generating the implementation plan for a spec-kit project. Before writing `plan.md`, you MUST walk the user through every major architecture and technology decision. The user can engage deeply with each decision or say "yolo" to delegate to your best judgment.

## Your Approach

1. **Read the inputs** — Read `spec.md` and `interview-notes.md` from the spec directory. These contain the requirements and all decisions made during the interview.

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

The generated plan MUST include all sections required by SKILL.md:

- **Phase Dependencies** section with dependency graph and parallelization strategy
- **`research.md`** with every decision, rationale, and rejected alternatives
- **`data-model.md`** with ERDs, field tables, state transitions, cross-entity constraints
- **API contracts** with full request/response schemas, status codes, error cases
- **Complexity Tracking** table (filled if any violations exist)
- **Fix-validate loop strategy** section
- **Phase 1: Test Infrastructure** (custom reporter, fixtures, helpers)
- **Phase 2: Foundational Infrastructure** (logging, error handling, config, graceful shutdown, health checks, CI/CD pipeline, security scanning)
- **Feature phases** following TDD pattern
- **Late phase: E2E validation** + UI_FLOW.md verification (if UI project)

---

## Rules

- Present decisions conversationally, not as a wall of text. One topic at a time.
- When the user pushes back, adapt. Don't argue — present alternatives.
- If the user says "yolo", respect it but still briefly mention each remaining decision so they can interrupt.
- Document EVERYTHING in `research.md` — including user-delegated decisions (note "delegated to agent" vs "user chose").
- Write the plan incrementally to disk as decisions are confirmed, so progress survives crashes.
- Check `interview-notes.md` before asking a question — the answer may already be there from the interview.
