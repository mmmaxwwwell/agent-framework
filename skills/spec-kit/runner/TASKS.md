# TASKS — TS runner port checklist

The work-list. Each `- [ ]` is **one unit of work** (see `CONTINUE.md`): do one,
verify it, check it off, update `MEMORY.md`, exit. Tasks are ordered; do the
first unchecked one. `[P]` marks tasks that may run in parallel with siblings if
multiple agents are active. Each task names its **verify** step.

Milestone gates and parity strategy are in
`/home/max/.claude/plans/groovy-stargazing-lemon.md`. Behavior parity source =
`../parallel_runner.py`. Fixture = `../runner-ts/specs/001-tabbed-pwa/`.

---

## M0 — Skeleton + pure layer (no Claude spawning)

- [x] **M0-1** Create `runner/` package boilerplate: `package.json` (name
  `@spec-kit/runner`, type module, Node 22, scripts `build`/`dev`/`test`),
  `tsconfig.json` (strict, `moduleResolution: bundler`, outDir `dist`),
  `vitest.config.ts`, `.gitignore` (`dist/`, `node_modules/`), `src/index.ts`
  stub. Add deps: `zod`, `better-sqlite3`, `@modelcontextprotocol/sdk`,
  `minimatch`; dev: `typescript`, `tsx`, `vitest`, `@types/node`,
  `@types/better-sqlite3`.
  **Verify:** `nix develop -c npm install --ignore-scripts && npm run build`
  succeeds; `npm test` runs (0 tests OK).
- [ ] **M0-2** Devshell: ensure the tooling is reachable. Either document using
  the sibling `../runner-ts/flake.nix` substrate or add a minimal `flake.nix`
  here (nodejs_22, typescript, sqlite). **Verify:** `nix develop -c node -v`
  prints v22.x.
- [ ] **M0-3** `src/stories/story-types.ts` + `src/dag/task-scheduler.ts` types:
  port the `Task`, `Phase` dataclasses (`../parallel_runner.py` ~L340) to TS
  interfaces + `TaskStatus` enum + Zod schemas. **Verify:** `tsc` clean; a unit
  test constructs a Task/Phase.
- [ ] **M0-4** `src/dag/task-scheduler.ts` — port `parse_task_file`
  (~L452): the `tasks.md` grammar (`- [ ] T### [P] [needs: …]`, `## Phase N`,
  `## Dependencies` arrows). **Verify:** vitest parses
  `../runner-ts/specs/001-tabbed-pwa/tasks.md` into the expected phase/task/dep
  counts (assert against a hand-computed golden).
- [ ] **M0-5** `src/config/cost-config.ts` + `src/models/roles.ts` +
  `src/models/role-model.ts` — port `E2E_ROLE_MODELS` defaults (Fable/Sonnet/
  Opus per locked decision #5), `_load_cost_config` (`.specify/cost-config.json`
  search up 2 dirs), `_role_model`/`_role_idle_s` resolvers. **Verify:** unit
  test: default planner→`claude-fable-5`; an override file flips it.
- [ ] **M0-6** `src/stories/feature-discovery.ts` — port feature discovery
  (sorted `specs/*/` dirs, skip dotdirs). **Verify:** unit test against a temp
  dir with 2 feature dirs + 1 dotdir.
- [ ] **M0-7** `src/artifacts/run-log.ts` + `completion-claim.ts` +
  `attempts-log.ts` — typed writers matching the Python file schemas
  (`run-log.jsonl`, `claims/completion-<id>.json`, `attempts/<id>.jsonl`); Zod
  schemas. **Verify:** unit test round-trips each through write+read.
- [ ] **M0-8** Fake-claude double + `runner parse <tasks.md>` CLI subcommand
  (dumps the parsed DAG as normalized JSON). **Verify:** output matches the
  Python `--dump-dag` (or a hand-built golden if Python lacks that flag — note
  which in MEMORY.md). **Parity-diff #1.**

## M1 — Trivial 1-story run end-to-end  *(stories.md lands here)*

- [ ] **M1-1** `src/stories/story-parser.ts` — parse `stories.md`: heading
  `## S<n> — title`, Connextra blockquote, `**Priority**`, `**Acceptance
  criteria**` GWT list, fenced ```yaml `Meta:` block. Zod-validate; reject
  malformed. **Verify:** unit tests (valid / missing-meta / bad-priority).
- [ ] **M1-2** `src/dag/story-dag.ts` — build DAG from `Meta.deps`; acyclic
  check (reject cyclic); `readySet()` weight-desc; `width()`. **Verify:** unit
  tests incl. a cyclic-rejection and a width computation.
- [ ] **M1-3** `src/process/stream-json.ts` — `claude --output-format
  stream-json` JSONL parser → typed events (usage/content_block/result).
  **Verify:** golden-file test over a captured real stream-json log.
- [ ] **M1-4** `src/process/token-accounting.ts` — cache-tier cost math
  (fresh/cache_read/cache_create per model). **Verify:** unit test vs known
  pricing.
- [ ] **M1-5** `src/sandbox/sandbox.ts` (interface) + `noop-sandbox.ts`.
  **Verify:** `tsc` clean; Noop passes a cmd through unchanged.
- [ ] **M1-6** `src/process/agent-runner.ts` + `wait.ts` — build `claude` argv,
  spawn via NoopSandbox, stream→log, idle-timeout + wall-cap. **Verify:**
  integration test spawns real `claude --help` (or fake-claude) and captures
  output.
- [ ] **M1-7** `src/roles/story-planner.ts` (Fable) — given one story + spec
  context, emit `specs/<f>/plans/<id>.tasks.md`; `refusal/fable-refusal.ts`
  fallback. **Verify:** with fake-claude, produces a parseable plan file.
- [ ] **M1-8** `src/roles/executor.ts` (Sonnet) — walk a parsed task list;
  honor `EXECUTOR_STEP_CAP_PER_SPAWN=4` / `EXECUTOR_WALL_CAP_S=600`; emit
  `handoff-spawn-N.md` on cap. **Verify:** with fake-claude, completes a 1-phase
  plan and writes a claim.
- [ ] **M1-9** `src/developer/developer.ts` (`runStory` + single-dev `runLoop`)
  + `src/supervisor/supervisor.ts` (N=1 pass-through) + `src/index.ts` wiring.
  **Verify (M1 demo):** a hand-written 1-story `specs/000-hello/stories.md` runs
  Fable→tasks→Sonnet→`claims/completion-S1.json`; `run-log.jsonl` has planner +
  executor rows. **Parity-diff #2.**

## M2 — bwrap sandbox + MCP config injection  `[P with M3]`

- [ ] **M2-1** `src/sandbox/bwrap-sandbox.ts` — port `_detect_bwrap` + arg
  construction (writable project + scratch dirs, DNS allowlist, `--unshare-pid`,
  `--no-sandbox` escape). **Verify:** `npm install -g` inside fails; arg vector
  matches Python.
- [ ] **M2-2** One-shot OAuth-token FD handoff + `src/sandbox/capabilities.ts`
  (capability→cred map, untrusted-code strips `gh`). **Verify:** integration
  test asserts token absent from `/proc/<pid>/cmdline` and `environ`.
- [ ] **M2-3** `src/mcp/mcp-config.ts` — write/merge `--mcp-config` JSON.
  **Verify:** merged config injected; a graph MCP tool call resolves. **Parity-diff #3.**

## M3 — Multi-story DAG scheduler + `[P]`/deps + capabilities  `[P with M2]`

- [ ] **M3-1** `src/dag/scheduler.ts` (SupervisorScheduler) + port `Scheduler`
  ready-logic into `task-scheduler.ts` (`getReadyTasks` `[P]` rules). **Verify:**
  table-driven tests vs Python on the fixture tasks.md.
- [ ] **M3-2** Concurrency cap (`min(16, cores-2)`) + `[needs: gh]` GH_TOKEN
  grant wiring. **Verify:** 3-story DAG (S1→S3, S2 indep) runs S1∥S2 then S3;
  ordering proven in `run-log.jsonl`. **Parity-diff #4.**

## M4 — Per-story verify gate

- [ ] **M4-1** `src/roles/verifier.ts` (VerifyGate) — port verify role +
  verdict→claim/rejection + substrate-wins falsification rule. **Verify:** a
  fake-green story is REJECTED → `claims/rejection-S1.md`. **Parity-diff #5.**

## M5 — Fix-validate loop

- [ ] **M5-1** `src/loops/fix-validate.ts` + `src/roles/fixer.ts` — bounded
  fix→validate cycle, structured test-output ingestion, `BLOCKED.md` +
  auto-unblock, rate-limit handling. **Verify:** failing-test story loops then
  passes; a `gh`-needing story writes BLOCKED.md and is auto-granted+retried.
  **Parity-diff #6.**

## M6 — Code review + validate-review cycle

- [ ] **M6-1** `src/roles/reviewer.ts` — inline the code-review skill body;
  cycle validate→review→clean; inject code-review-graph blast radius. **Verify:**
  planted-bug story yields ≥1 finding, clean story yields 0. **Parity-diff #7.**

## M7 — E2E planner→executor loop  (behind PlatformDriver)

- [ ] **M7-1** `src/platform/platform-driver.ts` iface + `NoopDriver`.
  **Verify:** `tsc` clean.
- [ ] **M7-2** `src/loops/e2e-loop.ts` — planner→executor for `maps:[W-…]`
  stories; consume `workflows.md`; emit `findings.json`/`plan.md`/handoff.
  **Verify:** fixture `W-OP-2` runs under fake-claude. **Parity-diff #8.**
- [ ] **M7-3** `[P]` `browser-driver.ts` / `android-driver.ts` / `ios-driver.ts`
  + mcp-android wiring. **Verify:** per-driver smoke.

## M8 — CI loop  `[P with M9]`

- [ ] **M8-1** `src/loops/ci-loop.ts` — push/poll/diagnose/fix sub-agents +
  sub-agent accounting. **Verify:** CI-loop story: push→fail→fix→green.
  **Parity-diff #9.**

## M9 — Cost accounting + reporting  `[P with M8]`

- [ ] **M9-1** Port `cost_report.py` → `runner cost-report`; cache-aware
  pricing; hang budgets. **Verify:** totals match `python cost_report.py` within
  rounding. **Parity-diff #10.**

## M10 — Meta-planner

- [ ] **M10-1** `src/meta/meta-planner.ts` — port `PROMPT-add-meta-planner.md`;
  amends `stories.md` (add/split/add-dep). **Verify:** a META brief produces
  correct new/amended stories + deps. **Parity-diff #11.**

## M11 — Multi-developer supervisor + coordination/monitoring MCP

- [ ] **M11-1** `src/mcp/coordination/atomic.ts` + `coordination-store.ts`
  (better-sqlite3, WAL, `schema.sql`). **Verify:** N concurrent `claimStory` on
  one story → exactly one winner; same for `acquireFileLock`.
- [ ] **M11-2** `coordination-server.ts` (§7 tools) + inject into developer
  `--mcp-config`. **Verify:** a spawned agent calls `claim_story` as a tool.
- [ ] **M11-3** `src/supervisor/n-sizing.ts` + push-wake + `proposals.ts`
  (in-flight rule) + N>1 developer loop wrapping `runStory`. **Verify:** 7
  independent stories run N=7; shared `flake.nix` edits coordinate via
  file-lock; one `split_story` applied mid-run; no lost claims.
- [ ] **M11-4** `monitoring-server.ts` (§7b read surface + gated `--monitor-control`).
  **Verify:** read tools return live fleet state; control verbs gated.

---

## Part B — spec-kit wrapper (can interleave; needed before real story-driven runs)

- [ ] **B-1** Write `../phases/stories.md` — the wrapper that generates
  `stories.md` from spec.md + workflows.md + plan.md (see plan §B.3). **Verify:**
  run it against the fixture; produced `stories.md` parses + `maps` resolve.
- [ ] **B-2** Edit `../SKILL.md` — phase-detection table (stories.md = Phase 7
  trigger for TS runner; tasks.md kept for Python), Step 3 loader row,
  auto-advance chain. **Verify:** re-read; phase detection picks stories.md.
- [ ] **B-3** Regenerate `ROUTER.md` via repo-root `GENERATE-ROUTER.md` (never
  hand-edit). **Verify:** `ROUTER.md` regenerated, diff sane.
- [ ] **B-4** Additive notes in `../phases/tasks.md` + `../reference/traceability.md`
  (story-to-workflow traceability + Meta schema). **Verify:** notes present,
  nothing removed.
