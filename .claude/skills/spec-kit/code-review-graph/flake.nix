{
  description = "code-review-graph — persistent incremental knowledge graph for code reviews (pinned to v2.3.2)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        # Overlay: upstream python312Packages.inquirer 3.4.1 has flaky
        # pexpect-based acceptance tests that timeout in the Nix sandbox.
        # `inquirer` arrives transitively via fastmcp → chalice → aioboto3.
        # Disable its test suite so the whole tree builds.
        python = pkgs.python312.override {
          packageOverrides = self: super: {
            inquirer = super.inquirer.overridePythonAttrs (_: { doCheck = false; });
            mcp = super.mcp.overridePythonAttrs (_: { doCheck = false; });
          };
        };

        # Pinned to v2.3.2 release.  Bump version + hash together.
        version = "2.3.2";
        src = pkgs.fetchFromGitHub {
          owner = "tirth8205";
          repo = "code-review-graph";
          rev = "v${version}";
          hash = "sha256-2U+NfPOb2A/gmqzRUQ/80C5EhOHPM4YpGilZmVSTY/g=";
        };

        code-review-graph = python.pkgs.buildPythonApplication {
          pname = "code-review-graph";
          inherit version src;
          pyproject = true;

          build-system = with python.pkgs; [ hatchling ];

          # Upstream pins tree-sitter-language-pack <1 (nixpkgs has 1.4.1)
          # and watchdog <6 (nixpkgs has 6.0.0).  Both are minor bumps with
          # no real incompatibility — relax the ranges.
          pythonRelaxDeps = [ "tree-sitter-language-pack" "watchdog" ];

          dependencies = with python.pkgs; [
            mcp
            fastmcp
            tree-sitter
            tree-sitter-language-pack
            networkx
            watchdog
          ];

          # Upstream test suite requires network + fixtures we don't vendor.
          doCheck = false;

          pythonImportsCheck = [ "code_review_graph" ];

          meta = with pkgs.lib; {
            description = "Persistent incremental knowledge graph for token-efficient, context-aware code reviews with Claude";
            homepage = "https://github.com/tirth8205/code-review-graph";
            license = licenses.mit;
            mainProgram = "code-review-graph";
          };
        };

        # Helper that returns a shellHook string.  Consuming projects call
        # this from their own devShell and splice the result into their
        # shellHook.  Handles: first-time build detection (async), idempotent
        # watch-mode lifecycle (PID file), MCP server lifecycle.
        mkShellHook =
          { projectName ? "project"
          , buildOnEnter ? true      # run `update` on shell entry (fast, incremental)
          , watch ? true             # keep a watcher running for the shell lifetime
          , serveMcp ? false         # start `code-review-graph serve` as an MCP server
          , autoInstall ? true       # run `code-review-graph install` once per project
                                     # (merges MCP config, drops skills, installs hooks)
          , mcpPort ? 7333
          , stateDir ? ".code-review-graph"
          # Project-specific exclude patterns. v2.3.2's CLI has no --exclude
          # flag, but the tool natively reads `.code-review-graphignore` at
          # the repo root (see upstream incremental.py:_load_ignore_patterns).
          # mkShellHook writes these as a managed block in that file on
          # every shell entry (idempotent — only rewrites on content change).
          # Each entry is a glob pattern; bare names are auto-suffixed with
          # `/**` so they match at any depth (e.g. `node_modules` matches
          # `packages/app/node_modules/foo.js` in monorepos).
          #
          # The upstream DEFAULT_IGNORE_PATTERNS already covers most of the
          # common noise (node_modules, .venv, dist, build, .dart_tool, .next,
          # vendor, .gradle, .pub-cache, coverage, *.min.js, package-lock.json,
          # etc.) so only list things NOT in that default set. Commit the
          # resulting `.code-review-graphignore` so all contributors share it.
          , excludeDirs ? [ ]
          }:
          let
            # Each pattern: if it already contains a glob character, pass as-is;
            # otherwise treat it as a directory and append `/**`.
            hasGlob = p: builtins.match ".*[*?].*" p != null;
            normalizePattern = p: if hasGlob p then p else "${p}/**";
            ignorePatterns = map normalizePattern excludeDirs;
            ignoreBlock =
              if ignorePatterns == [ ] then ""
              else builtins.concatStringsSep "\n" ignorePatterns + "\n";
          in
          ''
            # code-review-graph lifecycle — auto-maintained knowledge graph
            export CODE_REVIEW_GRAPH_STATE_DIR="$PWD/${stateDir}"
            export CODE_REVIEW_GRAPH_PROJECT="${projectName}"
            mkdir -p "$CODE_REVIEW_GRAPH_STATE_DIR"

            _crg_pid_file="$CODE_REVIEW_GRAPH_STATE_DIR/watch.pid"
            _crg_mcp_pid_file="$CODE_REVIEW_GRAPH_STATE_DIR/mcp.pid"
            _crg_log="$CODE_REVIEW_GRAPH_STATE_DIR/watch.log"
            _crg_mcp_log="$CODE_REVIEW_GRAPH_STATE_DIR/mcp.log"

            _crg_is_running() {
              local pidfile="$1"
              [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null
            }

            # Managed `.code-review-graphignore` block. Rewrites the block
            # on content change only — idempotent and diff-friendly. Anything
            # outside the BEGIN/END markers is preserved (users can add
            # their own patterns below the block). Upstream semantics:
            # patterns use fnmatch-style globs; `<dir>/**` matches nested
            # occurrences at any depth.
            _crg_ignore_file="$PWD/.code-review-graphignore"
            _crg_marker_begin="# BEGIN code-review-graph managed (from flake.nix excludeDirs)"
            _crg_marker_end="# END code-review-graph managed"
            _crg_desired_block=$(cat <<'CRG_IGNORE_EOF'
${ignoreBlock}CRG_IGNORE_EOF
            )
            _crg_write_ignore_block() {
              local existing="" before="" after=""
              [ -f "$_crg_ignore_file" ] && existing=$(cat "$_crg_ignore_file")
              if printf '%s\n' "$existing" | grep -qF "$_crg_marker_begin"; then
                before=$(printf '%s\n' "$existing" | sed "/$_crg_marker_begin/,\$d")
                after=$(printf '%s\n' "$existing" | sed "1,/$_crg_marker_end/d")
              else
                before="$existing"
                after=""
              fi
              {
                [ -n "$before" ] && printf '%s\n' "$before"
                if [ -n "$_crg_desired_block" ]; then
                  printf '%s\n' "$_crg_marker_begin"
                  printf '%s' "$_crg_desired_block"
                  printf '%s\n' "$_crg_marker_end"
                fi
                [ -n "$after" ] && printf '%s\n' "$after"
              } > "$_crg_ignore_file.tmp"
              # Only replace if content actually changed (preserves mtime,
              # avoids spurious "dirty tree" warnings from nix develop).
              if ! cmp -s "$_crg_ignore_file.tmp" "$_crg_ignore_file" 2>/dev/null; then
                mv "$_crg_ignore_file.tmp" "$_crg_ignore_file"
                echo "[code-review-graph] updated .code-review-graphignore"
              else
                rm -f "$_crg_ignore_file.tmp"
              fi
              # If desired block is empty AND file only contained our managed
              # block, remove the file entirely.
              if [ -f "$_crg_ignore_file" ] && [ -z "$_crg_desired_block" ] && ! grep -qv "^$\|^#" "$_crg_ignore_file"; then
                rm -f "$_crg_ignore_file"
              fi
            }
            _crg_write_ignore_block

            ${pkgs.lib.optionalString autoInstall ''
            # Auto-install: merges `code-review-graph` into .mcp.json (preserving
            # other servers), drops skill files into .claude/skills/, installs
            # PostToolUse + SessionStart hooks into .claude/settings.json, and a
            # git pre-commit hook.  Idempotent — skipped when the marker file
            # records the current tool version.  `--no-instructions` means the
            # upstream CLAUDE.md injection is skipped; spec-kit manages that
            # stanza itself (see reference/code-review-graph.md).
            _crg_install_marker="$CODE_REVIEW_GRAPH_STATE_DIR/installed-v${version}"
            if [ ! -f "$_crg_install_marker" ]; then
              if code-review-graph install \
                   --repo "$PWD" \
                   --platform claude-code \
                   --no-instructions \
                   -y >"$CODE_REVIEW_GRAPH_STATE_DIR/install.log" 2>&1; then
                touch "$_crg_install_marker"
                echo "[code-review-graph] installed hooks + skills + MCP config (v${version})"
              else
                echo "[code-review-graph] auto-install failed — see $CODE_REVIEW_GRAPH_STATE_DIR/install.log" >&2
              fi
            fi
            ''}

            # First build: async if the graph database doesn't exist yet.
            # Subsequent entries: quick `update` in the background.
            if [ ! -f "$CODE_REVIEW_GRAPH_STATE_DIR/graph.db" ] && [ ! -f "$CODE_REVIEW_GRAPH_STATE_DIR/code_graph.db" ]; then
              echo "[code-review-graph] building initial graph in background (first run — may take minutes)..."
              ( code-review-graph build >"$CODE_REVIEW_GRAPH_STATE_DIR/build.log" 2>&1 ) &
              echo $! > "$CODE_REVIEW_GRAPH_STATE_DIR/build.pid"
            ${pkgs.lib.optionalString buildOnEnter ''
            else
              ( code-review-graph update >>"$CODE_REVIEW_GRAPH_STATE_DIR/update.log" 2>&1 ) &
            ''}
            fi

            ${pkgs.lib.optionalString watch ''
            # Watcher: keep the graph fresh as files change.  Idempotent:
            # reuse an existing watcher if one is already running.
            if ! _crg_is_running "$_crg_pid_file"; then
              ( code-review-graph watch >"$_crg_log" 2>&1 ) &
              echo $! > "$_crg_pid_file"
              echo "[code-review-graph] watcher started (pid $(cat "$_crg_pid_file"), log: $_crg_log)"
            fi
            ''}

            ${pkgs.lib.optionalString serveMcp ''
            # MCP server: accessible to any MCP-aware client (Claude Code,
            # Cursor, etc.) via stdio.  Idempotent.
            if ! _crg_is_running "$_crg_mcp_pid_file"; then
              ( code-review-graph serve >"$_crg_mcp_log" 2>&1 ) &
              echo $! > "$_crg_mcp_pid_file"
              echo "[code-review-graph] MCP server started (pid $(cat "$_crg_mcp_pid_file"), log: $_crg_mcp_log)"
            fi
            ''}

            # Cleanup helper — projects can call `crg-stop` to terminate
            # watcher + MCP server.  Exposed as a shell function.
            crg-stop() {
              for pf in "$_crg_pid_file" "$_crg_mcp_pid_file"; do
                if [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null; then
                  kill "$(cat "$pf")" 2>/dev/null || true
                  rm -f "$pf"
                fi
              done
              echo "[code-review-graph] stopped watcher + MCP server"
            }
            export -f crg-stop 2>/dev/null || true
          '';
      in
      {
        packages = {
          inherit code-review-graph;
          default = code-review-graph;
        };

        lib = {
          inherit mkShellHook;
        };

        # Dev shell for hacking on this flake itself.
        devShells.default = pkgs.mkShell {
          packages = [ code-review-graph ];
        };
      }
    );
}
