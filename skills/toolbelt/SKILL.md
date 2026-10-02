---
name: toolbelt
description: "Behavioral skill for agents running with mcp-toolbelt MCP servers. Tells the agent which MCP tools to prefer over Claude Code built-ins. Auto-loaded via CLAUDE.md after toolbelt-setup runs."
user-invocable: false
allowed-tools: Read, Bash, Glob, Grep
---

# MCP Toolbelt — Tool Preferences

You are running with **mcp-toolbelt** MCP servers. These replace Claude Code's built-in tools with structured, policy-compliant alternatives. **Always prefer the MCP tool over the built-in** when one is available.

## Tool replacement map

Check which MCP servers are active by reading `.mcp.json` (or `.mcp-toolbelt/mcp.json`) in the project root. Only prefer MCP tools for servers that are actually configured.

| Instead of | Use MCP tool | Why |
|---|---|---|
| `Read`, `Glob`, `Grep` | **tree-sitter-mcp** (`search_symbols`, `find_references`, `get_outline`) | AST-enriched, symbol-aware, instant. Fall back to built-ins for non-code files (configs, docs, images). |
| `Edit`, `Write` (source code) | **semantic-edit-mcp** (`edit_function`, `rename_symbol`) | Syntax-validated, formatter-integrated. Fall back to built-in `Edit` for non-code files or if the language isn't supported. |
| `Bash` (builds, tests, lint) | **shell-mcp** (`run_command`) | Scoped to allowlisted commands. Use for `npm test`, `cargo build`, etc. |
| `Bash` (git commands) | **mcp-server-git** (`git_status`, `git_diff`, `git_commit`) | Scoped repos/branches, destructive ops blocked, audit logged. |
| `Bash` (test suites) | **mcp-test-runner** (`run_tests`) | Structured pass/fail/skip results instead of raw stdout. |
| `WebFetch` | **web-browser** (`fetch_url`, `search_cached`) | Playwright + Readability extraction, FTS5 cache across sessions. |
| `WebSearch` | **web-search** (`search`) | DuckDuckGo-backed, no API key. |

### Code knowledge graph

If **code-review-graph** is configured:

1. **Always start with** `get_minimal_context_tool(task="...")` — ~100 tokens, scopes everything.
2. Use `detect_changes_tool` / `get_review_context_tool` instead of `git diff` for reviews.
3. Use `semantic_search_nodes_tool` / `query_graph_tool` before creating new code — check for existing implementations.
4. Use `detail_level="minimal"` on all graph calls unless you specifically need more.

### Persistent storage

If **sqlite-memory-mcp** is configured, use it for cross-session notes and findings instead of writing to markdown files.

## When to fall back to built-ins

- **Non-code files** (markdown, JSON, YAML, images, configs): use built-in `Read`/`Edit`/`Write`
- **Unsupported language**: if semantic-edit-mcp rejects an edit, fall back to built-in `Edit`
- **Ad-hoc shell**: if you need a command not in the allowlist and it's safe, note it — the user may need to add it to `.shell-mcp.toml`
- **Agent tool**: always use built-in `Agent` for sub-agent orchestration
- **AskUserQuestion**: always use built-in

## Health check

If MCP tools return errors or are unresponsive, tell the user. Suggest:
```
nix develop -c claude-with-servers --check
```
