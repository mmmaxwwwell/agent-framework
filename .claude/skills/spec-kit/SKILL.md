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
2. **If not installed**, install it:
   ```bash
   uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
   ```
   If `uv` is not available, tell the user they need to install `uv` first (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
3. Verify: `specify --version`

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
- **MANDATORY**: Every spec MUST include a **Testing** section with functional requirements for integration tests. See "Integration Testing Requirements" below — these requirements must be woven into the spec, not added as an afterthought.

**Clarify (Phase 3):**
- Scans for ambiguities across 11 categories.
- Generates up to 5 prioritized questions, presented one at a time.
- Integrates answers back into the spec.

**Plan (Phase 5):**
- Generates `plan.md` plus supporting docs (data models, API contracts, test scenarios).
- Runs a research phase first, then a design phase.
- Checks constitutional compliance.
- **MANDATORY**: The plan MUST include a test infrastructure phase (Phase 1 or early) that builds structured test output before any feature work. The plan MUST describe the fix-validate loop strategy. See "Integration Testing Requirements" below.

**Tasks (Phase 6):**
- Generates `tasks.md` with dependency-ordered, phased tasks.
- Tasks marked `[P]` can be parallelized.
- Phases: Setup → Foundational → User Stories (P1-P3) → Polish.
- **MANDATORY**: Task list MUST follow the fix-validate loop pattern. See "Integration Testing Requirements" below for the required task structure.

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
4. Runs the project's build/test commands (from `CLAUDE.md` or `package.json`)
5. Self-reviews the diff for debug code, security issues, and pattern consistency
6. Records discoveries and decisions in `learnings.md` (persists across runs)
7. Marks the task `- [x]` and commits with the task ID (e.g., `feat(T008): implement HTTP server`)
8. Loop repeats until all tasks are done, `BLOCKED.md` is written, or the run limit is hit

**Automatic code review** — When the last implementation task completes, the agent appends a `REVIEW` task. The runner detects this, switches to a review-specific prompt that embeds the appropriate code-review skill (React, Node, or general), diffs all changes from the feature branch, and writes findings to `REVIEW.md` in the spec directory. The review is read-only — it reports issues but does not fix them.

**learnings.md** — a shared memory file in the spec directory that accumulates across runs. Each agent reads it for context and appends gotchas, decisions, and patterns it discovered. This prevents repeated mistakes and keeps later agents consistent with earlier decisions.

**BLOCKED.md** — if the agent hits ambiguity or a build failure it can't fix, it writes `BLOCKED.md` and the script stops. Edit the file with your answer, delete it, re-run.

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

### What the run-tasks agent MUST do

The implementation agent (spawned by `run-tasks.sh`) enforces the fix-validate loop on every task:

1. After implementing a task, run the project's test command
2. If tests fail, read `test-logs/` for structured failure output
3. Fix the code (not the tests)
4. Re-run tests
5. Repeat until green or 3 attempts exhausted (then BLOCKED.md)
6. Only mark the task complete when tests pass

This is already described in the run-tasks.sh prompt's Step 4, but the key addition is: **the agent MUST read `test-logs/` rather than parsing raw test runner output**. The structured logs are the primary feedback mechanism.

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
