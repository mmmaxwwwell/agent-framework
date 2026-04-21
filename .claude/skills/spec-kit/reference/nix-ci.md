# Nix-specific CI rules

These rules apply to any agent (CI diagnose, CI fix, CI local-validate) running commands in a project that uses a Nix flake. Read this file when you need to run `nix` commands or when CI is failing on a Nix project.

## Sandbox + daemon

- Set `NIX_REMOTE=daemon` for any nix command that writes to the store.
- Pass `--extra-experimental-features 'nix-command flakes'` when invoking `nix` directly.

## Devshell — do not re-evaluate per command

- Do NOT use `nix develop --command <cmd>` — it re-evaluates the flake every call (slow + cache-busting).
- Source the devshell once instead, or run commands in the existing devshell process.
- The runner's PATH already includes the devshell tools when launched via `nix develop` outside the agent.

## `nix flake check` and VM tests

- `nix flake check` can take 10–20 minutes when it includes NixOS VM tests. Use a timeout ≥ 1800s.
- Run it in the background (`run_in_background=true`) and write output to a file rather than relying on stdout.
- Do NOT pipe through `head` / `tail` — that truncates the failure signal.
- Sample command:
  ```
  NIX_REMOTE=daemon nix --extra-experimental-features 'nix-command flakes' flake check --print-build-logs > /tmp/nix-flake-check.log 2>&1; echo "EXIT_CODE=$?" >> /tmp/nix-flake-check.log
  ```
- After the command finishes, read the **last 200 lines** of the log — critical errors (FTL, FAIL, error:, "failed with") are always at the end.
- Include the actual error output in your report — the fix agent needs the real messages, not "exit code 1".

## bwrap sandbox

- The bwrap sandbox restricts writes; if a command needs to write outside the project directory, run it outside the sandbox or widen the sandbox explicitly.
- `~/.claude/`, `~/.ssh/`, and most home-dir paths are NOT mounted inside the sandbox.

## What NOT to do

- Do NOT prefix every command with `nix develop --command` — see the devshell rule above.
- Do NOT pipe `nix flake check` output through `head` / `tail` / `grep -c` — write to a file and read what you need.
- Do NOT try to install packages with `nix-env -i` inside the sandbox — it will fail on store writes. Add the package to `flake.nix` and let the runner re-enter the devshell.
- Do NOT trust a 0 exit code from a command that piped through `tee` without `set -o pipefail` — the source command may have failed silently.
