---
name: handoff
description: Regenerate a project's <name>-megaprompt.md — the self-contained paste-into-a-fresh-session resume prompt of the three-file funnel — from the current -plan.md, -TASKS.md and git state. Use at the end of a session, after a milestone, or when the user says "handoff", "write a megaprompt", "save state for next session".
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
argument-hint: [path-to-plan-or-TASKS.md]
---

# handoff

A megaprompt is a **stable hook**, not a snapshot: it points at the plan and TASKS
for detail and carries only what a fresh session needs in its first minute.

## Gather (cheap)
- Locate `<name>-plan.md` / `-TASKS.md` (argument, else most recently modified pair).
- `git log --oneline -10`, `git status --short`.
- From TASKS: next `[ ]` task(s), any `[~]`/`[!]` with their reasons, recent rulings.

## Write `<name>-megaprompt.md` (≤ 100 lines), exactly these sections
```
# <name> — paste-to-resume megaprompt
Paste everything below the line into a fresh Claude Code session in <repo path>.
---
I am continuing **<name>**. <one-line goal>
**Before each milestone:** `/scout <plan path> <milestone>` (reuse in-house tools and prior art; see the plan's `## Prior art`).
**Read first (in order):** 1. <plan path> — design + LOCKED L1..Ln  2. <TASKS path> — grep `[~]`/`[ ]`/`[!]`  3. <other must-read, ≤ 3>
**Locked decisions (one line each; plan has rationale):** - L1 … - Ln …
**Milestones:** M1 <name> — <done|in progress|todo>; ship gate `<cmd>` …
**State:** last commit <sha subject>; in progress: …; blocked: … (reason)
**Gotchas learned:** <≤ 5 non-obvious facts from rulings/sessions, each one line>
**Fail-safes:** <what never to do / which way to lean when ambiguous>
**Next:** run `/execute-milestone <TASKS path> <Mx>` — or, if the skill isn't available,
execute the next task per TASKS. Confirm you've read the docs and print the next task.
```
- Locked decision lines are copied, not paraphrased; drop none.
- Gotchas come from rulings and session discoveries, not from things already in the plan.
- Never include secrets, tokens, or transcript excerpts.

## Finish
Show the diff stat of the megaprompt. Commit only if asked or if the repo's
CLAUDE.md says handoff docs are committed.
