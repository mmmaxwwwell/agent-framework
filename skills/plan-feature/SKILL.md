---
name: plan-feature
description: Turn an idea into the three-file funnel — <name>-plan.md (design + LOCKED decisions L1..Ln + end-to-end verification gate), <name>-TASKS.md (milestones of subagent-sized tasks with ship gates), <name>-megaprompt.md (paste-to-resume prompt). Interviews the owner with AskUserQuestion, writes incrementally, ends with one adversarial review. Plans only — never implements. Use when starting a feature/project or when the user says "plan", "spec", "design" a multi-session piece of work.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <name> [one-line goal]
---

# plan-feature

Produce three small files that let any fresh session execute the work without
re-deriving decisions. Token budget is a first-class constraint: the plan is
read by every implementer, so every line must earn its place.

## Files (default dir: the repo's existing `*-plan.md` location, else `docs/plans/`)

| File | Purpose | Size target |
|---|---|---|
| `<name>-plan.md` | Goal, non-goals, LOCKED decisions, design, verification gate, risks/open | ≤ 300 lines |
| `<name>-TASKS.md` | Milestones → tasks with ship gates; living checklist + rulings | ≤ 250 lines |
| `<name>-megaprompt.md` | Paste-to-resume prompt (written by `/handoff` format) | ≤ 100 lines |

## Steps

1. **Ground (cheap).** Read the repo `CLAUDE.md`, any existing decision log
   (`docs/decisions.md`, constitution, prior `*-plan.md`), and `git log --oneline -15`.
   Don't re-ask anything already decided there — cite it as an L-decision source.
2. **Scout what we already have.** Run `/scout <plan path>` (skills/scout) once the
   goal is clear. It matches the design against the registry of in-house tools and
   prior-art repos and appends USE/PORT decisions plus a `## Prior art` section.
   Do this before external research, because a sibling repo may already answer the question.
3. **Research only what changes a decision.** If outside knowledge is needed, spawn
   ONE background research subagent with an explicit question list and a
   "≤ 1200 words, cite sources, mark unverified" cap; it saves the full report to
   `docs/research/<date>-<topic>.md`. Keep only its conclusions in context.
4. **Interview.** `AskUserQuestion`, ≤ 4 questions per round, recommended option
   first and labelled "(Recommended)". Ask only questions whose answer changes
   what gets built. When the owner says "no idea", pick the sensible default,
   lock it as a default, and say so. Secure by default: if the owner weakens a
   safety property, state the concrete consequence once, then record their call.
5. **Write incrementally.** After every round, append decisions to `-plan.md` as
   `- **Ln — <decision>.** <why, one line>. (<date>, owner|default)`. Decisions
   are append-only; reversals add a new Ln that names the one it supersedes.
6. **Design section.** Components, data/control flow, interfaces between tasks
   (file paths, formats, protocols), and the **verification gate**: the exact
   command(s) proving the whole thing works end-to-end (e.g. a NixOS VM test,
   `nix flake check`, an e2e script). No gate = plan not done.
7. **TASKS.** Group into milestones; each milestone has a `Ship gate:` command
   and leaves the repo green. Each task:
   ```
   - [ ] T3.2 <imperative title> [model: sonnet|opus] [deps: T3.1] [files: path/a, path/b]
     Done: <1–3 verifiable bullets>  Verify: `<command>`  Decisions: L4, L9
   ```
   Size a task to one fresh subagent (~≤ 30 min, ≤ ~5 files). Tasks with disjoint
   `files:` and no deps may run in parallel — mark them `[P]`. Default model
   `sonnet`; `opus` only for design-heavy or debugging-heavy tasks.
   Legend line at top: `[ ] todo · [~] doing · [x] done · [!] blocked`.
8. **Megaprompt.** Write it in the `/handoff` format (goal, read-first list, locked
   decision one-liners, milestone map, next task, fail-safes).
9. **Adversarial review (one pass).** Spawn one subagent (model: opus) with only the
   three file paths: "Find gaps: tasks that don't trace to a decision or goal,
   decisions no task implements, missing verification, tasks too big, hidden
   ordering deps. ≤ 300 words, ranked." Fix what's real; ask the owner about
   anything that is a genuine decision. Do not loop more than once.
10. **Stop.** Summarize in ≤ 10 lines: file paths, milestone count, first task,
   open questions. Do not implement; that's `/execute-milestone`.

## Rules
- Never paste research reports or file dumps into the conversation — write them to
  disk and reference paths.
- Plans name real paths; verify with Glob/Grep before citing an existing file.
- Commit the three files only if the owner asks (or the repo's CLAUDE.md says to).
