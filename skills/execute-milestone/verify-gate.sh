#!/usr/bin/env bash
# Claude Code Stop hook: block "done" until the project's verification gate is green.
# Gate command = first non-comment line of <project>/.claude/verify-gate. No file → no-op.
# Skips when nothing changed since the last green run (cache keyed on HEAD + diff),
# and never blocks twice in a row (stop_hook_active) so it can't loop forever.
set -uo pipefail
input=$(cat)
dir=$(jq -r '.cwd // empty' <<<"$input"); dir=${dir:-$PWD}
[[ $(jq -r '.stop_hook_active // false' <<<"$input") == true ]] && exit 0
cd "$dir" 2>/dev/null || exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
gate_file="$root/.claude/verify-gate"
[[ -f $gate_file ]] || exit 0
cmd=$(grep -v '^\s*#' "$gate_file" | grep -m1 .) || exit 0
stamp="$root/.claude/.verify-gate.green"
key=$( { git -C "$root" rev-parse HEAD; git -C "$root" diff HEAD; git -C "$root" status --porcelain; } | sha256sum | cut -d' ' -f1)
[[ -f $stamp && $(cat "$stamp") == "$key" ]] && exit 0
out=$(cd "$root" && timeout "${VERIFY_GATE_TIMEOUT:-1800}" bash -c "$cmd" 2>&1); rc=$?
if (( rc == 0 )); then echo "$key" >"$stamp"; exit 0; fi
{ echo "verify-gate FAILED (exit $rc): $cmd"; echo "--- last 30 lines ---"; tail -30 <<<"$out"; echo "Fix this before finishing, or tell the owner why it can't be fixed now."; } >&2
exit 2
