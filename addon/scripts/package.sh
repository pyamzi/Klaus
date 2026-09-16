#!/usr/bin/env bash
# Build klausmate.ankiaddon for manual distribution (Anki: File → Install add-on from file).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/klausmate"
OUT_DIR="$ROOT/dist"
OUT="$OUT_DIR/klausmate.ankiaddon"
STAGE="$(mktemp -d)"

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

if [[ ! -f "$SRC/__init__.py" ]]; then
  echo "error: $SRC/__init__.py not found" >&2
  exit 1
fi

# Bump manifest mod so Anki treats this as a new build.
python3 - "$SRC/manifest.json" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["mod"] = int(time.time())
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"manifest mod -> {data['mod']}")
PY

# The Klaus Plus service is NEVER shipped to a user. It is a separate
# program (server-side FastAPI, its own deps, its own licence) that lives
# in `service/` at the repo root — outside $SRC, so staging only "$SRC/"
# already leaves it out. The `service/` exclude below is belt-and-braces
# for the two ways that could quietly stop being true: someone widens
# $SRC to the repo root, or someone adds a `klausmate/service/` folder.
# Shipping it would put the operator's deploy runbook (and one day
# anything near it) in every user's add-ons folder.
echo "Staging add-on files..."
rsync -a \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'meta.json*' \
  --exclude 'service/' \
  --exclude 'user_files/' \
  --exclude 'user_files_README.txt' \
  "$SRC/" "$STAGE/"

mkdir -p "$STAGE/user_files"
# The user_files README ships to every install but the live copy under
# user_files/ is gitignored (the same rule that protects personal data),
# so it drifted unreviewed for months — it still described deleted
# features when caught (K-050). The TRACKED template one level up is the
# source of truth now; user_files/README.txt on a dev machine is just a
# stale artifact of old builds.
cp "$SRC/user_files_README.txt" "$STAGE/user_files/README.txt"

mkdir -p "$OUT_DIR"
rm -f "$OUT"

echo "Creating $OUT ..."
(
  cd "$STAGE"
  zip -rq "$OUT" . -x '*.pyc' -x '*__pycache__*' -x '.DS_Store'
)

BYTES=$(wc -c <"$OUT" | tr -d ' ')
echo "Done: $OUT ($BYTES bytes)"
echo "Install in Anki: Tools → Add-ons → Install from file…"