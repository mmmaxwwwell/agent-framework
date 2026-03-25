#!/usr/bin/env bash
# run-tasks.sh — Parallel spec-kit task runner (thin wrapper)
#
# Delegates to parallel_runner.py which provides:
#   - Parallel agent execution for [P]-marked tasks
#   - Live TUI with ASCII dependency graph + split agent output panes
#   - Headless mode (--headless) with all output to files
#
# Run this from the root of a spec-kit project (where .specify/ and specs/ live).
#
# Usage:
#   ./run-tasks.sh [options] [spec-dir] [max-runs]
#
# Options:
#   --headless       No terminal UI; write all output to log files
#   --max-parallel N Max concurrent agents (default: 3)
#
# Examples:
#   ./run-tasks.sh                                          # TUI mode, all features
#   ./run-tasks.sh specs/001-feature                        # specific spec
#   ./run-tasks.sh specs/001-feature 50                     # with run limit
#   ./run-tasks.sh --headless                               # headless, all features
#   ./run-tasks.sh --headless --max-parallel 5 specs/001    # headless, 5 agents
#
# Stopping:
#   The agent writes BLOCKED.md in the repo root when it needs your input.
#   The script detects this and stops. Edit BLOCKED.md with your answer,
#   then delete it and re-run the script.
#
# Requires: python3 3.9+, claude CLI (Claude Code) with Max subscription
# Run in tmux/screen so it survives terminal disconnects.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/parallel_runner.py"

if ! command -v python3 &>/dev/null; then
  echo "Error: python3 is required but not found in PATH."
  exit 1
fi

# Check python version >= 3.9
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYMAJOR=${PYVER%%.*}
PYMINOR=${PYVER##*.}
if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 9 ]; }; then
  echo "Error: python3 >= 3.9 required (found $PYVER)"
  exit 1
fi

exec python3 "$RUNNER" "$@"
