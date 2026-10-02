#!/usr/bin/env bash
# Print registry rows for skills, built from SKILL.md frontmatter (no agent).
# Usage: scout-stale.sh | scout-skill-rows.sh   (consumes NEW/CHANGED skill: lines)
set -euo pipefail

while read -r _ name path rev _; do
  [[ "$name" == skill:* ]] || continue
  f="$path/SKILL.md"
  [[ -f "$f" ]] || continue
  # description: inline, quoted, or a folded/literal block (> or |) — unfold it.
  desc="$(awk '
    /^---$/ { fm++; next }
    fm != 1 { next }
    /^description:/ {
      sub(/^description:[ ]*/, "")
      if ($0 ~ /^[>|][-+]?$/) { block = 1; next }
      print; exit
    }
    block && /^[ ]+/ { sub(/^[ ]+/, ""); printf "%s ", $0; next }
    block { exit }
  ' "$f" | sed -E 's/^"//; s/"[[:space:]]*$//' | tr '|' '/')"
  # First sentence, capped at 15 words.
  what="$(sed -E 's/([.!?])( |$).*/\1/' <<<"$desc" | awk '{ n = (NF < 15 ? NF : 15); for (i = 1; i <= n; i++) printf "%s%s", $i, (i < n ? " " : ""); print "" }')"
  host="$(cut -d: -f2 <<<"$name")"
  echo "| $name | skill | ${path/#$HOME/\~} | $rev | $what | skill, $host | |"
done
