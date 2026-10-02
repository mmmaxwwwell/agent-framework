---
name: execute-milestone
description: Execute one milestone of a <name>-TASKS.md (three-file funnel) with fresh-context subagents — one implementer per task (sonnet by default), orchestrator-run verification, one combined spec+quality review per task, at most 2 fix rounds, rulings logged instead of stopping to ask, per-task commits, ship gate at the end. Use when the user says "execute", "build", "implement milestone N", or "continue" on a project that has -plan.md/-TASKS.md.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion
argument-hint: <path-to-TASKS.md> [milestone id]
---

# execute-milestone

You are the orchestrator. Your context is the scarcest resource in the run:
you hold the plan's decision list, the task list, and short subagent reports —
never full diffs, file dumps, or test logs. Subagents do the reading and writing.

## 0. Load (once)
- Read `<name>-TASKS.md`, `<name>-plan.md` (decisions + design + gate), repo `CLAUDE.md`.
- Pick the milestone: argument, else first milestone with `[ ]`/`[~]` tasks.
- `git status --short` must be clean of unrelated changes; if not, ask before proceeding.
- Record `BASE=$(git rev-parse HEAD)`.
- Run `/scout <plan> <milestone>` (skills/scout). It's a no-op if the plan's
  `## Prior art` already has this milestone at the current registry rev. Feed its
  USE/PORT verdicts into each implementer's prompt as "Reuse: <path@rev> for <need>".

## 1. Schedule
Build the run order from `[deps:]`. Tasks marked `[P]` with disjoint `[files:]`
may be dispatched in the same message (parallel). Everything else is sequential.

## 2. Per task
**a. Dispatch implementer** (Agent tool, `model` from the task tag, default `sonnet`):
```
You are implementing ONE task in <repo>. Fresh context — everything you need is here.
Task: <task line + Done + Verify, verbatim>
Decisions you must honor: <only the L-lines the task cites, verbatim>
Interfaces/design excerpt: <only the plan lines this task touches; ≤ 40 lines>
Files you may touch: <files:>  (others only if unavoidable — say which and why)
Rules: write/extend tests first where a test seam exists; run `<Verify>` until green;
no scope creep; don't commit; don't edit TASKS/plan.
If a decision is ambiguous or wrong, choose the option most consistent with the plan,
continue, and report it as "Ruling: <what> because <why>".
Reply ≤ 150 words: STATUS (done|blocked), FILES changed, VERIFY result (last 5 lines),
RULINGS, CONCERNS.
```
**b. Verify yourself.** Run the task's `Verify` command; read only the tail
(`| tail -20`). Red → send the failure tail back to the same implementer
(SendMessage) as fix round 1.

**c. Review** (one subagent, `model: opus` for `[model: opus]` tasks, else `sonnet`):
"Review `git diff <task-start-sha>` against this task, its Done criteria, and these
decisions. Report only real problems: spec gaps, bugs, missing tests, decision
violations, scope creep. ≤ 200 words, ranked, each with file:line." For a run of
trivial tasks (docs, config one-liners), review them together once.

**d. Fix rounds ≤ 2 total** (verify + review combined). Still failing after 2 →
mark `[!]` with a one-line reason under the task, `git stash` or revert its changes,
continue with tasks that don't depend on it.

**e. Record + commit.** Tick `[x]`, append rulings under the task as
`  Ruling: <text>`, commit just that task's files: `<type>(<scope>): T<id> <title>`
(+ the repo's attribution trailer). One commit per task.

## 3. Ship gate
Run the milestone's `Ship gate:` (and the plan's verification gate if this is the
last milestone). Red → treat as one more task: dispatch a debugging subagent
(`opus`) with the failure tail and the milestone's diff stat; ≤ 2 rounds, then stop
and report.

## 4. Close
- Update `-TASKS.md` (milestone status line) and run the `/handoff` procedure to
  refresh `-megaprompt.md`.
- Report to the owner in ≤ 12 lines: tasks done/blocked, rulings worth their
  attention (the ones that touched a decision), gate result, next milestone.
- Never push, deploy, or touch remote machines unless the task explicitly says so
  and the owner has approved it in this session.

## Escalate to the owner (AskUserQuestion) only when
- a ruling would contradict a LOCKED decision,
- an action is destructive or outward-facing,
- the same blocker hits two tasks.
Otherwise rule, log, and keep going.
