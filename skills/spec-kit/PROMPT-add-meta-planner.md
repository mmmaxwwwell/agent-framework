# Prompt: add a project-planning brief + meta-planner loop to `parallel_runner.py`

You are extending `parallel_runner.py` (the spec-kit parallel task runner) with two new features:

1. **A repo-wide "planning brief"** at `specs/META.md` — a dense markdown summary of every Claude Code planning session in this repo, regenerated on demand. This is the cache target.
2. **A meta-planner loop** — a single agent that runs on its own cadence, primed with the brief + dynamic state, and amends `tasks.md` to keep the 5-wide executor pool on track.

The 5-wide executor pool is UNCHANGED. Do not touch executor spawn paths, prompt assembly, or sandboxing for executors. Only the meta-planner and the brief-generator are new agents.

---

## Files you may edit

- **`/home/max/git/agent-framework/skills/spec-kit/parallel_runner.py`** — primary edit surface. Add new functions; hook into `_run_feature` and the main loop.

## Files you must read first (in order)

- `/home/max/git/agent-framework/skills/spec-kit/parallel_runner.py` — at least: `_run_feature` (~line 10293), main loop (~line 10105 `def run`), `spawn_agent` (~line 3543), `_build_sandbox_cmd` (~line 3308), `parse_task_file` (~line 441). Understand how executors are spawned, sandboxed, and how tasks.md is re-parsed each iteration.
- `/home/max/git/agent-framework/skills/spec-kit/SKILL.md` — the spec-kit workflow phases (constitution → specify → clarify → plan → workflows → tasks → implement). The brief must reflect these phases.
- `/home/max/git/agent-framework/skills/spec-kit/phases/implement.md` — implementation-phase rules. The meta-planner must respect them when amending tasks.md.
- `/home/max/git/agent-framework/skills/spec-kit/reference/proof-discipline.md` and `reference/verification.md` — the substrate-evidence discipline. Meta-planner must not undermine it.

---

## Feature 1: `specs/META.md` — the project planning brief

### Decisions already made (do not re-litigate these)

- **Location**: single file at `specs/META.md`. Not a directory.
- **Trigger**: re-generate when stale. "Stale" = at least one planning JSONL or `specs/*/spec.md` / `plan.md` / `tasks.md` has an mtime newer than the brief's, AND that mtime change isn't from a task being ticked off (see "What counts as a real planning change" below).
- **Block on regen**: when stale is detected, regen runs synchronously inside `_run_feature` before any executor or meta-planner spawns. ~30-90s cold-start cost is acceptable.
- **Kill switch**: env var `SPEC_KIT_SKIP_BRIEF_REGEN=1` skips the regen entirely (CI, debugging). Use this in `_ensure_planning_brief`.
- **Generator output discipline**: the generator prints literal `OK` to stdout and writes `specs/META.md` as its only side effect. Prompt instructs it explicitly: "Output to stdout: only the literal string OK. Write the brief to specs/META.md. Do not explain. Do not summarize what you wrote. Exit." Output tokens must stay near zero.
- **Model**: Opus 4.7 with max effort for the brief generator. The brief is the cache target — quality of summary matters more than cost (one-off).
- **Executor exclusion**: `specs/META.md` must NOT be parsed as a feature by the existing `sorted(...)` discovery at ~line 19720. Filter it out.

### What counts as a real planning change (the staleness function)

Naive mtime comparison is wrong because executors mark tasks `- [x]` constantly, and each one bumps tasks.md's mtime. The staleness check must distinguish:

- **Real**: a new JSONL appearing in `~/.claude/projects/<repo-slug>/`; a `spec.md`, `plan.md`, `data-model.md`, `workflows.md`, or `research.md` being created or modified; tasks.md gaining entirely new task IDs (not status flips on existing ones).
- **Not real**: tasks.md being modified solely to flip `- [ ]` → `- [x]` / `- [!]` / `- [~]` on existing task IDs; `learnings.md` being appended; anything under `validate/`, `claims/`, `attempts/`, `reasoning/`, `test-logs/`.

Implementation hint: compute a hash of (sorted list of JSONL paths + their mtimes) ∪ (set of task IDs across all specs/*/tasks.md) ∪ (mtimes of spec.md/plan.md/data-model.md/workflows.md/research.md). Compare to a hash stored in `specs/META.md`'s frontmatter or a sibling `specs/.META.hash`. Hash mismatch → stale.

### JSONL discovery

```python
import os
repo_slug = str(Path.cwd().resolve()).replace('/', '-').lstrip('-')
# e.g. /home/max/git/kanix → home-max-git-kanix
# Sessions live at ~/.claude/projects/-home-max-git-kanix/*.jsonl
session_dir = Path.home() / ".claude" / "projects" / f"-{repo_slug}"
jsonls = sorted(session_dir.glob("*.jsonl"))
```

### Brief structure (the generator emits this)

```markdown
---
generated_at: <ISO timestamp>
source_hash: <hex>
sources:
  - uuid: <jsonl-uuid>
    first_user_msg: "<first 200 chars>"
    started: <iso>
    role: diagnosis | planning | strategist | unclassified
  - ...
specs_included:
  - <feature>/spec.md
  - <feature>/plan.md
  - ...
---

# Project Planning Brief

## Cross-feature context
<things true of the whole repo: tech stack, conventions, hard constraints,
recurring failure modes, what the user values vs. tolerates>

## Feature: <name>
### Discoveries
- <what the diagnosis sessions surfaced — bugs, root causes, dead ends>
### Decisions
- <architectural choices made during planning, with the reason>
### Watch-for
- <gotchas an executor or meta-planner must avoid; failure modes the planning
  sessions explicitly anticipated>
### Open questions
- <known unknowns the planner flagged but didn't resolve>

## Feature: <next>
...
```

The generator's prompt must include the literal section structure above so the brief is parseable by downstream consumers.

### The generator's prompt (use this verbatim as the basis)

```
You are generating a planning brief for a spec-kit project.

INPUTS — read all of these:
- Every JSONL at: <list of full paths>
- Every file at: <list of specs/*/{spec,plan,data-model,workflows,research}.md>

OUTPUT — write exactly one file: specs/META.md
SCHEMA — the file MUST match this structure:
<paste the brief structure block above>

RULES:
- Print only the literal string "OK" to stdout. Nothing else.
- Do not explain what you wrote. Do not summarize your reasoning.
- The brief is read by other agents — be dense, factual, specific. No
  filler. No "the user asked", no "the agent then", no chit-chat.
- For each Discovery / Decision / Watch-for / Open question, lead with
  the specific concrete fact, then a parenthetical with file:line or
  session UUID for traceability.
- Length budget: 15-25k tokens. Compress aggressively but do not omit
  load-bearing constraints.
- If two sessions cover the same feature, merge their content under
  one Feature heading. Do not duplicate.
- Sources frontmatter must list every JSONL you read with role inferred
  from its first user message.

Exit with status 0 when the file is written.
```

### How to invoke the generator

The runner shells out to `claude` (the CLI) the same way `spawn_agent` does, but with:

- `--print` (non-interactive)
- `--output-format json`
- `--model claude-opus-4-7`
- `--effort max`
- `--dangerously-skip-permissions` (the generator needs to write `specs/META.md`)
- The prompt as positional arg
- The same `bwrap` sandbox `spawn_agent` uses, with `specs/` writable

Capture stdout (must be `OK\n` or close to it — log a warning if it's longer than 100 bytes; that means the generator broke discipline). Capture stderr to a log file under `specs/.meta-planner-logs/brief-<timestamp>.stderr`.

Synchronous: `subprocess.run(...)` with a timeout (5 minutes — Opus max effort on ~700K tokens of input can be slow). On timeout, log a warning and proceed with the existing brief (if any).

### Hook point in `parallel_runner.py`

Add a call near the top of `_run_feature` (line 10293), right after `if not task_file.exists(): return`:

```python
if not os.environ.get("SPEC_KIT_SKIP_BRIEF_REGEN"):
    _ensure_planning_brief()  # repo-wide, no spec_dir argument needed
```

`_ensure_planning_brief` should be module-level, not a method of the runner. It operates on `Path.cwd()` (the repo root) regardless of which feature is currently being processed. It's idempotent — if the brief is fresh, it's a no-op (single hash compare, < 100ms).

Use `fcntl.flock` on `specs/.META.lock` so concurrent runner invocations don't race.

---

## Feature 2: meta-planner loop

A single, separate agent that runs on its own cadence concurrently with the 5-wide executor pool. Reads what executors have been doing. Edits `tasks.md` to keep them on track. Does not touch code, does not run tests.

### Decisions already made

- **Model**: Opus 4.7 max effort (same as the brief generator). This is judgment work, not text production.
- **Cadence**: configurable via CLI flag `--meta-planner-interval-min`, default 15 minutes. Honor `--meta-planner-disabled` to skip the loop entirely.
- **Cache target**: the meta-planner's stable prefix is `specs/META.md` (the brief) + spec-kit reference files + a short persona. The dynamic delta is `tasks.md` + run-log.jsonl tail + recent `validate/*/review-*.md` + any `BLOCKED.md`.
- **What it can write**: only `tasks.md`. Forbidden: `validate/`, `claims/`, `attempts/`, `learnings.md`, any source code. Enforce via bwrap mount restrictions (rebind those dirs read-only).
- **Audit trail**: every meta-planner invocation appends to `specs/.meta-planner-log.jsonl` with `{timestamp, model_used, input_tokens, output_tokens, cache_read_tokens, diff_applied, reasoning_summary}`. The agent itself does not need to write reasoning prose — the diff IS the reasoning.
- **Output discipline**: meta-planner prints either `NOCHANGE\n` (and exits 0) or a unified-diff against tasks.md to stdout. The runner applies the diff with `patch -p1` after validating it touches ONLY tasks.md. Anti-discipline output (prose, explanations) → log warning, treat as NOCHANGE.

### Anti-thrash rules (enforce in the runner, not just the prompt)

1. **Forward-only**: meta-planner cannot edit a task that has any `task_spawn` event in `run-log.jsonl` newer than the last meta-planner tick. Read run-log, build the set of "touched task IDs since my last run", strip those lines from the diff before applying. If the diff is non-empty after stripping, apply it; if empty, log "would have edited touched tasks; suppressed."

2. **Cooldown after 3 consecutive change-ticks**: if the last 3 meta-planner runs all produced non-empty diffs, the next run is forced to `NOCHANGE` (skip the spawn entirely, log "thrash suppression"). Re-enables after 1 tick of executor activity.

3. **Diff size cap**: any single tick that produces a diff > 200 lines is rejected and logged. Meta-planner is for incremental nudges, not rewrites.

### The meta-planner's prompt (use as basis)

```
You are the meta-planner for a spec-kit execution. You watch a pool of
executor agents and amend specs/<feature>/tasks.md to keep them on track.

CACHED CONTEXT (above): specs/META.md, spec-kit reference files, persona.

DYNAMIC CONTEXT (below):
- Current specs/<active-feature>/tasks.md
- run-log.jsonl entries since timestamp <T>
- Any review-*.md files modified since <T>
- Any BLOCKED.md present in specs/<feature>/

YOUR JOB:
Decide whether tasks.md needs to change based on what executors have been
doing since <T>. Reasons to change:
- An executor wrote BLOCKED.md → insert an investigation task before the
  blocked one, or relax the blocked task's done-criteria with a reason.
- A review-*.md surfaces a gap not covered by the existing task list →
  append a follow-up task in the affected phase.
- An executor produced output that violated a planning constraint (see
  Watch-for sections of META.md) → mark the task [!] for rework and add
  a clarifying note inline.
- Two parallel tasks are stepping on each other → drop the [P] from one.
- A task as written is unachievable given new info → split it into
  smaller tasks or mark it [~] (skipped) with a reason.

DO NOT:
- Edit any task whose ID appears in run-log.jsonl events newer than <T>.
- Add tasks that contradict META.md's Decisions section.
- Touch any file other than tasks.md.
- Write reasoning prose. Your output IS the diff.

OUTPUT (strict):
- If no change needed: print "NOCHANGE" to stdout. Exit 0.
- Otherwise: print a unified diff (the kind `patch -p1` accepts) of
  tasks.md changes to stdout. No header text. No trailing explanation.
  Exit 0.
- Any other output is treated as malformed and discarded.
```

### Hook point in `parallel_runner.py`

The meta-planner runs in its own thread, started from `run()` (the main loop, ~line 10105) before the feature loop begins, and stopped on shutdown.

Thread loop:

```python
def _meta_planner_thread(self):
    interval_s = self.meta_planner_interval_min * 60
    last_tick_ts = time.time()
    consecutive_change_ticks = 0
    while not self._shutdown:
        # Sleep with shutdown awareness
        if self._shutdown_event.wait(timeout=interval_s):
            return
        # Find the active feature (most recent task_spawn in run-log)
        active_feature = self._infer_active_feature()
        if not active_feature:
            continue
        # Cooldown check
        if consecutive_change_ticks >= 3:
            self.log("meta-planner: thrash cooldown, skipping tick")
            consecutive_change_ticks = 0
            last_tick_ts = time.time()
            continue
        # Spawn the meta-planner agent
        diff = self._spawn_meta_planner(active_feature, last_tick_ts)
        if diff and diff.strip() != "NOCHANGE":
            applied = self._apply_meta_planner_diff(active_feature, diff, last_tick_ts)
            if applied:
                consecutive_change_ticks += 1
            else:
                consecutive_change_ticks = 0
        else:
            consecutive_change_ticks = 0
        last_tick_ts = time.time()
```

### Sandbox for the meta-planner

Use `_build_sandbox_cmd` but with extra `--ro-bind` mounts for:

- `specs/<feature>/validate/` (RO)
- `specs/<feature>/claims/` (RO)
- `specs/<feature>/attempts/` (RO)
- All source code dirs (RO — meta-planner doesn't read them anyway)

Only `specs/<feature>/tasks.md` and `specs/.meta-planner-log.jsonl` are RW (use `--bind` for the file, not the dir, where possible).

### Diff validation before apply

```python
def _apply_meta_planner_diff(self, feature, diff_text, last_tick_ts):
    # 1. Validate: diff touches ONLY specs/<feature>/tasks.md
    # 2. Validate: diff is < 200 lines total
    # 3. Strip hunks affecting task IDs that have task_spawn events newer than last_tick_ts
    # 4. If diff is still non-empty: apply with `patch -p1 --dry-run` first, then real
    # 5. On any failure: log to specs/.meta-planner-log.jsonl with status=rejected, reason=<why>
    # 6. On success: log with status=applied, diff_summary=<first 5 lines>
    ...
```

---

## CLI additions

Add to `main()`'s argparse:

```python
parser.add_argument("--meta-planner-interval-min", type=int, default=15,
                    help="Minutes between meta-planner ticks (default 15)")
parser.add_argument("--meta-planner-disabled", action="store_true",
                    help="Skip meta-planner loop entirely")
parser.add_argument("--meta-planner-model", default="claude-opus-4-7",
                    help="Model for meta-planner (default opus 4.7)")
```

Pass into the runner constructor; store as instance attrs.

---

## Tests / verification

Before finishing, verify:

1. `_ensure_planning_brief` is idempotent: calling it twice in a row with no JSONL changes triggers no claude invocation on the second call (check via mtime, or log the early-return).
2. The kill switch works: `SPEC_KIT_SKIP_BRIEF_REGEN=1 python parallel_runner.py ...` makes zero claude invocations for brief regen.
3. The staleness function correctly ignores tick-off-only modifications to tasks.md. Write a small test: snapshot the hash, mark a task `[x]`, recompute hash, assert equal.
4. specs/META.md is excluded from the feature discovery list (the existing `spec_dirs = sorted(...)` at line 19720).
5. The meta-planner thread is properly joined on shutdown — no zombies.
6. Diff validation rejects: diffs touching files other than tasks.md; diffs > 200 lines; malformed diffs.
7. Run a dry-run end-to-end on the kanix belt-editor remediation: brief regenerates once (or no-op if already fresh from a prior run), meta-planner ticks at 15min intervals, every tick logs to specs/.meta-planner-log.jsonl.

---

## What you must NOT do

- Do not change executor agent prompts. They keep using the existing `build_prompt` / `spawn_agent` path.
- Do not change `parse_task_file` semantics. The runner's main loop already re-parses tasks.md every iteration; the meta-planner just edits the file and lets the existing re-parse pick it up.
- Do not add a dependency on a Python package not already imported by parallel_runner.py. Use only stdlib + whatever's already imported.
- Do not write to specs/META.md directly from Python. Always go through the claude CLI generator. The generator's prompt is the contract.
- Do not catch generic exceptions silently. Every failure path logs to specs/.meta-planner-log.jsonl with enough detail to diagnose.

---

## Definition of done

- `specs/META.md` exists and is non-empty after the first invocation in a fresh repo with planning sessions.
- The brief is regenerated only when planning sources actually change (not on task tick-off).
- The meta-planner loop runs, ticks at the configured interval, applies diffs that pass validation, suppresses thrash and forbidden edits.
- All audit lines land in `specs/.meta-planner-log.jsonl`.
- The kill switch works for both brief regen and the meta-planner loop.
- Existing executor behavior is unchanged. Existing parse/validate/review machinery untouched.
- No new files in the repo other than: `specs/META.md`, `specs/.META.hash` (or hash in META.md frontmatter), `specs/.META.lock`, `specs/.meta-planner-log.jsonl`, `specs/.meta-planner-logs/*.stderr`.
- All of these new files added to `.gitignore` EXCEPT `specs/META.md` (which IS committed — it's a checked-in artifact).

---

## Suggested implementation order

1. Read the files listed under "Files you must read first."
2. Implement `_ensure_planning_brief` + the staleness hash function + the kill switch. Test it on the kanix repo (which has 2 planning JSONLs). Commit.
3. Add the feature-discovery exclusion for `specs/META.md`. Verify the runner still works against kanix. Commit.
4. Implement the meta-planner thread skeleton (no agent spawn yet — just the timing loop and the log file). Commit.
5. Implement `_spawn_meta_planner` (the claude CLI invocation with the cached prefix and dynamic delta). Commit.
6. Implement `_apply_meta_planner_diff` with all the validation rules. Commit.
7. Wire CLI flags. Commit.
8. End-to-end test on kanix belt-editor. Commit.

Each commit should be small, reviewable, and reversible. Do not bundle.
