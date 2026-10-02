# MEMORY — TS runner port

Durable state for the TypeScript spec-kit parallel runner port. Read this first
(via `CONTINUE.md`). Update `## Current state`, `## Log`, `## Gotchas`,
`## Blockers` every time you finish a unit of work.

---

## Current state

- **Milestone:** M0 (skeleton + pure layer) — in progress.
- **Next unchecked task:** M0-2 — author local `runner/flake.nix` (nodejs_22,
  typescript, sqlite) so the package has its own devshell instead of borrowing
  `../runner-ts`. Verify: `nix develop -c node -v` prints v22.x from inside
  `runner/`.
- **Build status:** GREEN. `@spec-kit/runner` package scaffolded; deps installed
  in `runner/node_modules`; `npm run build` (tsc) clean; `npm test`
  passWithNoTests exit 0.
- **Last agent stopped:** after M0-1 (package boilerplate) verified.

---

## Locked decisions (do not re-litigate)

1. **Full feature-parity port** of `../parallel_runner.py` (~21k lines) into a
   new TypeScript package at `skills/spec-kit/runner/`.
2. **Python runner stays** as the reference — never delete or edit
   `../parallel_runner.py`.
3. **`stories.md` replaces `tasks.md`** as the runner's implement input. The
   per-story task list is generated **at runtime** by a Fable-model story
   planner — NOT authored statically.
4. **Story format** = Connextra ("As a <role>, I want <goal>, so that
   <benefit>") + numbered Given/When/Then acceptance criteria + Priority P1-P3 +
   a fenced ```yaml `Meta:` block (`id, deps, touches, maps, needs`,
   optional `produces/consumes`).
5. **Roles → models** (defaults, overridable via `.specify/cost-config.json`):
   planner = `claude-fable-5`, executor/fix/verify = `claude-sonnet-4-6`,
   diagnostic/supervisor/research = `claude-opus-4-8`.
6. **Per-story plan files + a story DAG.** Each ready story → Fable planner
   writes `specs/<f>/plans/<story-id>.tasks.md` → Sonnet executors work it →
   verify gate → completion claim.
7. **Single-unit-of-work contract** at both layers — see `CONTINUE.md`. Build
   agents do one TASKS.md task and exit; the runner processes one story (and,
   within it, bounded executor spawns with `handoff-spawn-N.md`) and exits.
8. **Three-level object model** (from `../../../docs/multi-developer-runner.md`):
   Supervisor → N Developers (each = one instance of the old runner) → many
   `claude` subprocesses. N=1 reduces to today's single-stream behavior exactly.

---

## Design summary (self-sufficient if the ~/.claude/plans files are missing)

**Module layout** (`runner/src/`): `config/`, `models/` (roles + role→model
resolver), `process/` (agent-runner, stream-json parser, wait/idle-caps, token
accounting), `sandbox/` (Sandbox iface + Noop + Bwrap + capabilities), `mcp/`
(mcp-config + `coordination/` SQLite store + coordination/monitoring MCP
servers + atomic primitive), `stories/` (parser + types + feature discovery),
`dag/` (story-dag, SupervisorScheduler, task-scheduler = port of py Scheduler),
`supervisor/`, `developer/`, `roles/` (story-planner=Fable, executor=Sonnet,
fixer, verifier, reviewer, diagnostic), `loops/` (e2e, ci, fix-validate),
`platform/` (PlatformDriver + android/browser/ios), `meta/` (meta-planner),
`artifacts/` (completion-claim, attempts-log, run-log, learnings, merged-log),
`refusal/` (fable-refusal handler).

**Core control flow:** Supervisor.run → discover `specs/*/` → parse stories.md →
build StoryDag (reject if cyclic) → size N → spawn N Developers →
each Developer.runLoop: claim a ready story (atomic) → `runStory`:
StoryPlanner(Fable) writes `plans/<id>.tasks.md` → `parseTaskFile` (reuse py
grammar) → TaskScheduler (unchanged `[P]` logic) walks tasks with
Executor(Sonnet) (handoff/blocker/caps) → VerifyGate per phase → publish claim.

**Key parity sources in `../parallel_runner.py`** (verify line numbers, the file
changes): `parse_task_file` ~L452, `Scheduler` ~L635, `spawn_agent` ~L3554
(builds `claude --dangerously-skip-permissions --model <m> --verbose
--output-format stream-json`, OAuth token via one-shot FD, prompt via `.prompt.md`,
MCP via repeated `--mcp-config`), sandbox builders ~L3319/L3484, `E2E_ROLE_MODELS`
~L8256 / `_role_model` ~L8310 (cost-config overrides), Task/Phase dataclasses
~L340, executor caps (`EXECUTOR_STEP_CAP_PER_SPAWN=4`, `EXECUTOR_WALL_CAP_S=600`,
`EXECUTOR_MAX_SPAWNS_PER_ITER=5`). The planner→executor handoff currently lives
ONLY in the E2E loop (~L17804-17890); the port promotes it to the default
`runStory` pipeline.

**Libraries:** `node:child_process` (spawn + FD inheritance for OAuth token),
`better-sqlite3` (synchronous → atomic `INSERT … ON CONFLICT DO NOTHING`, WAL),
`@modelcontextprotocol/sdk` (coordination/monitoring MCP servers),
`node:readline`-per-line JSON for stream-json, `zod` (boundary validation),
`vitest` (real processes), `minimatch` (touches globs), a small semaphore for
the concurrency cap. Node 22, TS strict, tsx (dev) / tsc (build), deps via
`nix develop`.

**Parity fixture:** `../runner-ts/specs/001-tabbed-pwa/` (real
spec/plan/workflows/tasks; ships a fake-claude contract). Per-milestone parity =
run TS + Python under `--fake-claude`, diff **normalized** `run-log.jsonl` +
`claims/*` (sort by id; strip timestamps/durations/pids; canonicalize JSON).

**Full design** (when present): `/home/max/.claude/plans/groovy-stargazing-lemon.md`
and `…-agent-afb84ce0e08f3d1e0.md` (types, signatures, pseudocode).

---

## Gotchas

- **Devshell substrate (until M0-2):** `runner/` has no local flake yet, so use
  `nix develop ../runner-ts -c …` from inside `runner/`. That shell provides
  nodejs_22 (v22.22.3) + typescript + sqlite. BUT entering it triggers
  runner-ts's `code-review-graph` shellHook, which creates a `.code-review-graph/`
  watcher dir in `runner/` and auto-appends it to `runner/.gitignore` (harmless,
  ignored). M0-2's local flake should NOT include that hook, to avoid the
  side-effect.
- **vitest zero-tests:** `vitest run` exits 1 on no test files; the `test` script
  uses `--passWithNoTests` so "0 tests OK" is genuinely green (exit 0).
- **better-sqlite3 native addon:** installs fine under `--ignore-scripts`
  (prebuilt, not compiled). A later milestone that actually OPENS a DB (M0-7 /
  M11) may need a real `npm install` (scripts enabled) or nixpkgs sqlite headers
  to build the native binding.
- **tsconfig:** `moduleResolution: bundler`, `module: ESNext`,
  `noUncheckedIndexedAccess` on, outDir `dist`, rootDir `src`, `*.test.ts`
  excluded from build but matched by vitest.
- **Pinned dep majors (M0-1):** zod ^3.23, better-sqlite3 ^11,
  @modelcontextprotocol/sdk ^1.0, minimatch ^10, typescript ^5.6, tsx ^4.19,
  vitest ^2.1, @types/node ^22, @types/better-sqlite3 ^7.6.
- (append more as discovered: Fable tokenizer ~+30%, refusal handling,
  FD-inheritance quirks, `[P]` scheduler edge cases.)

## Blockers

- (none.)

## Log

- 2026-06-10 — Scaffolded handoff files (CONTINUE/MEMORY/TASKS). Added the
  single-unit-of-work contract (build-time + runtime analogue) to CONTINUE.md.
  Added `DRIVE.md` — orchestrator prompt that drives the port via subagents
  (one subagent per unit; orchestrator owns the handoff files). Next: M0-1
  package boilerplate.
- 2026-06-10 — M0-1 done. Scaffolded `@spec-kit/runner` package (package.json,
  tsconfig.json, vitest.config.ts, .gitignore, src/index.ts stub) + installed
  deps via the `../runner-ts` devshell substrate. Verified: tsc build clean,
  `npm test` exit 0 (passWithNoTests), `npm run dev` runs the stub. Build GREEN.
  Next: M0-2 local flake.nix.
