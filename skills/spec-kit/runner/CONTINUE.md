# CONTINUE — resume the TS runner port

You are a build agent continuing the **TypeScript spec-kit parallel runner**
port. Work is resumable across context windows through three files in this dir.
Do this every time you start:

## 1. Read these, in order
1. **`MEMORY.md`** (this dir) — durable decisions, current milestone, where the
   last agent stopped and why, gotchas. This is the source of truth for "what is
   true right now."
2. **`TASKS.md`** (this dir) — the M0→M11 milestone checklist. Find the **first
   unchecked `- [ ]` task**; that is your next task.
3. **The design plan** — `/home/max/.claude/plans/groovy-stargazing-lemon.md`
   (approach, module layout, stories.md spec, milestones, verification) and its
   deep companion `/home/max/.claude/plans/groovy-stargazing-lemon-agent-afb84ce0e08f3d1e0.md`
   (full TS types, class signatures, control-flow pseudocode). Read the sections
   relevant to your current task — do not re-read everything.

   ⚠️ Plans live under `~/.claude/plans/` which is **not committed**. If those
   files are missing (fresh machine / new clone), the essential design is
   summarized in `MEMORY.md § Design summary` — rely on that.

## 2. Do exactly ONE unit of work, then exit

**A "unit of work" = one unchecked `- [ ]` task in `TASKS.md`.** Do that one
task, only that one, and then stop. Do not greedily chain tasks — bounded units
keep each context small, each handoff clean, and each step reviewable. The
*next* agent (or you, re-invoked) does the next unit.

- Implement the first unchecked task in `TASKS.md`.
- Honor the locked decisions in `MEMORY.md` — do not re-litigate them.
- Match the surrounding code's style. Keep modules small and single-purpose
  (the whole point of this port is to escape the 21k-line Python file).
- Source of truth for behavior parity: the Python runner at
  `../parallel_runner.py` (line refs are in the plan). Read the relevant
  function, port it, don't guess.

Exception: if the task is genuinely trivial AND the next task is a direct,
inseparable continuation (e.g. "add type" + "add the function using it"), you
may do both — but default to one, and never do more than fits comfortably in
one context with room to verify and record.

## 3. Verify (before checking the task off)
- Run the task's verification/demo (listed beside it in `TASKS.md`).
- `cd` into this `runner/` dir; use `nix develop` for tooling
  (`npm`, `tsc`, `vitest`). Tests use **real processes**, no integration mocks
  (project CLAUDE.md mandate).
- If verification fails and you can't fix it within this unit, leave the task
  unchecked, record the blocker in `MEMORY.md § Blockers`, and exit. Don't
  check off unverified work.

## 4. Record progress, then EXIT
This is the durable handoff — do it every time, even mid-milestone:
1. Check off the completed `- [ ]` → `- [x]` in `TASKS.md`.
2. Update `MEMORY.md`:
   - `## Current state` — overwrite with: current milestone, the exact next
     unchecked task, and the repo build status (green / broken + why).
   - `## Log` — append a dated one-liner of what you finished.
   - `## Gotchas` — append anything non-obvious a future agent needs.
   - `## Blockers` — add/clear as needed.
3. Leave the repo in a building state, or note clearly in `MEMORY.md` if not.
4. **Stop.** Your turn ends here. The single-unit contract is what makes this
   resumable — respect it.

### The runtime analogue (for when you implement the runner itself)
This same "process one unit and exit" contract is the runner's own execution
model, so build it in deliberately:
- **One story** is the runtime unit of scheduling: `Developer.runStory(story)`
  claims → Fable-plans → Sonnet-executes → verifies → publishes a completion
  claim → returns. A crash mid-story is recoverable because the claim/coord
  state is durable (SQLite + `claims/`).
- **Within a story, one executor spawn** is bounded by
  `EXECUTOR_STEP_CAP_PER_SPAWN = 4` steps OR `EXECUTOR_WALL_CAP_S = 600s`
  (whichever first); on cap it writes `handoff-spawn-N.md` (`Status: PARTIAL` +
  next-step + state-left-behind) and **exits**, and the next executor resumes
  from that handoff. This is the runtime mirror of this very document.
- Preserve those caps and the handoff schema during the port (M1/M5/M7).

## Boundaries
- This `runner/` package is the **new TS runner**. The Python
  `../parallel_runner.py` stays as the reference — **do not delete or edit it**.
- The existing sibling `../runner-ts/` is an unrelated "tabrunner" spec-kit test
  project; it is the **parity fixture**, not the runner. Don't build into it.
- After editing any `SKILL.md`, regenerate `ROUTER.md` via the repo-root
  `GENERATE-ROUTER.md` — never hand-edit `ROUTER.md`.
- Commit/push only when the human asks. If you do, branch off `main` first.
