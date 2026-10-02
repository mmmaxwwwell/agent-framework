---
name: scout
description: Find what we already have before building it. Covers in-house MCP servers, skills, libraries and sibling repos that already solved part of the problem. Matches them to a project's needs and records the USE/PORT/LEARN verdicts in the plan. Backed by a durable registry of everything in ~/git that is refreshed incrementally. Run at plan time (plan-feature step 2), at the start of every milestone (execute-milestone step 0), or when the user says "scout", "what do we already have for X", or "integrate our tools".
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion
argument-hint: <path-to-plan.md | free-text need> [milestone id]
---

# scout

The owner keeps building tools and solving pieces of problems in sibling repos.
Agents in a new project don't know those exist, so they rebuild them.
`scout` closes that gap cheaply:
- A **registry** is the cross-project memory: one row per repo, tool or skill.
- **Matching** happens against a project's needs.
- **Verdicts** are written into the project's own plan, so later sessions inherit them.

## Registry
- **Path:** `$SCOUT_REGISTRY`, else `~/git/agent-framework/registry/inventory.md`. It is a git-tracked file. Edit it in place.
- **Row format** (one line, no wrapping):
  `| name | kind | path | rev | what (≤ 15 words) | use-when tags | gaps/notes |`
  - **kind:** `mcp` · `skill` · `lib` · `app` · `nixmod` · `template` · `prior-art` · `infra`
    - `mcp` means the repo **provides** an MCP server. A `.mcp.json` only means it *uses* MCP: tag it `uses-mcp`.
    - `nixmod` means it provides NixOS or home-manager modules.
  - **tags:** lowercase capability words that a need would grep for, e.g. `android, kotlin, keystore, tailscale, mtls, e2e, fdroid`.
- **Ignored section:** repos with nothing reusable for software work (models, scratch, forks of upstreams we don't modify), recorded as `name@rev`. They are skipped until their rev changes.
- **Scanned roots:** `~/git/*`, `~/git/*/.claude/skills/*`, `~/.claude/skills/*`, `~/git/agent-framework/skills/*`.
- **Size cap:** keep it ≤ 250 rows. Git worktrees (`.git` is a file) are skipped by the script; mention notable ones in the parent row's notes.

## Modes
- **plan** (argument is a plan path, no milestone): match the whole design.
- **milestone** (plan path + milestone id): match only that milestone's tasks. Skip the run if the plan's `## Prior art` section already has a `scout <milestone>` line with the same registry rev.
- **ad hoc** (free text): answer "what do we have for X" from the registry. Write nothing to any project.

## 1. Refresh (incremental, cheap)
1. Run `bash <this skill dir>/scout-stale.sh [registry]`. It prints `NEW`, `CHANGED` and `GONE` names by comparing each root's `git rev-parse --short HEAD` with the registry rev.
2. Nothing stale: continue to step 2.
3. **Skill rows** need no agent: `scout-stale.sh | bash <this skill dir>/scout-skill-rows.sh` prints them from `SKILL.md` frontmatter. Optionally add capability words to their tags.
4. **Repo rows:** spawn subagents (`model: sonnet`, ≤ 20 names each, in parallel). Haiku was tried on 2026-09-30 and invented descriptions from repo names, e.g. a dog-belt repo became "Android Kotlin dev MCP". Prompt:
   > For each path, read only README / CLAUDE.md / flake.nix description and outputs / top-level `ls` / MCP tool list (≤ 80 lines per repo; read-only). Return registry rows in the exact format, or `- name@rev — IGNORE: reason`. Describe only what the files say; if the README is empty, say so in notes instead of guessing. No prose.
5. Apply the rows. Delete `GONE` rows. Re-run the script, and it must print nothing. Commit only if the owner asks.

## 2. Needs
From the plan (or milestone tasks), list 5–20 needs as short capability phrases, e.g.:
- `android ui automation on a physical device`
- `kanidm oidc public client`
- `f-droid repo hosting`
- `nix-built android apk`
- `keystore-backed secret storage`

Include **process** needs too (testing harnesses, review, deploy, docs lookup), not just product features.

## 3. Match
1. Grep the registry `what`/`tags` columns for each need (synonyms too). Shortlist ≤ 8 candidates.
2. Spawn **one** subagent (`model: sonnet`) with the needs, the shortlisted rows and the plan's locked-decision one-liners. Prompt:
   > For each candidate, read just enough of the repo to decide. Return a table: `candidate | need | verdict (USE / PORT / LEARN / SKIP) | evidence (path:line or file) | cost (S/M/L) | conflicts (Ln or none)`. Then ≤ 5 one-line lessons from prior art. ≤ 400 words.
   - **USE:** depend on it as-is: flake input, MCP server, skill.
   - **PORT:** copy or adapt code; cite the source path@rev in the commit.
   - **LEARN:** read it for decisions and pitfalls only.

## 4. Record (into the project, not chat)
- **USE/PORT that change what gets built:** append L-decisions, e.g. `- **Ln — Use <name> for <need>.** <why>. (<date>, scout: <path>@<rev>)`.
- **A verdict that conflicts with a locked decision:** never supersede it silently. Ask the owner (AskUserQuestion, recommended option first), then record their call.
- **LEARN and SKIP:** a `## Prior art` section in the plan, ≤ 15 lines: `- <name>@<rev> (<verdict>) — <lesson or why skipped>`. End it with `scout <mode/milestone> — registry <git rev of the registry file>`.
- **TASKS:** add wiring tasks or edit existing ones for USE/PORT (files, deps, Done/Verify). Keep tasks subagent-sized.
- **Gaps in our own tools** ("tool X almost fits but lacks Y"): add to that row's `gaps/notes` column. Mention it to the owner as optional upstream work. Don't edit other repos without asking.
- **Megaprompt:** make sure it contains `Before each milestone: /scout <plan path> <milestone>`.

## 5. Report (≤ 8 lines)
- Counts of USE/PORT/LEARN.
- New L-decisions.
- Tasks added or changed.
- Gaps logged.
- Registry rows refreshed.

## Rules
- The registry is the only thing read in bulk. Never paste READMEs or file dumps into the orchestrator context.
- Prefer USE over PORT over building something new. A candidate that violates a locked decision or a safety property loses, and gets recorded with the reason.
- Prior art is evidence, not authority. A newer plan decision wins, but the plan should say why it differs when prior art took the other path.
- Abandoned prior art (old, unfinished) is still LEARN material. Read its last commits for why it stopped.
