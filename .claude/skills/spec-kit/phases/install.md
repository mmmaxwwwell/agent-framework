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
