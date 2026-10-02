#!/usr/bin/env bash
# List registry entries that are NEW (on disk, not in registry), CHANGED (rev
# differs) or GONE (in registry, not on disk). Read-only.
# Usage: scout-stale.sh [registry-path]
set -euo pipefail

reg="${1:-${SCOUT_REGISTRY:-$HOME/git/agent-framework/registry/inventory.md}}"
declare -A known=()

if [[ -f "$reg" ]]; then
  # Table rows: | name | kind | path | rev | ... ; ignored lines: - name@rev — reason
  while IFS='|' read -r _ name _ _ rev _; do
    name="${name// /}"; rev="${rev// /}"
    [[ -z "$name" || "$name" == name || "$name" == -* ]] && continue
    known["$name"]="$rev"
  done < <(grep -E '^\|' "$reg")
  while read -r entry; do
    known["${entry%@*}"]="${entry#*@}"
  done < <(grep -oE '^- [A-Za-z0-9._-]+@[0-9a-z:]+' "$reg" | sed 's/^- //')
fi

rev_of() { git -C "$1" rev-parse --short HEAD 2>/dev/null || echo nogit; }
# A skill's rev is the last commit touching its own dir, so unrelated commits
# in the host repo don't mark every skill stale.
# Uncommitted or dirty dirs fall back to a content hash ("h:"), so edits still show.
skill_rev_of() {
  local r
  if [[ -z "$(git -C "$1" status --porcelain -- . 2>/dev/null)" ]]; then
    r="$(git -C "$1" log -1 --format=%h -- . 2>/dev/null)"
  fi
  [[ -n "${r:-}" ]] || r="h:$(find "$1" -type f -print0 | sort -z | xargs -0 sha1sum | sha1sum | cut -c1-7)"
  echo "$r"
}

declare -A seen=()
check() {  # name path rev
  local name="$1" path="$2" rev="$3"
  seen["$name"]=1
  if [[ -z "${known[$name]+x}" ]]; then echo "NEW $name $path $rev"
  elif [[ "${known[$name]}" != "$rev" ]]; then echo "CHANGED $name $path $rev (was ${known[$name]})"
  fi
}

# A git worktree (.git is a file) belongs to its parent repo's row: skip it
# and any skills inside it.
is_worktree() { [[ -f "$1/.git" ]]; }

for d in "$HOME"/git/*/; do
  d="${d%/}"; is_worktree "$d" && continue
  check "$(basename "$d")" "$d" "$(rev_of "$d")"
done
for d in "$HOME"/git/*/.claude/skills/*/ "$HOME"/.claude/skills/*/ "$HOME"/git/agent-framework/skills/*/; do
  [[ -f "$d/SKILL.md" ]] || continue   # e.g. ~/.claude/skills/synced is a harness bucket
  d="${d%/}"
  [[ "$d" == */.claude/skills/* ]] && is_worktree "${d%/.claude/skills/*}" && continue
  repo="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null || echo "$HOME/.claude")"
  check "skill:$(basename "$repo"):$(basename "$d")" "$d" "$(skill_rev_of "$d")"
done

for name in "${!known[@]}"; do
  [[ -n "${seen[$name]+x}" ]] || echo "GONE $name"
done | sort
