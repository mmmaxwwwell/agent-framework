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

## The explore-fix-verify loop

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
          │  FIX agent (no MCP)     │
          │  - Read findings.json   │
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
          │  - Find NEW bugs        │
          │  → updated findings     │
          └────────────┬────────────┘
                       │
                  Loop until clean
                       │
          ┌────────────▼────────────┐
          │  REGRESSION agent       │
          │  - Run ALL test suites  │
          │  - Fix any regressions  │
          │  - Report results       │
          │  → regression-report.md │
          └─────────────────────────┘
```

### Post-loop regression check

After the explore-fix-verify loop finishes (all bugs fixed or supervisor stops), the runner spawns a **regression check agent** that runs the project's full test suite. E2E fixes often touch shared code (screens, view models, navigation) and can break existing unit tests, lint checks, or instrumented tests.

The regression agent:
1. Reads `CLAUDE.md` to find all test commands (make test, gradlew test, go test, lint, etc.)
2. Runs every test suite — not just the ones related to E2E changes
3. If a test fails due to an E2E fix: fixes the regression and commits
4. If a test failure is pre-existing: notes it but doesn't block
5. Writes results to `validate/e2e/regression-report.md`

The task is only marked done after the regression check completes.

### Explore agent

The explore agent has MCP tools and reads:
- `UI_FLOW.md` — the authoritative specification of screens, flows, and state machines
- `spec.md` — functional requirements
- Previous findings (if any) — to avoid re-reporting known bugs

It systematically walks every screen and flow, taking screenshots and reading view trees. It tests both happy paths and error paths. It writes ALL bugs to `validate/e2e/findings.json`.

### Fix agent

The fix agent reads the findings and fixes ALL reported bugs in a single batch pass. It does NOT have MCP tools — it only needs source code access. This keeps token cost down by not loading MCP context for code-only work.

### Verify agent

The verify agent re-tests each bug from the findings. It has MCP tools and follows the same steps-to-reproduce for each bug. It updates statuses:
- `"new"` → `"fixed"` (bug is resolved)
- `"new"` → `"verified_broken"` (bug still exists after fix attempt)

It also discovers new bugs found during re-testing.

### Supervisor agent

Every N iterations (default 10), a supervisor agent reviews progress:
- Checks if bugs are being fixed (diminishing open count)
- Checks if coverage is improving (new screens/flows being tested)
- Detects stuck loops (same bugs repeatedly fixed then broken)
- Can redirect strategy ("focus on error paths in pairing flow")
- Can stop the loop ("human intervention needed" or "tests are comprehensive")

## Findings format

```json
{
  "version": 1,
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
| `verified_broken` | Fix attempt failed, bug still exists |
| `wont_fix` | Intentional behavior or out of scope |

## Context window management

MCP explore and verify agents accumulate screenshots and view hierarchy dumps in their conversation context. Without management, the agent will hit the Claude API's multi-image dimension limit and crash mid-session with:

> "An image in the conversation exceeds the dimension limit for many-image requests (2000px)"

### Rules the runner enforces via prompts

1. **Prefer DumpHierarchy/Snapshot over Screenshot** — text-based view trees use ~100x less context than images. Only screenshot when visual verification is needed (colors, layout, styling).
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

When `test/e2e/setup.sh` starts backend services, it writes connection info to `test/e2e/.state/env` as shell-style key=value pairs:

```bash
HEADSCALE_PORT=18080
HOST_AUTH_KEY=tskey-preauth-...
PHONE_AUTH_KEY=tskey-preauth-...
HOST_TAILSCALE_IP=100.64.0.1
SSH_AUTH_SOCK=/tmp/.../agent.sock
CONTROL_SOCKET=/tmp/.../control.sock
```

The runner reads this file and includes it in the explore agent's prompt so the agent knows how to connect to backend services. The explore agent can use this info to:
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

E2E loop tasks are typically placed in later phases (after core implementation is done):

```markdown
## Phase 10: E2E Integration Testing

- [ ] T045 E2E integration test exploration [needs: mcp-android, e2e-loop]
  Done when: all screens and flows from UI_FLOW.md have been visually verified,
  all discovered bugs are fixed, findings.json shows zero open bugs.
```

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
