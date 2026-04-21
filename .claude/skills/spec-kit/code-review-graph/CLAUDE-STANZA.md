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
v2.3.2 via the spec-kit skill's flake). On every `nix develop`, the hook:
(1) merges `code-review-graph` into `.mcp.json` — MCP server on stdio;
(2) installs upstream Claude Code skills into `.claude/skills/`;
(3) registers a `PostToolUse` hook that runs `update` after every Edit/Write/Bash;
(4) starts a filesystem watcher so the graph stays fresh between Claude turns;
(5) the spec-kit runner additionally runs `code-review-graph update` at phase boundaries.

The graph is **always current** — trust it.

### Preferred workflow: MCP tools (token-efficient)

When MCP is available (Claude Code desktop/CLI with this `.mcp.json`), **always
start a graph-related task with `get_minimal_context_tool(task="…")`**. It
returns ~100 tokens with risk, communities, flows, and suggested next tools.

```text
get_minimal_context_tool(task="review diff")        # ALWAYS first — ~100 tokens
detect_changes_tool(detail_level="minimal")          # risk-scored impact
get_review_context_tool(base="main")                 # blast radius + source snippets
get_impact_radius_tool(base="main")                  # for PR-sized reviews
query_graph_tool(pattern="callers_of", target="foo") # symbol-specific walks
semantic_search_nodes_tool(query="rate limiter")     # find things by meaning
get_docs_section_tool(section_name="review-delta")   # fetch exact doc section
```

Full tool catalog (24 tools + 5 prompts): call
`get_docs_section_tool(section_name="commands")` — the upstream reference is
specifically designed for lazy section-fetch so you never load the whole doc.

### Upstream-provided skills (auto-installed in `.claude/skills/`)

| Skill | When to invoke |
|-------|----------------|
| `review-changes` | Review a diff with graph-backed blast radius analysis |
| `explore-codebase` | Navigate an unfamiliar area by graph topology |
| `refactor-safely` | Plan a refactor by walking impacted callers first |
| `debug-issue` | Trace a bug via the graph's dependency/flow edges |

### CLI fallback (when MCP is unavailable)

```bash
code-review-graph status                             # sanity check
code-review-graph detect-changes --since <base_sha>  # risk-scored diff impact
code-review-graph visualize --format svg -o /tmp/g.svg
```

### Rules of engagement

1. **Always call `get_minimal_context_tool` first.** It decides which subsequent
   tool to use and scopes everything to ≤800 tokens. Skipping it wastes context.
2. **Use `detail_level="minimal"`** on all subsequent calls unless you
   specifically need more detail. The tools default to verbose; be explicit.
3. **Query before you create.** Before adding a new function, module, or
   API route, use `semantic_search_nodes_tool` or `query_graph_tool` to check
   whether something similar exists. Duplicates are the #1 source of rot.
4. **Name real modules, not invented ones.** When writing plans, specs, or
   commit messages, reference paths/symbols that the graph confirms exist.
   If the graph doesn't know about it, it probably doesn't exist yet.
5. **Start reviews with `detect_changes_tool` / `get_review_context_tool`**,
   not a raw `git diff`. You get the blast radius, risk scores, and source
   snippets for the changed code all at once.
6. **If the graph says one thing and the code says another**, trust the
   code — but log a note (in `learnings.md` or a commit message) so the
   discrepancy gets investigated. Persistent mismatches indicate a bug.
7. **Never bypass the graph for "speed".** MCP queries are near-instant,
   `update` is sub-second. Skipping trades minutes now for hours later.

### State and troubleshooting

- **State directory**: `.code-review-graph/` (git-ignored). Contains the
  SQLite graph db (`graph.db`), watcher PID, install marker, and logs.
- **Reset**: `crg-stop` shell function kills the watcher/MCP. Delete
  `.code-review-graph/graph.db` to force a full rebuild.
- **Schema upgrade**: bumping the pinned version in the spec-kit flake
  clears `installed-v*` markers so the install hook re-runs on next entry.
- **DB lock**: SQLite WAL mode auto-recovers; only one build at a time.
- **Stale symbols**: if incremental update misses a rename,
  `code-review-graph build` forces a full rebuild (takes minutes).

**Full reference**: `.claude/skills/spec-kit/reference/code-review-graph.md`
(in the agent-framework checkout). Read it for MCP tool schemas, custom
exclude dirs, CI integration, and upgrade procedures.

---END-STANZA---
