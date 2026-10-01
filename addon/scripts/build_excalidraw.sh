#!/bin/sh
# Rebuild klausmate/image_occlusion/excalidraw/ (the "Draw a diagram…"
# page): entry.jsx + @excalidraw/excalidraw + React, bundled by esbuild into
# ONE classic script (IIFE) because Anki serves add-on files over its local
# /_addons/ server, plus the stylesheet, the fonts and the licences.
# Needs node/npm; network only here, never at runtime. Versions are pinned.
#
# Three edits keep the page offline and under 8 MB:
#   - Excalidraw's font fallback (https://esm.sh/...) is pointed at
#     EXCALIDRAW_ASSET_PATH, so a missing font never goes to the network;
#   - every locale but English is stubbed (we never set langCode);
#   - @excalidraw/mermaid-to-excalidraw is stubbed (about 3 MB): pasting
#     Mermaid text pastes it as text, and the Mermaid dialog shows an error.
set -eu
EXCALIDRAW=0.18.1
REACT=18.3.1
ESBUILD=0.19.10   # the esbuild Excalidraw 0.18.1 itself builds with
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="$REPO/klausmate/image_occlusion/excalidraw"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
echo '{"private": true}' > package.json
npm install --silent --no-audit --no-fund --save-exact \
  "@excalidraw/excalidraw@$EXCALIDRAW" "react@$REACT" "react-dom@$REACT" "esbuild@$ESBUILD"
cp "$OUT/entry.jsx" entry.jsx
cp "$OUT/fonts/LICENSES.txt" "$TMP/LICENSES.txt"  # committed, not from npm: kept across the rebuild
# esbuild writes to $TMP/dist; the tree is touched only after the patch check passes.
node - "$TMP/dist" <<'EOF'
const esbuild = require("esbuild");
const fs = require("fs");
const out = process.argv[2];
const FALLBACK = '`https://esm.sh/${M.PKG_NAME?`${M.PKG_NAME}@${M.PKG_VERSION}`:"@excalidraw/excalidraw"}/dist/prod/`';
const LOCAL = "new URL(window.EXCALIDRAW_ASSET_PATH, location.href).href";
let patched = 0;
const offline = {
  name: "offline",
  setup(b) {
    b.onResolve({ filter: /^\.\/locales\// }, (a) =>
      a.path.startsWith("./locales/en-") ? undefined : { path: a.path, namespace: "stub" });
    b.onResolve({ filter: /^@excalidraw\/mermaid-to-excalidraw$/ }, (a) => ({ path: a.path, namespace: "stub" }));
    b.onLoad({ filter: /.*/, namespace: "stub" }, (a) => ({
      contents: a.path.startsWith("./locales/")
        ? "export default {};"
        : 'export const parseMermaidToExcalidraw = async () => { throw new Error("Mermaid is not included in Klaus"); };',
    }));
    b.onLoad({ filter: /@excalidraw[\/\\]excalidraw[\/\\]dist[\/\\]prod[\/\\][^\/\\]+\.js$/ }, (a) => {
      const src = fs.readFileSync(a.path, "utf8");
      const n = src.split(FALLBACK).length - 1;
      patched += n;
      return n ? { contents: src.split(FALLBACK).join(LOCAL), loader: "js" } : undefined;
    });
  },
};
esbuild.build({
  entryPoints: ["entry.jsx"],
  bundle: true,
  format: "iife",
  minify: true,
  target: "es2020",
  conditions: ["production"],
  define: { "process.env.NODE_ENV": '"production"' },
  external: ["./fonts/*"],  // the stylesheet's fonts: copied below
  legalComments: "external",
  outfile: out + "/excalidraw.js",
  logLevel: "warning",
  plugins: [offline],
}).then(() => {
  if (patched !== 1) { console.error("font fallback patched " + patched + " times, expected 1"); process.exit(1); }
}).catch((e) => { console.error(e.message); process.exit(1); });
EOF
rm -rf "$OUT/fonts" "$OUT/excalidraw.js" "$OUT/excalidraw.css" "$OUT"/*.LEGAL.txt
cp -R "$TMP/dist/." "$OUT/"
P=node_modules/@excalidraw/excalidraw
cp -R "$P/dist/prod/fonts/." "$OUT/fonts/"
cp "$TMP/LICENSES.txt" "$OUT/fonts/LICENSES.txt"
cp node_modules/react/LICENSE "$OUT/LICENSE-react.txt"
[ -s "$OUT/excalidraw.css.LEGAL.txt" ] || rm -f "$OUT/excalidraw.css.LEGAL.txt"
ls -l "$OUT/excalidraw.js" | awk '{print "excalidraw.js:", $5, "bytes"}'
