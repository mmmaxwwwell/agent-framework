---
name: spec-kit
description: Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. Handles install, init, and walks the user through the full SDD workflow — constitution, specify, clarify, plan, tasks, implement. Enforces end-to-end integration testing with real server implementations, structured agent-readable test output, and a fix-validate loop after every feature. Use when the user wants to start or continue a spec-kit project.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebFetch
argument-hint: [project-name]
---

# Spec-Kit — Specification-Driven Development

You are helping the user work with **spec-kit** (`specify` CLI), GitHub's toolkit for Specification-Driven Development (SDD). In SDD, natural-language specifications are the primary artifact — you write detailed specs describing *what* and *why*, then generate plans, tasks, and implementation from those specs.

## Quick reference

| Phase | Command | What it does |
|-------|---------|--------------|
| 0 | `specify init <name>` | Scaffold project with slash commands |
| 1 | `/speckit.constitution` | Define governance principles & architectural rules |
| 2 | `/speckit.specify` | Write a structured feature specification |
| 3 | `/speckit.clarify` | Identify and resolve ambiguities in specs |
| 4 | `/speckit.analyze` | Validate spec consistency (optional) |
| 5 | `/speckit.plan` | Generate technical implementation plan |
| 6 | `/speckit.tasks` | Break plan into actionable task list |
| 7 | `/speckit.implement` | Execute tasks with TDD, phased ordering |
| 8 | `/speckit.checklist` | Quality assurance checklists |
| 9 | `/speckit.taskstoissues` | Convert tasks to GitHub Issues |

---

## Step 0: Ensure spec-kit is installed

1. Check if `specify` is available: run `which specify || specify --version 2>/dev/null`.
2. **If not installed**, install it pinned to **v0.4.1**:
   ```bash
   uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git@v0.4.1"
   ```
   If `uv` is not available, tell the user they need to install `uv` first (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
3. **If already installed**, verify the version: `specify --version`. If it's not `0.4.1`, reinstall: `uv tool install --force specify-cli --from "git+https://github.com/github/spec-kit.git@v0.4.1"`
4. Verify: `specify --version` (should show `v0.4.1`)

---

## Step 1: Initialize or locate the project

**If `$ARGUMENTS` contains a project name** (or the user provides one):
- Check if a `.specify/` directory already exists in the current working directory.
  - **If it exists** → skip init, this project is already set up. Tell the user and proceed to Step 2.
  - **If it doesn't exist** → run: `specify init <project-name> --ai claude --script bash`
  - After init, briefly tell the user what was created.

**If no project name provided**:
- Check if `.specify/` exists in the current directory.
  - **If it exists** → this is an existing spec-kit project. Tell the user and proceed to Step 2.
  - **If not** → ask the user for a project name, then init.

---

## Step 2: Guide the user through the SDD workflow

Present the user with their current state and next recommended step. The workflow phases are ordered — each phase builds on the previous one's output.

### Detecting current state

Check which artifacts exist to determine where the user is:

| Artifact | Location | Means |
|----------|----------|-------|
| Constitution | `.specify/memory/constitution.md` | Phase 1 done |
| Feature spec | `specs/<branch-name>/spec.md` | Phase 2 done |
| Clarifications | Updated spec with no `[NEEDS CLARIFICATION]` tags | Phase 3 done |
| Plan | `plan.md`, `research.md`, `data-model.md` | Phase 5 done |
| Tasks | `tasks.md` | Phase 6 done |

### Running each phase

For each phase, the user has two options:
1. **Run the spec-kit slash command** — The slash commands are defined in `.specify/commands/` as markdown prompt files. Read the relevant command file and follow its instructions.
2. **Skip** — If the user wants to skip a phase (e.g., skip clarify for a simple spec), move to the next one.

**How to execute a phase:**

1. Tell the user which phase you're running and why it's next.
2. Read the command template from `.specify/commands/<command-name>.md` (e.g., `.specify/commands/specify.md` for the specify phase).
3. Follow the instructions in that template file. The template contains the full prompt for that phase — it tells you exactly what to do, what inputs to gather, and what outputs to produce.
4. After completing the phase, summarize what was produced and recommend the next step.

### Phase-specific notes

**Constitution (Phase 1):**
- This sets the architectural rules for the project. It's optional but recommended.
- If the user already has strong opinions about architecture, capture them here.
- The constitution template has 9 "articles" covering things like library-first design, test-first development, simplicity, etc.

**Specify (Phase 2):**
- This is the core of SDD — writing the feature spec.
- Focus the user on *what* and *why*, not *how*.
- The spec creates a branch and directory structure under `specs/`.
- Specs get automatic numbering.
- **MANDATORY**: Every requirement MUST have a unique `FR-xxx` ID and map to testable success criteria (`SC-xxx`). See "Specification Structure & Traceability" below.
- **MANDATORY**: Every spec MUST include a **Testing** section with functional requirements for integration tests. See "Integration Testing Requirements" below — these requirements must be woven into the spec, not added as an afterthought.
- **MANDATORY**: Every spec MUST include an **Edge Cases & Failure Modes** section. See "Edge Case Enumeration" below.
- **MANDATORY**: Every setup/initialization flow in the spec MUST be specified as idempotent. See "Idempotency & Readiness Checks" below.
- **MANDATORY**: The interviewer MUST determine enterprise-grade infrastructure decisions during the specify phase: logging library, error handling strategy, config management approach, auth strategy, security posture, observability tooling, migration strategy, and CI/CD platform. See the enterprise sections below. For each topic, present the enterprise-grade default, let the user accept or defer, and document the decision. **Secure by default** — if the user wants to skip or weaken a security measure, warn about the specific attack vector and consequences before accepting.
- **If the project has a UI**: The spec MUST include UI flow requirements — screens, navigation, state transitions, and field validations. Include a functional requirement that `UI_FLOW.md` exists and that e2e tests cover every flow documented in it. See "UI_FLOW.md" section below.

**Clarify (Phase 3):**
- Scans for ambiguities across 11 categories.
- Generates up to 5 prioritized questions, presented one at a time.
- Integrates answers back into the spec.

**Plan (Phase 5):**
- Generates `plan.md` plus supporting docs (data models, API contracts, test scenarios).
- Runs a research phase first, then a design phase.
- Checks constitutional compliance.
- **MANDATORY**: The plan MUST include a test infrastructure phase (Phase 1 or early) that builds structured test output before any feature work. The plan MUST describe the fix-validate loop strategy. See "Integration Testing Requirements" below.
- **MANDATORY**: `research.md` MUST document every major decision with rationale and rejected alternatives. See "Architecture Rationale Depth" below.
- **MANDATORY**: `data-model.md` MUST include ERDs, field tables, state transitions, and cross-entity constraints. See "Data Model Depth" below.
- **MANDATORY**: Any project with an API MUST produce contract documentation with full request/response schemas, status codes, and error cases. See "API Contract Depth" below.
- **MANDATORY**: The plan MUST include a "Phase Dependencies" section with a dependency graph and parallelization strategy. See "Phase Dependencies & Parallelization" below.
- **MANDATORY**: The complexity tracking table MUST be filled whenever a design decision introduces abstraction beyond the simplest approach. See "Complexity Tracking Enforcement" below.
- **MANDATORY**: All setup/initialization tasks MUST be idempotent, and tasks depending on external services MUST include readiness checks. See "Idempotency & Readiness Checks" below.
- **MANDATORY**: The plan MUST include foundational infrastructure for all enterprise practices the user accepted: logging, error handling, config management, graceful shutdown, health checks, security scanning, CI/CD pipeline. These go in Phase 1 (Setup) or Phase 2 (Foundational), before any feature work.
- **If the project has a UI**: The plan MUST include creation of `UI_FLOW.md` as an early task (during or immediately after the first UI phase). The plan MUST specify that UI_FLOW.md is updated incrementally as each phase adds screens/routes. See "UI_FLOW.md" section below.

**Tasks (Phase 6):**
- Generates `tasks.md` with dependency-ordered, phased tasks.
- Tasks marked `[P]` can be parallelized.
- Phases: Setup → Foundational → User Stories (P1-P3) → Polish.
- **MANDATORY**: Task list MUST follow the fix-validate loop pattern. See "Integration Testing Requirements" below for the required task structure.
- **MANDATORY**: Setup/init tasks MUST be idempotent. Tasks depending on external services (emulators, databases, dev servers) MUST include a readiness-check task or step before proceeding. See "Idempotency & Readiness Checks" below.
- **MANDATORY**: Foundational phase tasks MUST include: logging infrastructure, error hierarchy, config module, graceful shutdown, health endpoints, CI/CD pipeline setup, security scanning integration, and database seed script (if applicable). These are infrastructure — they come before feature work.
- **MANDATORY**: Every task MUST reference the user story or functional requirement it implements (e.g., `[Story 3]` or `[FR-015]`). See "Specification Structure & Traceability" below.
- **If the project has a UI**: The first UI phase MUST include a task to create `UI_FLOW.md`. Each subsequent UI phase MUST include a task to update `UI_FLOW.md` with the screens/routes/flows added in that phase. A late-phase task MUST verify all UI_FLOW.md flows have corresponding e2e tests. See "UI_FLOW.md" section below.

**Implement (Phase 7):**
- For autonomous implementation, use the task runner script (see below).
- Spec-kit's built-in `/speckit.implement` runs in a single context and will hit limits on larger projects.

---

## Autonomous implementation with run-tasks.sh

Once `tasks.md` exists, the user can run implementation autonomously using the task runner script bundled with this skill at `.claude/skills/spec-kit/run-tasks.sh`.

**How to launch it:** Determine the absolute path to `run-tasks.sh` within this skill's directory (it lives alongside this `SKILL.md`). Then run it from the target project root:

```bash
cd <project-root>
/path/to/agent-framework/.claude/skills/spec-kit/run-tasks.sh                          # auto-detect
/path/to/agent-framework/.claude/skills/spec-kit/run-tasks.sh specs/001-my-feature     # specific spec
/path/to/agent-framework/.claude/skills/spec-kit/run-tasks.sh specs/001-my-feature 50  # max 50 runs
```

The script must be run from the project root (where `.specify/` and `specs/` live). Run it in tmux/screen so it survives terminal disconnects.

### How it works

Each iteration spawns a fresh `claude` process (full context budget, no degradation across tasks):

1. Reads the task list and learnings, then consults a manifest of available reference files and loads only the ones relevant to the current task
2. Finds the first unchecked task whose phase/dependency prerequisites are all complete
3. Executes that ONE task, following TDD (test tasks fail before implementation)
4. At phase boundaries, runs the project's build/test commands — if validation fails, writes failure state to `specs/<feature>/validate/<phase>/` and appends a phase-fix task to `tasks.md` (see "fix-validate loop" below)
5. Self-reviews the diff for debug code, security issues, and pattern consistency
6. Records discoveries and decisions in `learnings.md` (persists across runs)
7. Marks the task `- [x]` and commits with the task ID (e.g., `feat(T008): implement HTTP server`)
8. Loop repeats until all tasks are done, `BLOCKED.md` is written, or the run limit is hit

**Fix-validate loop** — validation runs at phase boundaries, not per-task. When the last task in a phase completes, the agent runs the project's test suite. If it fails, the agent writes structured failure state to `validate/<phase>/<N>.md` and appends a phase-fix task (`phase3-fix1`, `phase3-fix2`, ...) to the task list. The next runner iteration picks up the fix task with fresh context and the full failure history on disk. After 10 failed fixes, the agent writes `BLOCKED.md` and the runner stops.

**Automatic code review** — When the last implementation task completes, the agent appends a `REVIEW` task. The runner detects this, switches to a review-specific prompt that embeds the appropriate code-review skill (React, Node, or general), diffs all changes from the feature branch, and writes findings to `REVIEW.md` in the spec directory. The review is read-only — it reports issues but does not fix them.

**learnings.md** — a shared memory file in the spec directory that accumulates across runs. Each agent reads it for context and appends gotchas, decisions, and patterns it discovered. This prevents repeated mistakes and keeps later agents consistent with earlier decisions.

**BLOCKED.md and auto-unblocking** — if the agent hits a blocker, it MUST NOT immediately write `BLOCKED.md`. Instead, it must first evaluate whether it can resolve the blocker autonomously. See "Auto-Unblocking" below for the full decision process. Only write `BLOCKED.md` for genuinely human-dependent blockers. When `BLOCKED.md` is written, the script stops. Edit the file with your answer, delete it, re-run.

**Rate limits** — detected from claude CLI streaming output. The script sleeps until the reset time, then resumes automatically.

**No-op detection** — stops after 5 consecutive runs with no task progress (agent is stuck).

### When to suggest it

When the user has completed planning (tasks.md exists) and asks to start or run implementation, tell them the command to run. Resolve the absolute path to the script based on where this skill is installed.

---

## Exhaustive interview mode

For automated/server-driven interview sessions, the interview wrapper prompt at `.claude/skills/spec-kit/interview-wrapper.md` (alongside this file) provides instructions for conducting exhaustive specification interviews. It instructs the agent to:

- Research similar projects on the web for inspiration
- Ask unlimited questions (no cap at 5) until the spec is comprehensive
- Suggest features proactively based on research
- Probe edge cases, error handling, deployment, auth, observability
- Loop specify → clarify until satisfied
- Wait for explicit user confirmation before advancing to planning
- Write `interview-notes.md` as a handoff document for downstream phases
- Recover context from `transcript.md` and `spec.md` after crashes

The agent-runner server reads this file and passes it via `-p` to the Claude interview session.

---

## Integration Testing Requirements

Every spec-kit project MUST include comprehensive integration tests that validate all user flows end-to-end. This is non-negotiable — without working tests, the autonomous fix-validate loop that powers implementation is blind.

### Philosophy: real servers, real processes, no mocks at system boundaries

Tests MUST exercise the real system wherever possible. The hierarchy of preference:

1. **Real server implementations** — spin up the actual server, hit real endpoints, verify real responses. For protocols like SSH, use a real SSH server (e.g., Node.js `ssh2` library with test keypairs) rather than mocking the protocol.
2. **Real processes** — if the feature spawns child processes, test with real child processes. If it reads files, use real temp directories with real files.
3. **Mock only what requires human interaction** — biometric prompts, hardware tokens, manual UI actions. Everything else should be real.
4. **Never mock internal boundaries** — don't mock the database, don't mock service-to-service calls within the same process. Integration tests exist precisely to catch the bugs that unit tests with mocks miss.

### Structured test output for agent-readable failure logs

The fix-validate loop depends on **structured, machine-readable test output**. Without it, the implementing agent can't diagnose failures efficiently. Every project MUST implement:

1. **Test log directory**: `test-logs/<type>/<timestamp>/` (gitignored)
2. **`summary.json`** per run: `{ pass: number, fail: number, skip: number, duration: number, failures: string[] }`
3. **`failures/<test-name>.log`** per failing test: assertion details (expected vs actual), full stack trace, and relevant context (server logs, captured stderr, request/response bodies)
4. **Passing tests**: one-line summary only (name + duration) — don't clutter output
5. **Custom test reporter**: use the test runner's reporter API (Node.js native test runner custom reporter, JUnit RunListener, pytest plugin, etc.) to produce this format

Example `summary.json`:
```json
{
  "pass": 42,
  "fail": 2,
  "skip": 1,
  "duration": 12340,
  "failures": [
    "session-lifecycle: start → blocked → resume",
    "ssh-bridge: sign request timeout"
  ]
}
```

Example failure log (`failures/ssh-bridge-sign-request-timeout.log`):
```
TEST: ssh-bridge: sign request timeout
FILE: tests/integration/ssh-agent-bridge.test.ts:142

ASSERTION: Expected session state to be "failed" after 60s timeout
  Expected: "failed"
  Actual:   "running"

STACK:
  at Object.<anonymous> (tests/integration/ssh-agent-bridge.test.ts:158:5)
  at async TestContext.run (node:internal/test_runner:123:9)

CONTEXT:
  Server log: [14:23:01] SSH bridge socket created at /tmp/test-abc123/agent.sock
  Server log: [14:23:01] Sign request forwarded, waiting for client response
  Server log: [14:24:01] Timeout — no client response after 60000ms
  Request: { requestId: "req-1", messageType: 13, data: "AAAA..." }
```

### What the spec MUST include

When writing a feature spec (Phase 2), inject these requirements:

- **Testing section** with functional requirements for every user flow:
  - Unit tests for every service, model, and utility
  - Integration tests for every multi-component workflow
  - Contract tests for every API endpoint and protocol
  - End-to-end tests for every user-facing flow
- **Test infrastructure requirements**:
  - Custom test reporter producing structured output
  - Test fixtures (template data files, test keypairs, test servers)
  - Test helpers (real protocol servers, mock-only-what-needs-human-interaction)
- **For each user story**, an "Independent Test" field describing how to verify the story works end-to-end without human interaction

### What the plan MUST include

When generating the implementation plan (Phase 5):

- **Phase 1 MUST be Test Infrastructure** — build the reporter, fixtures, and test helpers before any feature work. Without structured test output, the fix-validate loop can't function.
- **Smoke test phase** early — confirm the most basic thing works (server boots, app loads) before diving into test suites
- **Fix-validate loop strategy** section describing:
  1. Run tests
  2. Read `test-logs/` for structured failures
  3. Fix code (tests are the spec — fix code, not tests)
  4. Re-run until green
  5. Move to next phase
- **Real server test infrastructure** — plan for spinning up real servers (HTTP, WebSocket, SSH, etc.) in tests, not mocking protocols

### What the task list MUST include

When generating tasks (Phase 6):

- **Test infrastructure tasks FIRST** (Phase 1):
  - Custom test reporter
  - Test fixture templates
  - Test keypair generators (if crypto/auth involved)
  - Real protocol test servers (SSH, SMTP, etc. — whatever the project needs)
  - `.gitignore` entry for `test-logs/`
- **Each feature phase follows the pattern**:
  1. Write tests for the feature (they should fail — TDD)
  2. Implement the feature
  3. Run tests, read `test-logs/`, fix until green
  4. Phase checkpoint: all tests for this phase pass
- **End-to-end validation phase** near the end — actually exercise the real flows after all unit/integration tests pass
- **Approach note at the top of tasks.md**: `Approach: Fix-validate loop. Each phase: run tests → read test-logs/ failures → fix code → re-run until green.`

### How the fix-validate loop works at runtime

The loop operates at **phase boundaries**, not per-task. It's a **disk-based state machine** driven by the task runner:

1. Agents implement tasks T007, T008, T009 (all in Phase 3). Each agent marks its task done and commits.
2. The agent completing the **last task in Phase 3** runs the project's test suite.
3. Validation fails → agent writes failure state to `specs/<feature>/validate/phase3/1.md` (command, exit code, structured test output from `test-logs/`, list of tasks completed in this phase)
4. Agent appends `- [ ] phase3-fix1 Fix phase validation failure: read validate/phase3/ for failure history` to `tasks.md` at the end of Phase 3
5. **Next runner iteration** picks up `phase3-fix1` with fresh context — reads the full failure history from `validate/phase3/`, reads `test-logs/`, diagnoses and fixes across all files touched by the phase
6. The fix agent re-runs validation. If it still fails → writes `validate/phase3/2.md`, appends `phase3-fix2`
7. After 10 failed fix attempts → writes `BLOCKED.md` and the runner stops

Key properties:
- **Validation is per-phase, not per-task** — this avoids wasting runs on intermediate states and lets all tasks in a phase land before checking correctness
- **Each fix gets a fresh agent** with full context budget — no degradation from prior attempts
- **Failure history accumulates on disk** in `validate/<phase>/` — nothing is lost between runs
- **Tests are the spec** — fix the code, not the tests (unless a test is genuinely wrong)
- **Structured test output** (`test-logs/summary.json` + `test-logs/<type>/<timestamp>/failures/`) is the primary feedback mechanism — agents read these rather than parsing raw test runner output

---

## Edge Case Enumeration

Every spec MUST include an **Edge Cases & Failure Modes** section after the user stories. Without this, implementing agents encounter ambiguous situations and either guess wrong, write BLOCKED.md (wasting a run), or implement inconsistently across related features. When edge cases are enumerated upfront, agents have a lookup table for "what should happen when X goes wrong."

### What the spec MUST include

After defining user stories (Phase 2), enumerate edge cases for every major flow. For each edge case, specify the **trigger** and the **expected behavior** — not implementation details, just what the system should do.

Categories to probe (not all will apply to every project):

| Category | Example edge cases |
|----------|-------------------|
| **Timeout** | What happens when an API call, external service, or user action takes too long? |
| **Crash/restart** | What happens when the server, agent, or client process crashes mid-operation? |
| **Concurrent access** | What happens when two users/agents/processes touch the same resource simultaneously? |
| **Invalid input** | What happens with malformed data, wrong types, missing fields, or values outside valid ranges? |
| **Partial completion** | What happens when a multi-step flow fails halfway through? Is state rolled back or left partial? |
| **Network failure** | What happens when a connection drops, a WebSocket disconnects, or DNS fails? |
| **Resource exhaustion** | What happens when disk is full, memory is exhausted, or rate limits are hit? |
| **Missing dependencies** | What happens when an external service is unavailable, a file doesn't exist, or a tool isn't installed? |
| **Duplicate operations** | What happens when the same request is sent twice (retries, double-clicks, replayed messages)? |
| **Permission/auth failure** | What happens when credentials expire, tokens are invalid, or permissions are insufficient? |
| **Data migration/upgrade** | What happens when the system encounters data from a previous version? |

### How to integrate into the workflow

- **Specify phase (Phase 2)**: The interview/clarify phases MUST probe for edge cases explicitly — don't wait for the user to volunteer them. For each user story, ask "what should happen when this fails?"
- **Clarify phase (Phase 3)**: Any edge case marked `[NEEDS CLARIFICATION]` must be resolved before planning.
- **Plan phase (Phase 5)**: Edge cases inform the test scenarios in `plan.md`. Each enumerated edge case should map to at least one test.
- **Tasks phase (Phase 6)**: Edge case tests should appear alongside their feature's test tasks, not in a separate "edge case phase."

---

## Data Model Depth

Spec-kit's plan phase produces `data-model.md`, but the skill mandates a minimum level of detail. A shallow field list is not sufficient — implementing agents need an unambiguous schema reference.

### What `data-model.md` MUST contain

1. **Entity relationship diagram** (ASCII or Mermaid) showing all entities with cardinality (1:1, 1:many, many:many). Every relationship must show both directions and labels.

2. **Per-entity field tables**:

   | Field | Type | Required | Default | Constraints |
   |-------|------|----------|---------|-------------|
   | id | string (UUID) | yes | auto-generated | unique |
   | status | enum | yes | "pending" | one of: pending, active, archived |

3. **State transition rules** for any entity with lifecycle states. Use Mermaid state diagrams or explicit transition tables:

   | From | To | Trigger | Constraints |
   |------|----|---------|-------------|
   | pending | active | user confirms | all required fields populated |
   | active | archived | user deletes | no active child entities |

   Include: all valid transitions, what triggers each one, any guard conditions, and terminal states.

4. **Cross-entity constraints**:
   - Uniqueness (e.g., "only one active session per project")
   - Mutual exclusion (e.g., "a user can be either admin or member, not both")
   - Cascading behavior (e.g., "deleting a project archives all its sessions")
   - Referential integrity (e.g., "session.projectId must reference an existing project")

This applies regardless of storage backend — SQL database, document store, filesystem-as-database, or in-memory state. The data model describes the logical schema, not the physical storage.

---

## API Contract Depth

Spec-kit's plan phase produces contract documentation in `contracts/`, but the skill mandates minimum depth. Implementing agents need unambiguous references for what to send and what to expect — no guessing.

### What contract docs MUST contain

**For REST/RPC APIs** — per endpoint:

1. **Method + path** (e.g., `POST /api/sessions`)
2. **Request schema** with a concrete JSON example showing all fields
3. **Response schema** with concrete JSON examples for success and each error case
4. **All status codes** with their meaning and trigger:
   | Status | Meaning | Trigger |
   |--------|---------|---------|
   | 201 | Created | Session successfully started |
   | 400 | Bad Request | Missing required field `projectId` |
   | 404 | Not Found | Project ID doesn't exist |
   | 409 | Conflict | Active session already exists for this project |
5. **Authentication/authorization** requirements per endpoint

**For WebSocket/SSE/real-time channels** — per channel:

1. **Path** and connection parameters
2. **Message types** with direction (client→server, server→client, bidirectional)
3. **Payload schema** with concrete JSON example for each message type
4. **Connection lifecycle** — what happens on connect, disconnect, reconnect
5. **Sequencing/replay** — how clients resume after disconnection (e.g., lastSeq parameter)

**For binary/custom protocols** (IPC, Unix sockets, custom wire formats):

1. **Wire format** — byte order, length prefixes, header structure, message type codes
2. **Message type enumeration** with byte values
3. **Payload format** per message type with annotated byte layout
4. **Flow diagrams** showing message exchange sequences between participants

**For inter-process communication** (JavaScript bridges, Android Intents, IPC channels):

1. **Method signatures** with parameter types and return types
2. **Async behavior** — which calls are synchronous, which return promises/callbacks
3. **Error propagation** — how errors cross the boundary

This is stack-agnostic — applies to HTTP, gRPC, GraphQL, MQTT, Unix sockets, Android IPC bridges, or any other communication protocol the project uses.

---

## Architecture Rationale Depth

Spec-kit's plan phase produces `research.md`, but the skill mandates minimum depth. Without explicit rationale, downstream agents may second-guess or undo deliberate decisions.

### What `research.md` MUST contain

For every major decision (framework, database, auth strategy, deployment model, IPC mechanism, UI framework, test runner, logging library, etc.):

1. **The decision**: What was chosen (e.g., "Raw `http.createServer` with route Map")
2. **Rationale**: Why it was chosen, with specific reasoning tied to project constraints (e.g., "API surface is ~16 endpoints; a framework adds unnecessary abstraction and violates Constitution V: Simplicity")
3. **Alternatives rejected**: At least one alternative considered and why it was rejected (e.g., "Express: unnecessary middleware overhead for this API surface; Fastify: adds dependency for no measurable benefit")

### How agents use this

- **Implementing agents**: Before reaching for a library or pattern not mentioned in the plan, check `research.md` to see if it was already considered and rejected.
- **Fix-validate agents**: Before changing an architectural approach to fix a test failure, check `research.md` to understand *why* the current approach was chosen. Fix within the chosen architecture unless the rationale is provably wrong.
- **Code review agents**: Flag deviations from `research.md` decisions as potential issues.

---

## Complexity Tracking Enforcement

Spec-kit's plan template includes a Complexity Tracking table, but it's gated behind "Fill ONLY if Constitution Check has violations." The skill mandates that this table is actively maintained — not just at plan time, but during implementation.

### Rules

1. **At plan time**: Any design decision that introduces an abstraction, interface, indirection layer, generic solution, or additional dependency beyond the simplest possible approach MUST either:
   - Confirm it doesn't violate any constitution principle, OR
   - Add a row to the Complexity Tracking table with: the violation, why it's needed, and why the simpler alternative was rejected

2. **At implementation time**: If an implementing agent finds it needs to deviate from the plan — adding an interface the plan didn't call for, introducing a new dependency, creating an abstraction layer — it MUST:
   - Add a row to the Complexity Tracking table in `plan.md` before proceeding
   - Include a comment in the code referencing the justification

3. **The table format** (from spec-kit's template):

   | Violation | Why Needed | Simpler Alternative Rejected Because |
   |-----------|------------|-------------------------------------|
   | SigningBackend interface (4 implementations) | Users need Yubikey + app key + mock signing | Direct implementation would duplicate sign-request flow 3× |

The constitution is only useful if violations are caught and justified, not silently ignored. This prevents agents from quietly over-engineering.

---

## Phase Dependencies & Parallelization

Every plan MUST include a **Phase Dependencies** section that makes parallelization opportunities explicit. Without this, the task runner and human operators run everything serially by default, even when independent workstreams exist.

### What the plan MUST include

1. **Dependency graph** (ASCII or Mermaid) showing which phases block which:
   ```
   Phase 1 (Test Infra) ──▶ Phase 2 (Smoke Test)
   Phase 2 ──▶ Phase 3 (Core Services) ──▶ Phase 4 (API Layer) ──▶ Phase 5 (UI)
   Phase 1 ──▶ Phase 6 (Mobile Build)  [parallel with Phases 3-5]
   Phase 5 + Phase 6 ──▶ Phase 7 (Integration)
   ```

2. **Parallel workstreams** — identify phases that can run concurrently because they touch independent code paths. Common patterns:
   - Frontend and backend (until integration phase)
   - Different platform clients (Android, iOS, web)
   - Independent feature modules with no shared state
   - Test infrastructure and initial project scaffolding

3. **Optimal multi-agent strategy** — when the project has naturally independent workstreams, describe how agents could split the work:
   ```
   Agent A: Phase 1 → 2 → 3 → 4 → 5
   Agent B: Phase 1 (wait) → 6 → (wait for Phase 5) → 7
   ```
   For single-stream projects, state "all phases are sequential" — that's a valid answer.

4. **Sync points** — phases where parallel workstreams must converge (e.g., integration testing, e2e validation). These are where agents must wait for all prerequisite streams to complete.

---

## Idempotency & Readiness Checks

In agentic workflows, agents crash, get rate-limited, hit context limits, and get restarted constantly. The fix-validate loop retries phases. The task runner spawns fresh agents per task. Every setup step must be safe to re-run, and every dependency must be verified before use.

### Idempotency requirements

**In the spec (Phase 2)**: Any setup, initialization, or bootstrapping flow MUST be specified as idempotent — "if already done, skip gracefully." This applies to:
- Project initialization (git init, dependency install, config generation)
- Database/schema creation
- Cryptographic material generation (keypairs, certificates, tokens)
- External service registration (API keys, webhook subscriptions)
- File/directory creation
- Environment setup (flake generation, tool installation)

The rule: **check before mutating**. If the resource exists, reuse it. If the operation already ran, skip it. Never overwrite, double-initialize, or re-generate something that downstream steps already reference.

**In the plan (Phase 5)**: Call out the idempotency requirement for every setup task. Describe what "already done" looks like (e.g., "if `flake.nix` exists, skip generation").

**In implementation**: Every setup function must implement existence checks before mutating state. Example patterns:
- `if (existsSync(path)) return;` before file creation
- `CREATE TABLE IF NOT EXISTS` for database schemas
- `git init` only if `.git/` doesn't exist
- Keypair generation only if keypair file doesn't exist

### Readiness checks for external dependencies

When a task depends on an external service (emulator, database, dev server, message queue, etc.), the agent MUST NOT proceed until the dependency is verified ready. The project MUST provide **blocking readiness scripts** that:

1. **Block until the dependency is available** (polling with timeout)
2. **Return instantly if already up** (idempotent check)
3. **Exit non-zero with a clear message if the dependency can't be reached** (after timeout)

Example patterns:
- `npm run emulator:wait` — blocks until Android emulator is booted, returns instantly if already running
- `npm run db:wait` — blocks until database accepts connections
- `npm run dev:wait` — blocks until dev server responds to health check

These scripts MUST be:
- Defined in the project's `package.json` (or equivalent task runner) as named scripts
- Called by agents before any task that depends on the service
- Included in the task list as explicit steps (e.g., "Run `npm run emulator:wait` before running Android integration tests")

The plan MUST identify all external dependencies and specify which readiness script each one needs. The task list MUST include readiness-check steps before any task that depends on an external service.

---

## Auto-Unblocking

Agents MUST NOT write `BLOCKED.md` as a first resort. Many blockers — especially environment setup, tool installation, and dependency configuration — are things the agent can and should resolve autonomously. Writing `BLOCKED.md` for a solvable problem wastes a human's time and stalls the entire pipeline.

### Decision process before writing BLOCKED.md

When an agent encounters a blocker, it MUST evaluate the situation before giving up:

1. **Classify the blocker** into one of these categories:

   | Category | Auto-resolvable? | Examples |
   |----------|-------------------|---------|
   | **Tool/dependency installation** | YES | Emulator not installed, CLI tool missing, package not available, SDK not configured |
   | **Environment configuration** | YES | Env var not set, config file missing, port already in use, service not running |
   | **Build/compilation failure** | YES | Missing import, type error, syntax error, incompatible dependency version |
   | **Test infrastructure setup** | YES | Test database not created, test fixtures missing, test keypairs not generated |
   | **Dependency service startup** | YES | Database not running, emulator not booted, dev server not started |
   | **Design ambiguity** | NO | Spec says two contradictory things, requirement is unclear, multiple valid approaches |
   | **Missing credentials/secrets** | NO | API keys, tokens, certificates that the agent doesn't have access to generate |
   | **External system access** | NO | Need VPN, need account creation, need human to grant permissions |
   | **Hardware requirement** | NO | Physical device needed, USB connection required, biometric enrollment |

2. **Consult user preference artifacts**: Before attempting ANY solution, read these files from the spec directory:
   - **`interview-notes.md`** — key decisions, user pushbacks, things the user rejected
   - **`research.md`** — alternatives considered and why they were rejected
   - **`spec.md`** — requirements and constraints

   If a candidate solution conflicts with a user preference or rejected alternative documented in these files, **skip it and try the next option**. For example: if the user said "no Docker, use Nix for everything" and the obvious fix is to spin up a Docker container, don't do it — find a Nix-based solution instead. User preferences from the interview are constraints, not suggestions.

3. **If auto-resolvable and preference-compatible**: Attempt to fix it. Install the tool, configure the environment, fix the build error, start the service. Record what you did in `learnings.md` so future agents don't hit the same issue.

4. **If uncertain**: Spawn a sub-agent to evaluate the options. The sub-agent MUST read `interview-notes.md` and `research.md` before evaluating solutions. The sub-agent should:
   - Read the error/blocker details
   - Read user preference artifacts (interview-notes.md, research.md)
   - Research possible solutions (check docs, search for similar issues)
   - Filter out solutions that conflict with user preferences
   - Evaluate whether any remaining solution can be executed without human input
   - If yes, execute the solution and report back
   - If no, explain why — either human input is needed, or all viable solutions conflict with user preferences

5. **Only write `BLOCKED.md` if**:
   - The blocker genuinely requires human input (credentials, design decisions, access)
   - The agent attempted auto-resolution and it failed (document what was tried)
   - The agent spawned an unblocker sub-agent and it couldn't find a solution
   - All viable solutions conflict with user preferences documented in interview-notes.md or research.md (list the conflicting preferences and the solutions they block)

### What auto-resolution looks like

Common scenarios that agents MUST handle without writing BLOCKED.md:

- **Emulator not installed**: Install and configure it (e.g., `sdkmanager`, Android emulator setup). Create the readiness script if it doesn't exist.
- **Missing CLI tool**: Install via the project's package manager, `uv tool install`, `npm install -g`, or the project's Nix flake.
- **Database not running**: Start it, create the test database, run migrations.
- **Port conflict**: Find an available port, update the config.
- **Missing test fixtures**: Generate them (keypairs, template files, mock data).
- **Dependency version mismatch**: Update the lockfile, resolve the conflict.

### BLOCKED.md format

When `BLOCKED.md` IS written (genuinely human-dependent), it MUST include:

```markdown
# Blocked: [one-line summary]

## What I need
[Specific question or action required from a human]

## What I tried
[List of auto-resolution attempts and why they failed]

## Context
[Relevant error messages, log output, file paths]

## Suggested resolution
[What the human should do, as specifically as possible]
```

---

## UI_FLOW.md — Living UI Reference Document

For any project with a user interface (web app, mobile app, PWA, desktop app, or any combination), agents MUST create and incrementally maintain a `UI_FLOW.md` file at the project root. This is the authoritative, single-source-of-truth reference for all screens, routes, user actions, API calls, real-time connections, state transitions, and field validations.

**Skip this entirely** for libraries, CLI tools without interactive UI, API-only services, or any project with no visual interface.

### When to create and update

- **Create** `UI_FLOW.md` when the first UI-related task lands (first screen, first route, first component).
- **Update** it every time a task adds, modifies, or removes a screen, route, API endpoint, WebSocket path, state transition, or field validation. The document MUST stay in sync with the implementation at all times — never let it drift.
- **At phase boundaries**, the implementing agent MUST verify UI_FLOW.md reflects all screens and flows implemented in that phase before marking the phase complete.

### Required structure

UI_FLOW.md MUST contain all of the following sections that apply to the project. Omit sections that don't apply (e.g., no Android section if there's no Android client), but never omit a section that does apply.

#### 1. Main Flow Diagram

A Mermaid flowchart showing the complete navigation graph of the application. Use color-coded nodes to distinguish platform contexts:

- **Blue nodes** — top-level web/PWA screens (each has its own route/hash)
- **Orange nodes** — inline components that render within a screen (no route change)
- **Green nodes** — Android native screens (Activities, Dialogs, Fragments)
- **Purple nodes** — iOS native screens (ViewControllers, Sheets)
- **Red nodes** — Desktop native windows/dialogs (Electron, Tauri, etc.)

Arrow types:
- **Solid arrows** — user-triggered actions and navigation
- **Dotted arrows** — on-load API calls (automatic GETs)
- **Double-line arrows** — persistent real-time connections (WebSocket, SSE, etc.)

Only include node types and colors for platforms the project actually targets.

#### 2. State Machines

Mermaid state diagrams for every domain object with non-trivial lifecycle states. Examples:
- Session states (running → waiting-for-input → completed/failed)
- Project/resource status (onboarding → active → error → archived)
- Workflow phases (draft → review → approved → published)
- Connection states (connecting → connected → disconnected → reconnecting)

Each state diagram MUST show all valid transitions, the trigger for each transition, and any terminal states.

#### 3. Screen-by-Screen Details

For every screen/view in the application, a section containing:

| Field | Description |
|-------|-------------|
| **Route** | URL path, hash route, or native screen identifier |
| **Component** | File path to the component/view implementation |
| **On-load API calls** | Endpoints called automatically when the screen loads |
| **User actions** | Every interactive element and what it triggers (navigation, API call, state change) |
| **Field validations** | Per-field validation rules (see Field Validation Reference Table) |
| **Real-time updates** | WebSocket/SSE channels this screen subscribes to and the message types it handles |
| **Navigation** | Where the user can go from this screen and what triggers it |
| **Error states** | How errors are displayed (inline, toast, redirect, modal) and recovery actions |

#### 4. Platform-Native Screens (when applicable)

For projects with native platform components (Android, iOS, desktop), a dedicated subsection per platform documenting:

- **Android**: Activities, Dialogs, Fragments — their lifecycle, Intent extras, JavaScript bridge methods (`window.<BridgeName>.<method>()`)
- **iOS**: ViewControllers, Sheets, SwiftUI views — their presentation style, delegate callbacks, JavaScript bridge methods
- **Desktop**: Windows, dialogs, system tray interactions — IPC channels, native menu items

Include how native screens communicate with the web layer (JavaScript bridges, deep links, IPC, intent filters).

#### 5. API Sequence Diagrams

Mermaid sequence diagrams for every major multi-step flow in the application. Examples:
- Onboarding/signup flow
- Authentication handshake
- Real-time collaboration lifecycle
- File upload → processing → notification pipeline
- Payment/checkout flow
- Any flow involving more than 2 participants (client, server, external service, native layer)

Each diagram MUST show the participant (client, server, external service, native app), every HTTP request/response, every WebSocket message, and every state change.

#### 6. API Endpoint Summary

A table of all REST/RPC endpoints:

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/projects` | required | List all projects |
| POST | `/api/sessions` | required | Create new session |

#### 7. Real-Time Paths

A table of all WebSocket, SSE, or other persistent connection endpoints:

| Path | Direction | Messages | Purpose |
|------|-----------|----------|---------|
| `/ws/session/:id` | bidirectional | `output`, `input-request`, `state-change` | Session streaming |

#### 8. Generated Files Reference (when applicable)

If the application generates files as part of its workflow (onboarding artifacts, exports, reports), a table documenting:

| File | Created during | Location | Purpose |
|------|---------------|----------|---------|
| `transcript.md` | Interview phase | `specs/<feature>/` | Raw interview transcript |

#### 9. Field Validation Reference Table

A comprehensive table of every input field across all screens:

| Screen | Field | Required | Client Validation | Server Validation | Error Message |
|--------|-------|----------|-------------------|-------------------|---------------|
| Project Setup | Project name | yes | 1-100 chars, no special chars | unique check | "Project name already exists" |

Include both explicit validations (form rules) and implicit server-side validations (404 on missing resource, 409 on conflict, etc.).

### Tie to end-to-end testing

Every flow documented in UI_FLOW.md MUST have a corresponding end-to-end test. Each e2e test MUST include a comment referencing the specific UI_FLOW.md section it validates. Example:

```typescript
// Validates: UI_FLOW.md > Onboarding Flow > Step 3: Project creation
test('onboarding creates project and redirects to dashboard', async () => {
  // ...
});
```

When writing the spec (Phase 2), include a functional requirement that e2e tests cover every flow in UI_FLOW.md. When generating tasks (Phase 6), include a late-phase task to verify all UI_FLOW.md flows have corresponding e2e tests.

### CLAUDE.md instruction

When a spec-kit project has a UI, the agent MUST add the following to the project's `CLAUDE.md` (in the manual additions section or equivalent):

```markdown
## UI_FLOW.md — Keep It Up to Date

UI_FLOW.md is the single source of truth for all screens, routes, API calls, real-time connections, state transitions, and field validations. **Every agent that adds, modifies, or removes UI elements MUST update UI_FLOW.md in the same commit.** This includes:

- Adding/removing screens or routes
- Changing navigation between screens
- Adding/modifying API endpoints that the UI calls
- Adding/modifying WebSocket or SSE channels
- Changing field validations
- Adding/modifying state machines
- Adding platform-native screens or bridges

Never let UI_FLOW.md drift from the implementation. If you touch UI code, check UI_FLOW.md.
```

---

## Structured Logging

Every project MUST implement structured logging with a consistent strategy across all modules. The logging library is determined during the interview phase (see `interview-wrapper.md`). The implementation follows these non-negotiable rules.

### Log levels

Use the standard 5-level hierarchy. Every log statement must use the correct level — agents tend to over-use ERROR and under-use WARN:

| Level | When to use | Examples |
|-------|-------------|---------|
| **DEBUG** | Internal state useful only during development/troubleshooting. Never enable in production by default. | Variable values, function entry/exit, cache hit/miss, SQL queries, request/response bodies (PII omitted) |
| **INFO** | Lifecycle events and significant state changes. The "story" of what the system is doing. | Server started on port 3000, request completed (method, path, status, duration), session created, migration applied, shutdown initiated |
| **WARN** | Recoverable issues that may indicate a problem. The system continues but something is degraded or unexpected. | Retry succeeded after 2 attempts, deprecated API called, connection pool near capacity, rate limit approaching, config fallback used |
| **ERROR** | Operation failed but the system continues serving other requests. Requires investigation but not immediate action. | Request handler threw exception, external service returned 500, database query failed, file write failed |
| **FATAL** | System cannot continue. Process will exit after logging. | Database connection failed on startup, required config missing, port already in use, unrecoverable corruption detected |

### Output format

All logs MUST be structured JSON. No exceptions, even for "simple" projects. Structured logs are machine-parseable, filterable, and aggregatable — critical for both human debugging and agentic fix-validate loops.

Every log entry MUST include these fields:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601) | When the event occurred |
| `level` | string | DEBUG, INFO, WARN, ERROR, FATAL |
| `message` | string | Human-readable description of the event |
| `module` | string | Component/module name (e.g., `http-server`, `session-manager`, `onboarding`) |
| `correlationId` | string (optional) | Request/operation trace ID — present for all log entries within a single request/operation flow |

Additional fields for ERROR/FATAL:

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Error message |
| `errorCode` | string | Machine-readable error code (e.g., `ERR_SESSION_CONFLICT`) |
| `stack` | string | Stack trace |

### Log destination

Configure via the logging library — do not use raw `console.log` or `print`. The standard convention:
- **Application logs** → stderr (structured JSON)
- **Structured output/data** → stdout (if applicable)

The logging library must support configurable log levels (e.g., set to WARN in production, DEBUG in development) via environment variable or config file.

### Correlation IDs

For server/API projects: every incoming request generates a correlation ID at the entry point. This ID is attached to every log entry for that request's lifecycle and propagated to downstream calls (via HTTP headers, message metadata, etc.). For non-request-driven operations (cron jobs, background workers), generate a correlation ID per operation.

This enables filtering all logs for a single request/operation across all modules and services.

### What the plan MUST include

- Logging infrastructure as an early task (before feature work)
- Log level usage guidelines in the coding standards section

---

## Error Handling Strategy

Every project MUST implement a consistent error handling strategy. Without explicit guidance, agents create different error patterns per module — some throw strings, some use Error subclasses, some return null, some swallow errors silently.

### Error hierarchy

Every project MUST define a project-level error base class with typed subclasses. The hierarchy:

```
AppError (base)
├── ValidationError      — invalid input (400)
├── NotFoundError        — resource doesn't exist (404)
├── ConflictError        — state conflict (409)
├── AuthenticationError  — identity not verified (401)
├── AuthorizationError   — insufficient permissions (403)
├── ExternalServiceError — downstream service failed (502)
├── RateLimitError       — too many requests (429)
└── InternalError        — unexpected failure (500)
```

Each error class MUST include:
- **Error code**: Machine-readable string (e.g., `ERR_PROJECT_NOT_FOUND`, `ERR_SESSION_CONFLICT`). Clients use these to handle specific errors programmatically.
- **HTTP status mapping**: For API projects, each error type maps to a status code.
- **User-facing flag**: Whether the error message is safe to show to end users. Internal errors expose a generic message; validation errors expose the specific issue.

### Error propagation pattern

1. **Throw at the point of failure** with full context (what was attempted, what failed, relevant IDs)
2. **Catch at the boundary** (API handler, CLI entry point, event loop top)
3. **Log with full context at the catch site** — stack trace, error code, correlation ID, relevant entity IDs
4. **Return a sanitized response** to the caller — user-facing message, error code, HTTP status
5. **Never swallow errors** — every caught error is either handled (with logging) or re-thrown
6. **Never log-and-rethrow** — this causes double logging. Either handle it (log + respond) or let it propagate

### Unhandled rejection / uncaught exception handling

Every project MUST register a global handler for unhandled exceptions and unhandled promise rejections that:
1. Logs the error at FATAL level with full stack trace and context
2. Triggers the graceful shutdown sequence (see "Graceful Shutdown")
3. Exits with a non-zero exit code

This prevents silent crashes where the process dies and nobody knows why.

### What the plan MUST include

Error handling infrastructure as an early task, before feature implementation. The error hierarchy is customized for the project based on decisions made during the interview (see `interview-wrapper.md`).

---

## Configuration Management

Every project MUST implement a centralized configuration system. Agents tend to scatter `process.env` calls throughout the codebase, use inconsistent defaults, and never validate that required config is present at startup.

### Single config module

All configuration MUST be loaded and validated in one place (e.g., `src/config.ts`, `config/settings.py`). This module:
1. Loads config from three layers in order, each overriding the previous:
   - **App defaults** (hardcoded in the config module)
   - **Config file** (e.g., `config.json`, `config.yaml`, `.env` file)
   - **Environment variables** (override any config file value)
2. Validates all values (required fields present, correct types, valid ranges)
3. Exports a typed/validated config object
4. Is the ONLY place that reads config sources — no direct `process.env` / `os.environ` access elsewhere

### Fail-fast validation

On startup, validate all configuration before doing anything else. If a required value is missing or invalid, the process MUST exit immediately with a clear error message listing every invalid/missing config key and what's expected. Not halfway through handling the first request.

### Sensitive vs non-sensitive config

- **Secrets** (API keys, database passwords, tokens, private keys) MUST only come from environment variables or secret managers. Never from config files checked into git.
- The config module MUST distinguish between sensitive and non-sensitive values.
- Sensitive values MUST never appear in log output — mask or redact them. Log that the value is "present" or "missing", not the value itself.

### Config documentation

The config module (or a dedicated section in the project README and any agentic documentation) MUST document every config key:

| Key | Type | Default | Required | Sensitive | Description |
|-----|------|---------|----------|-----------|-------------|
| `PORT` | number | 3000 | no | no | HTTP server port |
| `DATABASE_URL` | string | — | yes | yes | PostgreSQL connection string |

This table MUST be kept in sync with the config module — update both when adding/removing config keys.

---

## Graceful Shutdown

Every server/daemon project MUST implement graceful shutdown. Without this, in-flight work is lost and resources leak on every restart or deployment.

### Signal handling

Register handlers for SIGTERM and SIGINT that trigger a shutdown sequence. The shutdown MUST be logged at INFO level at every step so operators can track progress if the process hangs.

### Shutdown sequence

Execute in this order (reverse of initialization):

1. **Log** `INFO: Shutdown initiated (signal: SIGTERM)` with timestamp
2. **Stop accepting new work** — close HTTP listeners, stop consuming from queues, reject new connections
3. **Log** `INFO: Stopped accepting new connections`
4. **Mark health endpoint as draining** — return 503 from `/ready` so load balancers stop routing traffic
5. **Drain in-flight work** — let active requests complete, wait for in-progress operations to finish
6. **Log** `INFO: Drained N in-flight requests in Xms`
7. **Close external connections** — database pools, message queue connections, WebSocket connections
8. **Log** `INFO: Closed external connections`
9. **Flush logs** — ensure all buffered log entries are written
10. **Log** `INFO: Shutdown complete, exiting`
11. **Exit** with code 0

### Shutdown timeout

Mandate a maximum shutdown window (configurable, default 30 seconds). If cleanup doesn't complete within the window:
1. **Log** `WARN: Shutdown timeout (30s) exceeded, force exiting`
2. Force-close remaining connections
3. Exit with code 1

### Shutdown hook registry

Provide a registration mechanism where modules register their cleanup functions during initialization. The shutdown sequence calls these hooks in reverse registration order (last registered = first cleaned up).

### What the plan MUST include

Graceful shutdown as a task in the foundational infrastructure phase.

---

## Health Checks

Every deployable project MUST implement health check endpoints (servers) or health check commands (CLIs/batch jobs).

### Server projects — two endpoints

**`GET /health`** (liveness):
- Returns **200** if the process is alive, regardless of dependency state
- Body includes full status for human/dashboard consumption:
```json
{
  "status": "ok",
  "uptime": 12345,
  "version": "1.2.3",
  "ready": true,
  "dependencies": {
    "database": "ok",
    "redis": { "status": "timeout", "latency": null },
    "external-api": "ok"
  }
}
```
- Kubernetes uses the status code (200 = alive); humans/dashboards read the body

**`GET /ready`** (readiness):
- Returns **200** when the service can accept traffic
- Returns **503** during startup (still initializing), during shutdown (draining), or when a critical dependency is down
- Same response body as `/health`
- Kubernetes uses this to control traffic routing

### Dependency check strategy

The plan MUST specify how readiness probes check dependencies — active checks (ping on each probe, simpler but adds latency) vs. cached/background checks (faster probes but potentially stale). This is determined during the interview (see `interview-wrapper.md`).

### CLI tools

Implement a `--check` or `--validate` flag that:
- Verifies all dependencies are available (tools installed, services reachable, config valid)
- Exits 0 if everything is OK, exits 1 with a clear error message if not
- Useful in CI pipelines and as a readiness check before running the tool

### Batch/cron jobs

Exit code is the primary health signal:
- Exit 0 = success
- Exit non-zero = failure
- Structured JSON output on completion: `{ "status": "ok", "processed": 42, "failed": 0, "duration": 12340 }`

### Libraries

Skip health checks — health is the consumer's responsibility.

---

## Rate Limiting & Backpressure

The rate limiting strategy is determined during the interview (see `interview-wrapper.md`). When implemented, the following patterns apply:

### Implementation requirements

- **Per-client rate limits**: Sliding window or token bucket, configurable limits per endpoint or globally
- **Rate limit headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` in responses
- **429 response**: Structured error with `Retry-After` header
- **Bounded queues**: For projects that queue work — explicit behavior when full (reject, backpressure, or drop oldest)
- **Connection limits**: Maximum concurrent connections setting as a safety valve
- **Timeout budgets**: Every external call (HTTP, database, DNS) MUST have an explicit timeout

### Documentation

Whatever strategy is chosen (including "deferred"), document it in the project README and agentic documentation. If deferred, include a TODO with the recommended approach so it's not forgotten.

---

## Security Baseline

**Core principle: secure by default.** Security decisions are made during the interview (see `interview-wrapper.md`). The implementation MUST follow these non-negotiable rules.

### Input validation and sanitization

All external input MUST be validated and sanitized at the system boundary. This is non-negotiable.

- **Validate at the edge**: Every API endpoint, form handler, CLI argument parser, file reader, and message consumer validates input before processing
- **Type checking**: Reject wrong types
- **Length limits**: Maximum length for all string inputs
- **Format validation**: Schema validation for structured inputs
- **Encoding**: Sanitize for the output context — HTML-encode for web, parameterize for SQL, escape for shell
- **Trust internally**: Once input passes boundary validation, internal code can trust it

**Testing**: Boundary validation MUST be covered by integration tests. If a change breaks validation, CI MUST fail. Include tests for: malformed input, boundary values, and injection attempts (SQL injection, XSS, command injection from OWASP).

### Authentication and authorization

When auth IS implemented:
- Passwords hashed with bcrypt/scrypt/argon2 (never MD5/SHA)
- Tokens have expiration times
- Failed auth attempts are rate-limited
- Auth errors don't leak information ("invalid credentials" not "user not found" vs "wrong password")

### CORS policy

Default MUST be restrictive (specific allowed origins), NOT `Access-Control-Allow-Origin: *`. If CORS is deferred, add a prominent WARNING in both agentic and human documentation.

### Secret management

- All secrets identified in the spec with their source and rotation strategy
- Secrets only from environment variables or secret managers (never in config files or code)
- `.gitignore` includes all secret-containing files (`.env`, `credentials.json`, `*.pem`)
- Pre-commit hook (Gitleaks) to prevent accidental secret commits

### Security headers

For HTTP servers, mandate these baseline headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Force HTTPS |
| `Content-Security-Policy` | Appropriate for the app | Prevent XSS |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME sniffing |
| `X-Frame-Options` | `DENY` or `SAMEORIGIN` | Prevent clickjacking |
| `X-XSS-Protection` | `0` | Disable legacy XSS filter (CSP is better) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Control referrer leakage |
| `Permissions-Policy` | Appropriate for the app | Restrict browser features |

### Security scanning pipeline

The scanning tools and tiers are selected during the interview (see `interview-wrapper.md`). At minimum (Tier 1, free):
- **Trivy** — SCA + SBOM generation (CycloneDX or SPDX on every CI run)
- **OSV-Scanner v2** — supplemental SCA with guided remediation
- **Semgrep** (OSS) — SAST on every PR
- **CodeQL** — deep SAST on schedule
- **Gitleaks** — pre-commit secret scanning
- **TruffleHog** — CI secret scanning with active verification
- Ecosystem-specific: `npm audit` / `pip audit` / `cargo audit` / `govulncheck`

SBOM MUST be generated on every CI run and stored as a build artifact.

---

## Observability Hooks

Beyond logging, the system needs hooks for metrics, tracing, and error reporting. The specific tools are determined during the interview (see `interview-wrapper.md`).

### Implementation requirements

**Metrics emission points** — key operations MUST emit metrics:
- **Request metrics**: count, latency histogram, error rate (by endpoint, by status code)
- **Resource metrics**: active connections, queue depth, pool utilization, memory/CPU
- **Business metrics**: operations completed, entities created, sessions active

**Trace context propagation** — a trace/correlation ID MUST be generated at the entry point and propagated through:
- All log entries (see "Structured Logging — Correlation IDs")
- HTTP headers to downstream services (`X-Request-ID`, `traceparent` for W3C Trace Context)
- Message queue metadata
- Error reports

**Structured error reporting** — error reports MUST include: stack trace, correlation ID, environment (staging/production), user context (anonymized), and breadcrumbs (recent actions leading to the error).

**Request/response logging** — at DEBUG level, log API requests and responses with enough detail to replay them. **PII omission**: NEVER log personally identifiable information. Mask or redact sensitive fields.

**Documentation** — document the observability strategy in both agentic and human documentation.

---

## Migration & Versioning Strategy

Every project MUST have an explicit strategy for handling change over time — data schema changes, API version bumps, and configuration format changes.

### Data schema migrations

**Strongly recommended**: Implement idempotent up/down structured migrations using a migration library appropriate for the stack (e.g., Knex/Prisma for Node.js, Alembic for Python, golang-migrate for Go, Diesel for Rust).

Migration requirements:
- **Up migration**: Apply the change (add column, create table, transform data)
- **Down migration**: Reverse the change (drop column, drop table, reverse transform)
- **Idempotent**: Safe to run multiple times — check if already applied before executing
- **Versioned**: Each migration has a sequential version number and timestamp
- **Tested**: Migration up/down is covered by integration tests

If the user defers migrations, document the decision with a warning: "No migration strategy — schema changes will require manual data transformation."

### Database seeding

If the project uses a database, provide a **seed script** that:
1. Creates the schema (runs all migrations)
2. Populates required reference data (roles, categories, default config)
3. Optionally populates sample data for development

The seed script serves double duty:
- **Development bootstrapping**: New developer runs seed, has a working database
- **Integration test setup**: Tests use the seed pattern to create isolated test scenarios with known state

### API versioning

Every project with an API MUST implement versioning from day one:
- **URL path versioning** is the default: `/v1/projects`, `/v2/projects`
- **Latest version alias**: Requests without a version prefix (e.g., `/api/projects`) route to the latest version. This lets clients that want "always latest" skip versioning, while clients that want stability pin to a version.
- **Semantic versioning**: The project follows semver. The implementing agent MUST have enough context to determine whether a change is a patch (bugfix), minor (new feature, backward compatible), or major (breaking change).

When a new API version is introduced:
- Update all documentation (API contracts, README, agentic docs) to reflect both versions
- Update the "latest" alias routing
- Document which version is current and which are deprecated

### Backward compatibility policy

The compatibility promise is defined during the interview (see `interview-wrapper.md`). If deferred, document "no backward compatibility policy — all clients assumed internal and updated simultaneously."

### Configuration versioning

When config file formats change between versions:
- Auto-migration: detect old format and upgrade automatically, logging what changed at INFO level
- Clear error message if auto-migration isn't possible, telling the user exactly what to change
- Document config format changes in release notes, README, and agentic documentation

---

## CI/CD Pipeline

Every project MUST include a working CI/CD pipeline committed to the repository. This is not a "set up CI later" item — the pipeline is produced during implementation, alongside the application code.

### Pipeline stages

The standard pipeline structure, in order:

1. **Lint** — code style, formatting, static analysis
2. **Build** — compile, bundle, generate artifacts
3. **Unit test** — fast, isolated tests
4. **Integration test** — multi-component tests with real services
5. **Security scan** — SAST (Semgrep), SCA (Trivy + ecosystem tools), secret scanning (Gitleaks, TruffleHog), SBOM generation
6. **Contract test** — API compliance (if applicable)
7. **E2E test** — full user flow tests (if applicable)
8. **Deploy** — staging/production deployment (if applicable)

### Pipeline as code

The CI configuration MUST be committed to the repository as part of the implementation tasks:
- `.github/workflows/` for GitHub Actions
- `.gitlab-ci.yml` for GitLab CI
- etc.

Tasks for pipeline setup should appear in the foundational infrastructure phase.

### Quality gates

The pipeline MUST block merges on:
- Test failures (unit, integration, contract, e2e)
- Critical or high severity vulnerabilities (from security scans)
- Secrets detected in code
- Lint failures
- Build failures

Additional gates (code coverage thresholds, license compliance) are determined during the interview (see `interview-wrapper.md`).

### Security scan reporting

Scan results MUST be visible and accessible:
- **SARIF uploads** to the GitHub Security tab (or equivalent) for unified findings
- **PR annotations** from scanning tools (Semgrep, Snyk, SonarCloud all support this)
- **README badges** for build status, vulnerability count, code coverage, license compliance
- **SBOM** generated on every CI run and stored as a build artifact
- **Security summary** in release notes listing scan results

### Artifact generation

Every CI run MUST produce:
- Test results (structured output per "Integration Testing Requirements")
- SBOM (CycloneDX or SPDX format)
- Security scan summary
- Code coverage report (if applicable)
- Build artifacts (Docker image, binary, bundle — if applicable)

### Agentic CI feedback loop

The agentic implementation loop MUST extend to CI failures. When the implementing agent pushes code and CI fails, the agent must be able to diagnose and fix the failure without human intervention.

**Strategy** (CI platform and access method determined during interview — see `interview-wrapper.md`):

1. **Monitor CI run**: After pushing, monitor the CI run to completion (e.g., `gh run watch` for GitHub Actions)
2. **Retrieve failure logs**: On failure, pull logs from the failed step (e.g., `gh run view <id> --log-failed`). Parse structured test output if available.
3. **Diagnose and fix**: Same fix-validate loop pattern — read failure logs, identify root cause (CI environment often differs from local), fix code or CI config, push and re-monitor
4. **CI-specific learnings**: CI gotchas go into `learnings.md` (e.g., "CI runner uses Ubuntu, local dev is NixOS — path to tool X differs")
5. **Failure limit**: After 3 failed CI fix attempts, write `BLOCKED.md` with CI failure details and what was tried

---

## Specification Structure & Traceability

These patterns ensure that specs are machine-readable, individually testable, and traceable from requirement through implementation to test.

### Functional requirement numbering

Every functional requirement in the spec MUST have a unique identifier:
- Format: `FR-001`, `FR-002`, etc. (sequential within the spec)
- Each requirement is a single, testable statement
- Requirements are grouped by feature area or user story

Example:
```
FR-001: System MUST validate all API request bodies against JSON schema before processing
FR-002: System MUST return 400 with error details when validation fails
FR-003: System MUST log validation failures at WARN level with request correlation ID
```

### Success criteria

Every spec MUST include a **Success Criteria** section with measurable criteria:
- Format: `SC-001`, `SC-002`, etc.
- Each criterion maps to one or more functional requirements
- Criteria are verifiable by tests or inspection

Example:
```
SC-001: All FR-001 through FR-003 pass integration tests [validates FR-001, FR-002, FR-003]
SC-002: Zero critical vulnerabilities in security scan [validates FR-045]
SC-003: All flows in UI_FLOW.md have corresponding e2e tests [validates FR-087]
```

### Story-to-task traceability

Every task in `tasks.md` MUST reference the user story or functional requirement it implements:
- Format: `[Story 3]` or `[FR-015]` suffix on the task description
- This enables bidirectional traceability: from requirement → task → test
- During code review, reviewers can verify that every requirement has a corresponding task and test

### Structured learnings format

`learnings.md` MUST be structured by task ID:

```markdown
### T001 — Custom test reporter
- Gotcha: Node.js test runner custom reporters must export a default function, not a class
- Decision: Using `spec` reporter as base, extending with JSON output

### T008 — WebSocket session streaming
- Gotcha: Must buffer all WebSocket messages from connection time, not from subscription time
- Pattern: Created `BufferedWebSocket` helper that queues messages until consumer is ready
```

Each entry captures: what was discovered, which task revealed it, and actionable implications for later tasks. This creates a pre-validation oracle — agents implementing T015 can read T001-T014's learnings first.

### Auto-generated CLAUDE.md

When a spec-kit project has multiple features, the project's `CLAUDE.md` MUST be kept in sync:
- **Auto-generated sections**: Active technologies, project structure, commands, code style — derived from the latest plan
- **Manual additions section**: Workflow instructions, environment setup, and other human-authored content (between `<!-- MANUAL ADDITIONS START -->` and `<!-- MANUAL ADDITIONS END -->` markers)
- Each new feature spec updates the auto-generated sections without overwriting manual additions
- Include a header: `Auto-generated from all feature plans. Last updated: <date>`

### Interview handoff documents

When the interview phase completes, the system MUST produce handoff documents for downstream phases:

- **`interview-notes.md`**: Key decisions, gaps, and open questions from the interview — a lightweight summary that planning agents read instead of the full transcript
- **`transcript.md`**: Full conversation history for reference and crash recovery
- **`spec.md`**: The structured specification output

Planning agents read `interview-notes.md` + `spec.md` for context. `transcript.md` is only used for crash recovery (if the interview session dies and needs to resume).

---

## Interaction style

- **Be a guide, not a lecturer.** The user may not know SDD — explain just enough for each step, then do it.
- **Propose, don't interrogate.** When gathering spec information, make concrete suggestions based on what you know about the project.
- **Show progress.** After each phase, summarize what exists and what's next.
- **Respect the workflow order** but don't be rigid — if the user wants to jump ahead or skip a phase, let them.
- **Read the command templates.** The `.specify/commands/` directory contains the actual prompts for each phase. Always read the relevant template before executing a phase — don't wing it from memory.

---

## Rules

- Always check for an existing `.specify/` directory before running `init`.
- Never modify spec-kit's generated command templates in `.specify/commands/`.
- Read the relevant command template before executing each phase.
- If a phase produces output files, verify they were created successfully.
- If `specify init` fails, check Python version (needs 3.11+) and `uv` availability.
- The `--ai claude` flag configures spec-kit for Claude — always use it during init.
