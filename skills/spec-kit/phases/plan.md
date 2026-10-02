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
   - **DX friction analysis** — for every tool, library, and service in the stack, evaluate:
     - **What is it?** Core purpose, maturity, maintenance status
     - **How is it installed?** Nix package available? npm/pip/cargo package? Binary download? Does it need a daemon or just a CLI?
     - **What's the lowest-friction DX path?** How to wire it so `nix develop` (or `npm install`) gives a fully working environment with zero manual steps. Prefer tools that are a single `flake.nix` entry over tools that need config files, signup, env vars, or manual downloads.
     - **Build/run overhead** — does it add seconds to the dev loop? Does it need a background process? Does it have a watch mode?
     - **CI parity** — can the same tool run identically in CI and local dev?
   - Use this analysis to choose between competing tools. When two tools solve the same problem, prefer the one with lower install/setup friction unless the higher-friction tool is dramatically better at its job. Document the trade-off in `research.md`.

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
- **Package manager** — npm, yarn, pnpm, uv, cargo, etc. Prefer the one with fastest install, best lockfile, and Nix integration.
- **Build tooling** — Compiler, bundler, dev server. Evaluate startup time, watch mode quality, and whether it's a single `flake.nix` entry.
- **Framework** (if any) — Present alternatives with trade-offs. Include DX friction: how many config files, how fast is cold start, does it have a good dev server with HMR?
- **DX friction summary** — After evaluating all tools, present a brief "setup cost" summary: what `flake.nix` provides, what needs config files, what needs env vars or tokens. Goal: `git clone && nix develop && npm run dev` works with zero manual steps beyond filling in `.env`.
- **Tool environment inventory** — For every build/test/lint command the project will use, produce a concrete inventory mapping command → tool → Nix package. This catches "Gradle isn't in nixpkgs" or "Android SDK needs a custom derivation" at plan time, not after 3 failed fix-validate cycles. For multi-language projects (e.g., Go host + Kotlin Android app), enumerate tools for EVERY tech stack:

  Example (adapt columns to the project's actual stacks):

  | Command | Tool | Nix package | Notes |
  |---------|------|-------------|-------|
  | `<build cmd>` | Compiler/runtime | `<pkg>` | Direct nixpkgs availability |
  | `<wrapper script>` | Build tool wrapper | Self-bootstraps | Needs runtime (JDK, SDK, etc.) provided by env |
  | `<device test cmd>` | Test runner + device | `<pkg>` + device/emulator | KVM or hardware required |
  | `<lint cmd>` | Linter | `<pkg>` | In nixpkgs |

  If a tool has no straightforward Nix package (e.g., proprietary SDKs, tools requiring license acceptance, platform-specific toolchains), document the derivation strategy in `research.md` and create a dedicated task for it in Phase 1. Do not leave "we'll figure it out later" as implicit — it will block every task that needs that tool.

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

### Runtime state machines
If the project has non-trivial runtime state (daemons, protocol handshakes, connection management, device lifecycles), present a formal state machine for each stateful subsystem. This is DISTINCT from:
- **data-model.md state transitions** — which cover *persistent entity* lifecycle (database records with status fields)
- **UI_FLOW.md state machines** — which cover *UI domain objects* (only for UI projects)

Runtime state machines cover **process/protocol state in flight**: daemon lifecycles, protocol handshakes, connection management, concurrent subsystem coordination. For each state machine, define:
1. **States** (including initial, terminal, and composite/nested where needed)
2. **Transitions** (from → to)
3. **Triggers** (signal, event, message, timeout)
4. **Guards** (conditions — e.g., "mTLS handshake complete")
5. **Actions** (side effects on transition — e.g., "emit SSH_AGENT_SUCCESS")

Use Mermaid `stateDiagram-v2` format (renders natively in GitHub Markdown). Link each state machine to the edge-cases section: for every state, the edge cases should cover crash-in-state, concurrent access, and timeout behavior.

Skip this section for stateless request/response services, pure-function libraries, and run-and-exit CLIs.

### Infrastructure decisions
- **Payment integration** — If `interview-notes.md` shows `Payment integration: stripe`, load `reference/stripe.md` and walk through the generated bundle at plan time so the user can see the full scaffolding footprint before tasks are written: scripts directory, flake entry, env scaffolding, webhook handler contract, publishable-key dual delivery (runtime fetch + build-time fallback), CLAUDE.md / test/e2e / RUNBOOK stanzas, task-deps entry, three live-key guardrails. Confirm the webhook forwarding URL (default `localhost:<api-port>/webhooks/stripe`) and the frontend env sync target (e.g., `site/.env` for Astro, `web/.env.local` for Next.js). Confirm any Stripe-specific scope answers from the interview (multi-currency, Stripe Tax, Connect, refund/dispute policy, subscription dunning).
- **Logging** — Confirm library from interview, present any adjustments
- **Error handling** — Present the error hierarchy customized for this project
- **Config management** — Config file format, secret management approach
- **Auth** — Confirm strategy, present implementation approach (library, middleware pattern)
- **Security headers** — Present the baseline set, note any project-specific additions
- **Graceful shutdown** — Confirm timeout, present the cleanup order for this specific project
- **Health checks** — Confirm active vs. cached probes, dependency list
- **Loading/initialization states** — For every async startup operation (model loading, dependency downloading, connection establishment, service discovery), plan the UI states the user sees. Define the state machine: what triggers each transition, what the user sees at each state, what happens on failure. The user should NEVER see a "ready" state while initialization is in progress, and should NEVER see a raw crash during startup — always an actionable error message.

### Testing strategy
- **Test runner** — Native test runner, Jest, Vitest, pytest, etc.
- **Code coverage** — Coverage tool (c8, vitest coverage, jest --coverage, pytest-cov, etc.), wired into the default test command so every run collects coverage. See `reference/testing.md` § Code coverage collection.
- **Custom reporter** — For structured test output (required by fix-validate loop)
- **Test tiers** — Unit, integration (per-boundary), user-flow integration (end-to-end chain), contract (cross-boundary format verification) — what goes where. **Contract tests are MANDATORY for multi-language/multi-system projects**: any seam where one language writes data another reads (Go→JSON→Kotlin, Nix→config→Go, API→JSON→frontend) MUST have a test that serializes on the producer side, deserializes on the consumer side, and asserts every field round-trips. These tests catch JSON tag mismatches, protobuf field renames, and serialization format drift that unit tests on each side independently will miss.
- **User-flow test plan** — For each primary user flow in the spec, identify: the chain of boundaries crossed, the injectable seams for deterministic input (fixture files, pre-cached resources, test data), and the observable output to verify. See `reference/testing.md` § "User-flow integration tests". This plan ensures implementing agents know WHAT flows to test and HOW to make them deterministic.
- **Real-runtime E2E strategy** — If the project targets a platform runtime (Android, iOS, web/PWA, desktop), load `reference/e2e-runtime.md` AND `reference/mcp-e2e.md` and decide: which runtimes to test on (emulator, simulator, headless browser), side-by-side vs nested architecture for multi-runtime tests, test bypass mechanisms for hardware features (camera, biometrics, NFC), UI automation framework (UI Automator, Playwright, XCUITest), and CI infrastructure (KVM, Xvfb, runner requirements). Present each decision to the user.

  **Also decide (MCP-specific, MANDATORY when any platform runtime is in scope):**
  - **MCP server selection** — for each target platform: `mcp-android`, `mcp-ios`, `mcp-browser` from `nix-mcp-debugkit`, or explicitly deferred with a reason
  - **Flake pinning** — `nix-mcp-debugkit` as flake input, `packages.mcp-<platform>` re-exported, `packages.mcp-<platform>-config` config writer producing a Nix-store-pinned `mcp/<platform>.json`
  - **Permission allowlist** — concrete list of `Bash(...)` entries for `.claude/settings.json` covering `nix run .#mcp-*`, platform CLIs (`adb`, `xcrun simctl`), screencap, logcat, install/launch commands
  - **Prereq checks** — KVM (Android), Xcode (iOS), display server (desktop) — scripted with fail-fast errors
  - **`test/e2e/setup.sh` / `teardown.sh` inventory** — list every backend service the app needs for end-to-end operation (DB, auth, API, websockets, third-party stubs) so the script can be scoped correctly at task time
  - **App build + install contract** — command the runner will invoke to rebuild+install the app between fix iterations (e.g., `flutter build apk --debug && adb install -r <path>`)
  - **Scripted regression harness** — Playwright for web, Patrol for Flutter, XCUITest for iOS, UI Automator for Android native — complementary to MCP exploration, not a replacement

  Record each decision in the plan with the owning task ID. These will be cross-checked against the mandatory checklist in `phases/tasks.md` during task generation.

- **E2E scenario coverage pre-registration** — Before moving on, enumerate candidate E2E scenarios against this checklist. Each row either becomes a task in Phase 6 or gets an explicit "out of scope because X" line. **Do not skip categories silently.**

  1. Happy path per user role (admin, customer, contributor, guest, etc.)
  2. Every state machine (order, fulfillment, shipment, dispute, ticket, payment, inventory reservation, etc.) — walked start → all terminals
  3. Every external adapter in BOTH stub and live-test modes (payments, tax, shipping, auth, email, push)
  4. Every webhook — success, duplicate, out-of-order, bad-signature
  5. Every edge case enumerated in the spec (`FR-E*` or `## Edge Cases`)
  6. Every cross-app real-time propagation (admin action → other client sees within SLA)
  7. Every guest → authenticated linking flow
  8. Every refund / cancellation / reversal — full, partial, over-limit, audit-log presence
  9. Every notification delivery path — trigger → channel → sink verified
  10. Every rate/race (concurrent last-unit claim, duplicate submission, expiry race)
  11. Security boundary sweep (auth, permission, injection, XSS, webhook tampering)
  12. Upload / file-picker flows
  13. Cross-platform parity (web vs native) when a flow exists in >1 client

  This pre-registration exists because comprehensive E2E scope is routinely under-scoped at plan time and discovered too late. Making it a plan-phase artifact gives the tasks-phase gap-analysis checklist something concrete to verify against.
- **Pre-PR gate** — Load `reference/pre-pr.md`. Every project (except poc) gets a `make pre-pr` target. Decide which checks to include based on the preset: build + test + lint + security (minimum), plus E2E, CI workflow validation, and contract tests (when applicable). Present the gate composition to the user.
- **Test plan matrix** — Map every SC-xxx to a specific test shape. This bridges the gap between success criteria (what to verify) and implementation (how to verify it). For each SC:

  | SC | Test Tier | Fixture Requirements | Assertion | Infrastructure |
  |----|-----------|---------------------|-----------|----------------|
  | SC-001 | Integration (user-flow) | Valid mTLS client cert, running daemon | Connection accepted, sign response returned | Tailscale test network |
  | SC-002 | Integration (adversarial) | Expired cert, wrong-CA cert | TLS handshake rejected for all variants | Same as SC-001 |
  | SC-003 | Unit | Mock signer, test keypair | Signature matches expected output | None |

  Place this matrix after the user-flow test plan in the Testing Strategy section. Reference flow names from the user-flow plan where applicable (e.g., "see Flow 2: sign request") rather than re-describing the boundary chain. The matrix adds tier/fixture/assertion; the user-flow plan provides boundary chain detail.
- **Test fixtures** — Real servers, test databases, audio/media fixtures, pre-cached model files — whatever the user-flow tests need for deterministic input without mocking boundaries
- **First-run testing** — Plan how to test cold-start scenarios (empty caches, no downloaded resources, first-time config creation). Identify which flows have first-run behavior and what fixtures/cleanup is needed.
- **Packaging tests** — If the project produces a distributable artifact: plan how to install-and-test in a clean environment. Identify files that must be bundled, dependencies that must be declared, and paths that must be relative (not absolute dev paths). See Pattern 7 in `reference/testing.md`.
- **Dependency compatibility** — If the project uses ML models, versioned binary assets, or native extensions: plan version pinning strategy and interface verification tests. Identify which dependencies have breaking changes across versions (model input schemas, removed APIs, missing wheels). See Pattern 8.
- **Cross-application integration** — If the project integrates with another app: identify the real delivery mechanism (public API, clipboard, IPC, file system) and plan tests for it. Document sandbox limitations early — don't discover them during implementation. See Pattern 9.
- **Concurrency safety** — If the project has concurrent code (goroutines, threads, async tasks): plan race detection in CI (`go test -race`, Rust ThreadSanitizer/Miri/Loom, Infer/RacerD for Android). Decide whether to split CI into race-enabled and non-race jobs for performance. See `reference/testing.md` § "Concurrency safety verification".
- **Adversarial security tests** — For every security boundary (mTLS, auth tokens, network ACLs): plan at least one E2E test with a rogue actor that verifies rejection. Plan adversarial cert fixtures (expired, wrong-CA, wrong-SAN). Decide whether to test via systemd-managed service (validates sandboxing) or manual launch. See `reference/testing.md` § "Adversarial flow tests".
- **Hardware-dependent test coverage** — If any test suite requires hardware or an emulator (Android instrumented, hardware tokens, physical devices): choose a CI tier for each (every PR, scheduled, manual). Plan interface boundaries that make platform code testable via fakes. Create a coverage gap document with boundaries and mitigations. See `reference/testing.md` § "Hardware-dependent and emulator-gated test coverage".
- **Performance benchmarks** — If the spec has performance goals (latency budgets, throughput targets): decompose end-to-end budgets into per-component sub-budgets. Plan E2E latency assertion tests (`*testing.T` style with p95 assertions) and microbenchmarks (`*testing.B` style with `benchstat` comparison). Choose a CI benchmarking tool and regression thresholds. See `reference/testing.md` § "Performance and benchmark testing".
- **Fuzz testing** — If the project parses untrusted input at system boundaries (wire protocols, binary formats, cert parsing): identify fuzz targets, plan fuzz functions alongside unit tests, configure CI with regression corpus on every PR and time-boxed generative fuzzing on schedule. See `reference/security.md` § "Fuzz testing".
- **Concurrency** — Parallel unit tests, sequential integration tests, sequential user-flow tests

### CI/CD
- **Pipeline structure** — Confirm stages from interview
- **Security scanning tools** — Confirm tier selection. For each tool, note: does it need a token (and how to get one), or is it zero-config? Prefer zero-config tools. Document token setup instructions for the README (per `reference/cicd.md` CI credential section).
- **Security success criteria → task mapping** — For each security-related success criterion (SC-*) in the spec, confirm there's a corresponding scanning task, Makefile target, and CI gate. If the spec says "zero critical vulnerabilities", the plan must include the specific scanners, their commands, and the CI step that enforces it. Don't let security SCs exist without implementation tasks.
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

### Interface contracts (internal)
Load `reference/interface-contracts.md` before writing this section. For any project with 2+ tasks that share state (file paths, socket paths, data formats, env vars), define the contracts between producer and consumer tasks:

| IC | Name | Producer | Consumer(s) | Specification |
|----|------|----------|-------------|---------------|
| IC-001 | Cert store layout | T005 | T008, T033 | Dir: `~/.config/app/certs/`, CA: `ca.pem`, format: PEM X.509, permissions: 0600 |

Each contract specifies: location, format, permissions, and lifecycle. Task descriptions in `tasks.md` reference contracts with `[produces: IC-xxx]` / `[consumes: IC-xxx]` tags.

**Field-level precision (MANDATORY):** For contracts involving serialized data (JSON config files, protobuf messages, API payloads, CLI output tables), the specification column MUST list every field/column name with its exact serialization key. Not "device info" but `{name: string, tailscaleIp: string, port: int, certFingerprint: string, clientCertPath: string|null, clientKeyPath: string|null}`. If the producer is a Nix module that outputs `clientCertPath` but the consumer Go struct has `json:"clientCert"`, this is a contract violation that should be caught here — at plan time — not after implementation. When one side uses a language with its own naming convention (camelCase in Go JSON, snake_case in Python, PascalCase in C#), the contract must specify the wire format key, not the language-native name.

**Cross-language serialization contracts:** For multi-language projects where different languages produce/consume the same data (Go → JSON → Kotlin, Nix → JSON → Go, Rust → protobuf → TypeScript), include a `Wire format` row in each contract that specifies: (a) the exact key names as they appear on the wire, (b) how nullable/optional fields are represented (null, absent, empty string), and (c) which side is the source of truth for the schema. This prevents the most common multi-language bug: both sides compile and pass unit tests independently, but disagree on field names at runtime.

This section covers *internal* shared state between tasks. External APIs/protocols are covered by `reference/api-contracts.md`. Persistent data schemas are covered by `data-model.md`.

### Critical path (user perspective)
Identify the minimal end-to-end flow a user exercises on day 1 — the "walking skeleton" that proves the system works. This is NOT a reordering of phases (technical dependencies still govern order), but an annotation that makes the user-visible integration path explicit:

1. **The day-1 user flow** — the minimal chain from first user action to first meaningful result (e.g., "scan QR code → pair phone → attempt SSH sign → see signature succeed")
2. **Phase mapping** — which phases contribute components to this flow, in order
3. **Incremental integration checkpoints** — for each phase on the critical path, a growing integration test that exercises the chain built so far:
   - Phase 2 done: "agent socket opens"
   - Phase 3 done: "agent socket opens, accepts connection, returns key list"
   - Phase 4 done: "full pairing + sign flow works"
4. **First testable user result** — which phase delivers the first result a user would recognize as "it works"

This fills the gap between per-phase user-flow tests (within-phase only) and the post-implementation E2E validation (too late). Each critical-path checkpoint becomes a task in `tasks.md`.

### Post-implementation validation strategy
- **Build and install command** — The exact command to build the distributable artifact and install it outside the dev workspace. This must be documented so the smoke test agent can execute it.
- **Primary user flows** — List every flow that the smoke test agent will exercise. Each flow should have: entry point, expected state transitions, expected final result. This becomes the smoke test checklist.
- **CI/CD pipeline access** — Confirm the agent can use `gh` CLI to monitor CI runs, read failure logs, and push fixes. Confirm the CI workflow file path and trigger conditions.

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
| User-flow integration test plan | `reference/testing.md` § "User-flow integration tests" | Testing strategy section — map each user flow to its boundary chain, injectable seams, and observable output |
| Concurrency safety / race detection | `reference/testing.md` § "Concurrency safety verification" | Testing strategy — race detector flags, CI job splitting |
| Adversarial security tests | `reference/testing.md` § "Adversarial flow tests" | Testing strategy — rogue-actor E2E tests, adversarial cert fixtures |
| Hardware-dependent coverage gaps | `reference/testing.md` § "Hardware-dependent and emulator-gated test coverage" | Testing strategy — CI tiers, coverage gap document |
| Performance benchmarks | `reference/testing.md` § "Performance and benchmark testing" | Testing strategy — budget decomposition, benchmark CI |
| Fuzz testing targets | `reference/security.md` § "Fuzz testing" | Testing strategy — fuzz target identification, CI time-boxing |
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
| Interface contracts (internal) | `reference/interface-contracts.md` | Defining shared data formats, file paths, and protocols between tasks |
| Pre-PR gate | `reference/pre-pr.md` | Single-command validation target, multi-build discovery, non-vacuous checks, CI workflow validation |
| Real-runtime E2E testing | `reference/e2e-runtime.md` | Emulator/browser/simulator selection, side-by-side architecture, readiness checks, test bypass, UI automation, CI infra |

**Conditional loads — check the spec and load only if applicable:**
- **If the project has a UI**: load `reference/ui-flow.md` before planning UI phases. Include UI_FLOW.md creation as an early task and incremental updates per phase.
- **If the project has persistent state** (database, filesystem, in-memory with durability): load `reference/data-model.md` before writing `data-model.md`. Skip if no persistence.
- **If the project has an API, IPC protocol, or real-time channels**: load `reference/api-contracts.md` before writing contract documentation. Skip if no external interfaces.
- **If the project spawns external processes** (CLI tools, agents, child workers): load `reference/testing.md` and include stub-process creation and integration tests for the spawn → stdin → stdout → exit lifecycle. Check the spec's functional requirements for external process interfaces.
- **If the project has external service dependencies** (databases, emulators, message queues): load `reference/idempotency.md` and plan readiness-check scripts for each dependency.
- **If the project targets a platform runtime** (Android, iOS, web/PWA, desktop): load `reference/e2e-runtime.md` before planning E2E phases. Include runtime selection, side-by-side architecture, test bypass mechanisms, UI automation framework, and CI infrastructure in the testing strategy. **If MCP debug tools were confirmed in the interview**: load `reference/mcp-e2e.md` and plan the E2E phase as runner-managed `[needs: mcp-<platform>, e2e-loop]` tasks — do NOT plan custom orchestration scripts, prompt templates, scenario runners, or agent management code. The runner handles the full lifecycle. **Nix-first projects**: plan a setup task that adds `nix-mcp-debugkit` as a flake input (`inputs.nix-mcp-debugkit.url = "github:mmmaxwwwell/nix-mcp-debugkit"`) so MCP servers are version-pinned in `flake.lock`. The runner detects this and uses `.#mcp-<platform>` instead of unpinned `github:` URIs. **Backend service dependencies**: if the app communicates with backend services to function (daemon, API server, database, mesh network, etc.), plan a `test/e2e/setup.sh` and `test/e2e/teardown.sh` task **before** the MCP E2E exploration task. The setup script starts all backend services, performs readiness checks, and writes connection info to `test/e2e/.state/env`. The runner calls `setup.sh` automatically before the E2E loop — the explore agent receives the connection info in its prompt. Without this, the E2E loop can only test screens that don't require backend connectivity, leaving critical flows (pairing, signing, data sync, auth) untested. Analyze the spec's architecture diagram and data flows to identify which screens/flows require backend services.

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
- **Late phase: E2E validation** — exercise real flows after all unit/integration tests pass. UI_FLOW.md verification if UI project. The runner automatically runs a post-loop regression check against the full test suite after MCP E2E fixes are applied — ensure `CLAUDE.md` lists ALL test commands (per-language, per-platform) so the regression agent can find them

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
