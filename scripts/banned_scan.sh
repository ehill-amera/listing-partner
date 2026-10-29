#!/bin/sh
# Banned-strings scan: street addresses and other private tokens must never
# appear in tracked files or file names.
#
# Usage: sh scripts/banned_scan.sh <repo-top>
# Exits 0 when clean, 1 with a loud message otherwise.
#
# The list lives OUTSIDE the repo. This script never prints the list's
# contents: a hit reports the tracked file, its line numbers, and the list
# entry's number, never the string itself.
set -u
top=${1:?usage: banned_scan.sh <repo-top>}
list="$top/../.listing-partner-private/banned-strings.txt"
if [ ! -s "$list" ]; then
  echo "BANNED LIST MISSING OR EMPTY: $list. The address check cannot run." >&2
  exit 1
fi
TAB=$(printf '\t')
# Number the active entries (skip blanks and #-comments) as entry #1, #2, ...
numbered=$(awk ' /^[[:space:]]*(#|$)/ {next} {n++; print n "\t" $0}' "$list")
if [ -z "$numbered" ]; then
  echo "BANNED LIST EMPTY: $list holds no active entries." >&2
  exit 1
fi
tracked=$(git -C "$top" ls-files) || { echo "BANNED SCAN FAILED: cannot list tracked files." >&2; exit 1; }
hit=0
# Heredoc (not a pipe) so the loop runs in this shell and $hit sticks.
while IFS= read -r line; do
  n=${line%%"$TAB"*}
  pat=${line#*"$TAB"}
  [ -n "${pat:-}" ] || continue
  # Tracked file names.
  names=$(printf '%s\n' "$tracked" | grep -i -F -e "$pat" || true)
  if [ -n "$names" ]; then
    printf '%s\n' "$names" | while IFS= read -r f; do
      echo "BANNED entry #$n in tracked file name: $f"
    done
    hit=1
  fi
  # Tracked file contents: files first, then line numbers, never the text.
  files=$(git -C "$top" grep -l -i -F -e "$pat" -- . 2>/dev/null || true)
  if [ -n "$files" ]; then
    printf '%s\n' "$files" | while IFS= read -r f; do
      lines=$(git -C "$top" grep -n -I -i -F -e "$pat" -- "$f" 2>/dev/null | cut -d: -f2 | paste -sd, -)
      echo "BANNED entry #$n in tracked file $f lines: $lines"
    done
    hit=1
  fi
done <<EOF
$numbered
EOF
if [ "$hit" = 1 ]; then
  exit 1
fi
echo "banned-strings scan clean"
exit 0
