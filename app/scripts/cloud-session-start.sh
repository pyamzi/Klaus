#!/bin/bash
# SessionStart hook: app setup for Claude Code cloud sessions.
# System packages and the Rust toolchain come from the environment's setup script.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
set -euo pipefail
cd "$(dirname "$0")/.."  # app/

git submodule update --init --depth 1 vendor/anki
git -C vendor/anki submodule update --init --depth 1 ftl/core-repo ftl/qt-repo
[ -d node_modules ] || npm ci
