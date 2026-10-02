{
  description = "Claude Code skills — reusable agent prompts, installable via nix";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;

      skillNames = [
        "code-review"
        "code-review-node"
        "code-review-react"
        "eng-standards"
        "execute-milestone"
        "handoff"
        "plan-feature"
        "scout"
        "spec-kit"
        "toolbelt"
        "toolbelt-setup"
        "ux-review"
      ];

      # Build a single skill package: copies skill content + substituted command wrapper
      mkSkill = pkgs: name: pkgs.stdenvNoCC.mkDerivation {
        pname = "claude-skill-${name}";
        version = "0.1.0";
        src = self;

        phases = [ "installPhase" ];

        installPhase = ''
          # Install skill content
          mkdir -p $out/share/claude-skills
          cp -r $src/skills/${name} $out/share/claude-skills/${name}

          # Install command wrapper with substituted path
          mkdir -p $out/share/claude-commands
          substitute $src/commands/${name}.md $out/share/claude-commands/${name}.md \
            --replace-fail "@SKILL_PATH@" "$out/share/claude-skills"
        '';
      };
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          skills = builtins.listToAttrs (map (name: {
            inherit name;
            value = mkSkill pkgs name;
          }) skillNames);
        in
        let
          all = pkgs.symlinkJoin {
            name = "claude-skills-all";
            paths = map (name: skills.${name}) skillNames;
          };
        in
        skills // {
          inherit all;
          default = all;
        }
      );

      # Home-manager module for declarative install
      homeManagerModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.programs.claude-skills;
          skillPkgs = self.packages.${pkgs.system};
        in
        {
          options.programs.claude-skills = {
            enable = lib.mkEnableOption "Claude Code skills";

            skills = lib.mkOption {
              type = lib.types.listOf (lib.types.enum skillNames);
              default = skillNames;
              description = "Which skills to install. Defaults to all.";
            };

            autoLoadEngStandards = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Auto-load eng-standards for software tasks via ~/CLAUDE.md";
            };
          };

          config = lib.mkIf cfg.enable (
            let
              selected = map (name: skillPkgs.${name}) cfg.skills;
              merged = pkgs.symlinkJoin {
                name = "claude-skills-selected";
                paths = selected;
              };
              engPkg = skillPkgs.eng-standards;
            in
            {
              # Symlink command wrappers into ~/.claude/commands/
              home.file = builtins.listToAttrs (map (name: {
                name = ".claude/commands/${name}.md";
                value = { source = "${skillPkgs.${name}}/share/claude-commands/${name}.md"; };
              }) cfg.skills);
            }
          );
        };
    };
}
