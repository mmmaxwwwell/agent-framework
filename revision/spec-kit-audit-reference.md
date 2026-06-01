# Spec-kit reference/ — rule & guardrail inventory

Scope: every file in `/home/max/git/agent-framework/.claude/skills/spec-kit/reference/` (37 markdown + 4 templates files). The goal is to map every prescriptive rule, where it lives, whether anything enforces it, and where rules contradict, overlap, or leave gaps relative to the user's goals (ship unattended quality, reduce time-per-feature, enforce a quality bar agents wouldn't self-impose, cost-controlled scaling). Known pain points: silent fake completion, ignored/contradictory rules, cost/token waste.

Legend for **Enforcement**:
- **Runner-enforced** = `parallel_runner.py` parses or executes this and refuses to advance on violation. Hardest enforcement.
- **CI-enforced** = a workflow file shipped to projects fails the build on violation.
- **Validator-enforced** = the validate/review agent (Part 1/Part 2 prompts) is told to mark FAIL. Soft — the validator is itself an agent.
- **Template-enforced** = a reporter/template ships code that exits non-zero.
- **Prose-only** = nothing executes the rule; an agent must read it and decide to comply. Highest-risk category.

---

## Part 1 — Per-file inventory

### `reference/index.md` (`reference/index.md:1-148`)

**Purpose.** Routing table that tells general-purpose agents (not E2E sub-agents) which reference files to read for a given task-kind + file-domain classification. Designed to keep prompts small via cache hits.

**Rules / guardrails.**
- "Do not read every file — read only what matches" (`reference/index.md:3`).
- E2E sub-agents skip the index entirely; the runner injects refs directly (`reference/index.md:7-14`).
- Classify task with exactly one `task:*` tag and all applicable `domain:*` tags before reading anything (`reference/index.md:16-71`).
- A row tagged `*` matches everything; read those always (`reference/index.md:80`).
- If two rows direct to same file, read once — cache hit covers re-read (`reference/index.md:81`).
- Zero matches = misclassification — re-tag (`reference/index.md:82`).

**Enforcement.** Prose-only. Index is a routing aid; no machinery checks an agent actually read what the index pointed to. Cache-hit math (`reference/index.md:147`) is the only feedback signal.

**Overlap.** Light overlap with `cost-guardrails.md § Reference injection` (which is the upstream rule for *why* indexes shouldn't be loaded by E2E sub-agents).

---

### `reference/testing.md` (`reference/testing.md:1-920` — 84 KB, the heaviest file)

**Purpose.** Defines the entire test taxonomy and the rules every test must satisfy: tiers, no-skip rule, structured output schema, shared-runtime safety, coverage, NixOS VM patterns, fuzz/perf/adversarial tests, real-runtime E2E.

**Rules / guardrails.**
- Every project MUST run unit + integration + E2E at every phase boundary; missing tier = false green (`reference/testing.md:3-13`).
- Test scripts declared in `package.json` MUST all run; no opt-out, no skip allowlist (`reference/testing.md:15-17`).
- Every user-facing artifact MUST have an E2E that runs it the way a user does (`reference/testing.md:19-21`).
- No `doCheck=false`, no `.skip`/`.skipIf`/`.only`/`xit`/`xdescribe`/`--skip-tests`/runtime guards, no `if(process.env.CI)` shortcuts (`reference/testing.md:27-32`).
- "When a test exposes a real bug, the fix goes in the *code*, not the test" — loosening assertions or raising timeouts is FAIL (`reference/testing.md:33`).
- Test tier taxonomy: unit (in-process, no network/DB), integration (real services, no UI runtime), E2E (full stack + platform runtime) (`reference/testing.md:39-43`).
- "Integration tests never touch the emulator/simulator/browser" (`reference/testing.md:47`).
- "E2E tests never substitute for integration tests" — diagnose 100× faster (`reference/testing.md:48`).
- "No mocking inside a tier's boundary" — only at the tier's outer edge (`reference/testing.md:50`).
- Every E2E flow has a user-flow integration mirror (`reference/testing.md:53`).
- Pre-E2E gate: setup.sh → write `env.sh` → run integration tests → escalation ladder (regular fix → meta-fix → BLOCKED.md) (`reference/testing.md:57-67`).
- Structural causes meta-fix should investigate when stalled — 8 enumerated patterns (`reference/testing.md:71-84`).
- Real servers, real processes, real DBs — mock only what needs human interaction (`reference/testing.md:86-94`).
- External-process boundary testing: spawn the real binary, send real JSON over real pipes (`reference/testing.md:96-110`).
- Structured test output: `test-logs/summary.json` + `failures/<name>.log`; canonical schema in `templates/EXAMPLE-OUTPUT.md` (`reference/testing.md:112-138`).
- **Non-vacuous assertion** (`pass + fail > 0`) (`reference/testing.md:137`).
- **Skip-as-failure**: `skip > 0` = FAIL (`reference/testing.md:138`).
- **Zero-skips rule** with 7 banned patterns + correct fail-fast `beforeAll` pattern (`reference/testing.md:140-183`).
- Runner-enforced: `skip > 0` is FAIL regardless of reporter output (`reference/testing.md:183`).
- 10 mandatory shared-runtime authoring rules (random IDs, no first-row reads, scoped cleanup, scoped assertions, `>=` not `==` on global metrics, self-contained cases, no seed-data assumptions, namespaced shared resources, account for runner concurrency model) (`reference/testing.md:224-262`).
- 10 mandatory shared-runtime review checks (detection heuristics for the same hazards) (`reference/testing.md:264-292`).
- Code coverage mandatory for every language/test suite, both terminal + file report (`reference/testing.md:294-325`).
- Acceptance scenario exerciser: auto-verifiable / CI-verifiable / manual classification (`reference/testing.md:327-350`).
- User-flow integration tests required: per-boundary tests don't catch cascade failures (`reference/testing.md:352-501`).
- 10 design patterns for user-flow tests (audio pipeline, process lifecycle, extension host, multi-service, first-run, config change, packaging/distribution, dependency compat, cross-application, NixOS VM/systemd) (`reference/testing.md:380-489`).
- Pre-PR gate is mandatory (`reference/testing.md:503-506`).
- Concurrency-safety: race detection mandatory in CI for concurrent code (Go `-race`, Rust Miri/Loom/TSan, Infer/RacerD for JVM) (`reference/testing.md:523-595`).
- Adversarial flow tests for every security boundary; cert + infrastructure attack matrices (`reference/testing.md:597-651`).
- Hardware-dependent tests: explicit coverage gap docs, CI tier strategy, multi-language coverage merging (`reference/testing.md:653-721`).
- Performance/benchmark: spec budgets become tests; p95 assertions; benchstat regression thresholds (`reference/testing.md:723-819`).
- Real-runtime E2E mandatory for projects targeting a platform (cross-references `e2e-runtime.md`) (`reference/testing.md:821-825`).
- E2E test harness decomposition rule: artifact build / env setup / bypasses / UI helpers / test itself = separate tasks (`reference/testing.md:827-857`).
- Fix-validate loop runs per-phase, not per-task; each fix gets fresh context; 10 attempt cap then BLOCKED.md (`reference/testing.md:859-877`).
- Security validation in same lifecycle: build→test→lint→security; failures use same fix-validate loop (`reference/testing.md:878-919`).

**Enforcement mix.**
- Runner-enforced: skip>0=FAIL (`testing.md:183`), pre-E2E gate (`testing.md:57-67`), per-phase fix-validate loop (`testing.md:859-877`), 10-attempt cap → BLOCKED.md.
- Template-enforced: non-vacuous + skip-as-failure are exit codes in `templates/test-reporter-*` files.
- Validator-enforced: tier placement, no-mock-inside-tier, error-path coverage — validate-review reads these but the validate-review agent is itself fallible (this is exactly what the May 22 incident burnt).
- Prose-only and the highest risk: real-server preference (`testing.md:86-94`), external process boundary tests (`testing.md:96-110`), user-flow integration tests (`testing.md:352-501`), adversarial flow tests (`testing.md:597-651`), perf tests (`testing.md:723-819`), shared-runtime authoring rules (`testing.md:224-262`) — all enforced by agents reading and deciding. NixOS VM systemd-readiness pattern (`testing.md:437-489`) is detailed prose with no detector.

**Overlap.** Massive.
- Zero-skip rule duplicated in `testing.md:140-183` + `validate-review.md:77` + `cicd.md:121-156` + `proof-discipline.md` (rule 2) + the reporter templates.
- Non-vacuous assertion duplicated in `testing.md:137` + `cicd.md:43-100` + `pre-pr.md:66-86` + `proof-discipline.md` (rule 1) + reporters.
- Tier taxonomy duplicated in `testing.md:35-54` + `validate-review.md:191` + `e2e-runtime.md` (E2E ≠ integration).
- Coverage matrix duplicated in `testing.md:294-325` + `proof-discipline.md` (rule 5) + `validate-review.md:75-76`.
- Fix-validate description duplicated in `testing.md:859-877` + `cicd.md:375-446` (CI-loop) + `validate-review.md` (validate vs review parts).
- Real-runtime testing in `testing.md:821-825` is just a pointer to `e2e-runtime.md`, but the latter restates most of the same content.

---

### `reference/proof-discipline.md` (`reference/proof-discipline.md:1-205`)

**Purpose.** The "claims are advertising, artifacts are state" canon. Codifies the May 22 belt-editor incident as the architectural reason proof artifacts (not commit messages, not completion JSONs) are the only acceptable input to the verifier.

**Rules / guardrails.**
- 9 numbered rules:
  1. Every gating step produces a JSON proof artifact with `status`, `executed`, `passed`, `failed`, `skipped`, `reason_if_zero` (`reference/proof-discipline.md:25-37`). `executed=0` is always FAIL.
  2. Skip without a runs-in-the-gate replacement = FAIL; `--allow-skip` ignored under CI/pre-pr (`reference/proof-discipline.md:39-48`).
  3. Cross-checkable: emit expected-count file at config-load time, verifier asserts `executed >= expected` (`reference/proof-discipline.md:50-60`).
  4. Build artifacts checked against manifest (`reference/proof-discipline.md:62-71`).
  5. **Coverage matrix mandatory**: parse route diff, parse test diff, every new route must have a test (`reference/proof-discipline.md:73-79`).
  6. Verifier reads artifacts, NOT claims: strip completion JSONs, commit messages, agent summaries from verifier's prompt (`reference/proof-discipline.md:81-97`).
  7. Verifier prompt MUST be adversarial — opener says "find the lie" and lists silent-skip / anchored-claim / pattern-matched / coverage-shortcut as failure patterns (`reference/proof-discipline.md:99-112`).
  8. `verification.json` schema — must contain `commands_run`, `artifacts_inspected`, `lie_check` per task (`reference/proof-discipline.md:114-143`).
  9. Runner refuses phases where any proof artifact has `executed=0` if the diff modifies code that artifact was supposed to cover (`reference/proof-discipline.md:145-149`).

**Enforcement.** Mostly **runner-enforced** by design — this is the file that says "the runner mechanically checks this." Rule 1, 6, 8, 9 are explicitly machine-checked. Rules 2-5, 7 still require the test wrapper or verifier prompt to be implemented properly; if a project's run-e2e.sh doesn't emit the JSON artifact, the runner has nothing to read (rule 1 is the load-bearing rule).

**Overlap.**
- Heavy with `validate-review.md` (`validate-review.md:7` says proof-discipline wins on conflict).
- Heavy with `verification.md` (rules 6, 7, 8 = the verifier mechanism).
- Light with `testing.md`/`cicd.md` on zero-skips, non-vacuous.

---

### `reference/validate-review.md` (`reference/validate-review.md:1-252`)

**Purpose.** Combined validate + review agent prompt-rules. The validate agent runs at every phase boundary; the review agent runs only if validate passes. This is the file that loops in proof-discipline at the agent layer.

**Rules / guardrails.**
- Read `proof-discipline.md` FIRST; on conflict it wins (`reference/validate-review.md:7`).
- Part 1: build → test → lint → security, in order, stop at first failure category; coverage proof mandatory before writing PASS (`reference/validate-review.md:9-25`).
- **Real-runtime verification for UI projects** (`reference/validate-review.md:17`): exercise changed routes against a real production build, not dev, not `javaScriptEnabled:false`. Hydration breakage detection — the exact May 22 surface.
- Code coverage mandatory; missing tools must be installed not skipped (`reference/validate-review.md:25,37-45`).
- Hung-test detection: run files individually past ~4 files, wrap in `timeout`, never retry hanging test (`reference/validate-review.md:27-34`).
- Missing-tool recovery: install via npm/uv/flake.nix, don't call "pre-existing" (`reference/validate-review.md:36-45`).
- CI workflow verification when `.github/workflows/` changed (`reference/validate-review.md:47-63`).
- Hard FAIL rules (`reference/validate-review.md:66-78`): unable to validate, zero test results, silent-skip wrapper, coverage matrix gap, any skipped test.
- Stub detection in production code (`reference/validate-review.md:80-86`) — grep for `"100.100.100.100"`, `"TODO"`, etc.
- Cross-boundary contract verification (`reference/validate-review.md:88-98`) — field names must match exactly between producer and consumer.
- Part 2 review: 6 spec-conformance checks (exact names, all specified steps, mechanism not just behavior, cross-boundary contracts, no stubs, UI completeness) (`reference/validate-review.md:173-184`).
- Test depth audit: 7 violations including no-skip-guards, correct tier, non-vacuous assertions, no mocking inside tier, error-path coverage, behavior-not-implementation, shared-runtime safety (`reference/validate-review.md:186-196`).
- Bug scan: exhaustive single pass; fix only "clearly wrong" things (`reference/validate-review.md:200-206`).
- Re-run tests after fixes (`reference/validate-review.md:208-210`).
- Don't read ROUTER.md, don't load skills (`reference/validate-review.md:247-248`).

**Enforcement.** Validator-enforced (the validate agent is itself an agent reading these rules and deciding). The runner backs some checks: PASS/FAIL anchors are parsed, `BLOCKED.md` after 10 attempts is automatic, review-clean vs review-fixes parsed.

**Overlap.** Repeats almost everything from `testing.md`, `proof-discipline.md`, and `verification.md`. Specifically: zero-skips, tier placement, no-mocks-inside-tier, error-path, shared-runtime checks, stub detection.

---

### `reference/verification.md` (`reference/verification.md:1-139`)

**Purpose.** Runner-side per-task verification. Agents propose `claims/completion-<TASK_ID>.json`; runner re-runs commands and checks files exist.

**Rules / guardrails.**
- Read proof-discipline first (`reference/verification.md:6`).
- LLMs rationalize failures — moves enforcement from agent reasoning to runner code (`reference/verification.md:8-16`).
- Claim format: task_id, status, summary, commands_run[], files_created[], files_modified[], screenshots[], mcp_interactions (`reference/verification.md:22-48`).
- Runner re-executes commands (exit codes must match) and checks files exist (`reference/verification.md:50-54`).
- MCP exploration tasks: ≥1 screenshot, mcp_interactions > 0, live evidence required (`reference/verification.md:58-62`).
- Tasks with `**Verify**:` field: runner extracts and executes the command; non-zero = fail (`reference/verification.md:64-68`).
- Scripted tasks: runner executes script after agent finishes; `bash -n` not sufficient (`reference/verification.md:70-72`).
- Agent MUST NOT edit `tasks.md` checkboxes — runner does it after verification (`reference/verification.md:81-93`).
- Independent verifier at phase boundary: read-only, adversarial prompt, no completion JSON / no validate records / no commit messages / no agent summaries (`reference/verification.md:96-122`).
- Verifier reads every proof artifact under `test-logs/` (`reference/verification.md:114`).
- 5 concrete May 22 failure patterns the verifier must detect: silent skip + green claim, anchored on prior claim, coverage shortcut (trainer not pro), test with hydration disabled, pattern-matched rule (`reference/verification.md:124-138`).

**Enforcement.** Runner-enforced for the mechanical parts (claim parsing, command re-execution, file existence). The adversarial verifier is itself an agent — "the verifier reads state" only works if the verifier's prompt is correctly stripped (rule 6 of proof-discipline). Risk: if runner has a bug in `_verifier_prompt()`, the verifier sees the lie.

**Overlap.** With `proof-discipline.md` (rules 6, 7, 8 directly), with `agent-file-schemas.md` IC-AGENT-014/015/016, with `validate-review.md`.

---

### `reference/fix-agent-playbook.md` (`reference/fix-agent-playbook.md:1-326`)

**Purpose.** General debugging heuristics for any fix agent the runner spawns. Reduces "cold start agents explore and guess" waste.

**Rules / guardrails.**
- Read the MCP launch probe first; trust it over other diagnostic sections (`reference/fix-agent-playbook.md:8-19`).
- Runtime-layer checks when probe is green: PATH diagnostics, run CLI yourself, compare wrapper vs raw binary (`reference/fix-agent-playbook.md:21-33`).
- Reproduce before hypothesizing — run the failing command live, capture, compare to diagnostic (`reference/fix-agent-playbook.md:35-46`).
- Health check disagreeing with log = the bug; do NOT raise timeout (`reference/fix-agent-playbook.md:48-62`).
- Stale processes poison diagnostics — kill ports + PID files before debugging setup timeouts (`reference/fix-agent-playbook.md:64-80`).
- Read the *failed* log, not all logs; stop at first ERROR/FATAL/panic line (`reference/fix-agent-playbook.md:82-88`).
- Check prior fix attempts before editing (`reference/fix-agent-playbook.md:90-99`).
- Verify by COLD re-run, not guarded re-run — "exit 0" with a port-already-up guard is not proof (`reference/fix-agent-playbook.md:101-114`).
- **Mtime check before claiming STILL_BROKEN** — service logs older than fix commit = debugging a ghost (`reference/fix-agent-playbook.md:116-136`).
- Default fix preference: root cause > symptom; smaller diffs; upstream-compatible; obvious test placeholders (`reference/fix-agent-playbook.md:138-150`).
- Runtime deps prefetched in flake.nix, not downloaded mid-test (`reference/fix-agent-playbook.md:152-166`).
- **Do NOT use curl/wget as substitute for E2E** — only for backend pre-flight or response cross-check (`reference/fix-agent-playbook.md:168-180`).
- What NOT to do: no BLOCKED.md/DEFER (runner decides), no `.skip`, no `sleep 30`, no scope expansion, no secrets in `.env` (`reference/fix-agent-playbook.md:182-193`).
- `verify.sh` is MANDATORY when closing an E2E bug — saves ~$12 per bug per iteration (`reference/fix-agent-playbook.md:195-238`).
- Out-of-scope claim format when file is read-only (`reference/fix-agent-playbook.md:240-301`).
- Final-message template: Root cause / Fix / Verification / Residual risk + `<claim>{...}</claim>` trailer (`reference/fix-agent-playbook.md:303-325`).

**Enforcement.** Mostly prose. `<claim>` trailer parsing IS runner-enforced (see `agent-file-schemas.md` IC-AGENT-016). `verify.sh` exit-code contract is runner-enforced. Mtime check, cold re-run, "don't curl" — all prose.

**Overlap.** With `e2e-failure-patterns.md` (probe interpretation), `cost-guardrails.md` (scripted verify first), `agent-file-schemas.md` (claim schema).

---

### `reference/cost-guardrails.md` (`reference/cost-guardrails.md:1-260`)

**Purpose.** Why the cost-related defaults in `parallel_runner.py` are what they are. Each rule has a $-amount post-mortem driver.

**Rules / guardrails.**
- Origin: $30 T096 post-mortem — 35% browser snapshots, 35% verify agent forensics, 15% Opus on mechanical roles, 25% hang-kill (`reference/cost-guardrails.md:13-25`).
- Role→model mapping: planner/diagnostic/supervisor/research on **Opus**; executor/fix/verify/crash-fix/build-fix on **Sonnet** (`reference/cost-guardrails.md:27-39`).
- Hang budgets per role (idle timeout): planner 8m, executor 8m, fix 12m, verify 8m, build-fix/crash-fix 20m; global hard cap 120m (`reference/cost-guardrails.md:44-61`).
- Work preservation on hang-kill: synthesize `handoff-spawn-N.md` with `Status: PARTIAL` (`reference/cost-guardrails.md:56-60`).
- Executor step cap: max 4 plan steps OR 10 min wall, then handoff + exit (`reference/cost-guardrails.md:64-80`).
- `EXECUTOR_MAX_SPAWNS_PER_ITER = 5` (`reference/cost-guardrails.md:72`).
- Scripted verify first: every closed bug needs `verify.sh`; 30s timeout; STATUS/EVIDENCE/COMMAND stdout format (`reference/cost-guardrails.md:83-114`).
- Handoff contract: parsed anchors `## Status:`, `## Cap reason:`, `## Next step to resume at:`, etc. (`reference/cost-guardrails.md:118-134`).
- `browser_evaluate` before `browser_snapshot` — 500-byte vs 330-KB delta is ~$10 (`reference/cost-guardrails.md:136-167`).
- Playwright MCP flags: `--snapshot-mode none`, `--console-level error` (`reference/cost-guardrails.md:169-181`).
- **Reference injection**: CLAUDE.md only for general-purpose roles; index.md only for general implementation agents; mcp-e2e split by platform; never inline reference content (`reference/cost-guardrails.md:183-204`).
- Page manifests: stable selectors at `specs/<feature>/validate/e2e/page-manifest/<route>.json` (`reference/cost-guardrails.md:206-213`).
- `code-review-graph` exclude rules: project-scaffolding / vendored / never-edited dirs go in `excludeDirs` (`reference/cost-guardrails.md:215-230`).
- `.specify/cost-config.json` override schema for role models + hang budgets + caps (`reference/cost-guardrails.md:232-252`).

**Enforcement.** Runner-enforced for the per-role model, hang timeouts, step cap, handoff schema, scripted-verify exit codes — these are constants and code in `parallel_runner.py`. `browser_evaluate before browser_snapshot` is prose-only (relies on agent compliance + the MCP env defaults in `mcp-e2e-core.md:426-438`).

**Overlap.** With `mcp-e2e-core.md`, `mcp-e2e-web.md`, `cost-reporting.md`, `code-review-graph.md`.

---

### `reference/cost-reporting.md` (`reference/cost-reporting.md:1-134`)

**Purpose.** How to read `run-log.jsonl` after the fact and what `cost_report.py` produces.

**Rules / guardrails.**
- Logged per agent: task_id, agent_id, status, exit_code, duration_s, model, input/output tokens (fresh / cache_read / cache_create) (`reference/cost-reporting.md:6-24`).
- `cost_report.py` produces grand total / by-model / by-phase / phase×model matrix / effectiveness signals (`reference/cost-reporting.md:48-63`).
- Effectiveness signals: target Executor Opus% = 0, target Verify Opus% = 0 (`reference/cost-reporting.md:58-60`).
- Pricing table (Opus / Sonnet / Haiku input / cache-read / cache-create / output) lives at top of script; edit there if Anthropic changes rates (`reference/cost-reporting.md:74-82`).
- **Prompt-caching strategy**: reference content NEVER inlined into prompt bodies; agents Read by absolute path; Read tool cache hits across spawns when paths are byte-stable (`reference/cost-reporting.md:86-106`).
- Tier-1 path lists hardcoded per role; do not build from runtime state (`reference/cost-reporting.md:95`).
- Editing a referenced file mid-run breaks cache_read → cache_create on next spawn (`reference/cost-reporting.md:103`).
- Legacy data: missing `model` → assumed Opus; flat `input_tokens` → priced as fresh input (`reference/cost-reporting.md:109-115`).
- Effectiveness debugging: if Verify Opus% > 0, run is against old runner OR launched before model change (`reference/cost-reporting.md:117-123`).

**Enforcement.** Runner-emitted (logs are written by `parallel_runner.py`), but the rules are descriptive — they constrain *how to write the prompts* so the cache works. Inlining reference content into a prompt is a programmer-side mistake the file warns against; the cache-cost discipline is enforced by the run-log + cost report being read by humans.

**Overlap.** With `cost-guardrails.md` (model mapping), with itself.

---

### `reference/cicd.md` (`reference/cicd.md:1-572`)

**Purpose.** Pipeline-stage requirements, non-vacuous CI assertions, skip-as-failure CI rule, security pipeline, Snyk integration, default-branch readiness, agentic CI feedback loop.

**Rules / guardrails.**
- Pipeline stage order: lint → build → unit → integration → security → contract → E2E → deploy (`reference/cicd.md:6-16`).
- Build/release/run separation; pipeline as code (`reference/cicd.md:18-30`).
- Merge-blocking gates: tests, **vacuous passes**, critical/high CVEs, secrets, lint, build failures (`reference/cicd.md:32-40`).
- **Non-vacuous CI validation** with YAML patterns for JUnit XML / Go JSON / security scanners (`reference/cicd.md:42-119`).
- Verification step MUST be separate with `exit 1` — summary steps don't gate merges (`reference/cicd.md:115-119`).
- **Skip-as-failure CI validation**: `skip > 0` → exit non-zero (`reference/cicd.md:121-156`).
- `continue-on-error: true` allowed only for security baselines / optional token-gated steps; NEVER on test execution (`reference/cicd.md:158-165`).
- Security scan reporting: SARIF, PR annotations, README badges, SBOM (`reference/cicd.md:167-174`).
- Snyk for open-source (free tier); README CI Setup section with secret reference table (`reference/cicd.md:176-270`).
- Artifact generation per run: test results / SBOM / security summary / coverage / build artifacts (`reference/cicd.md:272-280`).
- Pre-release artifact availability: CI workflow builds ALL artifacts, not just runs tests; release workflow only adds signing/versioning (`reference/cicd.md:282-307`).
- **Default branch readiness**: before PR, verify badges, workflow_run triggers, license, release config exist on default branch (`reference/cicd.md:309-334`).
- Observable output validation post-CI: badges (curl + check for "not found"/"not specified"/etc.), artifacts (`gh run view --json artifacts`), acceptance scenarios (`reference/cicd.md:336-373`).
- Local security scan in fix-validate loop (`reference/cicd.md:375-446`).
- Local CI workflow validation: actionlint, command reproducibility, artifact path verification, secret refs, action pin warnings, workflow_run chain integrity (`reference/cicd.md:448-509`).
- Third-party action version pinning: check latest release, read action.yml for valid inputs (`reference/cicd.md:491-505`).
- **Agentic CI feedback loop**: `[needs: gh, ci-loop]` tag → local-validate-first → push → poll → diagnose → fix → validate, 20 local iterations per attempt, 50 attempt cap (`reference/cicd.md:511-571`).
- CI parity in local validation: agent reads ALL workflows, runs every `run:` command including from release workflows (`reference/cicd.md:533-541`).
- Multi-build-system: a project with `go.mod` + `android/build.gradle.kts` must pass BOTH (`reference/cicd.md:541-542`).

**Enforcement.** Mix. The YAML patterns in `reference/cicd.md:42-100` are concrete and copy-pasteable (CI-enforced when used). The agentic CI loop is runner-enforced. Many "validators MUST run X" rules are validator-enforced (the validate agent reads them).

**Overlap.** Non-vacuous + skip-as-failure restated 4 times across `testing.md`, `proof-discipline.md`, `pre-pr.md`, `cicd.md`. Default-branch readiness is the closest thing to a unique rule here.

---

### `reference/pre-pr.md` (`reference/pre-pr.md:1-177`)

**Purpose.** The single command (`make pre-pr` / `npm run pre-pr`) that runs every quality gate locally before pushing. Repeatable post-implementation gate.

**Rules / guardrails.**
- One `pre-pr` target per project (`reference/pre-pr.md:8-24`).
- Order: build → test → lint → security → non-vacuous check → E2E → CI workflow syntax (`reference/pre-pr.md:26-37`).
- **Multi-build-system discovery**: pre-pr scans for manifests and runs each system's commands (`reference/pre-pr.md:40-64`).
- Non-vacuous assertion: assert test counts > 0 per suite (`reference/pre-pr.md:66-86`).
- CI workflow validation when `.github/workflows/` modified: YAML syntax (actionlint), pins, command reproducibility, artifact paths, secret refs documented (`reference/pre-pr.md:88-102`).
- E2E in pre-PR: timeout 20m, retry 2x, `SKIP_E2E=1` bypass, run LAST (`reference/pre-pr.md:104-119`).
- pre-pr runs SAME checks as CI in SAME order with SAME tools (`reference/pre-pr.md:121-134`).
- pre-pr subsumes fix-validate loop's checks (`reference/pre-pr.md:136-145`).

**Enforcement.** Project-side (each project must implement the script). The wrapper script is what the May 22 incident's `run-e2e.sh` was — the very thing that silently `exit 0`'d. Rule says agents must build it correctly, but the load-bearing enforcement is in `proof-discipline.md` rule 2.

**Overlap.** With `cicd.md`, `testing.md` (E2E rules), `e2e-runtime.md`.

---

### `reference/e2e-runtime.md` (`reference/e2e-runtime.md:1-545`)

**Purpose.** Real-runtime E2E testing principles, side-by-side architecture, readiness checks, bypasses for hardware features, multi-runtime orchestration, MCP-driven exploration.

**Rules / guardrails.**
- Every platform-targeting project MUST have E2E against the real runtime (`reference/e2e-runtime.md:1-12`).
- Runtime selection table: Android = QEMU emulator (NOT Robolectric), iOS = simulator, web = real headless browser (NOT jsdom), desktop = real binary with display (`reference/e2e-runtime.md:13-23`).
- "What real means" anti-patterns: Robolectric/jsdom hide bugs (`reference/e2e-runtime.md:25-36`).
- **Side-by-side, NOT nested** runtimes (CI doesn't have nested KVM) (`reference/e2e-runtime.md:37-66`).
- Readiness checks per runtime with timeouts (`reference/e2e-runtime.md:68-106`).
- Test bypass mechanisms for hardware features (camera/biometrics/GPS/NFC/etc.) — must be debug-build-only (`reference/e2e-runtime.md:108-126`).
- UI automation patterns per platform (`reference/e2e-runtime.md:128-213`).
- Multi-runtime orchestration via shell script: phases for infra start, runtime boot, readiness, test, log collection (`reference/e2e-runtime.md:215-262`).
- Log collection per runtime: logcat, console, syslog, journal, packet capture (`reference/e2e-runtime.md:251-262`).
- Single-runtime parallelism constraint: don't `[P]` mark tasks sharing one emulator (`reference/e2e-runtime.md:266-279`).
- Flakiness handling: retry wrapper 2-3x, generous timeouts 2-3x expected, explicit waits never `sleep`, idempotent test setup, deterministic test data (`reference/e2e-runtime.md:282-316`).
- CI infrastructure per runtime; KVM access for bubblewrap sandbox (`reference/e2e-runtime.md:318-355`).
- Backend services setup via `test/e2e/setup.sh` + `test/e2e/teardown.sh`; idempotent; writes `env.sh` (`reference/e2e-runtime.md:377-450`).
- adb reverse for Android host-port bridging — gated on `E2E_WANT_EMULATOR=1`, reapplied every run (`reference/e2e-runtime.md:434-453`).
- Task generation guidance for E2E infra tasks (`reference/e2e-runtime.md:472-499`).
- MCP-driven exploration vs scripted E2E: complementary not competing (`reference/e2e-runtime.md:501-512`).
- Post-loop regression check: full test suite after E2E loop (`reference/e2e-runtime.md:524-535`).

**Enforcement.** Mostly prose. Runtime selection (no Robolectric, no jsdom) is the policy rule most likely to be silently broken by an agent reaching for the easier option. Backend setup script convention is runner-enforced (the runner calls `test/e2e/setup.sh` if it exists).

**Overlap.** With `testing.md § Real-runtime E2E testing`, `mcp-e2e-core.md`, `mcp-e2e-android.md`, `mcp-e2e-web.md`, `e2e-failure-patterns.md`.

---

### `reference/e2e-failure-patterns.md` (`reference/e2e-failure-patterns.md:1-441`)

**Purpose.** Library of known failure signatures with match-regexes, diagnostic commands, ranked fixes, and anti-patterns. Runner matches and injects only relevant signatures into the fix prompt.

**Rules / guardrails (per signature).**
- `port-timeout-but-service-ready`: IPv4/IPv6 binding mismatch; fix bind, not timeout (`e2e-failure-patterns.md:22-57`).
- `config-validation-missing-required`: `.env` placeholders; populate with obvious test values, not real keys (`e2e-failure-patterns.md:61-98`).
- `service-crash-on-boot`: read the stack trace; never restart in a loop (`e2e-failure-patterns.md:101-126`).
- `stale-process-guard-skipped-restart`: kill stale PIDs; improve teardown not setup (`e2e-failure-patterns.md:128-160`).
- `migration-already-applied`: make idempotent; wiping pgdata is OK in dev/E2E only (`e2e-failure-patterns.md:162-193`).
- `browser-install-hang`: Playwright wants Chrome, Nix has Chromium; fix in nix-mcp-debugkit wrapper; never retry, never preinstall, never bundle google-chrome (`e2e-failure-patterns.md:196-259`).
- **`stale-android-apk-after-source-fix`**: Gradle incremental cache lies; `flutter clean` mandatory after source change; verify by APK content-grep not build log (`e2e-failure-patterns.md:262-355`).
- `emulator-boot-timeout`: AVD/KVM/headless flags; project-specific (`e2e-failure-patterns.md:358-381`).
- `mcp-launch-failed`: bwrap + `nix run` writes to nix store; placeholder binary; missing shared lib; protocol mismatch (`e2e-failure-patterns.md:386-423`).
- `mcp-exits-clean-within-5s`: historical — was a runner bug, not a server bug; don't add per-repo keepalive wrappers (`e2e-failure-patterns.md:425-441`).

**Enforcement.** Runner matches failure regex → injects matching signature into fix prompt. Anti-patterns are prose rules the fix agent reads. The "don't add keepalive wrappers" rule is the kind of rule that gets ignored because agents see what worked in some other project.

**Overlap.** With `mcp-e2e-android.md` (stale-apk pattern repeats verbatim in two places), `mcp-e2e-core.md` (mcp-launch-failed), `fix-agent-playbook.md` (probe interpretation).

---

### `reference/mcp-e2e-core.md` (`reference/mcp-e2e-core.md:1-481`)

**Purpose.** Platform-neutral E2E loop — findings format, supervisor flow, regression fast-path, env file convention, MCP server env defaults.

**Rules / guardrails.**
- Agents use MCP tools DIRECTLY — never write scripts/prompt templates as deliverables (`reference/mcp-e2e-core.md:15-30`).
- Loop: explore → findings → research → fix → rebuild → verify → loop; 3 fix attempts per bug → supervisor; 5 supervisors → BLOCKED.md (`reference/mcp-e2e-core.md:42-57`).
- Scripted verify-first: `verify.sh` required when closing a bug (`reference/mcp-e2e-core.md:59-68`).
- Per-bug file structure: research-N.md, history.json, fix-approach-latest.md, verify.sh, verify-evidence-N.md, supervisor-N-summary.md, supervisor-N-decision.md, BLOCKED.md (`reference/mcp-e2e-core.md:70-84`).
- Research agent on every new bug + on supervisor REDIRECT_RESEARCH (`reference/mcp-e2e-core.md:86-91`).
- Verify-evidence structure: Actions / Observed / Expected / Delta (`reference/mcp-e2e-core.md:94-101`).
- Bug supervisor decisions: DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE; max 5 supervisors per bug (`reference/mcp-e2e-core.md:104-117`).
- Post-loop regression check: full test suite after E2E loop (`reference/mcp-e2e-core.md:120-127`).
- Regression tests MUST be behavioral, not visual/render tests; specify state transition not text-to-assert (`reference/mcp-e2e-core.md:129-155`).
- Findings.json schema with status enum (`reference/mcp-e2e-core.md:157-200`).
- Context window management: 1 screen/flow per task; role-appropriate models; bounded executor spawns; save screenshots to disk (`reference/mcp-e2e-core.md:202-237`).
- State-verification shortcut: curl to admin API ALLOWED for state assertions (not for UI actions) (`reference/mcp-e2e-core.md:239-261`).
- Crash recovery: context overflow = recoverable; MCP/auth = STOP (`reference/mcp-e2e-core.md:263-269`).
- Skip rebuild when no changes (`reference/mcp-e2e-core.md:271-277`).
- Regression fast-path per platform: spec file with first-line signature `// regression for <TASK_ID>` (`reference/mcp-e2e-core.md:279-313`).
- Backend service connection info: env + env.sh files (`reference/mcp-e2e-core.md:315-347`).
- Nix-first projects: pin nix-mcp-debugkit as flake input (`reference/mcp-e2e-core.md:349-370`).
- Playwright JS/Native version skew: pin JS version to Nix-supplied version (`reference/mcp-e2e-core.md:372-424`).
- MCP server env defaults: `MCP_PREFER_SNAPSHOT`, `MCP_BROWSER_NO_AUTO_SCREENSHOT`, `MCP_ANDROID_DEFAULT_NO_VISION` (`reference/mcp-e2e-core.md:426-440`).
- One screen/flow per task (`reference/mcp-e2e-core.md:441-466`).
- `UI_FLOW.md` is the explore agent's primary guide (`reference/mcp-e2e-core.md:468-481`).

**Enforcement.** Mix. Loop structure, supervisor cap, regression fast-path signature, MCP env vars, scripted verify exit codes — all runner-enforced. "Use MCP tools directly, don't write scripts" — prose. "Don't curl as substitute for UI" — prose.

**Overlap.** With `cost-guardrails.md` (model/cap/scripted verify), `fix-agent-playbook.md` (verify.sh), `mcp-e2e-web.md` and `mcp-e2e-android.md` (cost rules), `agent-file-schemas.md` (findings, history, supervisor schemas all cross-referenced).

---

### `reference/mcp-e2e-web.md` (`reference/mcp-e2e-web.md:1-143`)

**Purpose.** Platform-specific web MCP rules.

**Rules / guardrails.**
- HARD cost rule: `browser_evaluate` (500 bytes) default; `browser_snapshot` (~330 KB) is fallback (`reference/mcp-e2e-web.md:9-42`).
- When snapshot IS right: first visit to unfamiliar page; one shot then switch (`reference/mcp-e2e-web.md:45-56`).
- Page manifests: stable selectors at `specs/<feature>/validate/e2e/page-manifest/<route>.json` (`reference/mcp-e2e-web.md:57-100`).
- Manifest stale → fall back to snapshot, file finding, update (`reference/mcp-e2e-web.md:95-100`).
- Regression spec writing: locator from snapshot; first line `// regression for <TASK_ID>` (`reference/mcp-e2e-web.md:102-111`).
- Browser MCP tool catalog (`reference/mcp-e2e-web.md:113-128`).
- Common failure patterns + fixes table (`reference/mcp-e2e-web.md:130-137`).

**Enforcement.** Prose + MCP env var defaults. The cost rule is the load-bearing rule from `cost-guardrails.md` restated for the web platform.

**Overlap.** With `cost-guardrails.md`, `mcp-e2e-core.md`.

---

### `reference/mcp-e2e-android.md` (`reference/mcp-e2e-android.md:1-181`)

**Purpose.** Platform-specific Android MCP rules.

**Rules / guardrails.**
- HARD cost rule: `State-Tool` without `use_vision` is default; vision only for bug evidence; every vision call must produce a finding (`reference/mcp-e2e-android.md:10-35`).
- 20-screenshot cap per session; save to disk, don't re-read (`reference/mcp-e2e-android.md:33-39`).
- `MCP_ANDROID_DEFAULT_NO_VISION=1` is the runner-injected default (`reference/mcp-e2e-android.md:39-41`).
- Tool catalog (`reference/mcp-e2e-android.md:43-56`).
- Regression spec: first-line signature; per-app location in multi-app monorepos (`reference/mcp-e2e-android.md:58-101`).
- Multi-app monorepos: `[android-app: <dir>]` annotation on every `[needs: mcp-android]` task (`reference/mcp-e2e-android.md:103-143`).
- Don't set project-wide `ANDROID_BUILD_ROOT` (`reference/mcp-e2e-android.md:131-137`).
- Common infrastructure issues + fixes table (`reference/mcp-e2e-android.md:145-152`).
- Platform boot: emulator + APK build + install (`reference/mcp-e2e-android.md:155-176`).
- `flutter clean` MANDATORY after any source change — full justification + verify pattern (`reference/mcp-e2e-android.md:159-175`).

**Enforcement.** MCP env defaults runner-enforced. Cost ratio counted by `PlatformDriver.cheap_vs_expensive_calls` (`reference/mcp-e2e-android.md:24-27`). flutter clean rule duplicated; verify.sh in `e2e-failure-patterns.md` does the APK content-grep.

**Overlap.** With `e2e-failure-patterns.md` (stale-apk), `cost-guardrails.md`, `mcp-e2e-core.md`.

---

### `reference/mcp-e2e-ios.md` (`reference/mcp-e2e-ios.md:1-28`)

**Purpose.** iOS MCP rules (deferred — no regression fast-path yet).

**Rules / guardrails.**
- Boot via xcrun simctl + xcodebuild (`reference/mcp-e2e-ios.md:11-14`).
- Cost rule mirrors Android: cheap structured tool default; vision for bug evidence only (`reference/mcp-e2e-ios.md:17-21`).
- iOS tasks cycle through full explore-loop every run; keep tasks narrow (`reference/mcp-e2e-ios.md:23-27`).

**Enforcement.** Prose-only at present.

---

### `reference/mcp-e2e.md` (`reference/mcp-e2e.md:1-29`)

**Purpose.** Stub pointing at the platform-specific splits, with cost-driven rationale for the split.

**Rules / guardrails.**
- Read core + the one platform file matching `mcp_caps`; don't load all three (`reference/mcp-e2e.md:5-18`).
- Cost rationale: 9.6k tokens × 300 turns × $0.30/M = $0.86 wasted per agent (`reference/mcp-e2e.md:20-26`).

**Enforcement.** Runner does the injection automatically (per `cost-guardrails.md`); the file is reader-facing only.

---

### `reference/agent-file-schemas.md` (`reference/agent-file-schemas.md:1-680`)

**Purpose.** The implicit communication contracts (IC-AGENT-001 .. IC-AGENT-020) for every file the runner-spawned agent roles produce / consume.

**Rules / guardrails.** Each IC-AGENT-NNN entry specifies writer / readers / format / location / runner-parsed anchors / required fields / lifecycle.
- IC-AGENT-001: `findings.json` (`agent-file-schemas.md:9-44`).
- IC-AGENT-002: `progress.md` (`agent-file-schemas.md:46-62`).
- IC-AGENT-003: `plan.md` (`agent-file-schemas.md:64-94`).
- IC-AGENT-004: `handoff.md` / `handoff-spawn-<N>.md` with parsed anchors `## Status:`, `## Cap reason:`, `## Infrastructure blockers`, `### BLOCKER-<slug>` (`agent-file-schemas.md:96-149`).
- IC-AGENT-005: `blocker.md` (`agent-file-schemas.md:151-176`).
- IC-AGENT-006: `unblock-N.md` with `## Action for next executor spawn` = FILE_AND_SKIP | RETRY_WITH | SKIP_SPEC_GAP (`agent-file-schemas.md:178-199`).
- IC-AGENT-007: `research-N.md` (`agent-file-schemas.md:201-228`).
- IC-AGENT-008: `verify-evidence-{iter}.md` with `## Status:` = FIXED | STILL_BROKEN (`agent-file-schemas.md:230-260`).
- IC-AGENT-009: `supervisor-{N}-decision.md` with H1 = DIRECT_FIX | REDIRECT_RESEARCH | ESCALATE (`agent-file-schemas.md:262-313`).
- IC-AGENT-010: `supervisor-{N}-summary.md` ≤15 lines (`agent-file-schemas.md:315-335`).
- IC-AGENT-011: loop-level `guidance.md` + `supervisor-decision.md` with H1 = CONTINUE | REDIRECT | STOP (`agent-file-schemas.md:337-365`).
- IC-AGENT-012: `bug_history.json` (`agent-file-schemas.md:367-392`).
- IC-AGENT-013: `fix-history.md` (parsed by regex) (`agent-file-schemas.md:394-408`).
- IC-AGENT-014: `claims/completion-{TASK_ID}.json` (`agent-file-schemas.md:410-435`).
- IC-AGENT-015: `claims/rejection-{TASK_ID}.md` (`agent-file-schemas.md:437-458`).
- IC-AGENT-016 (a): `claims/platform-fix-*.json` and `platform-meta-fix-*.json` with `<claim>` trailer parsed from agent output (`agent-file-schemas.md:460-514`).
- IC-AGENT-016 (a) out-of-scope variant with `out_of_scope: true`, `proposed_diff`, `target_path` (`agent-file-schemas.md:484-512`).
- Repeat-same-root-cause detection: two consecutive `verified: false` claims with same root cause → BLOCKED.md (`agent-file-schemas.md:514`).
- IC-AGENT-017: `attempt-N-diagnosis.md` (CI loop) (`agent-file-schemas.md:516-543`).
- IC-AGENT-018: `attempt-N-local-{iter}.md` with `## Result:` = PASS | FAIL (`agent-file-schemas.md:545-574`).
- IC-AGENT-019: `validate/{N}.md` with `# Phase <slug> — Validation #<N>:` and PASS/FAIL (`agent-file-schemas.md:576-612`).
- IC-AGENT-020: `review-{cycle}.md` with H1 containing REVIEW-CLEAN or REVIEW-FIXES (`agent-file-schemas.md:614-638`).
- IC-AGENT-016 (b): `bugs/<BUG-ID>/verify.sh` exit-code contract (`agent-file-schemas.md:640-672`).
- Schema maintenance: update this file in same commit as writer changes; don't inline schemas into prompts (`agent-file-schemas.md:674-679`).

**Enforcement.** Runner-enforced — every anchor here is parsed by `parallel_runner.py`. Drift between writer and this file means the runner silently misroutes. There is a numbering collision: two ICs labeled IC-AGENT-016 (claims and verify.sh) — they collide in the file (`agent-file-schemas.md:460` and `agent-file-schemas.md:640`).

**Overlap.** Cross-references nearly every other reference file.

---

### `reference/security.md` (`reference/security.md:1-341`)

**Purpose.** Security baseline: input validation, auth, CORS, secrets, headers, scanning, fuzzing.

**Rules / guardrails.**
- Validate at edge: API endpoints, form handlers, CLI args, file readers, message consumers; type + length + format + encoding (`reference/security.md:6-16`).
- Boundary validation MUST be covered by integration tests (`reference/security.md:16`).
- Auth: bcrypt/scrypt/argon2 never MD5/SHA; token expiration; rate-limit failed attempts; "invalid credentials" not "user not found"/"wrong password" (`reference/security.md:18-25`).
- CORS default restrictive, NOT `*` (`reference/security.md:27-29`).
- Secrets: env vars or secret managers only; `.env`/`credentials.json`/`*.pem` in `.gitignore`; pre-commit Gitleaks hook (`reference/security.md:31-36`).
- 7 mandatory HTTP security headers with values (`reference/security.md:37-50`).
- Local scanner commands with JSON output to `test-logs/security/<scanner>.json` (`reference/security.md:53-83`).
- summary.json aggregates findings per scanner (`reference/security.md:85-100`).
- SARIF outputs for GitHub Security tab (`reference/security.md:102-130`).
- Finding classification: dep vuln / SAST / secret / false positive — never suppress without justification (`reference/security.md:132-147`).
- Tier 1 mandatory scanners (free): Trivy, OSV-Scanner, ecosystem audit, Semgrep, CodeQL, Gitleaks, TruffleHog, GitHub Secret Scanning, SBOM via Trivy (`reference/security.md:149-163`).
- Tier 1.5 OSS-free: Snyk, SonarCloud, OpenSSF Scorecard, Dependency Review, ZAP (`reference/security.md:165-175`).
- Tier 2 paid + Tier 3 ecosystem-specific (`reference/security.md:177-202`).
- Fuzz testing required for: wire protocol parsers, binary deserializers, crypto surrounding code, input validators (`reference/security.md:204-221`).
- Tools per language: Go `testing.F`, Rust cargo-fuzz, C/C++ AFL++/libFuzzer, JVM Infer/RacerD (`reference/security.md:223-269`).
- CI integration: regression every PR, code-change fuzz 5-10m, nightly 30-60m, weekly 2-8h (`reference/security.md:271-310`).
- Crash handling: input saved, becomes regression test, minimize before committing (`reference/security.md:312-319`).
- Real-world examples — OSS-Fuzz finds 20-year-old OpenSSL CVE (`reference/security.md:321-331`).

**Enforcement.** CI-enforced when scanners run with `--severity-threshold=high` and don't have `continue-on-error: true`. Validator-enforced in the fix-validate loop. The "never suppress without justification" rule is prose.

**Overlap.** With `cicd.md § Security scan reporting`, with `validate-review.md § Security`, with `testing.md § Adversarial flow tests`.

---

### `reference/stripe.md` (`reference/stripe.md:1-534`)

**Purpose.** First-class dependency reference for Stripe. Bundled scripts, env management, webhook contract, RUNBOOK, live-key guardrails.

**Rules / guardrails.**
- Auto-detection keywords + explicit confirmation default `No` (`reference/stripe.md:11-25`).
- Three keys: secret (server-side), publishable (client-safe), webhook signing (rotates per dev session) (`reference/stripe.md:36-43`).
- Generated bundle is indivisible — no partial Stripe (`reference/stripe.md:46-50`).
- Scripts: `stripe-listen-start.sh` (idempotent JSON-output), `stripe-listen-stop.sh` (PID-safe), `stripe-webhook-secret.sh`, `sync-env.sh` (PUBLIC_*-only filter) (`reference/stripe.md:53-95`).
- flake.nix adds `stripe-cli` (`reference/stripe.md:99-110`).
- `.env.example` with explicit live-keys-never-here warning (`reference/stripe.md:113-154`).
- Webhook handler contract: raw body, signature verification, idempotent via `processed_stripe_events` table, return 200 quickly, return 500 only on transient (`reference/stripe.md:157-201`).
- Publishable key dual delivery: runtime fetch + build-time fallback (`reference/stripe.md:203-216`).
- CLAUDE.md stanza, test/e2e/README.md stanza, RUNBOOK.md 8-section stanza (`reference/stripe.md:218-365`).
- task-deps.json entry (`reference/stripe.md:369-401`).
- Live-key guardrails: pre-commit hook + gitleaks rule + .env.example warning — three layers (`reference/stripe.md:403-448`).
- Tasks driving real Stripe flows tagged `[needs: stripe-listen]` (`reference/stripe.md:455-487`).

**Enforcement.** Live-key guardrails are CI-enforced (gitleaks rule), pre-commit-enforced, and prose-enforced. Listener lifecycle is runner-enforced (`stripe-listen` is in task-deps and is phase-scoped).

**Overlap.** With `cicd.md` (gitleaks rule), with `agent-file-schemas.md` (task-deps).

---

### `reference/code-review-graph.md` (`reference/code-review-graph.md:1-374`)

**Purpose.** First-class dependency reference for code-review-graph. Set up via Nix flake input + `mkShellHook`; runner integrates at every phase.

**Rules / guardrails.**
- Treat the graph with same weight as Stripe / platform target (`reference/code-review-graph.md:6-12`).
- Use the graph wherever git grep/rg would fall short — relationships, not lines (`reference/code-review-graph.md:21-37`).
- mkShellHook options table: projectName, buildOnEnter, watch, serveMcp (default false — Claude Code starts via .mcp.json stdio), autoInstall (`reference/code-review-graph.md:76-85`).
- autoInstall passes `--no-instructions` because spec-kit owns the CLAUDE.md stanza (`reference/code-review-graph.md:87-100`).
- excludeDirs writes managed-block in `.code-review-graphignore`, content-addressed idempotent (`reference/code-review-graph.md:104-141`).
- DEFAULT_IGNORE_PATTERNS covers node_modules etc. — only add project-specific (`reference/code-review-graph.md:143-157`).
- Good vs bad candidates for excludeDirs (`reference/code-review-graph.md:159-180`).
- Glob syntax limited: no negation (`reference/code-review-graph.md:182-194`).
- After changing excludeDirs, force rebuild (incremental update doesn't purge) (`reference/code-review-graph.md:201-208`).
- `.gitignore` vs `.code-review-graphignore` — different purposes (`reference/code-review-graph.md:213-230`).
- Build time expectations table (`reference/code-review-graph.md:232-244`).
- CLI cheat-sheet (`reference/code-review-graph.md:246-258`).
- Phase integration per phase 0/2/5/6/7/review (`reference/code-review-graph.md:260-305`).
- Runner integration: startup check, per-phase refresh, prompt injection, review augmentation via detect-changes (`reference/code-review-graph.md:305-329`).
- Continuous refresh ownership table (`reference/code-review-graph.md:331-340`).
- Pitfalls: first build slow, watch uses inotify, db not portable across versions, excluded dirs matter, incremental update won't purge newly-excluded (`reference/code-review-graph.md:354-373`).

**Enforcement.** Nix-enforced when added as flake input. Runner-enforced per-phase refresh. Watcher runs in `nix develop`. Project-side: CLAUDE.md tells agents to always use `get_minimal_context_tool` first — that's prose.

**Overlap.** With CLAUDE.md instructions in this skill.

---

### `reference/dx.md` (`reference/dx.md:1-104`)

**Purpose.** One-command dev setup, script inventory, dev server, env management, debugging, CLAUDE.md integration.

**Rules / guardrails.**
- One-command dev setup: `nix develop && npm run dev` (`reference/dx.md:7-12`).
- Script inventory table: dev/test/test:unit/test:integration/lint/lint:fix/typecheck/build/db:migrate/db:seed/db:reset/codegen/clean/clean:all/check (`reference/dx.md:16-34`).
- Dev server: hot reload, proxy, HTTPS in dev (if needed), port consistency (`reference/dx.md:36-41`).
- Environment: `.env.example` committed; `.env` gitignored; Nix flake default; flake.lock committed; no `nvm`/`pyenv`/`rbenv` (`reference/dx.md:43-54`).
- Codegen: dedicated dir, `// @generated` header (`reference/dx.md:56-62`).
- Debugging configs: `launch.json` for VS Code; per-language attach methods (`reference/dx.md:64-69`).
- CLAUDE.md "Development" section template (`reference/dx.md:71-91`).
- Preset behavior: POC = dev only; Local/Public/Enterprise progressively fuller (`reference/dx.md:93-99`).

**Enforcement.** Prose. The validate agent checks for the script inventory existence indirectly.

**Overlap.** With `readme.md` (dev setup), `pre-pr.md` (script inventory), `idempotency.md`.

---

### `reference/readme.md` (`reference/readme.md:1-218`)

**Purpose.** Human-facing README content rules — cognitive funneling, required sections, badges, quality checklist.

**Rules / guardrails.**
- Cognitive funneling: broad → specific (`reference/readme.md:6-8`).
- 14 required sections: title+tagline, badges (3-6), description, visuals/demo, features, TOC if long, getting started (prereqs/install/quickstart), usage, configuration, architecture, development, security, license, acknowledgments (`reference/readme.md:10-160`).
- 7 conditional sections (`reference/readme.md:163-172`).
- Quality checklist (7 items) (`reference/readme.md:174-183`).
- 6 principles (`reference/readme.md:185-192`).
- Preset behavior (`reference/readme.md:194-201`).
- Task generation: README task goes in Polish phase (`reference/readme.md:203-217`).

**Enforcement.** Prose-only.

**Overlap.** With `cicd.md` (badges), `dx.md` (dev section).

---

### `reference/ui-flow.md` (`reference/ui-flow.md:1-132`)

**Purpose.** Mandate UI_FLOW.md as the living single source of truth for screens / routes / actions / API / WebSocket / state machines / field validations.

**Rules / guardrails.**
- Create on first UI task; update every UI-touching task (`reference/ui-flow.md:8-12`).
- Required sections: main flow diagram (Mermaid with color-coded nodes), state machines, screen-by-screen details, platform-native screens, API sequence diagrams, API endpoint summary, real-time paths, generated files reference, field validation reference table (`reference/ui-flow.md:14-99`).
- Every documented flow MUST have a corresponding E2E test referencing the flow (`reference/ui-flow.md:101-112`).
- CLAUDE.md instruction template (`reference/ui-flow.md:114-132`).

**Enforcement.** Prose-only. There is no detector for "UI_FLOW.md is out of date." The May 22 case is exactly this: 4 preset routes existed in code, UI_FLOW.md presumably documented them, but test coverage only hit `trainer`.

**Overlap.** With `mcp-e2e-core.md § Writing UI_FLOW.md`.

---

### `reference/data-model.md` (`reference/data-model.md:1-34`)

**Purpose.** Minimum depth requirements for `data-model.md` produced in plan phase.

**Rules / guardrails.**
- Entity relationship diagram with cardinality both directions (`reference/data-model.md:7`).
- Per-entity field tables with type/required/default/constraints (`reference/data-model.md:9-13`).
- State transition rules for lifecycle entities (transition table) (`reference/data-model.md:15-25`).
- Cross-entity constraints: uniqueness, mutual exclusion, cascading, referential integrity (`reference/data-model.md:27-32`).
- "describes logical schema not physical storage" (`reference/data-model.md:34`).

**Enforcement.** Prose-only.

---

### `reference/api-contracts.md` (`reference/api-contracts.md:1-39`)

**Purpose.** Minimum depth requirements for API contract docs.

**Rules / guardrails.**
- REST/RPC per endpoint: method+path, request schema with JSON example, response schemas, all status codes with meaning/trigger, auth requirements (`reference/api-contracts.md:5-17`).
- WebSocket/SSE per channel: path/params, message types with direction, payload schema per message, connection lifecycle, sequencing/replay (`reference/api-contracts.md:19-25`).
- Binary protocols: wire format, message type enumeration, payload byte layout, flow diagrams (`reference/api-contracts.md:27-32`).
- IPC: method signatures, async behavior, error propagation (`reference/api-contracts.md:34-38`).

**Enforcement.** Prose-only.

---

### `reference/interface-contracts.md` (`reference/interface-contracts.md:1-58`)

**Purpose.** Internal IC contracts between tasks within a project.

**Rules / guardrails.**
- Create an IC for any shared artifact between tasks: file paths, data formats, env vars, IPC, CLI interfaces (`reference/interface-contracts.md:7-15`).
- Contract table format with IC# / name / producer / consumer(s) / spec (`reference/interface-contracts.md:19-27`).
- Each contract: location / format / permissions / lifecycle (`reference/interface-contracts.md:29-33`).
- Task-level `[produces: IC-xxx]` / `[consumes: IC-xxx]` tags — runner does NOT parse them, they're for agents and reviewers (`reference/interface-contracts.md:35-46`).
- Relationships to api-contracts.md, data-model.md, learnings.md (`reference/interface-contracts.md:48-52`).

**Enforcement.** Prose-only. Validator checks at `validate-review.md:88-98` (cross-boundary contract verification) is the closest thing to enforcement.

**Overlap.** With `agent-file-schemas.md` (which covers meta-layer ICs).

---

### `reference/traceability.md` (`reference/traceability.md:1-75`)

**Purpose.** Make specs machine-readable + individually testable + traceable.

**Rules / guardrails.**
- FR-### numbering per requirement (`reference/traceability.md:7-10`).
- SC-### success criteria, each mapping to ≥1 FR (`reference/traceability.md:12-16`).
- Story-to-task traceability: `[Story 3]` or `[FR-015]` suffix on tasks (`reference/traceability.md:18-22`).
- SC-to-test traceability via Test Plan Matrix in plan.md (`reference/traceability.md:24-31`).
- Task `Done when:` line: concrete / verifiable / not subjective / 1-3 bullets (`reference/traceability.md:33-39`).
- IC tags for tasks sharing state (`reference/traceability.md:41-46`).
- Structured learnings.md format per task ID (`reference/traceability.md:48-60`).
- Auto-generated CLAUDE.md with manual-additions markers (`reference/traceability.md:62-68`).
- Interview handoff docs: interview-notes.md, transcript.md, spec.md (`reference/traceability.md:70-75`).

**Enforcement.** Prose-only.

**Overlap.** With `interface-contracts.md`, `data-model.md`, `api-contracts.md`.

---

### `reference/complexity.md` (`reference/complexity.md:1-20`)

**Purpose.** Constitution-check violations must be tracked, not silently ignored.

**Rules / guardrails.**
- At plan time: any abstraction/interface/dependency beyond simplest approach either confirms no violation or adds row to Complexity Tracking table (`reference/complexity.md:7-10`).
- At implementation: agent deviating from plan must add row + code comment with justification before proceeding (`reference/complexity.md:11-14`).
- Table format: Violation / Why Needed / Simpler Alternative Rejected Because (`reference/complexity.md:15-20`).

**Enforcement.** Prose-only. There is no detector for "agent added an abstraction the plan didn't have." This is exactly the rule most likely to be silently violated.

---

### `reference/phase-deps.md` (`reference/phase-deps.md:1-49`)

**Purpose.** Every plan MUST include a Phase Dependencies section enabling parallel work.

**Rules / guardrails.**
- Dependency graph (ASCII/Mermaid) showing blocking + parallel phases (`reference/phase-deps.md:7-13`).
- Parallel workstreams identified (frontend/backend, platform clients, independent modules, test infra) (`reference/phase-deps.md:15-19`).
- Multi-agent strategy described (`reference/phase-deps.md:21-26`).
- Sync points where parallel converges (`reference/phase-deps.md:28`).
- **DAG must be acyclic**: don't put a task that depends on later phase into same phase as tasks the later phase depends on (`reference/phase-deps.md:30-46`).
- Fix: split the phase (`reference/phase-deps.md:45`).

**Enforcement.** Prose-only. Runner detects deadlock by sitting idle ("No agents running"); the docs say split, but there's no automatic detector at plan time.

---

### `reference/edge-cases.md` (`reference/edge-cases.md:1-29`)

**Purpose.** Spec MUST include Edge Cases & Failure Modes section after user stories.

**Rules / guardrails.**
- 11 categories to probe: timeout, crash/restart, concurrent access, invalid input, partial completion, network failure, resource exhaustion, missing dependencies, duplicate operations, permission/auth failure, data migration/upgrade (`reference/edge-cases.md:8-22`).
- Specify trigger + expected behavior (`reference/edge-cases.md:5`).
- Integration: specify phase probes for edge cases; clarify phase resolves NEEDS CLARIFICATION; plan maps each to ≥1 test; tasks include edge-case tests alongside feature tests (`reference/edge-cases.md:24-28`).

**Enforcement.** Prose-only.

---

### `reference/health.md` (`reference/health.md:1-51`)

**Purpose.** Health-check endpoints (servers) / commands (CLIs).

**Rules / guardrails.**
- `GET /health` (liveness): 200 if alive regardless of deps; body shows full status (`reference/health.md:7-23`).
- `GET /ready` (readiness): 200 if can accept traffic; 503 during startup/shutdown/critical-dep-down (`reference/health.md:25-30`).
- Dependency check strategy explicit (active vs cached) (`reference/health.md:32-34`).
- CLI: `--check` / `--validate` flag; exit 0 = OK, 1 = problem (`reference/health.md:36-40`).
- Batch jobs: exit code primary signal; structured JSON output (`reference/health.md:42-48`).
- Libraries: skip (`reference/health.md:50-51`).

**Enforcement.** Prose-only.

---

### `reference/shutdown.md` (`reference/shutdown.md:1-35`)

**Purpose.** Every server/daemon MUST implement graceful shutdown.

**Rules / guardrails.**
- Register SIGTERM + SIGINT handlers (`reference/shutdown.md:5-7`).
- 11-step shutdown sequence with mandatory INFO logging at each step (`reference/shutdown.md:9-23`).
- Configurable shutdown timeout default 30s; force-exit code 1 if exceeded (`reference/shutdown.md:25-30`).
- Shutdown hook registry with reverse-order cleanup (`reference/shutdown.md:32-35`).

**Enforcement.** Prose-only.

---

### `reference/logging.md` (`reference/logging.md:1-55`)

**Purpose.** Structured logging with 5-level hierarchy and required fields.

**Rules / guardrails.**
- 5 levels with usage table: DEBUG/INFO/WARN/ERROR/FATAL with examples (`reference/logging.md:5-15`).
- All logs structured JSON, no exceptions, no raw `console.log`/`print` (`reference/logging.md:17-19,40-42`).
- Required fields: timestamp / level / message / module / correlationId (`reference/logging.md:21-29`).
- ERROR/FATAL additional fields: error / errorCode / stack (`reference/logging.md:31-37`).
- Destination: app logs → stderr; structured data → stdout (`reference/logging.md:39-43`).
- Plan must include logging infra as early task (`reference/logging.md:45-48`).
- Correlation IDs at every request entry; propagated downstream (`reference/logging.md:50-55`).

**Enforcement.** Prose-only.

**Overlap.** With `observability.md` (correlation IDs), `errors.md` (errorCode field).

---

### `reference/observability.md` (`reference/observability.md:1-23`)

**Purpose.** Beyond logging — metrics, tracing, error reporting.

**Rules / guardrails.**
- Metrics at key ops: request count/latency/error rate, resource metrics, business metrics (`reference/observability.md:6-9`).
- Trace context propagation: correlation ID through logs / HTTP headers / message queue metadata / error reports (`reference/observability.md:11-16`).
- Structured error reports: stack / correlation ID / env / user context anonymized / breadcrumbs (`reference/observability.md:18`).
- Request/response logging at DEBUG with PII omission (`reference/observability.md:20`).
- Document in CLAUDE.md + README (`reference/observability.md:22`).

**Enforcement.** Prose-only.

**Overlap.** With `logging.md`.

---

### `reference/rate-limiting.md` (`reference/rate-limiting.md:1-17`)

**Purpose.** Rate limiting + backpressure when applicable.

**Rules / guardrails.**
- Per-client rate limits (sliding window / token bucket) (`reference/rate-limiting.md:7`).
- Rate-limit headers: `X-RateLimit-Limit/Remaining/Reset` (`reference/rate-limiting.md:8`).
- 429 response with `Retry-After` (`reference/rate-limiting.md:9`).
- Bounded queues with explicit overflow behavior (reject/backpressure/drop) (`reference/rate-limiting.md:10`).
- Connection limits as safety valve (`reference/rate-limiting.md:11`).
- **Timeout budgets**: every external call MUST have explicit timeout (`reference/rate-limiting.md:12`).
- Document chosen strategy or "deferred" (`reference/rate-limiting.md:14-16`).

**Enforcement.** Prose-only.

---

### `reference/errors.md` (`reference/errors.md:1-42`)

**Purpose.** Consistent error handling strategy.

**Rules / guardrails.**
- Project-level error base class with typed subclasses (template: AppError + 8 subclasses with HTTP mappings) (`reference/errors.md:7-19`).
- Each error class has: machine-readable code, HTTP status, user-facing safety flag (`reference/errors.md:21-25`).
- Propagation pattern: throw at point of failure → catch at boundary → log with full context → return sanitized response (`reference/errors.md:27-33`).
- Never swallow / never log-and-rethrow (`reference/errors.md:32-33`).
- Global unhandled exception/rejection handler: log FATAL → trigger graceful shutdown → exit non-zero (`reference/errors.md:35-42`).

**Enforcement.** Prose-only.

**Overlap.** With `logging.md`, `shutdown.md`.

---

### `reference/config.md` (`reference/config.md:1-39`)

**Purpose.** Centralized configuration system.

**Rules / guardrails.**
- Single config module loading from 3 layers: defaults → file → env vars (`reference/config.md:7-14`).
- Validates all values + exports typed config object; only place reading config sources (`reference/config.md:13-15`).
- Backing services as attached resources — swappable via config; no hardcoded connection strings (`reference/config.md:17-19`).
- Fail-fast validation on startup; exit immediately listing every invalid/missing key (`reference/config.md:21-22`).
- Sensitive vs non-sensitive: secrets only from env vars / secret manager; never logged as values (`reference/config.md:24-29`).
- Config doc table per key: Key/Type/Default/Required/Sensitive/Description (`reference/config.md:31-39`).

**Enforcement.** Prose-only.

**Overlap.** With `security.md § Secret management`, `dx.md § Environment management`.

---

### `reference/migration.md` (`reference/migration.md:1-57`)

**Purpose.** Schema/API/config versioning strategy.

**Rules / guardrails.**
- Migrations: up/down idempotent versioned tested (`reference/migration.md:5-15`).
- Document defer with warning if user skips (`reference/migration.md:17`).
- Seed script: schema + required reference data + optional sample data (`reference/migration.md:19-27`).
- API versioning: URL-path default; latest-version alias; semantic versioning (`reference/migration.md:29-35`).
- Backward-compatibility policy from interview; default "all clients internal/sync-updated" if deferred (`reference/migration.md:37-43`).
- Admin process parity: migrations + seeds + scripts run inside same Nix flake / venv / container as app (`reference/migration.md:44-50`).
- Config versioning: auto-migrate / clear error / release-notes documentation (`reference/migration.md:52-57`).

**Enforcement.** Prose-only.

---

### `reference/idempotency.md` (`reference/idempotency.md:1-44`)

**Purpose.** Setup/initialization steps + readiness checks for agentic workflows.

**Rules / guardrails.**
- Every setup/init/bootstrap flow MUST be idempotent (`reference/idempotency.md:7-15`).
- Check-before-mutate rule: file exists → reuse; op already ran → skip; never overwrite/double-initialize (`reference/idempotency.md:13`).
- Specified in spec phase 2; called out per task in plan phase 5 (`reference/idempotency.md:17-19`).
- Implementation patterns: `existsSync` before file create; `CREATE TABLE IF NOT EXISTS`; `git init` only if no `.git/` (`reference/idempotency.md:21-26`).
- Readiness checks for external deps: blocking with timeout; instant return if up; non-zero exit on timeout (`reference/idempotency.md:28-44`).
- Scripts defined in task runner; called before every dependent task (`reference/idempotency.md:40-44`).

**Enforcement.** Prose-only. The runner's pre-E2E gate fix loop indirectly enforces because it loops on failure.

**Overlap.** With `dx.md`, `e2e-runtime.md § Backend service setup`.

---

### `reference/nix-ci.md` (`reference/nix-ci.md:1-39`)

**Purpose.** Nix-specific rules for CI/build agents.

**Rules / guardrails.**
- `NIX_REMOTE=daemon` for store writes (`reference/nix-ci.md:7`).
- `--extra-experimental-features 'nix-command flakes'` (`reference/nix-ci.md:8`).
- Devshell: do NOT use `nix develop --command <cmd>` (re-evals per call); source once instead (`reference/nix-ci.md:11-15`).
- `nix flake check` 10-20m timeout ≥1800s; background; never pipe through head/tail (`reference/nix-ci.md:17-26`).
- Last 200 lines of log = critical errors (`reference/nix-ci.md:25`).
- bwrap sandbox restrictions: home-dir paths not mounted (`reference/nix-ci.md:28-31`).
- DON'Ts: no prefix-every-command with nix develop; no `head`/`tail`/`grep -c` on logs; no `nix-env -i` in sandbox; don't trust exit 0 through `tee` without `pipefail` (`reference/nix-ci.md:34-39`).

**Enforcement.** Prose-only.

---

### `reference/templates/README.md` (`reference/templates/README.md:1-32`)

**Purpose.** Index for canonical structured-test-output reporters.

**Rules / guardrails.**
- Read EXAMPLE-OUTPUT.md first — it is the contract (`reference/templates/README.md:5-8`).
- "Copy, don't fork": extending fields safe; renaming/dropping fields not safe (`reference/templates/README.md:14-22`).
- Adding a new language: read EXAMPLE-OUTPUT end-to-end, match on-disk layout exactly, canonical field names (`pass`/`fail`/`skip` not `passed`/`failures`), enforce non-vacuous assertion (`reference/templates/README.md:24-31`).

**Enforcement.** Template-enforced when used.

---

### `reference/templates/EXAMPLE-OUTPUT.md` (`reference/templates/EXAMPLE-OUTPUT.md:1-171`)

**Purpose.** Canonical schema and on-disk layout for `test-logs/`.

**Rules / guardrails.**
- On-disk layout (`reference/templates/EXAMPLE-OUTPUT.md:14-25`): `test-logs/summary.json` (latest, always overwritten); `test-logs/<type>/<timestamp>/summary.json` (history, never overwritten); `failures/<sanitized-test-name>.log` per failure; `security/<scanner>.json`.
- summary.json schema (canonical) — exact field names; `skip` not `skipped` (alias only tolerated for legacy) (`reference/templates/EXAMPLE-OUTPUT.md:38-83`).
- Field reference table (`reference/templates/EXAMPLE-OUTPUT.md:86-99`).
- Per-result schema (`reference/templates/EXAMPLE-OUTPUT.md:101-112`).
- failures/*.log plain text format with assertion / stack / stderr / req-resp (`reference/templates/EXAMPLE-OUTPUT.md:114-138`).
- File-name sanitization rules: regex replace + collapse + trim + truncate 200 chars + `.log` (`reference/templates/EXAMPLE-OUTPUT.md:140-151`).
- Non-vacuous assertion: `pass + fail > 0` (`reference/templates/EXAMPLE-OUTPUT.md:153-158`).

**Enforcement.** Template + runner. The reporters in `templates/*.{ts,py,go}` enforce by exit code.

---

### `reference/templates/test-reporter-{vitest.ts,pytest.py,go.go}`

**Purpose.** Three drop-in reporter implementations of the canonical schema.

**Rules / guardrails.**
- Each writes `test-logs/summary.json` matching the schema exactly.
- Customisable `RUN_TYPE` env var (`unit | integration | e2e`).
- Each enforces the non-vacuous + skip-as-failure rules in code (exit non-zero).

**Enforcement.** Template-enforced (these are real running code, not prose).

---

## Part 2 — Synthesis

### Rule categories (what spec-kit collectively tries to enforce)

1. **Proof discipline / verification** — claims are advertising, artifacts are state. `proof-discipline.md`, `verification.md`, `validate-review.md`, `agent-file-schemas.md`. Substrate-layer.
2. **Testing tier discipline** — unit / integration / E2E boundaries, no mocks inside tier, file-name conventions load-bearing, every tier runs at every phase. `testing.md` (920 lines), restated in `validate-review.md`, `e2e-runtime.md`, `mcp-e2e-core.md`.
3. **Zero-skip / non-vacuous** — runner refuses skip>0 or executed=0. `testing.md`, `cicd.md`, `pre-pr.md`, `proof-discipline.md`, reporter templates. Most-repeated rule in the corpus.
4. **Shared-runtime safety** — 10 authoring rules + 10 review checks for concurrent test execution. `testing.md` only.
5. **Real-runtime E2E** — no Robolectric / jsdom / simulator stand-ins; pre-E2E gate runs integration first. `testing.md`, `e2e-runtime.md`, `mcp-e2e-*`.
6. **Coverage discipline** — every test command has coverage, language-specific tools, terminal + file output, multi-language merging. `testing.md`, `cicd.md`, `validate-review.md`.
7. **Adversarial security** — input validation, secrets, headers, scanners (Trivy/Semgrep/Gitleaks/etc.), SARIF, fuzz testing for parsers/binary formats. `security.md`, `cicd.md`, `testing.md § Adversarial flow tests`.
8. **CI discipline** — pipeline order, non-vacuous, skip-as-failure, default-branch readiness, agentic CI loop, action pinning. `cicd.md`, `pre-pr.md`.
9. **Cost guardrails** — role→model mapping, hang budgets, executor step cap, scripted verify, browser_evaluate before browser_snapshot, page manifests, reference-injection scoping, prompt-caching strategy. `cost-guardrails.md`, `cost-reporting.md`, `mcp-e2e-*`.
10. **E2E loop mechanics** — explore-research-fix-verify, supervisor escalation ladder, findings.json, regression fast-path, behavioral-not-render regression tests. `mcp-e2e-core.md`, `agent-file-schemas.md`, `fix-agent-playbook.md`.
11. **Idempotency & readiness** — every setup re-runnable; readiness scripts blocking with timeout; setup.sh/teardown.sh convention. `idempotency.md`, `e2e-runtime.md`, `testing.md`.
12. **Stripe / payments** — three keys, ephemeral webhook secret, sync-env, lifecycle scripts, live-key three-layer guardrails. `stripe.md` only.
13. **Observability** — structured JSON logs, 5-level hierarchy, correlation IDs, metrics, traces, error reporting. `logging.md`, `observability.md`.
14. **DX / scaffolding** — one-command setup, script inventory, env management, Nix-first, code-review-graph. `dx.md`, `readme.md`, `code-review-graph.md`.
15. **Spec quality / depth** — FR numbering, SC traceability, "Done when" criteria, data-model field depth, API contract depth, edge cases enumeration. `traceability.md`, `data-model.md`, `api-contracts.md`, `interface-contracts.md`, `edge-cases.md`, `complexity.md`, `phase-deps.md`.
16. **Reliability primitives** — rate limiting, error hierarchy, config validation, migration strategy, health checks, graceful shutdown. `rate-limiting.md`, `errors.md`, `config.md`, `migration.md`, `health.md`, `shutdown.md`.
17. **Failure-pattern library** — known signatures (port-timeout, browser-install-hang, stale-android-apk, mcp-launch-failed, etc.) with diagnostic commands + anti-patterns. `e2e-failure-patterns.md`, `fix-agent-playbook.md`.
18. **Nix particulars** — daemon flag, devshell rules, flake check timeouts, sandbox restrictions. `nix-ci.md`.

### Contradictions / tensions found

1. **Mocking — "real systems wherever possible" vs "mock only what requires human interaction" vs "mocks acceptable at boundary of tier."**
   `testing.md:50` says "no mocking inside a tier's boundary" — unit tests may mock HTTP clients, integration tests may stub paid SaaS.
   `testing.md:86-94` says use real servers everywhere; mock only biometrics/hardware/UI.
   `testing.md:96-110` ("External process boundary testing") says stub binaries are OK — but a stub binary is "not the same as mocking."
   These are reconcilable, but the file's wording is dense and contradictory on first read. Agents tend to grab the most permissive sentence — "mocks acceptable at the tier's outer edge" — and use it to justify mocking the DB in an integration test.

2. **Skip enforcement — `pytest.mark.skipif`.**
   `testing.md:156` bans `@pytest.mark.skipif`.
   `security.md:288` shows `if testing.Short() { t.Skip(...) }` as an OK pattern in a Go example.
   `testing.md:730-733` uses `if testing.Short() { t.Skip(...) }` as an example for latency tests — calls it a skip in lowercase but the rule says runtime skips are banned.
   Contradiction is real: spec-kit endorses `-short` skips in some places and bans them in others.

3. **"Use real platforms / no mocks" vs "test bypass mechanisms required for hardware."**
   `e2e-runtime.md:108-126` says bypass for camera/biometrics/NFC/GPS via debug-only deep links/mock APIs.
   `testing.md:92` says "Mock only what requires human interaction."
   Compatible in principle, but `e2e-runtime.md` adds a hard rule that bypasses must be debug-build-only and verified absent in release. Without that backup rule, agents tend to ship a bypass in release because it's the easier path.

4. **"Verifier reads artifacts, not claims" vs validator reading completion-{TASK_ID}.json.**
   `proof-discipline.md:81-97` strips completion JSONs from the verifier's prompt.
   `verification.md:50-54` has the runner reading and re-executing commands from `completion-{TASK_ID}.json`.
   These are talking about different verifiers (per-task vs phase-boundary), but the file labels are inconsistent and the prompt-stripping rule is easy to miss.

5. **`browser_snapshot` "use sparingly" vs "first visit only, then evaluate."**
   `cost-guardrails.md:140-148` says snapshot for first visit to unknown page.
   `mcp-e2e-web.md:45-56` says snapshot only when you need full accessibility tree to report an a11y bug, otherwise take one snapshot then switch.
   Soft contradiction in framing — both end in "don't keep snapshotting" but reach there differently. Agents reading only one file get different defaults.

6. **`continue-on-error` for security scanners.**
   `cicd.md:158-165` says `continue-on-error: true` only for security baselines or optional token-gated steps.
   `security.md:191` uses `continue-on-error: true` on Snyk by default.
   `cicd.md` says tighten after baseline; `security.md` shows the looser config without the discipline. An agent regenerating CI from `security.md` alone will ship a permanently-non-gating Snyk integration.

7. **Snyk: `--severity-threshold=high` blocks vs Snyk auto-fix PRs as default.**
   `cicd.md:212-216` says start with `continue-on-error: true`, tighten later.
   `security.md:165-175` says Snyk auto-fix PRs enabled by default — but that requires the SARIF upload + dashboard access to be working. The two files don't agree on the order of operations.

8. **README vs CLAUDE.md duplication.**
   `readme.md:192` says "Don't duplicate content between them; link instead."
   `dx.md:71-91` shows a complete CLAUDE.md "Development" section that essentially duplicates the README "Getting Started."
   `stripe.md:218-251` shows a CLAUDE.md stanza that explicitly references `test/e2e/README.md`.
   In practice the rules tolerate duplication; the no-duplicate principle is not enforced.

9. **"Don't curl as a substitute for E2E" vs "curl to admin API is ALLOWED."**
   `fix-agent-playbook.md:168-180`: shell HTTP clients only for pre-flight checks or response cross-checks.
   `mcp-e2e-core.md:239-261`: curl to admin API is allowed for state assertions after UI completes.
   These reconcile — different agents, different phases — but they're stated so close in spirit that an agent missing the nuance can either over-curl (state assertions never become E2E) or under-curl (a 5-line curl assertion gets replaced with a 50-step UI navigation).

10. **IC-AGENT-016 collision.**
    `agent-file-schemas.md:460` IC-AGENT-016 = platform-fix claim JSON.
    `agent-file-schemas.md:640` IC-AGENT-016 = verify.sh contract.
    Same number, two different file types. This is a documentation bug that almost certainly impacts the runner code that references IC-AGENT-016.

### Gaps relative to user's goals

The user's three explicit goals: (1) ship production-quality code unattended, (2) reduce time-per-feature, (3) enforce a quality bar agents wouldn't self-impose, (4) cost-controlled scaling. Pain points: silent fake completion, ignored/contradictory rules, cost waste.

**A. Silent fake completion.** This is the single biggest gap. Spec-kit responded to the May 22 incident by adding `proof-discipline.md`, but the substrate it requires (JSON proof artifacts at stable paths) is *generated by project-side wrappers* — `run-e2e.sh`, `run-a11y.sh`, etc. The runner can refuse `executed: 0`, but only if the wrapper emits that field. The May 22 incident is exactly the case where the wrapper said `exit 0` silently. The rule depends on every project's wrapper being correctly authored — a layer the runner can't audit at the wrapper-implementation stage. There is no "wrapper-lint" gate that says "this `run-e2e.sh` doesn't emit a proof JSON; the project itself is non-compliant." Until wrappers are validated against the proof contract, agents can produce a non-compliant wrapper and the runner will never know.

**B. Adversarial verifier requires correctly-built prompt.** `proof-discipline.md` rule 7 says the verifier's prompt MUST be adversarial. If the runner's `_verifier_prompt()` function has a bug, the verifier sees the lie. Tests for the runner code itself (the meta-layer) are not in scope of these reference docs; if you ship a code change to `parallel_runner.py` that accidentally leaves completion JSONs in the verifier's prompt, no reference rule catches it. The single point of failure is concentrated in one Python function.

**C. Prose-only rules with no enforcement.** These are the rules the user's question explicitly asks about — agents may quietly skip them under load:
- `testing.md § Shared-runtime authoring rules` (`testing.md:224-262`) — 10 rules every test must follow. No grep-detector in CI. Validator may flag, but the validator is an agent.
- `testing.md § User-flow integration tests` (`testing.md:352-501`) — every project must have these. Nothing checks the project actually has them.
- `testing.md § Adversarial flow tests` (`testing.md:597-651`) — every security boundary needs ≥1 rogue test. No coverage map for "security boundaries → adversarial tests."
- `testing.md § Performance and benchmark testing` (`testing.md:723-819`) — spec budgets become tests. If the spec says "<2s" and the test doesn't exist, nothing trips.
- `e2e-runtime.md § Test bypass mechanisms` (`e2e-runtime.md:108-126`) — bypasses must be absent in release builds. The "verify absent in release" check is prose; an agent may ship the bypass.
- `mcp-e2e-core.md § Regression test quality` (`mcp-e2e-core.md:129-155`) — must be behavioral not render. Agents naturally write render tests because they're easier; no detector flags this.
- `complexity.md` entire file — agents introducing abstractions without updating Complexity Tracking. No detector.
- `phase-deps.md § Avoiding circular phase dependencies` — runner detects deadlock by sitting idle. No plan-time detector.
- `ui-flow.md` — UI_FLOW.md drift. No detector that "you added a route but UI_FLOW.md doesn't list it." This is the EXACT shape of the May 22 incident's coverage shortcut.
- `interface-contracts.md` `[produces:]`/`[consumes:]` tags — runner does NOT parse them per the file itself (`interface-contracts.md:46`). Pure documentation.
- `data-model.md`, `api-contracts.md`, `traceability.md`, `edge-cases.md` — depth requirements for spec/plan artifacts. Validator can read but doesn't check.
- `health.md`, `shutdown.md`, `logging.md`, `observability.md`, `rate-limiting.md`, `errors.md`, `config.md`, `migration.md` — all prose-only. Every server-side reliability primitive depends on agent compliance.
- `security.md § Security headers` 7-header table — no automated check.
- `security.md § Fuzz testing` — required for parsers/binary formats; no detector.

**D. Cost rule decay.** Several rules in `cost-guardrails.md` are forward-thinking (e.g., the `cost-config.json` override schema, the `cheap_vs_expensive_calls` ratio) but the **anti-pattern detection** is one-shot: cost_report.py tells you Verify Opus% > 0, but only post-hoc, after the spend. There is no in-flight detector that says "this agent just made 50 `browser_snapshot` calls; warn." `mcp-e2e-android.md:24-27` mentions `PlatformDriver.cheap_vs_expensive_calls` as a counter but it's counted, not enforced as a budget.

**E. Reference content not version-aligned with the runner.**
- `cost-reporting.md:103` warns against editing reference files mid-run because it breaks cache_read. There is no machinery preventing it (an agent can absolutely Edit a file in `reference/` if it has write access).
- Pricing table in `cost-reporting.md:74-82` is hand-maintained — if Anthropic changes rates without the maintainer noticing, every cost report is wrong.
- `code-review-graph.md` is pinned to v2.3.2 with explicit "no negation syntax" warning; if upstream changes this, the rule stays stale.

**F. The "Stripe pattern" claim that other processors transfer.** `stripe.md:5` says "If the project later swaps to a different payment processor (Braintree, Adyen, Paddle), the shape documented here transfers directly." This is unverified — no parallel file for Braintree exists, so the assertion that the shape transfers is prose alone.

**G. iOS deferred is a real gap.** `mcp-e2e-ios.md:7-9`: every iOS task falls through to the full MCP loop with no regression fast-path. For a user trying to ship a multi-platform product, this is a known cost vector with no mitigation in this repo's reference docs.

**H. Multi-task / multi-agent rate limiting.** Nothing in this corpus addresses "how does the runner avoid blowing through your Anthropic quota when 5 fix-agents fire in parallel." There is `cost-guardrails.md § Hang budgets` but no hard ceiling on $/feature or $/day.

**I. Drift between writer and `agent-file-schemas.md`.** `agent-file-schemas.md:674-679` says "update this file in same commit as writer changes." When a writer change ships without the schema update, the runner silently parses the old format. There is no CI that re-parses every IC-AGENT-### entry's anchors against the running parser.

### Prose-only rules (highest-risk — agents can ignore silently)

Same list as gap (C) above. To make it scannable for the user, the top-10 most load-bearing prose-only rules:

1. **Shared-runtime authoring** (`testing.md:224-262`) — these are exactly the rules whose violation manifests as a flake in CI weeks later.
2. **User-flow integration tests must exist for every primary user flow** (`testing.md:352-501`).
3. **Adversarial flow tests must exist for every security boundary** (`testing.md:597-651`).
4. **No bypass mechanisms in release builds** (`e2e-runtime.md:126`).
5. **Regression tests must be behavioral, not render** (`mcp-e2e-core.md:129-155`).
6. **No Robolectric / jsdom / mock runtime substitution for real platform E2E** (`e2e-runtime.md:25-36`).
7. **Curl is not a substitute for E2E** (`fix-agent-playbook.md:168-180`).
8. **`browser_evaluate` before `browser_snapshot`** (`cost-guardrails.md:136-167`).
9. **No skip guards of any kind** (`testing.md:140-183`) — runner backstops only what the reporter reports; a hand-written wrapper that fakes `executed > 0` defeats the runner check.
10. **UI_FLOW.md stays in sync with implementation** (`ui-flow.md`) — the May 22 root cause.

### Redundancy (rules repeated in 3+ places)

| Rule | Locations |
|---|---|
| Zero-skip / `skip > 0 = FAIL` | `testing.md:140-183`, `validate-review.md:77`, `cicd.md:121-156`, `proof-discipline.md` rule 2, reporters in `templates/`, `verification.md:114` |
| Non-vacuous test count `pass + fail > 0` | `testing.md:137`, `cicd.md:43-100`, `pre-pr.md:66-86`, `proof-discipline.md` rule 1, `templates/EXAMPLE-OUTPUT.md:153-158`, reporters |
| Tier taxonomy (unit / integration / E2E) | `testing.md:35-54`, `validate-review.md:191`, `e2e-runtime.md` (E2E ≠ integration), `mcp-e2e-core.md` |
| Coverage matrix / coverage gap = FAIL | `testing.md:294-325`, `proof-discipline.md` rule 5, `validate-review.md:75-76`, `cicd.md` |
| Real-runtime E2E (no Robolectric/jsdom) | `testing.md:821-825`, `e2e-runtime.md:25-36`, `mcp-e2e-core.md`, `cicd.md` (E2E stage) |
| Scripted verify (`verify.sh`) | `cost-guardrails.md:83-114`, `fix-agent-playbook.md:195-238`, `mcp-e2e-core.md:59-68`, `agent-file-schemas.md:640-672` |
| Idempotent setup + readiness checks | `idempotency.md`, `e2e-runtime.md:377-450`, `testing.md` (Pre-E2E gate setup), `dx.md` |
| Webhook live-key guardrails | `stripe.md:403-448` (three layers — each layer cross-references itself: pre-commit, gitleaks, .env.example) |
| Structured logging w/ correlation IDs | `logging.md`, `observability.md`, `errors.md` (correlation field) |
| browser_evaluate vs browser_snapshot | `cost-guardrails.md:136-167`, `mcp-e2e-web.md:9-56`, `mcp-e2e-core.md:426-440` (env defaults) |
| State-Tool no-vision default (Android) | `cost-guardrails.md`, `mcp-e2e-android.md:10-41`, `mcp-e2e-core.md:426-440` |
| flutter clean mandatory after source change | `mcp-e2e-android.md:155-175`, `e2e-failure-patterns.md:262-355`, `fix-agent-playbook.md` |
| Don't BLOCKED.md as agent | `fix-agent-playbook.md:184-186`, multiple other files imply this |
| Default branch readiness | `cicd.md:309-334` (mostly unique here — good consolidation) |
| Read proof-discipline.md FIRST | `validate-review.md:7`, `verification.md:6` |

**Candidates for consolidation.** The runner-enforced rules (zero-skip, non-vacuous, coverage, scripted-verify, browser_evaluate, claim schema) could be consolidated into a single "rules the runner enforces" file with a clear "everything else is prose-only — caveat emptor" framing. Currently the runner-enforced and prose-only rules are intermixed at the file level, which makes it harder for an agent reading to know which lines have machinery behind them.

