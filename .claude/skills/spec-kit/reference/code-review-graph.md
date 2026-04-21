# code-review-graph — first-class spec-kit dependency

**code-review-graph** (`pip install code-review-graph`, pinned to v2.3.2 in
spec-kit) builds a persistent tree-sitter knowledge graph of the project and
exposes it via both a CLI and an MCP server. Spec-kit treats it with the same
weight as Stripe or a platform target: the graph is set up at project start,
kept fresh automatically, and consulted by **every phase** of the SDD workflow.

This doc is loaded on demand by phase files that need the graph (interview,
plan, tasks, implement, review). It is the single source of truth for how
spec-kit integrates the graph.

## Why first-class

Long-running SDD projects quickly outgrow a single agent's context window.
`git grep` and `rg` return lines but not *relationships* — they can't tell you
"what calls this function", "what depends on this module", or "what imports
from here". The graph answers those questions token-efficiently, and keeps
answering as the project grows.

Concrete wins:

- **Interview phase**: detect existing patterns so the spec doesn't duplicate
  or contradict what's already there.
- **Plan phase**: surface the actual module topology so the plan references
  real files, not invented ones.
- **Tasks phase**: flag cross-task file overlap (parallel-safety) by asking
  the graph who else touches a given symbol.
- **Implement phase**: agents query the graph to discover call sites, usages,
  and related tests before writing code — reducing "scaffold a new thing
  that already exists" bugs.
- **Review phase**: `detect-changes` produces risk-scored impact analysis of
  the phase diff; the review agent starts from that instead of a blank diff.
- **Continuously**: incremental `update` after every commit, plus a `watch`
  process during `nix develop`, so the graph is never stale.

## Nix integration (source of truth)

The derivation lives inside this skill at
`.claude/skills/spec-kit/code-review-graph/flake.nix`. Consuming projects add
it as a flake input and pull both the binary and a shellHook helper.

### In the consuming project's `flake.nix`

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    code-review-graph.url = "path:/home/max/git/agent-framework/.claude/skills/spec-kit/code-review-graph";
    # or, once published:
    # code-review-graph.url = "github:mmmaxwwwell/agent-framework?dir=.claude/skills/spec-kit/code-review-graph";
  };

  outputs = { self, nixpkgs, code-review-graph, ... }: let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
    crg = code-review-graph.packages.${system}.code-review-graph;
    crgHook = code-review-graph.lib.${system}.mkShellHook {
      projectName = "myproject";
      watch = true;       # keep graph fresh as files change
      serveMcp = false;   # set true if you want an MCP server auto-started
    };
  in {
    devShells.${system}.default = pkgs.mkShell {
      packages = [ crg /* + your other tools */ ];
      shellHook = crgHook + ''
        # your own shellHook content
      '';
    };
  };
}
```

### `mkShellHook` options

| Option | Default | Effect |
|--------|---------|--------|
| `projectName` | `"project"` | Label for logs; sets `$CODE_REVIEW_GRAPH_PROJECT` |
| `buildOnEnter` | `true` | Run `code-review-graph update` in background on shell entry |
| `watch` | `true` | Start a watcher (`code-review-graph watch`) with PID-file idempotency |
| `serveMcp` | `false` | Start an MCP server (`code-review-graph serve`) as a long-running background process. **Usually leave `false`** — Claude Code starts the MCP server on demand via `.mcp.json` (stdio), which is more reliable than a dangling daemon |
| `autoInstall` | `true` | Run `code-review-graph install --repo $PWD --platform claude-code --no-instructions -y` once per tool version. Merges the MCP server into `.mcp.json` (preserving other entries), drops upstream skills into `.claude/skills/`, installs `PostToolUse` + `SessionStart` hooks into `.claude/settings.json`, and a git pre-commit hook. Gated by `.code-review-graph/installed-v<version>` marker — bumping the pinned version re-triggers. Idempotent. Pass `autoInstall = false` if you manage `.mcp.json` / `.claude/settings.json` from another source and want the skill to stay hands-off |
| `stateDir` | `".code-review-graph"` | Where the SQLite graph db + logs + PID files live |
| `excludeDirs` | `[node_modules .direnv result dist .venv __pycache__ build .dart_tool]` | Dirs ignored by build/update/watch |

### What `autoInstall` does (and why `--no-instructions`)

The upstream `code-review-graph install` command wants to append its own
stanza to `CLAUDE.md`. Spec-kit manages that stanza itself (from
`code-review-graph/CLAUDE-STANZA.md`) because the spec-kit version is
tuned for runner-driven workflows (MCP-first, token-budget rules, runner
update-at-phase-boundary context). We pass `--no-instructions` so the
upstream doesn't duplicate or conflict with the spec-kit stanza.

Everything else the installer does is kept: MCP server registration,
skill file generation (`.claude/skills/{review-changes,explore-codebase,
refactor-safely,debug-issue}.md`), PostToolUse + SessionStart hook
registration in `.claude/settings.json`, and the git pre-commit hook.

A `crg-stop` shell function is defined automatically — it kills the watcher
and MCP server and clears PID files.

## Build-time expectations

| Repo size | First `build` | `update` (incremental) | `watch` idle cost |
|-----------|---------------|------------------------|-------------------|
| ~1k files | 5–30 seconds | sub-second | ≈0 |
| ~10k files | 1–5 minutes | sub-second | ≈0 |
| ~50k files (large monorepo) | 5–15 minutes | 1–5 seconds | negligible |

**First build is async** (`mkShellHook` backgrounds it into `build.log`). The
shell returns immediately; agents that need the graph should check for
`$CODE_REVIEW_GRAPH_STATE_DIR/graph.db` and wait/poll if absent.

## CLI cheat-sheet

```bash
code-review-graph build [--exclude DIR]...    # one-time initial parse
code-review-graph update [--exclude DIR]...   # incremental refresh
code-review-graph watch  [--exclude DIR]...   # long-running watcher
code-review-graph detect-changes              # risk-scored diff impact (HEAD vs prev)
code-review-graph visualize --format svg -o graph.svg
code-review-graph wiki > docs/ARCHITECTURE.md # generate markdown from graph
code-review-graph status                      # graph stats (node/edge counts)
code-review-graph serve [--tools TOOL,...]    # MCP server over stdio
```

The MCP server exposes 28 tools; see `code-review-graph serve --help` and
https://github.com/tirth8205/code-review-graph/blob/v2.3.2/docs/INDEX.md.

## Phase integration (what each phase does)

### Phase 0 (install) — MANDATORY

Add the skill's flake as an input. Wire `mkShellHook` into the project's
devShell so the watcher starts automatically. Baseline the first build.

### Phase 2 (specify / interview)

Before drafting the spec, the interview phase should run
`code-review-graph status` to confirm the graph exists, and optionally
`code-review-graph wiki` piped into `specs/<feature>/existing-architecture.md`
so the user can point to real modules when answering questions.

### Phase 5 (plan)

The plan phase queries the graph to:
- List existing top-level modules (→ "where does this new code live?")
- Identify high-fan-in nodes (→ "which interfaces are load-bearing?")
- Surface orphan/isolated modules (→ "what's safe to refactor?")

### Phase 6 (tasks)

When generating parallel tasks, the graph is consulted to detect file-overlap
between tasks. Two tasks that both edit a high-fan-in node are marked serial
even if the task author didn't flag a dependency.

### Phase 7 (implement)

Every implementation agent receives an "explore before you code" instruction
in its prompt:

> Before editing, run `code-review-graph detect-changes` to see the current
> impact graph of your phase's files. Before adding a new function, ask the
> graph if a similar symbol exists (`code-review-graph query_graph_tool
> --symbol <name>`). Prefer extending existing nodes over creating parallel
> implementations.

### Review phase (per-phase, runner-driven)

The review agent gets a pre-computed `detect-changes` report scoped to the
phase diff. This replaces the raw `git diff` as the starting point: the
agent sees not just the lines changed, but the blast radius in the graph.

## Runner integration (parallel_runner.py)

The runner treats the graph as infrastructure alongside stripe-listen and
test-logs. Specifically:

1. **Startup check**: if the project's flake references
   `code-review-graph`, the runner asserts
   `$CODE_REVIEW_GRAPH_STATE_DIR/graph.db` exists. If not, it runs a
   foreground `code-review-graph build` before dispatching any agent.
2. **Per-phase refresh**: after each phase's commits land, the runner runs
   `code-review-graph update` so subsequent agents see the latest graph.
3. **Prompt injection**: every agent prompt (implement, validate, review)
   includes a short stanza with the graph CLI cheat-sheet and the path to
   the MCP server's socket (if running).
4. **Review augmentation**: the review prompt builder invokes
   `code-review-graph detect-changes --since <base_sha>` and splices the
   JSON into the prompt so the agent starts with the impact analysis.

## Continuous refresh — who owns what

| Event | Refresh mechanism | Owner |
|-------|-------------------|-------|
| File edit during dev | `watch` picks it up live | shellHook |
| Task commit | runner runs `update` after commit | parallel_runner |
| Phase complete | runner runs `update` before review | parallel_runner |
| Branch switch / pull | developer runs `code-review-graph update` or re-enters devshell | manual |
| Schema-breaking upgrade | re-run `code-review-graph build` (rare) | manual |

The watcher and the runner's explicit `update` calls are complementary —
watcher catches edits inside the devshell; `update` guarantees freshness
at phase boundaries even if watcher is off.

## Future-proofing

If a future project prefers a different graph tool (Sourcegraph, ast-grep,
tree-sitter-stack-graphs), the **shape** of the integration transfers:

- Derivation lives in the skill, pinned to a release tag
- `mkShellHook` handles lifecycle (watch + MCP + PID files)
- phase files opt in by documenting which CLI commands to invoke
- runner runs `update` equivalents at phase boundaries
- review prompt gets pre-computed impact analysis

Only the CLI command names change.

## Pitfalls + known issues

- **First build is slow** — never block the devshell on it. `mkShellHook`
  runs it async; agents must tolerate missing graph by polling.
- **Watch mode uses inotify** — on Linux, `fs.inotify.max_user_watches` may
  need raising for very large repos (`sudo sysctl -w fs.inotify.max_user_watches=524288`).
- **Graph db is not portable across versions** — bumping `code-review-graph`
  past a minor release may invalidate the schema. Runner should detect
  schema-version mismatch and re-run `build`.
- **Excluded dirs matter** — forgetting to exclude `node_modules` adds tens
  of thousands of irrelevant nodes and balloons build time. `mkShellHook`
  defaults exclude common culprits; extend per-project.
- **MCP server = long-lived process** — make sure `crg-stop` is called on
  exit, or use the PID file to clean up stale servers on next shell entry.
