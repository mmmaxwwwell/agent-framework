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

- Tasks marked `[P]` can be parallelized — but ONLY if they don't share a singleton resource. Writing to different files is necessary but not sufficient: tasks that share a single emulator, database instance, device, or CI runner cannot run in parallel regardless of file independence. Common singleton resources: Android emulator (one at a time), iOS Simulator, browser instance, hardware device, test database. Only mark `[P]` when tasks are truly independent at both the file level AND the resource level.
- Tasks marked `[needs: gh]` are granted GitHub CLI access (GH_TOKEN) at runtime. Use this for tasks that call `gh` commands (push, PR creation, CI monitoring). **NEVER combine `[needs: gh]` with tasks that run package install commands** (npm install, pip install, go install, etc.) — this prevents supply-chain attacks from exfiltrating credentials.
- Tasks marked `[needs: gh, ci-loop]` use a runner-managed CI debug cycle instead of a single agent. The runner pushes, polls CI, and spawns separate diagnosis/fix sub-agents in a loop. See `reference/cicd.md`.
- Tasks that share state reference interface contracts: `[produces: IC-xxx]` / `[consumes: IC-xxx]`. See `reference/interface-contracts.md`.
- Phases: Setup → Foundational → User Stories (P1-P3) → Polish.

### Task done criteria

Every task MUST include a `Done when:` line — a concrete, verifiable completion statement that tells the implementing agent when to stop. This fills the gap between FR traceability (why the task exists) and the fix-validate loop (phase-level quality gate).

**Rules for done criteria:**
1. **Must be verifiable** — not "implement mTLS" but "mutual TLS handshake succeeds with test certs; connection rejected with expired cert; both paths have unit tests"
2. **Must add information beyond the task title** — if the done criterion just restates the description, omit it and write a better task description instead
3. **Keep to 1-3 bullet points** — not a mini-spec. The FR in `spec.md` is the full spec; `Done when:` is the agent's stop-signal
4. **"Write tests" means "tests pass on the target runtime"** — a done criterion like "write instrumented test verifying X" means the test must actually execute and pass, not just compile. If the task targets Android, the test must run on an emulator. If it targets a web runtime, it must run in a real browser. A test that was written but never executed is not a completed done criterion. Phrase criteria as "tests pass" not "tests exist."
5. **Must not be satisfiable by a stub** — if the task says "implement X using library Y," the done criterion must require observable behavior that only the real library Y can produce. For example: "TailscaleManager connects to a headscale instance and receives a real IP" — a stub returning a hardcoded IP would not satisfy this. When a task wraps an external library, include a criterion that exercises the real library's behavior.
6. **Must pin exact names when the spec defines them** — if the task says "show a STATUS column" or "log 'shutdown initiated'", the done criterion must assert the exact string. "Done when: `nix-key devices` output includes a column headed STATUS" — not just "shows device connectivity." This prevents synonym drift where the implementation uses a different word (SOURCE instead of STATUS, "shutting down" instead of "shutdown initiated") that satisfies the spirit but fails the letter of the spec. When the spec or task description uses a specific name, column header, field name, JSON key, log message, or UI label — the done criterion must repeat that exact string.
7. **Cross-boundary tasks must assert both sides** — if the task involves one system writing data that another reads (Nix config → Go daemon, Go server → Kotlin client, API → frontend), the done criterion must verify BOTH the write side AND the read side produce/consume the correct format. "Done when: NixOS module writes `devices` to config.json with keys `name`, `tailscaleIp`, `port`, `certFingerprint`, `clientCertPath`, `clientKeyPath` AND Go daemon's Config struct deserializes all fields correctly" — not just one side.

Example:
```markdown
- [ ] T015 Implement mTLS handshake [FR-007] [consumes: IC-001]
  Done when: handshake succeeds with valid test certs (fixture);
  connection rejected with expired/wrong-CA cert returns SSH_AGENT_FAILURE;
  both paths have integration tests; logged at INFO with correlation ID
```

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
| README.md | `reference/readme.md` | Section structure, cognitive funneling, badges, quality checklist, preset behavior |
| Database seed script | `reference/migration.md` | Idempotent migrations, seed script pattern, admin process parity |
| Pre-PR gate | `reference/pre-pr.md` | Single-command validation, multi-build discovery, non-vacuous checks, CI workflow validation |
| Real-runtime E2E testing | `reference/e2e-runtime.md` | Emulator/browser/simulator patterns, side-by-side architecture, readiness checks, test bypass, UI automation |

**Skip loading reference files for topics the preset says to skip.** But for any foundational task you're writing, load its reference first so the task description is specific enough for an implementing agent to execute without guessing.

Tasks MUST include (when not skipped by preset): logging infrastructure, error hierarchy, config module, graceful shutdown, health endpoints, CI/CD pipeline setup, security scanning integration (local + CI SARIF uploads), and database seed script (if applicable). These are infrastructure — they come before feature work.

### Security scanner setup tasks (foundational phase)

Load `reference/security.md` and `reference/cicd.md` before writing these tasks.

Security scanning infrastructure MUST be set up in the foundational phase so the fix-validate loop can use it from the first feature phase onward. Include these tasks:

1. **Local security scanner integration** — add scanner binaries to `flake.nix` devShell (trivy, semgrep, gitleaks, plus ecosystem-specific tools). Create a `scripts/security-scan.sh` that runs all project-relevant scanners with JSON output to `test-logs/security/` and produces `summary.json`. This script is what the validation agent calls during phase validation.
2. **CI SARIF upload integration** — update the CI workflow to output SARIF from each scanner and upload to GitHub Security tab via `github/codeql-action/upload-sarif@v3`. Add `security-events: write` permission to the workflow. See `reference/cicd.md` and `reference/security.md` for the exact SARIF flags per scanner.
3. **`.gitignore` update** — ensure `test-logs/security/` is gitignored (covered by the existing `test-logs/` entry).

The local scanner script is the key integration point — it's what makes security findings appear in the same fix-validate loop as test failures, using the same structured output pattern.

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

### Requirement precision checks

When generating tasks from spec requirements, watch for these common ambiguities:

1. **"Compatible with X"** — specify the exact integration point. "Compatible with the test reporter" is vague; "aggregatable by `scripts/ci-summary.sh` into ci-summary.json" is precise. Name the tool, script, or interface that consumes the output.
2. **Mode-scoped features** — if the project has multiple execution modes (CI vs local, debug vs release, server vs CLI), every requirement and task involving a mode-specific feature MUST explicitly state which mode it applies to. A supervisor agent that only runs in local mode must say so in the FR, not just in the task description. Ambiguity here causes implementing agents to wire features into the wrong mode.
3. **Shared-resource parallelism claims** — if the Dependencies section claims user stories can run in parallel, verify they don't share a singleton resource (emulator, device, database). If they do, the section must say they run sequentially and explain why.

### Cross-boundary contract tasks (MANDATORY for multi-language/multi-system projects)

When a task involves one system producing data that another system consumes (Go writing JSON that Kotlin reads, Nix generating config that Go parses, a CLI producing output that a script greps), the task description MUST:

1. **Enumerate exact field names / keys / column headers on both sides** — not "store device info" but "store `{name, tailscaleIp, port, certFingerprint, clientCertPath, clientKeyPath}`." If the producer uses `clientCertPath` and the consumer struct has `ClientCert`, the mismatch will be invisible to tests that only exercise one side.
2. **Include a cross-boundary integration test** — a test that writes data from the producer and reads it with the consumer, asserting that every field round-trips correctly. This test catches JSON tag mismatches, protobuf field renames, and serialization format disagreements.
3. **Reference the exact serialization format** — for JSON: specify the key casing convention (camelCase, snake_case) and nullable fields. For protobuf: reference the `.proto` field names. For CLI output: specify exact column headers.
4. **Pin the format in the task description, not just in external docs** — don't say "matches the format defined in module.nix." Inline the actual field names so the implementing agent doesn't have to read the other system's code to know what format to produce/consume.

This rule exists because the most common deficiency in multi-system projects is silent format disagreement — both sides compile, both sides' tests pass, but they disagree on a field name and the integration silently drops data.

### Non-goals awareness
If the spec has a `## Non-Goals` section, reference it in the approach note so implementing agents know what NOT to build. Agents encountering an unlisted scenario should check Non-Goals before implementing — if it's listed there, skip it. If it's genuinely ambiguous and not in Non-Goals, proceed or write BLOCKED.md.

### UI tasks (if the project has a UI)
Load `reference/ui-flow.md` before writing UI tasks. The first UI phase MUST include a task to create `UI_FLOW.md`. Each subsequent UI phase MUST include a task to update `UI_FLOW.md`. A late-phase task MUST verify all UI_FLOW.md flows have corresponding e2e tests.

### Phase dependencies
Load `reference/phase-deps.md` to structure the Phase Dependencies section with dependency graph, parallel workstreams, and sync points.

### Complexity tracking
Load `reference/complexity.md` — any task that introduces abstraction must reference the Complexity Tracking table.

### Approach note
Include at the top of tasks.md: `Approach: Fix-validate loop. Each phase: build → test → lint → security scan → read test-logs/ failures → fix code → re-run until green.` (Adjust based on preset — POC skips fix-validate and security scanning.)

### Conditional tasks — check the spec and include if applicable

- **If the project has persistent state**: include data model tasks (`data-model.md` already exists from the plan phase — tasks should implement the schema, migrations, and seed script described there). Load `reference/migration.md` if writing migration/seed tasks.
- **If the project has an API or IPC protocol**: include API contract tasks. The plan's contract documentation defines endpoints — tasks should implement them with the status codes, error cases, and schemas specified.
- **If the project spawns external processes**: include stub process creation tasks in the test infrastructure phase, and integration tests that exercise the full spawn → stdin → stdout → exit lifecycle. Load `reference/testing.md` for the stub process pattern.
- **If the project has external service dependencies** (databases, emulators, queues): include readiness-check script tasks. Load `reference/idempotency.md` for the pattern.
- **If the project has edge cases enumerated in the spec**: each edge case test should appear alongside its feature's test tasks, not in a separate "edge case phase." Load `reference/edge-cases.md` if you need to verify coverage of all 11 categories.
- **If `interview-notes.md` has `Payment integration: stripe`**: load `reference/stripe.md`. The foundational phase MUST include tasks for: generating the listener scripts (`scripts/stripe-listen-*.sh`, `scripts/stripe-webhook-secret.sh`, `scripts/sync-env.sh`, all chmod +x'd), adding `stripe-cli` to `flake.nix`, scaffolding `.env.example` with the Stripe stanza + banner, writing `docs/stripe-integration.md` (webhook handler contract + publishable key delivery contract), appending the Stripe stanza to `CLAUDE.md` and `test/e2e/README.md`, creating/extending `RUNBOOK.md` with the 8-section Stripe operations guide, adding the `stripe-listen` entry to `.claude/task-deps.json`, and installing the three live-key guardrails (pre-commit hook, gitleaks rule, `.env.example` warning). Every Stripe-driving E2E task (checkout, refund, subscription lifecycle, tax, webhook integration tests that hit real Stripe events) MUST carry the `[needs: stripe-listen]` tag and a `Prereq:` line referencing the start/stop scripts and `test/e2e/README.md`. Example:

  ```markdown
  - [ ] T042 E2E: guest checkout end-to-end [SC-001] [needs: mcp-browser, stripe-listen]
    Prereq: `scripts/stripe-listen-start.sh` before running (see test/e2e/README.md); tear down with `stripe-listen-stop.sh` after.
    Done when: guest completes checkout with test card 4242424242424242; `payment_intent.succeeded` webhook received; order transitions to `paid`; confirmation page renders with order id.
  ```

  The run-tasks runner reads `[needs: stripe-listen]`, resolves it via `.claude/task-deps.json`, and executes the start script before the task and the stop script after — no extra per-task boilerplate needed.

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

### Critical path integration checkpoints
If the plan includes a `## Critical Path (User Perspective)` section, add a growing integration test task at the end of each critical-path phase. Each checkpoint exercises the chain built so far — not just the current phase's features:

```markdown
- [ ] T0XX Critical path checkpoint (Phase 3): verify agent socket opens, accepts connection, returns key list [Critical Path]
  Done when: integration test exercises the chain from Phase 2 + Phase 3 components together; test passes
```

These checkpoints fill the gap between per-phase user-flow tests (within-phase only) and the late E2E phase. They catch cross-phase integration failures incrementally rather than in a big-bang at the end.

### End-to-end validation phase
Include a late-phase task that runs ALL user-flow integration tests together after all per-phase tests pass. This catches cross-feature interactions and cascade failures that per-phase testing misses. The test should exercise every primary user flow from the spec in sequence.

### Real-runtime E2E tests (if project targets a platform runtime)
Load `reference/e2e-runtime.md` before writing E2E tasks for projects targeting Android, iOS, web/PWA, or desktop platforms. The reference defines: runtime selection (real emulator/browser, never simulated), side-by-side architecture for multi-runtime tests, readiness checks, test bypass mechanisms for hardware features, UI automation patterns, flakiness handling, and CI infrastructure. Follow the task generation guidance in that reference — decompose E2E prerequisites into separate infrastructure tasks (artifact build, environment setup, test bypass, UI helper library) before writing the E2E test task itself.

### MCP-driven E2E exploration (if interview-notes specify MCP debug tools)
Load `reference/mcp-e2e.md` before writing MCP E2E tasks. If the interview confirmed that agents should use MCP tools for visual E2E testing, include **per-screen E2E tasks** with the `[needs: mcp-<platform>, e2e-loop]` capabilities. Each task uses the runner's explore-research-fix-verify loop.

### MANDATORY E2E + MCP gap-analysis checklist

**Before finalizing the task list for any project that targets one or more platform runtimes, walk through this checklist and add any missing tasks. Missing a row here is the single most common cause of E2E-time surprises (discovered twice on production kanix build-out). Treat this as a forcing function — not optional.**

#### Part A — MCP infrastructure tasks (one task per row, all MUST exist)

For every platform runtime the project targets (Android / iOS / web / desktop), verify these tasks exist:

| # | Task | Why it exists | Maps to |
|---|------|---------------|---------|
| 1 | Add `nix-mcp-debugkit` as flake input; re-export `packages.mcp-<platform>` and a `packages.mcp-<platform>-config` config-writer that pins MCP command to its Nix store path | Agents can only use MCP servers that are registered with pinned commands; `github:` URIs unpinned break reproducibility | `reference/mcp-e2e.md` §"Nix flake pinning" |
| 2 | Register MCP servers + required permissions in `.claude/settings.json` (allowlist `nix run .#mcp-*`, platform CLIs like `adb`, `xcrun simctl`, screencap, logcat, emulator commands) | Without permission entries, the agent gets prompted mid-run and the explore-fix-verify loop stalls | `reference/mcp-e2e.md` §"Runner integration" |
| 3 | Platform prereq verification script (KVM for Android, Xcode for iOS, display server for desktop) — fail fast with actionable error | Software emulation fallback is 10x slower; silent fallback masks the root cause | `reference/e2e-runtime.md` §"KVM access" |
| 4 | `test/e2e/setup.sh` + `test/e2e/teardown.sh` — start/stop backend services, kill orphan processes on known ports, clean stale sockets, write `$STATE_DIR/env` with service URLs + test credentials, idempotent | The runner auto-invokes these before booting the emulator; no annotation needed | `reference/e2e-runtime.md` §"Backend service setup for MCP E2E loops" |
| 5 | App build + install scripts (APK for Android, `.app` for iOS, static bundle for web) feeding into the runner's install step | The runner rebuilds+installs between fix iterations — this script is the contract | `reference/e2e-runtime.md` §"Runtime selection" |
| 6 | Scripted regression harness per platform (Playwright for web, Patrol / Flutter integration_test or Gradle androidTest for Android, XCUITest for iOS — iOS deferred). **The explore agent auto-emits the regression spec on first success for both web and Android** (see `reference/mcp-e2e.md § Regression fast-path`); subsequent runs skip the MCP agent entirely when the spec passes. iOS tasks always fall through to the MCP loop today. | MCP exploration finds bugs; scripted tests prevent regressions. On later runs, the scripted harness is what actually executes, not the MCP agent — this is where the token savings compound across an E2E phase. | `reference/e2e-runtime.md` §"MCP + scripted complementarity" |

#### Part B — E2E scenario coverage checklist (enumerate, then map to tasks)

For every category below, either (a) write a `[needs: mcp-*, e2e-loop]` task or a scripted E2E task, or (b) explicitly record in the task list that it's out of scope with a reason. **Do not leave a category silently uncovered.**

1. **Primary happy path per user role** — one E2E per major role (admin, customer, contributor, guest, etc.)
2. **Every state machine** — walk each state machine from start state through every terminal state, exercising at least one invalid transition per state
3. **Every external-service adapter in both modes** — stub mode (offline) AND live mode (gated on test keys). Payments, tax, shipping, auth, email, push, analytics.
4. **Every webhook + its idempotency** — duplicate delivery, out-of-order delivery, bad-signature rejection, race with internal state change
5. **Every edge case from spec** — if spec.md has a `## Edge Cases` / `FR-E*` section, each one needs either an E2E test or an integration test citation in its "done when"
6. **Every cross-app real-time propagation** — if the system has >1 client app or WebSocket subscribers, test admin action → other client sees update within SLA
7. **Every guest → authenticated linking flow** — if the system supports both, verify the linking path end-to-end
8. **Every refund / cancellation / reversal path** — full, partial, over-limit rejection, audit-log presence
9. **Every notification delivery path** — trigger → channel (in-app/email/push) → delivery verified at sink (log file, WebSocket receipt, etc.)
10. **Every rate/limit/race** — concurrent claim of last unit, concurrent duplicate submission, expiry race with late success
11. **Security boundary sweep** — unauthenticated, wrong permission, injection, XSS, webhook signature tampering — one scripted API-level task covers all
12. **Upload / file-picker flows** — size limits, type rejection, authorized access, unauthorized rejection
13. **Cross-platform parity** — if a flow exists on web AND native apps, cover each platform (or explicitly defer one with a reason)

#### Part C — Forcing function

When generating tasks for a multi-runtime project:

1. Read `interview-notes.md § Platform Runtime & E2E` first.
2. Write the **E2E / MCP infrastructure phase** BEFORE the feature phases — make these prerequisites of Phase 1 or Phase 2, not an afterthought in the final phase.
3. After drafting the integration/E2E phase, walk Part B categories 1–13 out loud in the task-generation response, mapping each to a specific task ID. If a category has no mapping, either add a task or add an explicit "deferred because X" line.
4. If iOS, Android, web, or desktop is listed in the interview but no `mcp-<that-platform>` tasks exist, STOP and ask the user whether to include or explicitly defer.

**This checklist is the mechanism. Without it, the initial kanix task list shipped with zero MCP setup tasks and missed six E2E categories — that's the failure mode this checklist prevents.**

#### Part D — Integration test hardening phase (MANDATORY when the project has `[needs: e2e-loop]` tasks)

Every project that ships `[needs: e2e-loop]` tasks MUST include a dedicated **integration test hardening phase** that runs *before* the E2E phase and gates it. This phase catches at the API tier what would otherwise only be discovered via the ~100× more expensive E2E crawl.

The phase has two layers:

**Layer 1 — per-file hardening, one task per `*.integration.test.ts`** (or equivalent in other languages). Each task has the same shape:

```markdown
- [ ] T<N> Harden `<path>.integration.test.ts` — <subdomain summary> [<FR tags>]
  Done when: file runs green against live services (source `test/e2e/.state/env.sh` first); no `describe.skip`/`canRun`/`if(!svcUp)return` skip guards; every vacuous assertion (`toBeDefined()` alone, `toBeTruthy()` alone, bare `typeof`) replaced with concrete behavior assertions; every public handler the file covers has both happy-path AND error-path tests; no mocking of DB / auth server / internal service-to-service calls; every FR the file tags is verified by at least one `it()` block that drives the real end-to-end path.
```

Order the per-file tasks by subdomain dependency (infrastructure → auth → catalog → cart → orders → inventory → admin → fulfillment → payments → support → evidence → contributors → notifications). Mark every per-file task non-parallel (no `[P]`) — integration tests share Postgres/SuperTokens/ports; parallel execution pollutes fixtures. See `reference/testing.md` § "Test tier taxonomy" rule 8.

**Layer 2 — cross-domain user-flow mirror tests, one task per E2E task** (see `reference/testing.md` § "Test tier taxonomy" rule 7). Each E2E task in the downstream E2E phase gets a paired `flows/*.integration.test.ts` task here that walks the same multi-step flow via direct API calls. These are the cheap sibling to E2E: when an E2E fails, the mirror tells you whether the bug is in the API or past it.

```markdown
- [ ] T<M> Flow test: <flow name> [mirrors T<E2E-task-id>, <SC/FR tags>]
  Done when: new `<src-root>/flows/<flow-name>.integration.test.ts` walks the full multi-step flow via HTTP against live services: <step 1> → <step 2> → ... → <final assertion on state>. Runs green with zero skips.
```

**Phase validation task** (last in the phase):

```markdown
- [ ] T<Z> Phase <N> validation
  Done when: `bash test/e2e/setup.sh` exits 0; running the project's test command with the env sourced exits 0 with 0 failures AND 0 skips; every FR referenced in this phase's tasks has at least one `it()` block that drives the real end-to-end path; runner-verified.json for this phase shows passed=true.
```

**Why Layer 1 is one task per file rather than one big task**: integration test files can be 500+ lines covering many endpoints. A single agent asked to "harden 55 files" will either OOM its context or produce surface-level passes. One-task-per-file bounds each agent's scope (~3-6 files of context total: the test, the app code it exercises, the spec fragment) and lets the runner track per-file progress.

**Why Layer 2 is not just more E2E tasks**: API-level integration tests are 10-100× faster to diagnose than MCP-driven E2E. A bug that takes 30 minutes to track down via screenshots + tool calls takes 30 seconds via test stack trace. The mirror layer means the expensive E2E only runs after the cheap test confirmed the API layer is green.

**Placement**: this phase goes *immediately before* the E2E phase. The pre-E2E gate in the runner will automatically run the integration test suite before any `[needs: e2e-loop]` task's MCP crawl, but that's a safety net — the hardening phase is the dedicated pass that gets the suite to green.

**CRITICAL: One screen per E2E task.** Each screen gets its own task. This gives each explore agent a fresh context window — screenshots and tool calls don't accumulate across screens, which avoids context overflow and keeps token usage ~5x lower. It also gets the research→fix→verify loop running faster and prevents one hard bug from blocking progress on other screens.

Only bundle two screens in one task when they are **tightly coupled** (e.g., you must create an item on ScreenA before you can view ScreenB). If in doubt, split them.

**Bad** — multiple screens in one task:
```markdown
- [ ] T0XX Validate AuthScreen + HomeScreen + SettingsScreen [needs: mcp-android, e2e-loop]
```

**Good** — one screen per task:
```markdown
- [ ] T0XX Validate AuthScreen [needs: mcp-android, e2e-loop]
  Done when: layout validated against UI_FLOW.md, auth flows tested, findings.json has pass/fail.

- [ ] T0XY Validate HomeScreen [needs: mcp-android, e2e-loop]
  Done when: empty/populated states validated, navigation tested, findings.json has pass/fail.

- [ ] T0XZ Validate SettingsScreen [needs: mcp-android, e2e-loop]
  Done when: all sections validated, toggle defaults and dropdown labels match spec.

- [ ] T0XW Validate ListScreen + DetailScreen [needs: mcp-android, e2e-loop]
  Done when: both screens validated (tightly coupled — must create item to see detail).

- [ ] T0XV Validate navigation flows [needs: mcp-android, e2e-loop]
  Done when: every navigation edge from UI_FLOW.md flowchart exercised.
```

Each task gets its own E2E loop with independent findings, per-bug research agents, fix cycles, and supervisor oversight. If one screen has hard bugs, it doesn't block other screens.

**The E2E loop per task**: For each task, the runner automatically runs:
1. **Explore** — agent discovers bugs on the screen(s)
2. **Research** — per-bug research agent investigates (searches web, codebase, docs) before fix
3. **Fix** — agent fixes bugs guided by research reports and supervisor guidance
4. **Verify** — agent produces structured evidence (raw hierarchy XML, exact assertions)
5. **Bug supervisor** — after 3 failed fix attempts, reviews history and redirects or escalates
6. **Regression check** — runs full test suite after loop completes

**Regression test quality**: When task descriptions require regression tests, the "Done when" criteria MUST specify **behavioral assertions** (state transitions, side effects, data flows), NOT visual assertions (string rendering). See `reference/mcp-e2e.md § Regression test quality` for the full guidance and examples. A regression test that mocks a ViewModel with a pre-set state and asserts text appears is worthless — it tests Compose rendering, not app behavior.

**These tasks are placed AFTER all implementation phases** — they depend on the app being buildable and functional. The runner handles the full lifecycle.

**Post-loop regression check**: After the E2E loop finishes, the runner automatically runs a regression check agent that executes the project's full test suite (all languages, lint, security scans). This catches regressions from E2E fixes without requiring a separate task. The regression agent reads `CLAUDE.md` to discover test commands — **ensure CLAUDE.md lists ALL test commands explicitly**, including per-language and per-platform commands (e.g., `make test` for Go, `./gradlew testDebugUnitTest` for Android JVM, `./gradlew ktlintCheck` for Kotlin lint).

**Backend service setup**: If the app requires backend services to test all screens (daemon, database, mesh network, API server), generate a `test/e2e/setup.sh` and `test/e2e/teardown.sh` task BEFORE the E2E exploration tasks. The runner calls `setup.sh` automatically before the E2E loop starts. See `reference/e2e-runtime.md § Backend service setup for MCP E2E loops`.

**CRITICAL: Do NOT generate tasks that build orchestration code for MCP E2E.** The runner already handles emulator boot, APK build+install, MCP server lifecycle, backend service setup/teardown, and the explore-research-fix-verify loop. Tasks should NOT create shell scripts, prompt templates, scenario runners, report libraries, or any code whose purpose is to invoke or manage agents. The implementing agent receives MCP tools directly from the runner and uses them to interact with the live app. See the anti-patterns section in `reference/mcp-e2e.md`. If a generated task description says "create a script that..." or "write a prompt template for..." for E2E testing, it is WRONG — rewrite it as "use MCP tools to verify [thing] on the live emulator."

**Multiple platform tasks**: If the project targets multiple platforms, create per-screen tasks for each platform:
```markdown
- [ ] T0XX Validate Android AuthScreen [needs: mcp-android, e2e-loop]
- [ ] T0XY Validate Android SettingsScreen [needs: mcp-android, e2e-loop]
- [ ] T0YY Validate Browser AuthScreen [needs: mcp-browser, e2e-loop] [P]
- [ ] T0YZ Validate Browser SettingsScreen [needs: mcp-browser, e2e-loop] [P]
```

Browser and iOS tasks can run in parallel with each other (different runtimes), but tasks within a single platform must run sequentially (single emulator/simulator constraint).

**Single platform projects**: If the project targets only one platform (e.g., Android only), do NOT mark E2E tasks as `[P]` — they all share one emulator and must run sequentially. Only non-runtime tasks (prompt writing, config files) can be parallelized. See `reference/e2e-runtime.md § Single-runtime constraint on parallelism`.

**Nix-first projects**: If `interview-notes.md` records `Nix available: yes`, the E2E setup phase MUST include a task that adds `nix-mcp-debugkit` as a flake input in `flake.nix` and exposes `mcp-android`, `mcp-browser`, and/or `mcp-ios` as packages. This pins the MCP debug toolkit version in `flake.lock` and lets the runner use `.#mcp-<platform>` instead of an unpinned `github:` URI. Example flake input:

```nix
inputs.nix-mcp-debugkit.url = "github:mmmaxwwwell/nix-mcp-debugkit";
```

The runner automatically detects the flake input and uses the pinned reference — no additional wiring is needed beyond adding the input.

**Prerequisites**: The E2E exploration task should depend on:
- `UI_FLOW.md` existing and being complete
- The app building successfully for the target platform
- Any test bypass mechanisms being in place (mock biometrics, deep links, etc.)
- (Nix-first) `nix-mcp-debugkit` added as a flake input

### Build environment gap analysis (MANDATORY)

Before the E2E gap analysis, verify that every tech stack in the project has its build tools accounted for in Phase 1 (test infrastructure / flake setup). Multi-language projects are the most common source of "command not found" blockers — the Nix flake covers the primary language but silently omits secondary stacks.

#### Tool availability per tech stack
- [ ] Does the plan's tool environment inventory list every build/test/lint command for every language in the project?
- [ ] For each tool, is there a Phase 1 task that adds it to `flake.nix` (or equivalent environment setup)?
- [ ] If a tool requires a non-trivial Nix derivation (e.g., mobile SDKs, proprietary CLIs, tools that need license acceptance), is there a dedicated task for creating/importing that derivation — not just a line in the flake?
- [ ] If a tool self-bootstraps (e.g., wrapper scripts that download their own toolchain), does it still need a JDK, SDK, or runtime provided by the environment? Check transitive dependencies.
- [ ] Is there a Phase 1 task that runs `<build-command> --version` (or equivalent) for every build tool to verify availability after flake setup?

If ANY of these checks fail, add the missing task(s) to Phase 1 with explicit dependencies from every later phase that uses the missing tool.

### E2E test harness gap analysis (MANDATORY)

**Load `reference/e2e-runtime.md` before performing this analysis** if the project targets any platform runtime (Android, iOS, web/PWA, desktop). The reference defines the full infrastructure stack for real-runtime E2E testing.

Before finalizing the task list, perform an explicit gap analysis on the E2E and CI/CD phases. E2E tests are the most likely to leave implementing agents blocked because they require infrastructure that earlier phases don't need. For each E2E test in the task list, verify that **every prerequisite** has its own task. Walk through this checklist:

#### Artifact build tasks
- [ ] Is there a task to **build the distributable artifact** (APK, binary, container, VSIX) in a reproducible way before the E2E test installs it? Don't assume the dev build output works — the E2E test should install the same artifact that users get.
- [ ] If the project has multiple artifacts (e.g., Go binary + Android APK), is there a build task for EACH one?
- [ ] Does the **CI workflow** (not just the release workflow) build ALL artifacts? Every artifact that the release workflow produces must also be built on PR/develop branches to catch build failures early. Debug variants are fine — the point is that the build command succeeds. See `reference/cicd.md § Pre-release artifact availability`.
- [ ] Are debug artifacts **uploaded as CI artifacts** on develop/PR branches so developers can install and test them without a release?

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

**Exhaustive screen enumeration (MANDATORY for UI loading-state tasks):** When writing a task like "add loading states to all async screens," the task description MUST enumerate every screen by name that needs the loading state. Do NOT write "all screens" or "all async operations" without listing them — implementing agents will miss screens they don't think of. Audit the full screen inventory from `UI_FLOW.md` or the navigation graph, identify which ones perform async operations (data fetching, network calls, file I/O), and list each one explicitly in the task description. If a screen does NOT need a loading state (e.g., it only shows static content), note that too — so the implementing agent doesn't waste time on it and the reviewer can verify completeness.

### Pre-PR gate (foundational phase)
Load `reference/pre-pr.md` before writing this task. Every project (except poc preset) MUST include a `make pre-pr` (or equivalent) target that runs all quality gates in a single command: build all stacks → test all suites → lint → security scan → non-vacuous assertion → E2E (if applicable) → CI workflow check (if modified). This target is the repeatable action that developers and agents run before every future PR — not just during initial implementation.

Include two tasks:
1. **Foundational phase**: Create the `pre-pr` target with build + test + lint + security + non-vacuous checks
2. **Late phase (after E2E infrastructure exists)**: Wire E2E tests into the `pre-pr` target with timeout and retry wrapper

### Local smoke test phase (post-implementation)
After all automated tests pass and code review is clean, include a final phase with these tasks:
1. **Build artifact** — build the distributable package (VSIX, wheel, tarball, container, binary)
2. **Install in clean environment** — install the artifact outside the dev workspace, using the platform's install mechanism
3. **Exercise every primary user flow** — walk through each user story from the spec as if you're a real user. Capture all output. Fix failures using the bug taxonomy in `phases/implement.md § Post-Implementation Validation`.
4. **Cold-start test** — clear all caches and downloaded resources, restart, verify first-run experience works
5. **Warm-start test** — verify second run uses cached state and is faster

This phase uses a fix-validate loop with a 20-iteration cap. See `phases/implement.md § Post-Implementation Validation` for the full process, bug taxonomy, and escalation strategy.

### README generation (post-smoke, pre-CI)
After local smoke passes, include a task to generate `README.md`. Load `reference/readme.md` before writing this task. The README documents what was actually built — it goes after implementation and smoke testing so the content is accurate.

```
- [ ] T0XX Generate README.md: write comprehensive human-facing README following reference/readme.md. Include: title/tagline, badges, description, visuals/demo, features list, getting started (prerequisites, install, first run with expected output), usage examples, configuration table, architecture overview, development setup, security notes, license. Verify all commands work by running them. [Story: developer onboarding]
```

The preset controls which sections to include — see `reference/readme.md § Preset behavior`. POC gets a minimal README; enterprise gets everything.

### CI workflow local verification (MANDATORY before CI loop)

**When any task modifies CI workflow files** (`.github/workflows/*.yml`), the phase MUST include a local verification task **before** the CI loop task. This task runs every build/test command that the modified workflow references — locally, not in CI. This catches broken build commands, missing artifacts, wrong paths, and misconfigured steps before burning CI cycles.

**Split into parallel sub-tasks by build system / CI job.** Each CI job's commands are independent and MUST run in parallel sub-agents. Do NOT put all builds in one sequential task — a Gradle failure shouldn't block Go verification, and vice versa.

```
- [ ] T0XX-a [P] Verify [primary build system] CI steps locally (fix-validate loop): run [build command], [test command]. Verify artifact path exists, test output files exist with >0 results. On failure: fix and retry.
  Done when: build succeeds, tests pass with non-zero count, artifact paths verified. Fix-validate loop, 20-iteration cap.

- [ ] T0XX-b [P] Verify [secondary build system] CI steps locally (fix-validate loop): run [build command], [test command]. Verify artifact path exists, test output files exist with >0 results. On failure: fix and retry.
  Done when: build succeeds, tests pass with non-zero count, artifact paths verified. Fix-validate loop, 20-iteration cap.

- [ ] T0XX-c [P] Verify [security/other] CI steps locally (fix-validate loop): run [scanner/tool commands]. Verify output files exist and are non-empty. On failure: fix and retry.
  Done when: all tools produce expected output. Fix-validate loop, 20-iteration cap.
```

Generate one sub-task per CI job that was modified, marked `[P]` for parallel execution. The runner spawns parallel sub-agents — one per build system. The CI loop task (`[needs: gh, ci-loop]`) depends on ALL sub-tasks completing.

**Each sub-task uses a fix-validate loop.** The agent does NOT just report failures — it fixes them. Common fixes:
- Missing build tool → add to `flake.nix` devShell or install
- Gradle build fails → fix `build.gradle.kts`, missing SDK, wrong Java version
- Artifact path wrong in ci.yml → update the `path:` in `upload-artifact` to match actual build output
- Test output missing → fix test runner config, verify reporter writes expected files
- Tool not found (`jq`, `bc`) → add to `flake.nix` buildInputs

Each sub-task has a 20-iteration cap. If still failing after 20 iterations, write `BLOCKED.md`.

**Why this is separate from phase validation**: The phase validation agent runs build+test+lint on the project's source code. But if the tasks only edit CI YAML (adding steps, changing paths, adding artifact uploads), the source code hasn't changed — phase validation sees "nothing to build" and passes. Meanwhile, the new CI steps reference commands like `./gradlew assembleDebug` or `nix build` that may not work. The local verification task explicitly runs those commands.

**What to verify**:
1. **Every `run:` command** added or modified in workflow YAML — execute it locally
2. **Every artifact path** in `actions/upload-artifact` steps — run the producing build command, verify the file exists at the expected path
3. **Every test verification step** (non-vacuous checks) — run the test suite, verify the expected output files exist (JUnit XML, summary.json, scanner JSON)
4. **Every tool referenced** in new steps (`jq`, `bc`, `find`, `grep`, `curl`) — verify it's available in the environment

If the project has multiple build systems (Go + Gradle, Rust + npm), verify ALL of them — not just the primary one. A project with `go.mod` and `android/build.gradle.kts` must pass both `go build ./...` AND `./gradlew assembleDebug`.

### CI/CD validation phase (post-smoke)
After local smoke passes (and CI workflow local verification, if applicable), create a **single CI validation task** marked `[needs: gh, ci-loop]`:

```
- [ ] T0XX [needs: gh, ci-loop] CI/CD validation: local validation first (parallel fix-validate subagents for each build system), then push to branch, iterate until CI green (including security scans), create PR
```

**Note**: By this point, the local fix-validate loop has already caught and fixed security findings during every phase, and any CI workflow changes have been verified locally. The CI security scan is a final gate — it should pass on the first push if the local scanners used the same configs. If CI security fails, the ci-loop diagnose/fix agents handle it the same as any other CI failure.

**Phase placement rule**: The `[needs: gh, ci-loop]` task MUST be in a separate phase from the local CI verification tasks (T0XX-a, T0XX-b, T0XX-c). If other phases depend on the verification tasks completing (e.g., an Android emulator phase that needs the build verification to pass first), putting the ci-loop task in the same phase as the verification tasks creates a circular dependency: the downstream phase waits for the ci-loop phase to complete, but the ci-loop task waits for downstream tasks. The runner deadlocks with "No agents running." See `reference/phase-deps.md § Avoiding circular phase dependencies`.

The `ci-loop` tag activates a runner-managed debug cycle (see `reference/cicd.md § Agentic CI feedback loop`):

- The **runner** pushes code, polls CI, and downloads failure logs — no agent context burned on waiting
- A **diagnosis sub-agent** reads logs and writes a structured diagnosis file
- A **fix sub-agent** reads the diagnosis, applies the fix, and pushes
- A **finalize sub-agent** creates the PR after CI passes

All artifacts are written to `ci-debug/<task_id>/` so sub-agents can read prior history without inflating context. The cycle has a 15-attempt cap; after that, the runner writes `BLOCKED.md`.

**All CI/CD tasks that use `gh` commands MUST be marked `[needs: gh]`.**  The runner injects a short-lived GH_TOKEN env var only for these tasks. Tasks without this marker never see the token. If an agent discovers it needs `gh` access mid-task, it writes `[needs: gh]` in `BLOCKED.md` and the runner auto-grants and retries.

### Observable output validation phase (post-CI)

After CI passes, create an **observable output validation task** marked `[needs: gh]`. This phase validates everything visible to users, contributors, and external services — not just that code compiles and tests pass.

```
- [ ] T0XX [needs: gh] Observable output validation: verify README badges render correctly, CI artifacts are downloadable, default branch has all required files for workflow triggers and service integrations, acceptance scenarios are exercised. Fix-validate loop.
```

This task exercises the checks described in `phases/implement.md § Phase 4: Observable Output Validation`:

1. **Badge validation** — fetch every badge URL from README, verify HTTP 200 and valid SVG content (not "not found", "not specified", 404). Fix causes of broken badges.
2. **Artifact validation** — use `gh run view` to verify every expected artifact was uploaded and is downloadable. Download at least one to confirm non-empty.
3. **Default branch readiness** — before creating a PR to main, verify the PR will bring: workflow files, LICENSE, README, release config, package manifests. Check that `workflow_run` triggers reference workflows that will exist on the default branch after merge.
4. **Acceptance scenario exerciser** — parse spec's Given/When/Then scenarios, classify as automatically verifiable / CI-verifiable / manual, execute all automatable ones and report PASS/FAIL.
5. **Cross-system integration** — verify GitHub API metadata (license detection, repo description), workflow trigger chains (`workflow_run` references), release automation config, SARIF upload categories.

**Fix-validate loop**: 10 iterations per check category. If a badge is broken because the default branch is empty, the fix is ensuring the PR brings the needed files — not a code change.

**Preset behavior**:
- **poc**: Skip this phase entirely — no badges, no CI, no release automation
- **local**: Badge + artifact checks only (no release automation, no cross-system)
- **library/extension/public/enterprise**: Full observable output validation

### Code review task
When the last implementation task completes, append a `REVIEW` task. See `phases/implement.md` for how the runner handles this.
