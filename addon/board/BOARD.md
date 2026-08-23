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

### K-007: Reconcile the rest of AGENTS.md with the current module map
owner: -
priority: P3
tags: sonnet-safe
files: AGENTS.md
verify: grep -q 'retention.py' AGENTS.md && grep -q 'pdf_drive.py' AGENTS.md
created: 2026-08-23

Two workers independently flagged this while doing other cards: beyond the privacy line fixed in K-003, AGENTS.md still describes an older architecture — the repo layout, the module list, the 'single active PDF' model, and the dependencies table all predate semantic search, the PDF drive, and multi-PDF tabs.

Done when: the repo layout and module list match what is actually in klausmate/ (including pdf_drive.py, deck_curate.py, drive_store.py, retention.py, curation.py, embeddings.py, card_index.py), the single-PDF section is replaced by the multi-PDF tab model, and nothing in the file contradicts CLAUDE.md.

Scope note: AGENTS.md only. Do not edit CLAUDE.md — it is the authority here, use it as your source.

#### Comments
- [2026-08-23 orchestrator] Groomed twice: my first verify command referenced a phrase that is not in the file, so it passed with zero work. Replaced with a check that pdf_drive.py and retention.py appear in the layout block — they exist in the tree and are absent from the doc, so it fails now and can only pass once the module list is genuinely current.

## Doing

## Review

## Done

### K-003: Fix stale claims in AGENTS.md
owner: sonnet-a
priority: P2
tags: sonnet-safe
files: AGENTS.md
verify: grep -c 'No API keys' AGENTS.md
created: 2026-08-23
claimed: 2026-08-23

AGENTS.md line 5 claims 'all inference runs on-device. No API keys, no cloud calls, no telemetry.' That has been false since Voyage became the default embedding provider and Claude became a selectable Ask engine.

Done when: the privacy claim describes what is actually true (autocomplete and Ask can run locally; semantic search defaults to the Voyage cloud API and card text is sent there; Ollama stays selectable for fully-local operation), and nothing else in the file contradicts CLAUDE.md.

#### Comments
- [2026-08-23 sonnet-a] Decisions: rewrote the line-5 privacy claim rather than the whole file. Verified actual defaults in code before writing: klausmate/embeddings.py has DEFAULT_PROVIDER = "voyage" (semantic search sends card text to Voyage's cloud API by default; switch embedding_provider to ollama for fully local), and klausmate/config.json has klaus_engine: "ollama" (autocomplete + Ask default to local Ollama, Claude API is opt-in and needs a key). New line keeps the literal substring 'No API keys' so the card's verify grep still matches, but now scopes that phrase to the local-only path. Files: AGENTS.md (line 5 only). Risks: the rest of AGENTS.md (module map, single-PDF model section, dependencies table, ollama_client.py/settings_ui.py references) is also stale versus CLAUDE.md's module map — I left it untouched since the card scoped this to the privacy claim and rewriting the whole architecture doc is a much bigger job than this card describes. Next: consider a follow-up card to reconcile the rest of AGENTS.md (repo layout, module list, single-PDF model, semantic search / Claude Ask, config keys) with CLAUDE.md's current module map — none of that was in this card's acceptance criteria.
- [2026-08-23 orchestrator] Reviewed the diff: the new privacy line is accurate against embeddings.py DEFAULT_PROVIDER=voyage and config.json klaus_engine=ollama. Signing off. Separately: this card's verify command was mine and it was broken — grep -c exits 0 when the phrase is present, so it would have passed on the untouched file. Gate fixed as a rule in ROLES.md.

### K-005: README refresh for the PDF drive and deck curation
owner: sonnet-b
priority: P3
tags: sonnet-safe
files: README.md
verify: grep -qi 'pdf drive' README.md
created: 2026-08-23
claimed: 2026-08-23

README documents the Klaus panel and PDF viewer but predates the PDF drive window and the deck-screen Curate Deck button.

Done when: both features are described from the user's side (what they see, where they click), the feature list at the top mentions them, and nothing still implies curation only happens in the side panel.

#### Comments
- [2026-08-23 sonnet-b] Decisions: added two feature-table rows (PDF drive, Curate Deck) plus new Usage subsections '### PDF drive (library)' and '### Curate Deck', placed right after the existing '### Lecture PDF' section. Described both from the user's side (toolbar PDFs link, tree/folders, right-click menu, retention %; deck-list/overview Curate Deck button, drag-to-arm, deck-scope prompt) based on reading klausmate/pdf_drive.py and klausmate/deck_curate.py. Noted the drive window replaced the old Priorities tab and that curation is launchable from both the drive window's context menu and the deck screens, so nothing implies it's side-panel-only (README previously didn't mention curation/Priorities at all, so there was nothing stale to remove). Files: README.md. Risks: none, pure doc addition, no code touched. Next: none for this card; README's Project structure list still doesn't mention pdf_drive.py/deck_curate.py/drive_store.py/retention.py, could be a future doc pass if desired.
- [2026-08-23 orchestrator] Reviewed the diff: both features described from the user's side, feature table updated, no code touched. Signing off.
