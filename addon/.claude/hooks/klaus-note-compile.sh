#!/bin/bash
# PostToolUse guard for klaus_note edits.
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
  */klaus_note/*.py) ;;
  *) exit 0 ;;
esac

# Cloud sessions have no Anki install, so only the syntax check applies.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  if ! OUT=$(python3 -m py_compile "$FILE" 2>&1); then
    echo "klaus_note: py_compile failed after editing $(basename "$FILE"):" >&2
    echo "$OUT" >&2
    exit 2
  fi
  exit 0
fi

LINK="$HOME/Library/Application Support/Anki2/addons21/klaus_note"
if [ ! -L "$LINK" ]; then
  echo "klaus_note: the addons21 symlink is MISSING ($LINK)." >&2
  echo "Anki is not loading this code. Recreate it with:" >&2
  echo "  ln -s \"/Users/pyamzi/Documents/Github/Klaus/klaus-note/addon/klaus_note\" \"$LINK\"" >&2
  exit 2
fi
if [ ! -e "$LINK" ]; then
  echo "klaus_note: the addons21 symlink is DANGLING ($LINK)." >&2
  exit 2
fi

if ! OUT=$(python3 -m py_compile "$LINK"/*.py 2>&1); then
  echo "klaus_note: py_compile failed after editing $(basename "$FILE"):" >&2
  echo "$OUT" >&2
  exit 2
fi
exit 0
