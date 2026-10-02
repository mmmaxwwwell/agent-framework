{
  description = "tabrunner — Tailscale-bound PWA + server for tabbed Claude Code sessions with a meta agent";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    code-review-graph.url = "path:/home/max/git/agent-framework/.claude/skills/spec-kit/code-review-graph";
  };

  outputs = { self, nixpkgs, code-review-graph }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      crg = code-review-graph.packages.${system}.code-review-graph;
      crgHook = code-review-graph.lib.${system}.mkShellHook {
        projectName = "tabrunner";
        watch = true;
        serveMcp = false;
        excludeDirs = [
          "test-logs"
          "logs"
          "validate"
          "attempts"
          "ci-debug"
          "public"
          "dist"
        ];
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          nodejs_22
          typescript
          typescript-language-server
          uv
          python312
          git
          tailscale
          bubblewrap
          openssl
          jq
          sqlite
          crg
        ];

        shellHook = crgHook + ''
          export TABRUNNER_ROOT="$PWD"
          alias specify='uvx --from "git+https://github.com/github/spec-kit.git@v0.4.1" specify'
          echo "tabrunner devshell — node $(node --version), uv $(uv --version | head -1)"
        '';
      };
    };
}
