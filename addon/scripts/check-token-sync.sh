#!/usr/bin/env bash
# Diffs docs/reference/design-tokens.json against its copy in the other
# Klaus repo (Klaus Addon <-> Klaus App/KlausBook-Context). The two must
# stay byte-identical — see that file's
# own "source_of_truth" field. Run this after editing tokens in either
# repo, from either repo (paths are relative to this script, not $PWD).
#
# Exit 0: copies match. Exit 1: they differ (diff is printed) or the
# sibling repo isn't checked out at the expected path.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKENS_REL="docs/reference/design-tokens.json"
OURS="$HERE/$TOKENS_REL"

# This script is checked into both repos at the same relative path, so its
# own location tells us which one we're running from and where the other
# one lives in the Klaus workspace: <root>/Klaus Addon and
# <root>/Klaus App/KlausBook-Context.
case "$HERE" in
  */"Klaus App"/KlausBook-Context) SIBLING="$(dirname "$(dirname "$HERE")")/Klaus Addon" ;;
  */"Klaus Addon") SIBLING="$(dirname "$HERE")/Klaus App/KlausBook-Context" ;;
  *)
    echo "check-token-sync: unexpected repo path $HERE (expected .../Klaus App/KlausBook-Context or .../Klaus Addon)" >&2
    exit 1
    ;;
esac
THEIRS="$SIBLING/$TOKENS_REL"

if [ ! -f "$THEIRS" ]; then
  echo "check-token-sync: sibling repo not found at $SIBLING (or missing $TOKENS_REL)" >&2
  exit 1
fi

if diff -u "$THEIRS" "$OURS"; then
  echo "check-token-sync: OK — $TOKENS_REL matches in both repos."
else
  echo
  echo "check-token-sync: FAILED — the two copies differ (diff above, ours vs theirs)." >&2
  echo "Copy the change across so both repos stay byte-identical." >&2
  exit 1
fi
