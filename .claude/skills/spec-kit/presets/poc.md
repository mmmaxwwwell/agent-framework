# Preset: POC (Proof of Concept)

**Goal**: Get a working prototype as fast as possible. Skip infrastructure and process overhead, but never skip things that help agents make informed decisions. The POC preset is the only preset that trades engineering rigor for speed — every other preset is enterprise-grade with different scope.

**Design principle**: FR numbering, traceability, and learnings cost near-zero time but prevent agents from guessing wrong and wasting runs. Include them. Skip everything that adds setup time without proving the concept works.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Logging library (use `console.log` / `print` / language default)
- Error handling strategy (use language defaults — throw/catch, no hierarchy)
- Configuration management (hardcode or use env vars directly, no config module)
- Authentication & authorization (none)
- CORS policy (allow all — `*`)
- Rate limiting & backpressure (none)
- Observability (none)
- Migration & data seeding (none — use auto-create/schema sync, no migrations)
- API versioning (none — single unversioned path)
- CI/CD pipeline (none)
- Security scanning (none)
- Graceful shutdown (none)
- Health checks (none)
- Config versioning (none)
- Security headers (none)
- Process architecture & statefulness (default to simplest — single process, in-memory state is fine)
- Branching strategy (default to main branch — no feature branches, no PRs)

**Default without asking**:
- DX tooling: `dev` script only. `.env.example` if env vars are used. No debugging configs, no codegen pipeline, no `clean:all`. Skip the full script inventory.

**Still ask about** (keep the interview focused on what matters):
- Core functionality, user workflows, data model
- API design and real-time requirements (if applicable)
- UI flows (if applicable)
- Edge cases for core happy-path flows — ask "what should happen when X fails?" for each major flow. Skip exhaustive failure mode enumeration, but don't skip edge cases entirely — agents need these answers when they encounter ambiguity during implementation.

**Interview style**: 3-5 questions max. Propose aggressively — suggest the simplest viable architecture and ask "does this work?" rather than exploring options. Default to the user's stack if stated, otherwise pick the most productive stack for the domain.

## Spec phase overrides

- **FR/SC numbering**: use it — costs nothing, prevents agents from guessing which requirement a task serves
- **No Enterprise Infrastructure section** — omit entirely
- **Edge Cases & Failure Modes**: include a lightweight version — one-liner per major flow describing the expected behavior on failure. Skip the full 11-category enumeration. Agents need *something* to reference when they hit an edge case during implementation, otherwise they guess or write BLOCKED.md.
- **Testing section**: minimal — list what the happy-path tests should cover, skip contract/e2e/security test requirements
- **UI_FLOW.md**: skip — too much overhead for a POC. If the project has a UI, just document screens in the spec.
- **No security warnings** for skipped items — the user chose POC, don't lecture

## Plan phase overrides

- **No Phase 1 Test Infrastructure** — skip custom test reporters, structured test output, test-logs/ directory
- **No Phase 2 Foundational Infrastructure** — skip logging, error hierarchy, config module, graceful shutdown, health checks, CI/CD, security scanning
- **research.md**: include but keep ultra-brief — one paragraph per major decision (language, framework, database) with the rationale. Prevents downstream agents from second-guessing choices and wasting runs on rewrites.
- **No data-model.md depth requirements** — a simple field list or schema snippet is sufficient
- **No API contract depth requirements** — endpoint list with example request/response is enough
- **No Complexity Tracking table**
- **No Phase Dependencies section** — run everything serially
- **Phases**: Setup → Feature implementation → Basic smoke tests
- **Testing strategy**: basic tests that prove core flows work. No TDD requirement. Tests can be written after implementation.

## Task phase overrides

- **No fix-validate loop** — just implement and test at the end
- **No `[P]` parallel markers needed** — everything runs serially
- **FR/Story traceability**: include — costs nothing (just a `[FR-001]` suffix on each task), but lets agents look up *why* a task exists when they encounter ambiguity during implementation
- **learnings.md**: include — each agent appends gotchas and decisions. Without this, later agents rediscover the same issues, wasting runs. The file is tiny and the write cost is near-zero.
- **No code review task** — skip automatic code review entirely. Ship it.
- **Approach note**: `Approach: Implement core features, then add basic tests to verify happy paths. Lightweight traceability (FR IDs + learnings.md) to keep agents informed.`

## What the agent should still know

The agent has the full SKILL.md loaded. It understands enterprise patterns exist. If the user asks "should I add logging?" or "what about auth?", the agent can reference the enterprise knowledge in SKILL.md and suggest the right approach — but it should frame it as "when you're ready to harden this, here's what to add" rather than blocking progress now.

**Upgrading from POC**: When the user is ready to move beyond POC, recommend the **local** preset (for non-networked tools) or **public** preset (for internet-exposed apps). Both are enterprise-grade and will fill in everything POC skipped. The agent reads the existing spec and interview-notes, identifies what the new preset adds, and walks through only the new decisions.
