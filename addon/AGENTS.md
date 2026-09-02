# Klausmate — Agent Guide

Klausmate ("Klaus") is an **Anki 2.1 add-on**. It has one AI-powered
capability — semantic search over your notes and lecture PDFs — which
powers the **Library**: a window over your imported lecture PDFs where each
one is indexed, the cards it covers are tagged with its own `!Library` tag,
and a per-PDF retention/study-priority score says how well you still recall
them. Copying a set of those cards into a new deck is a separate, manual
Browse action. A
native PDF viewer (selection, highlights, sticky notes baked in as real
annotations) and an image-crop dialog round out the add-on. There is no
autocomplete and no chat panel — both were removed in 2026-08, along with
the Claude/Anthropic integration that powered them (see "What used to be
here" below if you're archaeology-diving through git history) — though
Claude is back since 2026-09-02, in a different shape, as the Claude Code
CLI behind the assistant dock (see "The assistant" below).

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
    ├── curation.py             # Card index build (ensure_index) + the undoable Browse deck copier
    ├── pdf_drop.py             # PDF drop square + MainWebView.dropEvent wrap on the deck list / overview screens
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

### Semantic card matching (indexing a PDF)

```
Library row → right-click → "Add to Search Index" / "Update Search Index"
        │
        ▼
pdf_drive.py :: _on_embed(safe) — FOUR phases, one cancel token threaded
        │        through all of them (K-146)
        ▼
curation.py :: ensure_index() — sync the card index (only new/edited notes
        │        re-embed; text-hash diffed). This is the only user-facing
        │        path that refreshes it; the Curate button used to do it
        │        invisibly, which is why K-146 had to add it here.
        ▼
embeddings.py — Voyage / OpenAI / Ollama, unit-normalized vectors
        │
        ▼
card_index.py — user_files/card_index/: packed float32 vectors + manifest,
        │        top-K via math.sumprod over memoryviews (no numpy)
        ▼
retention.py :: ensure_pdf_index() → ensure_matches() — embed the PDF's
        │        chunks, score every indexed note (max cosine, cached in
        │        matches.json)
        ▼
tag_sync.py :: sync_after_matches() — the notes at/above this PDF's
          sensitivity threshold become the members of its one
          "!Library::<folder>::<leaf>" tag
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
retention.py — per PDF: embed its chunks (pdf_index.py) → score every
        │       indexed note against those chunks (max cosine, cached in
        │       matches.json) → pull FSRS retrievability for matched cards
        │       → aggregate into a study-priority score
        ▼
Library row shows the score; right-click can index/re-index, adjust match
sensitivity, show matches in Browse (it hops to the PDF's own !Library tag —
the "!Library::Matching" preview tag was retired in K-055), suspend or
unsuspend its cards, or chart its retention history
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

### The assistant

```
assistant_dock.py — the QDockWidget on Anki's main window (Ctrl+Shift+K,
        │  Tools → Klaus Assistant, or a Library toolbar button)
        ▼
viewer_context.py :: current() — the LAST ACTIVATED PdfSidebar (Library,
        │  Browse's editor pane, or the Lecture dock) that still has a
        │  document open, plus its page and selection
        ▼
page_ocr.py :: context_for() — that page as OCR'd text (cached) or the
        │  PDF's own text layer, plus a rendered PNG
        ▼
agent_host.py :: build_turn() — one stream-json user message (text +
        │  a "[Klaus context]" block + image) written to the `claude`
        │  child's stdin; a reader thread parses its stdout stream back
        ▼
anki_endpoint.py — mcp__klaus__* tool calls from the child arrive here
           over HTTP (see "Localhost endpoint" below); reads run right
           away, writes wait on an approval dialog
```

One assistant, one engine: Klaus hosts the **Claude Code CLI** as a
child process (`agent_host.py`) rather than running a chat loop of its
own — no API keys stored in Klaus, the user's own `claude` login and
subscription pay for it. Six modules, one concern each:
`agent_host.py` (finds, spawns, and streams with the `claude` binary —
binary discovery falls back to the user's login shell before known
install paths, since a GUI-launched Anki has a minimal `PATH`),
`anki_endpoint.py` (the localhost server both the wider AnkiConnect
ecosystem and the child's own MCP tools reach), `viewer_context.py` (a
registry of every live `PdfSidebar`; the assistant follows whichever one
was activated last), `page_ocr.py` (the followed page as text — OCR
through a local Ollama vision model, or the PDF's text layer — plus
image, cached per PDF digest and page under `user_files/ocr/`),
`assistant_sessions.py` (one Claude Code session id per PDF, plus slash-
command prompt files, under `user_files/assistant/`), and
`assistant_dock.py` itself (header, transcript, input, Send/Stop, New
Session, slash completion).

Every write the assistant makes — adding a note, editing fields, tagging
— goes through the SAME kind of plain-text approval dialog Klaus shows
for any other write (deck, every field, tags, the source page); a
declined or timed-out approval comes back to the model as an error, not
a silent no-op. Cards the assistant adds carry `klaus::assistant` and
`klaus::from::<pdf_safe>` — never the PDF's own `!Library` tag, which is
`tag_sync`'s membership invariant and would be wrong to set by hand; the
next index pass tags the card for real if it actually matches.

Design: `docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md`.
Per-module non-obvious rules are in CLAUDE.md's module map.

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
gui_hooks.profile_did_open.append(first_run_check)                  # embeddings-provider onboarding
gui_hooks.profile_did_open.append(setup_readiness_check)
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
```

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

`anki_endpoint.py` serves the assistant's Anki reach — and, incidentally,
anything else that speaks AnkiConnect's wire protocol — from a
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
  Klaus-only ones — `klausSearchNotes` (semantic), `klausSearchLecturePdfs`
  (semantic, over the indexed lecture PDFs), and `klausCurrentView` (what
  `viewer_context` says the user is looking at). Anything else answers
  `"unsupported action"`. A request carrying `X-Klaus-Agent: 1` (the
  `/mcp` route sets this) additionally requires `addNote`'s
  `params.note.options.sourcePage` — a card proposed with no source page
  is an error, never a silent add.
- **`/mcp`** — the same actions as MCP tools, JSON-RPC 2.0 over POST (no
  SSE stream), for the `claude` child's `--mcp-config`: `initialize`,
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
create/update and semantic search rather than a second implementation.
See CLAUDE.md's module map for the approval-dialog and card-tagging
rules.

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

Notable keys: `embedding_provider` (`voyage` default | `openai` | `ollama`),
`embedding_model`, `embedding_api_key_voyage` / `embedding_api_key_openai`,
`pdf_match_threshold`, `pdf_match_agg`,
`pdf_index_max_chunks`, `endpoint` (Ollama server URL), `runtime_auto_setup`
(Klaus manages its own local Ollama install when needed), `image_crop_enabled`,
`klausbook_design` (default false — master switch for the design
layer: toolbar/bottombar restyle, backgrounds, frosted panels,
dashboard editing; tools always work),
`heatmap_enabled` (the review heatmap under the deck list),
`dashboard_order` (deck-screen widget order; written by the dashboard's
right-click → Edit Widgets mode — drag to reorder, ⊖/＋ toggle the
per-widget bools). The assistant's own keys: `ocr_enabled` (default
true — OCR a lecture page through a local vision model when it has no
text layer), `ocr_model` (default `"glm-ocr"`), `claude_binary` (path
override for the `claude` executable; default `""` auto-detects),
`assistant_model` (which Claude model the assistant runs; default `""`
= Claude Code's own default), `assistant_reopen` (default false —
reopen the Assistant dock on the next Anki start), and
`assistant_dock_width` (default `420` — the dock's last width, written
by dragging it, not a Preferences row).

`_migrate_config()` (on `profile_did_open`) cleans up legacy `chat_*` /
`claude_*` config keys left over from the deleted Ask-on-Claude feature,
plus (retired 2026-09-01) `assistant_api_key` / `assistant_backend` /
`assistant_token` — the hosted/bring-your-own-key split those keys were
for was cut back to Claude Code's own login before it ever shipped —
keep both cleanups until users have upgraded past them.

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
`copilot.js`'s ghost-text/Ask bridge, `claude_api.py`, `settings_ui.py`,
and `chat_dock.py` (the "Klaus panel") were all deleted, along with the
`autocomplete_model` / `ask_model` / `klaus_engine` / `claude_*` config
keys and the Browse natural-language search. (`anki_tools.py` was
deleted in that same pass — it is no longer gone: it came back on
2026-09-01 as the collection tool layer the new assistant calls; see
"The assistant" above.) What remains from that era — the Library,
semantic card matching, the PDF viewer, and image cropping — plus the
assistant added 2026-09-02, is everything above. Don't resurrect
autocomplete/Ask/chat-panel language in docs or comments; if you find
some, it's stale, not a spec.

A second, much shorter-lived surface came and went the same week. Pouya's
2026-09-01 plan for an AI assistant first took the shape of a chat panel
in the Library (`assistant_panel.py`, its own session store
`assistant_session.py`) fed by a direct-API streaming client
(`llm_client.py`) and an advisory tier check (`entitlement.py`), with a
companion podcast-script generator (`podcast.py`) — all deleted
2026-09-02 when Pouya converged the design onto hosting the Claude Code
CLI instead (`assistant_dock.py`: one dock, one engine). Config keys
`assistant_api_key` / `assistant_backend` / `assistant_token` were
dropped with them — there is no separate assistant credential; the
user's own `claude` login is it. `card_forge.py` and `anki_tools.py` are
the two pieces of that plan that DID survive, now wired into the
endpoint rather than dormant. See CLAUDE.md's header and module map for
the exact commits. Don't resurrect a hosted/bring-your-own-key split, a
separate podcast feature, or a Library-panel assistant — the assistant
is `assistant_dock.py`.

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
