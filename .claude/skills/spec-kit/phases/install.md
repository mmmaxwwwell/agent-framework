# Phase 0: Ensure spec-kit is installed

1. Check if `specify` is available: run `which specify || specify --version 2>/dev/null`.
2. **If not installed**, install it pinned to **v0.4.1**:
   - **Preferred (Nix available)**: `nix profile install --impure --expr '(builtins.getFlake "github:github/spec-kit/v0.4.1").packages.${builtins.currentSystem}.default or (import (builtins.fetchGit { url = "https://github.com/github/spec-kit.git"; ref = "v0.4.1"; }) {})'` — if spec-kit doesn't publish a flake, fall back to `uv` below.
   - **Fallback**: `uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git@v0.4.1"`. If `uv` is not available, tell the user they need to install `uv` first (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
3. **If already installed**, verify the version: `specify --version`. If it's not `0.4.1`, reinstall using the same method as step 2 (with `--force` for `uv`).
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
