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
          , mcpPort ? 7333
          , stateDir ? ".code-review-graph"
          , excludeDirs ? [ "node_modules" ".direnv" "result" "dist" ".venv" "__pycache__" "build" ".dart_tool" ]
          }:
          let
            excludeArgs = builtins.concatStringsSep " " (map (d: "--exclude ${d}") excludeDirs);
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

            # First build: async if the graph database doesn't exist yet.
            # Subsequent entries: quick `update` in the background.
            if [ ! -f "$CODE_REVIEW_GRAPH_STATE_DIR/graph.db" ] && [ ! -f "$CODE_REVIEW_GRAPH_STATE_DIR/code_graph.db" ]; then
              echo "[code-review-graph] building initial graph in background (first run — may take minutes)..."
              ( code-review-graph build ${excludeArgs} >"$CODE_REVIEW_GRAPH_STATE_DIR/build.log" 2>&1 ) &
              echo $! > "$CODE_REVIEW_GRAPH_STATE_DIR/build.pid"
            ${pkgs.lib.optionalString buildOnEnter ''
            else
              ( code-review-graph update ${excludeArgs} >>"$CODE_REVIEW_GRAPH_STATE_DIR/update.log" 2>&1 ) &
            ''}
            fi

            ${pkgs.lib.optionalString watch ''
            # Watcher: keep the graph fresh as files change.  Idempotent:
            # reuse an existing watcher if one is already running.
            if ! _crg_is_running "$_crg_pid_file"; then
              ( code-review-graph watch ${excludeArgs} >"$_crg_log" 2>&1 ) &
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
