# Phase 0: Ensure spec-kit is installed (project-scoped only)

**Security rule: NEVER install tools globally.** No `nix profile install`, no `uv tool install`, no `npm install -g`, no `pip install`, no `curl | sh`. All tools go into the project's `flake.nix` devShell or are run ephemerally.

## Install specify CLI

1. Check if `specify` is available: `which specify || specify --version 2>/dev/null`.
2. **If not installed**, add it to the project's Nix devShell:
   - **If `flake.nix` exists**: Add `specify` (pinned to v0.4.1) to the devShell's `buildInputs`/`packages`. Then re-enter the shell with `nix develop` or `direnv reload`.
   - **If no `flake.nix` yet**: Create a minimal `flake.nix` with a devShell that includes `specify` and common tools (git, nodejs, python3). Then enter with `nix develop`.
   - **If Nix is not available**: Use `uvx --from "git+https://github.com/github/spec-kit.git@v0.4.1" specify --version` for ephemeral execution (no install). Every `specify` invocation must go through `uvx`. If `uvx` is not available, tell the user to install `uv` and do NOT run `curl | sh` or `pip install` — ask the user to install it themselves.
3. **If already installed**, verify the version: `specify --version`. If it's not `0.4.1`, update the pin in `flake.nix` and re-enter the shell.
4. Verify: `specify --version` (should show `v0.4.1`)

## Initialize or locate the project

**If `$ARGUMENTS` contains a project name** (or the user provides one):
- Check if a `.specify/` directory already exists in the current working directory.
  - **If it exists** → skip init, this project is already set up. Tell the user and proceed to phase detection.
  - **If it doesn't exist** → run: `specify init <project-name> --ai claude --script bash`
  - After init, briefly tell the user what was created.

**If no project name provided**:
- Check if `.specify/` exists in the current directory.
  - **If it exists** → this is an existing spec-kit project. Tell the user and proceed to phase detection.
  - **If not** → ask the user for a project name, then init.

## Bootstrap code-review-graph (MANDATORY)

**The knowledge graph must be wired up before anything else.** Every
downstream phase consumes it — skipping this step leaves the rest of the
workflow blind to the existing codebase.

Full spec: `reference/code-review-graph.md`. Load that file now if you
haven't already.

1. **Locate the skill's flake**: it lives at
   `.claude/skills/spec-kit/code-review-graph/flake.nix` inside the
   agent-framework checkout (single source of truth, pinned to v2.3.2).

2. **Add as an input to the project's `flake.nix`**:

   ```nix
   inputs = {
     # ... existing inputs ...
     code-review-graph.url = "path:/home/max/git/agent-framework/.claude/skills/spec-kit/code-review-graph";
   };
   ```

   Add `code-review-graph` to the `outputs` function arguments.

3. **Pull the package + shellHook** in the devShell:

   ```nix
   let
     crg = code-review-graph.packages.${system}.code-review-graph;
     crgHook = code-review-graph.lib.${system}.mkShellHook {
       projectName = "<your-project-name>";
       watch = true;      # keep graph fresh as files change
       serveMcp = false;  # set true if the project wants an MCP server
       # Project-specific graph excludes (on top of upstream defaults which
       # already cover node_modules/.venv/dist/build/.dart_tool/etc). These
       # get written to a managed block in `.code-review-graphignore`.
       # See reference/code-review-graph.md § "Per-project excludes".
       excludeDirs = [
         # Examples — add your project's generated / vendored / log dirs:
         # "stl"           # 3D model renders
         # "test-logs"     # test output artifacts
         # "fixtures/**/*.json"  # glob patterns also work
       ];
     };
   in pkgs.mkShell {
     packages = [ crg /* ... */ ];
     shellHook = crgHook + ''
       # existing shellHook content
     '';
   }
   ```

4. **Add `.code-review-graph/` to `.gitignore`** (SQLite db + logs + pid
   files — must never be committed):

   ```gitignore
   # code-review-graph state (build artifacts, not the ignore policy)
   .code-review-graph/
   ```

   Note: do **not** add `.code-review-graphignore` to `.gitignore` — that
   file is the per-project exclude policy and must be committed so every
   contributor indexes the same scope (see next step).

5. **Commit `.code-review-graphignore`** (auto-generated from `excludeDirs`):

   After entering the devshell once, the shellHook writes
   `.code-review-graphignore` at the repo root with a managed block
   derived from `excludeDirs`. Stage and commit it:

   ```bash
   git add .code-review-graphignore flake.nix flake.lock
   git commit -m "chore: wire code-review-graph exclude policy"
   ```

   If `excludeDirs = [ ]`, the file is not created. Anything a contributor
   adds *outside* the `# BEGIN … # END` managed block is preserved on
   re-entry. See `reference/code-review-graph.md § Per-project excludes`
   for the full behavior (idempotent rewrites, glob syntax, when to
   force-rebuild after changes).

6. **Install the CLAUDE.md stanza** so every agent spawned in this project
   reads graph-usage guidance automatically (no prompt-builder edits
   needed in parallel_runner.py):

   - Read the template at
     `.claude/skills/spec-kit/code-review-graph/CLAUDE-STANZA.md` (inside
     the agent-framework checkout)
   - Copy everything between the `---BEGIN-STANZA---` and
     `---END-STANZA---` markers
   - Append it to the project's `CLAUDE.md` (create one if it doesn't
     exist). Place it after any existing project-specific sections.
   - If the stanza is already present (idempotent re-runs), skip.

7. **Verify the bootstrap**:

   ```bash
   nix develop --command bash -c 'code-review-graph --version && ls .code-review-graph/'
   grep -q "code-review-graph — always use the knowledge graph" CLAUDE.md && echo "CLAUDE.md stanza installed"
   ```

   Expected: `code-review-graph 2.3.2`, plus `build.log`, `build.pid`,
   `watch.log`, `watch.pid` files in `.code-review-graph/`, and the
   CLAUDE.md grep match. The initial graph build runs **async** — don't
   block on it; subsequent phases can poll for `.code-review-graph/graph.db`
   (or `code_graph.db`) if they need a fully-built graph.

8. **Record in interview-notes** (if/when the interview starts):
   `code-review-graph: wired at phase 0, watcher active, CLAUDE.md stanza installed`.

**If the project is not Nix-based** (no `flake.nix`, no `which nix`): the
skill still expects code-review-graph to be available. Document the fallback
install in `reference/code-review-graph.md` (`pipx install
code-review-graph==2.3.2`) but prefer Nix whenever possible — the watcher
lifecycle management in `mkShellHook` is nontrivial to replicate by hand.
