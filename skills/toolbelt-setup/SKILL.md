---
name: toolbelt-setup
description: "Set up mcp-toolbelt in a project: add flake input, configure mkDevShell, generate .mcp.json, update CLAUDE.md and README. Run once on init or when updating the framework."
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
argument-hint: "[server-list]"
---

# Toolbelt Setup

You are setting up **mcp-toolbelt** in a project. This is a one-time (or on-update) operation that wires MCP servers into the project's nix flake and configures Claude Code to use them.

## User input

```text
$ARGUMENTS
```

If arguments list specific servers (e.g. "code-graph codebase git-guard"), only enable those. Otherwise enable the default set.

## Prerequisites check

1. Verify the project has a `flake.nix`. If not, ask the user — don't create one from scratch without confirmation.
2. Verify `nix` is available: `nix --version`
3. Check if mcp-toolbelt is already configured: look for `mcp-toolbelt` in `flake.nix` inputs.

## Available servers

| Server name | Flake package | What it replaces | Default |
|---|---|---|---|
| `code-graph` | `code-review-graph` | Deep codebase understanding (Read/Grep) | yes |
| `codebase` | `tree-sitter-mcp` | AST-aware code reading & search (Read/Glob/Grep) | yes |
| `edit-surface` | `semantic-edit-mcp` | Syntax-validated editing (Edit/Write) | yes |
| `git-guard` | `mcp-server-git` | Scoped git operations (Bash git) | yes |
| `task-runner` | `shell-mcp` | Allowlisted shell commands (Bash) | yes |
| `test-runner` | `mcp-test-runner` | Structured test results (Bash test) | yes |
| `web-browser` | `web-browser-sidecar` | Playwright + FTS5 cache (WebFetch) | no |
| `web-search` | `web-search` | DuckDuckGo search (WebSearch) | no |
| `sqlite-store` | `sqlite-memory-mcp` | Persistent FTS5 storage | no |

## Step 1 — Add mcp-toolbelt to flake.nix

Read the project's `flake.nix`. Add mcp-toolbelt as an input if not present:

```nix
inputs.mcp-toolbelt.url = "github:mmmaxwwwell/mcp-toolbelt";
```

If the flake already uses `flake-utils` or has a `follows` pattern for nixpkgs, add:
```nix
inputs.mcp-toolbelt.inputs.nixpkgs.follows = "nixpkgs";
```

## Step 2 — Configure devShell with mkDevShell

Replace or augment the project's `devShells.default` to use mcp-toolbelt's `mkDevShell`:

```nix
devShells.default = mcp-toolbelt.lib.${system}.mkDevShell {
  inherit pkgs;
  projectName = "<project-name>";  # derive from flake description or directory name
  servers = {
    codeGraph.enable = true;
    codebase.enable = true;
    editSurface.enable = true;
    gitGuard.enable = true;
    taskRunner.enable = true;
    testRunner.enable = true;
    # webBrowser.enable = false;   # opt-in: needs Chromium
    # webSearch.enable = false;    # opt-in
    # sqliteStore.enable = false;  # opt-in
  };
  # Pass through any existing packages the devshell had
  extraPackages = [ /* ... */ ];
};
```

**Important**: If the project already has a devShell with packages, preserve those in `extraPackages`. Read the existing devShell definition carefully before replacing it.

If the project doesn't use `flake-utils`, adapt the pattern to match the flake's style (e.g. `forAllSystems`, manual `system` binding, etc.).

## Step 3 — Update CLAUDE.md

Read the project's `CLAUDE.md` (create if absent). Add a section that loads the toolbelt behavioral skill:

```markdown
## MCP Toolbelt

This project uses mcp-toolbelt MCP servers. Read and follow the toolbelt skill at ~/git/agent-framework/skills/toolbelt/SKILL.md for tool preferences.

Launch with `nix develop -c claude-with-servers` to activate MCP servers.
```

If the project already has a toolbelt section, update it.

## Step 4 — Update README

Read the project's `README.md`. Add or update a development section:

```markdown
## Development

### Prerequisites

- [Nix](https://nixos.org/download/) with flakes enabled
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

### Getting started

```bash
nix develop -c claude-with-servers
```

This enters the dev shell with all MCP servers configured and launches Claude Code with enhanced tooling.
```

Keep it minimal — don't rewrite the whole README, just add the dev setup block if missing.

## Step 5 — Lock and verify

```bash
nix flake lock --update-input mcp-toolbelt
nix flake check
```

If `flake check` fails, read the error and fix. Common issues:
- Missing `follows` declaration
- `mkDevShell` not yet exported by mcp-toolbelt (see Step 6)
- Typo in server config attribute names

## Step 6 — Smoke test

Run a quick verification:

```bash
nix develop -c bash -c 'which claude-with-servers && which code-review-graph && echo "OK"'
```

Verify the key server binaries are on PATH. Report which servers are available and which aren't.

## Step 7 — Report

Tell the user:
- Which servers were enabled
- What files were modified (`flake.nix`, `CLAUDE.md`, `README.md`)
- How to launch: `nix develop -c claude-with-servers`
- If any servers failed the smoke test

## On update

When re-running this skill on an already-configured project:
1. Check current mcp-toolbelt input version vs latest
2. Run `nix flake lock --update-input mcp-toolbelt`
3. Re-verify with smoke test
4. Report what changed
