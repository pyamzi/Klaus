#!/bin/sh
# Generates Anki's TypeScript backend client into src/lib/generated (gitignored):
# backend.ts comes from anki_proto's build script, post.ts from Anki's source,
# and the *_pb.ts message types from protoc-gen-es (same version Anki pins).
set -e
cd "$(dirname "$0")/.."
cargo build -q -p anki_proto
out=src/lib/generated
rm -rf "$out" && mkdir -p "$out"
cp vendor/anki/out/ts/lib/generated/backend.ts vendor/anki/ts/lib/generated/post.ts "$out/"
# protoc.exe can't run npm's extensionless shim on Windows.
plugin=node_modules/.bin/protoc-gen-es
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) plugin="$plugin.cmd" ;; esac
protoc --plugin=protoc-gen-es="$plugin" \
  --es_out="$out" --es_opt=target=ts \
  -I vendor/anki/proto vendor/anki/proto/anki/*.proto
