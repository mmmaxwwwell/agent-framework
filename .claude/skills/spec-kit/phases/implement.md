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
3. The validation agent runs a four-step sequence: **build → test → lint → security scan**. Build failure skips all later steps. Test failure still runs lint (so the fix agent can address both in one pass). Security scans only run if build and test pass.

#### Multi-build-system discovery (MANDATORY)

The validation agent MUST NOT assume there is a single build command. Before running validation, it discovers ALL build systems in the project by scanning for build manifests:

| Manifest | Build system | Build command | Test command |
|----------|-------------|---------------|-------------|
| `go.mod` | Go | `go build ./...` | `go test ./...` |
| `build.gradle.kts` / `build.gradle` | Gradle | `./gradlew assemble` | `./gradlew test` |
| `Cargo.toml` | Cargo | `cargo build` | `cargo test` |
| `package.json` | npm/pnpm/yarn | `npm run build` | `npm test` |
| `pyproject.toml` / `setup.py` | Python | `python -m build` | `pytest` |
| `CMakeLists.txt` | CMake | `cmake --build build/` | `ctest --test-dir build/` |
| `flake.nix` | Nix | `nix build` | `nix flake check` |
| `Makefile` | Make | `make build` | `make test` |

**Discovery rules:**
1. Scan the project root AND immediate subdirectories (e.g., `android/build.gradle.kts` in a Go+Android project)
2. For each manifest found, add its build and test commands to the validation sequence
3. If `CLAUDE.md` lists explicit build/test commands, those take precedence over auto-discovered defaults for that build system
4. Run ALL discovered build commands — a project with `go.mod` at root and `build.gradle.kts` in `android/` must build BOTH
5. A phase passes validation only if ALL build systems pass. One failing build system = phase FAIL.

**Why this matters:** In multi-language projects (Go+Kotlin, Rust+TypeScript, Python+C++), agents routinely validate only the primary language's build. The secondary language's build fails silently, and the agent declares the phase "done." This rule makes secondary builds structurally un-skippable.
4. **If validation passes** (all steps clean, zero security findings) → the agent writes `specs/<feature>/validate/phase3/1.md` with `PASS`. The runner marks the phase as validated and allows downstream phases to start.
5. **If validation fails** (test failure, lint error, OR security finding) → the agent writes `specs/<feature>/validate/phase3/1.md` with `FAIL` including a **failure categories** summary (Build: PASS/FAIL, Test: PASS/FAIL, Lint: PASS/FAIL, Security: PASS/FAIL) plus per-step details (command, exit code, root cause summary, individual failures with file/line). This structured record lets the fix agent immediately see which steps failed without parsing raw output.
6. **Next runner iteration** picks up `phase3-fix1` as a normal implementation task with fresh context — reads the full failure history from `validate/phase3/` (including structured failure categories), reads `test-logs/` and `test-logs/security/`, checks prior fix attempts to avoid repeating failed approaches, diagnoses and fixes. The fix agent runs build+test+lint locally before marking complete to catch cascading issues in a single pass.
7. After the fix agent completes, the runner spawns another validation agent. If still failing → `validate/phase3/2.md`, appends `phase3-fix2`.
8. After 10 failed fix attempts → validation agent writes `BLOCKED.md` and the runner stops.

**Why a dedicated validation agent?** Implementation agents used to be responsible for running validation when they were the last task in a phase. In practice, agents skipped this step — especially with parallel tasks where no agent could reliably detect it was "last". Moving validation to a dedicated agent spawned by the runner makes it structural and un-skippable.

### No "expected failure" rationalization (MANDATORY)

Agents MUST NEVER classify a build, test, lint, or security failure as "expected," "work in progress," "known issue," or "will be fixed later." If a command fails, the agent fixes it — period. There are exactly TWO valid responses to a validation failure:

1. **Fix the code** so the command passes
2. **Write BLOCKED.md** if the failure genuinely requires human input (missing credentials, design ambiguity, hardware)

The following rationalizations are PROHIBITED:
- "The Android/frontend/secondary-language build is still a work in progress" — if tasks.md includes tasks for that component, its build must pass
- "This test is flaky" — fix the flake or add retry logic, don't skip it
- "This security finding is not relevant to our use case" — suppress with an inline justification comment (see security scan rules), don't ignore it
- "CI will catch this later" — local validation exists precisely to catch it NOW
- "The Gradle/Cargo/npm failure is expected because we haven't implemented X yet" — if X is in the task list and the phase depends on it, the phase must not pass until X works

**Why this rule exists:** Agents are trained to be helpful and accommodating. When faced with a failing build they can't easily fix, the path of least resistance is to explain why it's OK and move on. This is the single most common cause of broken releases — the agent rationalizes a failure, marks the phase done, and the broken build propagates to CI where it fails in front of humans. The rule is absolute: failures are fixed or blocked, never rationalized.

Key properties:
- **Runner-enforced** — validation is triggered by the scheduler, not by agent discretion
- **Validation is per-phase, not per-task** — avoids wasting runs on intermediate states
- **Downstream phases are blocked** until the upstream phase passes validation
- **Each fix gets a fresh agent** with full context budget — no degradation from prior attempts
- **Failure history accumulates on disk** in `validate/<phase>/` — nothing is lost between runs
- **Tests are the spec** — fix the code, not the tests (unless a test is genuinely wrong)
- **Security scans are part of validation** — a phase with security findings doesn't pass, same as a phase with test failures
- **Structured test output** is the primary feedback mechanism — agents read these rather than parsing raw test runner output

### Security scan in validation

The validation agent runs security scanners **after** build + test + lint pass. This ordering prevents wasting scanner time on code that doesn't compile, and prevents noise from scanners flagging code that's about to be rewritten by a test-failure fix.

**Scanner output**: Written to `test-logs/security/` in JSON format. The validation agent produces a `test-logs/security/summary.json` aggregating results across all scanners.

**Fix agent behavior for security findings**:
- Read `test-logs/security/summary.json` for scope (which scanners found issues, how many)
- Read individual scanner JSON files for details (file, line, rule ID, severity, description)
- Classify each finding: dependency vulnerability → update version; SAST pattern → fix code; secret → remove and rotate; false positive → suppress with justification
- Never suppress without a justification comment. Record suppressions in `learnings.md`.

See `reference/security.md` for the full scanner command list and finding classification table. See `reference/cicd.md` for how local security validation integrates with CI SARIF uploads.

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

If the agent hits a blocker, it MUST NOT immediately write `BLOCKED.md`. Instead, it must first evaluate whether it can resolve the blocker autonomously. See "Auto-Unblocking" below for the full decision process. Only write `BLOCKED.md` for genuinely human-dependent blockers. When `BLOCKED.md` is written, the script stops. Edit BLOCKED.md with your answer, then re-run — the runner will consume the answer, clean up the file, and retry the blocked task.

### Rate limits

Detected from agent stderr. The runner waits 60s then retries the task.

### No-op detection

Stops after 5 consecutive scheduling cycles with no progress (all agents stuck).

### When to suggest it

When the user has completed planning (tasks.md exists) and asks to start or run implementation, tell them the command to run. Resolve the absolute path to the script based on where the skill is installed.

---

## Environment preflight verification

Before the first implementation task begins, the runner or the Phase 1 agent MUST verify that the development environment provides every tool the project needs. This catches "command not found" errors at the start — not after 3 fix-validate cycles on Phase 4.

### What to verify

For every build/test/lint command listed in `CLAUDE.md` or the plan's tool environment inventory:

1. **Check tool availability** — run `command -v <tool>` (or `<tool> --version`) inside the dev environment (`nix develop`, or whatever the project uses). If the tool is missing, the environment is incomplete.
2. **Check transitive dependencies** — wrapper scripts (e.g., `./gradlew`, `./mvnw`) self-bootstrap their tool but often need a runtime (JDK, SDK, .NET runtime) provided by the environment. Verify the runtime is present, not just the wrapper.
3. **Check platform-specific requirements** — if any tool needs KVM, a display server, or a specific kernel module, verify it's available (e.g., `test -w /dev/kvm` for emulator tests).

### When to run

- **Phase 1 (test infrastructure / flake setup)**: After writing `flake.nix` and entering the dev shell, run the full preflight check. If any tool is missing, fix `flake.nix` before proceeding. This is the cheapest time to catch environment gaps.
- **Phase validation**: Before the build step in the validation sequence, run a lightweight tool availability check. This catches tools that were added to later phases but not to the environment.

### Preflight script pattern

The Phase 1 agent should create a `scripts/preflight.sh` (or equivalent Makefile target) that verifies all tools:

```bash
#!/usr/bin/env bash
# Generated from plan's tool environment inventory — customize per project
set -euo pipefail
missing=0
# Add every tool from the plan's inventory:
for cmd in <tool1> <tool2> <tool3>; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "MISSING: $cmd — add to flake.nix devShell"
    missing=1
  fi
done
exit $missing
```

The exact tool list comes from the plan's tool environment inventory. This script runs in seconds and gives a clear error message per missing tool — far better than a cryptic build failure 10 minutes into a phase.

### Multi-language project trap

The most common environment gap is in multi-language projects: the primary language's tools are in the flake, but secondary languages are forgotten. The plan's tool environment inventory exists to enumerate all tools across all stacks — but the Phase 1 agent must actually add them all to `flake.nix` and verify with the preflight check.

The plan's tool environment inventory (see `phases/plan.md` § Technology stack) exists to prevent this. The preflight check verifies it.

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

---

## Post-Implementation Validation: Local Smoke Test + CI/CD

After ALL implementation phases pass their automated tests and code reviews, the runner enters the **post-implementation validation** phase. This is where the agent becomes the user — it builds the distributable artifact, installs it in a clean-ish environment, and exercises every primary user flow end-to-end. Then it pushes to the remote and fix-validates CI/CD.

This phase exists because automated tests — even good integration tests — miss an entire class of bugs that only surface when you actually run the finished product. Packaging manifests exclude files. Dev-only paths break. Native libraries aren't linked. First-run downloads fail. Loading states are missing. The agent troubleshoots these exactly like a human developer would, except it doesn't give up after the first error.

### Phase 1: Build and Install ALL Artifacts

**MANDATORY: Build EVERY distributable artifact the project produces, not just the primary one.**

1. **Discover all artifacts** — scan the project for every build output that users or CI would produce:
   - Check `CLAUDE.md` / `Makefile` for build targets
   - Check CI workflow files (`.github/workflows/`) for build jobs — every `upload-artifact` step implies an artifact that must be buildable
   - Check for platform-specific build directories (`android/`, `ios/`, `desktop/`, `web/`)
   - Check `flake.nix` for package outputs (`packages.<system>.*`)

2. **Build each artifact** — run each build command and verify it succeeds:

   | Artifact type | Build command examples | Verify |
   |--------------|----------------------|--------|
   | Go binary | `go build`, `nix build` | Binary exists, runs `--version` |
   | Android APK | `./gradlew assembleDebug`, `./gradlew assembleRelease` | APK exists at expected path |
   | Python package | `python -m build` | `.whl` and `.tar.gz` exist in `dist/` |
   | npm package | `npm pack` | `.tgz` exists |
   | Container image | `docker build` | Image exists in local registry |
   | VS Code extension | `vsce package` | `.vsix` exists |
   | Nix package | `nix build .#<pkg>` | `result/` symlink exists |

3. **Install in a clean-ish environment** — NOT the dev workspace. For extensions: install the packaged artifact via the platform's CLI (`code --install-extension *.vsix`). For packages: install in a fresh venv/node_modules. For binaries: copy to a temp dir and run from there. For containers: `docker run` with no volume mounts to the source tree. For APKs: install on emulator (`adb install`).

4. **Verify each artifact contains everything it needs** — list the contents of the package and check against the project's runtime dependencies. If files are missing (source code, models, config templates, native libs), fix the packaging manifest and rebuild.

5. **Cross-reference with CI release workflow** — for every artifact that the release workflow uploads (e.g., `gh release upload`), verify that the local build produces the same artifact at the same path. If the release workflow renames the artifact (e.g., `app-release.apk` → `nix-key-{version}.apk`), verify the rename logic works.

### Phase 2: User Flow Smoke Test (fix-validate loop)

For each primary user flow from the spec:

1. **Exercise the flow from the user's entry point** — launch the installed artifact, trigger the first user action, and observe what happens. Capture ALL output: stdout, stderr, log files, status changes.
2. **When it fails (it will)** — read the error, classify it (see bug taxonomy below), fix it, rebuild, reinstall, retry. This is a fix-validate loop with a cap of 20 iterations per flow.
3. **Track progress** — after each fix, note which step in the chain you reached. If you're not getting farther after 3 consecutive fixes, escalate: re-read the full error chain, check if a foundational assumption is wrong (wrong model version, wrong Python version, missing system library), and try a different approach.
4. **Verify loading/initialization states** — on first launch, observe: does the UI show a loading/preparing state while resources download? Does it degrade gracefully if a dependency is slow? Does it recover after a transient failure? Missing loading states are the #1 UX bug in first-run scenarios.
5. **Test cold start vs warm start** — clear caches, delete downloaded models/resources, restart. Verify the first-run experience works. Then verify the second run is faster (cached).

### Phase 3: CI/CD Validation (fix-validate loop)

After local smoke passes:

#### Step 1: Reproduce CI locally FIRST

Before pushing, run the same checks CI would run — locally. Most CI failures are reproducible without a remote runner. Fix everything you can find before burning a push+CI cycle.

**Nix projects** (if `flake.nix` exists):
1. `nix flake check` — runs all flake checks (tests, linting, formatting, NixOS VM tests). This is what CI runs. Fix every failure.
2. `nix build` (or `nix build .#<package>` for each package) — verify the package builds in a pure Nix sandbox (no dev shell, no impurities).
3. `nix flake show` — verify all outputs are well-formed and nothing is broken by missing inputs.
4. If the flake has NixOS tests (`checks.<system>.<name>`), they run as part of `nix flake check`. If any fail, read the test driver output and fix.
5. `nix fmt -- --check` — verify formatting if a formatter is configured in the flake.

**Non-Nix projects**:
1. Read `.github/workflows/` (or `.gitlab-ci.yml`, etc.) to understand exactly what CI runs.
2. Run each CI step locally in order: install deps, build, test, lint, security scan, package.
3. If CI uses a different OS (e.g. Ubuntu), check for platform-specific assumptions: paths, system packages, shell syntax.

**ALL workflow files, not just CI** (applies to both Nix and non-Nix projects):
1. Read EVERY workflow file in `.github/workflows/` — not just `ci.yml`. Release workflows, E2E workflows, and scheduled workflows all contain build/test commands that must work.
2. For each workflow, identify every `run:` step and every build job. Categorize each as:
   - **Locally reproducible** — run it now (build commands, test commands, lint, security scans)
   - **CI-only but verifiable** — can't run the action but can verify the inputs exist (SARIF files for upload, artifacts at expected paths, workflow YAML syntax)
   - **CI-only and opaque** — requires CI secrets or infrastructure (Snyk with token, SonarCloud, deploy steps). Skip but verify the `continue-on-error` / conditional logic is correct.
3. For release workflows specifically: verify that every artifact the release workflow builds and uploads can be built locally. If the release workflow runs `./gradlew assembleRelease` and uploads the APK, that command must succeed locally.

**Fix-validate locally** until all commands pass. Only proceed to Step 2 when local CI reproduction is clean.

#### Step 2: Push and monitor remote CI

1. **Commit and push** to a feature branch
2. **Monitor CI** — use `gh run list` and `gh run view` to watch the pipeline
3. **When CI fails** — use `gh run view --log-failed` to read the failure logs. **Reproduce the failure locally first** (re-run the failing command), fix locally, verify locally, then push. Do not push speculative fixes.
4. **Failures that genuinely can't reproduce locally** (rare after Step 1):
   - Missing secrets/tokens (add to repo secrets, or mock for CI)
   - Network restrictions (CI can't reach internal registries — use public mirrors or cache in the workflow)
   - CI runner differences (older glibc, missing system libs not in Nix closure — add to flake `buildInputs`)
   - Timeout differences (CI runners are slower — increase test timeouts for integration tests)
5. **No hard cap** — same rules as smoke test: keep going as long as there's forward progress. Only write `BLOCKED.md` if stuck in circles or genuinely blocked (missing secrets, permissions, etc.).

### Bug taxonomy for smoke test troubleshooting

When a failure occurs during smoke testing, classify it to choose the right fix strategy. This taxonomy is ordered by frequency — the agent should check the most common categories first.

| Category | Symptoms | Fix strategy |
|----------|----------|--------------|
| **Packaging manifest gaps** | `MODULE_NOT_FOUND`, `FileNotFoundError`, missing source files | Fix `.vscodeignore` / `MANIFEST.in` / `files` in `package.json`. Rebuild and verify file list. |
| **Native library not linked** | `OSError: cannot load library`, `PortAudio not found`, `libXXX.so not found` | Add the library to `LD_LIBRARY_PATH` (Linux), `DYLD_LIBRARY_PATH` (macOS), or bundle it. For Nix: add to `buildInputs` and expose via `LD_LIBRARY_PATH` in the spawn environment. |
| **Dependency version incompatibility** | `No wheel for cpXXX`, `ModuleNotFoundError` for a sub-module that was removed, model input shape mismatch | Pin the exact working version. Check if the dep has wheels for the target Python/Node version. For models: verify the model file matches the code's expected API (input tensor names, output shape). |
| **Dependency API breakage** | `ImportError: cannot import name 'X'`, `AttributeError`, `TypeError` on a library call that used to work | The library removed/renamed an API between versions. Pin to the last working version, or update the code to use the new API. Add a smoke test that imports and calls the specific APIs used. |
| **Transitive dependency resource gaps** | Package installs but resource files (models, templates, configs) are missing from the installed location | The pip/npm package doesn't include data files, or a post-install hook didn't run. Download resources explicitly, cache them outside the venv, and copy/symlink into place. |
| **Network/TLS in isolated environments** | `SSL: CERTIFICATE_VERIFY_FAILED`, `ConnectionError` on downloads that work in dev | The isolated environment (venv, container, CI) may not have system CA certs. Use `certifi` (Python) or `NODE_EXTRA_CA_CERTS` (Node). Or use a library with bundled certs (`requests` vs `urllib`). |
| **Hardcoded paths / URLs** | `404 Not Found` on downloads, `ENOENT` on file reads, wrong binary path | Replace hardcoded absolute paths with relative paths from the artifact root. For download URLs: verify the URL is correct (case-sensitive repo names, correct release tags, correct version). |
| **Output format assumptions** | Feature works but downstream processing fails (regex doesn't match, parser rejects input) | The real output format differs from what the code assumes. E.g., Whisper adds punctuation, APIs return different field names, model outputs different precision. Fix the parser to be tolerant of real output. |
| **Cross-app sandbox limitations** | Can't write to another extension's input, can't simulate keystrokes, can't access webview | The target app's API is more limited than assumed. Identify what IS possible (clipboard, public commands, IPC). Implement the best available mechanism and document the limitation. |
| **Platform-specific behavior** | Works on X11 but not Wayland, works on macOS but not Linux, works on Python 3.11 but not 3.12 | Test on the actual target platform. For display server differences: detect at runtime and use the appropriate tool. For Python/Node version differences: pin in the project config and verify in CI. |
| **Missing loading/initialization states** | UI appears broken during startup, no feedback during downloads, user sees error before system is ready | Add intermediate states (Preparing, Downloading, Connecting) to the UI. Show progress for slow operations. Don't show "ready" until ALL subsystems are initialized. |
| **Process stderr not captured** | Child process crashes but parent shows generic "failed" with no details | Capture and log child process stderr. Include it in error messages. Parse structured log output if the child uses JSON logging. |
| **Ephemeral build environments** | `.venv` recreated on each install, losing cached pip packages / downloaded resources | Cache resources outside the ephemeral directory (`~/.cache/<project>/`). Copy into the build environment on startup instead of re-downloading. |

### Agent escalation strategy

The smoke test loop uses a **fast-then-deep** strategy:

1. **Use opus for all smoke test iterations.** These failures are often non-obvious — version incompatibilities, model format mismatches, platform-specific behavior, packaging gaps that require understanding the full build chain. A weaker model will waste iterations misdiagnosing the problem.
2. **After 5 consecutive iterations with no progress on the SAME error**: The agent should enable full research capability — web search for the specific error, check library changelogs for breaking changes, read platform documentation for sandbox limitations.
3. **When the agent resolves a bug and hits a NEW error**: The stall counter resets to 0. This is forward progress, not a stall.
4. **There is NO hard iteration cap.** As long as the agent is making forward progress (getting farther in the chain, encountering new errors at later steps, or the error is changing category), keep going. The only reasons to write `BLOCKED.md` are:
   - **Circular**: the agent has tried the same fix category 3+ times and keeps reverting to the same error
   - **Stuck**: 5+ consecutive iterations with zero forward progress — same step, same error category, no new information
   - **Genuinely human-dependent**: the fix requires credentials, hardware, or a design decision the agent can't make

"Forward progress" means ANY of: reaching a later step in the user flow chain, encountering a new error category, or the same error now has a different root cause. If the agent fixed 15 different issues and is on issue 16, that's progress — keep going.

"Going in circles" means: the agent applied a fix, it broke something earlier that was already working, it fixed that, and now the original error is back. When this happens, the deep agent must step back, understand the dependency between the two fixes, and find a solution that satisfies both constraints simultaneously.

---

## Mid-Implementation Spec Amendment

During implementation, agents (or the user) may discover that a spec decision was wrong — not a blocker that needs human input, but a fundamental assumption that needs to change and may affect other tasks. This is distinct from BLOCKED.md (which means "I can't proceed") — an amendment means "I CAN proceed but the spec premise is wrong and other tasks will be affected."

### When to write an amendment (not BLOCKED.md)

Write `AMENDMENT-<task_id>.md` when:
- A spec requirement contradicts what's technically possible (e.g., "FR-012 says use HMAC, but the phone's keystore only supports ECDSA")
- An interface contract proves unworkable (e.g., "IC-003 specifies Unix socket, but the daemon needs TCP for cross-host access")
- An architectural assumption in `research.md` is provably wrong (e.g., "research.md says library X supports streaming, but it doesn't")
- A completed task's output doesn't match what downstream tasks expect, and fixing it requires changing the spec (not just the code)

Do NOT write an amendment for:
- Build failures, missing tools, or environment issues (these are auto-resolvable — see Auto-Unblocking)
- Test failures within the current task (fix the code, not the spec)
- Ambiguity that can be resolved by reading `interview-notes.md` or `research.md`

### Amendment file format

```markdown
# AMENDMENT: [TASK_ID] — [one-line summary]

## What the spec says
[Quote the specific FR, SC, or plan decision that needs to change]

## What reality requires
[What the agent discovered and why the spec is wrong]

## Affected tasks
[List task IDs that depend on the incorrect assumption — both completed and pending]

## Proposed change
[Specific text change to spec.md and/or plan.md]

## Evidence
[Error messages, documentation links, test output proving the spec is wrong]
```

### How the runner handles amendments

1. Agent writes `AMENDMENT-<task_id>.md` to the spec directory
2. Runner detects the file (same mechanism as BLOCKED.md detection)
3. Runner pauses only the affected downstream tasks listed in the amendment (not all tasks)
4. Runner presents the amendment to the human for approval
5. Human approves, modifies, or rejects the amendment

### After human approval

1. **Update `spec.md`** — append an amendment section (ADR-style, append-only with date) rather than silently editing the original text. This preserves decision history:
   ```markdown
   ## Amendments

   ### AMD-001 (2026-03-30): ECDSA instead of HMAC for phone signing [T015]
   **Original**: FR-012 specified HMAC-SHA256 for signature operations
   **Amended to**: FR-012 now specifies ECDSA-P256, matching the phone keystore's hardware-backed keys
   **Reason**: Android hardware keystore does not support HMAC for asymmetric operations
   **Affected**: T015 (current), T018 (verification), T033 (daemon sign handler)
   ```

2. **Update `plan.md` and `research.md`** if the amendment affects architecture decisions

3. **Evaluate completed tasks** — for each affected completed task, the human decides:
   - **No rework needed** — the amendment is cosmetic or the completed task's output is still valid
   - **Rework needed** — uncheck the task in `tasks.md` (mark `[ ]` again). The runner re-parses and schedules it as a normal pending task with amendment context

4. **Record in `learnings.md`** — so downstream agents understand why the change was made

5. **Runner resumes** — re-parses `tasks.md`, picks up any reopened tasks and unpaused pending tasks

### Design principles

- **Lightweight** — writing an amendment should be as easy as BLOCKED.md. If it's harder, agents will use BLOCKED.md instead and the propagation benefit is lost.
- **Append-only spec changes** — never silently edit spec.md. The amendment trail helps future agents understand why decisions changed.
- **Surgical pausing** — only affected tasks are paused, not the entire pipeline. Unrelated parallel work continues.
- **Human approval required** — agents don't unilaterally change the spec. The human validates the amendment and decides on rework scope.

---

## BLOCKED.md format

When `BLOCKED.md` IS written (genuinely human-dependent), it MUST include:

```markdown
# BLOCKED: [TASK_ID] — [one-line summary]

## What I need
[Specific question or action required from a human]

## What I tried
[List of auto-resolution attempts and why they failed]

## Context
[Relevant error messages, log output, file paths]

## Suggested resolution
[What the human should do, as specifically as possible]
```
