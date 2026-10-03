#!/bin/sh
# Vendor rough.js for the hand-drawn PDF reader
# (docs/superpowers/specs/2026-10-01-hand-drawn-reader-design.md).
# Pinned: re-run only to upgrade, then re-run the reader tests.
set -eu
VERSION="roughjs@4.6.6"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
npm pack "$VERSION" >/dev/null
tar -xzf roughjs-*.tgz
cp package/bundled/rough.js "$HERE/klaus_note/web/rough.min.js"
cp package/LICENSE "$HERE/klaus_note/web/LICENSE-roughjs.txt"
echo "vendored $VERSION"
