# Spec-Kit Implementation Phase

## Autonomous implementation with run-tasks.sh

Once `tasks.md` exists, the user can run implementation autonomously using the task runner bundled with the spec-kit skill at `.claude/skills/spec-kit/run-tasks.sh`. The runner is a Python script (`parallel_runner.py`) that parses the task list, respects `[P]` parallel markers and phase dependency graphs, and spawns multiple claude agents concurrently where safe.

**How to launch it:** Determine the absolute path to `run-tasks.sh` within the skill directory (it lives alongside `SKILL.md`). Then run it from the target project root:

```bash
cd <project-root>

# TUI mode (default) — live dependency graph + split agent output panes
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py                                  # all features
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py specs/001-my-feature              # specific spec
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py specs/001-my-feature 50           # max 50 runs
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py --max-parallel 5 specs/001        # 5 agents

# Headless mode — no stdin/stdout, all output to log files
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py --headless                        # all features
python3 /path/to/agent-framework/.claude/skills/spec-kit/parallel_runner.py --headless --max-parallel 5       # 5 agents

# Or via the bash wrapper (validates python version, then exec's the above):
/path/to/agent-framework/.claude/skills/spec-kit/run-tasks.sh [same args]
```

The script requires **Python 3.9+** (stdlib only, no pip dependencies) and the `claude` CLI. Must be run from the project root (where `.specify/` and `specs/` live). Run it in tmux/screen so it survives terminal disconnects.

### Two modes

**TUI mode** (default) — the terminal is split into two sections:
- **Top**: ASCII dependency graph showing all phases, tasks, their status (○ pending, ◉ running, ● complete, ⊘ skipped, ⊗ blocked, ✗ failed), `[P]` markers, and phase dependency arrows
- **Bottom**: horizontally split panes showing live output from each running agent (e.g. 2 agents = 3 sections: graph + 2 output panes separated by vertical bars)

**Headless mode** (`--headless`) — no terminal I/O at all. Everything is written to `logs/parallel-<timestamp>/`:
- `runner.log` — main orchestrator log
- `agent-<N>-<task-id>.jsonl` — raw stream-json output per agent
- `agent-<N>-<task-id>.stderr` — stderr per agent
- `status.txt` — periodically updated snapshot of all phases/tasks/agents

### How it works

The runner parses `tasks.md` for phases, `[P]` markers, and the Phase Dependencies section. It builds a dependency graph and continuously schedules ready tasks:

1. **Parallel scheduling**: Tasks marked `[P]` within a phase run concurrently (up to `--max-parallel`, default 3). Sequential tasks (no `[P]`) block subsequent tasks in the same phase. Phase boundaries respect the dependency graph.
2. Each agent gets a fresh `claude` process with a prompt targeting its specific task (full context budget, no degradation)
3. The agent reads the task list, learnings, and only the reference files relevant to its task
4. Executes ONE task, following TDD
5. Self-reviews, records learnings, marks complete, commits
6. The runner re-parses `tasks.md` after each agent finishes to pick up changes and schedule the next wave
7. **When all tasks in a phase are complete**, the runner automatically spawns a dedicated **validation agent** (see below)

### Fix-validate loop

Validation runs at **phase boundaries**, not per-task. It is **enforced by the runner**, not by implementation agents — this ensures validation always happens and can't be skipped.

**How it works:**

1. Agents implement tasks T007, T008, T009 (all in Phase 3). Each agent marks its task done and commits.
2. The runner detects that all Phase 3 tasks are complete and spawns a **validation agent**.
3. The validation agent runs the project's build/test commands (from `CLAUDE.md` or the phase Checkpoint).
4. **If validation passes** → the agent writes `specs/<feature>/validate/phase3/1.md` with `PASS`. The runner marks the phase as validated and allows downstream phases to start.
5. **If validation fails** → the agent writes `specs/<feature>/validate/phase3/1.md` with `FAIL` (command, exit code, structured test output from `test-logs/`) and appends `- [ ] phase3-fix1 Fix phase validation failure: read validate/phase3/ for failure history` to `tasks.md`.
6. **Next runner iteration** picks up `phase3-fix1` as a normal implementation task with fresh context — reads the full failure history from `validate/phase3/`, reads `test-logs/`, diagnoses and fixes.
7. After the fix agent completes, the runner spawns another validation agent. If still failing → `validate/phase3/2.md`, appends `phase3-fix2`.
8. After 10 failed fix attempts → validation agent writes `BLOCKED.md` and the runner stops.

**Why a dedicated validation agent?** Implementation agents used to be responsible for running validation when they were the last task in a phase. In practice, agents skipped this step — especially with parallel tasks where no agent could reliably detect it was "last". Moving validation to a dedicated agent spawned by the runner makes it structural and un-skippable.

Key properties:
- **Runner-enforced** — validation is triggered by the scheduler, not by agent discretion
- **Validation is per-phase, not per-task** — avoids wasting runs on intermediate states
- **Downstream phases are blocked** until the upstream phase passes validation
- **Each fix gets a fresh agent** with full context budget — no degradation from prior attempts
- **Failure history accumulates on disk** in `validate/<phase>/` — nothing is lost between runs
- **Tests are the spec** — fix the code, not the tests (unless a test is genuinely wrong)
- **Structured test output** is the primary feedback mechanism — agents read these rather than parsing raw test runner output

### Structured test output format (critical for implementing agents)

Implementing agents MUST know this format to read failure logs during the fix-validate loop:

- **Test log directory**: `test-logs/<type>/<timestamp>/`
- **`summary.json`** per run: `{ "pass": number, "fail": number, "skip": number, "duration": number, "failures": ["test name 1", "test name 2"] }`
- **`failures/<test-name>.log`** per failing test containing:
  - `TEST:` — test name
  - `FILE:` — source file and line
  - `ASSERTION:` — expected vs actual
  - `STACK:` — full stack trace
  - `CONTEXT:` — server logs, captured stderr, request/response bodies
- **Passing tests**: one-line summary only (name + duration)

When running the fix-validate loop, agents read `test-logs/` for the latest run, diagnose from `summary.json` → `failures/*.log`, fix code, and re-run. For full details on the test output specification and the testing philosophy (real servers, no mocks at system boundaries, stub process pattern), see `reference/testing.md`.

### Automatic code review (per-phase)

Code review runs **after every phase**, not just at the end. It's structurally enforced by the runner — agents cannot skip it.

**Phase lifecycle:** tasks done → validate → (review → re-validate)* → clean → phase complete

After all tasks in a phase pass validation, the runner spawns a **review agent** that:

1. **Reviews the phase's diff** using the appropriate code-review skill (React, Node, or general — auto-detected from `package.json`)
2. **Auto-fixes bugs** — security vulnerabilities, correctness issues, broken error handling, missing input validation, anything that would cause runtime failures or data loss. Commits each fix.
3. **Writes a review record** to `validate/<phase>/review-N.md` with one of two outcomes:
   - **`REVIEW-CLEAN`** — no bugs found, code is clean. Phase is complete.
   - **`REVIEW-FIXES`** — fixes were applied. Runner spawns a validation agent to re-run tests.

**If the review applied fixes** (REVIEW-FIXES):
1. The runner re-validates (runs build/test commands via a validation agent)
2. If validation fails → standard fix-validate loop (fix task appended, fix agent runs, re-validate)
3. If validation passes → runner spawns **another review cycle** to check the fixes
4. The cycle repeats until a review comes back REVIEW-CLEAN (no more bugs found)
5. Safety cap: after 5 review cycles, the runner treats the phase as clean

**Why per-phase instead of end-of-project?** Issues compound across phases. A bug in Phase 2 may look fine in isolation but cause cascading failures when Phase 3 builds on it. Catching issues early means fix agents have simpler context and fewer moving parts.

Review records accumulate in `validate/<phase>/review-1.md`, `review-2.md`, etc. Each review cycle gets the full history of prior findings to avoid re-reporting fixed issues.

### learnings.md

A shared memory file in the spec directory that accumulates across runs. Each agent reads it for context and appends gotchas, decisions, and patterns it discovered. This prevents repeated mistakes and keeps later agents consistent with earlier decisions.

### BLOCKED.md and auto-unblocking

If the agent hits a blocker, it MUST NOT immediately write `BLOCKED.md`. Instead, it must first evaluate whether it can resolve the blocker autonomously. See "Auto-Unblocking" below for the full decision process. Only write `BLOCKED.md` for genuinely human-dependent blockers. When `BLOCKED.md` is written, the script stops. Edit the file with your answer, delete it, re-run.

### Rate limits

Detected from agent stderr. The runner waits 60s then retries the task.

### No-op detection

Stops after 5 consecutive scheduling cycles with no progress (all agents stuck).

### When to suggest it

When the user has completed planning (tasks.md exists) and asks to start or run implementation, tell them the command to run. Resolve the absolute path to the script based on where the skill is installed.

---

## Auto-Unblocking

Agents MUST NOT write `BLOCKED.md` as a first resort. Many blockers — especially environment setup, tool installation, and dependency configuration — are things the agent can and should resolve autonomously. Writing `BLOCKED.md` for a solvable problem wastes a human's time and stalls the entire pipeline.

### Decision process before writing BLOCKED.md

When an agent encounters a blocker, it MUST evaluate the situation before giving up:

1. **Classify the blocker** into one of these categories:

   | Category | Auto-resolvable? | Examples |
   |----------|-------------------|---------|
   | **Tool/dependency installation** | YES | Emulator not installed, CLI tool missing, package not available, SDK not configured. **Fix by adding to `flake.nix`, never by global install.** |
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

- **Emulator not installed**: Add it to `flake.nix` devShell and re-enter `nix develop`. Create the readiness script if it doesn't exist.
- **Missing CLI tool**: Add the tool to `flake.nix` devShell and re-enter `nix develop`. **NEVER use `npm install -g`, `uv tool install`, `pip install`, or system package managers** — these mutate the host outside the project and are blocked by the sandbox.
- **Any `npm install` / `pnpm install` / `yarn add`**: Always pass `--ignore-scripts`. Then `npm rebuild <pkg>` only for packages that need native compilation (e.g. `esbuild`, `sharp`, `better-sqlite3`).
- **Database not running**: Start it using project-local scripts or `nix develop` process-compose. Create the test database, run migrations.
- **Port conflict**: Find an available port, update the config.
- **Missing test fixtures**: Generate them (keypairs, template files, mock data).
- **Dependency version mismatch**: Update the lockfile or `flake.nix` pins, resolve the conflict.
- **Missing project dependency**: Add to `package.json` / `pyproject.toml` / `flake.nix` and install project-locally (`npm install --ignore-scripts`, `pip install --only-binary :all:` in a venv). Then `npm rebuild <pkg>` only for packages needing native compilation. Never install globally.

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
