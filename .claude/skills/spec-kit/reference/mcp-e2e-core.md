# MCP-driven E2E — core (platform-neutral)

When to read: you are driving the E2E explore-research-fix-verify loop
for any platform. For platform-specific tool names, cost rules, and
boot steps, also read the matching companion file:

- `mcp-e2e-web.md` for `mcp-browser`
- `mcp-e2e-android.md` for `mcp-android`
- `mcp-e2e-ios.md` for `mcp-ios`

The runner injects this file PLUS the matching platform file into E2E
sub-agents; other platforms are not in your context.

## Agents use MCP tools directly — never write scripts

The most common failure mode in MCP E2E tasks is **meta-framework
generation**: the task tells the agent to write a shell script or a
prompt template that would invoke a future agent to do the real work.
This is always wrong.

Tasks annotated with `[needs: mcp-<platform>, e2e-loop]` get MCP tools
injected by the runner. The implementing agent **directly uses** those
tools to interact with the live app. If a task description says
"create a script that…" or "write a prompt template for…" for E2E
testing, treat it as a spec bug and fix the description first.

The runner owns: runtime boot → app build+install → MCP server config →
agent gets MCP tools → findings.json → fix agent → rebuild → verify
agent. You do not write any of that plumbing.

## Task annotation

```markdown
- [ ] T050 E2E integration test [needs: mcp-android, e2e-loop]
- [ ] T051 E2E integration test [needs: mcp-browser, e2e-loop]
```

`e2e-loop` → use the explore-fix-verify cycle. `mcp-<platform>` → which
runtime to boot and which MCP server to provide.

## The explore-research-fix-verify loop

```
explore (MCP) → findings.json
              ↓
research (1/bug) → bugs/BUG-XXX/research-N.md
              ↓
fix (no MCP) → code changes + bugs/BUG-XXX/fix-approach-latest.md
              ↓
rebuild + reinstall
              ↓
verify (MCP or verify.sh) → updated findings + verify-evidence-N.md
              ↓
Loop until clean. After 3 failed fixes per bug → supervisor.
After 5 supervisors → synthesis → BLOCKED.md.
Finally → regression check (run all test suites).
```

### Scripted verify first (new)

When a fix agent closes a bug, it **must** also write
`specs/<feature>/validate/e2e/bugs/<BUG-ID>/verify.sh`. The runner
executes this script before deciding whether to spawn a verify agent.
See `cost-guardrails.md` § "Scripted verify first" for the contract.

If the script passes, the bug is closed without an agent spawn. If it
fails, the finding is marked `verified_broken` and the loop continues.
Only inconclusive / missing scripts fall through to a verify agent.

### Per-bug file structure

```
specs/<feature>/validate/e2e/bugs/BUG-008/
  research-1.md              # Initial research report
  research-2.md              # Redirected research (after supervisor)
  history.json               # Structured fix attempt log
  fix-approach-latest.md     # What the fix agent changed (overwritten)
  verify.sh                  # Scripted verify (REQUIRED when closing a bug)
  verify-evidence-1.md       # Evidence from verify iteration 1
  verify-evidence-2.md       # Evidence from iteration 2
  supervisor-1-summary.md    # Short summary for chain (< 15 lines)
  supervisor-1-decision.md   # DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE
  BLOCKED.md                 # Only if escalated — synthesis for human
```

### Research agent

Spawned once per new bug before fix. Searches codebase and web,
produces `bugs/BUG-XXX/research-N.md`. On supervisor REDIRECT_RESEARCH
a new research agent spawns with the directive and prior summaries so
it doesn't repeat dead ends.

### Verify agent structured evidence

Each bug gets `bugs/BUG-XXX/verify-evidence-N.md` with:

- **Actions taken** — exact MCP tool calls and parameters
- **Observed state** — raw state snippet (platform-specific form)
- **Expected state** — what it should look like per spec
- **Delta** — concrete difference

Fed to the next fix agent and the supervisor.

### Bug supervisor and escalation

After 3 failed fix attempts for a bug, a **bug supervisor** is
spawned instead of another immediate retry. It reads fix history,
prior supervisor summaries (< 15 lines each), and the latest research
report. Decisions:

| Decision | What happens |
|---|---|
| `DIRECT_FIX` | Supervisor provides a concrete strategy. Fix agent gets 1 more attempt. |
| `REDIRECT_RESEARCH` | Current research direction is wrong. New research agent spawns with directive. |
| `ESCALATE` | Synthesis agent produces `BLOCKED.md`; bug marked `wont_fix`. |

Max 5 supervisor runs per bug. Budget per bug: 3 initial + 5 × 1 = 8
attempts before human escalation.

### Post-loop regression check

After the loop finishes, the runner spawns a regression agent that runs
the project's full test suite. E2E fixes often touch shared code and
can break existing unit tests. The regression agent reads `CLAUDE.md`
for test commands, runs every suite, fixes regressions caused by E2E
fixes, and writes `validate/e2e/regression-report.md`. Task is only
marked done after regression completes.

### Regression test quality (agents tend to get this wrong)

When writing regression tests, agents tend to produce **shallow render
tests**: mock the ViewModel with a pre-set state and assert a specific
string appears. These verify that the rendering engine can render text,
not that the app behaves correctly. They are brittle and miss the bugs
they're supposed to guard against.

**Regression tests MUST be behavioral, not visual.** A behavioral test
exercises a state transition, validates a data flow, or verifies an
observable side effect.

| Bad (render test) | Good (behavioral test) |
|---|---|
| Mock `showWarning=true`, assert "Security Warning" text | Call `setPolicy(AUTO_APPROVE)` → assert warning flag true + policy unchanged. Call `confirmAutoApprove()` → assert flag false + policy changed. |
| Mock `error="Invalid"`, assert error text | Call `isValidAuthKeyFormat("")` → false. Call `isValidAuthKeyFormat("tskey-auth-abc")` → true. |
| Pre-set clipboard, assert text | Click "Copy" button on real screen, then read clipboard and assert content. |

Rules for regression task descriptions:

1. "Done when" specifies the state transition, not text to assert.
2. Prefer testing with real objects over mocks. Only mock complex
   external dependencies (network, biometrics).
3. Test the ViewModel/Manager layer, not the presentation layer.
4. A render test is only justified for exact text that is a
   security/compliance contract.

## Findings format

```json
{
  "version": 2,
  "iteration": 3,
  "findings": [
    {
      "id": "BUG-001",
      "severity": "critical",
      "screen": "CheckoutScreen",
      "flow": "Guest Checkout",
      "summary": "POST /api/checkout returns 500 on valid address",
      "steps_to_reproduce": ["Add product to cart", "Navigate to /checkout", "Fill shipping", "Click 'Continue to Payment'"],
      "expected": "Stripe payment element appears; order summary shows shipping + tax",
      "actual": "Page shows 'API error: 500'",
      "screenshot_path": "validate/e2e/screenshots/BUG-001.png",
      "bug_dir": "validate/e2e/bugs/BUG-001",
      "status": "new"
    }
  ]
}
```

### Status values

| Status | Meaning |
|---|---|
| `new` | Just discovered, not yet fixed |
| `fixed` | Verify confirmed the fix works (agent or script) |
| `verified_fixed` | Fix confirmed across multiple iterations |
| `verified_broken` | Fix attempt failed, bug still exists |
| `wont_fix` | Escalated or intentional behavior |

### Per-bug `history.json`

```json
{
  "bug_id": "BUG-008",
  "fix_attempts": [
    {"attempt": 1, "approach": "...", "verify_status": "failed", "verify_evidence": "...", "timestamp": "..."}
  ],
  "supervisor_runs": 2
}
```

## Context window management

### One screen/flow per task → fresh context per task

Each E2E task should cover exactly one screen or one narrow flow. Each
task gets its own explore agent, so each starts with a fresh context
window. Screenshots and tool calls from one screen don't accumulate
into the next task's session. Only bundle two screens when they're
tightly coupled (must create on ScreenA to view ScreenB).

### Role-appropriate models

See `cost-guardrails.md` § "Role → model mapping". Executor and verify
run on Sonnet; planner and diagnostic run on Opus; fix runs on Sonnet
after the T096 cost review.

### Bounded executor spawns

Each executor spawn is capped at **4 plan steps** OR **10 minutes of
wall time**. On cap hit, write `handoff-spawn-N.md` and exit. The
runner spawns the next executor with that handoff as input. A fresh
spawn drops the sticky tool-result context that dominates per-turn
cost after 4–5 steps. See `cost-guardrails.md` § "Executor step cap".

### Runner-enforced context rules

1. Save screenshots to disk, don't re-read captured images.
2. Write findings incrementally — update `findings.json` after each
   screen/flow, not at the end. If the agent crashes, the next
   iteration picks up from partial findings.
3. Write progress checkpoints — append to `validate/e2e/progress.md`
   after each flow. The next iteration reads this and skips already-
   validated areas.
4. Graceful exit on low context — write findings and progress, then
   stop.

## State-verification shortcut (curl to admin API is ALLOWED)

The "no curl" rule in E2E prompts is narrow: no curl as a
**substitute for UI navigation**. After the UI flow completes, prefer
asserting backend state via the admin API rather than re-driving the
UI (which would double the token cost).

```bash
# Admin creds and API URL are written to test/e2e/.state/env by setup.sh.
source test/e2e/.state/env

# Example: after a checkout flow, verify the order was created with
# correct totals + snapshot fields — one cheap curl instead of a second
# navigate into the admin UI.
curl -s "$API_URL/api/admin/orders/$ORDER_ID" \
  -H "cookie: $ADMIN_COOKIE" -H "authorization: Bearer $ADMIN_TOKEN" | jq .
```

Rules:

- Use it for **state assertions**, not to drive user actions.
- Endpoints must be ones the admin UI uses; don't scrape or invent.
- If the endpoint you need doesn't exist, file a finding.

## Crash recovery

When an explore agent crashes (exit non-zero), the crash supervisor
sees stderr, the JSONL result entry, and full loop state. Context
overflows (image limits, token limits) are classified as **recoverable**:
the supervisor says CONTINUE and the next iteration resumes from
`progress.md`. Infrastructure crashes (MCP server down, auth failure)
are classified as **STOP — human intervention needed**.

## Skip rebuild when no changes

After the fix agent completes, the runner checks `git diff --stat HEAD`
against the pre-fix commit. If the fix agent made no code changes
(already fixed in a prior iteration or couldn't fix), the runner skips
rebuild and verify phases: "Fix agent made no code changes — skipping
rebuild and verify."

## Regression fast-path (per platform)

When an explore agent's happy path validates cleanly, it MUST emit a
platform-native regression test. On subsequent runs the runner executes
that test **before** spawning any MCP agent — if the regression passes,
the MCP explore loop is skipped entirely.

| Platform | Spec path | Runner command |
|---|---|---|
| Web (`mcp-browser`) | `site/tests/e2e/<TASK_ID>.spec.ts` | `npx playwright test <file> --reporter=line` (inside `site/`) |
| Android (`mcp-android`) | `<flutter-app>/integration_test/<TASK_ID>_test.dart` or `app/src/androidTest/java/<TASK_ID>Test.kt` | `patrol test --target <file>` or `flutter test <file>` or `./gradlew connectedDebugAndroidTest` |
| iOS (`mcp-ios`) | — | Deferred — every iOS task falls through to the MCP loop |

Signature: the file's first line MUST be `// regression for <TASK_ID>`
(or `# regression for <TASK_ID>` in Kotlin). Without the signature the
runner treats the file as unrelated and falls through.

If you cannot produce a regression (the flow requires manual
intervention), file a `REGRESSION-NEEDED` finding instead of emitting
a placeholder — the runner treats a missing regression as a bug on the
next pass.

## Backend service connection info

`test/e2e/setup.sh` writes two files under `test/e2e/.state/`:

1. **`env`** — flat `KEY=value` for human/tool inspection:
   ```
   DATABASE_URL=postgresql://...
   SUPERTOKENS_URL=http://127.0.0.1:3567
   API_URL=http://127.0.0.1:3000
   ```

2. **`env.sh`** — sourceable shell snippet with `export` statements.
   **MANDATORY** for any project whose integration tests read service
   connection info from env vars. The runner's pre-E2E integration
   gate and phase-validation runner-verify step wrap the test command
   in `bash -c 'set -a; source env.sh; set +a; <cmd>'` so the
   subprocess inherits the service env.

Shape:

```bash
# Generated by test/e2e/setup.sh — do not edit.
export DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/app"
export SUPERTOKENS_CONNECTION_URI="http://127.0.0.1:3567"
export SUPERTOKENS_API_KEY="e2e-test-key"
export API_BASE_URL="http://127.0.0.1:3000"
```

Write both. The runner reads `env.sh` automatically; tests don't need
to reference it manually. Third-party keys (Stripe, EasyPost, etc.)
should be sourced from the project `.env` at the top of setup.sh so
the placeholder fallbacks only kick in when the real key is absent —
otherwise the API boots with a placeholder that looks enough like a
real key to bypass stub-routing guards and make live API calls.

## Nix-first projects: pin MCP servers in `flake.nix`

If the project uses Nix, `nix-mcp-debugkit` MUST be added as a flake
input, not referenced via unpinned `github:` URIs:

```nix
# flake.nix
{
  inputs.nix-mcp-debugkit.url = "github:mmmaxwwwell/nix-mcp-debugkit";
  outputs = { self, nixpkgs, nix-mcp-debugkit, ... }:
    packages.x86_64-linux = {
      mcp-android = nix-mcp-debugkit.packages.x86_64-linux.mcp-android;
      mcp-browser = nix-mcp-debugkit.packages.x86_64-linux.mcp-browser;
      mcp-ios = nix-mcp-debugkit.packages.x86_64-linux.mcp-ios;
    };
}
```

The runner detects the flake input: if `"nix-mcp-debugkit"` appears
in `flake.nix`, it uses `nix run .#mcp-<platform>` (pinned) instead of
unpinned `github:` URIs. You control updates via
`nix flake update nix-mcp-debugkit`.

## Nix-first projects: JS/Native version skew (Playwright et al.)

Tools that ship a JS/TS package alongside a downloaded native binary
(Playwright, Puppeteer, Cypress, Bun's prebuilt deps, Tauri's webview)
are a recurring NixOS landmine. The JS package on npm declares it wants
a specific binary build (e.g. `@playwright/test@1.59.1` ↔ chromium
build 1217). The downloaded binary expects glibc-style shared library
paths that don't exist on NixOS, exiting with errors like:

```
chrome-headless-shell: error while loading shared libraries:
libglib-2.0.so.0: cannot open shared object file
```

NixOS's solution is `playwright-driver.browsers` (and equivalents): a
Nix-packaged binary with correct RPATHs. **The version of the JS
package must match what the Nix package ships.** When they skew,
Playwright refuses to launch the Nix-packaged binary because the
build number doesn't match what the JS-side expected.

Required setup:

1. **Pin the JS dep to the Nix-supplied version.** In `package.json`:
   ```json
   "devDependencies": {
     "@playwright/test": "1.58.2"  // exact, not ^1.58.2
   }
   ```
   Look up the current version with
   `nix eval --raw nixpkgs#playwright-driver.version`.

2. **Add the Nix browser package + env vars to the project's root flake**
   (NOT a sub-flake — `inputsFrom` does not propagate `mkShell` env
   vars, so site-level / app-level flakes can't set them):
   ```nix
   devShells.default = pkgs.mkShell {
     packages = with pkgs; [ ... playwright-driver.browsers ];
     PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
     PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
   };
   ```

3. **Bumping the JS dep requires bumping nixpkgs in lockstep.** When
   `npm update` raises `@playwright/test`, also `nix flake update
   nixpkgs` and confirm `playwright-driver.version` matches. If
   nixpkgs hasn't caught up yet, **stay on the old JS version** —
   running an unpinned playwright-installed binary on NixOS will
   fail at launch with library errors.

The same pattern applies to any tool with auto-downloaded native deps.
If you see a `cannot open shared object file` error during E2E,
suspect a version-skew between an npm-managed JS dep and a Nix-managed
native binary.

## MCP server env defaults (cost-shaping)

`PlatformRuntime.get_mcp_config` injects these env vars into MCP
server subprocesses:

| Var | Meaning |
|---|---|
| `MCP_PREFER_SNAPSHOT=1` | When a tool can return snapshot or screenshot, prefer snapshot |
| `MCP_BROWSER_NO_AUTO_SCREENSHOT=1` | Do NOT auto-attach a screenshot to every navigate/click response |
| `MCP_ANDROID_DEFAULT_NO_VISION=1` | `State-Tool` defaults to `use_vision:false` |

MCP server versions that recognize the flags default to the cheap
path. Prompt-side cost rules are the load-bearing enforcement; env
flags are belt-and-suspenders.

## Task splitting: one screen/flow per task

Each E2E task should cover **1-2 screens** or one narrow flow, not all
screens at once. This keeps explore cycles short, gets the
research→fix→verify loop running faster, and prevents one hard bug
from blocking unrelated screens.

**Bad** — monolithic task:

```markdown
- [ ] T045 Validate all screens [needs: mcp-android, e2e-loop]
```

**Good** — one task per screen:

```markdown
- [ ] T045 Validate TailscaleAuth + ServerList screens [needs: mcp-android, e2e-loop]
  Done when: both screens validated against UI_FLOW.md.
- [ ] T046 Validate Settings screen [needs: mcp-android, e2e-loop]
  Done when: all sections validated, toggle defaults and dropdowns match spec.
- [ ] T047 Validate Pairing screen [needs: mcp-android, e2e-loop]
  Done when: pairing phases verified, deep link and QR paths tested.
```

Each task gets independent findings, research, and fix cycles. If
Settings has 4 hard accessibility bugs, it doesn't block Pairing.

## Writing `UI_FLOW.md` for MCP-driven testing

`UI_FLOW.md` is the explore agent's primary guide. Include:

1. **Screen inventory** — every screen with its route/name
2. **Navigation flows** — how to get from A to B
3. **State machines** — valid transitions for domain objects
4. **Field validations** — valid/invalid inputs per field
5. **Error states** — what error messages appear and when
6. **Conditional UI** — elements that appear/disappear based on state

The more detailed `UI_FLOW.md` is, the more bugs the explore agent
can find without needing a separate codebase exploration pass.
