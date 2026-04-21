# MCP-Driven E2E Testing

When a project targets a platform runtime (Android, iOS, web), the parallel runner supports **MCP-driven E2E testing** — an automated loop where agents interact with the running app through MCP tools to discover bugs visually, fix them in batches, and verify fixes.

## CRITICAL: Agents use MCP tools directly — they do NOT write scripts

The most dangerous failure mode in MCP E2E task generation is **meta-framework generation**: instead of writing tasks where agents USE MCP tools to interact with the live app, the spec/plan/tasks tell agents to BUILD shell scripts, prompt templates, scenario runners, and orchestration layers that would invoke *future* agents to do the real work.

**This defeats the entire purpose of MCP-driven E2E testing.** The result is thousands of lines of untested scaffolding code, zero actual interaction with the app, and zero bugs found.

### Anti-patterns (NEVER do these)

- Writing a "scenario runner" shell script that invokes `claude` as a subprocess
- Creating "agent prompt templates" (markdown files) that describe what a future agent should do with MCP tools
- Building a `report.sh` / `scenario-runner.sh` / `infrastructure.sh` library for orchestrating agents
- Writing "validation scripts" that test the framework with synthetic/fake data instead of testing the app
- Creating any code whose purpose is to invoke or manage other AI agents

### Correct pattern

Tasks annotated with `[needs: mcp-android, e2e-loop]` get MCP tools injected by the runner. The implementing agent **directly uses** Screenshot, DumpHierarchy, Click, Type, etc. to interact with the live app on the real emulator. The agent reads UI_FLOW.md, looks at the actual screen, and reports real bugs.

The runner handles: emulator boot → APK build+install → MCP server config → agent gets MCP tools → agent interacts with live app → findings.json → fix agent → rebuild → verify agent. No custom orchestration code needed.

**If a task description says "create a script that..." or "write a prompt template for..." for E2E testing, it is WRONG.** The task should say "use MCP tools to verify [screen/flow/state] on the live emulator."

## Overview

Traditional E2E tests are scripted: you write the test, run it, check pass/fail. MCP-driven E2E is **exploratory**: an agent with visual access to the running app walks through every flow, compares actual behavior against the spec, and reports bugs it discovers. This catches categories of bugs that scripted tests miss:

- UI doesn't match spec (wrong text, missing elements, broken layout)
- Navigation flows don't work (buttons go to wrong screen, back doesn't work)
- State machines are broken (sign request stuck in pending, key not showing unlock state)
- Error paths not handled (invalid input shows blank screen instead of error)
- Cross-component integration failures (gRPC call succeeds but UI doesn't update)

## Task annotation

Tasks that should use the E2E explore-fix-verify loop MUST declare both capabilities:

```markdown
- [ ] T050 E2E integration test exploration [needs: mcp-android, e2e-loop]
```

The `e2e-loop` capability tells the runner to use the explore-fix-verify cycle instead of the normal implementation flow. The `mcp-android` (or `mcp-browser`, `mcp-ios`) capability tells the runner which platform runtime to boot and which MCP server to provide.

## The explore-research-fix-verify loop

```
┌─────────────────────────────────────────────────┐
│  Runner: boot runtime, build+install app        │
└──────────────────────┬──────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │  EXPLORE agent (MCP)    │
          │  - Walk every UI flow   │
          │  - Screenshot each      │
          │  - Compare vs spec      │
          │  - Report ALL bugs      │
          │  → findings.json        │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  RESEARCH agent(s)      │
          │  - 1 per new bug        │
          │  - Search web + code    │
          │  - Find working examples│
          │  - Recommend fix        │
          │  → bugs/BUG-XXX/        │
          │    research-N.md        │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  FIX agent (no MCP)     │
          │  - Read findings.json   │
          │  - Read research reports│
          │  - Follow guidance      │
          │  - Fix ALL bugs         │
          │  - Commit changes       │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  Runner: rebuild+install│
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  VERIFY agent (MCP)     │
          │  - Re-test each bug     │
          │  - Mark fixed/broken    │
          │  - Write structured     │
          │    evidence per bug     │
          │  - Find NEW bugs        │
          │  → updated findings +   │
          │    verify-evidence-N.md │
          └────────────┬────────────┘
                       │
              Loop until clean
                       │
         After 3 failed fixes ──────────┐
                                        │
          ┌─────────────────────────────▼┐
          │  BUG SUPERVISOR agent        │
          │  - Review fix history        │
          │  - Read supervisor summaries │
          │  - Decide: DIRECT_FIX /      │
          │    REDIRECT_RESEARCH /       │
          │    ESCALATE                  │
          │  → supervisor-N-summary.md   │
          │  → supervisor-N-decision.md  │
          └──────────────┬───────────────┘
                         │
          ┌──────────────▼───────────────┐
          │  1 more fix attempt          │
          │  (with supervisor guidance)  │
          └──────────────┬───────────────┘
                         │
         After 5 supervisors ───────────┐
                                        │
          ┌─────────────────────────────▼┐
          │  ESCALATION agent            │
          │  - Synthesize full history   │
          │  - Categorize: code/spec/    │
          │    infra                     │
          │  → BLOCKED.md               │
          └──────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │  REGRESSION agent       │
          │  - Run ALL test suites  │
          │  - Fix any regressions  │
          │  - Report results       │
          │  → regression-report.md │
          └─────────────────────────┘
```

### Per-bug file structure

Each bug gets its own directory for tracking research, fix history, supervisor
assessments, and verify evidence:

```
validate/e2e/bugs/BUG-008/
  research-1.md              # Initial research report
  research-2.md              # Redirected research (after supervisor)
  history.json               # Structured fix attempt log
  fix-approach-latest.md     # What the fix agent changed (overwritten each attempt)
  verify-evidence-1.md       # Structured evidence from verify iteration 1
  verify-evidence-2.md       # Evidence from iteration 2
  supervisor-1-summary.md    # Short summary for chain (< 15 lines)
  supervisor-1-decision.md   # Full decision (DIRECT_FIX/REDIRECT_RESEARCH/ESCALATE)
  supervisor-2-summary.md
  supervisor-2-decision.md
  BLOCKED.md                 # Only if escalated — synthesis for human
```

### Research agent

When the explore agent discovers new bugs, the runner spawns a **research agent per bug** before the fix agent runs. The research agent:

1. Searches the codebase for relevant source files
2. Reads the code to understand the current implementation
3. Searches the web for documentation, guides, and working examples
4. Finds similar patterns in the codebase that already work
5. Synthesizes a concrete fix strategy with specific API calls and code patterns
6. Writes its report to `bugs/BUG-XXX/research-N.md`

The fix agent receives the research report and is instructed to follow its recommendations.

When a supervisor issues REDIRECT_RESEARCH, a new research agent spawns with the
supervisor's directive, all previous supervisor summaries, and the fix attempt history.
This ensures the new research doesn't repeat dead-end investigations.

### Verify agent structured evidence

The verify agent now writes **structured evidence** per bug to `bugs/BUG-XXX/verify-evidence-N.md`. Each evidence file contains:

- **Actions taken**: exact MCP tool calls and parameters
- **Observed state**: raw DumpHierarchy XML snippet (not a summary)
- **Expected state**: what the XML should look like per spec
- **Delta**: concrete difference (e.g., "checkable=false, expected checkable=true")

This evidence is fed to the fix agent and supervisor in subsequent iterations.

### Bug supervisor

After 3 failed fix attempts for a specific bug, the runner spawns a **bug supervisor** instead of immediately retrying. The supervisor:

1. Reads all fix attempts, their approaches, and verify evidence
2. Reads all previous supervisor summaries (short chain, not full transcripts)
3. Reads the latest research report
4. Decides one of three actions:

| Decision | What happens |
|----------|-------------|
| **DIRECT_FIX** | Supervisor provides a concrete fix strategy. Fix agent gets 1 more attempt with this guidance. |
| **REDIRECT_RESEARCH** | Current research direction is wrong. New research agent spawns with supervisor's directive and new questions. |
| **ESCALATE** | Bug can't be fixed automatically. Synthesis agent produces BLOCKED.md. |

Each supervisor writes a **short summary** (< 15 lines) that future supervisors and research agents see. This prevents context bloat while preserving what was tried.

After each supervisor, the fix agent gets **1 attempt** (not 3). If that attempt fails, the next supervisor fires immediately.

Maximum 5 supervisor runs per bug before escalation to human.

### Escalation

When a bug exhausts all supervisor runs (or a supervisor explicitly escalates), a **synthesis agent** produces `bugs/BUG-XXX/BLOCKED.md` with:

- Full history synthesis (what was tried, why each approach failed)
- Category: **code** (implementation stuck), **spec** (platform can't satisfy requirement), or **infra** (tooling can't verify)
- Specific recommended human action
- Links to all evidence files in the bug directory

Escalated bugs are marked `wont_fix` in findings.json and excluded from further fix attempts. The E2E loop continues fixing other bugs.

### Fix attempt budget

Per bug: 3 initial attempts + up to 5 supervisor cycles with 1 attempt each = **8 max fix attempts** before human escalation.

### Post-loop regression check

After the explore-fix-verify loop finishes (all bugs fixed or supervisor stops), the runner spawns a **regression check agent** that runs the project's full test suite. E2E fixes often touch shared code (screens, view models, navigation) and can break existing unit tests, lint checks, or instrumented tests.

The regression agent:
1. Reads `CLAUDE.md` to find all test commands (make test, gradlew test, go test, lint, etc.)
2. Runs every test suite — not just the ones related to E2E changes
3. If a test fails due to an E2E fix: fixes the regression and commits
4. If a test failure is pre-existing: notes it but doesn't block
5. Writes results to `validate/e2e/regression-report.md`

The task is only marked done after the regression check completes.

### Regression test quality

When task descriptions say "write a regression test for each bug fixed," agents tend to produce **shallow render tests** — they mock the ViewModel with a pre-set state and assert that a specific string appears on screen. These tests verify that Compose can render text, not that the app behaves correctly. They are brittle (break on any string change) and miss the actual bugs they're supposed to guard against.

**Regression tests MUST be behavioral, not visual.** A behavioral test exercises a state transition, validates a data flow, or verifies an observable side effect. A render test just checks if text appears.

| Bad (render test) | Good (behavioral test) |
|---|---|
| Mock ViewModel with `showWarning=true`, assert "Security Warning" text displayed | Call `viewModel.setPolicy(AUTO_APPROVE)` → assert warning flag true + policy unchanged. Call `confirmAutoApprove()` → assert warning flag false + policy changed. |
| Mock state with `error="Invalid format"`, assert error text displayed | Call `isValidAuthKeyFormat("")` → false. Call `isValidAuthKeyFormat("tskey-auth-abc")` → true. |
| Mock ViewModel with `isUnlocked=true`, assert "Lock Key" button exists | Create real `KeyUnlockManager`, call `unlock(key)` → assert `isUnlocked(fingerprint)` true. Call `lock(fingerprint)` → assert false. |
| Pre-set clipboard content, assert text matches | Click "Copy" button on real screen, then read system clipboard and assert content matches public key string. |

**Rules for regression test task descriptions:**

1. **"Done when" must specify the state transition to test**, not the text to assert. "Done when: setting policy to AUTO_APPROVE triggers warning, dismissing preserves original policy, confirming changes policy" — not "Done when: dialog shows 'Security Warning' text."
2. **Prefer testing with real objects over mocks.** If `KeyUnlockManager` is a simple in-memory class, instantiate it. If `KeyManager` needs Android context, use `InstrumentationRegistry`. Only mock things that have complex external dependencies (network, biometrics).
3. **Test the ViewModel/Manager layer, not the Compose layer.** ViewModel state transitions are the behavioral contract. Compose rendering is a presentation detail that changes frequently.
4. **A render test is only justified for exact text that is a security/compliance contract** — e.g., the exact wording of a security warning that legal reviewed. Even then, pair it with a behavioral test of the underlying state machine.

### Explore agent

The explore agent has MCP tools and reads:
- `UI_FLOW.md` — the authoritative specification of screens, flows, and state machines
- `spec.md` — functional requirements
- Previous findings (if any) — to avoid re-reporting known bugs

It systematically walks every screen and flow, taking screenshots and reading view trees. It tests both happy paths and error paths. It writes ALL bugs to `validate/e2e/findings.json` with a `bug_dir` field pointing to the per-bug directory.

### Fix agent

The fix agent reads the findings and fixes ALL reported bugs in a single batch pass. It does NOT have MCP tools — it only needs source code access. This keeps token cost down by not loading MCP context for code-only work.

The fix agent now receives per-bug context:
- **Research reports** with recommended fix strategies
- **Supervisor guidance** (if the bug supervisor has run)
- **Fix attempt history** showing what was already tried and failed
- **Verify evidence** showing the exact observed vs expected state

After fixing each bug, the fix agent writes `bugs/BUG-XXX/fix-approach-latest.md` describing what it changed.

### Verify agent

The verify agent re-tests each bug from the findings. It has MCP tools and follows the same steps-to-reproduce for each bug. It updates statuses:
- `"new"` → `"fixed"` (bug is resolved)
- `"new"` → `"verified_broken"` (bug still exists after fix attempt)

It also discovers new bugs found during re-testing.

**Structured evidence**: The verify agent now writes detailed evidence to `bugs/BUG-XXX/verify-evidence-N.md` for every bug it checks. Evidence includes raw DumpHierarchy XML, exact assertions, and concrete deltas. This evidence is fed to fix agents and supervisors in subsequent iterations.

### Iteration-level supervisor agent

Every N iterations (default 10), an iteration-level supervisor agent reviews overall progress:
- Checks if bugs are being fixed (diminishing open count)
- Checks if coverage is improving (new screens/flows being tested)
- Detects stuck loops (same bugs repeatedly fixed then broken)
- Can redirect strategy ("focus on error paths in pairing flow")
- Can stop the loop ("human intervention needed" or "tests are comprehensive")

## Findings format

```json
{
  "version": 2,
  "iteration": 3,
  "findings": [
    {
      "id": "BUG-001",
      "severity": "critical",
      "screen": "TailscaleAuthScreen",
      "flow": "First Launch → Tailscale Auth",
      "summary": "Invalid auth key shows blank screen instead of error",
      "steps_to_reproduce": [
        "Launch app",
        "Enter 'tskey-invalid' in auth key field",
        "Tap Connect"
      ],
      "expected": "Error dialog: 'Invalid auth key format'",
      "actual": "Screen goes blank, no error shown",
      "screenshot_path": "validate/e2e/screenshots/BUG-001-blank.png",
      "bug_dir": "validate/e2e/bugs/BUG-001",
      "status": "new"
    }
  ]
}
```

### Status values

| Status | Meaning |
|--------|---------|
| `new` | Just discovered, not yet fixed |
| `fixed` | Verify agent confirmed the fix works |
| `verified_fixed` | Fix confirmed across multiple iterations |
| `verified_broken` | Fix attempt failed, bug still exists |
| `wont_fix` | Escalated to human or intentional behavior |

### Per-bug history.json format

```json
{
  "bug_id": "BUG-008",
  "fix_attempts": [
    {
      "attempt": 1,
      "approach": "Added Modifier.toggleable(role=Switch)...",
      "verify_status": "failed",
      "verify_evidence": "Switch node has checkable=false in hierarchy...",
      "timestamp": "2026-04-07T14:30:00"
    }
  ],
  "supervisor_runs": 2
}
```

## Context window management

### One screen per task = fresh context per screen

The most important context management strategy is structural: **each E2E task should cover exactly one screen** (see `phases/tasks.md`). Since each task gets its own explore agent, this means each agent starts with a fresh context window. Screenshots and tool calls from one screen don't accumulate into the next screen's session.

Only bundle two screens when they're tightly coupled (e.g., must create an item on ScreenA to view ScreenB).

### Sonnet for explore and verify agents

Explore and verify agents use Sonnet, not Opus. These agents do visual inspection — "look at screenshot, compare to spec, click things" — which doesn't require Opus-level reasoning. Sonnet is ~5x cheaper per token and handles this work well. Fix, research, and supervisor agents still use Opus for deeper reasoning.

### Rules the runner enforces via prompts

1. **Prefer Screenshot over DumpHierarchy** — screenshots are a single image token while XML hierarchy dumps consume 20-50k text tokens. Only use DumpHierarchy when you need exact resource IDs or accessibility attributes for selectors.
2. **Maximum 15 screenshots per explore session, 10 per verify session** — agents count and stop taking screenshots after the limit.
3. **Save screenshots to disk, don't re-read** — once captured to `validate/e2e/screenshots/`, reference by path in findings. Don't re-read images already analyzed.
4. **Write findings incrementally** — update `findings.json` after each screen/flow, not at the end. If the agent crashes, the next iteration picks up from partial findings.
5. **Write progress checkpoints** — after each screen/flow, append to `validate/e2e/progress.md`. The next iteration reads this and skips already-validated areas.
6. **Graceful exit on low context** — if 10+ screenshots taken or 100+ tool calls made, write current findings and progress, then stop.

### Token reporting

The runner reads cumulative token usage from the JSONL result entry (authoritative), not from individual assistant messages. Synthetic error messages (model `"<synthetic>"`) have zeroed-out usage and are ignored to prevent false "0k tok" reporting.

### Crash recovery

When an explore agent crashes (exit non-zero), the crash supervisor receives:
- stderr output (if any)
- The JSONL result entry (real error message, num_turns, duration, cost)
- Full loop state history

Context overflow crashes (image limits, token limits) are classified as **recoverable** — the supervisor says CONTINUE and the next iteration resumes from `progress.md`. Infrastructure crashes (MCP server down, auth failure) are classified as **STOP — human intervention needed**.

## Skip rebuild when no changes

After the fix agent completes, the runner checks `git diff --stat HEAD` and compares HEAD against the pre-fix commit. If the fix agent made no code changes (already fixed in a prior iteration, or couldn't fix), the runner skips the rebuild and verify phases entirely, logging "Fix agent made no code changes — skipping rebuild and verify." This prevents wasted iterations where the fix agent discovers everything was already fixed.

## Backend service connection info

When `test/e2e/setup.sh` starts backend services, it writes two files under `test/e2e/.state/`:

1. **`env`** — flat key=value for human/tool inspection:

```bash
HEADSCALE_PORT=18080
HOST_AUTH_KEY=tskey-preauth-...
HOST_TAILSCALE_IP=100.64.0.1
DATABASE_URL=postgresql://...
SUPERTOKENS_URL=http://127.0.0.1:3567
API_URL=http://127.0.0.1:3000
```

2. **`env.sh`** — sourceable shell snippet with `export` statements. **MANDATORY** for any project whose integration tests read service connection info from environment variables. The runner's pre-E2E integration test gate and phase-validation runner-verify step both wrap the test command in `bash -c 'set -a; source env.sh; set +a; <cmd>'` so the subprocess inherits the service env. Without `env.sh`, tests that require `DATABASE_URL` / `SUPERTOKENS_CONNECTION_URI` / similar fail because the runner's own environment doesn't have them — setup.sh exports into its own shell, which exits before the test subprocess runs.

Shape:

```bash
# Source this file to get the env the services are running with.
# Generated by test/e2e/setup.sh — do not edit by hand.
export DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/app"
export SUPERTOKENS_CONNECTION_URI="http://127.0.0.1:3567"
export SUPERTOKENS_API_KEY="e2e-test-key"
export API_BASE_URL="http://127.0.0.1:3000"
# ... every var the tests require ...
```

Write both files at the end of setup.sh — not only `env`. The runner reads `env.sh` automatically; you don't need to reference it in your tests or CI manually.

The runner reads `env` for agent prompt injection (so the agent knows how to connect to backend services). The explore agent can use this info to:
- Inject the phone auth key into the app (via deep link or adb instrumentation)
- Verify the host daemon is reachable at the Tailscale IP
- Test sign requests through the real infrastructure

## Platform runtimes

The runner has built-in knowledge of three platform runtimes:

| Platform | Capability | Boot | Build+Install | MCP Server |
|----------|-----------|------|---------------|------------|
| Android | `mcp-android` | Emulator via `start-emulator` or `emulator @avd` | `gradlew assembleDebug` + `adb install` | `nix-mcp-debugkit#mcp-android` |
| Browser | `mcp-browser` | Bundled with MCP server | N/A | `nix-mcp-debugkit#mcp-browser` |
| iOS | `mcp-ios` | `xcrun simctl boot` | `xcodebuild build` + `simctl install` | `nix-mcp-debugkit#mcp-ios` |

## Nix-first projects: pin MCP servers in flake.nix

If the project uses Nix (`flake.nix` exists), `nix-mcp-debugkit` MUST be added as a flake input rather than referenced via unpinned `github:` URIs. This follows the nix-first principle: all dependencies are version-pinned in `flake.lock`.

```nix
# flake.nix
{
  inputs.nix-mcp-debugkit.url = "github:mmmaxwwwell/nix-mcp-debugkit";

  outputs = { self, nixpkgs, nix-mcp-debugkit, ... }:
    # Expose MCP servers as packages so the runner can use .#mcp-android etc.
    packages.x86_64-linux = {
      mcp-android = nix-mcp-debugkit.packages.x86_64-linux.mcp-android;
      mcp-browser = nix-mcp-debugkit.packages.x86_64-linux.mcp-browser;
      mcp-ios = nix-mcp-debugkit.packages.x86_64-linux.mcp-ios;
    };
}
```

The parallel runner automatically detects the flake input: if `"nix-mcp-debugkit"` appears in `flake.nix`, it uses `nix run .#mcp-<platform>` (pinned) instead of `nix run github:mmmaxwwwell/nix-mcp-debugkit#mcp-<platform>` (unpinned). No config changes needed — just add the input.

**Why this matters**: Without pinning, every `nix run github:...` fetches whatever `main` currently points to. A breaking change upstream silently breaks your E2E tests. With a flake input, you control when to update via `nix flake update nix-mcp-debugkit`.

## MCP tools available to agents

When an agent has MCP tools, it can:

| Tool | Purpose |
|------|---------|
| `Screenshot` / `Snapshot` | Capture the current screen as PNG |
| `DumpHierarchy` | Read the accessibility/view tree (find selectors) |
| `Click` / `ClickBySelector` | Tap UI elements |
| `LongClick` | Long press |
| `Swipe` | Scroll, swipe gestures |
| `Type` / `SetText` | Enter text |
| `Press` | Hardware buttons (BACK, HOME) |
| `WaitForElement` | Poll for element appearance |
| `GetScreenInfo` | Screen dimensions |

## Integration with spec-kit workflow

E2E loop tasks are typically placed in later phases (after core implementation is done).

### CRITICAL: Split tasks by screen, not by "all screens"

Each E2E task should cover **1-2 screens**, not all screens at once. This keeps
explore cycles short (~5-7 minutes instead of 20-25), gets the research→fix→verify
loop running faster, and prevents one hard bug from blocking progress on other screens.

**Bad** — one monolithic task:
```markdown
- [ ] T045 Validate all screens [needs: mcp-android, e2e-loop]
```

**Good** — one task per screen or per 2 related screens:
```markdown
## Phase 10: Screen Validation

- [ ] T045 Validate TailscaleAuth + ServerList screens [needs: mcp-android, e2e-loop]
  Done when: both screens validated against UI_FLOW.md, findings.json has pass/fail.

- [ ] T046 Validate Settings screen [needs: mcp-android, e2e-loop]
  Done when: all sections (Security, Tailscale, Tracing, About) validated,
  toggle defaults and dropdown labels match spec.

- [ ] T047 Validate Pairing screen [needs: mcp-android, e2e-loop]
  Done when: pairing phases verified (scan, connect, success, error),
  deep link and QR paths tested.

- [ ] T048 Validate KeyManagement + KeyDetail screens [needs: mcp-android, e2e-loop]
  Done when: key CRUD verified, policy dropdowns, unlock state, delete confirmation.

- [ ] T049 Validate navigation flows [needs: mcp-android, e2e-loop]
  Done when: every navigation edge from UI_FLOW.md flowchart exercised.
```

Each task gets its own E2E loop with independent findings, research, and fix cycles.
If Settings has 4 hard accessibility bugs, it doesn't block Pairing from being validated and fixed.

The phase depends on all implementation phases being complete. The runner handles the entire lifecycle — no manual intervention needed unless the supervisor requests it.

## Writing UI_FLOW.md for MCP-driven testing

The `UI_FLOW.md` is the explore agent's primary guide. For MCP-driven testing to work well, it should include:

1. **Screen inventory** — every screen with its route/name
2. **Navigation flows** — how to get from screen A to screen B
3. **State machines** — valid state transitions for domain objects
4. **Field validations** — what inputs are valid/invalid per field
5. **Error states** — what error messages should appear and when
6. **Conditional UI** — elements that appear/disappear based on state

The more detailed the UI_FLOW.md, the more bugs the explore agent can find.
