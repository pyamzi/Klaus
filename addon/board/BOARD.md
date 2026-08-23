# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### K-001: Manual-verify PDF drive and deck-curate surfaces in live Anki
owner: -
priority: P1
tags: needs-human
verify: human confirms each checklist item in Anki
created: 2026-08-23

Only a human can do this: it needs a running Anki with a real collection.

Checklist:
- Toolbar shows the PDFs link; it opens the drive window and re-raises on second click.
- Drive tree lists imported PDFs; folder create/move/rename and display-rename survive a restart.
- Double-click opens a PDF in the right pane with annotations intact.
- Retention columns populate; Embed runs with progress and can be cancelled; the threshold slider re-aggregates live.
- Deck browser shows the Curate Deck button; dropping a PDF imports and arms it without Anki's own importer opening.
- Curate at root offers the all-decks/specific chooser; inside a deck it scopes silently.

Report failures as new cards rather than fixing them here.

### K-002: Visual polish pass: Manage models dialog and Klaus panel
owner: -
priority: P2
tags: design
files: klausmate/web/search.css,klausmate/web/search.html
verify: designer sign-off; screenshots attached to this card
created: 2026-08-23

Needs a design spec before any code. The Manage models dialog was reorganised by job (What Klaus uses / Local model library) but never got a visual pass. The Klaus panel still uses Bootstrap-era defaults.

Designer: write the spec into this card, then move it to Ready. Do not hand this to a worker un-specced.

### K-006: Slice klausmate/__init__.py into modules
owner: -
priority: P3
tags: sonnet-safe,large
files: klausmate/__init__.py
verify: python3 -m py_compile via the symlink, then the full suite
created: 2026-08-23

5,980 lines in one file. Too large for one card — the orchestrator must slice it into file-disjoint pieces first, or every worker collides on the same path.

Blocked on grooming, not on skill. Candidate seams: the Manage models dialog (~1000 lines), the editor panel and PDF bar, the Browse toolbar toggles, hook registration and bootstrap.

## Ready

### K-005: README refresh for the PDF drive and deck curation
owner: -
priority: P3
tags: sonnet-safe
files: README.md
verify: grep -qi 'pdf drive' README.md
created: 2026-08-23

README documents the Klaus panel and PDF viewer but predates the PDF drive window and the deck-screen Curate Deck button.

Done when: both features are described from the user's side (what they see, where they click), the feature list at the top mentions them, and nothing still implies curation only happens in the side panel.

### K-003: Fix stale claims in AGENTS.md
owner: -
priority: P2
tags: sonnet-safe
files: AGENTS.md
verify: grep -c 'No API keys' AGENTS.md
created: 2026-08-23

AGENTS.md line 5 claims 'all inference runs on-device. No API keys, no cloud calls, no telemetry.' That has been false since Voyage became the default embedding provider and Claude became a selectable Ask engine.

Done when: the privacy claim describes what is actually true (autocomplete and Ask can run locally; semantic search defaults to the Voyage cloud API and card text is sent there; Ollama stays selectable for fully-local operation), and nothing else in the file contradicts CLAUDE.md.

### K-004: Edge-case coverage for drive_store and deck_curate
owner: -
priority: P2
tags: sonnet-safe
files: tests/test_drive.py
verify: python3 tests/test_drive.py
created: 2026-08-23

Extend the existing suite. Gaps worth covering: a folder rename that collides with an existing folder; two PDFs whose safe-names collide; drive.json holding a folder no card references; deck_curate recency ordering when last_used is missing for some PDFs.

Done when: new assertions cover each gap, the suite still passes, and no production module changed — this card owns only the test file.

#### Comments
- [2026-08-23 sonnet-1] Started; reading the existing suite to find the gaps.

## Doing

## Review

## Done
