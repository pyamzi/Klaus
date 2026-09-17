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

### KB-014: Find bar (Cmd+F) in the PDF editor
owner: -
priority: P2
tags: parity
created: 2026-09-17

Top strip per parity spec: input 'Find in PDF...', count label formats, prev/next/close, 250ms debounce, Cmd+G / Cmd+Shift+G cycling (silent no-op while hidden), hide+clear on document change. Search over pdf.js text content.

### KB-015: Sticky notes on highlights
owner: -
priority: P3
tags: parity
created: 2026-09-17

Per-highlight notes per parity spec: Add note.../Edit note... via context menu, box anchored top-right of first rect, rgba(255,245,170,235) fill, 1px rgb(190,170,80) border, rgb(70,60,20) 10px text, <=180px wide, <=4 lines, radius 3. Distinct from the per-slide notes sidebar.

### KB-016: Shortcut + toast parity in the PDF editor
owner: -
priority: P2
tags: parity,sonnet-safe
created: 2026-09-17

Per parity spec: Cmd+= / Cmd+- (x1.25, clamp 0.25-5), Cmd+0 fit, Cmd+A select page text, Cmd+Alt+G go-to-page, PageUp/Down + Home/End (exists), double/triple-click selection, and a transient 'Klaus: ...' toast component for all feedback (no modals).

## Ready

## Doing

## Review

## Done
