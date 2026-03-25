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
4. Executes ONE task, following TDD and the fix-validate loop
5. Self-reviews, records learnings, marks complete, commits
6. The runner re-parses `tasks.md` after each agent finishes to pick up changes and schedule the next wave

### Fix-validate loop

Validation runs at **phase boundaries**, not per-task. It's a **disk-based state machine** driven by the task runner:

1. Agents implement tasks T007, T008, T009 (all in Phase 3). Each agent marks its task done and commits.
2. The agent completing the **last task in Phase 3** runs the project's test suite.
3. Validation fails → agent writes failure state to `specs/<feature>/validate/phase3/1.md` (command, exit code, structured test output from `test-logs/`, list of tasks completed in this phase)
4. Agent appends `- [ ] phase3-fix1 Fix phase validation failure: read validate/phase3/ for failure history` to `tasks.md` at the end of Phase 3
5. **Next runner iteration** picks up `phase3-fix1` with fresh context — reads the full failure history from `validate/phase3/`, reads `test-logs/`, diagnoses and fixes across all files touched by the phase
6. The fix agent re-runs validation. If it still fails → writes `validate/phase3/2.md`, appends `phase3-fix2`
7. After 10 failed fix attempts → writes `BLOCKED.md` and the runner stops

Key properties:
- **Validation is per-phase, not per-task** — avoids wasting runs on intermediate states
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

### Automatic code review

When the last implementation task completes, the agent appends a `REVIEW` task. The runner detects this, switches to a review-specific prompt that embeds the appropriate code-review skill (React, Node, or general), diffs all changes from the feature branch, and performs a two-tier review:

1. **Auto-implement necessary fixes** — bugs, security vulnerabilities, correctness issues, broken error handling, missing input validation, and anything that would cause runtime failures or data loss. The agent fixes these directly in the code and commits.
2. **Write `REVIEW-TODO.md`** — optional improvements that are helpful but not necessary: refactoring suggestions, performance optimizations, better naming, additional test coverage, documentation gaps, code style improvements. Each item includes the file, line range, what to improve, and why. This file lives in the spec directory alongside `REVIEW.md`.
3. **Write `REVIEW.md`** — summary of all findings: what was auto-fixed (with commit refs), what was deferred to `REVIEW-TODO.md`, and overall assessment.
4. **Fix-validate loop** — after applying fixes, the agent runs the project's test suite. If tests fail (the review fixes broke something), the agent enters the standard fix-validate loop: read `test-logs/`, diagnose, fix, re-run. After 10 failed attempts, write `BLOCKED.md`. Tests MUST pass before the review task is marked complete.

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
- **Missing CLI tool**: If the project has a `flake.nix`, add the tool there and re-enter `nix develop`. Otherwise, install via `uv tool install`, `npm install -g`, or the system package manager.
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
