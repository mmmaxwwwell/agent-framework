# Cost guardrails

When to read: you are modifying `parallel_runner.py`, a role prompt, or an
E2E convention and need to know **why** a given budget, model, or exclude
rule exists before you change it.

This file captures the runner-side cost discipline that was established
after a single T096 E2E cycle on Kanix cost ~$30. Every rule below maps
to a specific driver from that post-mortem. Do not relax a rule without
naming the driver you believe it no longer applies to.

## Origin: the $30 T096 post-mortem

One E2E iteration on a guest-checkout task cost ~$27–33. Breakdown:

| Driver | Approx cost | % |
|---|---:|---:|
| 2 oversize browser MCP responses (~329 KB each) → sticky cache-read | ~$10 | 35% |
| Verify agent doing log forensics through 142 Bash calls over 316 turns | ~$12 | 35% |
| Opus on mechanical roles (fix agent for a 1-line package.json edit: $5.78) | ~$4 | 15% |
| Hang-kill of a fix agent → full planner+executor redo | ~$7.50 | 25% |
| Misleading code-review-graph results → agents bypassed the tool | ~$2 | indirect |

The rules below are the countermeasures. Ship them together; they
compound.

## Role → model mapping

Mechanical roles run on sonnet; reasoning-heavy roles run on opus.

| Role | Model | Why |
|---|---|---|
| planner | `opus` | Reasons over a spec + code to produce a plan. Reasoning-heavy. |
| executor | `sonnet` | Drives tools, files bugs. Tool-heavy, mechanical. |
| fix | `sonnet` | Applies a diagnosed diff. Was `opus`; downgraded — a 1-line package.json edit on opus cost $5.78, same work on sonnet is ~$1.15. |
| verify | `sonnet` | Re-runs a check, parses output, writes evidence. Mechanical. |
| diagnostic / supervisor / research | `opus` | Called rarely; need reasoning. |
| crash-fix / build-fix | `sonnet` | Previously opus. Same rationale as fix. |

**Override per project**: `.specify/cost-config.json` at the project root
can override any of these. See schema in the [.specify override] section.

## Hang budgets (idle timeout) per role

Tight budgets catch real hangs fast without killing legitimately slow
build/install work.

| Role | Idle timeout | Why |
|---|---:|---|
| planner | 8 min | Reading + writing. Anything longer is a hang. |
| executor | 8 min | Per-spawn cap is 10 min wall; idle ≥8 min means stuck. |
| fix | 12 min | May run a short build to validate. |
| verify | 8 min | Read logs + curl. Should be fast. |
| build-fix / crash-fix | 20 min | Legitimately long — full `pnpm build` / `flutter build`. |

**Work preservation on hang-kill**: if an executor is killed, the runner
synthesizes `handoff-spawn-N.md` with `Status: PARTIAL` and proceeds.
If a planner is killed and `plan.md` already has content, the runner
proceeds to executor instead of re-spawning a planner.

Global hard timeout stays at 120 min as a last-resort backstop.

## Executor step cap

One executor spawn handles at most **4 plan steps** OR **10 minutes of
wall time**, whichever comes first. On cap hit, the executor writes
`handoff-spawn-N.md` and exits. The runner spawns the next executor
with that handoff as input.

- `EXECUTOR_STEP_CAP_PER_SPAWN = 4`
- `EXECUTOR_WALL_CAP_S = 600`
- `EXECUTOR_MAX_SPAWNS_PER_ITER = 5` (unchanged; per-iteration ceiling)

**Why**: a single long-running executor accumulates tool-result history
that gets re-cached on every turn. A fresh spawn drops that context at
the cost of one cache prime — net big win past ~4 steps.

Cap-hit signal: the runner writes `<exec_dir>/cap-hit.flag` when wall
cap is approaching. The executor polls this file and exits on first
sight. See § Handoff contract below.

## Scripted verify first

When a fix agent closes a bug, it **must** also write
`specs/<feature>/validate/e2e/bugs/<BUG-ID>/verify.sh`. The runner
executes this script before considering spawning a verify agent.

**Contract**:

- Runner invokes: `bash verify.sh` with cwd = project root.
- Runner sources `test/e2e/.state/env` before invoking.
- Runner enforces a 30 s timeout.

**Exit codes**:

| Code | Meaning | Runner action |
|---|---|---|
| `0` | Verified fixed | Finding → `fixed`; runner writes evidence from stdout |
| `1` | Verified still broken | Finding → `verified_broken`; runner writes evidence |
| `2` | Inconclusive | Fall through to verify-agent spawn |
| other / timeout | Treated as inconclusive | Fall through to verify-agent spawn |

**Stdout format** (first 3 lines parsed by the runner):

```
STATUS: FIXED | STILL_BROKEN
EVIDENCE: <one-line concrete delta — e.g. "POST /api/checkout returned 200 with order_id=ord_xxx">
COMMAND: <command used>
```

Everything after line 3 is captured verbatim in the evidence file.

**Why**: agent 393 spent ~$12 and 316 assistant turns to ultimately
reproduce one `curl` call. A scripted check is ~$0 and takes 1 second.

## Handoff contract — `handoff-spawn-N.md`

Written by the executor at cap-hit, on blocker detection, or on
completion. Required sections (headings are parsed by the runner):

```
# Executor handoff (spawn N)
## Status: COMPLETE | PARTIAL
## Cap reason: step-cap | wall-cap | self-elected | blocker
## Steps completed this spawn
- step-K: <result>
## Next step to resume at: step-M         (omit if COMPLETE)
## State left behind                      (omit if COMPLETE)
<free text: URL, cookies, cart token, screenshot paths>
## Findings written
- <BUG-ID> or "none"
## Infrastructure blockers                (optional)
<if present, runner fast-paths to fix agent; skips remaining executor spawns>
```

## Browser MCP: `browser_evaluate` before `browser_snapshot`

Default page-understanding tool is a targeted `browser_evaluate` that
returns ~500 bytes of structured JSON. Use `browser_snapshot` only for
first-visit mapping of an unknown page.

| Goal | Tool |
|---|---|
| Read 1-5 specific fields/values | `browser_evaluate` |
| Locate a known selector by name/role | `browser_evaluate` |
| First visit to an unfamiliar page | `browser_snapshot` (one shot) |
| Visual evidence for a bug report | `browser_take_screenshot` |

**Canonical example** (inject into executor/verify prompts):

```js
await browser_evaluate({
  expression: `({
    heading: document.querySelector('h1')?.innerText,
    formFields: [...document.querySelectorAll('input,select,textarea')].map(e => ({
      name: e.name, type: e.type, required: e.required,
      value: e.value?.slice(0, 50), error: e.validationMessage
    })),
    errors: [...document.querySelectorAll('[role=alert],.error')].map(e => e.innerText),
    url: location.pathname
  })`
});
```

**Why**: two full-page `browser_snapshot` responses in one verify cycle
cost ~$10 of sticky cache-read. A 500-byte targeted evaluate is ~100×
cheaper per call and drops to zero sticky cost once the turn completes.

**Playwright MCP flags shipped** (checked upstream v0.0.56):

- `--snapshot-mode none` — disables automatic ARIA snapshots on every
  tool response. Agents must call `browser_snapshot` explicitly when
  they want one. This is the load-bearing cost fix for the T096
  failure mode where `browser_navigate` returned 330 KB of implicit
  snapshot payload.
- `--console-level error` — the built-in console-messages feed only
  returns errors, not info/debug chatter.

Wired up in ``PlatformRuntime._default_mcp_args`` (parallel_runner.py).
If the fork adds a max-response-size flag later, add it there and
remove the prompt-side escape-hatch language in the fallback.

## Reference injection: scope prompts tightly

Sub-agents re-cache every byte of their prompt on every turn. A 38 KB
reference doc × 300 turns × $0.30 / M cache-read = ~$0.35 per doc per
spawn. Multiple sub-agents per cycle → adds up fast.

Rules:

- **CLAUDE.md** is only injected for roles that legitimately need
  project-wide conventions (validate, review, fix-build, crash-fix).
  E2E sub-agents (planner, executor, fix, verify) do **not** get it —
  the parent agent has already read it and puts the relevant bits in
  the prompt directly.
- **`reference/index.md`** is only injected for general-purpose
  implementation agents that need to pick which reference to read at
  runtime. E2E sub-agents get their refs injected directly by the
  runner and never need the index.
- **`mcp-e2e.md` is split by platform** into `mcp-e2e-core.md` +
  `mcp-e2e-web.md` / `mcp-e2e-android.md` / `mcp-e2e-ios.md`. Inject
  core plus the one platform variant that matches the current
  `mcp_caps`, not all three.

## Page manifests (optional, high ROI)

For stable pages (checkout, product detail, login), author a JSON
manifest at `specs/<feature>/validate/e2e/page-manifest/<route>.json`
with stable selectors and expected side-effects. The runner injects
the relevant manifest into the planner + executor prompts so the
agents don't have to discover selectors by snapshot.

See `reference/mcp-e2e-web.md` § "Page manifests" for the schema.

## code-review-graph: keep the signal clean

The graph's relevance ranking is only useful if dense cross-edge
clusters correspond to actual product code. On Kanix, Flutter-
generated desktop runner scaffolding (`admin/windows/`, etc.) was
drowning out payment/checkout/shipping code in results.

**Rule**: any directory that is
(a) never edited by humans,
(b) platform-scaffolding for a platform the project doesn't ship, or
(c) vendored third-party code
goes in `excludeDirs` in the project flake.

The existing `DEFAULT_IGNORE_PATTERNS` in upstream already covers
`node_modules`, `.dart_tool`, `dist`, etc. — only list project-specific
additions.

## `.specify/cost-config.json` override schema

Project root file, optional. Overrides the runner defaults on a
per-project basis. All keys optional.

```json
{
  "role_models": {
    "fix": "sonnet",
    "crash-fix": "sonnet"
  },
  "hang_budget_s": {
    "default": 480,
    "build-fix": 1200,
    "crash-fix": 1200,
    "fix": 720
  },
  "executor_step_cap": 4,
  "executor_wall_cap_s": 600
}
```

## What changes land with this guardrail file

See the commit history of this file and cross-reference with changes in
`parallel_runner.py`. If you're loosening a rule, first check the
git log for why it was tightened — the answer is almost always in the
T096 post-mortem or a later one.
