# Spec-kit rule matrix

Every rule and guardrail extracted from the wrapper docs, reference docs, and `parallel_runner.py`. Tagged with enforcement strength, rationalization payoff, and preset applicability.

## Legend

**Enforcement strength** (highest → lowest):

| Tag | Meaning |
|---|---|
| **CODE** | `parallel_runner.py` or a shipped script mechanically refuses on violation. Not bypassable. |
| **TEMPLATE** | A shipped test reporter or generated script exits non-zero. Bypassable only by editing the template. |
| **CI** | A workflow file gated by `if: failure() == false` or equivalent. Bypassable by editing the workflow. |
| **VALIDATOR** | The validate-review agent is *told* to enforce; itself an agent and itself fallible. |
| **PROMPT** | The agent's prompt says MUST. Pure prose. Agent compliance only. |
| **CONVENTION** | Documented somewhere but not even in a prompt — relies on reader to find it. |

**Rationalization payoff** — how much work does skipping save the agent?

| Tag | Meaning |
|---|---|
| **HIGH** | Hours to days of work avoided. The kind of thing an agent under load skips. |
| **MED** | 10 min to an hour of work avoided. Skippable when context is tight. |
| **LOW** | Seconds to minutes. Skipping is rarely worth it. |
| **NEG** | Skipping makes things harder, not easier (no rationalization incentive). |

**Preset applicability** — which presets the rule binds in.

| Tag | Meaning |
|---|---|
| **ALL** | Every preset. |
| **NON-POC** | local, library, extension, public, enterprise. POC skips. |
| **PROD** | public, enterprise. Local/library/extension may skip. |
| **ENT** | enterprise only. |
| **PLATFORM** | Only when project targets Android/iOS/web/desktop. |
| **CONDITIONAL** | Depends on project shape (has UI / has DB / has API / etc.). |

---

## Section 1 — Anti-fake-work / verification / proof discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 1.1 | Every gating step produces JSON proof artifact with `status`, `executed`, `passed`, `failed`, `skipped`, `reason_if_zero` | `proof-discipline.md:25-37` | CODE (runner refuses missing fields) | HIGH | NON-POC |
| 1.2 | `executed=0` is always FAIL regardless of exit code | `proof-discipline.md:30`, `parallel_runner.py:11529-11556` | CODE | HIGH | NON-POC |
| 1.3 | `skip > 0` is always FAIL regardless of reason | `testing.md:138`, `parallel_runner.py:11593-11623`, reporter templates | CODE + TEMPLATE | HIGH | NON-POC |
| 1.4 | Non-vacuous: `pass + fail > 0` per test run | `testing.md:137`, `EXAMPLE-OUTPUT.md:153-158`, reporter templates | TEMPLATE | HIGH | NON-POC |
| 1.5 | Skip without runs-in-the-gate replacement = FAIL | `proof-discipline.md:39-48` | CODE (skip count) | HIGH | NON-POC |
| 1.6 | `--allow-skip` ignored under CI/pre-pr | `proof-discipline.md:48` | PROMPT | MED | NON-POC |
| 1.7 | Cross-checkable expected count file at config-load time; verifier asserts `executed >= expected` | `proof-discipline.md:50-60` | PROMPT (project-side wrapper must implement) | HIGH | ENT |
| 1.8 | Build artifacts checked against manifest | `proof-discipline.md:62-71` | PROMPT (project-side) | MED | NON-POC |
| 1.9 | Coverage matrix: every new route has a test | `proof-discipline.md:73-79`, `parallel_runner.py:11563-11584` | CODE | HIGH | NON-POC |
| 1.10 | Verifier reads artifacts NOT claims — strip completion JSONs from verifier prompt | `proof-discipline.md:81-97` | CODE (prompt builder) | HIGH | NON-POC |
| 1.11 | Verifier prompt MUST be adversarial — opens with "find the lie" | `proof-discipline.md:99-112`, `parallel_runner.py:2422-2433, 2594-2601` | CODE (prompt builder) | MED | NON-POC |
| 1.12 | `verification.json` schema with per-task `commands_run`, `artifacts_inspected`, `lie_check`, `verdict`, `evidence` | `proof-discipline.md:114-143`, `parallel_runner.py:868-898` | CODE (refuses missing fields) | HIGH | NON-POC |
| 1.13 | Runner refuses phase when any proof artifact has `executed=0` for code the artifact should cover | `proof-discipline.md:145-149`, `parallel_runner.py:11529` | CODE | HIGH | NON-POC |
| 1.14 | Stale-artifact poisoning prevention: `verify_start_mtime` filter on proof / skip scans | `parallel_runner.py:11450` | CODE | NEG | NON-POC |
| 1.15 | Stale `runner-verified.json` failures unlinked on startup; review-*.md cleared | `parallel_runner.py:10367-10405` | CODE | NEG | NON-POC |
| 1.16 | Runner independently re-executes test commands after REVIEW-CLEAN | `parallel_runner.py:11428-11502` | CODE | HIGH | NON-POC |
| 1.17 | No-progress detector: 3 RV cycles with identical command signatures → stop | `parallel_runner.py:9873-9890, 11284-11313` | CODE | NEG | NON-POC |
| 1.18 | Claim format MUST have `task_id`, `status`, `commands_run`, `files_created`, `files_modified`, `screenshots`, `mcp_interactions` | `verification.md:22-48`, `IC-AGENT-014` (`agent-file-schemas.md:410-435`) | CODE (parsing) | LOW | NON-POC |
| 1.19 | Runner re-executes commands from claim; exit codes must match | `verification.md:50-54` | CODE (partial — see gap below) | HIGH | NON-POC |
| 1.20 | MCP exploration tasks require ≥1 screenshot, `mcp_interactions > 0`, live evidence | `verification.md:58-62` | CODE (parsing claim) | MED | PLATFORM |
| 1.21 | `**Verify**:` field on task: runner extracts and executes the command | `verification.md:64-68` | CODE | LOW | NON-POC |
| 1.22 | Scripted task verification — `bash -n` not sufficient | `verification.md:70-72` | PROMPT | MED | NON-POC |
| 1.23 | Agent MUST NOT edit `tasks.md` checkboxes — runner does it | `verification.md:81-93` | PROMPT (safety net at `parallel_runner.py:10483-10493`) | LOW | NON-POC |
| 1.24 | Sanity-check before CI finalize: cross-reference test counts against source files | `parallel_runner.py:9637-9667` | PROMPT (agent does the check) | MED | NON-POC |
| 1.25 | `verify.sh` MANDATORY when closing E2E bug | `fix-agent-playbook.md:195-238`, `mcp-e2e-core.md:59-68`, `IC-AGENT-016b` | CODE (runner executes) | HIGH | PLATFORM |
| 1.26 | Hang-diagnosis file (`.hang.md`) injected into next attempt's prompt | `parallel_runner.py:4054-4085` | CODE | NEG | NON-POC |
| 1.27 | Watchdog detects 0-CPU background bash for 5 min | `parallel_runner.py:11728-11821` | CODE | NEG | NON-POC |
| 1.28 | Trivial-diff fast-path: phase with only docs/configs/non-source diff → auto REVIEW-CLEAN | `parallel_runner.py:10952-10977` | CODE | NEG (cost saver) | NON-POC |
| 1.29 | Adversarial review stance: "validate agent's PASS is not trustable" | `parallel_runner.py:2594-2601` | CODE (prompt builder) | MED | NON-POC |
| 1.30 | Mtime check before claiming STILL_BROKEN — service logs older than fix commit = debugging a ghost | `fix-agent-playbook.md:116-136` | PROMPT | MED | PLATFORM |
| 1.31 | Cold re-run verification — "exit 0 with port-already-up guard is not proof" | `fix-agent-playbook.md:101-114` | PROMPT | MED | NON-POC |
| 1.32 | Repeat-same-root-cause detection: 2 consecutive `verified: false` claims with same root cause → BLOCKED.md | `agent-file-schemas.md:514`, runner code | CODE | LOW | NON-POC |

---

## Section 2 — Anti-fake-work GAPS (claimed but not enforced)

| # | Gap | Source | Should-be-presets |
|---|---|---|---|
| 2.1 | No diff-vs-claim verification: agent's `files_modified` not compared to `git diff` | runner audit §7 | NON-POC |
| 2.2 | `mcp_interactions: N` self-reported; never reconciled against stream-json tool-use count | runner audit §7 | PLATFORM |
| 2.3 | Reasoning section quality unmeasured — "What I did" not compared to actual diff | runner audit §7 | NON-POC |
| 2.4 | `claims/completion-{TASK_ID}.json` `commands_run` not replayed by runner (the runner replays a *different* set: project gate commands) | runner audit §7 | NON-POC |
| 2.5 | Stub-detection prompt-only — hardcoded sentinel that passes tests because tests also stub is invisible | runner audit §7 | NON-POC |
| 2.6 | No wrapper-script linter — `run-e2e.sh` that silently `exit 0`s passes proof-discipline gate | reference audit §gap A | NON-POC |
| 2.7 | Adversarial-verifier-prompt depends on `_verifier_prompt()` correctness — no test of the runner itself | reference audit §gap B | n/a (system-side) |

---

## Section 3 — Testing tier discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 3.1 | Unit / integration / E2E tiers run at every phase boundary | `testing.md:3-13` | VALIDATOR | HIGH | NON-POC |
| 3.2 | Unit = in-process, no network/DB; integration = real services, no UI runtime; E2E = full stack + platform runtime | `testing.md:39-43` | PROMPT | HIGH | NON-POC |
| 3.3 | Integration tests NEVER touch emulator/simulator/browser | `testing.md:47` | PROMPT | MED | NON-POC |
| 3.4 | E2E tests NEVER substitute for integration tests | `testing.md:48` | PROMPT | HIGH | NON-POC |
| 3.5 | No mocking inside a tier's boundary | `testing.md:50` | PROMPT | HIGH | NON-POC |
| 3.6 | Every E2E flow has a user-flow integration mirror | `testing.md:53` | PROMPT | HIGH | NON-POC |
| 3.7 | Pre-E2E gate: setup.sh → write env.sh → run integration tests | `testing.md:57-67`, `parallel_runner.py` (pre-e2e gate) | CODE | HIGH | PLATFORM |
| 3.8 | Real servers, real processes, real DBs — mock only what requires human interaction | `testing.md:86-94` | PROMPT | HIGH | NON-POC |
| 3.9 | External-process boundary tests: spawn real binary, real JSON, real pipes | `testing.md:96-110` | PROMPT | HIGH | CONDITIONAL |
| 3.10 | Structured test output: `test-logs/summary.json` + `failures/<name>.log` | `testing.md:112-138`, `EXAMPLE-OUTPUT.md` | TEMPLATE | LOW | NON-POC |
| 3.11 | Shared-runtime safety: 10 authoring rules (random IDs, no first-row reads, scoped cleanup, etc.) | `testing.md:224-262` | PROMPT | HIGH | NON-POC |
| 3.12 | Shared-runtime review: 10 detection heuristics | `testing.md:264-292` | VALIDATOR | HIGH | NON-POC |
| 3.13 | Code coverage mandatory for every language/suite, terminal + file report | `testing.md:294-325`, `validate-review.md:25,37-45` | VALIDATOR | MED | NON-POC |
| 3.14 | User-flow integration tests required per primary user flow | `testing.md:352-501` | PROMPT | HIGH | NON-POC |
| 3.15 | 10 design patterns for user-flow tests (audio pipeline, process lifecycle, etc.) | `testing.md:380-489` | PROMPT | HIGH | CONDITIONAL |
| 3.16 | Race detection mandatory in CI for concurrent code (`-race`, Miri/Loom, RacerD) | `testing.md:523-595` | CI | HIGH | NON-POC |
| 3.17 | Adversarial flow tests: every security boundary needs ≥1 rogue-actor test | `testing.md:597-651` | PROMPT | HIGH | PROD |
| 3.18 | Hardware-dependent tests: explicit coverage gap docs, CI tier strategy | `testing.md:653-721` | PROMPT | HIGH | PLATFORM |
| 3.19 | Performance/benchmark: spec budgets become p95 assertion tests | `testing.md:723-819` | PROMPT | HIGH | ENT |
| 3.20 | benchstat regression thresholds in CI | `testing.md:723-819` | CI (if implemented) | MED | ENT |
| 3.21 | Real-runtime E2E mandatory for platform-targeting projects | `testing.md:821-825`, `e2e-runtime.md` | PROMPT | HIGH | PLATFORM |
| 3.22 | E2E test harness decomposition: artifact / env / bypasses / helpers / test = separate tasks | `testing.md:827-857` | PROMPT | MED | PLATFORM |
| 3.23 | Fix-validate loop per phase; fresh context per fix; 10-attempt cap → BLOCKED.md | `testing.md:859-877`, runner code | CODE | LOW | NON-POC |
| 3.24 | File-name convention load-bearing: `*.integration.test.ts` vs `*.test.ts` vs `*.e2e.test.ts` | `testing.md` § "Test tier taxonomy" | CONVENTION | MED | NON-POC |
| 3.25 | When test exposes real bug, fix code not test (loosening assertions = FAIL) | `testing.md:33` | VALIDATOR | HIGH | NON-POC |
| 3.26 | No Robolectric / jsdom / mock runtime substitution for real platform E2E | `e2e-runtime.md:25-36`, `validate-review.md:17` | PROMPT | HIGH | PLATFORM |
| 3.27 | Side-by-side runtimes, NOT nested (CI has no nested KVM) | `e2e-runtime.md:37-66` | PROMPT | MED | PLATFORM |
| 3.28 | Readiness checks per runtime with explicit timeouts | `e2e-runtime.md:68-106` | PROMPT | MED | PLATFORM |
| 3.29 | Test bypass mechanisms for hardware features must be debug-build-only, verified absent in release | `e2e-runtime.md:108-126` | PROMPT | HIGH | PLATFORM |
| 3.30 | Single-runtime parallelism constraint: don't `[P]` tasks sharing one emulator | `e2e-runtime.md:266-279` | CODE (scheduler), PROMPT | LOW | PLATFORM |
| 3.31 | Flakiness handling: retry 2-3x, generous timeouts 2-3x expected, explicit waits never `sleep`, idempotent setup | `e2e-runtime.md:282-316` | PROMPT | MED | PLATFORM |
| 3.32 | `test/e2e/setup.sh` + `teardown.sh` idempotent; writes `env.sh` | `e2e-runtime.md:377-450` | CODE (runner calls if exists) | MED | PLATFORM |
| 3.33 | `adb reverse` for Android host-port bridging — gated on `E2E_WANT_EMULATOR=1`, reapplied every run | `e2e-runtime.md:434-453` | CONVENTION | MED | PLATFORM |
| 3.34 | One screen/flow per task — fresh context per agent | `mcp-e2e-core.md:441-466` | PROMPT | NEG (cost saver) | PLATFORM |
| 3.35 | Regression spec MUST be behavioral (state transitions, side effects), NOT visual/render | `mcp-e2e-core.md:129-155` | PROMPT | HIGH | PLATFORM |
| 3.36 | Regression spec first-line signature `// regression for <TASK_ID>` | `mcp-e2e-core.md:279-313`, `mcp-e2e-web.md:102-111`, `mcp-e2e-android.md:58-101` | CODE (runner parses) | LOW | PLATFORM |
| 3.37 | MCP-driven exploration + scripted E2E are complementary, not competing | `e2e-runtime.md:501-512` | PROMPT | MED | PLATFORM |
| 3.38 | Post-loop regression check: full test suite after E2E loop | `e2e-runtime.md:524-535`, `mcp-e2e-core.md:120-127` | CODE | LOW | PLATFORM |

---

## Section 4 — Cost / model / token discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 4.1 | Role→model mapping: planner/diagnostic/supervisor/research = Opus; executor/fix/verify/crash-fix/build-fix = Sonnet | `cost-guardrails.md:27-39`, `parallel_runner.py:_role_model()` | CODE | NEG | ALL |
| 4.2 | Validate agent: Sonnet by default; Opus when diff touches test files | `parallel_runner.py:11009-11013` | CODE | NEG | NON-POC |
| 4.3 | Review agent: Opus | `parallel_runner.py:11020` | CODE | NEG | NON-POC |
| 4.4 | Hang budgets per role: planner 8m, executor 8m, fix 12m, verify 8m, build/crash-fix 20m; global hard cap 120m | `cost-guardrails.md:44-61`, `parallel_runner.py:AGENT_HARD_TIMEOUT_S` | CODE | NEG | ALL |
| 4.5 | Executor step cap: max 4 plan steps OR 10 min wall, then handoff + exit | `cost-guardrails.md:64-80`, `parallel_runner.py:EXECUTOR_STEP_CAP_PER_SPAWN/EXECUTOR_WALL_CAP_S` | CODE | NEG | PLATFORM |
| 4.6 | `EXECUTOR_MAX_SPAWNS_PER_ITER=5` | `cost-guardrails.md:72`, `parallel_runner.py:8231` | CODE | NEG | PLATFORM |
| 4.7 | Work preservation on hang-kill: write `handoff-spawn-N.md` with `Status: PARTIAL` | `cost-guardrails.md:56-60` | CODE | NEG | PLATFORM |
| 4.8 | `browser_evaluate` (500B) default; `browser_snapshot` (~330KB) fallback; `browser_take_screenshot` evidence-only | `cost-guardrails.md:136-167`, `mcp-e2e-web.md:9-42` | PROMPT | HIGH | PLATFORM |
| 4.9 | State-Tool no-vision default (Android); vision only for bug evidence; every vision call produces a finding | `cost-guardrails.md`, `mcp-e2e-android.md:10-35` | PROMPT (env var default) | HIGH | PLATFORM |
| 4.10 | 20-screenshot cap per session (Android) | `mcp-e2e-android.md:33-39` | PROMPT | MED | PLATFORM |
| 4.11 | 15-screenshot cap per verify session | runner audit §2.11 | PROMPT | MED | PLATFORM |
| 4.12 | MCP env defaults: `MCP_PREFER_SNAPSHOT`, `MCP_BROWSER_NO_AUTO_SCREENSHOT`, `MCP_ANDROID_DEFAULT_NO_VISION` | `mcp-e2e-core.md:426-440` | CODE (injected by runner) | NEG | PLATFORM |
| 4.13 | Playwright MCP flags: `--snapshot-mode none`, `--console-level error` | `cost-guardrails.md:169-181` | CODE (config writer) | NEG | PLATFORM |
| 4.14 | Page manifests: stable selectors at `specs/<feature>/validate/e2e/page-manifest/<route>.json` | `cost-guardrails.md:206-213`, `mcp-e2e-web.md:57-100` | PROMPT | MED | PLATFORM |
| 4.15 | Reference injection scoping: CLAUDE.md only for general-purpose roles; index.md only for general implementation agents; mcp-e2e split by platform | `cost-guardrails.md:183-204` | CODE (prompt builder) | NEG | ALL |
| 4.16 | NEVER inline reference content into prompt body — read by absolute path for cache hits | `cost-reporting.md:86-106` | CONVENTION (programmer-side discipline) | NEG (cost saver) | ALL |
| 4.17 | Tier-1 path lists hardcoded per role; do NOT build from runtime state | `cost-reporting.md:95` | CONVENTION | NEG | ALL |
| 4.18 | Editing a referenced file mid-run breaks cache_read → cache_create on next spawn | `cost-reporting.md:103` | CONVENTION | NEG | ALL |
| 4.19 | Effectiveness targets: Executor Opus% = 0, Verify Opus% = 0 | `cost-reporting.md:58-60` | (cost_report.py post-hoc) | LOW | ALL |
| 4.20 | `code-review-graph` exclude rules: project-scaffolding / vendored / never-edited dirs | `cost-guardrails.md:215-230` | CONVENTION | LOW | ALL |
| 4.21 | `.specify/cost-config.json` override schema for role models, hang budgets, caps | `cost-guardrails.md:232-252` | CODE (read on startup) | NEG | ALL |
| 4.22 | Curl/wget NOT a substitute for E2E — only pre-flight or response cross-check | `fix-agent-playbook.md:168-180` | PROMPT | HIGH | PLATFORM |
| 4.23 | Curl to admin API ALLOWED for state assertions (not UI actions) | `mcp-e2e-core.md:239-261` | PROMPT | NEG | PLATFORM |
| 4.24 | Skip rebuild when no changes in E2E loop | `mcp-e2e-core.md:271-277` | CODE | NEG | PLATFORM |
| 4.25 | Crash recovery: context overflow recoverable; MCP/auth = STOP | `mcp-e2e-core.md:263-269` | CODE | NEG | PLATFORM |

---

## Section 5 — Cost / model GAPS

| # | Gap | Source | Should-be-presets |
|---|---|---|---|
| 5.1 | No aggregate token/dollar budget kill-switch. Per-agent caps exist; cumulative does not | runner audit §5 | ALL |
| 5.2 | `max_runs=100` is per-feature not total; `--and-later` across N specs = 100×N spawns | runner audit §3.3 | ALL |
| 5.3 | Pricing tables disagree across files: runner $15/$75 Opus, cost_report.py $5/$25 — 3× delta | runner audit §8.1 | n/a (bug) |
| 5.4 | No in-flight cost monitor: agent making 50 snapshot calls in a row never triggers a warning | reference audit §gap D | ALL |
| 5.5 | `cost_report.py` is post-hoc only; no runtime feedback | runner audit §6 | ALL |
| 5.6 | TUI shows per-agent cost; no cumulative session cost displayed | runner audit §6 | ALL |
| 5.7 | A single agent can stream 500k input tokens before completing without triggering anything | runner audit §6 | ALL |
| 5.8 | `run-log.jsonl` is O(file) re-scanned every iteration; no index / rotation | runner audit §8.6 | ALL |
| 5.9 | `cheap_vs_expensive_calls` counted but not enforced as budget | reference audit §gap D | PLATFORM |
| 5.10 | Effectiveness signal "Verify Opus% > 0" detected only after the spend | reference audit §gap D | ALL |
| 5.11 | Pricing table hand-maintained in two files; no source-of-truth pointer | runner audit §8.1 | n/a (maintenance) |
| 5.12 | `--max-parallel` default 3; no auto-tuning by token budget or rate limits | runner audit §8.21 | ALL |

---

## Section 6 — Failure handling / loops / retries

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 6.1 | `MAX_VR_FIX_ATTEMPTS=5` | `parallel_runner.py:11139` | CODE | NEG | NON-POC |
| 6.2 | `MAX_VR_HANGS=3` before stopping VR spawns | `parallel_runner.py:10907` | CODE | NEG | NON-POC |
| 6.3 | `MAX_REVIEW_CYCLES=2` | `parallel_runner.py:10906` | CODE | NEG | NON-POC |
| 6.4 | `max_consecutive_noop=20` iterations → break | `parallel_runner.py:10408` | CODE | NEG | ALL |
| 6.5 | `PLATFORM_INIT_MAX_ATTEMPTS=10` per session | `parallel_runner.py:14123` | CODE | NEG | PLATFORM |
| 6.6 | `PLATFORM_META_FIX_MAX=2` | `parallel_runner.py:5182` | CODE | NEG | PLATFORM |
| 6.7 | `PLATFORM_LOOP_FAIL_THRESHOLD=3` triggers meta-fix | `parallel_runner.py:5175` | CODE | NEG | PLATFORM |
| 6.8 | Circuit breaker: 3 connection errors in 10 min → wait 5 min | `parallel_runner.py:8816-8859` | CODE | NEG | ALL |
| 6.9 | `BLOCKER_MAX_RETRIES_PER_STEP=3` | `parallel_runner.py:8232` | CODE | NEG | PLATFORM |
| 6.10 | Pre-E2E gate: `_PRE_E2E_GATE_UNPRODUCTIVE_STREAK_MAX=3`, `_PRE_E2E_GATE_META_FIX_MAX=2`, `_PRE_E2E_GATE_ROUND_HARD_CAP=50` | `parallel_runner.py:12651-12653` | CODE | NEG | PLATFORM |
| 6.11 | `_PRE_E2E_SERVICES_FIX_MAX_ATTEMPTS=5` | `parallel_runner.py:13026` | CODE | NEG | PLATFORM |
| 6.12 | `MAX_CONSECUTIVE_EXPLORE_FAILURES=3` | `parallel_runner.py:15974` | CODE | NEG | PLATFORM |
| 6.13 | `MAX_FIX_ATTEMPTS_BEFORE_SUPERVISOR=3` per bug | `parallel_runner.py:16904` | CODE | NEG | PLATFORM |
| 6.14 | `MAX_SUPERVISOR_RUNS=5` per bug → escalation | `parallel_runner.py:16905` | CODE | NEG | PLATFORM |
| 6.15 | `BUILD_FIX_MAX_ATTEMPTS=10` | `parallel_runner.py:17249` | CODE | NEG | PLATFORM |
| 6.16 | `INSTALL_RETRY_MAX=2` | `parallel_runner.py:17250` | CODE | NEG | PLATFORM |
| 6.17 | CI loop: `CI_LOOP_MAX_ATTEMPTS=50` outer; `CI_LOCAL_MAX_ITERATIONS=20` per attempt; `CI_REPEAT_FAILURE_THRESHOLD=5` consecutive identical | `parallel_runner.py:8955-8957` | CODE | NEG | NON-POC |
| 6.18 | CI loop respawn cap: 3 per task | `parallel_runner.py:10706` | CODE | NEG | NON-POC |
| 6.19 | E2E loop respawn cap: 5 per task | `parallel_runner.py:10747` | CODE | NEG | PLATFORM |
| 6.20 | Auth error → entire run stops (`_shutdown.set()`) | `parallel_runner.py:12056` | CODE | NEG | ALL |
| 6.21 | Rate-limit: pull `resetsAt` from stream-json, sleep until +10s buffer | `parallel_runner.py:12060` | CODE | NEG | ALL |
| 6.22 | Connection error → task stays PENDING with attempt history | `parallel_runner.py:4011` | CODE | NEG | ALL |
| 6.23 | flake.nix-change re-exec: drain agents, probe `nix develop`, `os.execvp` | `parallel_runner.py:10420-10474` | CODE | NEG | ALL |
| 6.24 | Process-group kill on SIGINT: TERM → 5s → KILL → reap | `parallel_runner.py:10205-10261` | CODE | NEG | ALL |
| 6.25 | PID file + stale runner cleanup on startup | `parallel_runner.py:10062-10096` | CODE | NEG | ALL |
| 6.26 | Strict mode: refuses to advance to next spec_dir when current didn't reach `all_complete` | `parallel_runner.py:10142-10177` | CODE | NEG | ALL |
| 6.27 | Bug supervisor decisions: DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE | `mcp-e2e-core.md:104-117`, `IC-AGENT-009` | CODE (anchor parsing) | LOW | PLATFORM |
| 6.28 | Loop supervisor decisions: CONTINUE / REDIRECT / STOP | `mcp-e2e-core.md`, `IC-AGENT-011` | CODE | LOW | PLATFORM |
| 6.29 | "Same bug fixed-then-verified-broken 3+ times = fix approach wrong" supervisor heuristic | `parallel_runner.py:18935` | PROMPT | MED | PLATFORM |

---

## Section 7 — Failure handling GAPS

| # | Gap | Source | Should-be-presets |
|---|---|---|---|
| 7.1 | Connection-error retry has no upper bound — persistent network problem = days of attempts | runner audit §4, §8.4 | ALL |
| 7.2 | `subprocess.run(..., timeout=600)` for runner-verify blocks main thread for 600s on a wedged test | runner audit §4.5, §8.5 | ALL |
| 7.3 | Auto-grant capabilities (gh, mcp-*) loop: keeps granting on every BLOCKED.md with no cap | runner audit §4.7 | ALL |
| 7.4 | Stripped capabilities only log to stderr; agent doesn't see warning; loop bounded only by noop-timeout | runner audit §8.16 | ALL |
| 7.5 | `_check_untrusted_code_risk` is regex-on-description (substring); false positives silent | runner audit §8.17 | n/a (bug) |
| 7.6 | "Do NOT use Skill tool" enforced purely by prompt; no programmatic block if a model auto-loads a skill | runner audit §8.8 | n/a (system-side) |
| 7.7 | `flake.nix` re-exec drains all agents using their own hang budgets; no force-kill escalation in that path | runner audit §8.13 | ALL |
| 7.8 | Sandbox bind-mounts `~/.claude/.credentials.json` read-only; expiry mid-spawn = entire run terminates | runner audit §8.14 | ALL |
| 7.9 | `read_attempt_history` vs `_count_recent_platform_failures` have contradictory policies on cross-session history | runner audit §8.15 | n/a (bug) |
| 7.10 | No retention policy on `logs/` or `specs/<feature>/reasoning/` — unbounded growth | runner audit §8.19 | ALL |
| 7.11 | "Reasoning — missing" feedback channel has no consumer; agents pay output tokens for no use | runner audit §8.20 | ALL |

---

## Section 8 — Architecture / code quality (runner)

| # | Smell | Location | Severity |
|---|---|---|---|
| 8.1 | `Runner` class is ~9,800 LOC inside one class | runner audit §8.2 | HIGH |
| 8.2 | `_run_feature` is ~1,800 LOC single method (10293-12087) | runner audit §1, §8.2 | HIGH |
| 8.3 | `MAX_VR_FIX_ATTEMPTS=5` declared twice (11139 and 11265) | runner audit §3, §8.9 | LOW (bug) |
| 8.4 | ~30 hardcoded constants; only handful config-readable via cost-config.json | runner audit §3, §8.9 | MED |
| 8.5 | Reasoning appendix added to every prompt — bloats prompt file, no consumer | runner audit §8.10 | LOW |
| 8.6 | `_agent_done_tasks` / `_recently_finished` / `self.agents` — three concurrent views of finished agents; comments describe past bugs from this | runner audit §8.7 | MED |
| 8.7 | Implementer prompt at 1834-1835 ("OK to mark complete after connection error if code compiles") contradicts 1897 ("NEVER claim done without exit-0") | runner audit §2.14, §8.11 | HIGH |
| 8.8 | CI-fix forbids `nix flake check`; CI-local-validate requires it — by-design but fragile | runner audit §2.14 | MED |
| 8.9 | Nix-note duplication: 10+ near-identical "this project uses Nix" blocks across prompts | runner audit §2.14 | LOW |
| 8.10 | "Do NOT use Skill tool" rule duplicated in 8+ prompts | runner audit §2.14 | LOW |
| 8.11 | IC-AGENT-016 collision: claims and verify.sh share the same IC number | reference audit §contradictions, `agent-file-schemas.md:460`+`:640` | MED (bug) |
| 8.12 | Validator told to install missing tools ("install via npm/uv/flake.nix") but `_check_untrusted_code_risk` silently strips `gh` cap on `npm install` description match | runner audit §2.14 | HIGH |
| 8.13 | "Don't skip ahead" (implementer) vs "Skip steps gated on CI-only secrets" (CI-fix) — same word, different scope | runner audit §8.11 | LOW |
| 8.14 | E2E executor cost section says "no grace period" but only enforcement is post-hoc cost_report | runner audit §8.12 | MED |

---

## Section 9 — Reference content contradictions

| # | Contradiction | Locations | Severity |
|---|---|---|---|
| 9.1 | Mocking: `testing.md:50` "no mocking inside tier" vs `testing.md:86-94` "use real servers everywhere" vs `testing.md:96-110` "stub binaries OK" — agents grab the most permissive reading | reference audit §contradictions | HIGH |
| 9.2 | Skip enforcement: `testing.md:156` bans `@pytest.mark.skipif`; `security.md:288` shows `t.Skip(...)` as OK; `testing.md:730-733` uses `t.Skip` example for latency tests | reference audit §contradictions | HIGH |
| 9.3 | Real platforms vs hardware bypass: `e2e-runtime.md:108-126` requires bypass for camera/biometrics; `testing.md:92` says mock only what requires human interaction; compatible but `e2e-runtime.md` has the load-bearing "verify absent in release" rule | reference audit §contradictions | MED |
| 9.4 | "Verifier reads artifacts not claims" vs `verification.md` "runner reads completion-{TASK_ID}.json" — different verifiers (per-task vs phase-boundary), but labels inconsistent | reference audit §contradictions | LOW |
| 9.5 | `browser_snapshot`: `cost-guardrails.md:140-148` "first visit OK" vs `mcp-e2e-web.md:45-56` "only for a11y bugs" | reference audit §contradictions | LOW |
| 9.6 | `continue-on-error: true` allowed for security baselines (`cicd.md:158-165`) but `security.md:191` uses it unconditionally on Snyk | reference audit §contradictions | MED |
| 9.7 | README vs CLAUDE.md duplication: `readme.md:192` says "don't duplicate"; `dx.md:71-91` and `stripe.md:218-251` show full duplication | reference audit §contradictions | LOW |
| 9.8 | Curl: `fix-agent-playbook.md:168-180` "not substitute for E2E"; `mcp-e2e-core.md:239-261` "allowed for state assertions" — reconcilable but easy to misread | reference audit §contradictions | LOW |

---

## Section 10 — CI/CD discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 10.1 | Pipeline stage order: lint → build → unit → integration → security → contract → E2E → deploy | `cicd.md:6-16` | CI (when shipped) | LOW | NON-POC |
| 10.2 | Build/release/run separation; pipeline as code | `cicd.md:18-30` | CI | LOW | NON-POC |
| 10.3 | Merge-blocking gates: tests, vacuous passes, critical/high CVEs, secrets, lint, build failures | `cicd.md:32-40` | CI | MED | NON-POC |
| 10.4 | Non-vacuous CI validation: YAML patterns for JUnit XML / Go JSON / security scanners | `cicd.md:42-119` | CI | HIGH | NON-POC |
| 10.5 | Verification step separate with `exit 1` (summary steps don't gate) | `cicd.md:115-119` | CI | HIGH | NON-POC |
| 10.6 | Skip-as-failure CI validation: `skip > 0` → exit non-zero | `cicd.md:121-156` | CI | HIGH | NON-POC |
| 10.7 | `continue-on-error: true` only for security baselines / optional token-gated steps; NEVER on test execution | `cicd.md:158-165` | CI | HIGH | NON-POC |
| 10.8 | Security scan reporting: SARIF, PR annotations, README badges, SBOM | `cicd.md:167-174` | CI | MED | NON-POC |
| 10.9 | Snyk for OSS (free tier); README CI Setup section with secret reference table | `cicd.md:176-270` | PROMPT | LOW | PROD |
| 10.10 | Artifact generation per run: test results, SBOM, security summary, coverage, build artifacts | `cicd.md:272-280` | CI | MED | NON-POC |
| 10.11 | Pre-release artifact availability: CI workflow builds ALL artifacts | `cicd.md:282-307` | CI | HIGH | PROD |
| 10.12 | Default branch readiness: badges, workflow_run, license, release config exist on default branch | `cicd.md:309-334` | PROMPT | MED | PROD |
| 10.13 | Observable output validation post-CI: badge curl, artifact verification, acceptance scenario execution | `cicd.md:336-373` | PROMPT | MED | PROD |
| 10.14 | Local security scan in fix-validate loop | `cicd.md:375-446` | CODE (validate agent runs scanners) | MED | NON-POC |
| 10.15 | Local CI workflow validation: actionlint, command reproducibility, artifact paths, secret refs, action pin warnings, workflow_run chain integrity | `cicd.md:448-509` | PROMPT | MED | NON-POC |
| 10.16 | Third-party action version pinning; check latest release; read action.yml | `cicd.md:491-505` | PROMPT | LOW | NON-POC |
| 10.17 | Agentic CI feedback loop: `[needs: gh, ci-loop]` tag → local-validate → push → poll → diagnose → fix → validate | `cicd.md:511-571`, `parallel_runner.py:CI_LOOP_*` | CODE | NEG (force multiplier) | NON-POC |
| 10.18 | CI parity in local validation: agent reads ALL workflows, runs every `run:` command including release | `cicd.md:533-541` | PROMPT | HIGH | NON-POC |
| 10.19 | Multi-build-system: project with `go.mod` + `android/build.gradle.kts` must pass BOTH | `cicd.md:541-542`, `implement.md` | VALIDATOR | HIGH | CONDITIONAL |
| 10.20 | Pre-PR target single command runs build → test → lint → security → non-vacuous → E2E → CI workflow syntax | `pre-pr.md:8-37` | PROMPT (project-side) | MED | NON-POC |
| 10.21 | Multi-build-system discovery: pre-pr scans manifests, runs each system's commands | `pre-pr.md:40-64` | PROMPT (project-side) | MED | CONDITIONAL |
| 10.22 | E2E in pre-PR: timeout 20m, retry 2x, `SKIP_E2E=1` bypass, runs LAST | `pre-pr.md:104-119` | CONVENTION | LOW | PLATFORM |
| 10.23 | pre-pr runs SAME checks as CI in SAME order with SAME tools | `pre-pr.md:121-134` | CONVENTION | MED | NON-POC |
| 10.24 | Stripe live-key guardrails: pre-commit hook + gitleaks rule + .env.example warning (three layers) | `stripe.md:403-448` | CI + CODE (gitleaks) + CONVENTION | NEG | CONDITIONAL |

---

## Section 11 — Security baseline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 11.1 | Validate at edge: API endpoints, form handlers, CLI args, file readers, message consumers — type + length + format + encoding | `security.md:6-16` | PROMPT | HIGH | PROD |
| 11.2 | Boundary validation covered by integration tests | `security.md:16` | PROMPT | HIGH | PROD |
| 11.3 | Auth: bcrypt/scrypt/argon2 never MD5/SHA; rate-limit failed attempts; "invalid credentials" generic message | `security.md:18-25` | PROMPT | HIGH | PROD |
| 11.4 | CORS default restrictive, NOT `*` | `security.md:27-29` | PROMPT | MED | PROD |
| 11.5 | Secrets: env vars or secret managers only; `.env`/`credentials.json`/`*.pem` gitignored; pre-commit Gitleaks | `security.md:31-36` | CI + CODE (sandbox) | MED | ALL |
| 11.6 | 7 mandatory HTTP security headers (HSTS, CSP, X-Content-Type, X-Frame-Options, Referrer-Policy, Permissions-Policy) | `security.md:37-50` | PROMPT | MED | PROD |
| 11.7 | Local scanner commands with JSON output to `test-logs/security/<scanner>.json` | `security.md:53-83` | CODE (validate runs) | MED | NON-POC |
| 11.8 | `summary.json` aggregates findings per scanner | `security.md:85-100` | CODE | MED | NON-POC |
| 11.9 | SARIF outputs for GitHub Security tab | `security.md:102-130` | CI | LOW | NON-POC |
| 11.10 | Finding classification: dep vuln / SAST / secret / false positive — never suppress without justification | `security.md:132-147` | PROMPT | MED | NON-POC |
| 11.11 | Tier 1 mandatory scanners: Trivy, OSV-Scanner, Semgrep, CodeQL, Gitleaks, TruffleHog, GitHub Secret Scanning, SBOM | `security.md:149-163` | CI | MED | NON-POC |
| 11.12 | Tier 1.5 OSS-free: Snyk, SonarCloud, OpenSSF Scorecard, Dependency Review, ZAP | `security.md:165-175` | CI | LOW | PROD |
| 11.13 | Fuzz testing required for: wire protocol parsers, binary deserializers, crypto, input validators | `security.md:204-221` | PROMPT | HIGH | ENT |
| 11.14 | Crash inputs saved, become regression tests, minimize before committing | `security.md:312-319` | PROMPT | MED | ENT |
| 11.15 | CI integration: regression every PR, code-change fuzz 5-10m, nightly 30-60m, weekly 2-8h | `security.md:271-310` | CI | MED | ENT |
| 11.16 | Sandboxing on by default (`_sandbox_enabled = True`); bwrap allowlist | `parallel_runner.py:3115, 3308-3468` | CODE | NEG | ALL |
| 11.17 | Untrusted-code capability stripping: `npm install|pip install|cargo install` patterns strip `gh`/sensitive caps | `parallel_runner.py:5098-5108, 3606-3616` | CODE | NEG | ALL |
| 11.18 | Sensitive env keys: `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` injected via Popen env, not bwrap setenv (keep out of /proc/cmdline) | `parallel_runner.py:5107, 3456-3461` | CODE | NEG | ALL |
| 11.19 | GH token TTL: 5 min | `parallel_runner.py:_GH_TOKEN_TTL=3273` | CODE | NEG | NON-POC |
| 11.20 | GH push always HTTPS, never SSH (YubiKey hangs in headless) | `parallel_runner.py:8997-9029` | CODE | NEG | NON-POC |
| 11.21 | Stripe: three keys (secret, publishable, webhook signing) | `stripe.md:36-43` | CONVENTION | LOW | CONDITIONAL |
| 11.22 | Stripe webhook handler: raw body, signature verification, idempotent via `processed_stripe_events` table, return 200 quickly, return 500 only on transient | `stripe.md:157-201` | PROMPT | HIGH | CONDITIONAL |
| 11.23 | Stripe publishable key dual delivery: runtime fetch + build-time fallback | `stripe.md:203-216` | PROMPT | MED | CONDITIONAL |

---

## Section 12 — Spec quality / depth

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 12.1 | FR-### numbering per requirement | `traceability.md:7-10`, `interview.md` | PROMPT | LOW | ALL (even poc) |
| 12.2 | SC-### success criteria, each mapping to ≥1 FR | `traceability.md:12-16` | PROMPT | LOW | NON-POC |
| 12.3 | Story-to-task traceability via `[Story 3]` or `[FR-015]` tags | `traceability.md:18-22` | PROMPT | LOW | NON-POC |
| 12.4 | SC-to-test traceability via Test Plan Matrix | `traceability.md:24-31`, `plan.md` | PROMPT | MED | NON-POC |
| 12.5 | Every task `Done when:` concrete / verifiable / 1-3 bullets / non-subjective | `traceability.md:33-39`, `tasks.md` | PROMPT | HIGH | NON-POC |
| 12.6 | Done criterion must add information beyond title | `tasks.md` § Task done criteria | PROMPT | MED | NON-POC |
| 12.7 | "Write tests" done-when means "tests pass on target runtime" not "tests exist" | `tasks.md` § Task done criteria | PROMPT | HIGH | NON-POC |
| 12.8 | Done criterion must not be satisfiable by a stub | `tasks.md` § Task done criteria | PROMPT | HIGH | NON-POC |
| 12.9 | Done criterion MUST pin exact names from spec (column headers, log strings, JSON keys, UI labels) | `tasks.md` § Task done criteria | VALIDATOR (spec-conformance check) | HIGH | NON-POC |
| 12.10 | Cross-boundary tasks must assert both sides — producer writes correct format AND consumer deserializes correctly | `tasks.md`, `validate-review.md:88-98` | VALIDATOR | HIGH | CONDITIONAL |
| 12.11 | Edge Cases section: 11 categories to probe — timeout, crash, concurrent access, invalid input, partial completion, network failure, resource exhaustion, missing deps, duplicate ops, permission failures, data migration | `edge-cases.md:8-22` | PROMPT | HIGH | NON-POC |
| 12.12 | Each edge case has trigger + expected behavior | `edge-cases.md:5` | PROMPT | HIGH | NON-POC |
| 12.13 | Non-Goals section: explicit scope-creep prevention; what could be a goal but isn't | `interview.md`, `spec.md` template | PROMPT | MED | ALL |
| 12.14 | Examples on FRs: mandatory on `[NEEDS CLARIFICATION]` FRs; encouraged on ambiguous user-visible behavior | `interview.md` § FR numbering | PROMPT | MED | NON-POC |
| 12.15 | Operational workflows: day-1 setup, day-2 ops, failure recovery, admin processes for daemons/long-running tools | `interview.md` § Operational workflows | PROMPT | MED | CONDITIONAL |
| 12.16 | data-model.md depth: ERDs with cardinality both directions, per-entity field tables, state transition tables, cross-entity constraints | `data-model.md`, `plan.md` § Data layer | PROMPT | MED | CONDITIONAL |
| 12.17 | API contract depth: full request/response schemas, all status codes with triggers, wire format docs for binary protocols | `api-contracts.md`, `plan.md` § API layer | PROMPT | MED | CONDITIONAL |
| 12.18 | research.md: every major decision documented with rationale + rejected alternatives | `plan.md` § Research, "Architecture Rationale Depth" | PROMPT | HIGH | NON-POC |
| 12.19 | Complexity Tracking: any abstraction beyond simplest = row in table or constitution-check confirmation | `complexity.md`, `plan.md` | PROMPT | MED | NON-POC |
| 12.20 | Interface contracts (IC-xxx): producer/consumer/format/location/permissions/lifecycle for shared state | `interface-contracts.md` | PROMPT | MED | CONDITIONAL |
| 12.21 | Wire format precision: enumerate field names with exact serialization keys (camelCase vs snake_case vs PascalCase); cross-language source of truth | `plan.md` § Interface contracts | PROMPT | HIGH | CONDITIONAL |
| 12.22 | Phase dependencies section: dependency graph, parallel workstreams, sync points; DAG must be acyclic | `phase-deps.md`, `plan.md` § Phase Dependencies | PROMPT | MED | NON-POC |
| 12.23 | Runtime state machines for daemons / protocol handshakes / connection management — distinct from data-model state transitions and UI_FLOW state machines | `plan.md` § Runtime state machines | PROMPT | MED | CONDITIONAL |
| 12.24 | Critical path (user perspective): minimal day-1 user flow + phase mapping + incremental integration checkpoints | `plan.md` § Critical path | PROMPT | MED | NON-POC |
| 12.25 | Tool environment inventory: every build/test/lint command mapped to tool and Nix package | `plan.md` § Technology stack, `implement.md` § Environment preflight | PROMPT | HIGH | ALL |
| 12.26 | DX friction analysis: for every tool, evaluate install path, build/run overhead, CI parity | `plan.md` § Technology stack | PROMPT | MED | NON-POC |
| 12.27 | Workflows.md (Phase 5.5) is the E2E test contract; one workflow → one E2E test | `workflows.md` | PROMPT | HIGH | CONDITIONAL |
| 12.28 | Persona inventory: developer + sysadmin + ≥1 end-user; expand by role spec.md names | `workflows.md` § Personas | PROMPT | MED | CONDITIONAL |
| 12.29 | Workflow schema: Persona / Touches / Trigger / Preconditions / Bypass paths / Steps / Edge cases / Performance budget / Test command | `workflows.md` § Workflow schema | PROMPT | HIGH | CONDITIONAL |
| 12.30 | Workflow assertion depth: DOM state + CSS resolution + network + negative assertions | `workflows.md` § Assertion depth | PROMPT | HIGH | CONDITIONAL |
| 12.31 | Selectors: ARIA role + accessible name; data-testid; visible text — NEVER tag+nth-child or CSS class | `workflows.md` § Selectors | PROMPT | MED | CONDITIONAL |
| 12.32 | Edge case enumeration is exhaustive not selective — walk spec edge cases per workflow | `workflows.md` § Edge case enumeration | PROMPT | HIGH | CONDITIONAL |
| 12.33 | Document user pushbacks + rejected alternatives in research.md so implementers don't re-evaluate | `interview.md` § Auto-unblocking context | PROMPT | HIGH | NON-POC |
| 12.34 | UI_FLOW.md: screens / state machines / per-screen details / API sequence diagrams / endpoint summary / real-time paths / field validation table | `ui-flow.md`, `interview.md` § UI-specific topics | PROMPT | HIGH | CONDITIONAL |
| 12.35 | UI_FLOW.md update in same commit as UI code; every flow has corresponding E2E test | `ui-flow.md:101-112` | PROMPT | HIGH | CONDITIONAL |
| 12.36 | Specify branching strategy in interview (feature branches+PRs vs direct-to-main) | `interview.md` § Branching strategy | PROMPT | LOW | NON-POC |
| 12.37 | Authoring Acceptance Scenarios in spec.md is DEPRECATED — replaced by workflows.md | `interview.md` § When You're Satisfied | PROMPT | MED | CONDITIONAL |
| 12.38 | E2E gap-analysis checklist: 13 categories (happy path, state machines, external adapters, webhooks, edge cases, cross-app, guest→auth, refund/cancel, notification, race, security boundary, upload, cross-platform) — each gets task or "out of scope because X" | `tasks.md` § E2E + MCP gap-analysis | PROMPT | HIGH | CONDITIONAL |
| 12.39 | MCP infrastructure tasks (7 mandatory rows): flake input + packages + permissions + prereq + setup.sh + build/install + regression harness + multi-app annotation | `tasks.md` § Part A — MCP infrastructure | PROMPT | HIGH | PLATFORM |
| 12.40 | Integration test hardening phase (Layer 1: per-file; Layer 2: cross-domain user-flow mirror tests) BEFORE E2E phase | `tasks.md` § Part D | PROMPT | HIGH | CONDITIONAL |
| 12.41 | One screen per E2E task — fresh context per agent | `tasks.md`, `mcp-e2e-core.md:441-466` | PROMPT | NEG | PLATFORM |
| 12.42 | Multi-app Android repos: every `[needs: mcp-android]` task carries `[android-app: <dir>]` | `tasks.md`, `mcp-e2e-android.md:103-143` | CODE (runner parses) | MED | CONDITIONAL |
| 12.43 | Acceptance scenario exerciser: classify as auto-verifiable / CI-verifiable / manual; execute all auto-verifiable | `cicd.md:336-373`, `implement.md` § Phase 4 | PROMPT | HIGH | PROD |

---

## Section 13 — Spec quality GAPS

| # | Gap | Source |
|---|---|---|
| 13.1 | No "done when" criteria generated mechanically from spec — agent authors them and can write itself loose criteria | implicit in our discussion |
| 13.2 | No detector for "agent added abstraction without Complexity Tracking entry" | reference audit §gap C |
| 13.3 | No detector for "you added a route but UI_FLOW.md doesn't list it" (May-22 shape) | reference audit §gap C, §F |
| 13.4 | `[produces: IC-xxx]` / `[consumes: IC-xxx]` tags are NOT parsed by runner — pure documentation | reference audit, `interface-contracts.md:46` |
| 13.5 | `data-model.md`, `api-contracts.md`, `traceability.md`, `edge-cases.md` depth — no detector | reference audit §gap C |
| 13.6 | No detector for "workflow exists but no corresponding E2E task in tasks.md" | (workflows.md → tasks gap) |
| 13.7 | No machinery detects diff-vs-task-description mismatch (the rationalization gap) | implicit in our discussion |
| 13.8 | No detector for "spec.md changed but plan.md and tasks.md don't reflect it" | spec drift |
| 13.9 | Acceptance Scenario reframe to workflows.md is documented but not validated — analyzer doesn't fail when old Given/When/Then bullets remain | `interview.md` deprecation, `workflows.md` |

---

## Section 14 — Reliability primitives

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 14.1 | Structured JSON logging, 5 levels (DEBUG/INFO/WARN/ERROR/FATAL) | `logging.md:5-15` | PROMPT | MED | NON-POC |
| 14.2 | Required fields: timestamp / level / message / module / correlationId | `logging.md:21-29` | PROMPT | MED | NON-POC |
| 14.3 | ERROR/FATAL additional fields: error / errorCode / stack | `logging.md:31-37` | PROMPT | LOW | NON-POC |
| 14.4 | Logs destination: app → stderr; structured data → stdout; no raw console.log/print | `logging.md:39-43` | PROMPT | MED | NON-POC |
| 14.5 | Correlation IDs at every request entry, propagated downstream | `logging.md:50-55` | PROMPT | MED | NON-POC |
| 14.6 | Project-level error base class with typed subclasses + HTTP mappings | `errors.md:7-19` | PROMPT | MED | NON-POC |
| 14.7 | Each error: machine-readable code + HTTP status + user-facing safety flag | `errors.md:21-25` | PROMPT | MED | NON-POC |
| 14.8 | Error propagation: throw at point of failure → catch at boundary → log full context → return sanitized response | `errors.md:27-33` | PROMPT | MED | NON-POC |
| 14.9 | Never swallow / never log-and-rethrow | `errors.md:32-33` | PROMPT | MED | NON-POC |
| 14.10 | Global unhandled exception/rejection handler: log FATAL → trigger shutdown → exit non-zero | `errors.md:35-42` | PROMPT | MED | NON-POC |
| 14.11 | Single config module loading from defaults → file → env vars | `config.md:7-14` | PROMPT | MED | NON-POC |
| 14.12 | Config validation: typed config object, fail-fast on startup, list ALL invalid keys | `config.md:13-22` | PROMPT | HIGH | NON-POC |
| 14.13 | Backing services as attached resources — swappable via config | `config.md:17-19` | PROMPT | MED | NON-POC |
| 14.14 | Secrets only from env vars / secret manager; never logged as values | `config.md:24-29` | PROMPT | HIGH | ALL |
| 14.15 | Config doc table: Key/Type/Default/Required/Sensitive/Description | `config.md:31-39` | PROMPT | LOW | NON-POC |
| 14.16 | GET /health (liveness): 200 if alive regardless of deps | `health.md:7-23` | PROMPT | LOW | CONDITIONAL |
| 14.17 | GET /ready (readiness): 200 if can accept traffic; 503 during startup/shutdown/critical-dep-down | `health.md:25-30` | PROMPT | MED | CONDITIONAL |
| 14.18 | Dependency check strategy explicit (active vs cached) | `health.md:32-34` | PROMPT | LOW | CONDITIONAL |
| 14.19 | CLI: `--check`/`--validate` flag; exit 0 OK, 1 problem | `health.md:36-40` | PROMPT | LOW | CONDITIONAL |
| 14.20 | Register SIGTERM + SIGINT handlers | `shutdown.md:5-7` | PROMPT | MED | CONDITIONAL |
| 14.21 | 11-step shutdown sequence with INFO logging at each step | `shutdown.md:9-23` | PROMPT | MED | CONDITIONAL |
| 14.22 | Configurable shutdown timeout default 30s; force-exit code 1 if exceeded | `shutdown.md:25-30` | PROMPT | LOW | CONDITIONAL |
| 14.23 | Shutdown hook registry, reverse-order cleanup | `shutdown.md:32-35` | PROMPT | LOW | CONDITIONAL |
| 14.24 | Per-client rate limits (sliding window / token bucket) | `rate-limiting.md:7` | PROMPT | MED | PROD |
| 14.25 | Rate-limit headers: `X-RateLimit-Limit/Remaining/Reset` | `rate-limiting.md:8` | PROMPT | LOW | PROD |
| 14.26 | 429 response with `Retry-After` | `rate-limiting.md:9` | PROMPT | LOW | PROD |
| 14.27 | Bounded queues with explicit overflow behavior | `rate-limiting.md:10` | PROMPT | MED | PROD |
| 14.28 | Every external call has explicit timeout | `rate-limiting.md:12` | PROMPT | HIGH | NON-POC |
| 14.29 | Up/down idempotent versioned tested migrations | `migration.md:5-15` | PROMPT | MED | CONDITIONAL |
| 14.30 | Seed script: schema + required reference data + optional sample data | `migration.md:19-27` | PROMPT | MED | CONDITIONAL |
| 14.31 | API URL-path versioning + latest-version alias | `migration.md:29-35` | PROMPT | LOW | CONDITIONAL |
| 14.32 | Admin process parity: migrations + seeds + scripts inside same Nix flake / venv / container as app | `migration.md:44-50` | PROMPT | MED | CONDITIONAL |
| 14.33 | Config versioning: auto-migrate / clear error / release-notes | `migration.md:52-57` | PROMPT | LOW | ENT |
| 14.34 | Every setup/init/bootstrap MUST be idempotent | `idempotency.md:7-15` | PROMPT | HIGH | ALL |
| 14.35 | Check-before-mutate rule | `idempotency.md:13` | PROMPT | HIGH | ALL |
| 14.36 | Readiness checks: blocking with timeout, instant return if up, non-zero on timeout | `idempotency.md:28-44` | PROMPT | MED | NON-POC |
| 14.37 | Metrics at key ops: request count/latency/error rate, resource metrics, business metrics | `observability.md:6-9` | PROMPT | MED | ENT |
| 14.38 | Trace context propagation via correlation ID through logs / headers / queue metadata / error reports | `observability.md:11-16` | PROMPT | MED | ENT |
| 14.39 | Structured error reports: stack + correlation ID + env + user context anonymized + breadcrumbs | `observability.md:18` | PROMPT | MED | ENT |
| 14.40 | Request/response logging at DEBUG with PII omission | `observability.md:20` | PROMPT | MED | ENT |

---

## Section 15 — DX / scaffolding / environment

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 15.1 | One-command dev setup: `nix develop && npm run dev` (or equivalent) | `dx.md:7-12` | PROMPT | MED | NON-POC |
| 15.2 | Script inventory: dev/test/test:unit/test:integration/lint/lint:fix/typecheck/build/db:* /codegen/clean/clean:all/check | `dx.md:16-34` | PROMPT | MED | NON-POC |
| 15.3 | Dev server: hot reload, proxy, HTTPS in dev (if needed), port consistency | `dx.md:36-41` | PROMPT | LOW | CONDITIONAL |
| 15.4 | `.env.example` committed; `.env` gitignored; Nix flake default; flake.lock committed; no `nvm`/`pyenv`/`rbenv` | `dx.md:43-54` | CONVENTION | MED | ALL |
| 15.5 | Codegen in dedicated dir with `// @generated` header | `dx.md:56-62` | PROMPT | LOW | CONDITIONAL |
| 15.6 | Debugging configs: `launch.json` for VS Code | `dx.md:64-69` | PROMPT | LOW | NON-POC |
| 15.7 | CLAUDE.md "Development" section template | `dx.md:71-91` | PROMPT | LOW | NON-POC |
| 15.8 | code-review-graph wired at Phase 0 — flake input + mkShellHook + .code-review-graphignore | `code-review-graph.md`, `install.md` | CODE (flake hook) | NEG | ALL |
| 15.9 | Always call `get_minimal_context_tool` first | `code-review-graph.md` (CLAUDE.md stanza) | PROMPT | MED | ALL |
| 15.10 | Use `detail_level="minimal"` on graph tool calls | `code-review-graph.md` CLAUDE-STANZA | PROMPT | MED | ALL |
| 15.11 | Query before creating: `semantic_search_nodes_tool` / `query_graph_tool` | `code-review-graph.md` CLAUDE-STANZA | PROMPT | MED | ALL |
| 15.12 | Reviews start with `detect_changes_tool` not raw `git diff` | `code-review-graph.md` CLAUDE-STANZA | PROMPT | MED | ALL |
| 15.13 | If graph and code disagree, trust code but log it | `code-review-graph.md` CLAUDE-STANZA | PROMPT | LOW | ALL |
| 15.14 | code-review-graph DEFAULT_IGNORE_PATTERNS handles node_modules etc.; only add project-specific to `excludeDirs` | `code-review-graph.md:143-157` | CONVENTION | LOW | ALL |
| 15.15 | `excludeDirs` writes managed block in `.code-review-graphignore` (idempotent rewrites) | `code-review-graph.md:104-141` | CODE (mkShellHook) | NEG | ALL |
| 15.16 | After changing `excludeDirs`, force rebuild | `code-review-graph.md:201-208` | CONVENTION | NEG | ALL |
| 15.17 | `_GRAPH_USAGE_STANZA` appended to every prompt | `parallel_runner.py:140-176` | CODE | NEG | ALL |
| 15.18 | E2E roles skip CLAUDE.md auto-prepend + reference index pointer | `parallel_runner.py:203-205, 271` | CODE | NEG | PLATFORM |
| 15.19 | Required-reads header on every prompt: "MUST Read every file listed below before any tool, plan, or code" | `parallel_runner.py:179-227` | CODE (prompt builder) | NEG | ALL |
| 15.20 | Read checklist in agent response: literal `Read checklist: [✓] <file 1>, [✓] <file 2>, …` | `parallel_runner.py:221` | PROMPT | LOW | ALL |
| 15.21 | "Planning before reading" forbidden | `parallel_runner.py:227` | PROMPT | LOW | ALL |
| 15.22 | Reasoning appendix at end of every agent: What I did / Why / Confidence & risks / Next step if this fails / Prompt feedback | `parallel_runner.py:4409-4436` | CODE (prompt builder) | LOW | ALL |
| 15.23 | NEVER inline reference content into prompt body — pass absolute paths for cache hits | `cost-reporting.md:86-106` | CONVENTION | NEG | ALL |
| 15.24 | .gitignore baseline + conditional entries per preset | `SKILL.md` § .gitignore management | PROMPT | LOW | ALL |
| 15.25 | Update .gitignore after every phase that produces new artifacts (poc/Phase 0; non-poc/Phases 0/2/5/6/7) | `SKILL.md` § .gitignore management | PROMPT | LOW | ALL |
| 15.26 | `--ignore-scripts` for npm/pnpm/yarn installs (block postinstall supply-chain) | `SKILL.md` § Install rules | PROMPT | HIGH | ALL |
| 15.27 | Pip prefer wheels (`--only-binary :all:`); source builds only when no wheel exists | `SKILL.md` § Install rules | PROMPT | MED | ALL |
| 15.28 | NEVER `nix profile install`, `npm install -g`, `uv tool install`, `pip install` (global), `curl \| sh` | `SKILL.md` § Install rules, `implement.md` § Auto-Unblocking | CODE (sandbox blocks) | HIGH | ALL |
| 15.29 | NIX_REMOTE=daemon, `--extra-experimental-features 'nix-command flakes'`, source devshell once not per-call | `nix-ci.md:7-15` | PROMPT | MED | ALL |
| 15.30 | `nix flake check` 10-20m timeout ≥1800s; background; never pipe through head/tail | `nix-ci.md:17-26` | PROMPT | MED | ALL |
| 15.31 | bwrap sandbox: home-dir paths not mounted | `nix-ci.md:28-31`, `parallel_runner.py:3308-3468` | CODE | NEG | ALL |
| 15.32 | NEVER prefix every command with `nix develop --command` (re-evals each call) | `nix-ci.md:34` | PROMPT | MED | ALL |
| 15.33 | NEVER use `head`/`tail`/`grep -c` on nix flake check logs (last 200 lines = critical errors) | `nix-ci.md:34-39` | PROMPT | MED | ALL |
| 15.34 | NEVER `nix-env -i` in sandbox; NEVER trust exit 0 through `tee` without `pipefail` | `nix-ci.md:34-39` | PROMPT | HIGH | ALL |

---

## Section 16 — README discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 16.1 | Cognitive funneling: broad → specific | `readme.md:6-8` | PROMPT | LOW | ALL |
| 16.2 | 14 required sections (title+tagline / badges / description / visuals / features / TOC if long / getting started / usage / configuration / architecture / development / security / license / acknowledgments) | `readme.md:10-160` | PROMPT | LOW | NON-POC |
| 16.3 | Quality checklist (7 items) | `readme.md:174-183` | PROMPT | LOW | NON-POC |
| 16.4 | README generated post-smoke pre-CI (so content is accurate) | `tasks.md` § README generation | PROMPT | LOW | NON-POC |
| 16.5 | Badge validation: extract URL, fetch, check HTTP 200, no error text in SVG | `cicd.md:336-373`, `implement.md` § Phase 4 | PROMPT | MED | PROD |
| 16.6 | Artifact validation: `gh run view --json artifacts`, download one to confirm not empty | `cicd.md`, `implement.md` § Phase 4 | PROMPT | MED | PROD |

---

## Section 17 — Failure-pattern library

| # | Signature | Diagnostic | Source | Enforcement |
|---|---|---|---|---|
| 17.1 | `port-timeout-but-service-ready`: IPv4/IPv6 binding mismatch; fix bind, not timeout | `e2e-failure-patterns.md:22-57` | CODE (runner regex matches + injects into fix prompt) |
| 17.2 | `config-validation-missing-required`: `.env` placeholders; populate with obvious test values | `e2e-failure-patterns.md:61-98` | CODE |
| 17.3 | `service-crash-on-boot`: read stack trace; never restart in loop | `e2e-failure-patterns.md:101-126` | CODE |
| 17.4 | `stale-process-guard-skipped-restart`: kill stale PIDs; improve teardown not setup | `e2e-failure-patterns.md:128-160` | CODE |
| 17.5 | `migration-already-applied`: make idempotent; wiping pgdata OK in dev/E2E only | `e2e-failure-patterns.md:162-193` | CODE |
| 17.6 | `browser-install-hang`: Playwright wants Chrome, Nix has Chromium; fix in nix-mcp-debugkit wrapper; never retry, never preinstall, never bundle google-chrome | `e2e-failure-patterns.md:196-259` | CODE |
| 17.7 | `stale-android-apk-after-source-fix`: Gradle cache lies; `flutter clean` mandatory; verify by APK content-grep not build log | `e2e-failure-patterns.md:262-355` | CODE |
| 17.8 | `emulator-boot-timeout`: AVD/KVM/headless flags | `e2e-failure-patterns.md:358-381` | CODE |
| 17.9 | `mcp-launch-failed`: bwrap + nix store; placeholder binary; missing shared lib; protocol mismatch | `e2e-failure-patterns.md:386-423` | CODE |
| 17.10 | `mcp-exits-clean-within-5s`: historically a runner bug, not a server bug; don't add per-repo keepalive wrappers | `e2e-failure-patterns.md:425-441` | CODE + PROMPT |

---

## Section 18 — Auto-unblocking discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 18.1 | Classify blocker first: tool install / env config / build fail / test infra / dep service — auto-resolvable; design ambiguity / credentials / external access / hardware — needs human | `implement.md` § Auto-Unblocking | PROMPT | HIGH | ALL |
| 18.2 | Scope aversion is NOT a blocker — bounded env/tooling failures are in scope | `implement.md` § Auto-Unblocking | PROMPT | HIGH | ALL |
| 18.3 | NEVER anchor on prior BLOCKED.md without re-diagnosing | `implement.md` § Auto-Unblocking | PROMPT | HIGH | ALL |
| 18.4 | Run `[needs: X]` diagnose script first; respect `working` / `fixable` / `broken` returns | `implement.md` § Auto-Unblocking | CODE (task-deps.json hook) | MED | NON-POC |
| 18.5 | Diagnose hint chain depth capped at 2 | `implement.md` § Auto-Unblocking | CODE | NEG | NON-POC |
| 18.6 | Read `interview-notes.md` + `research.md` + `spec.md` before auto-resolution | `implement.md` § Auto-Unblocking | PROMPT | MED | NON-POC |
| 18.7 | If solution conflicts with user preference, skip and try next option | `implement.md` § Auto-Unblocking | PROMPT | HIGH | NON-POC |
| 18.8 | BLOCKED.md only for: credentials, design decisions, external access, hardware | `implement.md` § Auto-Unblocking | CODE (auto-grant for `[needs:]` capabilities) | NEG | NON-POC |
| 18.9 | Client/server protocol mismatch: upgrade older side first; only downgrade as last resort | `implement.md` § Auto-Unblocking | PROMPT | HIGH | NON-POC |
| 18.10 | Always upgrade older component first; downgrade only if upgrade demonstrably impossible | `implement.md` § Auto-Unblocking | PROMPT | HIGH | NON-POC |
| 18.11 | `_AUTO_GRANTABLE_CAPS = {gh, e2e-loop, mcp-android, mcp-browser, mcp-ios, stripe-listen}` | `parallel_runner.py:5093, 5157, 5165` | CODE | NEG | NON-POC |
| 18.12 | Amendment (not BLOCKED.md) for "I CAN proceed but spec is wrong" | `implement.md` § Mid-Implementation Spec Amendment | CODE (file detection) | MED | NON-POC |
| 18.13 | Amendment ADR-style append-only in spec.md — never silently edit original | `implement.md` § Mid-Implementation Spec Amendment | PROMPT | MED | NON-POC |
| 18.14 | Amendment pauses ONLY affected downstream tasks, not the entire pipeline | `implement.md` § Mid-Implementation Spec Amendment | CODE | NEG | NON-POC |

---

## Section 19 — Phase orchestration

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 19.1 | Mandatory analyze loop after clarify, until clean | `SKILL.md` § Phase 4 | PROMPT | HIGH | NON-POC |
| 19.2 | Auto-advance between phases except never auto-start Phase 7 (implement) | `SKILL.md` § Auto-advance | PROMPT | NEG | ALL |
| 19.3 | Workflows.md re-runs analyze loop (new artifact) | `SKILL.md`, `workflows.md` | PROMPT | MED | CONDITIONAL |
| 19.4 | Per-phase fix-validate loop, runner-enforced, validation per-phase not per-task | `implement.md` § Fix-validate loop | CODE | NEG | NON-POC |
| 19.5 | Multi-build-system discovery before validation | `implement.md` § Multi-build-system discovery | VALIDATOR | HIGH | CONDITIONAL |
| 19.6 | Real-runtime E2E requirement: Android `connectedDebugAndroidTest` not just `test`; web Playwright/Chromium not jsdom | `implement.md` § Real-runtime E2E | VALIDATOR | HIGH | PLATFORM |
| 19.7 | Cross-language artifact verification: AAR contains real `.so`, `nm -D` exports, WASM >10KB, exercise cross-boundary code path | `implement.md` § Cross-language artifact | VALIDATOR | HIGH | CONDITIONAL |
| 19.8 | Validation FAIL with unvalidated build system in coverage proof = automatic FAIL | `implement.md` § Validation coverage proof | VALIDATOR | HIGH | NON-POC |
| 19.9 | Coverage proof MANDATORY in every validation record — files-changed table + per-build-system status | `implement.md` § Validation coverage proof | VALIDATOR | HIGH | NON-POC |
| 19.10 | "Unable to validate = FAIL" rule (vs skip) | `implement.md` § Validation coverage proof | VALIDATOR | HIGH | NON-POC |
| 19.11 | No "expected failure" rationalization — fix code OR write BLOCKED.md, no third option | `implement.md` § No "expected failure" rationalization | PROMPT | HIGH | NON-POC |
| 19.12 | No skip-without-replacement: disabling a check (doCheck=false, it.skip, .only, xdescribe, --skip-tests) = FAIL unless agent adds runs-in-the-gate replacement | `implement.md` § No "expected failure" rationalization | VALIDATOR | HIGH | NON-POC |
| 19.13 | Stub detection in production code: DI modules, factory methods, provider functions for implementations that only set flags or return hardcoded values | `implement.md` § Stub detection | VALIDATOR | HIGH | NON-POC |
| 19.14 | Test code (test doubles, mocks, fakes in test dirs) is exempt; production stubs are FAIL | `implement.md` § Stub detection | VALIDATOR | HIGH | NON-POC |
| 19.15 | Cross-boundary contract verification: field name agreement at every cross-boundary seam (Nix→Go, Go→Kotlin, API→frontend) | `implement.md` § Cross-boundary contract verification | VALIDATOR | HIGH | CONDITIONAL |
| 19.16 | Environment preflight: every build/test/lint tool verified via `command -v` after flake setup | `implement.md` § Environment preflight | VALIDATOR | HIGH | ALL |
| 19.17 | `scripts/preflight.sh` Phase 1 task; runs in seconds; clear error per missing tool | `implement.md` § Preflight script pattern | PROMPT | MED | NON-POC |
| 19.18 | Multi-language project trap: secondary languages forgotten in flake — preflight catches it | `implement.md` § Multi-language project trap | VALIDATOR | HIGH | CONDITIONAL |
| 19.19 | After CI passes: Observable Output Validation (badges, artifacts, default branch readiness, acceptance scenarios, cross-system integration) | `implement.md` § Phase 4 | VALIDATOR | MED | PROD |
| 19.20 | Local smoke test phase: build all artifacts, install in clean environment, exercise every primary user flow, cold + warm start | `implement.md` § Post-Implementation Validation | VALIDATOR | HIGH | NON-POC |
| 19.21 | Smoke test 20-iteration cap per flow; reset on forward progress | `implement.md` § Agent escalation strategy | CODE | NEG | NON-POC |
| 19.22 | Smoke test bug taxonomy: 12 categories ordered by frequency (packaging gaps, native libs, dep version, etc.) | `implement.md` § Bug taxonomy | PROMPT | MED | NON-POC |
| 19.23 | CI workflow local verification BEFORE CI loop when workflows modified — parallel sub-tasks per build system | `tasks.md` § CI workflow local verification | CODE (runner spawns parallel sub-agents) | MED | NON-POC |
| 19.24 | Verify EVERY `run:` command, EVERY artifact path, EVERY test verification step, EVERY tool referenced | `tasks.md` § CI workflow local verification | PROMPT | HIGH | NON-POC |
| 19.25 | CI/CD validation phase placement rule: `[needs: gh, ci-loop]` MUST be in separate phase from local CI verification tasks to avoid circular phase deadlock | `tasks.md` § CI/CD validation phase | PROMPT | MED | NON-POC |
| 19.26 | All CI/CD tasks using `gh` MUST be marked `[needs: gh]` — short-lived GH_TOKEN env var injection | `tasks.md`, `parallel_runner.py:_GH_TOKEN_TTL` | CODE | NEG | NON-POC |
| 19.27 | NEVER combine `[needs: gh]` with package install commands (supply chain attack vector) | `tasks.md` § Task structure | CODE (capability stripping) | NEG | ALL |
| 19.28 | `workflow_run` chain integrity: after triggering workflow passes, verify downstream triggered, conclusion = success not skipped | `cicd.md`, `implement.md` § Phase 4 | PROMPT | MED | PROD |
| 19.29 | Preset overrides MANDATORY tags — preset wins | `SKILL.md` § Apply the preset | PROMPT | NEG | ALL |

---

## Section 20 — Learnings management

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 20.1 | `learnings.md` accumulates discoveries across tasks | `SKILL.md` § Learnings management, `traceability.md:48-60` | CODE (runner reads + auto-prunes) | NEG | NON-POC |
| 20.2 | Phase-based filtering: each agent gets only learnings from its phase + upstream dependencies | `SKILL.md` § Learnings management | CODE | NEG | NON-POC |
| 20.3 | Auto-pruning after each main-loop iteration: removes learnings for fully-validated phases with no pending downstream | `SKILL.md` § Learnings management | CODE | NEG | NON-POC |
| 20.4 | Max 3 bullet points per task, focus on non-obvious gotchas only | `SKILL.md` § Learnings management, `interview.md` | PROMPT | LOW | NON-POC |
| 20.5 | Structured format per task ID | `traceability.md:48-60` | PROMPT | LOW | NON-POC |

---

## Section 21 — Reference content & prompt-cache discipline

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 21.1 | Two-tier prompt loading: Tier 1 mandatory reads (2-4 files per role), Tier 2 reference index pointer | `README.md` § Two-tier prompt loading | CODE (prompt builder) | NEG | ALL |
| 21.2 | Tier 1 path list per role is a literal list at the call site — don't generate from runtime state unless byte-stable | `README.md`, `cost-reporting.md:95` | CONVENTION | NEG | ALL |
| 21.3 | Role string in Tier-1 block must be stable per call site | `README.md` | CONVENTION | NEG | ALL |
| 21.4 | Don't append per-attempt content (timestamps, attempt numbers, claim files) into Tier-1/Tier-2 blocks | `README.md` | CONVENTION | NEG | ALL |
| 21.5 | When adding a new reference file, add row to `reference/index.md`; when role's mandatory references change, update role's `_required_reads_block` | `README.md` | CONVENTION | NEG | ALL |
| 21.6 | Determinism check: render each builder twice with identical inputs, assert byte-equality | `README.md` | CONVENTION | NEG | ALL |
| 21.7 | Reference index decision-tree: "if you are doing X, read Y" | `reference/index.md` | PROMPT | NEG | ALL |
| 21.8 | E2E sub-agents skip the index entirely (cost rationale, $0.86 wasted per agent) | `reference/index.md:7-14`, `mcp-e2e.md:20-26` | CODE (prompt builder) | NEG | PLATFORM |
| 21.9 | Classify task with exactly one task:* tag and all applicable domain:* tags before reading | `reference/index.md:16-71` | PROMPT | NEG | ALL |
| 21.10 | A row tagged `*` matches everything; read those always | `reference/index.md:80` | PROMPT | NEG | ALL |
| 21.11 | If two rows direct to same file, read once — cache hit covers re-read | `reference/index.md:81` | CONVENTION | NEG | ALL |
| 21.12 | Zero matches = misclassification — re-tag | `reference/index.md:82` | PROMPT | NEG | ALL |

---

## Section 22 — Agent-file schemas (IC-AGENT-001..020)

| # | File | Producer → Consumer | Schema location | Runner-parsed anchor |
|---|---|---|---|---|
| 22.1 | `findings.json` (IC-001) | explore/executor/verify/fix → planner, supervisor | `agent-file-schemas.md:9-44` | status enum |
| 22.2 | `progress.md` (IC-002) | explore/executor → planner, supervisor | `agent-file-schemas.md:46-62` | (none — pure prose) |
| 22.3 | `plan.md` (IC-003) | planner → executor (verbatim), diagnostic | `agent-file-schemas.md:64-94` | numbered steps |
| 22.4 | `handoff.md` / `handoff-spawn-<N>.md` (IC-004) | executor → next executor; `## Infrastructure blockers` → fix | `agent-file-schemas.md:96-149` | `## Status:`, `## Cap reason:`, `## Infrastructure blockers`, `### BLOCKER-<slug>` |
| 22.5 | `blocker.md` (IC-005) | executor → diagnostic | `agent-file-schemas.md:151-176` | (parsed) |
| 22.6 | `unblock-N.md` (IC-006) | diagnostic → next executor spawn | `agent-file-schemas.md:178-199` | `## Action for next executor spawn`: FILE_AND_SKIP / RETRY_WITH / SKIP_SPEC_GAP |
| 22.7 | `research-N.md` (IC-007) | research/fix (inline) → fix, bug-supervisor, escalation | `agent-file-schemas.md:201-228` | (parsed) |
| 22.8 | `verify-evidence-{iter}.md` (IC-008) | verify → fix (next attempt), bug-supervisor, research | `agent-file-schemas.md:230-260` | `## Status:` = FIXED / STILL_BROKEN |
| 22.9 | `supervisor-{N}-decision.md` (IC-009) | bug-supervisor → fix, research, future supervisors, escalation | `agent-file-schemas.md:262-313` | H1 = DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE |
| 22.10 | `supervisor-{N}-summary.md` (IC-010) | bug-supervisor → future supervisors, research | `agent-file-schemas.md:315-335` | ≤15 lines |
| 22.11 | `guidance.md` + `supervisor-decision.md` (IC-011, loop-level) | loop-supervisor → explore (next iter), runner decision logic | `agent-file-schemas.md:337-365` | H1 = CONTINUE / REDIRECT / STOP |
| 22.12 | `bug_history.json` (IC-012) | runner internal → fix, bug-supervisor, research, escalation | `agent-file-schemas.md:367-392` | (parsed) |
| 22.13 | `fix-history.md` (IC-013) | runner internal → platform-fix (repeat-failure detection) | `agent-file-schemas.md:394-408` | parsed by regex |
| 22.14 | `claims/completion-{TASK_ID}.json` (IC-014) | task-implementer/executor → runner verifier | `agent-file-schemas.md:410-435` | claim schema |
| 22.15 | `claims/rejection-{TASK_ID}.md` (IC-015) | runner verifier → next implementer/explore spawn | `agent-file-schemas.md:437-458` | (parsed) |
| 22.16 | `claims/platform-fix-*.json` + `platform-meta-fix-*.json` (IC-016a) | platform-fix → runner (cross-attempt summary) | `agent-file-schemas.md:460-514` | `<claim>{...}</claim>` trailer, out-of-scope variant fields |
| 22.17 | `bugs/<BUG-ID>/verify.sh` (IC-016b) | fix agent → runner | `agent-file-schemas.md:640-672` | exit-code contract |
| 22.18 | `attempt-N-diagnosis.md` (IC-017) | ci-diagnose → ci-fix (inlined) | `agent-file-schemas.md:516-543` | (parsed) |
| 22.19 | `attempt-N-local-{iter}.md` (IC-018) | ci-local-validate → ci-fix (next iter), runner PASS/FAIL routing | `agent-file-schemas.md:545-574` | `## Result:` = PASS / FAIL |
| 22.20 | `validate/{N}.md` (IC-019) | validate → vr-fix (next cycle), runner PASS/FAIL state | `agent-file-schemas.md:576-612` | `# Phase <slug> — Validation #<N>:` + PASS/FAIL |
| 22.21 | `review-{cycle}.md` (IC-020) | review → next review cycle, vr-fix (indirectly) | `agent-file-schemas.md:614-638` | H1 contains REVIEW-CLEAN or REVIEW-FIXES |

### Agent-file schema GAPS

| # | Gap | Source |
|---|---|---|
| 22a.1 | IC-AGENT-016 numbered twice (claims and verify.sh) — collision | reference audit §contradictions |
| 22a.2 | No CI re-parses every IC-AGENT-### entry's anchors against the running parser | reference audit §gap I |
| 22a.3 | `agent-file-schemas.md:674-679` says "update this file in same commit as writer changes" — relies on convention, not detector | reference audit §gap I |

---

## Section 23 — Preset behavior table (cross-reference)

How each preset answers the load-bearing questions. This is the actual current behavior of the wrapper layer; the runner layer treats every preset identically.

| Concern | poc | local | library | extension | public | enterprise |
|---|---|---|---|---|---|---|
| FR/SC numbering | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Non-Goals section | ✓ lightweight | ✓ | ✓ | ✓ | ✓ | ✓ |
| Edge Cases section | ✓ lightweight | ✓ data-loss focus | ✓ API-misuse focus | ✓ platform-event focus | ✓ hostile-input focus | ✓ full 11-category |
| Examples on FRs | optional | required on flagged | encouraged on public API | required on flagged | required on flagged | required on flagged |
| research.md depth | ultra-brief | full | full | full | full | full |
| data-model.md depth | omit | full | when applicable | when applicable | full | full |
| API contracts depth | omit | when applicable | critical (it IS the product) | when applicable | full | full |
| Complexity Tracking | omit | required | required | required | required | required |
| Phase Dependencies | omit | required | required | required | required | required |
| Interface contracts | omit | when shared state | when applicable | when applicable | required | required |
| Critical path | omit | required | required | required | required | required |
| Test plan matrix | omit | required | required | required | required | required |
| Test infrastructure (custom reporter) | omit | full | full + multi-env | full + host platform | full | full |
| Foundational infrastructure | omit | error + config + logging + CI/CD + Tier-1 sec | error + config + build + CI/CD + publish + docs | error + config + settings + storage + CI/CD + package + publish | full minus observability | full |
| Logging library | console.log | structured INFO | none (pluggable interface) | structured to host console | structured + correlation IDs | full |
| Error hierarchy | language defaults | full | full (public API) | full | full | full |
| Config management | hardcode | full | options objects | host settings API | full | full |
| Auth | none | none | n/a | host platform auth API | none unless admin endpoints | full |
| CORS | allow `*` | n/a | n/a | host-managed | restrictive | full |
| Rate limiting | none | n/a | n/a | n/a | per-IP | full |
| Security headers | none | n/a | n/a | host-managed | full baseline | full |
| Graceful shutdown | none | for long-running tools | n/a | host-managed | yes 30s | yes |
| Health checks | none | --check for daemons | n/a | n/a | /health only | /health + /ready |
| Security scanning | none | Tier 1 (+Tier 1.5 if public) | Tier 1 | Tier 1 + permission audit | Tier 1 + Tier 1.5 | Full |
| CI/CD pipeline | none | lint+test+sec | full + publish | full + store publish | full | full |
| Branching | direct-to-main | direct-to-main | feature branches | feature branches | feature branches preferred | feature branches |
| Fix-validate loop | implement-then-test | per phase | per phase | per phase | per phase | per phase |
| `[P]` parallel markers | n/a | yes | yes | yes | yes | yes |
| Done criteria | omit | required | required | required | required | required |
| Interface contract tags | omit | required | when applicable | when applicable | required | required |
| Code review | skip | full | full + API surface | full + permission scope | full | full |
| learnings.md | required | required | required | required | required | required |
| Spec amendment process | direct edit | supported | supported | supported | supported | supported |

### Preset behavior GAPS

| # | Gap | Note |
|---|---|---|
| 23.1 | Runner doesn't read preset from interview-notes.md | The runner enforces the same checks (fix-validate, review, runner-verified, proof-discipline) for poc as for enterprise |
| 23.2 | Preset defines what to author; nothing in preset defines what to enforce at runtime | The wrapper says "skip CI" for poc; the runner still runs fix-validate per phase with full review |
| 23.3 | No preset describes a runner-side budget ceiling (`$X per feature`, `Y max spawns`) | Cost discipline is global, not per-preset |
| 23.4 | No preset describes which proof-discipline gates apply | All-or-nothing; can't say "poc trusts agent claims, enterprise re-executes everything" |
| 23.5 | Preset overrides are scattered across phase docs; no single "this is what poc means" doc that captures both authoring + execution behavior | Hard to add a new preset; hard to audit a single preset's behavior |
| 23.6 | "library" and "extension" presets exist but their runtime behavior is identical to "local" — distinguishing characteristic is in authoring only | Could be runtime-distinct (e.g., library cares about cross-version compat, extension cares about permissions audit) |

---

## Section 24 — Observability of the runner itself

| # | Rule / property | Location | Enforcement | Notes |
|---|---|---|---|---|
| 24.1 | `logs/agent-{id}-{task_id}-{ts}.jsonl` per spawn (full stream-json) | runner audit §6 | CODE | unbounded growth |
| 24.2 | `logs/agent-{id}-{task_id}-{ts}.stderr` per spawn | runner audit §6 | CODE | |
| 24.3 | `logs/agent-{id}-{task_id}-{ts}.prompt.md` sidecar prompt | runner audit §6 | CODE | |
| 24.4 | `logs/agent-{id}-{task_id}-{ts}.hang.md` only on watchdog kill | runner audit §6 | CODE | |
| 24.5 | `specs/<feature>/run-log.jsonl` structured events (session_start, task_spawn, task_complete, vr_*, rv_*, runner_verify, feature_*, platform_*, pre_e2e_gate_*, agent_hang_kill, task-deps) | runner audit §6 | CODE | append-only |
| 24.6 | `specs/<feature>/attempts/{task_id}.jsonl` per-task summaries | runner audit §6 | CODE | |
| 24.7 | `specs/<feature>/reasoning/{seq}-{ts}-{kind}-{task_id}-agent{id}.md` extracted Reasoning section per spawn | runner audit §6 | CODE | unbounded growth |
| 24.8 | TUI repaints every 500ms with dep graph, scheduler activity (yellow if >30s idle), per-agent stream-json tails | runner audit §6 | CODE | |
| 24.9 | `HeadlessLogger` writes runner messages to log file; same event stream | runner audit §6 | CODE | |
| 24.10 | `verification.json` per phase with `tasks_verified[].{commands_run, artifacts_inspected, verdict, evidence, lie_check}` | `parallel_runner.py:868-898`, `proof-discipline.md` | CODE | |
| 24.11 | `runner-verified.json` per phase with deterministic re-verification result | runner audit §6 | CODE | |

### Runner-observability GAPS

| # | Gap | Source |
|---|---|---|
| 24a.1 | No global cost dashboard at runtime | runner audit §6 |
| 24a.2 | No cumulative session cost displayed in TUI | runner audit §6 |
| 24a.3 | No alerts on token spike | runner audit §6 |
| 24a.4 | `run-log.jsonl` has no rotation; O(n) re-scanned every iteration | runner audit §6, §8.6 |
| 24a.5 | `logs/` and `specs/<feature>/reasoning/` have no retention policy | runner audit §8.19 |
| 24a.6 | No system-level metric on "runner doing nothing useful for N minutes" beyond consecutive-noop | implicit |

---

## Section 25 — Stripe integration (first-class)

| # | Rule | Location | Enforcement | Payoff | Presets |
|---|---|---|---|---|---|
| 25.1 | Auto-detection keywords scan; explicit confirmation; default NO | `stripe.md:11-25`, `interview.md` | PROMPT | LOW | CONDITIONAL |
| 25.2 | Three keys: secret (server), publishable (client-safe), webhook signing (rotates per dev session) | `stripe.md:36-43` | CONVENTION | LOW | CONDITIONAL |
| 25.3 | Generated bundle indivisible — no partial Stripe | `stripe.md:46-50` | PROMPT | MED | CONDITIONAL |
| 25.4 | Scripts: stripe-listen-start.sh (idempotent JSON output), stripe-listen-stop.sh (PID-safe), stripe-webhook-secret.sh, sync-env.sh (PUBLIC_*-only filter) | `stripe.md:53-95` | TEMPLATE | NEG | CONDITIONAL |
| 25.5 | `stripe-cli` added to `flake.nix` | `stripe.md:99-110` | CODE (flake) | NEG | CONDITIONAL |
| 25.6 | Webhook handler: raw body, signature verify, idempotent via processed_stripe_events table, return 200 quickly, return 500 only on transient | `stripe.md:157-201` | PROMPT | HIGH | CONDITIONAL |
| 25.7 | Publishable key dual delivery: runtime fetch + build-time fallback | `stripe.md:203-216` | PROMPT | MED | CONDITIONAL |
| 25.8 | CLAUDE.md + test/e2e/README.md + RUNBOOK.md stanzas | `stripe.md:218-365` | PROMPT | LOW | CONDITIONAL |
| 25.9 | task-deps.json entry: `stripe-listen` with start/stop scripts, JSON schema, prereq list | `stripe.md:369-401` | CODE | NEG | CONDITIONAL |
| 25.10 | Task-list tagging: `[needs: stripe-listen]` with `Prereq:` line | `stripe.md:455-487` | CODE (runner reads + starts) | NEG | CONDITIONAL |
| 25.11 | Three live-key guardrails: pre-commit hook + gitleaks rule + .env.example warning | `stripe.md:403-448` | CI + CODE (gitleaks) + CONVENTION | NEG | CONDITIONAL |
| 25.12 | "If project later swaps Braintree/Adyen/Paddle, shape transfers" claim | `stripe.md:5` | CONVENTION (unverified — no parallel file exists) | n/a | CONDITIONAL |

---

## Section 26 — Pure docs-side smells (no obvious gap, but worth noting)

| # | Smell | Location |
|---|---|---|
| 26.1 | Zero-skip rule restated in 6 places (testing.md:140-183, validate-review.md:77, cicd.md:121-156, proof-discipline.md rule 2, reporters, verification.md:114) | reference audit §redundancy |
| 26.2 | Non-vacuous rule restated in 6 places (testing.md:137, cicd.md:43-100, pre-pr.md:66-86, proof-discipline.md rule 1, EXAMPLE-OUTPUT.md, reporters) | reference audit §redundancy |
| 26.3 | Tier taxonomy restated in 4 places (testing.md:35-54, validate-review.md:191, e2e-runtime.md, mcp-e2e-core.md) | reference audit §redundancy |
| 26.4 | Coverage matrix in 4 places (testing.md:294-325, proof-discipline.md rule 5, validate-review.md:75-76, cicd.md) | reference audit §redundancy |
| 26.5 | Real-runtime E2E in 4 places (testing.md:821-825, e2e-runtime.md:25-36, mcp-e2e-core.md, cicd.md) | reference audit §redundancy |
| 26.6 | `verify.sh` in 4 places (cost-guardrails.md:83-114, fix-agent-playbook.md:195-238, mcp-e2e-core.md:59-68, agent-file-schemas.md:640-672) | reference audit §redundancy |
| 26.7 | browser_evaluate vs browser_snapshot in 3 places (cost-guardrails.md:136-167, mcp-e2e-web.md:9-56, mcp-e2e-core.md:426-440) | reference audit §redundancy |
| 26.8 | State-Tool no-vision in 3 places (cost-guardrails.md, mcp-e2e-android.md:10-41, mcp-e2e-core.md:426-440) | reference audit §redundancy |
| 26.9 | flutter clean in 3 places (mcp-e2e-android.md:155-175, e2e-failure-patterns.md:262-355, fix-agent-playbook.md) | reference audit §redundancy |
| 26.10 | Read proof-discipline.md first in 2 places (validate-review.md:7, verification.md:6) | reference audit §redundancy |

---

## Section 27 — Structural observations (no specific rule)

| # | Observation | Source |
|---|---|---|
| 27.1 | Most rules use MANDATORY/MUST voice; presets override this; in practice MANDATORY ≠ mandatory | implicit, audit-wide |
| 27.2 | ~6 mechanically-enforced rules dominate; ~75 prose-only rules trail behind | reference audit §headline |
| 27.3 | The proof-discipline contract depends on project-side wrapper scripts emitting the JSON correctly; nothing audits the wrappers | reference audit §gap A |
| 27.4 | The runner has all the data to do diff-vs-claim verification but doesn't | runner audit §7, our discussion |
| 27.5 | The runner has all the data to count actual MCP interactions but trusts the agent's count | runner audit §7 |
| 27.6 | "Done when" criteria are agent-authored; nothing constrains the agent from writing itself a loose criterion | implicit, our discussion |
| 27.7 | Validator-enforced rules (~30 listed) depend on the validator agent — itself fallible | reference audit, audit-wide |
| 27.8 | The adversarial-stance machinery is well-built but its correctness depends on `_verifier_prompt()` having no bugs — single point of failure | reference audit §gap B |
| 27.9 | "Reasoning" appendix produces feedback that has no automated consumer | runner audit §8.20 |
| 27.10 | Layer-3 strict mode (refuse to advance to next spec_dir when current didn't reach all_complete) is the cleanest example of runner-enforced discipline | runner audit §3 |
| 27.11 | E2E roles bypass the index + CLAUDE.md to save tokens — context-dependent prompt assembly already happens, but only by role-type, not by preset | runner audit §2.1 |
| 27.12 | The runner re-executes test commands itself for runner-verified.json — this is the strongest anti-fake-work piece; could be extended | runner audit §7 |
| 27.13 | Capability stripping logs to stderr; agent doesn't see it; results in silent failure loop | runner audit §8.16 |
| 27.14 | `_check_untrusted_code_risk` substring match has no false-positive guard | runner audit §8.17 |
| 27.15 | `cost-config.json` override hook exists but only covers executor caps and role models — could be extended to gate enabling/disabling | runner audit §5 |
| 27.16 | Pricing tables are hand-maintained in two files with no source-of-truth pointer | runner audit §8.1 |
| 27.17 | `max_runs=100` per-feature is presented as a global cap in CLI help | runner audit §8.3 |
| 27.18 | Connection-error retry circuit-breaker has no upper bound — can cooldown indefinitely | runner audit §8.4 |
| 27.19 | `subprocess.run(..., timeout=600)` for runner-verify blocks main thread | runner audit §8.5 |
| 27.20 | Three concurrent views of finished agents (`self.agents`, `_recently_finished`, `_agent_done_tasks`) — comments mention past bugs from this | runner audit §8.7 |
| 27.21 | `_run_feature` is ~1,800 LOC inside one method; high blast radius for edits | runner audit §1, §8.2 |
| 27.22 | Some rules contradict by file (`testing.md:50` vs `:86-94` vs `:96-110`; `testing.md:156` vs `security.md:288`); agents grab the most permissive | reference audit §contradictions |
| 27.23 | Some duplications diverge (Nix-note 10+ copies, long version at 2368 includes sandbox+timeout guidance, CI versions are one-liners) | runner audit §2.14 |
| 27.24 | "Reasoning" feedback-loop channel ("Prompt feedback — missing") has no automated consumer mutating prompts | runner audit §8.20 |
| 27.25 | The wrapper-and-runner are interlinked but the runner has zero awareness of preset; preset is wrapper-time only | our discussion |
| 27.26 | No system-level concept of "what is enforced for this preset" vs "what is advisory for this preset" | our discussion |
| 27.27 | The "demote MANDATORY voice for prose-only rules" move is straightforward but would touch most reference files | implicit |
| 27.28 | The "make presets affect runtime behavior" move requires a config layer the runner currently lacks | our discussion |
| 27.29 | Both audits independently land on "code-enforced wins, prose-enforced loses" as the system's defining structural fact | both audits |
| 27.30 | The "done when must pin exact names" rule (tasks.md, §12.9) is one of the strongest agent-rationalization defenses but is still prose-only — the validator-enforced spec-conformance check (`validate-review.md:173-184`) is the closest enforcement and is itself an agent | implicit |

---

## Closing summary

Total rules inventoried: **~250** across 27 sections.

Distribution by enforcement strength (best estimate from tags above):

- **CODE** (mechanical, runner refuses): ~80
- **TEMPLATE** (shipped reporter exits non-zero): ~6
- **CI** (workflow file): ~20
- **VALIDATOR** (validate-review agent told to check): ~30
- **PROMPT** (agent compliance only): ~110
- **CONVENTION** (documented but no prompt enforces): ~15

Distribution by rationalization payoff:

- **HIGH** (hours-to-days work skipped): ~75
- **MED** (10min-1hr work skipped): ~55
- **LOW** (seconds-minutes): ~50
- **NEG** (skipping makes things harder): ~70

Highest-leverage observation: **the HIGH-payoff rules cluster in PROMPT and VALIDATOR enforcement, not CODE**. That's where rationalization wins and the system loses. Cells with HIGH × PROMPT or HIGH × VALIDATOR are where to either build mechanical enforcement or honestly downgrade the rule.

Distribution by preset applicability is highly skewed — ALL or NON-POC covers most rules. Very few rules are preset-specific in either direction, which confirms the structural observation that **the runner treats every preset the same** even though the wrapper presets differ widely.
