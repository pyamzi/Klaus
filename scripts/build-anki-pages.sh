#!/bin/sh
# Builds Anki's own SvelteKit pages (deck options, import, graphs, …) into
# vendor/anki/out/sveltekit with Anki's pinned yarn and dependencies.
# Skipped when already built for the current Anki commit.
set -e
cd "$(dirname "$0")/../vendor/anki"
rev=$(git rev-parse HEAD)
stamp=out/sveltekit/.klaus-rev
[ -f "$stamp" ] && [ "$(cat "$stamp")" = "$rev" ] && exit 0
yarn="npx -y -p @yarnpkg/cli-dist@4.11.0 yarn"
$yarn install --immutable
$yarn build
echo "$rev" > "$stamp"
