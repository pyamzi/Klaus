#!/bin/bash
# PostToolUse guard for klausmate edits.
#
# Compiles the addon *through the Anki symlink*, which checks two things at
# once: that the Python is syntactically valid, and that the symlink Anki
# actually loads still points here. The second one matters — when that link
# broke, Anki silently loaded a stale numbered copy and every change looked
# like it did nothing.
set -uo pipefail

FILE=$(python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit
print(d.get("tool_input", {}).get("file_path", "") or "")' 2>/dev/null)

case "$FILE" in
  */klausmate/*.py) ;;
  *) exit 0 ;;
esac

LINK="$HOME/Library/Application Support/Anki2/addons21/klausmate"
if [ ! -L "$LINK" ]; then
  echo "klausmate: the addons21 symlink is MISSING ($LINK)." >&2
  echo "Anki is not loading this code. Recreate it with:" >&2
  echo "  ln -s /Users/pyamzi/Documents/Github/KlausMate-Context/klausmate \"$LINK\"" >&2
  exit 2
fi
if [ ! -e "$LINK" ]; then
  echo "klausmate: the addons21 symlink is DANGLING ($LINK)." >&2
  exit 2
fi

if ! OUT=$(python3 -m py_compile "$LINK"/*.py 2>&1); then
  echo "klausmate: py_compile failed after editing $(basename "$FILE"):" >&2
  echo "$OUT" >&2
  exit 2
fi
exit 0
