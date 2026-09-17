# klausbook board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->

## Backlog

### KB-001: Bundle klaus-pdf as a built-in extension
owner: -
priority: P1
tags: fork
created: 2026-08-24

Launch Klausbook without --extensionDevelopmentPath: wire extensions/klaus-pdf into the fork's dev/build extension set so it loads like a shipped extension. Keep the fork patch minimal.

### KB-002: Port klausmate annotation model: JSON source of truth + bake
owner: -
priority: P1
created: 2026-08-24

Highlights + per-slide side notes stored as JSON sidecars in Klausbook's own user_data; bake writes them into the PDF as real annotations from a pristine original (klausmate pdf_handler.bake_annotations model, vendored pypdf). Never incremental; empty JSON = restore.

### KB-003: Viewer: text selection -> highlight + side-note UI
owner: -
priority: P1
tags: design
created: 2026-08-24

Needs a spec first: selection affordance, highlight palette, per-slide note column, states, theme behavior.

#### Comments
- [2026-09-17 orchestrator] Spec landed: docs/reference/klausmate-viewer-parity.md (full inventory of klausmate's viewer with exact colors/strings/shortcuts). This card's scope is now the highlight flow: selection -> Cmd+Shift+H / context-menu Highlight, five inks (#FADC50 default, #8AE08C, #7FC6F2, #F79AC8, #F7B267) at 43% alpha, one record per page, stored in the klaus-core notes doc. Sliced follow-ups: KB-013 context menu, KB-014 find bar, KB-015 sticky notes, KB-016 shortcuts+toasts.

### KB-004: klaus-core: embedding index over the library
owner: -
priority: P2
created: 2026-08-24

Port embeddings.py + pdf_index.py (aqt-free already): Voyage default, unit-normalized vectors, packed array storage. Expose /search over chunks of all PDFs.

### KB-005: Anki bridge: slim klausmate addon serving HTTP
owner: -
priority: P2
created: 2026-08-24

Endpoints Klausbook needs from a running Anki: FSRS retrievability per card, batch note snapshots (id, mod, flds), undoable deck copy. Evolved from klausmate, not AnkiConnect.

### KB-006: Retention scores in the Library view
owner: -
priority: P2
created: 2026-08-24

Per-PDF retention/study-priority in the tree view (description text), klausmate retention.py model: max-cosine card matches x FSRS retrievability via the bridge.

### KB-007: Chat assistant in klaus-core
owner: -
priority: P2
created: 2026-08-24

Agent endpoint with tools: search_library, read_page (image+text+notes), get_retention, show_html. Multimodal model (Claude default) answers questions about PDF images without OCR. UI panel card follows separately.

### KB-008: Notes: Markdown folder + PDF deep links
owner: -
priority: P2
created: 2026-08-24

User-owned notes folder (plain .md, native VS Code editing) with links to PDF page/region that open the viewer at that spot.

### KB-009: Retention-driven podcast pipeline
owner: -
priority: P3
created: 2026-08-24

Async job in core: select what you're about to forget (FSRS via bridge) -> script -> TTS, provider-pluggable like embeddings. The signature feature; needs bridge + retention first.

### KB-010: Packaging: product build + core sidecar
owner: -
priority: P3
created: 2026-08-24

Signed app build of the fork; klaus-core bundled via PyInstaller and supervised by the app; port 7863 token hardening.

### KB-011: Theme PDF viewer with --vscode-* variables
owner: -
priority: P3
tags: sonnet-safe
created: 2026-08-24

viewer.css uses a fixed dark palette; key it off --vscode-editor-background/-foreground etc. so all themes work.

#### Comments
- [2026-09-17 orchestrator] Direction change (2026-09-17): the design north star for BOTH KlausBook and klausmate is Obsidian (dark-first, sidebar-driven, one accent family) — not the Quiet Clinic palette. First pass landed on the impress-editor branch: viewer.css now ships Obsidian dark+light tokens keyed off vscode-light. Remaining scope of this card: bind to --vscode-* variables / user themes where sensible.

### KB-012: klausmate: re-skin library + viewer to the Obsidian look
owner: -
priority: P2
tags: design,needs-human
created: 2026-09-17

Pouya wants klausmate (inside Anki) and KlausBook to look almost identical, with Obsidian as the shared north star (dark-first, sidebar file-tree feel, quiet chrome, one accent family). klausmate's Quiet Clinic palette (KlausMate-Context/DESIGN.md) keeps its token discipline but the palette direction is superseded. This is addon-side work in the klausmate repo: theme.py palette swap + DESIGN.md rewrite + test_theme.py scale updates. Coordinate tokens with KlausBook's extensions/klaus-pdf/webview-src/viewer.css so the two stay in lockstep.

### KB-013: Context menu parity in the PDF editor
owner: -
priority: P2
tags: parity
created: 2026-09-17

Custom context menu per docs/reference/klausmate-viewer-parity.md: Copy / Copy Selection as Image / Highlight / note items / Remove Highlight / Copy Page Text / Copy Slide as Image / separator / Zoom In-Out-Actual with key hints. Items disable rather than hide; floats on the sanctioned 16px shadow.

### KB-015: Sticky notes on highlights
owner: -
priority: P3
tags: parity
created: 2026-09-17

Per-highlight notes per parity spec: Add note.../Edit note... via context menu, box anchored top-right of first rect, rgba(255,245,170,235) fill, 1px rgb(190,170,80) border, rgb(70,60,20) 10px text, <=180px wide, <=4 lines, radius 3. Distinct from the per-slide notes sidebar.

### KB-017: Fix stale repo paths (library default + README run commands)
owner: -
priority: P1
tags: sonnet-safe
created: 2026-09-17

The session fixing these was deleted before landing. (1) core/klaus_core/library.py DEFAULT_USER_FILES still points at ~/Documents/Github/Addons/klausmate/user_files which no longer exists — the real library is ~/Documents/Github/KlausMate-Context/klausmate/user_files ({pdfs,pdf_originals}); without KLAUS_LIBRARY_DIR the app lists an empty library. (2) README.md Run/Architecture sections still say klausbook-code / ../klausbook — should be KlausBook-Code / KlausBook-Context. Also sweep context/PROJECT.md and context/prompts/*.md for the same stale paths. Verify: curl -s -H 'X-Klaus-Token: dev' localhost:7863/library lists 5 PDFs with no env override; python3 tests/test_notes.py passes.

#### Comments
- [2026-09-17 orchestrator] Same rename fallout hit core/.venv: script shebangs pointed at the old klausbook/ path (bad interpreter). Rebuilt 2026-09-17; card's README sweep should add a note that any repo rename requires rm -rf core/.venv + recreate.

## Ready

## Doing

## Review

### KB-016: Shortcut + toast parity in the PDF editor
owner: orchestrator
priority: P2
tags: parity,sonnet-safe
files: extensions/klaus-pdf/webview-src/shortcuts.ts,extensions/klaus-pdf/webview-src/toast.ts,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/viewer.css,tests/shortcuts_test.mjs
verify: node --test tests/shortcuts_test.mjs && cd extensions/klaus-pdf && npm run typecheck
created: 2026-09-17
claimed: 2026-09-17

Per docs/reference/klausmate-viewer-parity.md, bring the editor's keyboard and feedback behavior up to klausmate's.

Behavior:
- Cmd/Ctrl+= and Cmd/Ctrl++ zoom in x1.25, Cmd/Ctrl+- zooms out /1.25, clamped 0.25-5.0. The toolbar buttons use the same step and clamp (today they are x1.2 / 0.1-6).
- Cmd/Ctrl+0 fits the slide to the stage.
- Cmd/Ctrl+A selects the current slide's text layer; with no text on the page, toast "Klaus: no selectable text on this page" and change nothing.
- Cmd/Ctrl+Alt+G focuses an inline page field in the toolbar; the page label is click-to-edit too. Out-of-range or non-numeric input is refused with a toast and leaves the slide unchanged. No native dialog: a webview has no prompt(), and the voice rule forbids modals.
- PageUp/PageDown/Home/End keep working; nothing above fires while focus is in the notes textarea or the page field.
- Double-click selects a word, triple-click a paragraph, on the slide text layer.
- Every piece of feedback goes through one transient toast, each message prefixed "Klaus: ", auto-dismissed, never a modal and never inline text.

Acceptance criteria:
- Shortcut matching, the zoom ladder and page-number parsing live in a pure module with no React/DOM imports, so the gate needs no browser.
- tests/shortcuts_test.mjs asserts: the zoom step is exactly 1.25 and clamps at 0.25 and 5.0 from both directions; each shortcut in the table maps to its action for both Cmd and Ctrl; a plain key or a typing target yields no action; page parsing rejects "", "abc", "0" and n+1 while accepting "1" and n.
- npm run typecheck in extensions/klaus-pdf is clean.
- The verify command fails on the pre-card tree (the module and test do not exist) and passes after.

#### Comments
- [2026-09-17 orchestrator] Implemented on branch kb-016-shortcuts (b5212f5, branched off impress-editor so it carries the unmerged Obsidian retheme dbc6544). verify exits 0 (5 node:test cases + tsc --noEmit); it exited 1 on the pre-card tree. node build.mjs bundles clean. Divergence from the card, deliberate: Cmd+Alt+G focuses an inline page field in the toolbar instead of klausmate's getInt dialog - a webview has no prompt() and the voice rule forbids modals; the page indicator became the field, format '{n} / {total}' kept. Double/triple-click selection is native pdf.js text-layer behaviour and nothing in viewer.css blocks it - not machine-verified. NEEDS A REAL-WINDOW CHECK before Done: VS Code binds Cmd+= / Cmd+- / Cmd+0 at the workbench level, so confirm the webview's preventDefault wins and the shell does not also zoom.
- [2026-09-17 orchestrator] PR #2 open: https://github.com/pyamzi/KlausBook-Context/pull/2 (1 commit, based on the merged retheme). Stays in Review until the real-window shortcut check.

### KB-014: Find bar (Cmd+F) in the PDF editor
owner: orchestrator
priority: P2
tags: parity
files: extensions/klaus-pdf/webview-src/find.ts,extensions/klaus-pdf/webview-src/FindBar.tsx,extensions/klaus-pdf/webview-src/shortcuts.ts,extensions/klaus-pdf/webview-src/ImpressView.tsx,extensions/klaus-pdf/webview-src/viewer.css,tests/find_test.mjs,tests/shortcuts_test.mjs
verify: node --test tests/find_test.mjs tests/shortcuts_test.mjs && cd extensions/klaus-pdf && npm run typecheck
created: 2026-09-17
claimed: 2026-09-17

Top strip in the PDF editor per docs/reference/klausmate-viewer-parity.md, "Find bar".

Behavior:
- Cmd/Ctrl+F reveals the bar, focuses the input and selects what is in it. Esc hides it, clears the search and returns focus to the slide.
- Input placeholder "Find in PDF…" with a clear button. Live search debounced 250ms.
- Count label is exactly one of: "" (empty query) / "0 matches" / "{i+1} of {count}" / "{count} matches" (a query with matches but no current one).
- Prev (‹, Shift+Enter) and next (›, Enter) cycle with wraparound. Cmd/Ctrl+G and Cmd/Ctrl+Shift+G do the same from anywhere, and are a silent no-op while the bar is hidden.
- Search spans the whole document over pdf.js text content, not just the visible slide; selecting a match navigates to its page.
- The current match is highlighted in the slide's text layer via the CSS Custom Highlight API - no DOM mutation - and degrades to plain navigation where unsupported, per the repo's None-guard house style.
- The bar hides and clears when the document changes.

Note: this card extends shortcuts.ts, which KB-016 owns and which is in Review. Cmd+Shift+G currently asserts as "no action" in tests/shortcuts_test.mjs; this card flips that assertion to "find-prev" and must keep the rest of that gate green. Branch from kb-016-shortcuts (PR #2) so the two do not conflict.

Acceptance criteria:
- Match finding, count-label formatting and index cycling live in a pure module (no React, no DOM), so the gate needs no browser.
- tests/find_test.mjs asserts: case-insensitive matching with per-page positions over a fake two-page document; overlapping-candidate and zero-match queries; the four count-label forms verbatim; cycling next/prev wraps at both ends; an empty or whitespace query yields no matches and the empty label.
- tests/shortcuts_test.mjs still passes with find shortcuts added, and Cmd+Shift+H stays unclaimed for KB-003.
- npm run typecheck in extensions/klaus-pdf is clean.

#### Comments
- [2026-09-17 orchestrator] Implemented on kb-014-find-bar (7d87e12), PR #3 stacked on PR #2 (it extends shortcuts.ts and updates KB-016's gate; retarget to main once #2 lands). verify exits 0 (9 node:test cases + tsc), exited 1 before. Two deliberate calls, both narrower than the card: (1) a fresh query selects no match - the label reads '{n} matches' until Enter/Cmd+G moves to one, so live typing never yanks the stage, and all four label forms stay reachable; (2) the current match is shown by selecting its range in the text layer (which already tints ::selection) rather than via the CSS Custom Highlight API - no new API, no extra CSS, and it degrades to plain navigation when offsets do not map. NEEDS A REAL-WINDOW CHECK: whether VS Code passes Cmd+F to the webview instead of opening its own find widget; also the 250ms debounce and the offset mapping onto the rendered text layer.

## Done
