# spec-kit Skill

A wrapper around [spec-kit](https://github.com/github/spec-kit) (`specify` CLI) that adds the discipline needed to make Specification-Driven Development work with autonomous agents. Spec-kit gives you the workflow — this skill gives you the guardrails.

## Why this exists

Spec-kit's SDD workflow (specify → clarify → plan → tasks → implement) is powerful, but its templates are intentionally open-ended. An agent running the vanilla workflow can produce shallow specs, vague data models, and incomplete test coverage — and still technically follow the process. When those specs drive autonomous implementation via the task runner, the gaps compound: agents guess at edge cases, write inconsistent tests, over-engineer without justification, and write BLOCKED.md for problems they could solve themselves.

This skill closes those gaps by mandating minimum depth at every phase and baking enterprise-grade engineering practices into every project from day one. The result: agents produce specs that other agents can implement reliably, with fewer blocked runs, fewer wasted fix-validate cycles, and fewer surprises at integration time.

## What it adds beyond vanilla spec-kit

### Analyze phase (Phase 4) — mandatory loop

Vanilla spec-kit treats `/speckit.analyze` as optional. This skill makes it **mandatory and looping**: after clarify completes, the analyze phase runs repeatedly against the spec until it finds zero ambiguities, inconsistencies, or gaps. Only then does the workflow advance to planning. This eliminates the class of bugs where an ambiguous spec produces a plausible-but-wrong plan that agents implement faithfully.

### Auto-advance between phases

Phases auto-chain: constitution → specify → clarify → analyze loop → plan → tasks → **stop**. The agent proceeds to the next phase automatically after each completion — except Phase 7 (implement), which requires explicit user confirmation before launching the runner.

### Spec phase (Phase 2)

- **Edge case enumeration** — Every spec must include an "Edge Cases & Failure Modes" section. Without it, implementing agents encounter ambiguous situations and either guess wrong or write BLOCKED.md. With it, they have a lookup table for "what should happen when X goes wrong."
- **Idempotency requirements** — Every setup/init flow must be specified as idempotent. Agents crash, get rate-limited, and restart constantly — setup steps must be safe to re-run.
- **Functional requirement numbering** — Every requirement gets a unique `FR-xxx` ID and maps to testable success criteria (`SC-xxx`). This enables bidirectional traceability from requirement → task → test.
- **UI flow requirements** (UI projects only) — Screens, navigation, state transitions, and field validations must be specified upfront so UI_FLOW.md can be built incrementally during implementation.

### Plan phase (Phase 5)

- **Data model depth** — `data-model.md` must include entity-relationship diagrams, per-entity field tables with types/constraints, state transition rules, and cross-entity constraints. A shallow field list is not enough for agents to implement against.
- **API contract depth** — Contract docs must include full request/response schemas with concrete examples, all status codes with triggers, and wire format documentation for binary/custom protocols.
- **Architecture rationale depth** — `research.md` must document every major decision with rationale and rejected alternatives. Prevents downstream agents from undoing deliberate decisions.
- **Complexity tracking enforcement** — Any design decision that violates a constitution principle must be justified. Applies at plan time AND implementation time.
- **Phase dependency chart** — Explicit dependency graph showing which phases can run in parallel, with an optimal multi-agent strategy.
- **Readiness checks** — External dependencies must have blocking readiness scripts that agents call before proceeding.

### Enterprise-grade engineering practices

These are determined during the interview phase. The interviewer presents each topic, recommends enterprise-grade defaults, and the user decides what to implement now vs. defer. All decisions are documented — including deferrals.

- **Structured logging** — JSON-structured logs with 5 levels (DEBUG/INFO/WARN/ERROR/FATAL), correlation IDs for request tracing, and configurable destinations. Library chosen during interview.
- **Error handling** — Project-level error hierarchy with typed subclasses, error codes, HTTP status mappings, and user-facing flags. Consistent propagation pattern: throw at failure, catch at boundary, never swallow.
- **Configuration management** — Single config module with three-layer precedence (app defaults → config file → env vars), fail-fast validation at startup, and secret separation.
- **Graceful shutdown** — Signal handling, ordered cleanup (stop accepting → drain → close connections → flush logs), shutdown timeout, and verbose INFO logging at every step.
- **Health checks** — Dual endpoints (`/health` for liveness, `/ready` for readiness) with structured JSON responses including dependency status. CLI tools get `--check` flags.
- **Rate limiting & backpressure** — Per-client rate limits, bounded queues, connection limits, timeout budgets on all external calls. Deferred if user chooses, but documented.
- **Security baseline** — Secure by default, insecure by explicit informed consent. Input validation/sanitization at all boundaries (tested in CI), auth strategy, CORS, secret management, security headers, and comprehensive security scanning.
- **Observability** — Metrics emission points, trace context propagation, structured error reporting, and request/response logging (PII omitted).
- **Migration & versioning** — Idempotent up/down schema migrations, database seeding (doubles as test fixture setup), API versioning from day one with latest-version alias, and config format auto-migration.
- **CI/CD pipeline** — Working pipeline committed to the repo. Lint → build → test → security scan → deploy. Quality gates block merges. SBOM generated every run. Agentic CI feedback loop for autonomous failure diagnosis.

### Security scanning stack

Three tiers of security tooling, integrated into CI:

| Tier | Tools | Cost |
|------|-------|------|
| **Tier 1 (mandatory)** | Trivy (SCA + SBOM), OSV-Scanner v2, Semgrep (SAST), CodeQL (scheduled SAST), Gitleaks (pre-commit), TruffleHog (CI secrets), ecosystem-specific (`npm audit`, `pip audit`, etc.) | Free |
| **Tier 2 (recommended)** | Snyk (reachability analysis), Semgrep Team (cross-file), FOSSA (license compliance), SonarCloud (quality gates) | Paid |
| **Tier 3 (ecosystem)** | `eslint-plugin-security` (Node.js), `bandit` (Python), OWASP Dependency-Check (Java) | Free |

### Implementation phase (Phase 7)

- **Integration testing** — Real servers, real processes, no mocks at system boundaries. Structured test output that agents parse. Custom test reporters.
- **Fix-validate loop** — Disk-based state machine at phase boundaries. Fresh agent per fix attempt, failure history on disk.
- **Auto-unblocking** — Agents resolve environment/tooling blockers autonomously. BLOCKED.md only for genuinely human-dependent issues.
- **UI_FLOW.md** (UI projects only) — Living reference document updated in the same commit as UI code. E2e tests reference specific sections.
- **learnings.md** — Cross-agent memory structured by task ID. Gotchas, decisions, and patterns that prevent repeated mistakes.
- **Agentic CI feedback loop** — Agent monitors CI runs, pulls failure logs, diagnoses and fixes failures, pushes again. Same fix-validate pattern applied to CI.

### Specification traceability

- **FR-xxx numbering** — Every requirement has a unique ID
- **SC-xxx success criteria** — Measurable, testable criteria mapped to requirements
- **Story-to-task traceability** — Every task references its source requirement
- **Interview handoff documents** — `interview-notes.md` + `transcript.md` for phase transitions and crash recovery
- **Auto-generated CLAUDE.md** — Project CLAUDE.md stays in sync with feature plans

## How it benefits you

| Without this skill | With this skill |
|---|---|
| Agents guess at edge cases | Edge cases enumerated in spec — agents look them up |
| Shallow data models → inconsistent implementations | ERDs + field tables + state transitions = unambiguous schema |
| API contracts say "returns JSON" | Concrete examples, all status codes, error triggers — no guessing |
| Agents over-engineer silently | Constitution violations must be justified in tracking table |
| Everything runs serially | Phase dependency chart identifies parallel workstreams |
| Agents write BLOCKED.md for installable tools | Auto-unblocking resolves environment/tooling issues |
| Test failures = raw terminal output | Structured test logs that agents parse efficiently |
| Retries corrupt state | Idempotent setup + readiness checks make retries safe |
| UI drifts from documentation | UI_FLOW.md updated in same commit as UI code |
| Each agent starts from scratch | learnings.md carries wisdom across agent contexts |
| Inconsistent logging across modules | Structured JSON logging with correlation IDs from day one |
| Error handling varies per file | Typed error hierarchy with codes, status mappings, consistent propagation |
| Config scattered as raw env var reads | Single validated config module, fail-fast on startup |
| Process dies, in-flight work lost | Graceful shutdown with ordered cleanup and verbose logging |
| No health checks until production incident | `/health` + `/ready` endpoints from the start |
| No security scanning until breach | Trivy + Semgrep + Gitleaks + TruffleHog in every CI run, SBOM on every build |
| CI breaks, human has to fix it | Agentic CI feedback loop diagnoses and fixes failures autonomously |
| No migration strategy until v2 | Idempotent up/down migrations + seed scripts from day one |
| Insecure defaults slip through | Secure by default — insecure choices require explicit informed consent |

## Architecture: lazy-loaded phases + reference files

The skill uses a **dispatcher pattern** for token efficiency. Instead of loading ~25k tokens of enterprise knowledge into every agent context, the skill loads only what's needed for the current phase.

```
SKILL.md              ← Thin dispatcher (~3k tokens): preset selection, phase detection, routing
phases/
  install.md          ← Phase 0: install specify, init project
  interview.md        ← Phase 2: specification interview
  plan.md             ← Phase 5: architecture walkthrough and plan generation
  tasks.md            ← Phase 6: task list generation
  implement.md        ← Phase 7: runner, fix-validate loop, auto-unblocking
reference/            ← Enterprise knowledge base, loaded on demand by phase files
  testing.md          ← Integration testing, structured output, stub processes
  logging.md          ← Structured logging spec
  errors.md           ← Error hierarchy, propagation
  config.md           ← Config management
  security.md         ← Security baseline, scanning tiers, headers
  shutdown.md         ← Graceful shutdown
  health.md           ← Health checks
  rate-limiting.md    ← Rate limiting & backpressure
  observability.md    ← Metrics, tracing
  migration.md        ← Migration & versioning
  cicd.md             ← CI/CD pipeline
  dx.md               ← Developer experience tooling
  ui-flow.md          ← UI_FLOW.md spec
  data-model.md       ← Data model depth
  api-contracts.md    ← API contract depth
  traceability.md     ← FR numbering, learnings format
  idempotency.md      ← Idempotency & readiness checks
  edge-cases.md       ← Edge case enumeration
  complexity.md       ← Complexity tracking
  phase-deps.md       ← Phase dependencies & parallelization
presets/              ← Quality presets (poc, local, public, enterprise)
run-tasks.sh          ← Bash wrapper for parallel_runner.py
parallel_runner.py    ← Task runner: parses task list, spawns parallel agents
```

Typical savings: **60-90%** fewer tokens per phase for poc/local presets. Enterprise interview is the worst case since it loads nearly all reference files.

## Version

Pinned to spec-kit **v0.4.1**. The skill will install this specific version and verify it on every run.
