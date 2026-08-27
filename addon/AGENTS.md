# Klausmate — Agent Guide

Klausmate ("Klaus") is an **Anki 2.1 add-on**. It has one AI-powered
capability — semantic search over your notes and lecture PDFs — which
powers two user-facing features: **Curate Deck** (find cards matching a
lecture PDF and copy them into a new deck) and the **Library** (a window
over your imported PDFs with a per-PDF retention/study-priority score). A
native PDF viewer (selection, highlights, sticky notes baked in as real
annotations) and an image-crop dialog round out the add-on. There is no
autocomplete, no chat panel, and no Claude/Anthropic integration — all three
were removed; see "What used to be here" below if you're archaeology-diving
through git history.

**Privacy:** the only network calls Klaus makes are for embeddings. The
default provider is **Voyage**, a cloud API — card text is sent to Voyage's
servers to build the search index unless you switch `embedding_provider` to
`ollama` in config, which keeps everything local. `openai` is a second cloud
option. No telemetry.

---

## Repository layout

```
Addons/                       # Git repo root
├── AGENTS.md                 # This file — architecture & dev conventions
├── CLAUDE.md                 # Module map + hard-won gotchas (authority for internals)
├── README.md                 # Repo entry point — build/install from source
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── scripts/
│   └── package.sh            # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package (copy/symlink into addons21/)
    ├── README.md              # Ships inside the add-on — user-facing usage
    ├── __init__.py             # Bootstrap, gui_hooks, JS bridge, Tools→Klaus menu, PDF tab/window management, image-crop context menu
    ├── embeddings.py           # Embedding provider abstraction: Voyage (default) / OpenAI / Ollama, aqt-free
    ├── card_index.py           # Persistent embedding index over the user's notes (aqt-free)
    ├── curation.py             # Curate Deck pipeline: sync index, embed query, rank, tag preview, undoable deck copy
    ├── deck_curate.py          # "Curate Deck" button + PDF drop on the deck list / overview screens
    ├── pdf_index.py            # Persistent embedding index over one PDF's text chunks (aqt-free)
    ├── retention.py            # Per-PDF retention/study-priority scoring for the Library
    ├── pdf_handler.py          # PDF import/storage, text extraction, per-tab state, annotation baking
    ├── pdf_viewer.py           # PdfViewer (QPdfView + selection/highlight overlay, find, thumbnails) and PdfSidebar
    ├── pdf_drive.py            # The Library window — virtual-folder tree + PdfSidebar
    ├── drive_store.py          # Library's virtual folder layer (user_files/drive.json); nothing on disk moves
    ├── manage_models.py        # "Manage models" dialog: embedding provider/key, local Ollama model pulls, general toggles
    ├── setup_flow.py           # First-run dialog + per-profile-open readiness checks, gated on the active embedding provider
    ├── tag_migrate.py          # One-time klaus:: -> !Library:: tag rename for upgrading collections
    ├── browse_toggles.py       # Browse toolbar ◧/◨ sidebar and editor-column toggles
    ├── ollama_client.py        # Stdlib HTTP client for Ollama: /api/embed, pull, delete (no text generation)
    ├── ollama_runtime.py       # Managed Ollama download/extract/serve under user_files/runtime/
    ├── ollama_setup.py         # First-run install detection (Homebrew, winget)
    ├── crop_dialog.py          # Image-crop dialog (crop saved as a new media file)
    ├── config.json             # Default add-on config
    ├── config.md               # Config key documentation (shown in Anki config UI)
    ├── manifest.json           # Package name and version for non–AnkiWeb distribution
    ├── web/
    │   └── copilot.js          # Editor field-focus tracking (for PDF page-insert targeting) + image-crop dblclick trigger
    ├── vendor/                 # Vendored pure-Python deps (pypdf 6.11.0) — the sole third-party exception
    └── user_files/             # Persisted across upgrades — never write here from a test
        ├── contexts/           # *.json (per-page PDF text), one per imported PDF
        ├── pdfs/                # Stored PDF copies (post-bake, real annotations included)
        ├── pdf_originals/       # Pristine copy captured once, used to regenerate bakes
        ├── annotations/         # Per-PDF highlight/note JSON, source of truth for baking
        ├── pdf_tabs.json        # Open tabs, placement (dock above/below/float), thumbs, last_used
        ├── drive.json           # Library's virtual folders + window geometry (drive_store.py)
        ├── card_index/          # Packed vectors.f32 + manifest.json for semantic deck search
        ├── pdf_index/           # Per-PDF embedding indexes for retention scoring
        └── runtime/             # Klaus-managed Ollama install, versioned subdirectory
```

**Install path:** `addons21/klausmate/` (folder name must be alphanumeric per Anki conventions).

**Do not store user data outside `user_files/`** — everything else in the add-on folder is wiped on upgrade.

---

## Architecture

### Semantic deck curation (Curate Deck)

```
Deck list / deck overview — drop a PDF, or pick one from the "Curate Deck" menu
        │
        ▼
deck_curate.py :: run_curation_flow(pdf_name, deck_scope)
        │
        ▼
curation.py :: run_curation() — sync the card index (only new/edited notes
        │        re-embed; text-hash diffed), embed the PDF's text, rank
        │        every card by cosine similarity
        ▼
embeddings.py — Voyage / OpenAI / Ollama, unit-normalized vectors
        │
        ▼
card_index.py — user_files/card_index/: packed float32 vectors + manifest,
        │        top-K via math.sumprod over memoryviews (no numpy)
        ▼
Best matches tagged "!Library::Curating" → Browse opens on that tag → prune →
"Create curated deck" copies the selection into a new deck (one undo step,
tagged "!Library::Curated", originals untouched)
```

There is no free-text search box anymore — curation is always driven by a
lecture PDF (`curation.run_curation`'s `prompt` parameter exists but nothing
in the current UI passes one; the panel that used to type into it,
`chat_dock.py`, is gone).

### The Library and retention scoring

```
pdf_drive.py — the Library window: a tree of virtual folders (drive_store.py,
        │       user_files/drive.json — nothing on disk moves) next to a
        │       standalone PdfSidebar
        ▼
retention.py — per PDF: embed its chunks (pdf_index.py) → score every
        │       indexed note against those chunks (max cosine, cached in
        │       matches.json) → pull FSRS retrievability for matched cards
        │       → aggregate into a study-priority score
        ▼
Library row shows the score; right-click can re-embed, adjust match
sensitivity, show matches in Browse ("!Library::Matching" tag), or hand off
to deck_curate.py's curation flow
```

### PDF viewer (`pdf_viewer.py`)

- One `QPdfView` in **MultiPage / FitToWidth** mode inside a `PdfSidebar` widget, opened from the Library or the editor's drop panel.
- Layout math mirrors Qt's `QPdfViewPrivate::calculateDocumentLayout` (screen DPI / 72, margins, page spacing, centered page width) — required so hit-testing and selection highlights line up.
- Text selection: viewport `eventFilter` drags map to `(page, QPointF)` via `_viewport_to_page_point`; `QPdfDocument.getSelection()` is called per page (multi-page drags supported); highlights painted by `_SelectionOverlay` using `QPdfSelection.bounds()`.
- **Cmd+C** / right-click **Copy** copy selected text; **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**, copies it as an image (there is no toolbar button for this — it was removed).
- Highlights and sticky notes are baked into the stored PDF as real annotations by `pdf_handler.bake_annotations` (vendored `pypdf`).

### Editor-side PDF panel

`_PdfTabContainer` in `__init__.py` hosts any number of open PDFs, one bar of
chrome per editor window: `[tabs ✕] [page n/m] [＋]`. It docks ABOVE or BELOW
the note-editor pane (wrapping `editor.widget` in a `QSplitter`), or floats
as a real, parentless window — dragged out via native `startSystemMove()`
with a watchdog/ghost fallback for when that call lies about succeeding. One
`PdfViewer`/`PdfSidebar` instance is reused across tabs. The open tab set,
dock placement, thumbnails, and last-used page persist in
`user_files/pdf_tabs.json` (all writers merge via `pdf_handler._save_tabs_file`,
never overwrite wholesale). `web/copilot.js` only tracks field focus (for
PDF-page-insert targeting) and the image-crop double-click trigger now —
the ghost-text/Ask bridge it used to carry is gone.

### Hooks registered at import (`__init__.py`, approximate)

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)              # -> manage_models_dialog
gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)      # pycmd routing ("klausmate:" prefix)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)  # right-click crop
gui_hooks.main_window_did_init.append(install_menu)                 # Tools → Klaus
gui_hooks.profile_did_open.append(_migrate_config)                  # legacy chat_*/claude_* key cleanup
gui_hooks.profile_did_open.append(tag_migrate.migrate_on_profile_open)  # one-time klaus:: -> !Library:: rename
gui_hooks.profile_did_open.append(first_run_check)                  # embeddings-provider onboarding
gui_hooks.profile_did_open.append(setup_readiness_check)
gui_hooks.editor_did_init.append(on_editor_did_init)                # PDF panel + tab container
gui_hooks.browser_will_show.append(on_browser_will_show)            # Browse toolbar toggles (◧ / ◨)
curation.setup_hooks()                                              # gui_hooks.browser_menus_did_init
deck_curate.setup()                                                 # "Curate Deck" on deck screens (independent try/except)
pdf_drive.setup()                                                   # Library window + top-toolbar link (independent try/except)
top_bar.setup()                                                     # toolbar restyle + star logo (independent try/except)
browse_highlight.setup()                                            # Browse search-term highlighting (independent try/except)
heatmap.setup()                                                     # review heatmap on the deck list (independent try/except)
dashboard.setup()                                                   # Control-Center widget editing (independent try/except; MUST stay after heatmap — body order)
```

`heatmap.setup()` adds four of its own:
`deck_browser_will_render_content` (the panel HTML into `content.stats`),
`webview_will_set_content` (its stylesheet, DeckBrowser only),
`webview_did_receive_js_message` (a clicked day) and `browser_will_search`
(resolving the `klausday:` token those clicks produce).

`deck_curate.setup()` and `pdf_drive.setup()` are each wrapped in their own
`try/except` at import time — a failure in one must not cost the user the
other, or the editor/menu features above. `tests/test_imports.py` imports
every module directly (bypassing that swallowing try/except) so a genuine
import-time bug fails loudly instead of a buried `print()`.

### JS ↔ Python message protocol

One bridge now: `web/copilot.js` → `on_js_message` in `__init__.py`, prefix
`"klausmate:"`, split `":", 2`. Payloads are **base64-encoded JSON** after
the action name:

| Action | JS → Python | Purpose |
|--------|-------------|---------|
| `focus` | `{field}` | Sets `editor._klausmate_target_field_index` / `_target_field_name` — used for PDF page-insert targeting |
| `crop` | `{...}` | Opens `crop_dialog.py` for the referenced image |
| `log` / `dbg` | plain string | Console logging |

Two more prefixes ride the same gui_hook from other modules:
`klausmate:heatmap:<day>` (a heatmap cell click → Browse) and
`klausmate:dash:<b64 json>` (dashboard edit/order/remove/add —
validated by `dashboard.apply_action`, the only gate to config).

The old `"klaus:"`-prefixed bridge belonged to the deleted chat panel
(`chat_dock.py` / `web/search.js`) and no longer exists.

### Editor-attached state

Attributes on `editor` (all `editor._klausmate_*`, guarded with
`getattr(..., None)` / `is None` checks to stay reload-safe): `_klausmate_panel`
(the PDF drop bar, `_PdfBar`), `_klausmate_pdf_container`, `_klausmate_pdf_tabs`,
`_klausmate_sidebar`, `_klausmate_active_pdf`, `_klausmate_vsplit`,
`_klausmate_target_field_index` / `_target_field_name`, `_klausmate_crop_open`.
Browse-window toggles carry their own: `_klausmate_sidebar_toggle_btn` /
`_klausmate_editor_toggle_btn`. Deck-screen state:
`_klausmate_curate_link`, `_klausmate_drop_wrapped` / `_drop_orig`.

---

## Configuration

- Defaults: `klausmate/config.json`
- User overrides: stored in `meta.json` by Anki's add-on manager
- UI: **Tools → Klaus → Manage models…** (`manage_models_dialog`, also reached via **Tools → Add-ons → Klausmate → Config**)
- Key docs: `klausmate/config.md`

Notable keys: `embedding_provider` (`voyage` default | `openai` | `ollama`),
`embedding_model`, `embedding_api_key_voyage` / `embedding_api_key_openai`,
`curate_top_k`, `curate_min_score`, `pdf_match_threshold`, `pdf_match_agg`,
`pdf_index_max_chunks`, `endpoint` (Ollama server URL), `runtime_auto_setup`
(Klaus manages its own local Ollama install when needed), `image_crop_enabled`,
`heatmap_enabled` (the review heatmap under the deck list),
`dashboard_order` (deck-screen widget order; written by the dashboard's
right-click → Edit Widgets mode — drag to reorder, ⊖/＋ toggle the
per-widget bools).

`_migrate_config()` (on `profile_did_open`) cleans up legacy `chat_*` /
`claude_*` config keys left over from the deleted Ask-on-Claude feature —
keep it until users have upgraded past it.

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| `pypdf` 6.11.0 | Vendored under `klausmate/vendor/` — the **sole** third-party dependency |
| `PyQt6.QtPdf` / `PyQt6.QtPdfWidgets` | Anki's PyQt6 (PDF viewer; graceful fallback if missing) |
| Ollama | Optional — user-installed, or Klaus-managed under `user_files/runtime/` via `ollama_runtime.py`; used only if `embedding_provider` is `ollama` |
| Voyage / OpenAI embedding APIs | Optional — `embeddings.py`, used only when `embedding_provider` selects them |

Every network client (`ollama_client.py`, `embeddings.py`) is **stdlib
only** (`urllib`) — no `requests`, no third-party SDKs, no bundled wheels.
No numpy either — Anki's venv doesn't have it, so `card_index.py`/
`pdf_index.py` do ranking with `math.sumprod` over `array('f')` memoryviews.

---

## Development workflow

1. Symlink or copy `klausmate/` into `addons21/`.
2. Restart Anki (add-ons load at startup; no hot reload).
3. Debug from terminal: macOS `/Applications/Anki.app/Contents/MacOS/anki` — `print()` goes to stdout.
4. Webview JS: `QTWEBENGINE_REMOTE_DEBUGGING=8080` → Chrome DevTools at `http://localhost:8080`.
5. Anki debug console: `pp(obj)`; avoid `traceback.print_exc()` inside `QueryOp` success/failure callbacks (prints `NoneType: None` outside active `except` blocks).

### Packaging

```sh
./scripts/package.sh
```

Produces `dist/klausmate.ankiaddon`. The script stages files to a tempdir, bumps `manifest.json`'s `mod`, and zips with these rules:

- Build from **inside** the staging dir (the zip must NOT contain a `klausmate/` wrapper folder — AnkiWeb rejects those).
- Strip every `__pycache__`/`*.pyc`/`.DS_Store` (AnkiWeb rejects archives that contain them).
- Exclude `meta.json*` (per-user config, may hold API keys — the glob covers timestamped backups too) and all `user_files/` contents except `README.txt`.

### Tests

Headless logic tests stub `aqt`/`anki` and never touch real Qt widgets — see `.claude/skills/klaus-test/` and `tests/README.md`. Run them all:

```sh
for t in tests/test_*.py; do
  env QT_QPA_PLATFORM=offscreen python3 "$t" || exit 1
done
```

### Type checking

```sh
pip install mypy "aqt[qt6]"
mypy klausmate
```

---

## Code conventions (this project)

- Prefer **gui_hooks** over monkey-patching.
- Background work: always `QueryOp` / `without_collection()` for network calls (Ollama, Voyage, OpenAI); UI updates via `mw.taskman.run_on_main` when needed.
- Import Qt from `aqt.qt`; QtPdf from `PyQt6.QtPdf` behind try/except (`pdf_viewer.py`).
- Editor-attached state via attributes — see "Editor-attached state" above.
- When adding config keys: update `config.json`, `config.md`, and the relevant section of `manage_models.py`.

---

## What used to be here

Klaus was originally a Copilot-style inline-autocomplete + ⌘K-Ask tool with
a separate chat panel for semantic search. That product surface is gone:
`copilot.js`'s ghost-text/Ask bridge, `claude_api.py`, `anki_tools.py`,
`settings_ui.py`, and `chat_dock.py` (the "Klaus panel") were all deleted,
along with the `autocomplete_model` / `ask_model` / `klaus_engine` /
`claude_*` config keys and the Browse natural-language search. What
remains — Curate Deck, the Library, the PDF viewer, and image cropping — is
everything above. Don't resurrect autocomplete/Ask/chat-panel language in
docs or comments; if you find some, it's stale, not a spec.

---

## Anki add-on quick reference

<details>
<summary>General Anki add-on patterns (expand when porting or debugging)</summary>

### Key imports

```python
from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showInfo, tooltip
from aqt.operations import QueryOp
```

### Collection access

Use `mw.col` and high-level APIs (`get_card`, `update_note`, …). Avoid raw SQL schema changes.

### Web asset exports

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
# In webview_will_set_content:
pkg = mw.addonManager.addonFromModule(__name__)
web_content.js.append(f"/_addons/{pkg}/web/copilot.js")
```

### Config

```python
cfg = mw.addonManager.getConfig(__name__)
mw.addonManager.writeConfig(__name__, cfg)
```

### Background ops

```python
op = QueryOp(parent=mw, op=lambda col: work(), success=on_ok)
op.without_collection().run_in_background()  # no collection lock — use for network
```

### Porting notes

- Anki 23.10+ target; WebEngine (async JS, `pycmd` for JS→Python).
- https://forums.ankiweb.net/t/porting-tips-for-anki-23-10/35916

</details>
