{
  description = "@spec-kit/runner — TypeScript spec-kit parallel runner (dev shell)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          nodejs_22
          typescript
          typescript-language-server
          sqlite
          git
        ];

        shellHook = ''
          echo "@spec-kit/runner devshell — node $(node --version), tsc $(tsc --version)"
        '';
      };
    };
}
