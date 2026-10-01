#!/bin/sh
# Builds Anki's own web pieces from vendor/anki with Anki's pinned yarn and
# dependencies:
#   out/sveltekit  Anki's SvelteKit pages (deck options, import, editor, …)
#   out/klaus      what Anki's Qt app copies into its web folder for the reviewer:
#                  webview.css, reviewer.js/.css, mathjax.js and MathJax itself
#                  (served at /_anki/js|css)
# Each is skipped when already built for the current Anki commit and this script.
set -e
cd "$(dirname "$0")/../vendor/anki"
rev="$(git rev-parse HEAD) $(cksum < ../../scripts/build-anki-pages.sh)"
yarn="npx -y -p @yarnpkg/cli-dist@4.11.0 yarn"
fresh() { [ -f "$1/.klaus-rev" ] && [ "$(cat "$1/.klaus-rev")" = "$rev" ]; }

if ! fresh out/sveltekit || ! fresh out/klaus; then
  $yarn install --immutable
fi

if ! fresh out/sveltekit; then
  $yarn build
  echo "$rev" > out/sveltekit/.klaus-rev
fi

if ! fresh out/klaus; then
  # Same entry points and esbuild script as Anki's build (build/configure/src/web.rs).
  rm -rf out/klaus && o=out/klaus/_anki && mkdir -p "$o/js/vendor" "$o/css"
  node ts/bundle_ts.mjs ts/reviewer/index_wrapper.ts "$o/js/reviewer.js"
  node ts/bundle_ts.mjs ts/mathjax/index.ts "$o/js/mathjax.js"
  sass="node_modules/.bin/sass --load-path . --no-source-map"
  $sass qt/aqt/data/web/css/webview.scss "$o/css/webview.css"
  $sass ts/reviewer/reviewer.scss "$o/css/reviewer.css"
  cp -R node_modules/mathjax/es5 "$o/js/vendor/mathjax"
  echo "$rev" > out/klaus/.klaus-rev
fi
