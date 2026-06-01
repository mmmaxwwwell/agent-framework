# Design: spec-kit tasks.md format for the multi-developer runner

**Status:** Design doc (no code yet)
**Author:** planning session, 2026-06-01
**Companion to:** [`multi-developer-runner.md`](./multi-developer-runner.md)
**Touches (when implemented):**
`agent-framework/.claude/skills/spec-kit/phases/tasks.md` (the task-generation
prompt), `.specify/templates/tasks-template.md` (the output template), and the
DAG parser in `parallel_runner.py`.

---

## 1. Why the format must change

The multi-developer runner (companion doc) schedules *N* developers against the
DAG it parses out of `tasks.md`, and routes shared-file edits through a
coordination MCP server. To do that it needs three things the current
`tasks.md` format does not express **machine-readably**:

1. **`deps`** — the precise prerequisite story IDs (scheduling edges). Today
   ordering is implied by phase position + `[P]`, which the runner already
   parses (`get_ready_tasks`), but cross-story dependencies *within* a phase
   (e.g. "Package depends on Research") are conveyed only by sequence, not by
   ID. The runner infers them from "sequential task waits for all preceding";
   that's coarse — it blocks a story on *everything* above it, not on its
   actual prerequisites, which serializes work that could run in parallel.
2. **`touches` / `shared`** — which files a story will write, and which of those
   are also written by another story. This is what feeds the coordination
   server's intent channel (`announce_intent`, `check_intents`) and what lets
   the runner detect that two stories collide on `flake.nix`.
The runtime then makes concurrent edits to a `shared` file safe via the
intent → lock → repair protocol (companion §6) — no fragments, no integrator
story; the format only needs to *flag* the shared files so the runner knows to
take the lock.

The existing prompt already has the *semantic* layer for shared state —
`[produces: IC-xxx]` / `[consumes: IC-xxx]` interface contracts — and the
`[P]` marker. The change is **additive**: keep those, add a structured
per-story metadata block, and teach the generator to derive `deps`/`shared`
correctly.

**Backward compatibility is a hard requirement.** A `tasks.md` with no new
metadata must still run exactly as today (single-developer, phase+`[P]`
scheduling). The new fields are an *enrichment* the multi-developer scheduler
consumes; the legacy scheduler ignores them.

---

## 2. The new per-story metadata block

Each task gains an optional, indented metadata block immediately under its
checkbox line. Fields are `key: value`, one per line, values are JSON-ish
lists/strings:

```markdown
- [ ] T027 [P] Package edit-surface flake [FR-001] [produces: IC-001, IC-002]
    deps: [T026]
    touches: ["servers/edit-surface/flake.nix", "servers/edit-surface/flake.lock"]
    shared: []
    Done when: `nix build ./servers/edit-surface#default` succeeds; ...
```

Field semantics:

| Field | Meaning | Consumed by |
|---|---|---|
| `deps` | prerequisite **story IDs** — hard scheduling edges. A story is not `ready` until every id here has a completion record. | runner scheduler → coordination `stories.deps_json` |
| `touches` | files/globs this story will **write**. | intent channel; `ready` does not depend on it, but the runner uses it to detect shared-file overlap. |
| `shared` | the subset of `touches` that **another story also writes** (computed by the generator, see §3). Non-empty `shared` triggers the cooperative protocol. | coordination `stories.shared_json`; tells the developer to `check_intents` before editing. |

Relationship to existing markers (kept, not replaced):

- **`[P]`** stays as the human-readable "this can parallelize" hint and the
  legacy scheduler's input. With `deps` present, `[P]` becomes *derivable*
  (`[P]` ⇔ no `deps` on a same-phase peer) — the generator emits both so the
  file reads well and both schedulers work.
- **`[produces/consumes: IC-xxx]`** stays as the *interface* layer above raw
  files. `deps` is the concrete edge; an IC contract is the reason for it. The
  generator SHOULD derive a `deps` edge from every `consumes`→`produces` pair
  (the consumer depends on the producer's story) so the two layers agree.
- **`[needs: gh, ...]`**, `Done when:`, `[FR-xxx]` — all unchanged.

---

## 3. Generator rules (changes to `phases/tasks.md`)

Add a section to the task-generation prompt — under "Task structure" (where
`[P]` and IC contracts are already defined). The generator MUST:

1. **Emit `deps` for every task** as explicit story IDs, derived from:
   - within-server / within-feature sequence (Research → Package → Test →
     Wire), and
   - every `consumes: IC-x` → the story that has `produces: IC-x`.
   `deps: []` for a story with no prerequisites (a phase-entry parallel task).

2. **Emit `touches` for every task** — the files/globs it will write. This is
   already implicit in good task descriptions ("Package as
   `servers/<name>/flake.nix`"); the rule makes it a declared field. Use the
   same path precision the prompt already demands elsewhere.

3. **Compute `shared` — mark files written by more than one story.** After
   drafting all tasks, the generator builds the file→stories map. For any file
   written by **>1 story**, add that file to each writer's `shared` list. That
   is the *only* transformation — the writers still edit the file directly; the
   runtime intent → lock → repair protocol (companion §6) makes concurrent edits
   safe. **No fragments and no integrator story are created** (that approach was
   dropped — companion §9). A non-empty `shared` list is purely a signal to the
   runtime that the developer must take the MCP file-lock before editing.

   The generator MUST report, in its task-generation response, every shared file
   it found and which stories write it (forcing-function, like the existing E2E
   gap-analysis checklist) — so a human can sanity-check the contention set.

4. **Validate the DAG is acyclic** and that every `deps`/`consumes` id resolves
   to a real story. Reject (STOP and report) on a cycle or dangling reference —
   same posture as the existing "STOP if workflows.md missing" rule.

5. **Emit a `kind` hint per story** (e.g. `kind: research|package|test|wire|
   integrate`). The supervisor's critical-path estimator (companion §5b.1) uses
   `kind` to look up a duration prior from `run-log.jsonl` history before any
   real durations exist, so scheduling is sensible from the first story. Cheap,
   optional, ignored by the legacy scheduler.

6. **Prefer small, single-purpose stories — they reshape better.** Because the
   team can `split_story` mid-run (companion §5b.3), the generator should err
   toward stories that are already atomic (one server's research, one server's
   package) rather than omnibus tasks. Smaller stories = a finer DAG = more
   parallelism exposed and fewer mid-run splits needed. This reinforces the
   existing "one task per file / one screen per task" guidance in the prompt.

7. **Stay backward-compatible.** If the preset or feature is simple/linear, the
   metadata still emits (it's cheap and harmless); the legacy scheduler ignores
   it. The generator never *removes* `[P]` or IC markers.

---

## 4. Template changes (`.specify/templates/tasks-template.md`)

The template's `## Format` legend gains the new fields so generated files are
self-documenting:

```markdown
## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (derivable from `deps`; kept for readability)
- **deps**: prerequisite story IDs — the scheduler's dependency edges
- **touches**: files this story writes
- **shared**: subset of `touches` also written by another story → the developer
  must take the MCP file-lock before editing it (intent → lock → repair)
- **[produces/consumes: IC-xxx]**: interface contract this story emits/requires
```

One worked sample task in the template carries the full block so the generator
has a concrete pattern to imitate (the template's samples are illustrative and
stripped from real output, per its existing comment).

---

## 5. Runner changes (`parallel_runner.py`) — interface only

This doc is format-focused; the runner work is specified in the companion. The
contract between them:

- **Parser**: extend the existing `Task` dataclass (which already has
  `dependencies`, `parallel`) to populate `deps`, `touches`, `shared` from the
  metadata block. The current line-regex parser (`PARALLEL_RE`, the
  phase/task walker around `get_ready_tasks`) gains a metadata-block reader.
- **Plan load → coordination DB**: on run start, the supervisor writes one
  `stories` row per task (`deps_json`, `touches_json`, `shared_json`,
  `produces/consumes`) into the coordination server's SQLite store (companion
  §7.2). This is the single source of truth the developers then query via
  `ready_stories` / `check_intents`.
- **Scheduler upgrade**: `get_ready_tasks` gains a DAG mode — a task is ready
  when every `deps` id has a `done` record AND it is unclaimed — used when N>1.
  When N==1 or no metadata is present, the existing phase+`[P]` logic is the
  fallback (backward compat, §1).

---

## 6. Worked example (the 7-server plan, in the new format)

```markdown
### codebase (tree-sitter-mcp)

- [ ] T010 [P] Research tree-sitter-mcp [FR-007]
    deps: []
    touches: ["servers/codebase/README.md"]
    shared: []
- [ ] T011 Package tree-sitter-mcp flake [FR-001] [produces: IC-001, IC-002]
    deps: [T010]
    touches: ["servers/codebase/flake.nix", "servers/codebase/flake.lock"]
    shared: []
- [ ] T012 Create tests/codebase.sh [FR-005]
    deps: [T011]
    touches: ["tests/codebase.sh"]
    shared: []
- [ ] T013 Wire codebase into root [FR-008] [consumes: IC-001, IC-002]
    deps: [T012]
    touches: ["flake.nix", "scripts/claude-with-servers"]
    shared: ["flake.nix", "scripts/claude-with-servers"]  # written by every server's wire story
    Done when: `nix build .#tree-sitter-mcp` works; entry present in .mcp.json

# ... 6 more servers, identical shape. All 7 wire stories list the same two
#     files in `shared`; at runtime each takes the MCP file-lock before editing,
#     so they serialize only for the brief edit window. No integrator node.
```

Reading this, the runner sees: 7 research stories with `deps: []` → width 7 →
N up to 7 developers. Each server chain serializes on its own `deps`. The 7
wire stories all list `flake.nix` + `claude-with-servers` in `shared`, so each
takes the file-lock before editing — they run fully in parallel right up to the
seconds-long edit window, where the lock serializes them and the repair loop
backstops. This is the companion doc's §6 + §8, expressed in the file format the
generator produces. (Phase 3 integration tasks like T034–T038 still exist as
*verification* — `nix flake show`, `tests/integration.sh` — but they are no
longer a fragment-merge step.)

---

## 7. Open questions

1. **Metadata syntax**: indented `key: [json]` lines (as above) vs. an HTML
   comment block vs. a fenced `yaml` sub-block. Indented lines are the lightest
   and survive Markdown rendering; chosen here pending implementation taste.
2. **Glob semantics in `touches`**: how precise must globs be for overlap
   detection? `servers/<name>/**` never overlaps across servers, but root files
   are exact paths — the generator should prefer exact paths for anything that
   could be shared.
3. **Derived vs. authored `shared`**: the generator computes `shared`, but
   should a human be able to *force* a file into `shared` (e.g. a file two
   stories append to that the generator didn't catch)? Lean yes — authored
   `shared` is a union with the computed set.
4. **(Resolved — removed)** Fragment/integrator approach was dropped in favor of
   direct edits under intent → lock → repair (companion §6, §9). The generator
   no longer emits fragments or an integrator story; it only marks `shared`
   files so the runtime knows to take the file-lock. Nothing left open here.
