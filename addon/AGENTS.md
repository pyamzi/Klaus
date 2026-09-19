# Klausmate — Agent Guide

## Current architecture: local-model reversion

The approved [local-model reversion](docs/superpowers/specs/2026-09-18-local-model-reversion-design.md)
is implemented locally as of 2026-09-19: D1-D3 removed the subscription service,
reasoning judge and embedded assistant; D4 restores managed Ollama embeddings,
D6 supplies whisper.cpp transcription, and D5 exposes context through a local
stdio MCP bridge. See [completion evidence and limits](docs/superpowers/reports/2026-09-19-local-model-reversion.md).
Older API-first and cloud-only designs are dated history, not current guidance.

Klaus is an Anki add-on built around the Library: imported lecture PDFs,
semantic card matching, per-PDF tags and retention scores, a native PDF
viewer, annotations and image cropping. Lecture recording and the page
store remain; duplicate matching now uses cosine thresholds without a
reasoning pass. See [the matching runner](klausmate/index_queue.py),
[retention](klausmate/retention.py) and [the recorder](klausmate/lecture_recorder.py).

**Privacy:** [Embeddings](klausmate/embeddings.py) use local Ollama and
[recordings](klausmate/lecture_recorder.py) use [whisper.cpp](klausmate/local_transcription.py).
Runtime/model downloads use the network. Recording begins only on explicit Record;
failed chunks remain on disk. The external client's chosen model provider may
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
    ├── __init__.py             # Bootstrap, gui_hooks, JS bridge, Tools→Klaus menu, PDF tab/window management, image-crop context menu
    ├── embeddings.py           # Local Ollama embedding adapter and cache signature
    ├── anki_endpoint.py        # Authenticated localhost server, discovery, current_view/current_page tools
    ├── viewer_context.py       # Retained active PDF/page/selection registry
    ├── LICENSE                 # The same AGPL v3 text, shipped inside the package
    ├── page_store.py           # One record per (PDF, page): slide text + transcript segments
    ├── lecture_recorder.py     # ● Record: Chunker (30 s / page change), WAV chunks, the local transcription worker that writes segments (aqt-free above its Qt glue)
    ├── local_transcription.py   # whisper.cpp discovery, subprocess execution and JSON parsing
    ├── ollama_client.py         # Local-only HTTP embeddings and model inventory/pull/delete
    ├── ollama_runtime.py        # Runtime installation and owned server lifecycle
    ├── ollama_setup.py          # Background local runtime readiness
    ├── scripts/mcp_stdio_bridge.py # Standalone stdio to authenticated HTTP bridge
    ├── card_index.py           # Persistent embedding index over the user's notes (aqt-free)
    ├── curation.py             # Card index build (ensure_index) + the undoable Browse deck copier
    ├── pdf_drop.py             # PDF drop square + MainWebView.dropEvent wrap on the deck list / overview screens
    ├── pdf_index.py            # Persistent embedding index over one PDF — ONE vector per page (aqt-free)
    ├── retention.py            # Per-PDF retention/study-priority scoring for the Library
    ├── pdf_handler.py          # PDF import/storage, text extraction, per-tab state, annotation baking
    ├── pdf_viewer.py           # PdfViewer (QPdfView + selection/highlight overlay, find, thumbnails) and PdfSidebar
    ├── pdf_drive.py            # The Library window — virtual-folder tree + PdfSidebar
    ├── drive_store.py          # Library's virtual folder layer (user_files/drive.json); nothing on disk moves
    ├── manage_models.py        # General, Appearance, Local models and external MCP configuration
    ├── setup_flow.py           # First-run dialog + per-profile-open readiness checks (library root and local runtime readiness)
    ├── tag_migrate.py          # One-time klaus:: -> !Library:: tag rename for upgrading collections
    ├── browse_toggles.py       # Browse toolbar ◧/◨ sidebar and editor-column toggles
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
        ├── pdf_tabs.json        # Open tabs, placement (dock left/right/bottom/float), thumbs, last_used
        ├── drive.json           # Library's virtual folders + window geometry (drive_store.py)
        ├── card_index/          # Packed vectors.f32 + manifest.json for semantic deck search
        ├── pdf_index/           # Per-PDF embedding indexes (one vector per page) and cosine matches
        ├── recordings/          # <pdf_safe>/<t0>-p<page>.wav — chunks awaiting transcription; empty once they land
        └── pages/               # <pdf_safe>/<digest12>/<page:04d>.json — slide text + transcript segments (page_store.py)
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
pdf_drive.py — the Library window: a tree of virtual folders (drive_store.py,
        │       user_files/drive.json — nothing on disk moves) next to a
        │       standalone PdfSidebar
        ▼
retention.py — per PDF: embed its pages (pdf_index.py, one vector each) →
        │       score every indexed note against those pages (max cosine,
        │       cached in matches.json) → pull FSRS retrievability for
        │       matched cards → aggregate into a study-priority score
        ▼
Library row shows the score and matched card count; right-click can
index/re-index, adjust sensitivity, show matches in Browse, suspend or
unsuspend cards, or chart retention history
```

The judge, doubtful count and Doubtful cards menu were removed in D2.
`Doubtful` remains a reserved historical tag name; existing user tags are
not deleted by the rebuild. See [tag membership](klausmate/tag_sync.py).

### PDF viewer (`pdf_viewer.py`)

- One `QPdfView` in **MultiPage / FitToWidth** mode inside a `PdfSidebar` widget, opened from the Library or the editor's drop panel.
- Layout math mirrors Qt's `QPdfViewPrivate::calculateDocumentLayout` (screen DPI / 72, margins, page spacing, centered page width) — required so hit-testing and selection highlights line up.
- Text selection: viewport `eventFilter` drags map to `(page, QPointF)` via `_viewport_to_page_point`; `QPdfDocument.getSelection()` is called per page (multi-page drags supported); highlights painted by `_SelectionOverlay` using `QPdfSelection.bounds()`.
- **Cmd+C** / right-click **Copy** copy selected text; **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**, copies it as an image (there is no toolbar button for this — it was removed).
- Highlights and sticky notes are baked into the stored PDF as real annotations by `pdf_handler.bake_annotations` (vendored `pypdf`).
- **Transcript strip** (2026-09-17): a collapsible readout under the page showing what was *said* over it (the page record's `segments`, never its slide text). Native = a NoFocus Qt strip; pdf.js = a docked footer outside `#pages`, pushed as `klausSetTranscript` and re-pushed on the page's ready signal. It refreshes on a page change and on `page_store.subscribe`; that notification arrives on the transcription worker thread, so `_on_page_store_notify` defers its whole body through `_run_on_main`.

### Editor-side PDF panel

`PdfDock` — a `QDockWidget`, one per host window (Browse and Add Cards),
created from `editor_did_init` exactly as the panel's earlier container
was — hosts any number of open PDFs, with `_PanelBar` as its title-bar
widget (`[◫] [＋] [tabs] … [page n/m] [⧉] [✕]`), which ignores presses it
does not handle so Qt itself moves, docks and floats the dock from the
bar's empty space. Allowed areas are left, right and bottom; floating is
Qt's own attached tool window above the host, never a parentless real
window — the old pane-anchored placements and the native
`startSystemMove()` tear-off with its watchdog/ghost fallback are gone.
`placement` (`left`/`right`/`bottom`/`float`, old values migrated once by
`pdf_handler.migrate_placement`) and `geom` persist the same way and
apply on the first `panel_show`, never from Anki's own saved
`QMainWindow` state. One
`PdfViewer`/`PdfSidebar` instance is reused across tabs. The open tab set,
dock placement, thumbnails, and last-used page persist in
`user_files/pdf_tabs.json` (all writers merge via `pdf_handler._save_tabs_file`,
never overwrite wholesale). `web/copilot.js` only tracks field focus (for
PDF-page-insert targeting) and the image-crop double-click trigger now —
the ghost-text/Ask bridge it used to carry is gone.

### Retained endpoint and page context

The embedded assistant, its process host and session store were removed
in D3 (2026-09-19). [Endpoint](klausmate/anki_endpoint.py) remains with
AnkiConnect-compatible actions and MCP over HTTP. Its existing
`current_view` tool already reads [viewer_context](klausmate/viewer_context.py).
The page store still owns text, transcripts and rendering. D5 implements `current_page` with text and an image when available, private
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
gui_hooks.profile_did_open.append(_migrate_config)                  # legacy chat_*/claude_* key cleanup
gui_hooks.profile_did_open.append(tag_migrate.migrate_on_profile_open)  # one-time klaus:: -> !Library:: rename
gui_hooks.profile_did_open.append(first_run_check)                  # first-run: library root + local-model setup
gui_hooks.profile_did_open.append(setup_readiness_check)
gui_hooks.profile_did_open.append(_start_klaus_endpoint)        # anki_endpoint bind (mw.col must exist)
gui_hooks.editor_did_init.append(on_editor_did_init)                # PDF panel + tab container
gui_hooks.browser_will_show.append(on_browser_will_show)            # Browse toolbar toggles (◧ / ◨)
curation.setup_hooks()                                              # gui_hooks.browser_menus_did_init
pdf_drop.setup()                                                    # PDF drop square + drop wrap on deck screens (independent try/except)
pdf_drive.setup()                                                   # Library window + top-toolbar link (independent try/except)
top_bar.setup()                                                     # toolbar restyle + star logo (independent try/except)
browse_highlight.setup()                                            # Browse search-term highlighting (independent try/except)
heatmap.setup()                                                     # review heatmap on the deck list (independent try/except)
dashboard.setup()                                                   # Control-Center widget editing (independent try/except; MUST stay after heatmap — body order)
window_chrome.setup()                                               # KlausBook chrome for Add/Browse/Stats/reviewer-bar (independent try/except)
gui_hooks.profile_will_close.append(_stop_endpoint_on_profile_close)  # stop the retained endpoint
lecture_view.setup()                                                # review-time Lecture dock (independent try/except)
gui_hooks.profile_did_open.append(_start_lecture_uploader)          # the profile's one lecture_recorder.Uploader
gui_hooks.profile_will_close.append(_stop_lecture_uploader)         # stops every _active_recorders entry FIRST, then the uploader
```

The retained endpoint hooks are `_start_klaus_endpoint` on profile open
and `_stop_endpoint_on_profile_close` on profile close. There is no
assistant teardown or reopen hook. See [bootstrap](klausmate/__init__.py).

`_stop_lecture_uploader` stops every live `Recorder` before it stops the
uploader, not after: a recorder mid-chunk enqueues into that worker, so
tearing the queue down first orphans the WAV it was about to hand over.

`heatmap.setup()` adds four of its own:
`deck_browser_will_render_content` (the panel HTML into `content.stats`),
`webview_will_set_content` (its stylesheet, DeckBrowser only),
`webview_did_receive_js_message` (a clicked day) and `browser_will_search`
(resolving the `klausday:` token those clicks produce).

`pdf_drop.setup()` and `pdf_drive.setup()` are each wrapped in their own
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
(the PDF drop bar, `_PdfBar`), `_klausmate_pdf_container`, `_klausmate_pdf_tabs`,
`_klausmate_sidebar`, `_klausmate_active_pdf`, `_klausmate_vsplit`,
`_klausmate_target_field_index` / `_target_field_name`, `_klausmate_crop_open`.
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
and [migration](klausmate/__init__.py) select Ollama, native vector dimensions and
local transcription paths. Migration removes retired cloud credentials, Plus,
judge and dock settings. The local migration marker preserves later model choices.
General and appearance keys retain their existing roles.

Use `patch_config` for narrow config updates and background writers; it
merges on the main thread. `write_config` replaces the whole stored blob,
so a one-key dict would discard other settings. Preserve legacy-key
cleanup until users have upgraded; D4 explicitly un-retires its local
runtime keys. See [configuration helpers](klausmate/__init__.py).

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| `pypdf` 6.11.0 | Vendored under `klausmate/vendor/`; the sole vendored third-party Python dependency |
| `PyQt6.QtPdf` / `PyQt6.QtPdfWidgets` | Anki's PyQt6 (PDF viewer; graceful fallback if missing) |
| Ollama | Managed local runtime; no cloud embedding fallback |
| whisper.cpp | User-installed local executable and model |
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
- Background work: always `QueryOp` / `without_collection()` for network calls (including local Ollama HTTP calls); UI updates via `mw.taskman.run_on_main` when needed. The lecture recorder's uploader is the one exception and a deliberate one; a plain daemon thread with a FIFO queue, because it must outlive any single dialog or dock and survive a failed chunk; anything it hands back to Qt (`on_segment`, `page_store.subscribe`) is the CONSUMER's job to marshal.
- Import Qt from `aqt.qt`; QtPdf from `PyQt6.QtPdf` behind try/except (`pdf_viewer.py`).
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
Plus, the judge and assistant; D4 restores managed Ollama, D6 replaces
transcription, and D5 exposes the retained endpoint. OCR and Voyage are
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
