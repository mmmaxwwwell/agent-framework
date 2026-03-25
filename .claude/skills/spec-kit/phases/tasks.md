# Spec-Kit Tasks Phase

Generate `tasks.md` with dependency-ordered, phased tasks from the implementation plan.

## Inputs — read these FIRST

Before generating any tasks, read these project artifacts in order:

1. **`interview-notes.md`** — for the `preset:` line and all infrastructure decisions
2. **Preset file** from `presets/<preset>.md` — for phase overrides (what to skip, what to include)
3. **`spec.md`** — for functional requirements (FR-xxx), success criteria (SC-xxx), and edge cases
4. **`plan.md`** — for the phase structure, dependency graph, and technology decisions
5. **`research.md`** — for rationale behind decisions (so task descriptions reflect intent, not just action)
6. **`.specify/commands/tasks.md`** template (if it exists) — for the expected output format

These documents contain all the decisions from the interview and planning phases. Task descriptions must be specific enough that an implementing agent can execute them without guessing — that specificity comes from these inputs.

## Task structure

- Tasks marked `[P]` can be parallelized.
- Phases: Setup → Foundational → User Stories (P1-P3) → Polish.

## Required task patterns (subject to preset overrides)

### Setup/init tasks
- MUST be idempotent. Tasks depending on external services (emulators, databases, dev servers) MUST include a readiness-check task or step before proceeding. Load `reference/idempotency.md` for the idempotency patterns and readiness check requirements.

### Foundational phase

**MANDATORY: Load the reference file for each foundational topic BEFORE writing its tasks.** The reference files define what "logging infrastructure" or "error hierarchy" actually means — specific formats, patterns, and requirements that the implementing agent needs to see reflected in the task description.

| Foundational topic | Reference file to load | What it tells you about the task |
|--------------------|----------------------|----------------------------------|
| Logging infrastructure | `reference/logging.md` | 5 levels, JSON format, correlation IDs, configurable destinations, per-language library recommendations |
| Error hierarchy | `reference/errors.md` | AppError base class, 8 subclasses with HTTP mappings, error codes, propagation pattern, unhandled exception handler |
| Config module | `reference/config.md` | Three-layer precedence, fail-fast validation, secret separation, config documentation table, backing services as attached resources |
| Graceful shutdown | `reference/shutdown.md` | 11-step sequence, signal handling, timeout, hook registry |
| Health endpoints | `reference/health.md` | `/health` + `/ready` endpoints, JSON response format, dependency check strategy |
| CI/CD pipeline | `reference/cicd.md` | Pipeline stages (lint→build→test→scan→deploy), quality gates, SBOM, agentic CI feedback loop |
| Security scanning | `reference/security.md` | Tool selection per tier, pre-commit hooks, CI integration, SARIF uploads |
| DX tooling | `reference/dx.md` | Full script inventory, dev server config, Nix flake setup, debugging configs, CLAUDE.md section |
| Database seed script | `reference/migration.md` | Idempotent migrations, seed script pattern, admin process parity |

**Skip loading reference files for topics the preset says to skip.** But for any foundational task you're writing, load its reference first so the task description is specific enough for an implementing agent to execute without guessing.

Tasks MUST include (when not skipped by preset): logging infrastructure, error hierarchy, config module, graceful shutdown, health endpoints, CI/CD pipeline setup, security scanning integration, and database seed script (if applicable). These are infrastructure — they come before feature work.

**Nix coordination**: Check `interview-notes.md` for `Nix available: yes/no`. If yes, the **first Setup task** MUST be `flake.nix` creation with `devShells.default` providing all project tools, plus `.envrc` with `use flake`. All subsequent tasks that need tools (linters, test runners, database engines) should reference the flake rather than installing globally.

### Test infrastructure tasks FIRST (Phase 1)
Load `reference/testing.md` before writing these tasks:
- Custom test reporter (structured JSON output to `test-logs/`)
- Test fixture templates
- `.gitignore` entry for `test-logs/`
- **If the project involves crypto/auth**: test keypair generators
- **If the project uses protocols** (SSH, SMTP, WebSocket, etc.): real protocol test servers
- **If the project spawns external processes** (check spec for CLI tools, agents, child workers): stub process scripts that accept the same flags/protocols as the real tool. See the "External process boundary testing" section in `reference/testing.md` — this is the most commonly missed test category and the one most likely to cause "both sides green, system broken" failures.

### Fix-validate loop
Task list MUST follow the fix-validate loop pattern. Load `reference/testing.md` for the required task structure:
1. Write tests for the feature (they should fail — TDD)
2. Implement the feature
3. Run tests, read `test-logs/`, fix until green
4. Phase checkpoint: all tests for this phase pass

### Traceability
Every task MUST reference the user story or functional requirement it implements (e.g., `[Story 3]` or `[FR-015]`). Load `reference/traceability.md` for the structured learnings format and CLAUDE.md auto-generation requirements.

### UI tasks (if the project has a UI)
Load `reference/ui-flow.md` before writing UI tasks. The first UI phase MUST include a task to create `UI_FLOW.md`. Each subsequent UI phase MUST include a task to update `UI_FLOW.md`. A late-phase task MUST verify all UI_FLOW.md flows have corresponding e2e tests.

### Phase dependencies
Load `reference/phase-deps.md` to structure the Phase Dependencies section with dependency graph, parallel workstreams, and sync points.

### Complexity tracking
Load `reference/complexity.md` — any task that introduces abstraction must reference the Complexity Tracking table.

### Approach note
Include at the top of tasks.md: `Approach: Fix-validate loop. Each phase: run tests → read test-logs/ failures → fix code → re-run until green.` (Adjust based on preset — POC skips fix-validate.)

### Conditional tasks — check the spec and include if applicable

- **If the project has persistent state**: include data model tasks (`data-model.md` already exists from the plan phase — tasks should implement the schema, migrations, and seed script described there). Load `reference/migration.md` if writing migration/seed tasks.
- **If the project has an API or IPC protocol**: include API contract tasks. The plan's contract documentation defines endpoints — tasks should implement them with the status codes, error cases, and schemas specified.
- **If the project spawns external processes**: include stub process creation tasks in the test infrastructure phase, and integration tests that exercise the full spawn → stdin → stdout → exit lifecycle. Load `reference/testing.md` for the stub process pattern.
- **If the project has external service dependencies** (databases, emulators, queues): include readiness-check script tasks. Load `reference/idempotency.md` for the pattern.
- **If the project has edge cases enumerated in the spec**: each edge case test should appear alongside its feature's test tasks, not in a separate "edge case phase." Load `reference/edge-cases.md` if you need to verify coverage of all 11 categories.

### End-to-end validation phase
Include a late-phase task that exercises the real user flows end-to-end after all unit/integration tests pass. This catches integration gaps that per-phase testing misses.

### Code review task
When the last implementation task completes, append a `REVIEW` task. See `phases/implement.md` for how the runner handles this.
