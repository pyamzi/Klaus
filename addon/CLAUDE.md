# CLAUDE.md — Addons repo / Klaus (klausmate)

The real project here is **`klausmate/`** — "Klaus", a local-AI Anki addon
(autocomplete, ⌘K Ask on either a local Ollama model or the Claude API,
semantic deck curation, PDF viewer, image cropping). The rest of this repo
is dotfiles.

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/Addons/klausmate/`,
  even though worktrees now contain a copy. Anki loads the addon through a
  symlink to the main checkout only, and the PostToolUse compile hook
  compiles that symlink target — so a worktree edit would report success
  without ever being compiled or loaded.
- Commits and diffs for addon work are now expected.

## How Anki loads the addon

- Symlink: `~/Library/Application Support/Anki2/addons21/klausmate` →
  `/Users/pyamzi/Documents/Github/Addons/klausmate`. If the repo folder is ever
  renamed, this symlink breaks silently and Anki loads nothing.
- **Never create a second copy under `addons21/`** (e.g. a numbered AnkiWeb
  install). Two copies race on the same hooks and `editor._klausmate_*`
  attribute guards make the collision silent. A removed duplicate is backed up
  at `~/Library/Application Support/Anki2/klausmate-duplicate-1402639583.backup`.
- Anki must be **fully restarted** to pick up code changes.

## Anki runtime (for reference & testing)

- Anki app is a launcher; the real Python env:
  `~/Library/Application Support/AnkiProgramFiles/.venv/` (Python 3.13,
  PyQt6/Qt 6.9). Anki's own source (read-only reference):
  `.../site-packages/aqt/`, generated UI forms in `.../site-packages/_aqt/forms/`.
- Verify syntax **through the symlink**:
  `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`
- **Offscreen runtime testing works** and has caught real bugs:
  `env QT_QPA_PLATFORM=offscreen "$VENV/bin/python3" script.py`, importing
  `pdf_viewer.py` via importlib under a synthetic `klausmate` package
  (sys.modules stub exposing `USER_FILES` + `pdf_handler`) with a
  `SimpleNamespace` editor stub. Real test PDF:
  `klausmate/user_files/pdfs/Bootcamp.com_Biostatistics.pdf`. Never point
  tests at the real `user_files` — use a scratch copy.

## Module map

- `__init__.py` (~5k lines): bootstrap + gui_hooks; JS bridge
  (`pycmd("klausmate:<action>:<b64 json>")` routed in `on_js_message`, which
  splits `":", 2`); `_PdfTabContainer` (tabbed PDF panel + window management:
  embed above/below/left/right of the editor pane via a QSplitter wrapper, or
  float as a parentless real window; native drag via `startSystemMove` with a
  watchdog + ghost fallback); image-crop plumbing; Browse toolbar toggles
  (◧ sidebar / ◨ editor column).
- `pdf_viewer.py`: `PdfViewer` (QPdfView + selection/marquee/highlight
  overlay, find bar, thumbnails, zoom/nav, per-gesture eventFilter) and
  `PdfSidebar` (one instance reused across tabs).
- `pdf_handler.py`: storage + retrieval. `user_files/{contexts,pdfs,
  pdf_originals,annotations}`, state in `pdf_tabs.json` (open tabs, placement,
  thumbs, last_used — all writers MERGE via `_save_tabs_file`). BM25 retrieval
  for autocomplete/Ask grounding. `bake_annotations(dir, name)` writes
  highlights/notes into `pdfs/<base>.pdf` as REAL annotations (vendored
  pypdf): pristine original captured once in `pdf_originals/`, every bake
  regenerates from pristine + full json (never incremental; empty json =
  un-bake/restore), atomic `os.replace` (safe under the viewer's open
  QPdfDocument inode). Scheduled from `pdf_viewer._save_annotations` via a
  1200ms debounce → daemon thread.
- `crop_dialog.py`: image-crop dialog (crop saved as NEW media file).
- `web/copilot.js`: injected into editor webviews; shadow-DOM-aware
  (`composedPath`); ghost text, focus tracking, crop dblclick.
- **Semantic curation stack** (replaced the old Klaus chat in 2026-07):
  - `embeddings.py` (aqt-free): provider abstraction — Ollama `/api/embed`
    (default, `nomic-embed-text`), OpenAI, Voyage. `OPENAI_API_BASE`/
    `VOYAGE_API_BASE` module globals exist for test monkeypatching.
    Vectors are **unit-normalized at write time**.
  - `card_index.py` (aqt-free): `user_files/card_index/` = packed
    `array('f')` vectors + JSON manifest. **Text hash is the change
    detector; `note.mod` only a pre-filter** — the Browse-preview tag bumps
    mod without changing text. A row's (mod, hash) advances only together
    with its vector → cancelled indexing resumes for free. Manifest is
    written AFTER vectors (size mismatch on load ⇒ rebuild). `top_k` =
    `math.sumprod` over memoryview rows (C-speed; **no numpy in Anki's
    venv**) — 30k×768 ranks in ~0.25 s.
  - `curation.py` (aqt glue): two-phase `ensure_index` (snapshot with col
    via `select id, mod, flds from notes` + `flds.split("\x1f")`; embed
    without col, partial save every ~1k vectors), `run_curation`, preview
    via temp tag `klaus::curate` (+ `Browser.search_for`; `nid:` lists
    break at thousands of ids), undoable deck copy (`add_custom_undo_entry`
    → `col.add_notes` → `merge_undo_entries`).
  - `chat_dock.py`: the Klaus panel controller (name kept so the
    `klausmateChatDock` objectName preserves saved dock geometry). Hosts
    `web/search.html|css|js`, bridge prefix `klaus:`, `window.klausSearch`.
  - `claude_api.py` (aqt-free): stdlib SSE client for the Anthropic
    Messages API (the official SDK needs compiled pydantic-core — banned).
    Powers the ⌘K Claude brain (`klaus_engine`/`claude_api_key` config).
  - `anki_tools.py`: **inert** collection tools (kept, tested) for a future
    agent surface.
  - `ollama_runtime.py`/`ollama_setup.py`: managed Ollama provisioning.
    **Never kill a user-owned Ollama** — only servers Klaus spawned
    (pidfile + process-identity verify).
- Config lives in Anki's addon config (`meta.json`) + `config.md`;
  `browser_dock_enabled` is a dead legacy key. `_migrate_config()`
  (profile_did_open) renames legacy `chat_*` keys → `klaus_engine`/
  `claude_*`; keep it until users have upgraded.

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
- Ollama models: presets in `_MODEL_PRESETS` (`__init__.py`), all must run in
  ≤8 GB RAM; index 0 stays the tiny starter model (first-run flow pulls it).
