# Klausmate — Agent Guide

## Current architecture: local-model reversion

The approved [local-model reversion](docs/superpowers/specs/2026-09-18-local-model-reversion-design.md)
is implemented locally as of 2026-09-19: D1-D3 removed the subscription service,
reasoning judge and embedded assistant; D4 restores managed Ollama embeddings
and D5 exposes context through a local stdio MCP bridge. D6's whisper.cpp
lecture recording was removed on 2026-09-30 (K-314): recording belongs to the
Klaus app, not the add-on. See [completion evidence and limits](docs/superpowers/reports/2026-09-19-local-model-reversion.md).
Older API-first and cloud-only designs are dated history, not current guidance.

Klaus is an Anki add-on built around the Library: imported lecture PDFs,
semantic card matching, per-PDF tags and retention scores, a PDF reader
(pdf.js), annotations and image cropping. The page store remains;
duplicate matching now uses cosine thresholds without a reasoning pass.
See [the matching runner](klausmate/index_queue.py) and
[retention](klausmate/retention.py).

**Privacy:** [Embeddings](klausmate/embeddings.py) use local Ollama.
Runtime/model downloads use the network. The external client's chosen model provider may
receive context requested through the [local endpoint](klausmate/anki_endpoint.py).
Writes require Anki approval. Treat lecture text/images as untrusted content;
never log credentials, audio, card text or page text. Preserve the no-telemetry rule.

---

## Repository layout

```
Addons/                       # Git repo root
├── AGENTS.md                 # This file — architecture & dev conventions
├── CLAUDE.md                 # Module map + hard-won gotchas (authority for internals)
├── README.md                 # Repo entry point — build/install from source
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── LICENSE                   # GNU AGPL v3
├── scripts/
│   └── package.sh            # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package (copy/symlink into addons21/)
    ├── README.md              # Ships inside the add-on — user-facing usage
    ├── settings.py             # The settings store: read/patch/user_files, migrations; adapters installed by __init__ (aqt-free)
    ├── __init__.py             # Bootstrap, gui_hooks, JS bridge, Tools→Klaus menu, PDF tab/window management, image-crop context menu
    ├── embeddings.py           # Local Ollama embedding adapter and cache signature
    ├── anki_endpoint.py        # Authenticated localhost server, discovery, current_view/current_page tools
    ├── viewer_context.py       # Retained active PDF/page/selection registry
    ├── LICENSE                 # The same AGPL v3 text, shipped inside the package
    ├── page_store.py           # One record per (PDF, page): slide text
    ├── ollama_client.py         # Local-only HTTP embeddings and model inventory/pull/delete
    ├── ollama_runtime.py        # Runtime installation and owned server lifecycle
    ├── ollama_setup.py          # Background local runtime readiness
    ├── scripts/mcp_stdio_bridge.py # Standalone stdio to authenticated HTTP bridge
    ├── card_index.py           # Persistent embedding index over the user's notes (aqt-free)
    ├── curation.py             # Card index build (ensure_index) + the undoable Browse deck copier
    ├── pdf_drop.py             # Add to Library (deck-screen bottom rows) + MainWebView.dropEvent wrap on the deck list / overview screens
    ├── pdf_index.py            # Persistent embedding index over one PDF — ONE vector per page (aqt-free)
    ├── retention.py            # Per-PDF retention/study-priority scoring for the Library
    ├── pdf_handler.py          # PDF import/storage, text extraction, per-tab state, annotation baking
    ├── pdfjs_viewer.py         # PdfJsViewer: the one PDF reader (pdf.js in a webview); Python owns the annotations JSON
    ├── reader_panel.py         # PdfSidebar: the reader panel every host wraps ("PDF viewer is unavailable" without QtWebEngine)
    ├── reader_tabs.py          # ReaderTabs: the reader's tab strip ([＋] [tabs] … [page n/m]), one tab set per host
    ├── pdf_source.py           # Piece loading: DocSource byte ranges from a hard-link snapshot (user_files/reading), ≤1 MB a call
    ├── doc_sync.py             # Open-PDF folder sync: watcher + rescan events changed/moved/missing/back; own writes pinned
    ├── annotation_save.py      # SavePipeline: the one bake path (500 ms debounce, one worker per PDF, retry, flush on close)
    ├── pdf_drive.py            # The Library's disk half: background folder scan, watcher, delete-to-Trash
    ├── library_sidebar.py      # The Library in Browse's sidebar: real names, retention %, icons, menus, footer
    ├── tasks.py                # The one list of running processes (aqt-free, thread-safe reports)
    ├── status_bar.py           # Browse's bottom bar: gear (Anki Preferences), task progress, pane toggles
    ├── bottom_row.py           # main window: Anki's own bottom row + gear and task readout at its left edge
    ├── addons_menu.py          # other add-ons' top-level menus → one Add-ons menu before Help (main window + Browse)
    ├── single_window.py        # Decks + Add + Browse as tabs (Add = Library tree | reader | editor), Edit Current in a right dock — Anki's windows built inside mw, never moved
    ├── host_keys.py            # review keys disabled on the Add and Browse tabs; the hosted editors get their keys (ShortcutOverride)
    ├── reader_host.py          # the ONE PDF reader: home = the Add tab's reader slot, lent to Browse's viewer mode, never across windows
    ├── library_tree.py         # the Add tab's Library view (Klaus's own QTreeView over library_sidebar's index; filter, clicks, menus, drops)
    ├── library_actions.py      # Window-free Library actions the sidebar menus call
    ├── drive_store.py          # Library's virtual folder layer (user_files/drive.json); nothing on disk moves
    ├── prefs_state.py        # Preferences value state: keys, dirty, commit() → one patch + effects (aqt-free)
    ├── manage_models.py        # General, Appearance, Local models and external MCP configuration
    ├── setup_flow.py           # First-run dialog + per-profile-open readiness checks (library root and local runtime readiness)
    ├── tag_migrate.py          # One-time klaus:: -> !Library:: tag rename for upgrading collections
    ├── browse_toggles.py       # Browse toolbar ◧/◨ sidebar and editor-column toggles
    ├── crop_dialog.py          # Image-crop dialog (crop saved as a new media file)
    ├── config.json             # Default add-on config
    ├── config.md               # Config key documentation (shown in Anki config UI)
    ├── manifest.json           # Package name and version for non–AnkiWeb distribution
    ├── web/
    │   ├── copilot.js          # Editor field-focus tracking (for PDF page-insert targeting) + image-crop dblclick trigger
    │   ├── pdfjs_viewer.html   # The reader page (pdf.js 3.11.174 vendored in pdfjs/; pure helpers in pdfjs_pure.js)
    │   └── pdfjs/              # Vendored pdf.js
    ├── vendor/                 # Vendored pure-Python deps (pypdf 6.11.0) — the sole third-party exception
    └── user_files/             # Persisted across upgrades — never write here from a test
        ├── contexts/           # *.json (per-page PDF text), one per imported PDF
        ├── pdfs/                # Stored PDF copies (post-bake, real annotations included)
        ├── pdf_originals/       # Pristine copy captured once, used to regenerate bakes
        ├── annotations/         # Per-PDF highlight/note JSON, source of truth for baking
        ├── pdf_tabs.json        # Open tabs per host, thumbs, last_used (placement/geom dropped on read since the Add tab)
        ├── drive.json           # Library's virtual folders + window geometry (drive_store.py)
        ├── card_index/          # Packed vectors.f32 + manifest.json for semantic deck search
        ├── pdf_index/           # Per-PDF embedding indexes (one vector per page) and cosine matches
        ├── pages/               # <pdf_safe>/<digest12>/<page:04d>.json — slide text (page_store.py)
        ├── library_stats.json   # {safe: [size, mtime_ns]} per mapped PDF — spots closed PDFs changed outside Klaus
        └── reading/             # Hard-link snapshots the open readers read ranges from (pdf_source.py)
```

**Install path:** `addons21/klausmate/` (folder name must be alphanumeric per Anki conventions).

**Do not store user data outside `user_files/`** — everything else in the add-on folder is wiped on upgrade.

---

## Architecture

### Semantic card matching (indexing a PDF)

```
Library row → right-click → "Add to Search Index" / "Update Search Index"
        │
        ▼
index_queue.py :: _run(job): FOUR phases, one cancel token threaded
        │        through all of them (K-146, K-152, K-255). The Library's
        │        _on_embed is now just one request_pdf() call into this.
        ▼
curation.py :: ensure_index() — sync the card index (only new/edited notes
        │        re-embed; text-hash diffed). This is the only user-facing
        │        path that refreshes it; the Curate button used to do it
        │        invisibly, which is why K-146 had to add it here.
        ▼
embeddings.py: unit-normalized local Ollama vectors
        │
        ▼
card_index.py — user_files/card_index/: packed float32 vectors + manifest,
        │        top-K via math.sumprod over memoryviews (no numpy)
        ▼
retention.py :: ensure_pdf_index() → ensure_matches() — embed the PDF's
        │        PAGES (one vector each, from page_store.page_texts; a page
        │        whose text_hash is unchanged keeps its vector), score every
        │        indexed note (max cosine, cached in matches.json with the
        │        winning page)
        ▼
tag_sync.py :: sync_after_matches(): notes at/above this PDF's sensitivity
          threshold become members of "!Library::<folder>::<leaf>"
```

Copying matches into a deck is a SEPARATE, manual action with no PDF and no
deck scope: **Browse → Notes → "KlausMate: Create Curated Deck from
Selection…"** (`curation.prompt_and_create` / `create_curated_deck`), one
undo step, tagged `!Library::Curated`, originals untouched. There is no
free-text search box and no Curate Deck button — K-146 removed the button
(it never created a deck; it tagged and opened Browse on the tag indexing
already writes) and K-151 removed the last of its vocabulary.

### The Library and retention scoring

```
library_sidebar.py — the Library is the !Library tag branch in Browse's
        │       sidebar (K-306..K-308): real names, a retention % per tag,
        │       warning icons, right-click menus (library_actions.py);
        │       pdf_drive.py mirrors the library root on disk
        ▼
retention.py — per PDF: embed its pages (pdf_index.py, one vector each) →
        │       score every indexed note against those pages (max cosine,
        │       cached in matches.json) → pull FSRS retrievability for
        │       matched cards → aggregate into a study-priority score
        ▼
Browse's Library sidebar row shows the retention %; right-click can
adjust sensitivity, chart retention history or show the file in Finder
```

The judge, doubtful count and Doubtful cards menu were removed in D2.
`Doubtful` remains a reserved historical tag name; existing user tags are
not deleted by the rebuild. See [tag membership](klausmate/tag_sync.py).

### PDF reader (`pdfjs_viewer.py`, `reader_panel.py`)

- One reader everywhere: pdf.js in a webview (`PdfJsViewer`) inside a `PdfSidebar` panel, with a `ReaderTabs` strip and its own tab set per host. The native QPdfView renderer was deleted in PDF reader 5/5; without QtWebEngine the panel shows "PDF viewer is unavailable".
- Loading is piecewise: the page gets the file length and the first 256 KB, then pdf.js asks for byte ranges over the bridge (`pdf_source`). The page owns rendering, selection (pdf.js text layer), zoom and find; Python owns the annotations JSON.
- Outside edits, renames and deletes reach an open reader through `doc_sync`; every save goes through `annotation_save`'s pipeline.
- **Cmd+C** / right-click **Copy** copy selected text; **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**, copies it as an image (there is no toolbar button for this — it was removed).
- Highlights and sticky notes are baked into the stored PDF as real annotations by `pdf_handler.bake_annotations` (vendored `pypdf`).

### The PDF reader and its homes

The ONE editor-host reader (`reader_panel.PdfSidebar`, `host_key="editor"`,
with `reader_tabs.ReaderTabs` above the page) is owned by `reader_host.py`:
its permanent parent is the Add tab's reader slot (`set_home`), Browse's
viewer mode borrows it (`library_viewer.enter` → `lend(box)`, `leave` →
`give_back()`), and `release()` is cleanup + forget (a cleaned reader is
never reused; the next `reader()` builds afresh). It is never re-parented
across top-level windows: a lend into another window releases and rebuilds
there (fallback mode, where Browse is a stock window, builds it under
Browse and releases it when that Browse closes). The dock (`PdfDock`,
`_PanelBar`), its placement memory and the editor-toolbar Library… button
went with the Add tab (spec 2026-10-01-add-tab-design.md); the Lecture
panel keeps its own reader. The open tab set, thumbnails and last-used
page persist in `user_files/pdf_tabs.json` (all writers merge via
`pdf_handler._save_tabs_file`, never overwrite wholesale; `placement`/`geom`
from older builds are dropped on read).
`web/copilot.js` only tracks field focus (for
PDF-page-insert targeting) and the image-crop double-click trigger now —
the ghost-text/Ask bridge it used to carry is gone.

### Retained endpoint and page context

The embedded assistant, its process host and session store were removed
in D3 (2026-09-19). [Endpoint](klausmate/anki_endpoint.py) remains with
AnkiConnect-compatible actions and MCP over HTTP. Its existing
`current_view` tool already reads [viewer_context](klausmate/viewer_context.py).
The page store still owns text and rendering. D5 implements `current_page` with text and an image when available, private
`user_files/mcp_connection.json` discovery and the standalone
`scripts/mcp_stdio_bridge.py` for an external client. Preferences copies a
token-free config using a separate Python 3.9+ interpreter. Discovery is published
atomically at server startup, read on each bridge request, and removed on matching
server shutdown. POSIX permissions are tested; native Windows ACL privacy is not.

Endpoint writes require a plain-text approval preview. Declining or timing
out must return an error. Agent-created cards carry source tags, never a
hand-applied PDF `!Library` membership tag; indexing owns that invariant.
See [endpoint permissions and actions](klausmate/anki_endpoint.py).

### Hooks registered at import (`__init__.py`, approximate)

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)              # -> manage_models_dialog
gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)      # pycmd routing ("klausmate:" prefix)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)  # right-click crop
gui_hooks.main_window_did_init.append(install_menu)                 # Tools → KlausMate Preferences…
gui_hooks.profile_did_open.append(settings.migrate)                 # registered dict->dict migrations, legacy key scrub
gui_hooks.profile_did_open.append(tag_migrate.migrate_on_profile_open)  # one-time klaus:: -> !Library:: rename
gui_hooks.profile_did_open.append(first_run_check)                  # first-run: library root + local-model setup
gui_hooks.profile_did_open.append(setup_readiness_check)
gui_hooks.profile_did_open.append(_start_klaus_endpoint)        # anki_endpoint bind (mw.col must exist)
gui_hooks.browser_will_show.append(on_browser_will_show)            # Browse layout repair (toggles now in the status bar)
curation.setup_hooks()                                              # gui_hooks.browser_menus_did_init
pdf_drop.setup()                                                    # Add to Library + drop wrap on deck screens (independent try/except)
library_sidebar.setup()                                             # the Library in Browse's sidebar (independent try/except)
status_bar.setup()                                                  # Browse bottom bar; sync/media hooks (independent try/except)
bottom_row.setup()                                                  # main window bottom row: gear + task readout (independent try/except)
addons_menu.setup()                                                 # main_window_did_init + browser_will_show: Add-ons menu (independent try/except)
single_window.setup()                                               # main_window_did_init: host layout, dialog-registry creators, hooks; config single_window (independent try/except)
gui_hooks.operation_did_execute.append(tag_sync.on_operation_did_execute)  # sidebar tag edits reach the PDFs
top_bar.setup()                                                     # toolbar restyle + star logo (independent try/except)
browse_highlight.setup()                                            # Browse search-term highlighting (independent try/except)
heatmap.setup()                                                     # review heatmap on the deck list (independent try/except)
dashboard.setup()                                                   # Control-Center widget editing (independent try/except; MUST stay after heatmap — body order)
window_chrome.setup()                                               # KlausBook chrome for Add/Browse/Stats/reviewer-bar (independent try/except)
gui_hooks.profile_will_close.append(_stop_endpoint_on_profile_close)  # stop the retained endpoint
lecture_view.setup()                                                # review-time Lecture dock (independent try/except)
```

The retained endpoint hooks are `_start_klaus_endpoint` on profile open
and `_stop_endpoint_on_profile_close` on profile close. There is no
assistant teardown or reopen hook. See [bootstrap](klausmate/__init__.py).

`heatmap.setup()` adds four of its own:
`deck_browser_will_render_content` (the panel HTML into `content.stats`),
`webview_will_set_content` (its stylesheet, DeckBrowser only),
`webview_did_receive_js_message` (a clicked day) and `browser_will_search`
(resolving the `klausday:` token those clicks produce).

`pdf_drop.setup()` and `library_sidebar.setup()` are each wrapped in their own
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

### Localhost endpoint

`anki_endpoint.py` serves authenticated AnkiConnect and MCP requests from a
`ThreadingHTTPServer` bound to `127.0.0.1:0` (an OS-assigned ephemeral
port; AnkiConnect's usual 8765 is never assumed free). Started on
`profile_did_open`, stopped on `profile_will_close`. A fresh 32-byte hex
token is generated per start; every request must carry it as
`X-Klaus-Token`, and any request carrying an `Origin` header is refused
outright (a browser page must never drive the collection) — both
checked before the body is even read. Bodies over 4 MB are rejected.
Writes never touch the collection without the user approving a
plain-text preview in a window-modal dialog (`open()`, never `exec()` —
K-114) while the HTTP thread waits on a `threading.Event`.

Two routes share ONE registry (`ACTIONS`) so they can't drift apart:

- **`/`** — AnkiConnect's own `{"action", "version", "params"}` protocol;
  HTTP 200 always, `{"result", "error"}` in the body (AnkiConnect's own
  convention). Supported actions: `version`, `deckNames`,
  `deckNamesAndIds`, `modelNames`, `modelFieldNames`, `findNotes`,
  `notesInfo`, `findCards`, `cardsInfo`, `addNote`, `addNotes`,
  `updateNoteFields`, `addTags`, `removeTags`, `guiBrowse`, plus three
  Klaus-only ones — `klausSearchNotes` (**lexical**: `anki_tools`'
  handler behind it is `col.find_notes`, i.e. Anki's own search syntax,
  and the tool description and system prompt both say so; the semantic
  note search is a separate future card, K-207),
  `klausSearchLecturePdfs` (the **semantic** one, over the indexed
  lecture PDFs), and `klausCurrentView` (what
  `viewer_context` says the user is looking at). Anything else answers
  `"unsupported action"`. A request carrying `X-Klaus-Agent: 1` (the
  `/mcp` route sets this) additionally requires `addNote`'s
  `params.note.options.sourcePage` — a card proposed with no source page
  is an error, never a silent add.
- **`/mcp`** — the same actions as MCP tools, JSON-RPC 2.0 over POST (no
  SSE stream), with `initialize`,
  `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Tools
  are named `mcp__klaus__<name>` — `current_view`, `search_notes`,
  `find_notes`, `get_notes`, `search_lecture_pdfs`, `list_decks`,
  `list_models`, `model_fields`, `add_note`, `update_note_fields`,
  `add_tags`, `remove_tags`, `open_in_browse` — each mapped onto one `/`
  action (`mcp_args_to_params` reshapes the flat, snake_case MCP
  arguments into that action's params). A tool error comes back as
  `isError: true` with the message, never a JSON-RPC error, so the model
  can recover instead of aborting the turn.

The endpoint reuses `anki_tools`'s existing handlers for note
create/update and for both searches rather than a second implementation.
D5 will add a discovery file and stdio bridge without credentials in
command-line arguments. Preserve the endpoint's token, Origin, body-size
and approval checks; external client permissions do not replace these
server-side gates. See [D5](docs/superpowers/plans/2026-09-19-external-mcp-bridge.md).

### Editor-attached state

Attributes on `editor` (all `editor._klausmate_*`, guarded with
`getattr(..., None)` / `is None` checks to stay reload-safe): `_klausmate_panel`
(the PDF drop bar, `_PdfBar`), `_klausmate_vsplit`,
`_klausmate_target_field_index` / `_target_field_name`, `_klausmate_crop_open`.
(`_klausmate_pdf_tabs` / `_klausmate_sidebar` / `_klausmate_pdf_container` went
with the dock: the reader is reached through `reader_host.reader()`.)
Browse-window toggles carry their own: `_klausmate_sidebar_toggle_btn` /
`_klausmate_editor_toggle_btn`. Deck-screen state is down to the drop
wrap's own guards since K-151: `_klausmate_drop_wrapped` / `_drop_orig`.

---

## Configuration

- Defaults: `klausmate/config.json`
- User overrides: stored in `meta.json` by Anki's add-on manager
- UI: **Tools → KlausMate Preferences…** (`manage_models_dialog`; the top bar's star opens it too, and raw JSON is still at **Tools → Add-ons → Klausmate → Config**)
- Key docs: `klausmate/config.md`

The current [defaults](klausmate/config.json), [configuration reference](klausmate/config.md)
and [migrations](klausmate/settings.py) select Ollama and native vector dimensions. Migration removes retired cloud credentials, Plus,
judge, dock and transcription settings. The local migration marker preserves later model choices.
General and appearance keys retain their existing roles.

**Config accessors (`klausmate/settings.py`, aqt-free, 2026-09-30):**
`settings.read()` is a fresh dict of the stored config; `settings.patch(
updates, remove=())` is the ONE writer (merge into a fresh read, inline
on the main thread, hopped through `run_on_main` from any other thread,
dropped if the profile changed first); `settings.user_files()` is the
user-files path; `settings.register_migration(fn)` takes a pure
`dict -> dict` that `settings.migrate()` runs once per profile open.
`__init__.py` installs the adapters (`AnkiStore` over `mw.addonManager`,
`run_on_main`, `current_profile`). There is no whole-blob writer:
`write_config`, `patch_config`, `get_config`, the `_pkg()` helpers and
the per-module `USER_FILES` copies are gone. Tests swap `settings.store`
for a `DictStore` and `settings.user_files_dir` for a scratch dir.
Preserve legacy-key cleanup until users have upgraded; D4 explicitly
un-retires its local runtime keys.

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| `pypdf` 6.11.0 | Vendored under `klausmate/vendor/`; the sole vendored third-party Python dependency |
| `PyQt6.QtWebEngine` | Anki's PyQt6 (the pdf.js reader; "PDF viewer is unavailable" label if missing) |
| `PyQt6.QtPdf` | Anki's PyQt6 (page images only: `page_store.render_page_png`) |
| Ollama | Managed local runtime; no cloud embedding fallback |
| External MCP client | Separate client connects through a stdio bridge while Anki runs |

The rebuild uses stdlib HTTP/subprocess code without third-party Python
SDKs or bundled native Python wheels. `pypdf` remains the vendored Python
exception. See [the approved design](docs/superpowers/specs/2026-09-18-local-model-reversion-design.md).
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
- Verify the archive excludes local data and credentials. The historical
  service was removed in D1; package only the add-on source.

### Tests

Headless logic tests stub `aqt`/`anki`; selected suites also construct real Qt widgets offscreen; see `.claude/skills/klaus-test/` and `tests/README.md`. Run them all:

```sh
failed=0
for t in tests/test_*.py; do
  env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" || failed=1
done
test "$failed" -eq 0
```

### Type checking

```sh
pip install mypy "aqt[qt6]"
mypy klausmate
```

---

## Code conventions (this project)

- Prefer **gui_hooks** over monkey-patching.
- Background work: always `QueryOp` / `without_collection()` for network calls (including local Ollama HTTP calls); UI updates via `mw.taskman.run_on_main` when needed.
- Import Qt from `aqt.qt`; QtPdf from `PyQt6.QtPdf` only inside the function that uses it (`page_store.render_page_png`).
- Editor-attached state via attributes — see "Editor-attached state" above.
- When adding config keys: update `config.json`, `config.md`, and the relevant section of `manage_models.py`.

---

## What used to be here

Klaus was originally a Copilot-style inline-autocomplete + ⌘K-Ask tool with
a separate chat panel for semantic search. That product surface is gone:
`copilot.js`'s ghost-text/Ask bridge, `claude_api.py`, `settings_ui.py`,
and `chat_dock.py` (the "Klaus panel") were all deleted, along with the
`autocomplete_model` / `ask_model` / `klaus_engine` / `claude_*` config
keys and the Browse natural-language search. `anki_tools.py` was later
restored as the collection tool layer retained by the localhost endpoint. Do not resurrect autocomplete/Ask/chat-panel
language; the current architecture is linked above.

A second, much shorter-lived surface came and went the same week. Pouya's
2026-09-01 plan for an AI assistant first took the shape of a chat panel
in the Library (`assistant_panel.py`, its own session store
`assistant_session.py`) fed by a direct-API streaming client
(`llm_client.py`) and an advisory tier check (`entitlement.py`), with a
companion podcast-script generator (`podcast.py`) — all deleted
2026-09-02 when Pouya converged the design onto hosting the Claude Code
CLI instead (`assistant_dock.py`: one dock, one engine). Config keys
`assistant_api_key` / `assistant_backend` / `assistant_token` were
dropped with them. `card_forge.py` and `anki_tools.py` survived; the
embedded assistant that followed was itself removed in D3 on 2026-09-19.

Historical note, 2026-09-15: the API-first turn removed Ollama and OCR
and introduced page records, page-level vectors and cloud adapters.
Reverted by the approved 2026-09-18 local-model design: D1-D3 have removed
Plus, the judge and assistant; D4 restores managed Ollama, D6's local
transcription came and went (removed in K-314), and D5 exposes the retained endpoint. OCR and Voyage are
not part of the approved restoration. The superseded specs retain the
original design history.

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
