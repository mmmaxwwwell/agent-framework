# Design: Multi-Developer Parallel Runner

**Status:** Design doc (no code yet)
**Author:** planning session, 2026-06-01
**Context:** Upgrade the existing single-stream task runner into a supervisor
that runs *N* concurrent "developer" workers against one task list, where
workers respect cross-task dependencies and coordinate cooperatively through a
**runner-internal coordination MCP server backed by SQLite**.

> **Revision (2026-06-01):** Inter-developer coordination moved from loose
> coordination files to an **MCP server (agent-facing API) with a SQLite store
> behind it**. Agents announce/observe intent by calling MCP tools, not by
> writing JSON files. Rationale and protocol in §6–§7. Durable *results*
> (completion claims, `learnings.md`, `run-log.jsonl`) are unchanged — see §7.4
> for the split.

---

## 1. Motivation

The current runner is a **supervisor with one developer**. It walks `tasks.md`
top-to-bottom, spawns one agent per task, waits for it to finish, records a
completion claim, and moves on. Evidence in the repo:

- `run-log.jsonl` — `task_spawn` → `task_complete` events, strictly serial
  (`T023` finishes, *then* `T024` spawns, *then* `T025`).
- `claims/completion-T0xx.json` — each finished task writes a claim that
  **already declares `files_created` and `files_modified`**.
- `attempts/T0xx.jsonl` — per-task attempt log (supports retries via `attempt`).
- `learnings.md` — shared, append-only knowledge base across tasks.

The task list itself already encodes the dependency structure the supervisor
needs: `[P]` markers, `[consumes: IC-xxx]` / `[produces: IC-xxx]` interface
contracts, and explicit "Dependencies & Execution Order" prose. tasks.md
already states the invariant we want to exploit: *"All 7 servers are
independent of each other; sequential within each server."*

**The gap is not the result-recording bus — it already exists. The gap is:**

1. The supervisor runs **one** developer, not N.
2. Coordination is **backward-looking and supervisor-mediated only**. Claims
   are written on *completion*; there is no *forward* channel for one developer
   to announce "I am about to edit `flake.nix`" and for another to observe it
   live. Today agents never talk — the Python supervisor reads claims and
   decides everything.
3. There is no DAG-aware scheduler that lets developer A run ahead while B is
   still working a prerequisite, then block A precisely at the dependency edge.

This doc specifies those three additions and the cooperative protocol —
delivered as a **coordination MCP server** — that keeps N developers from
clobbering each other.

### 1.1 Why MCP instead of coordination files

The original draft used loose JSON files (`intents/`, `blocked/`) as the live
coordination channel. We changed to a **runner-internal MCP server**:

- **Agents already speak MCP.** A spawned `claude` developer calls
  `announce_intent(...)` / `check_intents(...)` as ordinary tool calls — no
  "go read this directory and parse JSON" instruction, no prompt bloat, no
  parse-skew between developers. Coordination becomes a typed contract.
- **It fits the project thesis.** mcp-toolbelt's whole premise is "MCP servers
  that mechanically pre-process and mediate." Coordination-as-MCP is the same
  pattern applied to multi-agent scheduling.
- **SQLite behind it gives atomicity for free.** The one place we need true
  mutual exclusion — claiming a ready story so two developers don't both grab
  it — is a single `INSERT ... ON CONFLICT DO NOTHING`. Transactional reads of
  the intent set are consistent by construction. This also matches the
  project's standing decision (see project memory): *SQLite FTS5 over vector
  stores; shared SQLite with namespaced tables.*
- **Durable + restartable + inspectable.** Because state lives in SQLite, a
  supervisor or developer crash doesn't lose coordination state, and the DB is
  queryable for the live dashboard and post-hoc audit — the same properties the
  file bus gave, with stronger consistency.

---

## 2. Object model (three levels)

The key structural fact: **a "developer" is one instance of the *old*
`parallel_runner.py`** — the entire single-stream runner (its scheduler,
fix-validate loop, review cycle), reclassified from a top-level procedure into a
`Developer` class. The new **Supervisor** holds a dict of N such instances **in
one Python process** and drives them. Each developer, internally, still spawns
many `claude` subprocesses to execute a story (implement agent, review agent,
fix agents) exactly as the old runner does today.

So there are three levels, not two:

```
Supervisor  (the NEW runner — one process)
  └── developers: dict[dev_id -> Developer]      # N instances of the OLD runner
        each Developer:
          - runs the existing single-stream machinery (get_ready_tasks,
            fix-validate, review) — REUSED WHOLESALE, scoped to its stories
          - spawns many `claude` subprocesses per story (unchanged)
          - calls the coordination MCP server to claim/announce/publish
```

```
class Developer:                  # == an instance of the old parallel_runner
    id            # "dev-1"
    stories       # the story IDs this instance is responsible for (a view, not
                  #   exclusive ownership — claims are atomic via §7.3)
    state         # idle | working | blocked | done
    blocked_on    # story ID this developer is waiting for (if blocked)
    # ... plus everything the old runner already carried (phase state,
    #     review state, agent-spawn bookkeeping)

class Supervisor:                 # == the new runner
    developers    # dict[dev_id -> Developer]   (dynamic N)
    plan          # the DAG, parsed from the task list
    coord         # client to the coordination MCP server (SQLite-backed, §7)
```

- A **Developer** is "what the runner used to be," instantiated N times. Its
  internals — the scheduler, the fix-validate loop, the review cycle, the
  per-story `claude` subprocess spawning — are **reused unchanged**. The
  supervisor does not reimplement any of that machinery.
- **N instances run in-process** (chosen model): the supervisor refactors the
  old runner into the `Developer` class and instantiates N of them in one
  process, driving them concurrently (async tasks / threads). Because they
  share a process, coordination *could* be in-memory — but the substrate is
  MCP+SQLite (§7) so the `claude` subprocesses each developer spawns can also
  announce/check intent, and so state is durable + inspectable. SQLite is the
  source of truth; any in-memory view is a cache of it.
- The **Supervisor** is the new layer: it parses the DAG, instantiates the N
  developers, and runs a *second* scheduling layer *above* each developer's
  existing one — deciding which stories are ready and letting developers claim
  them, blocking a developer at a dependency edge until the prerequisite lands.
- **N is dynamic**, chosen per-plan from the DAG's structure (§5). Sometimes
  N=1 (a purely linear plan — behaves like today); sometimes N=5 (a wide
  fan-out like the 7 independent servers).

### 2.1 Two scheduling layers

There are now two schedulers, and they do not conflict:

| Layer | Who | Scope | Decides |
|---|---|---|---|
| **Supervisor scheduler** (new) | the new runner | the whole DAG | which stories are `ready` and in what **priority order** (critical-path weight, §5b.1); applies developer-proposed DAG mutations (§5b.3); recomputes weights + N as the plan reshapes |
| **Developer scheduler** (existing) | each old-runner instance | the stories that developer claimed | phase ordering, `[P]` within its slice, fix-validate, review — i.e. today's `get_ready_tasks` logic, unchanged |

When N==1 the supervisor layer is a thin pass-through and the system reduces to
exactly today's behavior — the backward-compat guarantee.

---

## 3. The task list format (source of truth)

The plan is **still parsed from the task list** — the format gains explicit,
machine-readable dependency and file-touch metadata so the supervisor can build
the DAG without prose-parsing. Each story (task) declares:

```
- [ ] T027 [story]
    deps: [T026]                       # prerequisite story IDs (hard edges)
    touches: [servers/edit-surface/**] # files/globs this story will write
    shared: []                         # subset of `touches` that other stories also write
    produces: [IC-001, IC-002]         # interface contracts emitted
    consumes: [IC-001]                 # interface contracts required
    Package edit-surface as servers/edit-surface/flake.nix ...
```

Notes:

- `deps` are the **scheduling edges**. The supervisor will not start a story
  until every `deps` entry has a completion claim.
- `touches` / `shared` are the **conflict-avoidance metadata**. `shared`
  entries (a file written by more than one story — e.g. root `flake.nix`,
  `scripts/claude-with-servers`) trigger the cooperative protocol in §6.
- `produces` / `consumes` already exist in tasks.md as `[produces: IC-xxx]`.
  We keep them; they are the semantic layer above raw file edges (a story can
  consume an *interface* without caring which file produced it).
- Existing `[P]` markers are derivable from this (`[P]` == no `deps` on
  same-server peers), so the upgrade is backward-compatible: a plan with no
  metadata degrades to the current single-stream behavior.

The supervisor builds the DAG from `deps` + `consumes/produces`, validates it
is acyclic, and rejects the plan if not.

---

## 4. The developer loop (claim → work → publish)

Each developer instance runs a loop that does as much ready work as it can,
then awaits more. Since developers are **in-process** (§2), a blocked developer
is a coroutine/thread that `await`s an event the supervisor sets when a
dependency completes — no cross-process polling needed. (If the model were ever
promoted to separate processes, the same loop falls back to poll-and-sleep; the
coordination contract is identical either way.)

```
run():                                          # the developer's top-level loop
  while True:
      ready = coord.ready_stories(dev=me)       # deps satisfied AND unclaimed
      if ready:
          story = ready[0]
          if not coord.claim_story(story, dev=me):   # atomic INSERT ... ON CONFLICT (§7.3)
              continue                                # lost the race; re-evaluate
          coord.announce_intent(story, dev=me, touches=story.touches, action="...")
          run_old_runner_for(story)             # ← the ENTIRE existing single-stream
                                                #   machinery: implement agent, fix-validate
                                                #   loop, review cycle, claude subprocesses
          coord.publish_done(story, files_modified=..., contracts=...)  # clears intent + records
          write claims/completion-<story>.json  # durable result mirror (§7.4)
      elif coord.has_unstarted():               # work remains in the DAG but all blocked
          coord.mark_blocked(dev=me, blocked_on=<dep>)
          await supervisor.work_available        # set on any publish_done (§ push-wake)
      else:
          coord.mark_done(dev=me); return        # DAG drained
```

Every `coord.*` is a call against the coordination MCP server (§7).
`run_old_runner_for(story)` is **the old runner, unchanged** — that is the whole
point of the object model in §2: the developer *is* the old runner, so this step
is not reimplemented, it is invoked.

**Blocking is an in-process await, not a busy-wait.** Because all N developers
live in one process with the supervisor, a blocked developer suspends on an
asyncio event / condition variable that the supervisor sets the instant any
`publish_done` lands (push-wake, ~0 latency). The supervisor owns both the
coordination DB and the developer objects, so it knows exactly which blocked
developers might now have ready work and wakes them.

> *(Earlier draft note, kept for the separate-process fallback: if developers
> were separate processes they could not share an in-memory event, so blocking
> would be poll-and-sleep with a sub-5-minute interval to stay cache-warm. The
> in-process model removes that concern.)*

This is the "developer A goes as far as he can and waits for the prerequisite
work by developer B" behavior — and in the in-process model it is a direct
`await` on a supervisor-set event, so A resumes the instant B's `publish_done`
makes one of A's stories ready.

---

## 5. Choosing N (dynamic width)

The supervisor sizes the developer pool from the DAG, not from a fixed config:

```
width = max over all "levels" of (number of stories with no unsatisfied deps at that level)
N = min(width, concurrency_cap, budget_cap)
```

- `width` = the widest parallel front the DAG ever exposes (for the 7
  independent servers, width = 7 at the research level).
- `concurrency_cap` = the runner's hard ceiling on simultaneous agents
  (~min(16, cores−2) in the Workflow runtime; the same cap applies whether the
  developers are Workflow instances or background agents).
- `budget_cap` = derived from the turn's token target if one is set
  (`floor(total / per_developer_estimate)`), so a "+500k" directive scales the
  pool and an unbounded run uses `width`.

N is recomputed if the plan changes mid-run (a story is split, a dep added).

**Distribution model — pure pull / work-stealing (decided).** There are no
per-developer queues. Every idle developer calls `ready_stories()` and
`claim_story()` against the *global*, **priority-ordered** ready-set (§5b.1);
SQLite's atomic claim (§7.3) arbitrates races. A story's "owner" is simply
whichever developer won its claim. This is self-balancing — a fast developer
naturally pulls more stories, a developer stuck on a slow story doesn't starve
the others — and needs no reassignment logic. The in-process model makes a pull
near-free, so there is no locality argument for pre-partitioning. The `stories`
field in the `Developer` object (§2) is a *view of what it has claimed so far*,
not an assigned queue.

---

## 5b. Intelligent parallelism: minimizing wall-clock

The goal is not "run independent things at once" — it is **minimize wall-clock**.
That decomposes into three mechanisms beyond mechanical coordination: schedule
along the critical path, let an idle developer always pull the most valuable
ready work, and let the team *reshape the plan* as it discovers reality. All
three are decided (design-owner directed).

### 5b.1 Critical-path-first scheduling

The wall-clock floor of any DAG is its **longest dependency chain** (sum of
story durations along it). To not blow past that floor, the critical path must
never sit waiting for a free developer. So:

- The supervisor computes, per story, a **downstream weight** = the longest
  remaining dependency chain that runs *through* this story (standard DAG
  longest-path / CPM). Higher weight ⇒ more wall-clock rides on it.
- `ready_stories()` returns the ready-set **ordered by downstream weight,
  descending**. Work-stealing (§5) then naturally pulls critical-path work
  first: "steal next ready story" = "steal the highest-weight ready story."
- **Durations are estimated, and the estimate improves.** Up front, weights use
  a per-story-*type* prior drawn from `run-log.jsonl` history (the runner
  already records `duration_s` per task — e.g. "research ≈ 3 min, npm package ≈
  10 min"). As real stories complete, measured durations replace the prior and
  the supervisor **recomputes weights**. This is *critical-path-biased*
  scheduling, not provably optimal — optimal DAG scheduling under unknown
  durations is unattainable — but the bias captures the dominant share of the
  available wall-clock reduction.

### 5b.2 Idle developer → steal highest-priority ready story (decided)

When a developer finishes and others are mid-story, it immediately pulls the
top of the priority-ordered ready-set (§5b.1). No assist/review detour, no
idling while work exists. A developer idles (awaits the supervisor event, §4)
only when the ready-set is genuinely empty — i.e. everything left is blocked.
This keeps every developer saturated on the most wall-clock-relevant work
available at that instant.

### 5b.3 Dynamic DAG reshaping — the team adapts the plan (decided)

A frozen plan can't be optimal, because the plan is written before anyone has
*done* the work. A developer mid-story discovers things that change what's
downstream (this upstream is Rust not TS; there's no `Cargo.lock`; the entry
point needs a wrapper; this "one" packaging task is really two). A real team
surfaces that and re-plans. So developers may **propose plan mutations**, which
the supervisor validates and applies.

**Allowed mutations (a deliberately small, composable set):**

| Mutation | Use |
|---|---|
| `split_story(id, [sub-stories])` | one story is really N; replace it with sub-stories + their deps |
| `add_story(story, deps)` | a missing prerequisite surfaced (e.g. "vendor a lockfile before packaging") |
| `add_dependency(from, to)` | discovered ordering: `from` must precede `to` |
| `flag_blocker(id, detail)` | "I'm stuck / this needs a human or another dev" — does not mutate the DAG, escalates |

Arbitrary rewrites are **not** allowed — these four cover the real cases and
keep the DAG statically analyzable.

**The supervisor is the sole DAG writer (same pattern as control verbs).** A
developer calls `propose_plan_change(...)` (coordination tool, §7.1) which
writes to a `proposals` table. The supervisor, on its loop:
1. **validates** — still acyclic? do referenced IDs exist? (reject + log if not);
2. **enforces the in-flight rule** (below);
3. **applies** the mutation to the `stories` table;
4. **recomputes** critical-path weights (§5b.1) and **re-wakes** any developer
   whose ready-set changed (§4 push-wake);
5. **recomputes N** if the DAG's width changed (§5).

**The in-flight rule (prevents retroactive corruption).** A mutation is valid
only against **not-yet-started** stories. You cannot add a dependency *onto* a
story that is already running or done (you can't un-run it), nor split a story
someone is mid-way through. A proposal that would do so is rejected and
converted to a `flag_blocker` for the supervisor to reconcile (e.g. by spawning
a follow-up fix story). This is the single rule that keeps reshaping safe.

**This subsumes knowledge-sharing.** Once developers publish structured
discoveries, a finding splits two ways: one that changes the DAG becomes a
`propose_plan_change`; one that's merely *useful to a peer* ("upstream tags are
calver, not semver") becomes a `findings` row (§7.1 `share_finding` /
`read_findings`) that downstream developers read before starting related work —
the structured upgrade of today's append-only `learnings.md`. Either way the
team stops re-learning and re-deciding the same things in parallel.

Two stories sometimes edit the same shared file (root `flake.nix`,
`scripts/claude-with-servers`). **There are no fragments and no integrator
story** — developers edit the real files directly, coordinated through the MCP
server. Safety comes from three layers stacked as a sequence, each catching what
the one before it can miss: **advisory intent** (cooperation/visibility), then
an **MCP file-lock** (correctness — closes the race intent alone leaves open),
then the **repair loop** (heals any residual, including collisions with agents
that never spoke to the server). Defense in depth; not redundant.

### 6.1 Layer 1 — advisory intent (announce + check)

Before editing a shared file, the developer announces what it is about to do and
looks at who else is live, via the coordination MCP server:

```
coord.announce_intent(story, dev, file="flake.nix",
                      action="add edit-surface input + re-export")
others = coord.check_intents(file="flake.nix")    # live intents on this file
```

Intent is **advisory**: it gives visibility and lets a developer cooperate
*before* contending — reorder its work, do other ready stories first, or simply
know a collision is likely. Announcing *before* checking means a developer sees
its own intent alongside anyone who beat it, so "oldest live intent goes first"
is a cheap, fair ordering rule. Intent alone is **not** sufficient — two
developers can both check-clear in the same instant (TOCTOU). That is what
Layer 2 fixes.

### 6.2 Layer 2 — MCP file-lock (atomic, closes the race)

To actually edit, the developer must hold the file's lock:

```
if coord.acquire_file_lock(file="flake.nix", dev=me):   # atomic, §7.3
    try:
        edit flake.nix directly        # ordinary Edit/Write on the real file
    finally:
        coord.release_file_lock(file="flake.nix", dev=me)
else:
    # someone holds it — do other ready work, retry later (Layer 1 told us who)
```

`acquire_file_lock` is backed by the **same atomic SQLite primitive as
`claim_story`** — `INSERT INTO file_locks(file) ... ON CONFLICT DO NOTHING`,
success iff `changes()==1` (§7.3). Exactly one developer holds a given shared
file at a time; the rest get `false` and yield. This is a genuine mutex over the
*edit window*, not advisory — it eliminates the concurrent-clobber race between
cooperating developers. Locks are **short-held** (acquire → edit → release,
seconds) and **stealable on timeout**: a lock older than a threshold (crashed
holder) can be reclaimed, with the event logged. The lock guards *editing*, not
the whole story — a developer does its long work first, then takes the lock only
for the brief shared-file edit.

### 6.3 Layer 3 — repair loop (heals the residual)

Locks make *cooperating* developers safe. They do **not** constrain an agent
that never spoke to the server (the "another agent working right now" case) or a
lock-steal that raced a slow holder. So after editing — lock released — the
developer validates, and the existing fix-validate loop doubles as collision
detection:

- Run the relevant validation (`nix flake show`,
  `bash -n scripts/claude-with-servers`, `tests/integration.sh`).
- A failure that looks like a clobber (an input another `done` record says was
  added is now missing; a syntax break at the edit site) triggers a bounded
  **reconcile**: re-acquire the lock, re-read the file, re-apply this story's
  change, re-validate. Bounded to ~2 attempts.
- Conflicts are logged to `attempts/<story>.jsonl` + `run-log.jsonl` and
  recorded via `coord.report_conflict(...)` so the monitoring server (§7b) sees
  them live. If it can't self-heal, the story is marked `needs-human` and
  surfaced — never silently proceed on a broken shared file.

**The trade, stated honestly:** intent gives cooperation, the lock gives
correctness among participants, and repair gives resilience against
non-participants and edge races. We get a real mutex without an integrator node
or a fragment-merge algorithm — developers just edit the files, but only one at
a time, and validate after. This is the design owner's "cooperate and rely on
agent fix-it resilience" philosophy, hardened with a cheap atomic lock so the
common case is correct-by-construction rather than repaired-after-the-fact.

---

## 7. The coordination MCP server — *inside* (developer ↔ developer)

> **Two servers, two audiences.** Coordination splits into two MCP servers over
> the **same** SQLite DB:
> - **§7 — coordination server (inside):** the developers' nervous system.
>   Transactional, write-capable, clients are the N developer instances and the
>   `claude` subprocesses they spawn. Tight peer-to-peer contract.
> - **§7b — monitoring server (outside-in):** a read-mostly observability lens
>   for an *external* agent (you) or dashboard to watch the whole fleet. Wide,
>   safe, aggregate. Clients are observers, never developers.
>
> They are separate servers — not one with extra tools — so an observer
> physically cannot mutate coordination state, and developers carry no
> monitoring surface. The DB is the shared source of truth; each server is a
> different lens with different write rights (§7b.3).

Coordination is a **runner-internal MCP server** that the spec-kit runner spins
up alongside the run and points every spawned developer at (added to each
developer's `.mcp.json`). It is *not* a packaged toolbelt server — it is harness
infrastructure local to the runner. State lives in a single SQLite DB
(`specs/<feature>/.coord.db`, WAL mode), so coordination survives a supervisor
or developer crash and is queryable for the live dashboard.

### 7.1 Tool surface (the agent-facing API)

| Tool | Purpose | SQLite effect |
|---|---|---|
| `ready_stories(dev)` | stories whose `deps` all have a `done` row AND that are unclaimed | `SELECT` over `stories`/`claims` |
| `claim_story(story, dev)` → bool | atomically take a ready story; `false` if already taken | `INSERT INTO claims ... ON CONFLICT DO NOTHING`; success = `changes()==1` |
| `announce_intent(story, dev, touches[], action)` | Layer 1: forward-looking "about to touch these files" (§6.1) | `INSERT INTO intents` |
| `check_intents(file?)` | live intents (optionally filtered to a file) — what others are about to touch | `SELECT FROM intents WHERE status='live'` |
| `acquire_file_lock(file, dev)` → bool | Layer 2: atomically take the edit-lock on a shared file; `false` if held (§6.2) | `INSERT INTO file_locks ... ON CONFLICT DO NOTHING`; success = `changes()==1` |
| `release_file_lock(file, dev)` | release the edit-lock after the edit | `DELETE FROM file_locks WHERE file=? AND dev=?` |
| `publish_done(story, files_modified[], contracts[])` | finish a story; clears its live intent | `UPDATE intents SET status='done'`; `INSERT INTO done` |
| `mark_blocked(dev, blocked_on)` | record that a developer is waiting on a dep (observability) | `UPSERT developers` |
| `report_conflict(story, file, detail)` | a clobber was detected during reconcile (§6.3) | `INSERT INTO conflicts` |
| `propose_plan_change(kind, payload)` | propose a DAG mutation: split/add_story/add_dependency/flag_blocker (§5b.3) | `INSERT INTO proposals` (supervisor applies) |
| `share_finding(story, dev, topic, detail)` | publish a discovery useful to peers (§5b.3) | `INSERT INTO findings` |
| `read_findings(topic?)` | read peer discoveries before starting related work | `SELECT FROM findings` |
| `plan_status()` | full DAG + per-story state + downstream weights — for the dashboard/supervisor | `SELECT *` |

The implementing agent never sees SQL. It calls these as ordinary MCP tools.
The supervisor reads the same DB directly (it owns the process) for scheduling
and push-wake.

### 7.2 Schema (sketch)

```sql
CREATE TABLE stories (                 -- the parsed DAG, written once at plan load
  id TEXT PRIMARY KEY, phase TEXT, deps_json TEXT,
  touches_json TEXT, shared_json TEXT, produces_json TEXT, consumes_json TEXT
);
CREATE TABLE claims (                  -- atomic story ownership (§7.3)
  story TEXT PRIMARY KEY REFERENCES stories(id),   -- PK = the mutex
  dev TEXT NOT NULL, claimed_at INTEGER NOT NULL
);
CREATE TABLE intents (                 -- forward-looking edit announcements (§6.1)
  id INTEGER PRIMARY KEY, story TEXT, dev TEXT,
  touches_json TEXT, action TEXT, status TEXT,     -- 'live' | 'done'
  started_at INTEGER
);
CREATE TABLE done (                    -- completion record (mirrors completion-*.json)
  story TEXT PRIMARY KEY, dev TEXT,
  files_modified_json TEXT, contracts_json TEXT, finished_at INTEGER
);
CREATE TABLE file_locks (              -- short-held edit-lock on a shared file (§6.2)
  file TEXT PRIMARY KEY,               -- PK = the mutex; one holder per file
  dev TEXT NOT NULL, acquired_at INTEGER NOT NULL   -- acquired_at → timeout-steal
);
CREATE TABLE developers (id TEXT PRIMARY KEY, state TEXT, blocked_on TEXT);
CREATE TABLE conflicts (id INTEGER PRIMARY KEY, story TEXT, file TEXT, detail TEXT, at INTEGER);
CREATE TABLE control (                 -- operator control verbs, applied by supervisor (§7b.3)
  id INTEGER PRIMARY KEY, verb TEXT, arg TEXT, status TEXT, at INTEGER
);
CREATE TABLE proposals (               -- DAG mutations proposed by developers (§5b.3)
  id INTEGER PRIMARY KEY, dev TEXT, kind TEXT,        -- split|add_story|add_dependency|flag_blocker
  payload_json TEXT, status TEXT, at INTEGER          -- pending|applied|rejected
);
CREATE TABLE findings (                -- peer-shared discoveries (§5b.3); upgrade of learnings.md
  id INTEGER PRIMARY KEY, story TEXT, dev TEXT, topic TEXT, detail TEXT, at INTEGER
);
-- `stories` also carries a computed `weight` column (downstream critical-path
-- weight, §5b.1), recomputed by the supervisor as durations land / DAG mutates.
```

### 7.3 The atomic primitive (shared by claim + file-lock)

Two places need true mutual exclusion, and **both use the same one-line SQLite
idiom** — an `INSERT` against a PRIMARY KEY with `ON CONFLICT DO NOTHING`, where
success is `changes()==1`:

```sql
-- story ownership (no two developers run the same story)
INSERT INTO claims (story, dev, claimed_at) VALUES (?, ?, ?)
  ON CONFLICT(story) DO NOTHING;        -- claims.story is PK

-- shared-file edit-lock (no two developers edit flake.nix at once, §6.2)
INSERT INTO file_locks (file, dev, acquired_at) VALUES (?, ?, ?)
  ON CONFLICT(file) DO NOTHING;         -- file_locks.file is PK
```

Exactly one inserter wins; losers see `changes()==0` and yield. This is a real
mutex (atomic one-shot create), stronger than the file-based `O_CREAT|O_EXCL` of
the original draft because the read and the write happen in one transaction —
no read-then-act TOCTOU window. `claim_story` guards a story for its whole life;
`acquire_file_lock` guards only the brief shared-file edit window and is
released immediately after (with timeout-steal for a crashed holder, §6.2).

### 7.4 What stays as files (the durable/transient split)

Coordination moved to MCP+SQLite; **durable results stay as files**, unchanged:

- `claims/completion-<story>.json` — still written on completion (mirrors the
  `done` table) so the existing audit trail, dashboards, and human inspection
  keep working. The DB is the live coordination truth; the JSON is the durable
  record.
- `attempts/<story>.jsonl`, `run-log.jsonl`, `learnings.md` — unchanged.

(There are no `wire.fragment.json` build artifacts — the fragment/integrator
approach was dropped; shared files are edited directly under §6.)

Rule of thumb: **transient coordination signals → MCP/SQLite; permanent record
→ files.** Anything an external agent or a human needs to read after the run is
a file; anything only live developers consult mid-run is an MCP call.

---

## 7b. The monitoring MCP server — *outside-in* (observer agent → fleet)

A **second, separate MCP server** that lets an external agent (you, driving the
run) or a dashboard observe everything happening inside the parallel runner:
all developers, what each is working on, the dependency frontier, who is blocked
on whom, live intents, conflicts, and throughput. It is the "outside-in" lens;
the coordination server (§7) is the "inside" channel between developers.

### 7b.1 Why a separate server (not more tools on §7)

- **Different audience & trust.** §7's clients are trusted developers issuing
  transactional mutations (atomic claim, intent writes). §7b's client is an
  observer who must be able to look at *everything* but must **not** be able to
  call `claim_story` and corrupt scheduling. Separation makes that a hard
  boundary, not a convention.
- **Different shape.** §7 is narrow and write-heavy per call; §7b is wide,
  aggregate, read-mostly, and tolerant of being called constantly (a babysitter
  loop, a live TUI). Mixing them bloats the developers' tool list with read
  verbs they never use.
- **Same data, different lens.** Both servers open the **same** SQLite DB
  (`specs/<feature>/.coord.db`) plus the existing `run-log.jsonl` event stream.
  Monitoring adds no new source of truth — it is a read view over §7's tables
  (`stories`, `claims`, `intents`, `done`, `developers`, `conflicts`) joined
  with the event log.

### 7b.2 Tool surface (read-mostly)

| Tool | Returns |
|---|---|
| `fleet_status()` | one row per developer: id, state (working/blocked/done), current story, since-when |
| `dag_frontier()` | ready / running / blocked / done counts; the priority-ordered ready-set |
| `critical_path()` | the current longest chain, per-story downstream weights, estimated wall-clock remaining (§5b.1) |
| `story_detail(story)` | full state of one story: owner, deps (and which are satisfied), touches, weight, attempts, last log lines |
| `who_is_blocked()` | blocked developers and the exact story each waits on (the wait-for graph) |
| `live_intents()` | all `status='live'` intents — what is about to be written, by whom, to which files |
| `pending_proposals()` | developer-proposed DAG mutations awaiting / recently applied (§5b.3) — watch the plan reshape live |
| `recent_findings(topic?)` | peer-shared discoveries (§5b.3) |
| `recent_conflicts(limit)` | shared-file collisions detected + whether they self-healed (§6.3) |
| `throughput(window)` | stories/min, mean story duration, token spend per developer (from `run-log.jsonl`) |
| `tail_events(since)` | recent `run-log.jsonl` events (task_spawn/complete/conflict/proposal/…) for a live feed |

### 7b.3 Control verbs (v1, behind an opt-in flag)

In addition to the read surface, the monitoring server exposes a small set of
*control* verbs for an operator agent — `pause_developer(dev)`,
`resume_developer(dev)`, `set_target_n(k)`, `requeue_story(story)`,
`abort_story(story)`. These do **not** mutate coordination tables directly;
they write to a separate `control` table that the supervisor polls and applies
on its own loop (so control is mediated by the supervisor, never a raw write
into scheduling state). Control verbs are **gated behind an explicit
`--monitor-control` flag** at server start: a pure-observer agent started
without the flag gets the read surface only and physically cannot call them.
The read-only SQLite handle of §7b.4 is relaxed to read-write for the `control`
table only when the flag is set.

### 7b.4 Lifecycle & wiring

- The **supervisor** starts both servers at run start and tears them down at the
  end. The monitoring server is given a **read-only** SQLite handle
  (`mode=ro`) to the same `.coord.db`, enforcing read-only at the connection
  level — belt-and-suspenders with the tool surface.
- The monitoring server's address is **not** injected into developers'
  `--mcp-config` (they don't observe themselves). Instead it is surfaced to the
  *external* operator/agent — printed at run start and written to
  `specs/<feature>/.monitor-endpoint` so a babysitter agent or `/loop` can pick
  it up and call `fleet_status()` / `tail_events()` on an interval, and (when
  started with `--monitor-control`) issue control verbs (§7b.3).
- Because it's a normal MCP server over a file DB, it works whether or not the
  run is live: pointed at a finished run's `.coord.db` it becomes a post-mortem
  query tool.

---

## 7c. The developer's external toolset — proxied toolbelt servers

§7 and §7b are the runner's *internal* nervous system. They are not the only
MCP servers a developer talks to. A developer is a `claude` subprocess doing
real implementation work, so its tools come in **two layers**, both delivered
through the same `--mcp-config` injection (§10 resolved-3):

| Layer | Servers | Purpose | Trust |
|---|---|---|---|
| **Internal (harness)** | coordination server (§7) | claim/intent/lock/publish — keep N developers from clobbering each other | runner-local, transactional |
| **External (work)** | the toolbelt servers — `codebase`, `git-guard`, `web-browser`, `task-runner`, … | the actual *superpowers*: structure-aware reads, scoped git, cached web, allowlisted shell | each **fronted by nix-mcp-proxy** |

The external layer is the point of the whole stack. A developer doesn't `Read`
raw bytes and `Bash` arbitrary commands — it calls high-level toolbelt tools
that return pre-digested, policy-compliant results. Every one of those servers
sits behind nix-mcp-proxy.

### 7c.1 The stack spine

```
Supervisor (the new runner — one process)
  └── Developer  (a claude subprocess, §2)
        ├── coordination MCP server      (internal, §7 — claim/intent/lock)
        └── toolbelt MCP servers         (external, the work)
              └── each routed through → nix-mcp-proxy
                    └── → upstream MCP server (codebase / git / web / …)
```

This is the architecture a stack-aware planner must account for (§7c.4):
spec-kit generates `tasks.md` → the supervisor runs it as N developers →
each developer's work tools are proxied → the proxy enforces what each
developer may touch.

### 7c.2 Why the proxy is the safety complement to coordination

The coordination server gives **correctness among cooperating developers** —
the file-lock (§6.2) stops two developers writing `flake.nix` at the same
instant. It does **nothing** about a single developer doing something it
shouldn't: deleting outside its workstream, `git push --force`, fetching an
arbitrary URL, committing to `infra/` when it owns `src/`. That is exactly
what nix-mcp-proxy enforces — tool whitelists, path/field validation, branch
restrictions, audit logging — declared per the toolbelt's `proxy.config.nix`
and sealed at `nix build` time.

So the two layers are orthogonal and both required for N untrusted parallel
developers to be *safe*:

- **Coordination server** — developers don't clobber **each other**.
- **nix-mcp-proxy** — a developer doesn't clobber **the system**.

Neither subsumes the other. A run with N>1 needs both.

### 7c.3 Teaching a developer to use the proxy — the consumer skill

A developer talking through the proxy must read the narrowed contract first
(`proxy.describe`), prefer proxied tools over raw built-ins, and recover from
structured rejections (`validator_rejected`, `field_not_allowed`, …) instead
of retrying blindly. That behavioral contract lives in the
**`nix-mcp-proxy-consumer` skill** (shipped *from* nix-mcp-proxy, see its
`lib.consumerSkillsDir`; forwarded into the project by the toolbelt's
`claude-with-servers`).

**Delivery is the same problem as the review skill — and the same solution.**
Developer agents are spawned with the standing rule *"do NOT read ROUTER.md or
load any skills / do NOT use the Skill tool"* (`parallel_runner.py` ~L1898,
2479, 2680, 3111). So a skill file sitting in `skills/` never reaches
them. The runner already solves this for code review: it reads
`Path(skills_dir) / "code-review*" / "SKILL.md"`, strips the frontmatter, and
**inlines the body** into the agent prompt (~L2545, L2777). The
`nix-mcp-proxy-consumer` skill rides the **identical mechanism**: when a
developer's external toolset is proxied, the runner inlines that skill's body
into the developer prompt as an `## Operating behind the proxy` section.

Responsibility boundary (each layer owns its slice; the territory lives where
its consumer can reach it):

| Layer | Owns |
|---|---|
| **nix-mcp-proxy** | authors + ships the skill (source of truth for proxy behavior); exposes `lib.consumerSkillsDir` (stable read path) + `lib.installConsumerSkills` (devshell install hook) |
| **mcp-toolbelt** | fronts each server with `mkProxy`; forwards the skill into the project via `claude-with-servers` |
| **parallel_runner.py** | inlines the skill body into each proxied developer's prompt (mirrors the review-skill inline) |
| **spec-kit planner** | generates `tasks.md` aware that developers run proxied (§7c.4) |

The skill is **not** copied into this doc or into agent-framework — it
describes the *proxy's* contract (its error codes, its `proxy.describe` shape),
so it stays co-located with the proxy and is referenced, not duplicated. The
runner is a pure consumer of it.

### 7c.4 Stack-aware planning (spec-kit)

Only one persona needs the whole spine: the **spec-kit planning agent** that
writes `tasks.md`. When the project it is planning will run under this stack,
the plan must reflect it — tasks reference proxied tools and `proxy.describe`
rather than raw `Read`/`Bash`, and the plan includes the proxy-wiring +
skill-forwarding stories. This is delivered the spec-kit-native way: a
reference doc (sibling to `reference/code-review-graph.md`) loaded on demand by
`phases/plan.md` + `phases/tasks.md`, plus a `CLAUDE-STANZA` stamped into the
generated project so local sessions get a pointer. The planner is the only
consumer of the full picture; every other persona needs only its one slice
(table in §7c.3).

### 7c.5 Open question — per-developer proxy profiles

nix-mcp-proxy supports **per-agent profiles** (named tool/field/value subsets,
resolved per connection — its FR-056). The DAG already carries each story's
`touches` globs (§3). The open question: should each developer connect under a
**distinct proxy profile** scoped to its claimed workstream — e.g. a developer
that owns `servers/edit-surface/**` gets a `git-guard` profile that can only
commit under that path — turning the conflict-avoidance metadata into an
*enforced* boundary rather than an advisory one?

- **For:** defense in depth — the proxy would mechanically deny a cross-
  workstream write even if intent/lock (§6) were bypassed; the `touches`/`shared`
  data already exists to derive the profile.
- **Against:** profiles are resolved at connect time but work-stealing (§5)
  means a developer's claimed set grows *during* the run — a connect-time
  profile can't widen as it claims more stories without a reconnect. May fit a
  static per-developer scope (the union of a server's stories) better than a
  per-story one.

Out of scope for v1 (the coordination correctness layer ships first); recorded
here because the `touches` → profile mapping is the natural bridge between this
doc's DAG metadata and the proxy's existing isolation feature.

---

## 8. Worked example: the 7-server plan

- **Research level** (T005, T010, T014, T018, T022, T026, T030): 7 stories, no
  cross-deps, disjoint `touches` (each writes its own `servers/<name>/`).
  → width = 7, supervisor spins up N = min(7, cap) developers, all run flat-out.
- **Per-server chain**: within a server, Package `deps` Research, Test `deps`
  Package, Wire `deps` Test. Each developer walks its server's chain; no
  blocking between servers.
- **Wire steps** declare `shared: ["flake.nix", "scripts/claude-with-servers"]`.
  Each wire story edits those files directly, but only under the intent → lock →
  repair protocol (§6): announce intent, `acquire_file_lock("flake.nix")`, edit,
  release, validate. Whichever wire story reaches the lock first edits first;
  the others briefly yield and retry. No fragments, no integrator node.
- Because the lock serializes only the *edit window* (seconds), seven wire
  stories that each spend minutes on their own server still parallelize almost
  entirely — they queue only for the short moment they touch a shared file.

Result: 7-wide parallelism on the disjoint majority; the two shared files are
edited directly but mutually-exclusively via the MCP file-lock, with the repair
loop as backstop. No worktree, no integrator, no merge algorithm — just atomic
story-claim, atomic file-lock, and live intent visibility through the
coordination MCP server.

---

## 9. What this deliberately does NOT do

- **No fragments, no integrator story, no merge algorithm.** An earlier draft
  prevented shared-file collisions by having wire stories emit fragments that a
  single integrator merged. Dropped in favor of direct edits under the
  intent → lock → repair protocol (§6): simpler (no fragment schema, no merge
  code, no extra DAG node), and the short-held MCP file-lock gives the same
  correctness for cooperating developers.
- **No *long*-held lock on file contents.** The file-lock guards only the brief
  edit window (acquire → edit → release, seconds), not a whole story, and is
  stealable on timeout — so a crashed holder can't wedge the run. This is the
  narrow, cheap mutex the contended section actually needs; the repair loop
  covers anything outside it (lock-steal races, external agents).
- **No direct peer-to-peer agent messaging.** Developers do not message each
  other; they read/write shared state through the coordination MCP server. No
  developer depends on another being *awake* — intent and claims persist in
  SQLite, so a developer that comes back from a poll sees the current truth
  regardless of who is running.
- **No assumption the supervisor owns the whole tree.** The design tolerates
  external agents (and humans) editing concurrently: coordination-state
  correctness rests on SQLite atomicity, and shared *source* writes are
  validate-and-repair. An external agent that doesn't speak to the coordination
  server simply isn't visible in `check_intents` — the repair loop is the
  backstop for exactly that blind spot.

---

## 10. Open questions for implementation

### Resolved

1. **Developer unit — RESOLVED.** A developer is an **in-process instance of
   the old `parallel_runner.py`**, refactored into a `Developer` class; the
   supervisor holds a dict of N of them in one process (§2). Each developer
   still spawns many `claude` subprocesses per story (its existing mechanism).
   Coordination is MCP+SQLite so those subprocesses can also speak intent and
   so state is durable; in-memory is a cache of SQLite.
2. **Push-wake — RESOLVED (in-process).** Blocked developers `await` a
   supervisor-set asyncio event; the supervisor sets it on every `publish_done`.
   ~0 latency, no polling. (§4)
3. **Coordination server lifecycle — RESOLVED.** Supervisor starts the
   coordination MCP server before instantiating developers and tears it down
   after the DAG drains. `.coord.db` lives at `specs/<feature>/.coord.db` (WAL,
   gitignored). The server address is injected into each spawned `claude`'s
   config via the runner's **existing `--mcp-config` mechanism** (already used
   for `mcp-android` et al., `parallel_runner.py` ~L3557–3598) — no new wiring.

7. **Work distribution — RESOLVED.** Pure pull / work-stealing: no
   per-developer queues, every idle developer claims from the global ready-set,
   SQLite atomic claim arbitrates (§5). No reassignment logic.
8. **Monitoring scope — RESOLVED.** v1 ships **read + control**: the read
   surface (§7b.2) plus control verbs (§7b.3 — pause/resume/set-N/requeue/abort)
   gated behind a `--monitor-control` flag, mediated through a `control` table
   the supervisor applies.

9. **Shared-file protocol — RESOLVED.** Intent → lock → repair (§6): advisory
   `announce_intent`/`check_intents`, then atomic `acquire_file_lock` (same
   SQLite `ON CONFLICT` primitive as `claim_story`), then the validate-and-repair
   loop. No fragments, no integrator, no merge algorithm.
10. **Scheduling — RESOLVED.** Critical-path-first: ready-set ordered by
   downstream weight (DAG longest-path), durations estimated from
   `run-log.jsonl` history and refined as stories complete (§5b.1). Idle
   developer steals the highest-weight ready story (§5b.2).
11. **Developer communication — RESOLVED (richest tier).** Beyond mechanical
   coordination, developers (a) share discoveries via `share_finding`/
   `read_findings`, and (b) reshape the DAG via `propose_plan_change`
   (split/add_story/add_dependency/flag_blocker), applied by the supervisor
   under the in-flight rule (§5b.3).

### Still open

4. **Lock tuning.** The file-lock timeout-steal threshold (how long before a
   crashed holder's lock can be reclaimed) and the reconcile attempt cap — both
   are small constants to settle during implementation, not design forks.
6. **External-agent *announce* visibility.** The monitoring server (§7b) already
   gives an external agent full *read* visibility. Open: should an external
   agent also be able to *announce* intent / take a file-lock in §7 (so it
   participates in the lock protocol rather than only being repaired-around)?
   Out of scope for v1; the SQLite design doesn't preclude it.
12. **Per-developer proxy profiles.** Should each developer connect to the
   proxied toolbelt under a distinct nix-mcp-proxy profile scoped to its
   workstream `touches` (§3), making conflict-avoidance an *enforced* boundary,
   not advisory? Full discussion + the connect-time-vs-work-stealing tension in
   §7c.5. Out of scope for v1.
