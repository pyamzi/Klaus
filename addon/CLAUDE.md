# CLAUDE.md — Addons repo / Klaus (klausmate)

The real project here is **`klausmate/`** — "Klaus", an Anki addon for
semantic deck curation (find cards matching a lecture PDF, copy them into a
new deck), a lecture-PDF library with per-PDF retention scoring, a native
PDF viewer with highlights/sticky notes, and image cropping. Around it:
`tests/` (headless logic tests), `board/` + `context/` (the multi-agent
kanban board — see below), `References/` and `scripts/` (vendored
reference repos + packaging), and `AGENTS.md` (deep architecture guide:
hooks registered, JS↔Python protocol, config keys, packaging).

Klaus is **embeddings-only**: its one AI capability is semantic search,
which defaults to the **Voyage** cloud embedding API (Ollama is an optional
local alternative, OpenAI a second cloud option). Autocomplete, ⌘K Ask, the
Klaus chat panel, the Settings dialog, and the Claude/Anthropic integration
were all deleted in 2026-08 — if you find docs, comments, or instincts that
assume any of those still exist, they're stale. See AGENTS.md's "What used
to be here" for the full list of what was removed.

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/Addons/klausmate/`,
  even though worktrees now contain a copy. Anki loads the addon through a
  symlink to the main checkout only, and the PostToolUse compile hook
  compiles that symlink target — so a worktree edit would report success
  without ever being compiled or loaded.
- Commits and diffs for addon work are now expected.

## The agent board

Multi-session work is coordinated through a kanban board:
`board/BOARD.md` is the source of truth, and **every state change
(claim/move/comment) goes through `python3 board/board.py`** — it
serializes writes behind a lockfile; hand-editing BOARD.md to move a card
will eventually lose a write (card *body* prose may be hand-edited by the
orchestrator/designer only). Claiming enforces file-disjointness against
cards already in Doing, and a card's `verify:` command must fail before
the work and pass after. Roles, columns, and gates: `context/ROLES.md`.
Dashboard: `python3 board/serve.py` → 127.0.0.1:8765 (preview config
"board-dashboard" in `.claude/launch.json`). Signed-off history is in
`board/ARCHIVE.md` — search it (K-0xx) before re-debugging anything.

## How Anki loads the addon

- Symlink: `~/Library/Application Support/Anki2/addons21/klausmate` →
  `/Users/pyamzi/Documents/Github/Addons/klausmate`. If the repo folder is ever
  renamed, this symlink breaks silently and Anki loads nothing.
- **Never create a second copy under `addons21/`** (e.g. a numbered AnkiWeb
  install). Two copies race on the same hooks and `editor._klausmate_*`
  attribute guards make the collision silent. A removed duplicate is backed up
  at `~/Library/Application Support/Anki2/klausmate-duplicate-1402639583.backup`.
- Anki must be **fully restarted** to pick up code changes.

## Anki runtime & testing

- Anki 26.8.1 lives at `/Applications/Anki.app`; its packages are Python
  3.13 **bytecode-only** in `Contents/Resources/app_packages` (no runnable
  python binary — `aqt`/`_aqt` there are `.pyc`, readable only by
  decompiling/`strings`). There is NO venv anywhere. System `python3` is
  3.9.6: it can `py_compile` every addon file (all use
  `from __future__ import annotations`) but **cannot import `aqt`**.
- So headless testing = **stub `aqt`/`anki` in `sys.modules` and test
  logic only, never Qt widgets**. The harness lives in `tests/` (see its
  README) with the bootstrap documented in the `klaus-test` skill — use
  that skill when adding or changing klausmate modules. Run everything:
  `for t in tests/test_*.py; do echo "— $t"; python3 "$t" || break; done`
- Verify syntax **through the symlink**:
  `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`
  (the PostToolUse hook `.claude/hooks/klausmate-compile.sh` does this
  automatically after every klausmate `*.py` edit, and fails loudly if the
  symlink is missing or dangling — that failure means Anki is not loading
  this code; fix the symlink, don't suppress the hook).
- Never point tests at the real `user_files` — use a scratch copy.
  `.claude/settings.json` denies Edit/Write under `user_files/` and
  Read of `meta.json` (API keys).
- Read-only SQL against the live collection works:
  `sqlite3 "file:...collection.anki2?immutable=1"`. FSRS is ON;
  `cards.data` JSON carries `{"s","d","dr","decay","lrt"}`.

## Module map

- `__init__.py`: bootstrap + gui_hooks; JS bridge
  (`pycmd("klausmate:<action>:<b64 json>")` routed in `on_js_message`, which
  splits `":", 2` — only `focus`/`crop`/`log`/`dbg` actions remain, the
  `complete`/`ask` actions are gone with autocomplete/Ask); `_PdfTabContainer`
  (tabbed PDF panel + window management: embed above/below/left/right of the
  editor pane via a QSplitter wrapper, or float as a parentless real window;
  native drag via `startSystemMove` with a watchdog + ghost fallback);
  image-crop plumbing; Tools → Klaus menu (`install_menu`: Clear library tag,
  Manage models…, Test connection).
- `browse_toggles.py`: Browse toolbar toggles (◧ sidebar / ◨ editor column),
  split out of `__init__.py`.
- `pdf_viewer.py`: `PdfViewer` (QPdfView + selection/marquee/highlight
  overlay, find bar, thumbnails, zoom/nav, per-gesture eventFilter) and
  `PdfSidebar` (one instance reused across tabs). No toolbar "Copy page"
  button — Cmd/Ctrl-double-click a page, or right-click "Copy slide as
  image", copies it as an image; right-click also offers "Copy page text".
- `pdf_handler.py`: storage + text extraction. `user_files/{contexts,pdfs,
  pdf_originals,annotations}`, state in `pdf_tabs.json` (open tabs, placement,
  thumbs, last_used — all writers MERGE via `_save_tabs_file`). Since K-070/
  K-073 the PDF *files* live in a user-chosen **library root** (config key
  `library_root`, picked at setup or in Preferences): `library_map.json`
  maps safe basename → path relative to that root, and **`pdf_path_for` is
  the single resolution choke point** (mapped location first, legacy
  `pdfs/<safe>.pdf` fallback; tests pass `root=` explicitly to stay
  aqt-free). No retrieval consumer remains here (autocomplete/Ask, the only
  callers of its old BM25 search, are gone) — `_chunk_text` now only feeds
  the semantic-curation pipeline (`curation.py`, `pdf_index.py`).
  `bake_annotations(dir, name)` writes highlights/notes into the stored
  PDF as REAL annotations
  (vendored pypdf): pristine original captured once in `pdf_originals/`,
  every bake regenerates from pristine + full json (never incremental; empty
  json = un-bake/restore), atomic `os.replace` (safe under the viewer's open
  QPdfDocument inode). Scheduled from `pdf_viewer._save_annotations` via a
  1200ms debounce → daemon thread.
- `pdf_drive.py`: the **Library** window (renamed from "PDF drive" in the
  UI; file/class names still say drive) — folder tree (`drive_store.py`,
  `user_files/drive.json`) next to a standalone `PdfSidebar`. Since K-073
  the tree is **mirrored two-way with real folders under the library
  root** (single-copy invariant: one file per PDF, living in the root;
  `rescan_library_root` + a debounced filesystem watcher pick up outside
  edits) — `drive_store.py` itself stays a pure aqt-free presentation
  join; the disk sync lives here and in `pdf_handler`. Top-toolbar link
  labeled "Library" (`gui_hooks.top_toolbar_did_init_links`). Right-click
  per row: open, rename, move to folder, re-embed, adjust match
  sensitivity, show matches in Browse, curate deck from this PDF, delete.
- `tag_sync.py`: per-PDF collection tags. THE INVARIANT: every indexed PDF
  owns exactly one tag `!Library::<folder path, / → ::>::<leaf>` (leaf =
  display name minus extension, tag-sanitized), whose members are exactly
  the notes at/above that PDF's sensitivity threshold. Forward direction
  (index/re-index creates + renames tags, K-053) and reverse (a rename in
  Anki's tag sidebar renames the PDF, K-054 — INFERENCE from a
  before/after tag diff on profile open, never a real event). Reserved
  leaves `Curating`/`Curated`/`Matching` are never touched.
- `retention.py`: per-PDF retention/study-priority score shown in the
  Library — embed the PDF's chunks (`pdf_index.py`) → score every indexed
  note against them (max cosine, cached in `matches.json`) → pull FSRS
  retrievability for matched cards → aggregate. The old
  `!Library::Matching` preview tag was retired in K-055 — "Show matches
  in Browse" now hops to the per-PDF `tag_sync` tag.
- `projection.py` (aqt-free, pure stdlib): top-2 PCA by power iteration +
  deflation over one packed `array('d')` buffer (`math.sumprod` on
  memoryview slices, strided slices for the transpose — never the d×d
  covariance matrix). Numeric foundation for the embedding map (Phase D).
- `pdf_graph.py` (aqt-free at module top): assembles the embedding-map
  graph dict — PDF nodes at their matched notes' 2D centroid, edges to
  every note at/above threshold. `retention` (which imports aqt) is
  imported lazily inside `build_graph_data`. No window/canvas yet.
- `pdf_index.py` (aqt-free): persistent embedding index over one PDF's text
  chunks, `card_index.py`'s sibling for the PDF side.
- `crop_dialog.py`: image-crop dialog (crop saved as NEW media file).
- `web/copilot.js`: injected into editor webviews; shadow-DOM-aware
  (`composedPath`). Ghost text and Ask are gone — this file now only tracks
  field focus (for PDF page-insert targeting) and the image-crop dblclick
  trigger.
- **Semantic curation stack** (Curate Deck + the Library's retention score;
  this is the only AI-powered feature left):
  - `embeddings.py` (aqt-free): provider abstraction — Voyage
    (default, `voyage-3-lite`), with Ollama `/api/embed` (`nomic-embed-text`)
    and OpenAI (`text-embedding-3-small`) as alternatives. `OPENAI_API_BASE`/
    `VOYAGE_API_BASE` module globals exist for test monkeypatching. Vectors
    are **unit-normalized at write time**.
  - `card_index.py` (aqt-free): `user_files/card_index/` = packed
    `array('f')` vectors + JSON manifest. **Text hash is the change
    detector; `note.mod` only a pre-filter** — the Browse-preview tag bumps
    mod without changing text. A row's (mod, hash) advances only together
    with its vector → cancelled indexing resumes for free. Manifest is
    written AFTER vectors (size mismatch on load ⇒ rebuild). `top_k` =
    `math.sumprod` over memoryview rows (C-speed; **no numpy in Anki's
    bundled Python**) — 30k×768 ranks in ~0.25 s.
  - `curation.py` (aqt glue): two-phase `ensure_index` (snapshot with col
    via `select id, mod, flds from notes` + `flds.split("\x1f")`; embed
    without col, partial save every ~1k vectors), `run_curation`, preview
    via temp tag `!Library::Curating` (+ `Browser.search_for`; `nid:` lists
    break at thousands of ids), undoable deck copy (`add_custom_undo_entry`
    → `col.add_notes` → `merge_undo_entries`) tagged `!Library::Curated`.
    Curation is always PDF-driven now — `run_curation`'s free-text `prompt`
    param has no caller since the chat panel that used to fill it in was
    deleted.
  - `deck_curate.py`: "Curate Deck" button + PDF drop/arm on the deck list
    and deck overview screens; calls into `curation.py` via
    `run_curation_flow(pdf_name, deck_scope)`.
  - `tag_migrate.py`: one-time `klaus::*` → `!Library::*` collection tag
    rename on `profile_did_open`, guarded idempotent (only proposes a rename
    when the old tag still exists), returns `col.merge_undo_entries(pos)`
    (a plain list return here crashed every profile open — `on_op_finished`
    reads `.changes` off a `CollectionOp`'s result).
  - `manage_models.py`: the "Manage models" dialog (`manage_models_dialog`,
    also first-run setup) — three sections: **Semantic search** (embedding
    provider/key/model — `_resolve_ollama_model()` guards against silently
    orphaning an existing index when the ollama model config is empty),
    **Local model library (Ollama)** (pull/delete embedding models only —
    `_EMBED_PRESETS`: nomic-embed-text, snowflake-arctic-embed,
    mxbai-embed-large, embeddinggemma), **General** (`image_crop_enabled`,
    `runtime_auto_setup` toggles — no other UI touches either key).
  - `setup_flow.py`: first-run "Welcome to Klaus" dialog + per-profile-open
    readiness checks, gated on `embeddings.provider_name(cfg)` — a
    Voyage/OpenAI profile never sees Ollama-flavored copy or probes.
  - `ollama_client.py`: stdlib HTTP client — `/api/embed`, pull, delete.
    **No text-generation method** (stripped when autocomplete/Ask were
    removed).
  - `ollama_runtime.py`/`ollama_setup.py`: managed Ollama provisioning.
    **Never kill a user-owned Ollama** — only servers Klaus spawned
    (pidfile + process-identity verify). No UI control removes a
    Klaus-managed install; reclaiming that disk space is a manual delete of
    `user_files/runtime/` (after switching off "Manage Ollama automatically"
    in Manage models → General so it doesn't just come back).
- Deleted (2026-08, do not resurrect the language): `claude_api.py`,
  `anki_tools.py`, `settings_ui.py`, `chat_dock.py` (the "Klaus panel"),
  `web/search.html|css|js`; also `single_window.py` (2026-08-25 — the
  panes-in-one-window mode from K-059..K-062 was removed as too buggy:
  dark webview panes survived five rework rounds, K-090..K-094. Anki is
  stock multi-window again; `_migrate_config` scrubs the
  `single_window_mode` key). Config lives in `klausmate/config.json` +
  Anki's addon config (`meta.json`) + `config.md`. `_migrate_config()`
  (profile_did_open) cleans up legacy `chat_*`/`claude_*` keys left from the
  deleted Claude-Ask feature; keep it until users have upgraded past it.

## Hard-won gotchas (each cost real debugging — don't relearn them)

- **pdfium hit tolerance**: `QPdfDocument.getSelection()` silently returns an
  INVALID selection if an endpoint is >~7pt from a glyph, or if both endpoints
  hit the same character. Never anchor at page corners/edges — use
  `getAllText` / `getSelectionAtIndex` (index space) or the probe helpers
  (`_probe_selection_at`, `_snap_to_char`).
- **Host-window shortcut ambiguity**: widget-scoped QShortcuts that collide
  with Browse/AddCards QActions (⌘F, ⌘G, ⌘⌥G, ⇧⌘G, ⇧⌘H) become *dead keys*.
  The viewer claims them via `QEvent.ShortcutOverride` + KeyPress handling.
- **Reparenting mid-mouse-gesture kills Cocoa tracking** — never
  `setParent` into a new native window while a button is down. Tear-off =
  float on threshold + `startSystemMove()` (which *lies* — returns True even
  when the drag dies; a 300ms/40px watchdog detects that and falls back).
- **`QSplitter.setOrientation` transposes its sizePolicy** — re-assert the
  wrapped pane's policy after every orientation change or the host layout's
  stretch hints are lost (blank-space bug in the Add window).
- **One `QPdfDocument` is reused across tabs** — cache by
  `_doc_generation` (bumped in `set_document`), never `id(doc)`.
- **Anki stores DECODED filenames in note fields** (`reverse_url_quoting` on
  save) and entity-escapes attribute values — `_replace_img_src` matches raw,
  percent-decoded, and html-unescaped forms.
- Safe note mutation from Python:
  `editor.call_after_note_saved(cb, keepFocus=True)` → mutate
  `note.fields` → `_save_current_note()` (non-addMode) →
  `loadNoteKeepingFocus()`.
- `gui_hooks.editor_did_focus_field` signature is `(note, field_idx)` — it
  does NOT provide the editor; focus tracking rides the JS bridge instead.
- Browse `gridLayout` cell (0,0) is occupied at runtime by Anki's Cards/Notes
  switch (added in `Browser.setup_table`), not empty as the form suggests.
- Generated `_qt6.py` forms show the `setupUi` state only — Anki mutates
  layouts afterwards; grep `aqt/` before trusting a form.
- **pdfium renders annotations only WITH `RenderFlag.Annotations`** — the
  viewer and image copies render without it, so baked-in highlights never
  double-draw under the screen overlay. The coordinate flip is
  `y_pdf = page_mediabox_height − (y_qt + h)` (verified pixel-exact).
- **Selection-path perf caches** (pdf_viewer): `_page_geoms_cache` keyed
  (doc generation, viewport width, zoom mode, zoom factor, vsb.max);
  `_alltext_bounds_cache` keyed (generation, page); `_probe_selection_at`
  has a `fast=True` mode for per-mouse-move callers. Rewiring selection
  code must respect these or drag/scroll jank returns.

## Conventions

- Defensive `try/except` around every Qt call; guarded imports with `None`
  fallbacks (`PDF_VIEWER_AVAILABLE` pattern); log with
  `print("[klausmate] ...")`; tooltips only for capture-style actions
  (selection/copy is silent, Preview-style).
- pypdf is vendored in `klausmate/vendor/` (6.11.0, has
  `pypdf.annotations`); no other third-party deps, no native code.
- Ollama embedding-model presets live in `_EMBED_PRESETS`
  (`manage_models.py`) — there is no text-generation model list anymore
  (autocomplete/Ask are gone), and no first-run auto-pull; the user picks a
  provider/model explicitly.
