<!--
This is a template stanza meant to be appended to the project's CLAUDE.md
during the spec-kit install phase.  Every Claude Code agent spawned in the
project (implementation, validation, review, fix) will auto-read CLAUDE.md,
so this is how spec-kit delivers graph guidance to all agents without
touching parallel_runner.py's prompt builders.

Copy everything between the `---BEGIN-STANZA---` and `---END-STANZA---`
markers into the project's CLAUDE.md.  Do not include the markers or this
comment block.
-->

---BEGIN-STANZA---

## code-review-graph — always use the knowledge graph

This project has `code-review-graph` wired into its Nix devshell (pinned to
v2.3.2 via the spec-kit skill's flake). A watcher keeps the graph fresh as
files change; the spec-kit runner additionally runs `code-review-graph
update` at phase boundaries. The graph is **always current** — trust it.

**Before writing or editing code, consult the graph:**

```bash
code-review-graph status                             # sanity check — confirms graph is live
code-review-graph detect-changes --since <base_sha>  # risk-scored impact of a diff
code-review-graph visualize --format svg -o /tmp/g.svg
# 28 MCP tools are also available via `code-review-graph serve` (stdio).
```

**Rules of engagement:**

1. **Query before you create.** Before adding a new function, module, or
   API route, ask the graph whether something similar already exists.
   Duplicates are the #1 source of rot in long-lived spec-kit projects.
2. **Name real modules, not invented ones.** When writing plans, specs, or
   commit messages, reference paths/symbols that the graph confirms exist.
   If the graph doesn't know about it, it probably doesn't exist yet.
3. **Use `detect-changes` for review.** When reviewing a diff (your own or
   someone else's), start from `detect-changes --since <base>`. It tells
   you the blast radius, not just the lines changed.
4. **If the graph says one thing and the code says another**, trust the
   code — but file a note (in `learnings.md` or a commit message) so the
   discrepancy gets investigated. Graph staleness should be rare given
   the watcher + phase-boundary updates; a persistent mismatch is a bug.
5. **Never bypass the graph for "speed".** It's fast — `update` is
   sub-second for incremental changes, and queries are near-instant.
   Skipping it to save time trades minutes now for hours of duplicated
   work later.

**State directory**: `.code-review-graph/` (git-ignored). Contains the
SQLite graph db, watcher PID, and logs. `crg-stop` shell function kills
the watcher/MCP if you need to reset.

**Full reference**: `.claude/skills/spec-kit/reference/code-review-graph.md`
(in the agent-framework checkout). Read it if you need to dig into MCP
tools, custom exclude dirs, CI integration, or schema upgrades.

---END-STANZA---
