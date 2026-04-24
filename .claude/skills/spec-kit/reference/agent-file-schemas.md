# Agent File Schemas (implicit communication contracts)

When the runner hands work between agents, it does so through files on disk. Each file has a schema — sometimes strict JSON, sometimes markdown with parsed anchor headings, sometimes pure narrative. This reference is the source of truth for every such file. If you're writing or reading one of these files, match this schema exactly; the runner parses specific anchors and downstream agents rely on field names.

**Anchor convention.** Headings listed under "Runner-parsed anchors" are matched verbatim by `parallel_runner.py` — the runner uses them for routing, status detection, or state machine transitions. Change them and the runner breaks. Headings under "Narrative structure" are conventions agents follow so downstream agents can skim; they're not machine-parsed but they're contracts nonetheless.

**Relation to `interface-contracts.md`.** `interface-contracts.md` covers project-level IC-### contracts between tasks *within a project's codebase*. This file covers the meta-layer IC contracts between the runner-spawned *agent roles* themselves. Every file listed here is an implicit IC that the runner enforces. When you change a format here, update the consumers in `parallel_runner.py` at the same time.

## IC-AGENT-001: `findings.json`

- **Writer:** e2e-explore, e2e-executor, e2e-verify, e2e-fix (for infra synthesis)
- **Readers:** e2e-planner, e2e-explore (next iteration), e2e-verify, e2e-supervisor, e2e-fix, e2e-bug-supervisor
- **Format:** JSON
- **Location:** `{e2e_dir}/findings.json`
- **Lifecycle:** Created by first explore; updated in place (never truncated); overflow moved to `findings-full.json` when the inline excerpt exceeds 20KB (40KB for verify).

```json
{
  "version": 1,
  "iteration": 3,
  "findings": [
    {
      "id": "BUG-001",
      "severity": "critical|high|medium|low",
      "screen": "checkout",
      "flow": "guest-checkout",
      "summary": "one-line description",
      "steps_to_reproduce": ["step 1", "step 2"],
      "expected": "what should happen per spec",
      "actual": "what actually happens",
      "screenshot_path": "{e2e_dir}/screenshots/BUG-001.png",
      "view_tree_path": "{e2e_dir}/bugs/BUG-001/view-tree.txt",
      "status": "new|fixed|verified_fixed|verified_broken|wont_fix|pass",
      "category": "code|infrastructure",
      "source": "explore|executor|verify|infra-synthesis",
      "bug_dir": "{e2e_dir}/bugs/BUG-001"
    }
  ]
}
```

**Required fields:** `id`, `severity`, `screen`, `summary`, `expected`, `actual`, `status`.
**ID format:** `BUG-NNN` for UI bugs; `BLOCKER-<slug>` for infrastructure blockers synthesized from executor handoffs (see IC-AGENT-004).
**Status transitions:** `new` → `verified_broken` | `fixed` → `verified_fixed` | `pass` | `wont_fix`. Preserve prior-iteration entries with status `fixed` / `verified_broken` — never delete.

## IC-AGENT-002: `progress.md`

- **Writer:** e2e-explore, e2e-executor (append-only)
- **Readers:** e2e-planner, e2e-supervisor, e2e-explore (next iteration, to skip validated screens)
- **Format:** Markdown, append-only log
- **Location:** `{e2e_dir}/progress.md`
- **Runner-parsed anchors:** none (narrative)

Each entry is one line per completed screen or executor step:

```markdown
- step-1: navigated to /home, saw welcome screen
- step-2: filled login form with test@example.com, clicked submit
- Cart screen: validated add/remove, coupon errors (iteration 2)
```

Tail-truncated to ~8KB when inlined; overflow moved to `progress-full.md`.

## IC-AGENT-003: `plan.md`

- **Writer:** e2e-planner
- **Readers:** e2e-executor, e2e-diagnostic
- **Format:** Markdown
- **Location:** `{e2e_dir}/plan.md`
- **Runner-parsed anchors:** `# E2E Plan`, `## Steps`, `### step-<N>:`

```markdown
# E2E Plan — iteration 3

## Intent
2–3 sentences on what this iteration focuses on and why.

## Steps

### step-1: navigate to checkout
- intent: validate cart persistence across navigation
- preconditions: cart has ≥1 item
- actions: browser_navigate to /checkout; browser_snapshot
- expected: cart total and item list visible on checkout page
- on_mismatch: if cart is empty, skip — likely BUG-014

### step-2: ...

## Notes for executor
Cross-step gotchas (e.g., "steps 3-5 share cart state — do not reset between them").
```

**Step ID format:** `step-<N>` sequentially. The executor matches these IDs when resuming from a prior handoff.

## IC-AGENT-004: `handoff.md` / `handoff-spawn-<N>.md`

- **Writers:** e2e-executor (primary); parallel_runner's `_synthesize_executor_handoff` (fallback, when the executor exits or is killed without writing one)
- **Readers:** next e2e-executor spawn; e2e-fix (when `## Infrastructure blockers` section present)
- **Format:** Markdown
- **Location:** `{e2e_dir}/executor/handoff.md` (current spawn) → archived to `{e2e_dir}/executor/handoff-spawn-<N>.md` after the runner consumes it
- **Runner-parsed anchors:** `## Status:`, `## Cap reason:`, `## Infrastructure blockers`, `### BLOCKER-<slug>` (parsed by `_parse_infra_blockers` at parallel_runner.py)

Exit modes — exactly one `Status:` value:

```markdown
# Executor handoff (spawn 3)

## Status: COMPLETE | PARTIAL

## Cap reason: step-cap | wall-cap | self-elected | blocker | hang-kill | unknown-exit
<!-- REQUIRED when Status: PARTIAL. Tells the runner why the spawn ended. -->

## Steps completed this spawn
- step-1: [short result]
- step-2: [short result]

## Next step to resume at: step-4
<!-- REQUIRED when Status: PARTIAL; omit when COMPLETE -->

## State left behind
<!-- REQUIRED when Status: PARTIAL. One paragraph: cart contents, auth state, current URL, etc. -->

## Infrastructure blockers
<!-- OPTIONAL. When present, runner skips remaining executor spawns and hands to e2e-fix. -->

### BLOCKER-<slug>
- **Symptom** [one line, concrete]
- **Evidence** [log line, curl output, version numbers, file paths + line numbers]
- **Suspected root cause** [one sentence]
- **Suggested fix location** [file path(s)]
- **How a fix agent can verify** [one short check]

## Findings written
BUG-001, BUG-002
<!-- Or "none" -->
```

**Status values:** `COMPLETE` (all plan steps done), `PARTIAL` (stopped gracefully mid-plan), `PARTIAL` + `## Infrastructure blockers` (app-level defect prevents progress; routes to fix agent instead of another executor spawn).

**Cap reasons:**

- `step-cap` — executor hit `EXECUTOR_STEP_CAP_PER_SPAWN` (default 4).
- `wall-cap` — executor approached `EXECUTOR_WALL_CAP_S` (default 600 s).
- `self-elected` — executor chose to stop early (context feels loaded, tool-call budget high).
- `blocker` — executor wrote `blocker.md` instead (same file, different field).
- `hang-kill` / `unknown-exit` — runner-synthesized handoff, not agent-authored. The executor was killed by the idle watchdog or wall-cap without writing its own handoff. See `reference/cost-guardrails.md` § "Hang budgets — work preservation".

**BLOCKER slug format:** kebab-case (e.g., `BLOCKER-supertokens-cdi-mismatch`). The runner uses the slug as the finding ID when it synthesizes entries into `findings.json` with `category: "infrastructure"`.

## IC-AGENT-005: `blocker.md`

- **Writer:** e2e-executor (exit mode C: current step unsalvageable, cannot classify as bug vs precondition error)
- **Reader:** e2e-diagnostic
- **Format:** Markdown
- **Location:** `{e2e_dir}/e2e/<step-id>/blocker.md`
- **Runner-parsed anchors:** `# Executor blocker`, `## Blocked step:`

```markdown
# Executor blocker (spawn 2)

## Blocked step: step-5
## Step intent: [from plan.md]

## What you tried
[Exact MCP tool calls and their results — tool name, args, returned value]

## Observed state
[Snapshot / hierarchy / tree excerpt showing the relevant element(s).]

## Expected state
[Per plan.md step-5 expected field, with attribute values if relevant.]

## Why it doesn't match (hypothesis)
[One paragraph: could be bug, could be precondition you missed, could be spec gap. Be explicit that you cannot tell.]
```

## IC-AGENT-006: `unblock-N.md`

- **Writer:** e2e-diagnostic
- **Reader:** next e2e-executor spawn on that step
- **Format:** Markdown
- **Location:** `{e2e_dir}/e2e/<step-id>/unblock-<attempt>.md`
- **Runner-parsed anchors:** `## Action for next executor spawn` — the value starts with exactly one of `FILE_AND_SKIP`, `RETRY_WITH`, or `SKIP_SPEC_GAP`.

```markdown
# Unblock guidance — step-5, attempt 1

## Diagnosis
[One paragraph: what's actually going on.]

## Action for next executor spawn
<!-- Exactly one of: -->
- FILE_AND_SKIP: File the blocker as a finding with summary "<short>", severity <critical|high|medium|low>, then skip this step.
- RETRY_WITH: Try the step again, but [concrete modification — new selector, different preconditions, specific waits].
- SKIP_SPEC_GAP: Skip the step. Note in progress.md: "step-N skipped — spec unclear about <aspect>".

## Why
[One sentence: why this is the right action.]
```

## IC-AGENT-007: `research-N.md`

- **Writer:** e2e-research (standalone) or e2e-fix (inline when no research exists)
- **Readers:** e2e-fix, e2e-bug-supervisor, e2e-escalation
- **Format:** Markdown
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/research-<N>.md` (N starts at 1; redirected research increments)
- **Runner-parsed anchors:** none (narrative consumed whole)

```markdown
# Research: <BUG-ID> — <summary>

## Root cause analysis
[What's actually wrong in the code and why. One paragraph.]

## Evidence
[Code snippets, doc quotes, working examples found in codebase. Concrete citations — file:line, URL, or exact tool output.]

## Recommended fix strategy
[Concrete approach — exact API calls, code patterns, file paths to modify. "use X with parameters Y" not "consider using X".]

## What NOT to do
[Approaches already tried that failed, and why they failed. Each entry should be 1 line.]

## Confidence
[High | Medium | Low — and what would increase confidence if Low.]
```

**Cross-reference:** Fix attempts listed here come from `bug_history.json` (IC-AGENT-012) `fix_attempts` array. The `What NOT to do` section is the human-readable projection of that structured history.

## IC-AGENT-008: `verify-evidence-{iter}.md`

- **Writer:** e2e-verify
- **Readers:** e2e-fix (next attempt), e2e-bug-supervisor, e2e-research (when redirected)
- **Format:** Markdown
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/verify-evidence-<iteration>.md`
- **Runner-parsed anchors:** `## Status:` — value is exactly `FIXED` or `STILL_BROKEN`

```markdown
# Verify evidence: <BUG-ID> — iteration N

## Status: FIXED | STILL_BROKEN

## Actions taken
1. [exact MCP tool call and parameters]
2. [next action...]

## Observed state
[Snapshot / hierarchy / tree excerpt showing the relevant UI element(s). Paste the exact output — do NOT paraphrase.]

## Expected state
[What the state SHOULD look like per the spec, with specific attribute values.]

## Delta
[Concrete difference: "Element has aria-disabled=true, expected aria-disabled=false" or "Node missing entirely from tree" — NOT "the UI is broken".]

## Screenshot
[Path to screenshot file, or "not needed — structured state sufficient".]
```

**Why Delta is strict:** downstream agents (fix, supervisor, research) read the Delta line to form their next approach. "Bug still broken" is useless; "`aria-disabled=true`, expected `false`" is surgical.

## IC-AGENT-009: `supervisor-{N}-decision.md`

- **Writer:** e2e-bug-supervisor
- **Readers:** e2e-fix (embedded in fix prompt), next e2e-research (if redirected), next e2e-bug-supervisor run, e2e-escalation
- **Format:** Markdown
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/supervisor-<run>-decision.md`
- **Runner-parsed anchors:** `# DIRECT_FIX`, `# REDIRECT_RESEARCH`, `# ESCALATE` — the H1 is the decision

```markdown
# DIRECT_FIX | REDIRECT_RESEARCH | ESCALATE

## (body varies by decision — see below)
```

Decision body templates (all three chosen in the prompt at parallel_runner.py:14533):

**DIRECT_FIX** — concrete strategy ready:
```markdown
## Strategy
[Exact approach — specific API calls, code changes, file paths]

## Why this will work
[Evidence from the history/research that supports this approach]

## What's different from previous attempts
[How this differs from what was already tried]
```

**REDIRECT_RESEARCH** — prior research wrong/incomplete:
```markdown
## What went wrong with current approach
[Why the research/fix direction isn't working]

## Research directive
Question: [specific question the research agent should answer]
Context: [what's been ruled out and why]
Leads to investigate:
- [specific search leads]
```

**ESCALATE** — fundamentally stuck:
```markdown
## Category
code | spec | infra

## Why we're stuck
[Summary of what's been tried and why nothing works]

## What a human could provide
[Specific guidance or decision needed]
```

## IC-AGENT-010: `supervisor-{N}-summary.md`

- **Writer:** e2e-bug-supervisor
- **Readers:** future e2e-bug-supervisor runs (accumulated context), e2e-research (when redirected)
- **Format:** Markdown, ≤15 lines
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/supervisor-<run>-summary.md`
- **Runner-parsed anchors:** none (narrative)

```markdown
## Approach evaluated
[What the fix agent tried — one line.]

## Why it failed
[One line. Reference verify-evidence Delta if applicable.]

## Decision taken
DIRECT_FIX | REDIRECT_RESEARCH | ESCALATE

## Key insight for next supervisor
[One line — the load-bearing observation from this run.]
```

## IC-AGENT-011: `guidance.md` + `supervisor-decision.md` (loop-level)

- **Writer:** e2e-supervisor (loop-level)
- **Readers:** e2e-explore (next iteration, `guidance.md`); runner decision logic (`supervisor-decision.md`)
- **Format:** Markdown
- **Location:** `{e2e_dir}/guidance.md` and `{e2e_dir}/supervisor-decision.md`

**`supervisor-decision.md`** — the H1 is the decision, parsed by the runner:

```markdown
# CONTINUE | REDIRECT | STOP

[Body: narrative assessment, bug-count oscillation observations, reasoning.]
```

**`guidance.md`** — narrative strategy for the next explore spawn (no parsed anchors):

```markdown
## Strategic guidance for iteration <N>

Focus on error paths in the sign-up flow. Previous iteration tested happy path;
now test:
- Invalid email format handling
- Existing email rejection
- Network timeout during signup

## What to skip

- Checkout happy path (validated iterations 1–2)
```

## IC-AGENT-012: `bug_history.json`

- **Writer:** runner (via `_record_fix_attempt` at parallel_runner.py:5677)
- **Readers:** e2e-fix, e2e-bug-supervisor, e2e-research, e2e-escalation
- **Format:** JSON
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/history.json`

```json
{
  "bug_id": "BUG-001",
  "fix_attempts": [
    {
      "attempt": 1,
      "approach": "Added CartService.saveCart() call in onClick handler",
      "verify_status": "still_broken",
      "verify_evidence": "Cart still resets on reload; localStorage remains empty",
      "timestamp": "2026-04-20T14:32:11Z"
    }
  ],
  "supervisor_runs": 1
}
```

**Required fields:** `bug_id`, `fix_attempts[]` (each: `attempt`, `approach`, `verify_status`, `timestamp`), `supervisor_runs`.
**`verify_status` enum:** `still_broken`, `fixed`, `verified_fixed`, `pending_verify`.
**Oscillation detection:** e2e-bug-supervisor builder computes a signature hash from the first 80 chars of each `approach` and pre-computes an oscillation note (parallel_runner.py:14600+).

## IC-AGENT-013: `fix-history.md`

- **Writer:** runner (rolling log, appended after each platform-fix claim)
- **Readers:** platform-fix (repeat-failure detection at parallel_runner.py:11076), cross-attempt summary
- **Format:** Markdown (one line per attempt, machine-parsed)
- **Location:** `{project}/test/e2e/.state/fix-history.md`
- **Runner-parsed anchor:** `- attempt <N>: service=<X> port=<P> patterns=<a>,<b> at=<ts>` — parsed by the regex at parallel_runner.py:11098

```markdown
- attempt 1: service=api port=3000 patterns=port-already-in-use,stale-pid at=2026-04-20T14:32:11Z
- attempt 2: service=api port=3000 patterns=stale-pid at=2026-04-20T14:38:02Z
- attempt 3: service=supertokens port=3567 patterns=config-validation-missing-required at=2026-04-20T14:42:19Z
```

**Format is strict** — `service=<token>` and `patterns=<comma-list>` are both matched by regex. `patterns=none` is valid (no pattern matched).

## IC-AGENT-014: `claims/completion-{TASK_ID}.json`

- **Writer:** task-implementer, e2e-executor (on task completion)
- **Readers:** runner verifier, e2e-explore (next iteration, when re-running a task)
- **Format:** JSON
- **Location:** `{spec_dir}/claims/completion-<TASK_ID>.json`

```json
{
  "task_id": "T096",
  "status": "complete",
  "summary": "One-line description of what you did",
  "commands_run": [
    {"command": "pnpm --dir api test", "exit_code": 0},
    {"command": "pnpm --dir api build", "exit_code": 0}
  ],
  "files_created": ["api/src/webhooks/stripe.ts"],
  "files_modified": ["api/src/router.ts"],
  "screenshots": [],
  "mcp_interactions": 0
}
```

**Required fields:** `task_id`, `status`, `summary`, `commands_run[]`, `files_created[]`, `files_modified[]`, `screenshots[]`, `mcp_interactions`.
**Status enum:** `complete` (only legal value when writing; `deferred` / `blocked` use different files).
**`mcp_interactions`:** count of MCP tool calls for UI-driven tasks; `0` for non-E2E tasks. The runner rejects completion claims where `mcp_interactions: 0` on tasks tagged `[needs: mcp-*]` — see verification.md § Verification rules by task type.

## IC-AGENT-015: `claims/rejection-{TASK_ID}.md`

- **Writer:** runner verifier
- **Readers:** task-implementer (on retry), e2e-explore (on retry)
- **Format:** Markdown (narrative; no parsed anchors)
- **Location:** `{spec_dir}/claims/rejection-<TASK_ID>.md`

```markdown
# Rejection: T096

## Reason
Completion claim shows `mcp_interactions: 0` but the task is tagged `[needs: mcp-android]`.
Tasks that drive a platform runtime must have at least one MCP interaction.

## Required before re-submission
1. Launch the Android app via MCP and observe at least one screen.
2. Save a screenshot to `{e2e_dir}/screenshots/T096-proof.png`.
3. Re-submit the claim with `mcp_interactions >= 1` and the screenshot path in `screenshots[]`.

## Prior attempt reference
See `{spec_dir}/attempts/T096.jsonl` line 3 — that attempt wrote no screenshots.
```

## IC-AGENT-016: `claims/platform-fix-*.json` and `claims/platform-meta-fix-*.json`

- **Writer:** platform-fix / platform-fix-meta (via `<claim>...</claim>` trailer parsed from agent output)
- **Readers:** runner (cross-attempt summary, repeat-failure detection)
- **Format:** JSON
- **Location:** `{spec_dir}/claims/platform-fix-<TASK_ID>-platform-fix-<N>.json` and analogous `platform-meta-fix-*.json`

Emitted by the agent inside a final-message trailer (parsed by the runner, then written to disk):

```markdown
<claim>
{
  "root_cause": "Stale pidfile at .dev/e2e-state/api.pid prevented the runner from noticing the service had crashed.",
  "files_changed": ["test/e2e/setup.sh", "test/e2e/teardown.sh"],
  "verified": true,
  "evidence": "ran `bash test/e2e/setup.sh` from a cold state and observed exit 0; all pidfiles removed before start"
}
</claim>
```

**Required fields:** `root_cause`, `files_changed[]`, `verified`, `evidence`.
**`verified` semantics:** `true` only if the agent ran a cold-start reproduction and observed success. The runner treats `verified: false` as "fix proposed but not proven" and keeps the attempt open for the next agent.
**Meta-fix extension:** `platform-meta-fix-*.json` adds `"structural_cause": "..."` (the one-layer-up observation) and may include `"hypothesis_falsified": "<what was ruled out>"`.

## IC-AGENT-017: `attempt-N-diagnosis.md`

- **Writer:** ci-diagnose
- **Readers:** ci-fix (inlined in fix prompt at parallel_runner.py:6405)
- **Format:** Markdown
- **Location:** `{debug_dir}/attempt-<N>-diagnosis.md`
- **Runner-parsed anchors:** `# CI Diagnosis — Attempt <N>`

```markdown
# CI Diagnosis — Attempt 1

## Root cause
One paragraph: what exactly failed and why.

## Failed jobs
- build-typescript: error TS2314 at src/components/Settings.tsx:42
- test-integration: 2 failed assertions in DarkModeToggle.test.ts

## Recommended fix
Specific files to change and what to change — be precise with line numbers.

## Risk assessment
What might break if this fix is applied naively.

## Files to modify
- src/components/Settings.tsx
- src/components/DarkModeToggle.tsx
```

## IC-AGENT-018: `attempt-N-local-{iter}.md`

- **Writer:** ci-local-validate
- **Readers:** runner (PASS/FAIL routing), ci-fix (next iteration)
- **Format:** Markdown
- **Location:** `{debug_dir}/attempt-<N>-local-<iter>.md`
- **Runner-parsed anchors:** `## Result:` — value is exactly `PASS` or `FAIL`

```markdown
# Local Validation — Attempt 1, Iteration 1

## Result: PASS | FAIL

## Commands run
| Command | Exit code | Status |
|---------|-----------|--------|
| `pnpm --dir api build` | 0 | PASS |
| `pnpm --dir api test -- --run` | 1 | FAIL |
| `pnpm --dir api lint` | 0 | PASS |

## Failure details
<!-- Omit when Result: PASS -->

### Command: `pnpm --dir api test -- --run`
[relevant error output — full stderr tail, not truncated]

## Sanity checks
- Zero-tests guard: 47 tests ran (vs 47 test files on disk) — OK
- Skip guard: 0 skipped — OK
```

## IC-AGENT-019: `validate/{N}.md` (validation report)

- **Writer:** validate-review
- **Readers:** vr-fix (next cycle), runner (PASS/FAIL state)
- **Format:** Markdown
- **Location:** `{spec_dir}/validate/<phase-slug>/<N>.md`
- **Runner-parsed anchors:** `# Phase <phase_slug> — Validation #<N>:` and the trailing verdict `PASS` or `FAIL` on the H1 line

```markdown
# Phase phase1 — Validation #1: FAIL

**Date**: 2026-04-20T14:32:11Z

## Failure categories
- **Build**: PASS | FAIL | SKIPPED
- **Test**: PASS | FAIL | SKIPPED (N passed, M failed, K skipped)
- **Lint**: PASS | FAIL | SKIPPED (N errors, M warnings)
- **Security**: PASS | FAIL | SKIPPED (N findings)
- **Coverage**: COMPLETE | INCOMPLETE

## Coverage proof
**Files changed**: 5 files
**Build systems modified**:
- TypeScript: 3 files → `pnpm --dir api test` → 12 passed, 0 failed
- Go: 2 files → `go test ./...` → 45 passed, 0 failed

**Unvalidated build systems**: none

## Failed steps detail

### Test
**Command**: `pnpm --dir api test -- --run`
**Exit code**: 1
**Root cause summary**: [1–2 sentence diagnosis]

[Full stderr tail — do not truncate]
```

## IC-AGENT-020: `review-{cycle}.md`

- **Writer:** validate-review (after the validation step passes, as the review phase)
- **Readers:** validate-review (next cycle, to see what was flagged), vr-fix (indirectly via subsequent FAIL)
- **Format:** Markdown
- **Location:** `{spec_dir}/validate/<phase-slug>/review-<cycle>.md`
- **Runner-parsed anchors:** H1 contains either `REVIEW-CLEAN` or `REVIEW-FIXES`

```markdown
# Phase phase1 — Review #1: REVIEW-CLEAN | REVIEW-FIXES

## Findings
<!-- When REVIEW-CLEAN, one-line summary is enough. -->
<!-- When REVIEW-FIXES, list each finding: -->

### Finding 1: [one-line summary]
- **Severity**: blocker | major | minor
- **File:line**: api/src/router.ts:42
- **Observed**: [what's wrong]
- **Fix applied**: [what the review agent changed in this cycle]

## Diff range reviewed
Delta: `git diff <prev_review_sha>...HEAD`
Full phase: `git diff <base_sha>...HEAD`
```

## IC-AGENT-016: `bugs/<BUG-ID>/verify.sh`

- **Writer:** e2e-fix (REQUIRED when closing any E2E bug)
- **Readers:** parallel_runner's `_run_scripted_verify_phase`
- **Format:** Executable bash script
- **Location:** `{e2e_dir}/bugs/<BUG-ID>/verify.sh`
- **Runner invocation:** `bash verify.sh`, cwd = project root, env sourced from `test/e2e/.state/env`, 30 s timeout

**Exit codes**

| Code | Meaning | Runner action |
|---|---|---|
| `0` | Verified fixed | Finding → `fixed`; evidence written from stdout |
| `1` | Verified still broken | Finding → `verified_broken`; evidence written |
| `2` | Inconclusive | Falls through to e2e-verify agent spawn |
| other / timeout | Treated as inconclusive | Falls through to e2e-verify agent spawn |

**Stdout format** (parsed by the runner for the evidence file):

```
STATUS: FIXED | STILL_BROKEN
EVIDENCE: <one-line concrete delta>
COMMAND: <command used>
```

Lines after line 3 are captured verbatim in
`verify-evidence-<iter>-script.md` next to the script.

**Rationale:** a missing or inconclusive `verify.sh` triggers a full
verify-agent spawn for that bug (~$12 per iteration). See
`reference/cost-guardrails.md` § "Scripted verify first" for the
contract origin and `reference/fix-agent-playbook.md` § "Writing
verify.sh" for authoring guidance and a canonical example.

## Schema maintenance rules

1. **When a writer changes the format**, update the corresponding IC-AGENT-* entry here in the same commit. Consumers key off field names and anchor headings — silent changes break downstream agents.
2. **When the runner adds a new parsed anchor**, add it to the "Runner-parsed anchors" line of the file's entry. If you don't document it, future refactors will break the parser.
3. **When you add a new cross-agent file**, assign the next IC-AGENT-NNN number and add the entry here before writing the first prompt that produces or consumes it.
4. **Do not inline these schemas into prompts.** The Tier-1 read of this file gives every agent the schemas; inlining them per-prompt bloats each per-agent prompt file without any cross-spawn cache benefit (see cost-reporting.md § Prompt-caching strategy).
