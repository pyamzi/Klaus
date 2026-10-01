#!/bin/sh
# Rebuild klausmate/web/fonts/Excalifont-Regular.ttf, the Preferences
# wordmark font. Source: the Latin subset of Excalifont shipped (as woff2)
# in @excalidraw/excalidraw (MIT). Qt cannot load woff2, so it is
# converted to TTF with fontTools. Needs node/npm and python3; network only
# here, never at runtime.
set -eu
VERSION=0.18.1
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="$REPO/klausmate/web/fonts"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
npm pack "@excalidraw/excalidraw@$VERSION" --silent >/dev/null
tar xzf "excalidraw-excalidraw-$VERSION.tgz"
python3 -m venv venv
./venv/bin/pip -q install fonttools brotli
mkdir -p "$OUT"
./venv/bin/python - "$OUT/Excalifont-Regular.ttf" package/dist/prod/fonts/Excalifont/*.woff2 <<'EOF'
import sys
from fontTools.ttLib import TTFont
out, files = sys.argv[1], sys.argv[2:]
for f in files:
    font = TTFont(f)
    cmap = font.getBestCmap()
    # The Latin subset: the one covering "KlausMate" and basic ASCII letters.
    if all(ord(c) in cmap for c in "ABCXYZabcxyz0123456789"):
        font.flavor = None
        font.save(out)
        print("wrote", out, "from", f)
        break
else:
    sys.exit("no Excalifont subset covers basic Latin")
EOF
