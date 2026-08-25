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

## Ready

## Doing

## Review

## Done
