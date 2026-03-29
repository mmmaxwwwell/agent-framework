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
- **User-flow test fixtures and helpers**: deterministic input fixtures for each primary user flow (audio files, test data, pre-cached models/resources). Helper utilities for starting/stopping multi-process test environments, polling for async state changes, and capturing cross-process logs. See `reference/testing.md` § "User-flow integration tests" for the patterns.
- **First-run test support**: scripts or test helpers that clear cached state (model caches, config files, downloaded resources) to enable cold-start testing. The first-run path is where the most user-facing bugs hide.
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

### User-flow integration tests (every feature phase)
Load `reference/testing.md` § "User-flow integration tests" before writing these tasks. For each user story or functional requirement implemented in a phase:
- **Map the user flow chain**: identify every system boundary crossed from user action to observable result
- **Create deterministic input fixtures**: audio files, test data, pre-cached models — whatever makes the flow reproducible without mocking boundaries
- **Write a test that exercises the full chain** with real processes, real connections, and real data flowing through — verify the user-visible result
- **Include first-run / cold-start tests** for flows that involve downloads, caching, or one-time setup
- **If the project produces a distributable artifact** (VSIX, wheel, npm package, binary, container): include a packaging test that installs the artifact in a clean environment and runs the user-flow tests against it. This catches missing files, undeclared dependencies, and dev-only paths. See Pattern 7 in `reference/testing.md`.
- **If the project uses ML models or versioned binary assets**: include a dependency compatibility test that loads each model/asset and verifies the interface (input names, output shapes, API calls) matches what the code expects. See Pattern 8.
- **If the project integrates with another application** (IDE host, browser, third-party service): include a cross-application test that exercises the real delivery path and documents any sandbox limitations. See Pattern 9.
- These tests go AFTER per-boundary tests in the same phase, not in a separate phase

### End-to-end validation phase
Include a late-phase task that runs ALL user-flow integration tests together after all per-phase tests pass. This catches cross-feature interactions and cascade failures that per-phase testing misses. The test should exercise every primary user flow from the spec in sequence.

### E2E test harness gap analysis (MANDATORY)

Before finalizing the task list, perform an explicit gap analysis on the E2E and CI/CD phases. E2E tests are the most likely to leave implementing agents blocked because they require infrastructure that earlier phases don't need. For each E2E test in the task list, verify that **every prerequisite** has its own task. Walk through this checklist:

#### Artifact build tasks
- [ ] Is there a task to **build the distributable artifact** (APK, binary, container, VSIX) in a reproducible way before the E2E test installs it? Don't assume the dev build output works — the E2E test should install the same artifact that users get.
- [ ] If the project has multiple artifacts (e.g., Go binary + Android APK), is there a build task for EACH one?

#### Test environment infrastructure tasks
- [ ] Is there a task to **set up the test environment** (emulator, VM, container, sandbox) as a reusable Nix expression or script? Don't make the E2E test task also responsible for creating its own environment — that's two things at once.
- [ ] If the test environment needs special hardware support (KVM, GPU, nested virtualization), is the configuration explicit? Include: GPU rendering mode (swiftshader for headless), memory allocation, timeout for environment boot.
- [ ] If the project uses external services (Tailscale, databases, message queues), is there a task to set up test instances (headscale, test DB, mock queue) that the E2E test depends on?

#### UI automation / interaction tasks
- [ ] If the E2E test involves a UI (mobile app, web app, desktop app), is there a **reusable test helper library** task? Individual UI actions (tap button, wait for element, navigate to screen) should be methods in a shared helper, not inline in the E2E test.
- [ ] If the app has features that are hard to automate in a test environment (camera, NFC, Bluetooth, GPS, biometrics), is there a **test bypass mechanism** task? Examples: deep link that bypasses camera scanner, mock biometric API, test GPS provider. Without this, the E2E test is blocked.
- [ ] If the UI automation framework is flaky (UI Automator, Selenium, Playwright), does the E2E test include a retry wrapper?

#### CI debugging infrastructure tasks
- [ ] Is there a task to **upload structured test output as CI artifacts**? `test-logs/` from the structured reporter (see Phase 1 test infra) must be uploaded via `actions/upload-artifact` or equivalent on failure. Without this, CI failures produce logs that are lost.
- [ ] Is there a task to **produce a structured CI failure summary**? A machine-readable `ci-summary.json` (or equivalent) with pass/fail per job and failure details lets fix-validate agents diagnose CI failures without parsing raw workflow logs.
- [ ] If the E2E test runs in CI, does the CI workflow include a **retry wrapper** with a timeout budget? Emulator/VM-based E2E tests are flaky — one failure shouldn't fail the pipeline.

#### Release automation tasks
- [ ] Is there a task to **configure semantic versioning automation**? (e.g., `release-please`, conventional commits, version file bumping). Don't leave "auto-tag with semantic version" as an undefined concept.
- [ ] Is there a task to verify the **release pipeline end-to-end**? Push → CI → release artifacts appear. This catches misconfigurations in the workflow before the project ships.

If ANY of these checks fail, add the missing task(s) before finalizing the task list. Each missing item becomes a separate task that the E2E/CI tasks explicitly depend on in the Phase Dependencies section.

### Loading and initialization states
For every feature that involves async initialization (model loading, dependency downloading, service startup, connection establishment), include a task to:
- Add an intermediate UI state (e.g., "Preparing", "Downloading", "Connecting") visible to the user
- Show progress for operations that take >1 second
- Ensure the UI never shows "ready" or "idle" while initialization is still in progress
- Handle initialization failures gracefully (show error with actionable guidance, not a cryptic crash)
- Test the initialization sequence explicitly: verify the state transitions (idle → preparing → ready, and idle → preparing → error)

### Local smoke test phase (post-implementation)
After all automated tests pass and code review is clean, include a final phase with these tasks:
1. **Build artifact** — build the distributable package (VSIX, wheel, tarball, container, binary)
2. **Install in clean environment** — install the artifact outside the dev workspace, using the platform's install mechanism
3. **Exercise every primary user flow** — walk through each user story from the spec as if you're a real user. Capture all output. Fix failures using the bug taxonomy in `phases/implement.md § Post-Implementation Validation`.
4. **Cold-start test** — clear all caches and downloaded resources, restart, verify first-run experience works
5. **Warm-start test** — verify second run uses cached state and is faster

This phase uses a fix-validate loop with a 20-iteration cap. See `phases/implement.md § Post-Implementation Validation` for the full process, bug taxonomy, and escalation strategy.

### CI/CD validation phase (post-smoke)
After local smoke passes:
1. **Push to feature branch** — commit all smoke test fixes and push
2. **Monitor and fix CI failures** — use `gh run list`, `gh run view --log-failed` to read CI output. If a structured `ci-summary.json` artifact exists (from the CI debugging infrastructure task), download and read it first — it's faster than parsing raw logs. Fix failures, push, repeat. Cap: 15 iterations.
3. **Create PR** — once CI is green, create the pull request with `gh pr create`

See `phases/implement.md § Post-Implementation Validation § Phase 3` for common CI failure categories.

### Code review task
When the last implementation task completes, append a `REVIEW` task. See `phases/implement.md` for how the runner handles this.
