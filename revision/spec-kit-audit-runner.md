# Spec-Kit Runner Audit — `parallel_runner.py` (19,737 LOC) + `cost_report.py` (549 LOC)

Audit scope: the orchestration loop, every embedded agent prompt, every
runtime guardrail, and every observable smell. Line references are to
`parallel_runner.py` unless otherwise noted.

---

## 1. Architecture overview (~300 words)

`parallel_runner.py` is a single-file orchestrator that parses
`specs/<feature>/tasks.md`, builds a phase + dependency graph, then spawns
`claude` CLI sub-processes in parallel (default 3, `--max-parallel`) to
execute tasks. The CLI is invoked with `--dangerously-skip-permissions
--model <opus|sonnet|haiku> --verbose --output-format stream-json`, and the
prompt is written to a sidecar `*.prompt.md` file referenced via `-p "Follow
the instructions in <file> exactly"` (lines 3575-3595). Each spawn runs
inside a bubblewrap sandbox with an allowlist filesystem (lines 3308-3468):
only `/nix/store` (ro), the project dir (rw), the spec-kit `reference/`
directory (ro), DNS/SSL, and credentials passed via `Popen env=` are
visible.

The top-level loop lives in `Runner._run_feature` (10293+). Per iteration
it: (1) re-parses `tasks.md`, (2) scans `validate/<phase>/` files for
PASS/FAIL/REVIEW-CLEAN signals, (3) auto-clears stale `runner-verified.json`
failures, (4) clean-slate resets review files after a VR-fix completes, (5)
spawns up to `max_parallel` task agents on `[P]`-marked or ready tasks, (6)
spawns phase-boundary **validate** (Sonnet) and **review** (Opus) agents, (7)
spawns `VR-fix` agents on validation FAIL, (8) spawns `RV-fix` agents when
the runner's own deterministic re-execution of test commands fails after
REVIEW-CLEAN, (9) runs an independent runner-side verification step
(`subprocess.run(cmd, shell=True, timeout=600)`) that re-executes discovered
test commands and scans `test-logs/` for proof artifacts, skipped tests, and
coverage gaps.

CI-loop tasks (`[needs: ci-loop]`) and E2E loop tasks (`[needs: mcp-*,
e2e-loop]`) get dedicated threads with their own internal sub-agent
spawning, separate from the main scheduler (10712-10778). The `Runner`
class is monolithic (~9,800 LOC inside one class).

A `TUI` renderer (1088-1250) draws a live ASCII dependency graph plus
per-agent panes. Headless mode (`HeadlessLogger`, 1295+) just writes
status files. Sub-agents append structured events to
`<spec_dir>/run-log.jsonl`; `cost_report.py` reads those JSONL files,
buckets by model + task prefix, applies a hardcoded pricing table, and
emits `cost-report.md` + `cost-report.json`. The two files share no
pricing constants — see §8.

---

## 2. Embedded agent prompts (verbatim or near-verbatim)

### 2.1 Required-reads header — applied to every prompt

`_required_reads_block(role, abs_paths)` at line 179 renders the same
header for every spawn:

> "You are the **{role}** agent. Before you write a single line of code,
> call a single tool, or plan your approach, you MUST Read every file
> listed below. … An agent that skips required reads and produces the
> wrong output is **FAIL** — we do not grade on effort, we grade on whether
> you read the rules and followed them." (211-217)

It then mandates a literal `Read checklist: [✓] <file 1>, [✓] <file 2>, …`
line in the response (221) and forbids "Planning before reading" (227).

The `_GRAPH_USAGE_STANZA` (140-176) is appended for every role:

> "**Mandatory first-turn protocol** … 1. Call `mcp__code-review-graph__get_minimal_context_tool(task=...)` BEFORE any Read/Grep/Glob on source code. … **Never skip the graph to 'save time'**." (149-176)

E2E roles (`role.startswith("e2e-")`) skip CLAUDE.md auto-prepend and the
reference-index pointer to save tokens (203-205, 271).

### 2.2 Reasoning appendix — appended to every prompt

`REASONING_APPENDIX` (4409-4436) is concatenated to every `prompt` before
it's written to the sidecar file (3594):

> "Before you stop, end your final message with a section titled exactly
> `## Reasoning` covering: **What I did** … **Why** … **Confidence &
> risks** … **Next step if this fails** … **Prompt feedback —
> unnecessary** … **Prompt feedback — missing (mechanical)** …"

The runner parses this via `extract_reasoning` (4439) and archives it to
`<spec_dir>/reasoning/NNNNNN-{ts}-{kind}-{task_id}-agent{id}.md`.

### 2.3 Task-implementer prompt — `build_prompt` (1632-1899)

Opens with:

> "You are an implementation agent for a spec-kit project. Your job is to
> execute exactly ONE task from the task list, then stop." (1691)

Required reads: `CLAUDE.md`, `reference/testing.md` (1683-1687).

Inlines the phase-filtered task list and phase-relevant learnings
(`_extract_phase_block`, `_extract_relevant_learnings`).

Notable rules (1764-1772, "CRITICAL — Spec conformance rules"):

1. "Pin exact names from the task description… use that name verbatim."
2. "Implement the specified mechanism, not just the behavior."
3. "Count all specified steps."
4. "No stubs in production code."
5. "Cross-boundary data contracts."
6. "'Done when' is your stop signal."
7. "Fix failures — don't rationalize them."

Final-rules block (1882-1898):

> "- Execute your assigned task ({task.id}) ONLY, then stop
> - Do NOT skip ahead to later phases
> - Do NOT refactor unrelated code
> - Do NOT read ROUTER.md or load any skills
> - Do NOT use the Skill tool
> - If you need user input, write to BLOCKED.md … (e.g. `# BLOCKED: T075`)
> - If you need a tool that requires authentication, write `[needs: gh]` in BLOCKED.md
> - SECURITY: If your task has `gh` access, you MUST NOT run any package installation commands
> - GIT PUSH: Always push via HTTPS, never SSH … YubiKey prompts that hang in headless mode
> - ALWAYS update `{learnings_file}` if you discovered anything non-obvious (max 3 concise bullets per task)
> - When your task is complete, mark it `[x]` in tasks.md
> - NEVER write a completion claim if any required command from the task description did not exit 0"

Also: Step 5 requires writing `{spec_dir}/claims/completion-{task.id}.json`
with `commands_run`, `files_created`, `files_modified`, `screenshots`,
`mcp_interactions` (1787-1804).

### 2.4 Retry prompt (for connection-error retries) — `build_retry_prompt` (8886-8937)

When prior agents wrote code but crashed on connection errors, swaps the
full implementer prompt for a 30-line "verify and mark complete" prompt.
Tells the agent NOT to re-read spec/plan/data-model, NOT to rewrite
existing code.

### 2.5 Validate-only prompt — `build_validate_prompt` (2384-2472)

Stance block (2422-2433):

> "## STANCE: ADVERSARIAL
>
> You are looking for the case where the previous agents claimed success
> without doing the work. **Assume that case.** Find the evidence. Prior
> agents' commit messages, completion claims, and self-authored validation
> records are NOT a source of truth — they are advertising."

Lists five "failure shapes" (silent skip with green claim, pattern-matched
rule satisfaction, coverage shortcut, test ran with failure-mode disabled,
anchored on prior validate/N.md) — all explicit anti-fake-work
heuristics.

Required reads: `CLAUDE.md`, `proof-discipline.md`, `testing.md`,
`validate-review.md`, `pre-pr.md` (2408-2417). Sonnet by default but
upgraded to Opus when the diff touches test files (11009-11013).

### 2.6 Review-only prompt — `build_review_prompt` (2475-2672)

Cycle-aware (delta vs full diff, 2496-2530). Pre-computes
`code-review-graph detect-changes` and splices the formatted result into
the prompt (2545-2559). Required reads include the project-stack-specific
review skill (`code-review-react`, `code-review-node`, or base
`code-review`, 2534-2541).

Adversarial stance again (2594-2601):

> "The validate agent wrote PASS for this phase. **Do not trust that
> PASS.** Re-derive whether the phase actually accomplished what tasks.md
> demanded."

Mandates substrate audits: read `test-logs/`, read tests that disable
failure modes, build the route-coverage matrix, treat `claims/completion-*.json`
only as "what claims to falsify."

Mandates `verification.json` schema (2635-2660) with
`tasks_verified[].{commands_run, artifacts_inspected, verdict, evidence,
lie_check}` and `overall_verdict`. The runner refuses REVIEW-CLEAN
records that lack non-vacuous `verification.json` (868-898), keying
specifically on the `lie_check` field.

### 2.7 Combined validate+review prompt — `build_validate_review_prompt` (2675-3107)

Legacy code path (still callable, e.g. for projects pre-split). Long —
~430 lines. Critical rules (2934-2947):

> "**CRITICAL — unable to validate = FAIL** … **CRITICAL — zero test
> results = FAIL** … **CRITICAL — any skipped test = FAIL**: If `skip > 0`
> in the test summary, the phase is FAIL. No exceptions, no matter the
> reason. `describe.skip`, `t.Skip`, `pytest.mark.skipif`, `if (!canRun)
> return;` … all equivalent silent-skip loopholes."

### 2.8 VR-fix prompt — `build_vr_fix_prompt` (1902-1995)

Required reads: `testing.md`, `fix-agent-playbook.md` (1949-1955).

> "**Do NOT modify the task list** — the runner manages task status.
> **Do NOT write validation files** — the runner will re-run VR after you finish.
> **Do NOT skip tests to make them pass** — see testing.md § Zero-skips rule." (1987-1989)

### 2.9 RV-fix prompt — `build_rv_fix_prompt` (1998-2236)

Used when the LLM said REVIEW-CLEAN but the runner's deterministic re-run
of test commands failed. Inlines the failed-command tails (stdout 8 KiB,
stderr 8 KiB) and embeds a "non-negotiable exit checklist" listing every
failing command numbered, "must exit 0" each (2173-2183).

Surfaces every prior RV-fix attempt's reasoning file as a Read path
(2082-2110). Caps explicit at attempt 5: "further attempts after the cap
will stall the entire phase."

### 2.10 CI-debug-loop prompts (4 sub-agents)

- `build_ci_diagnose_prompt` (9227-9329): "**You MUST NOT modify any
  source code, config files, or CI workflows.** Your only output is the
  diagnosis file." Lists Markdown schema with Root cause / Failed jobs /
  Recommended fix / Risk assessment / Files to modify.
- `build_ci_fix_prompt` (9332-9440): Inlines diagnosis. Mandates "Fast
  checks" only (lint + build + `go test -short`); explicitly forbids
  "slow commands" (nix flake check, docker integration, full `-race`
  suites). Allows 3 iterations of fast checks (9413-9415).
- `build_ci_local_validate_prompt` (9443-9620): Tells agent to discover CI
  commands by parsing `.github/workflows/*.yml`, run each, sanity-check
  semantically. Calls out specific anti-patterns: "Zero tests ran",
  "Phantom passes" (compare tests-run vs `find -name '*_test.go' | wc -l`),
  "Exit code swallowed by pipe", "Multi-build-system blind spot",
  "Silent tool failures".
- `build_ci_finalize_prompt` (9623-9754): Adds a Step 0 "Sanity-check CI
  results" before allowing PR creation — fetches run summary, downloads
  job logs, cross-references test counts against source files, validates
  badges and artifacts, runs spec acceptance scenarios. On any mismatch,
  writes `sanity-check-fail.md` and refuses to finalize.

### 2.11 E2E loop prompts (planner / executor / diagnostic / fix / verify / supervisor / research / regression / crash-supervisor / escalation / bug-supervisor) — 8 distinct builders

- `_build_e2e_explore_prompt` (17678-17904): Full-app or task-scoped UI
  sweep. Hard caps: "20 screenshots per session", "10+ screenshots or 100+
  tool calls → save and stop gracefully". Forbids: curl/wget/fetch
  substitutes for MCP, source-code modification, interactive Bash
  commands without timeout.
- `_build_e2e_planner_prompt` (17911+): Opus, plans 10–20 steps, no app
  interaction.
- `_build_e2e_executor_prompt` (18046-18296): Sonnet. Hard per-spawn cap:
  `EXECUTOR_STEP_CAP_PER_SPAWN=4` (8238), `EXECUTOR_WALL_CAP_S=600` (8239,
  10 min). Three exit modes: (A) COMPLETE, (B) PARTIAL with handoff /
  (B-infra) PARTIAL with infrastructure blocker, (C) BLOCKED on step.
  Inline retry once before declaring blocker. Cost-discipline section
  mandates cheap structured tools (`browser_evaluate`/`State-Tool`) over
  snapshots/screenshots. Mandatory `<claim>{...}</claim>` JSON trailer.
- `_build_e2e_diagnostic_prompt` (18298-18378): Opus. Diagnoses an
  executor blocker, writes `unblock-<N>.md` with FILE_AND_SKIP /
  RETRY_WITH / SKIP_SPEC_GAP.
- `_build_e2e_fix_prompt` (18380-18701): Required reads
  `fix-agent-playbook.md`, `e2e-failure-patterns.md`. Mandates per-bug
  `verify.sh` script (saves $12 per cycle per the prompt text, 18632).
  Mandatory `<claim>{...}</claim>` trailer with `root_cause`,
  `files_changed`, `verified`, `evidence`. Out-of-scope variant for
  read-only sandbox writes.
- `_build_e2e_verify_prompt` (18703-): "Maximum 15 screenshots per
  session". Updates findings.json after each bug.
- `_build_e2e_supervisor_prompt` (18864-18938): Reviews loop progress,
  writes CONTINUE / REDIRECT / STOP decision. Heuristic: "If the same bug
  has been 'fixed' and 'verified_broken' more than 3 times, that's a sign
  the fix approach is wrong" (18935).
- `_build_e2e_regression_prompt` (18940-18992), `_build_e2e_crash_supervisor_prompt`
  (18994-19068), `_build_e2e_research_prompt` (19072-19229),
  `_build_e2e_bug_supervisor_prompt` (19231+), `_build_e2e_escalation_prompt`
  (19439+).

### 2.12 Cost-discipline section (17610-17676)

Same text every spawn, every iteration:

> "Two-tier discipline. The cheapest tier is the default; the middle tier
> is a fallback; the expensive tier is only for bug evidence."

For web (mcp-browser): default `browser_evaluate` (~500 bytes), fallback
`browser_snapshot` (one shot), evidence-only `browser_take_screenshot`.
For Android: `State-Tool` without `use_vision` default, `Screenshot` only
for visual bug evidence.

> "Every screenshot must produce a finding whose `screenshot_path` points
> at the file. No finding = wasted budget."

### 2.13 Platform-init fix prompt (15041-15600+, both regular and meta variants)

Required reads: `fix-agent-playbook.md`, `e2e-failure-patterns.md`. Surfaces
all prior `claims/platform-fix-*.json` and `platform-meta-fix-*.json` files
as a Read list. Meta-variant adds a "structural-redesign" charter with five
categories (environment drift, sandbox/host mismatch, missing durable state,
wrong abstraction boundary, race between 'ready' and 'registered') and
mandates a hypothesis brief before any edit.

### 2.14 Duplications & contradictions noted

- **Nix-note duplication**: substantively identical "Environment: This
  project uses Nix" stanza appears at 1663, 1941-1947, 2058-2064,
  2368-2381, 2699-2711, 8899-8903, 9251-9253, 9352-9354, 9451-9453,
  9629-9631 — at least 10 copies, occasionally diverging (long version
  at 2368 includes sandbox+timeout guidance; CI versions are one-liners).
- **"Do NOT read ROUTER.md or load any skills / Do NOT use the Skill
  tool"** appears verbatim in nearly every prompt (1887-1888, 2468-2469,
  2669-2670, 3100-3101, 9328, 9437, 9616-9617, 9752). The implementer
  prompt forbids it, then the embedded code-review SKILL.md is inlined
  into the review prompt (2766-2790) — agent is told to follow it as
  prose instead.
- **Cap inconsistency in attempt-history advice**: the implementer
  prompt (1834-1835) says agents may mark a task complete after
  connection errors IF "code is already written and tests can't run due
  to connection issues, verify the code compiles (`go vet`, `go build`)
  and mark the task complete — phase validation will run the full test
  suite later." A few rules later (1897): "NEVER write a completion
  claim if any required command from the task description did not exit
  0." These collide whenever a connection-error retry hits a transitive
  test-command failure.
- **CI-fix says don't run slow tests; CI-local-validate says do**:
  `build_ci_fix_prompt` (9406-9411) explicitly forbids `nix flake check`
  and `-race -count=1` runs; `build_ci_local_validate_prompt` (9503-9505)
  explicitly requires them. The runner architecture is that fix→validate,
  so this is by design, but the role distinction is fragile — a single
  rename or a `_wait_for_subagent` swap could silently invert it.

---

## 3. Behavioral guardrails (code-enforced, not prompt-enforced)

| Guardrail | Where | Value |
|---|---|---|
| Max concurrent agents | `--max-parallel` (default 3) | 19634 |
| Max spawns per feature | `max_runs` arg (default 100) | 19630 |
| Agent idle log-timeout (default) | `AGENT_IDLE_TIMEOUT_S` | 20 min (8966) |
| Agent wall-clock cap (default) | `AGENT_HARD_TIMEOUT_S` | 90 min (8967) |
| Background bash 0-CPU deadlock | `AGENT_BG_DEADLOCK_S` | 5 min (8971) |
| VR agent idle budget | `_task_idle_budget_s` | 30 min (4106) |
| E2E agent idle budget | `_task_idle_budget_s` | 45 min (4109) |
| CI sub-agent idle | `CI_AGENT_IDLE_TIMEOUT_S` | 15 min (8960) |
| CI sub-agent wall | `CI_AGENT_HARD_TIMEOUT_S` | 60 min (8961) |
| CI loop max attempts | `CI_LOOP_MAX_ATTEMPTS` | 50 (8955) |
| CI local fix iterations per attempt | `CI_LOCAL_MAX_ITERATIONS` | 20 (8956) |
| CI same-failure consecutive cap | `CI_REPEAT_FAILURE_THRESHOLD` | 5 (8957) |
| Max VR fix attempts (also re-used for RV-fix) | `MAX_VR_FIX_ATTEMPTS` | 5 (11139, 11265) |
| Max VR-prefix hangs before giving up | `MAX_VR_HANGS` | 3 (10907) |
| Max review cycles | `MAX_REVIEW_CYCLES` | 2 (10906) |
| Max consecutive no-op iterations | `max_consecutive_noop` | 20 (10408) |
| Platform-init retries (per session) | `PLATFORM_INIT_MAX_ATTEMPTS` | 10 (14123) |
| Platform-init meta-fix cap | `PLATFORM_META_FIX_MAX` | 2 (5182) |
| Platform unproductive-streak threshold | `PLATFORM_LOOP_FAIL_THRESHOLD` | 3 (5175) |
| Platform lookback window | `PLATFORM_LOOP_LOOKBACK_HOURS` | 24 (5176) |
| Circuit breaker connection-error window | `check_circuit_breaker` | 3 in 10 min → wait 5 min (8816-8859) |
| Executor steps per spawn | `EXECUTOR_STEP_CAP_PER_SPAWN` | 4 (8238) |
| Executor wall cap per spawn | `EXECUTOR_WALL_CAP_S` | 600s (8239) |
| Executor spawns per E2E iteration | `EXECUTOR_MAX_SPAWNS_PER_ITER` | 5 (8231) |
| Blocker retries per step | `BLOCKER_MAX_RETRIES_PER_STEP` | 3 (8232) |
| Pre-E2E gate unproductive streak | `_PRE_E2E_GATE_UNPRODUCTIVE_STREAK_MAX` | 3 (12651) |
| Pre-E2E gate meta-fix max | `_PRE_E2E_GATE_META_FIX_MAX` | 2 (12652) |
| Pre-E2E gate hard cap | `_PRE_E2E_GATE_ROUND_HARD_CAP` | 50 (12653) |
| Pre-E2E services fix max | `_PRE_E2E_SERVICES_FIX_MAX_ATTEMPTS` | 5 (13026) |
| E2E consecutive explore failures | `MAX_CONSECUTIVE_EXPLORE_FAILURES` | 3 (15974) |
| E2E fix attempts before supervisor | `MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR` | 3 (16904) |
| E2E max supervisor runs | `MAX_SUPERVISOR_RUNS` | 5 (16905) |
| E2E build-fix max attempts | `BUILD_FIX_MAX_ATTEMPTS` | 10 (17249) |
| E2E install retry max | `INSTALL_RETRY_MAX` | 2 (17250) |
| CI loop respawn cap | inline | 3 per task.id (10706) |
| E2E loop respawn cap | inline | 5 per task.id (10747) |
| Subprocess test-command timeout | `subprocess.run(..., timeout=600)` | 600s (11481) |
| GH token TTL | `_GH_TOKEN_TTL` | 5 min (3273) |
| _recently_finished buffer | `_recently_finished_cap` | 200 (9790) |
| Output_lines buffer per agent | trim | last 200 lines (11902) |

### Other code-level guards

- **Sandboxing** is on by default (`_sandbox_enabled = True`, 3115).
  Disabled only via `--no-sandbox` (19638) or when `bwrap` isn't found
  (19660-19666). Sandbox env-var construction in `_build_sandbox_env`
  (3473) inherits PATH and SDK env vars but injects credentials via
  `Popen env=` not bwrap `--setenv`, to keep tokens out of
  `/proc/*/cmdline` (3456-3461).
- **Untrusted-code capability stripping** (5098-5108, 3606-3616): tasks
  whose description matches `npm install|pip install|cargo install|...`
  have `gh` and similar caps stripped even if declared. Hard block.
- **GH push always over HTTPS, never SSH** (`_gh_push`, 8997-9029):
  SSH would trigger YubiKey prompts and hang in headless mode.
- **flake.nix-change re-exec** (10420-10474): if any agent modifies
  `flake.nix`, drain agents, probe `nix develop --command true` (with
  `--impure` retry on unfree-detected stderr), `os.execvp` into new
  shell. 300s probe timeout.
- **Phase trivial-diff fast-path** (10952-10977): if a phase's diff
  contains no source-code files (only docs/configs), write
  REVIEW-CLEAN automatically without spawning a review agent.
- **Validate-review model routing** (11009-11013): Sonnet by default,
  Opus when the diff touches test files (per
  `_phase_diff_touches_tests`, 2338) — heuristic match against test
  filename/dir patterns 2309-2335.
- **Process-group kill** (`_kill_all_agents`, 10205-10261):
  SIGTERM → 5s wait → SIGKILL to each process group, then individual
  PIDs, then reap. Detects PID recycled into the runner's own pgid and
  signals individually to avoid self-kill.
- **PID file & stale runner cleanup** (`_cleanup_stale_run`, 10062-10096):
  on startup, kills the previous runner's process group if alive.
- **Layer-3 strict-mode**: refuses to advance to the next spec_dir when
  the current one didn't reach `all_complete` (10142-10177). Writes
  `STALLED.md`, `sys.exit(2)`. Bypass: `--continue-on-stall`.
- **No-progress detector** (`_no_progress_for_phase`, 9873-9890): if the
  last 3 runner_verify events for a phase all failed on the same set of
  commands, refuse to spawn another RV-fix agent. Writes
  `rv_no_progress_stall` event and logs a stall message (11284-11313).
- **Verification-json gating** (868-898): a REVIEW-CLEAN record is
  rejected if `verification.json` is missing, has empty `tasks_verified`,
  has `overall_verdict != "pass"`, or any task entry lacks
  `commands_run` / `artifacts_inspected` / `lie_check`.
- **Stale runner-verified.json reset on startup** (10367-10405): any
  `passed: false` rv_file is unlinked and all `review-*.md` files
  cleared, forcing a fresh VR cycle.
- **Runner-side proof-artifact scan** (11529-11556): for every
  `test-logs/**/*.json` that looks like a proof artifact (has `status`
  and `executed`), the runner requires `status="pass"` and `executed>0`.
  `status` mismatch is a FAIL regardless of command exit codes.
- **Runner-side skip scan** (`_scan_for_skipped_tests`, 11593-11623):
  scans for any skipped tests in test summary files since the verify
  started; any `skip > 0` is FAIL.
- **Runner-side coverage-matrix scan** (`_scan_coverage_matrix`,
  11563-11584): added/modified routes must be referenced by tests.
- **`run_in_background` deadlock probe** (`_check_agent_hang`,
  11728-11821): probes the agent's most recent background-bash command;
  if its process subtree accumulates 0 CPU ticks for 5 minutes while
  the agent log is also silent, kills the subtree and writes a
  `agent-<id>-<task>-<ts>.hang.md` diagnosis file. Next attempt's prompt
  surfaces these.

### Capabilities & MCP gating

`_AUTO_GRANTABLE_CAPS = {gh, e2e-loop, mcp-android, mcp-browser, mcp-ios,
stripe-listen}` (5093, 5157, 5165). BLOCKED.md with `[needs: X]` for any
of these → auto-grant, retry. Anything else → human gate (`sys.exit(2)`,
10628). `_SENSITIVE_ENV_KEYS = {GH_TOKEN, GITHUB_TOKEN,
GH_ENTERPRISE_TOKEN}` (5107).

---

## 4. Failure handling

### Path 1 — task-implementer fails

- **Non-zero exit + no rate-limit/auth/conn error**: status=`failed`,
  task stays PENDING (`_poll_agents`, 11986-11988). Next iteration
  re-spawns with `attempt_history` injected (1810-1851). No explicit
  per-task retry cap on the regular task path — relies on
  `max_consecutive_noop=20` (no spawn for 20 ticks → break) and
  `max_runs=100` (10428) to bound runaway.
- **Auth error** (`check_auth_error`, 3988): permanent.
  `_shutdown.set()` (12056), entire run stops. `claude` would need
  re-auth.
- **Rate-limited** (`check_rate_limited`, 3921): pulls `resetsAt`
  timestamp from stream-json, sleeps until then + 10s buffer (12060), or
  60s if no timestamp. Task stays PENDING.
- **Connection error** (`check_connection_error`, 4011): task stays
  PENDING. If 3 such errors hit within 10 minutes across all tasks, the
  circuit breaker trips and waits 5 minutes (8859, 10662-10678).
- **Watchdog-killed**: idle > budget, wall-clock > hard cap, or 0-CPU
  background bash for 5 min. Writes `agent-<id>-<task>-<ts>.hang.md`
  (4231-4296). Next attempt sees it; after `MAX_VR_HANGS=3` (10907) for
  VR-prefixed tasks, writes a FAIL record and stops spawning.

### Path 2 — phase VR fails

Validation FAIL → runner spawns `VR-fix-<phase>-<N>` (11140-11229) up
to `MAX_VR_FIX_ATTEMPTS=5`. After 5: logs "VR fix cap reached", does
NOT spawn anything; phase remains incomplete. Combined with
no-progress detector, leads to noop-exit → `feature_abandoned` event
→ STALLED.md (default strict-mode).

### Path 3 — REVIEW-CLEAN but runner-verify fails

Distinct fix path: `RV-fix-<phase>-<N>` (11231-11370) up to
`MAX_VR_FIX_ATTEMPTS=5`. After 5: same stall.

### Path 4 — CI loop

`CI_LOOP_MAX_ATTEMPTS=50` outer attempts, each with up to
`CI_LOCAL_MAX_ITERATIONS=20` local fix-validate cycles. Same job failing
`CI_REPEAT_FAILURE_THRESHOLD=5` consecutive times writes BLOCKED.md
(12466-12483). After 50 attempts: BLOCKED.md (12628-12634).

### Path 5 — E2E loop

Multiple nested caps. Per-iteration: planner → up to
`EXECUTOR_MAX_SPAWNS_PER_ITER=5` executors → diagnostic if blocker → fix
→ verify. Per-bug: `MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR=3` triggers
supervisor; `MAX_SUPERVISOR_RUNS=5` then escalation. Build path:
`BUILD_FIX_MAX_ATTEMPTS=10`.

### Possible silent-loop / runaway corners

1. **`max_runs=100` is per-feature, NOT total**: each new feature
   resets the counter. A 10-feature run can spend 1000 agent spawns.
2. **`max_consecutive_noop=20` × 5 seconds = ~100 seconds of "nothing
   happening" before exit** (10408, 11714). Not weeks, but real-time
   wall-clock not enforced beyond per-agent.
3. **The CI loop allows up to 50 × (20 local iter × ~2 sub-agents) = up
   to 2000 sub-agent spawns per CI task.** No aggregate token/dollar
   cap on the CI thread.
4. **The platform-init meta-fix path** (15041+) and the E2E supervisor
   path each have their own caps but no shared budget.
5. **`subprocess.run(..., timeout=600)` for runner-verify test
   commands** (11481): a wedged test that ignores SIGTERM keeps the
   runner blocked for 600s; this is single-threaded inside `_run_feature`,
   so the rest of the runner is paused while this fires.
6. **Connection-error retry loop has no cap**: if every retry hits a
   connection error but the circuit-breaker `cutoff` constantly slides,
   the breaker may trip, wait 5 min, and reset. No upper bound.
7. **Auto-grant capabilities (gh, mcp-*) loop**: if an agent keeps
   writing BLOCKED.md `[needs: gh]` over and over, the runner keeps
   granting and retrying with no cap. The implementer-prompt rule
   "GIT PUSH: Always push via HTTPS" depends on the agent following it.

---

## 5. Cost controls

### Model selection

Token pricing (3741-3745) — note this is the **runner's** in-process
estimator:

```
opus:   input $15  / output $75  / cache_read $1.50 / cache_create $18.75
sonnet: input $3   / output $15  / cache_read $0.30 / cache_create $3.75
haiku:  input $0.80 / output $4  / cache_read $0.08 / cache_create $1.00
```

Model assignment by role:

| Role | Model | Where |
|---|---|---|
| Task implementer | `opus` (default in `spawn_agent`, 3547) | implicit |
| Retry agent | `opus` (default) | 10785 |
| Validate (split flow) | `sonnet` unless test diff → `opus` | 11009-11013 |
| Review (split flow) | `opus` | 11020 |
| VR-fix | `opus` (default) | 11211 |
| RV-fix | `opus` (default) | 11354 |
| CI sub-agents | `opus` (default) | implicit (12128, 12299, etc.) |
| E2E planner | `opus` | per `_role_model("e2e-planner")` (8299) |
| E2E executor | `sonnet` | per cost-config |
| E2E verify | `sonnet` | per cost-config |
| E2E supervisor | `opus` | implicit |
| E2E research | `opus` | implicit |

`.specify/cost-config.json` (loaded via `_load_cost_config`, 8275-8298)
allows project-level overrides for: `executor_step_cap`,
`executor_wall_cap_s`, role-model assignments (`_role_model`), idle
budgets (`_role_idle_s`).

### Per-spawn caps

- Executor: 4 steps OR 600s per spawn, 5 spawns per E2E iteration.
- Watchdog idle + hard wall-clock caps per agent (§3 table).

### Aggregate caps

**There is no aggregate token or dollar budget kill-switch.** The runner:

- Counts tokens in each agent's `AgentSlot` (input_tokens,
  output_tokens, fresh / cache_read / cache_create breakdowns,
  3787-3800).
- Emits per-completion `task_complete`/`vr_complete` events with token
  totals to `run-log.jsonl` (12017-12033).
- Estimates cost per agent (`estimate_cost_usd`, 3758-3767).
- Displays per-agent cost in the TUI (`format_usage_compact`, 3781).

But there is **no global cost budget**, no "stop the run if we've spent
$X", no per-feature dollar cap. A runaway agent that legitimately
streams JSONL output (so the idle watchdog never fires) burns Opus
tokens at $15/M input until its hard 90-minute cap.

### Cost-discipline pressure (prompt-level only)

The `_build_cost_discipline_section` (17610) gives mandatory tool-tier
guidance to E2E agents. Enforcement is purely the agent reading and
complying — there is no runtime check that screenshots are tied to
findings. The prompt's "every screenshot must produce a finding" is a
norm, not a gate.

### `cost_report.py`

Post-hoc tool, not real-time. Walks `run-log.jsonl` files and reports
spend by model, by task prefix, and a phase×model matrix. Emits
"Effectiveness signals" comparing planner+executor cost vs legacy
explore cost, and the "Executor Opus%" target (should be 0%).

**Pricing mismatch**: `cost_report.py` uses opus
input=$5/output=$25/cache_read=$0.50/cache_create=$6.25 (lines 39-44),
while `parallel_runner.py` uses opus input=$15/output=$75/
cache_read=$1.50/cache_create=$18.75 (3742). The two will report
**very different** dollar figures for the same logs — `cost_report.py`
is consistently 3× lower. This looks like one file is on the 200k
context tier ($15/$75) and the other is on something else (the cost_report
comment says "standard ≤200K context", but the numbers don't match
public Anthropic pricing for Opus 4 in either tier). Either way, both
prices are hard-coded.

---

## 6. Observability

### Files written per spawn

- `logs/agent-{id}-{task_id}-{timestamp}.jsonl` — full stream-json
  transcript (every assistant message, tool_use, tool_result, result).
- `logs/agent-{id}-{task_id}-{timestamp}.stderr` — stderr capture.
- `logs/agent-{id}-{task_id}-{timestamp}.prompt.md` — sidecar prompt
  file the agent was told to Read.
- `logs/agent-{id}-{task_id}-{timestamp}.hang.md` — only on watchdog
  kill; includes last 30 log lines + bg process snapshot.

### Files written per task/phase

- `specs/<feature>/run-log.jsonl` — structured events. Event types:
  `session_start`, `task_spawn`, `task_complete`, `vr_spawn`,
  `vr_complete`, `vr_fix_spawn`, `rv_fix_spawn`, `rv_fix_complete`,
  `runner_verify`, `runner_verify_retry`, `rv_no_progress_stall`,
  `feature_complete`, `feature_abandoned`, `vr_auto_clean`,
  `platform_init_fail`, `platform_fix_claim`,
  `platform_meta_fix_spawn`, `pre_e2e_gate_*`, `agent_hang_kill`,
  `task-deps`, etc.
- `specs/<feature>/attempts/{task_id}.jsonl` — per-task attempt
  summaries (`write_attempt_record`, 4381+).
- `specs/<feature>/reasoning/{seq}-{ts}-{kind}-{task_id}-agent{id}.md`
  — extracted `## Reasoning` section per spawn.
- `specs/<feature>/validate/<phase>/{N}.md` — validation records.
- `specs/<feature>/validate/<phase>/review-{N}.md` — review records.
- `specs/<feature>/validate/<phase>/runner-verified.json` — runner's
  deterministic re-verification result.
- `specs/<feature>/validate/<phase>/verification.json` — review
  agent's structured evidence per task.
- `specs/<feature>/claims/completion-{task_id}.json` — agent's
  self-claim.
- `specs/<feature>/claims/rejection-{task_id}.md` — verifier's
  rejection.
- `ci-debug/<task_id>/attempt-*-{logs,diagnosis,local-N,ci-result}.md/json`
  — full CI history.
- `test/e2e/<feature>/{findings.json, progress.md, plan.md,
  handoff.md, blocker.md, executor/, bugs/<BUG-ID>/...}` — E2E artifacts.

### TUI

`TUI._render_loop` (1143+) repaints every 500ms. Shows the dependency
graph (with running ◉ / complete ● / failed ✗ / blocked ⊗ symbols), a
"Scheduler: {activity}" line when no agents are running (with age,
yellow if >30s), and per-agent panes with live stream-json output
tails. `set_activity()` (1124) is called at every main-loop decision
point: "scanning for work", "spawning agent #N", "runner-verify:
{phase} — running `cmd`", "circuit breaker — cooling down for Nm", etc.
Solid coverage.

### Headless mode

`HeadlessLogger` (1295+) writes runner messages to a log file. Same
event stream goes to `run-log.jsonl` regardless of TUI/headless.

### Debug recipe for a failed task (inferable)

1. Open `specs/<feature>/run-log.jsonl`, grep for the task_id, look
   at `task_spawn` and `task_complete` (or absence of `task_complete`).
2. Read the latest `logs/agent-<id>-<task_id>-*.jsonl` — the full
   stream-json — to see what tools the agent called and what the
   result was.
3. Look for `agent-<id>-<task_id>-*.hang.md` for watchdog kills.
4. Check `specs/<feature>/attempts/<task_id>.jsonl` for the rolled-up
   per-attempt summary.
5. Check `specs/<feature>/reasoning/*-{task_id}-*.md` for the
   `## Reasoning` writeup.
6. For phase issues: `specs/<feature>/validate/<phase>/*.md` and
   `verification.json` / `runner-verified.json`.

### Gaps in observability

- **No global cost dashboard at runtime.** TUI shows per-agent cost
  (`format_usage_compact`), but not cumulative session cost.
- **No alerts on token spike.** A single agent can stream 500k input
  tokens before completing without triggering any guardrail (it's
  technically "making progress" if it keeps emitting events).
- **`cost_report.py` and the live TUI disagree on Opus pricing** (§5).
- **`run-log.jsonl` is append-only with no rotation.** A multi-day
  multi-feature run produces a single growing file; the runner reads it
  for `_no_progress_for_phase` etc. via O(file) scan every iteration.

---

## 7. Anti-fake-work mechanisms

### Code-enforced

1. **`verification.json` gating** (868-898): REVIEW-CLEAN claims are
   rejected if `verification.json` lacks per-task `commands_run`,
   `artifacts_inspected`, AND `lie_check` fields. Forces the review
   agent to record actual substrate it inspected.
2. **Runner-side independent test re-run** (11428-11502): the runner
   itself executes `test_cmds` after REVIEW-CLEAN and writes the
   outcome to `runner-verified.json`. Bypasses agent self-reporting.
3. **Proof-artifact scan** (11529-11556): every test-logs JSON with
   `status` + `executed` must be `status="pass"` AND `executed>0`,
   regardless of command exit code.
4. **Skip scan** (11593-11623): any skipped test in the test summary
   is a FAIL, even if the test runner exited 0.
5. **Coverage-matrix scan** (11563-11584): added/modified routes must
   be referenced by tests in the diff.
6. **Stale-artifact poisoning prevention** (11450): captures
   `verify_start_mtime` and filters proof-artifact / skip scans to
   files written ≥ that time — old archives can't pass a fresh
   verification.
7. **Auto-cleanup of stale `runner-verified.json` failures on
   startup** (10367-10405): a `passed: false` rv_file from a prior
   session is unlinked along with `review-*.md`, forcing the phase
   back through VR.
8. **No-progress detector** (`_no_progress_for_phase`, 9873): if the
   last 3 RV cycles all fail with identical command signatures, refuses
   to spawn another fix agent — the agents claim to be fixing but the
   substrate disagrees.
9. **Sanity-check before CI finalize** (9637-9667 in
   `build_ci_finalize_prompt`): the finalize agent itself is required
   to cross-reference CI test counts against source-file counts and
   bail out with `sanity-check-fail.md` if they diverge.
10. **`verify.sh` for E2E bugs** (18587-18634): each bug requires a
    scripted verifier; the runner executes it (`_run_scripted_verify_phase`,
    8444) before deciding whether to spawn the full verify agent.
11. **Hang-diagnosis file injection** (4054-4085): a killed agent's
    hang.md is surfaced to the next attempt's prompt explicitly — "do
    not repeat that invocation."
12. **Untrusted-code capability stripping** (3606-3616, §3): tasks
    that install packages don't get `gh` tokens.
13. **Watchdog 0-CPU bg-bash detection** (11770-11820): differentiates
    "agent is genuinely waiting" from "background command is wedged."

### Prompt-level

All of §2.5 (validate-only prompt's STANCE: ADVERSARIAL block) and
§2.6 (review-only prompt's STANCE: ADVERSARIAL block) explicitly
direct the agent to treat prior claims as "advertising," re-derive
from substrate, and enumerate specific failure shapes to look for
(silent-skip-with-green-claim, pattern-matched assertions, coverage
shortcut, test ran with failure mode disabled, anchored on prior
records). The CI finalize prompt's Step 0 (sanity-check CI results)
enumerates specific anti-patterns (zero tests, phantom passes,
silent tool failures).

### Gaps

- **No diff-vs-claim check**: nothing compares what the implementer
  agent's `completion-{task.id}.json` `files_modified` lists against
  the actual `git diff` for that commit. An agent could claim to have
  modified 5 files but only modify 1; the only catch is the next phase
  validation noticing missing behavior.
- **`mcp_interactions: 0`** in the claim schema (1802) — the agent
  fills this in; never verified against the stream-json log's actual
  tool-use count.
- **Reasoning section quality is unmeasured**: the runner extracts and
  archives it, but no automatic check that "What I did" matches actual
  diff, or that "Confidence & risks" isn't empty.
- **Tests-the-spec doctrine is prompt-only**: 1769 says "No stubs in
  production code"; runtime check 11531-11556 only catches stubs that
  break a build/test, not legitimate-looking hardcoded sentinels that
  pass tests because the tests also stub.
- **No re-execute of agent's `commands_run` claim**: the implementer
  writes `commands_run: [{command, exit_code: 0}]`; the runner trusts
  it. (The runner-side verify re-executes a different set — the
  project's gate commands — but doesn't replay the agent's claimed
  command list.)

---

## 8. Smells, gaps, and stress-fragility

### 8.1 Pricing tables disagree across files

`parallel_runner.py:3741-3745` uses Opus $15/$75 input/output; cache
$1.50/$18.75. `cost_report.py:38-57` uses Opus $5/$25 input/output;
cache $0.50/$6.25. The TUI live cost (~3× higher than the post-hoc
report) and the historical reports will tell different stories. Pick
one source of truth.

### 8.2 Monolithic class

`Runner` is ~9,800 LOC inside one class. `_run_feature` alone runs
from 10293 to ~12087. Adding a new agent kind requires editing in
multiple places (the main loop, `_poll_agents`, the prompt builder
list, the event-name list, the cost_report classifier). High risk of
state inconsistencies as more cases pile up.

### 8.3 `max_runs=100` is per-feature, not total

CLI help text (19630) implies it's a global cap. It isn't — see §4.
For an `--and-later` invocation across N specs, the runner can spawn
100×N agents.

### 8.4 Connection-error retry loop unbounded

Per §4: the circuit breaker waits 5 min after 3 connection errors in
10 min, then resumes. Forever. A persistent network problem can
result in days of agent-launch attempts with no escalation. Suggested
fix: count total cooldowns and escalate to BLOCKED.md after N.

### 8.5 `subprocess.run(..., timeout=600)` blocks main thread

11479-11521. The runner is single-threaded for the main loop; while
runner-verify is running a test, no other phase makes progress, no
other agent gets polled. For a multi-spec or many-phase run this is
significant. A wedged 10-minute test is a 10-minute pause.

### 8.6 `_run_feature` does file scans every iteration

`_recent_runner_verify_failures` (9839-9871) and
`_rv_fix_attempt_count` (9902-9953) full-scan `run-log.jsonl` line by
line every main-loop tick. A long-running feature accumulates events;
each scan is O(n). No index, no rotation, no cache.

### 8.7 `_agent_done_tasks` & `_recently_finished` lifecycle is fragile

The runner has *three* concurrent views of a finished agent:
`self.agents` (still pending poll), `self._recently_finished` (just
removed, kept for main-loop drains), and `_agent_done_tasks` (set of
task IDs to safety-net mark `[x]`). Comments at 10498, 10538-10549,
11109-11134 describe past bugs where finished agents were invisible
to the main loop. The fix is reasonable, but the same lifecycle is
repeated in `_run_ci_loop` and `_run_e2e_loop` threads with subtly
different invariants. Race-prone.

### 8.8 "Do NOT use the Skill tool" is everywhere — but the runner depends on agents NOT loading skills

This is enforced purely by prompt text (1887-1888 et al.). If a model
ever silently auto-loads a routed skill (e.g. spec-kit), the
agent-in-skill recursion is undefined. The harness has no programmatic
block.

### 8.9 Hardcoded constants that should be config

The §3 table has ~30 named constants. Only a handful are
config-readable (executor caps via `.specify/cost-config.json`,
role-model via `_role_model`). The rest are buried as inline
`MAX_*` ints inside method bodies. Things like
`MAX_VR_FIX_ATTEMPTS = 5` at line 11139 (inside `_run_feature`) and
again at 11265 — two copies of the same constant.

### 8.10 Reasoning appendix bloats every prompt

Adds ~1KB to every spawn's prompt file. With 100s of spawns, that's
fine in absolute terms, but it also expands the prompt-file hash key —
every spawn's prompt file is unique by path so cache hits are
agent-Read-based, not prompt-text-based. The appendix is on every
prompt regardless of role; the meta-prompts that already produce
reasoning are double-instrumented (a reasoning section is added on
top of an existing structured-output mandate).

### 8.11 Contradictions / awkward overlap

- "Do NOT skip ahead" vs CI-fix prompt's "Skip steps gated on CI-only
  secrets" (9495). Same word, different scope. Confusing.
- The validate-only prompt's STANCE: ADVERSARIAL pre-amble (2422) and
  the combined validate+review prompt's "Step 6 — Stub detection"
  (2942) overlap in intent but use different vocabularies.
- The implementer prompt at 1834-1835 specifically authorizes marking
  a task complete during connection-error retries even if tests
  haven't run, then 1897 forbids any completion claim without exit-0
  commands. The connection-error escape clause supersedes 1897 — but
  the agent reading these in order may not see it that way.
- The CI-fix prompt explicitly forbids `npm install` patterns'
  capability injection (3606-3616 security strip), but the prompt
  itself says "If a tool is not installed, install it" in the
  combined validate+review prompt at 2912-2917. An agent that
  follows that latter instruction loses its `gh` capability without
  warning — the [SECURITY] log message goes to stderr (3614), not to
  the prompt or to the agent. Silent failure mode.

### 8.12 E2E executor cost-section says "no grace period" then
relies on agent compliance

17666-17669: "There is no grace period. Spawn 1 call 1 follows this
rule. If you reach for a snapshot or vision capture and you're not
about to file a bug, use the cheap tool instead." But the only
enforcement is the cost_report.py post-hoc `_opus_pct("e2e-executor")`
target check (cost_report.py:418), and the
`BrowserDriver.cheap_vs_expensive_calls` referenced at 18099 (not
read here, but likely a soft metric for prompt back-pressure). An
executor that ignores the prompt sees no consequence within the
session.

### 8.13 `flake.nix` re-exec drains all agents

10433-10474: if any agent edits flake.nix, the runner drains all
in-flight agents and `os.execvp`s into a new shell. Drain timeout is
the agent's own hang budgets, so a stuck agent at the time of a flake
edit blocks the restart for up to 90 minutes. There's no force-kill
escalation in that path — only the watchdog firing on its own
schedule.

### 8.14 Sandbox excludes `~/.claude/` but mounts
`~/.claude/.credentials.json` conditionally (3438-3453)

This is intentional (short-lived OAuth) but the file is bind-mounted
read-only — if it expires mid-spawn, the agent sees an auth_error and
the entire run terminates (12053-12056). No graceful re-auth. A
long-running feature that started near token-expiry can lose hours of
work.

### 8.15 `read_attempt_history` returns session-scoped records
(4585-4609)

Comment says "This prevents old failures from a previous runner
invocation from poisoning retry/failure decisions after the user
intervenes." But the platform-init meta-fix path
(`_count_recent_platform_failures`, 5185-5255) deliberately reads
cross-session events from the run log. So the runner has two
contradictory policies for "are prior failures still relevant" depending
on which subsystem you're in. Could cause surprising behavior when a
user intervenes — task path forgets, platform path remembers.

### 8.16 Stripped capabilities only log to stderr, agent never knows

`spawn_agent`, 3613-3615:

```python
print(f"[SECURITY] Stripping capabilities {stripped} from {task.id} — "
      f"task runs untrusted code", file=_sys.stderr)
```

Agent sees neither this warning nor an explanation; it just finds
`gh` missing from PATH and probably writes BLOCKED.md, which (since
the same pattern still matches) gets re-spawned without the cap
forever. Loop is bounded only by the noop-timeout.

### 8.17 `_check_untrusted_code_risk` is regex-on-description (5137-5143)

A task description that mentions "DO NOT run npm install" matches.
The function is a substring search, not semantic. False positives are
silent.

### 8.18 Multiple "Do NOT modify the task list — the runner manages
task status" rules in fix prompts, while the implementer prompt mandates
the agent mark its own task `[x]`

VR-fix says don't modify tasks.md (1987); implementer requires marking
`[x]` (1805, 1896). If a fix agent accidentally marks a task `[x]`, the
runner has a safety net (`_agent_done_tasks`, 10483-10493) but the
inverse — an implementer that forgets — is also covered by the same
safety net. The two safety nets only fire on the runner's own
inference and don't reconcile with VR-fix activity. Subtle but
probably harmless.

### 8.19 No retention policy

`logs/` accumulates one JSONL + stderr + prompt file per spawn. After
1000 spawns over a multi-day run, that's 3000 files in one directory.
`specs/<feature>/reasoning/` also grows unbounded. No cleanup.

### 8.20 The "Reasoning" appendix's "Prompt feedback — missing"
section is a self-improving feedback channel — but I see no consumer

4426-4432 asks the agent to list "what concrete info, if the prompt
generator had fed it in automatically, would have let you finish faster."
This is excellent introspection data, but there's no code that reads
the resulting reasoning files to mutate prompts. So agents are paying
output tokens to write feedback that may only be read by humans
post-mortem. (The cost is probably small.)

### 8.21 `--max-parallel` defaults to 3 (19634)

For a user trying to "reduce time-per-feature", 3 is conservative.
There's no auto-tuning based on token budget or rate limits — if the
account can handle 10 concurrent agents, the user has to know to set
that explicitly. Combined with the per-feature `max_runs=100`, a
heavily-parallel run isn't possible without CLI flags.

---

## Closing note

The runner is a serious, well-instrumented orchestrator with many
explicit anti-fake-work mechanisms — adversarial validate/review
stances, `verification.json` substrate gating, runner-side independent
test re-execution, proof-artifact and skip scans, no-progress
detector, and detailed event logging. The dominant smells are
(a) hardcoded pricing/constants that disagree between files,
(b) a single monolithic 19k-LOC file with one ~10k-LOC class,
(c) no aggregate cost/budget kill-switch beyond per-spawn caps,
(d) several loops (connection-error retry, BLOCKED-cap-grant) without
upper bounds, and (e) heavy reliance on prompt text rather than code
to enforce critical rules (no Skill tool, no curl substitutes, every
screenshot must produce a finding). The substrate-vs-claim verification
discipline is the strongest defense against fake work, and it's the
most thoroughly implemented piece.
