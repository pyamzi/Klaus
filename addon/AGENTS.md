# Klausmate — Agent Guide

Klausmate ("Klaus") is an **Anki 2.1 add-on** that adds Copilot-style inline ghost-text autocomplete and a
⌘K "Ask" popover to the card editor, powered by a **local [Ollama](https://ollama.com)** server (Ask can
also be pointed at the Claude API). Lecture PDFs supply retrieval context — BM25 by default, or page-aware
when a PDF tab is open — and any number of them can be docked (above/below/floating) or browsed in a
separate library window. A second, independent stack does semantic deck curation: embedding-based note
search, similarity-based deck copy, and PDF-vs-deck retention scoring.

**Privacy:** autocomplete and ⌘K Ask can run fully on-device via Ollama. No API keys, no cloud calls, and no telemetry are required for that path. Semantic deck search is the exception — it defaults to the **Voyage** cloud embedding API, so card text is sent to Voyage's servers unless you switch `embedding_provider` to `ollama` in settings. Ask can also be switched to the Claude API, which does require an API key.

---

## Repository layout

```
Addons/                       # Git repo root
├── AGENTS.md                 # This file — architecture & dev conventions
├── CLAUDE.md                 # Module map + hard-won gotchas (authority for internals)
├── README.md                 # User-facing install/usage guide
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── scripts/
│   └── package.sh            # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package (copy/symlink into addons21/)
    ├── __init__.py           # Bootstrap, gui_hooks, JS bridge, completion/ask, PDF panel wiring
    ├── ollama_client.py      # Stdlib HTTP client for Ollama (/api/generate, pull, delete)
    ├── ollama_runtime.py     # Managed Ollama download/extract/serve under user_files/runtime/
    ├── ollama_setup.py       # First-run install detection (Homebrew, winget)
    ├── claude_api.py         # Stdlib SSE client for the Anthropic Messages API (Claude Ask brain)
    ├── pdf_handler.py        # PDF import/storage, BM25 retrieval, per-tab state helpers
    ├── pdf_viewer.py         # PdfViewer (QPdfView + selection/highlight overlay, find, thumbnails)
    │                         #   and PdfSidebar (one instance reused across tabs)
    ├── pdf_drive.py          # Klaus PDF drive — Obsidian-style library window (tree + PdfSidebar)
    ├── drive_store.py        # Virtual folder layer + display names for the PDF drive (user_files/drive.json)
    ├── pdf_index.py          # Persistent embedding index over one PDF's text chunks (retention's sibling of card_index.py)
    ├── retention.py          # PDF study-priority scoring: retrievability of cards matched to each PDF
    ├── crop_dialog.py        # Image-crop dialog (crop saved as a new media file)
    ├── curation.py           # Semantic deck curation glue: ensure_index, run_curation, preview via temp tag
    ├── embeddings.py         # Embedding provider abstraction: Ollama (default) / OpenAI / Voyage
    ├── card_index.py         # Persistent embedding index over the user's notes (aqt-free)
    ├── chat_dock.py          # Klaus panel controller — right-side dock hosting web/search.html
    ├── deck_curate.py        # "Curate Deck" button on Anki's deck screens, PDF drop, deck scoping
    ├── anki_tools.py         # Inert collection tools (search/read/create/update notes) for a future agent surface
    ├── settings_ui.py        # KlausSettingsPanel for Preferences / config dialog
    ├── config.json           # Default add-on config
    ├── config.md             # Config key documentation (shown in Anki config UI)
    ├── manifest.json         # Package name and version for non–AnkiWeb distribution
    ├── web/
    │   ├── copilot.js        # Ghost text, debounce, Tab/Esc, Cmd+K ask, cycle hotkeys
    │   ├── copilot.css       # Ghost / hint / ask popover styling
    │   ├── search.html/.css/.js  # Klaus panel UI (chat_dock.py), bridge prefix "klaus:"
    ├── vendor/               # Vendored pure-Python deps (pypdf 6.11.0) — the sole third-party exception
    └── user_files/           # Persisted across upgrades — never write here from a test
        ├── contexts/         # *.txt (BM25) + *.json (per-page text), one pair per imported PDF
        ├── pdfs/             # Stored PDF copies (post-bake, real annotations included)
        ├── pdf_originals/    # Pristine copy captured once, used to regenerate bakes
        ├── annotations/      # Per-PDF highlight/note JSON, source of truth for baking
        ├── pdf_tabs.json     # Open tabs, placement (dock above/below/float), thumbs, last_used
        ├── drive.json        # PDF-drive virtual folders + window geometry (drive_store.py)
        ├── card_index/       # Packed vectors.f32 + manifest.json for semantic deck search
        ├── pdf_index/        # Per-PDF embedding indexes for retention scoring
        ├── objectives/       # Per-PDF free-text study objectives
        └── runtime/          # Klaus-managed Ollama install, versioned subdirectory
```

**Install path:** `addons21/klausmate/` (folder name must be alphanumeric per Anki conventions).

**Do not store user data outside `user_files/`** — everything else in the add-on folder is wiped on upgrade.

---

## Architecture

### End-to-end autocomplete

```
Editor field (contenteditable, shadow DOM)
    │ keystroke → debounce (config.debounce_ms)
    ▼
web/copilot.js
    │ pycmd("klausmate:complete:<base64 json>")
    ▼
__init__.py :: on_js_message
    │ retrieve_chunks_for() → build_prompt() → clean_completion()
    ▼
ollama_client.OllamaClient.generate()  →  POST /api/generate
    ▼
editor.web.eval("window.klausmate.onCompletion({...})")
    ▼
copilot.js inserts inline ghost <span>; Tab replaces span with real text
```

All Ollama/network work uses `QueryOp.without_collection().run_in_background()` so the Anki UI never blocks.

### Two LLM interaction modes

| Mode | Trigger | Python entry | Max tokens (typical) |
|------|---------|--------------|----------------------|
| **Autocomplete** | Typing (debounced) | `request_completion` | 8–120 by `completion_mode` |
| **Ask** | `ask_hotkey` (default `Cmd+K`) | `request_ask` | 600 |

Shared pieces: `retrieve_chunks_for`, `extract_card_ctx`, `strip_markdown`, `OllamaClient`.

Cycling alternates (`Cmd+Shift+]` / `Cmd+Shift+[`) reuses `request_completion` with `variant=True` and an `avoid` list of previously-shown candidates.

### PDF context retrieval (two paths)

1. **BM25 (default):** `pdf_handler.retrieve_relevant_chunks()` chunks `user_files/contexts/*.txt` (~400 chars, 50 overlap), scores against field text, returns top-K.
2. **Page-aware (dock):** When `editor._klausmate_active_pdf = (name, (start, end))` is set by the active tab's `PdfSidebar`, the visible page ±1 is injected as a synthetic chunk with sentinel `score=999.0` (see `retrieve_chunks_for`), bypassing BM25.

`choose_mode()` may auto-promote to `long` when the field ends with a list/definition cue **and** the top retrieval score ≥ 6.0.

`retrieval_method: "semantic"` exists in config as a placeholder — it currently logs a warning and falls back to `keyword` (BM25). It is unrelated to the semantic *deck curation* stack below, which is fully implemented.

### Multi-PDF tab model

Klausmate can have **any number of PDFs open at once**, each in its own tab inside `_PdfTabContainer` (`__init__.py`), one bar of chrome per editor window: `[tabs ✕] [page n/m] [＋]`. The panel docks ABOVE or BELOW the note-editor pane (wrapping `editor.widget` in a `QSplitter`), or floats as a real, parentless macOS window — dragged out via native `startSystemMove()` with a watchdog/ghost fallback for when that call lies about succeeding. One `PdfViewer`/`PdfSidebar` instance is reused across tabs; switching tabs loads that PDF and repoints `editor._klausmate_active_pdf`, so autocomplete/Ask retrieval always follows the visible tab. The open tab set, dock placement, thumbnails, and last-used page persist in `user_files/pdf_tabs.json` (all writers merge via `pdf_handler._save_tabs_file`, never overwrite wholesale).

A separate **Klaus PDF drive** window (`pdf_drive.py`) is an Obsidian-style library over every imported PDF — a tree of virtual folders (`drive_store.py`, `user_files/drive.json`; nothing on disk actually moves) next to a standalone `PdfSidebar`. Each row shows a retention score computed by `retention.py` from cached match/retrievability artifacts.

### Hooks registered at import

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)
gui_hooks.profile_will_close.append(_chat_profile_close)                 # persist Klaus panel dock state
# Klaus panel toggle: native top-right tray slot when available, else the
# centered link row — same handler, hook picked by hasattr() at import time.
gui_hooks.top_toolbar_will_set_right_tray_content.append(on_top_toolbar_right_tray)
# or: gui_hooks.top_toolbar_did_init_links.append(on_top_toolbar_right_tray)
gui_hooks.webview_will_set_content.append(on_webview_will_set_content)   # inject JS/CSS + runtime config
gui_hooks.webview_did_receive_js_message.append(on_js_message)           # pycmd routing ("klausmate:" prefix)
gui_hooks.editor_will_munge_html.append(strip_ghost_html)                # never persist ghost spans
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)   # right-click PDF/crop actions
gui_hooks.main_window_did_init.append(install_menu)                      # Tools → Klaus
gui_hooks.main_window_did_init.append(install_preferences)               # Edit → Preferences embed
curation.setup_hooks()                                                   # semantic curation gui_hooks (search bridge, Browse wiring)
gui_hooks.profile_did_open.append(_migrate_config)                       # legacy chat_* -> klaus_engine/claude_*
gui_hooks.profile_did_open.append(first_run_check)                       # Ollama onboarding
gui_hooks.profile_did_open.append(setup_readiness_check)                 # re-warn after install
gui_hooks.editor_did_init.append(on_editor_did_init)                     # panel + PDF tab container
gui_hooks.browser_will_show.append(on_browser_will_show)                 # Browse toolbar toggles (◧ / ◨)
deck_curate.setup()                                                      # "Curate Deck" on deck screens (independent try/except)
pdf_drive.setup()                                                        # Klaus PDF drive window (independent try/except)
```

`deck_curate.setup()` and `pdf_drive.setup()` are each wrapped in their own `try/except` at import time — a
failure in one must not cost the user the other, or the editor features above.

Note: there is deliberately **no** `gui_hooks.editor_did_focus_field` registration. That hook fires as
`(note: Note, current_field_idx: int)` — it does not hand back the `Editor`, so it cannot drive target-field
tracking reliably. Target-field tracking rides the `"focus"` JS-bridge message instead (see below):
`copilot.js` sends `"klausmate:focus"` with the field name, and `on_js_message` receives the owning `Editor`
as its `context`.

`on_webview_will_set_content` only runs for `Editor` contexts and injects `window.klausmateConfig` (debounce, hotkeys, cooldowns, completion mode, enabled flags).

### JS ↔ Python message protocol

Two independent bridges exist, split by `pycmd` prefix and routed in separate handlers:

**Editor bridge** (`web/copilot.js` → `on_js_message` in `__init__.py`, prefix `"klausmate:"`, split `":", 2`).
Payloads are **base64-encoded JSON** after the action name:

| Action | JS → Python | Python → JS |
|--------|-------------|-------------|
| `complete` | `{id, text, avoid?, variant?}` | `klausmate.onCompletion({id, completion, source, variant})` |
| `ask` | `{id, prompt, text}` | `klausmate.onAskResult({id, text})` |
| `focus` | `{field}` | — (sets `editor._klausmate_target_field_index` / `_target_field_name`) |
| `crop` | `{...}` | opens `crop_dialog.py` for the referenced image |
| `log` | plain string | — |
| `dbg` | plain string | — (debug-only tracing) |

**Klaus panel bridge** (`web/search.js` → `chat_dock.py`, prefix `"klaus:"`, e.g. the JS-pushed `"klaus:ready"`
on `DOMContentLoaded`). This is the semantic-curation search UI's own protocol and is independent of the
editor's ghost-text bridge above.

### Ghost text (important)

Ghost suggestions are **inline** `<span data-klausmate-ghost>` nodes inside the contenteditable (not a fixed overlay). A separate fixed-position hint label shows "Tab to accept" and optional source attribution. `editor_will_munge_html` strips any stray ghost spans before save.

`copilot.js` only auto-triggers when the caret is at the **end** of the field and the character before the caret is whitespace (mid-word does not fire). Cycle hotkeys reuse the active ghost; pressing past the last candidate requests a fresh `variant`.

### PDF viewer (`pdf_viewer.py`)

- One `QPdfView` in **MultiPage / FitToWidth** mode inside a `PdfSidebar` widget.
- Layout math mirrors Qt's `QPdfViewPrivate::calculateDocumentLayout` (screen DPI / 72, margins, page spacing, centered page width) — required so hit-testing and selection highlights line up.
- Text selection: viewport `eventFilter` drags map to `(page, QPointF)` via `_viewport_to_page_point`; `QPdfDocument.getSelection()` is called per page (multi-page drags supported); highlights painted by `_SelectionOverlay` using `QPdfSelection.bounds()`.
- **Cmd+C** and right-click **Copy** copy selected text to the clipboard.
- Toolbar **Copy page** renders the current page at ~150 DPI and puts the image on the clipboard.

### Semantic curation stack (replaced the old Klaus chat panel)

A second, independent feature line embeds notes and PDFs for similarity search — it does not touch the
autocomplete/Ask path above:

- `embeddings.py` (aqt-free): provider abstraction over Ollama `/api/embed` (default, `nomic-embed-text`),
  OpenAI, and Voyage. Vectors are unit-normalized at write time.
- `card_index.py` (aqt-free) and `pdf_index.py` (aqt-free): persistent embedding indexes — packed
  `array('f')` vectors + a JSON manifest — over notes and per-PDF text chunks respectively. `top_k` ranks via
  `math.sumprod` over memoryviews (no numpy in Anki's venv).
- `curation.py` (aqt glue): `ensure_index` / `run_curation`, preview via a temporary `klaus::curate` tag,
  undoable deck copy.
- `retention.py`: turns the PDF index + card index into a per-PDF retrievability/study-priority score,
  consumed by the PDF drive.
- `chat_dock.py`: the Klaus panel controller (hosts `web/search.html/.css/.js`, bridge prefix `"klaus:"`).
- `claude_api.py` (aqt-free): powers the Claude option for ⌘K Ask (`klaus_engine` / `claude_api_key` config).
- `anki_tools.py`: inert collection tools, kept and tested, for a future agent surface — not wired into any
  hook today.

---

## Configuration

- Defaults: `klausmate/config.json`
- User overrides: stored in `meta.json` by Anki's add-on manager
- UI: **Tools → Klaus → Settings…**, **Edit → Preferences** (Klaus group via `install_preferences` + `KlausSettingsPanel`), **Tools → Add-ons → Klausmate → Config** (`open_config` → Settings dialog)
- Key docs: `klausmate/config.md`

Notable keys: `autocomplete_model`, `ask_model`, `endpoint`, `completion_mode` (`word` | `phrase` | `sentence` | `paragraph` | `long`), `temperature`, `top_p`, `top_k`, `repeat_penalty`, `retrieval_top_k`, `retrieval_method` (`keyword` only; `semantic` logs and falls back), `ask_hotkey`, `cycle_forward_hotkey`, `cycle_backward_hotkey`, debounce/cooldown timings, `system_prompt`, `ask_system_prompt`, feature toggles `autocomplete_enabled` / `ask_enabled` / `image_crop_enabled`.

Semantic-curation and Claude-Ask keys (all in the same `config.json`): `chat_hotkey` (Klaus panel toggle,
default `Ctrl+Shift+K`), `klaus_engine` (`ollama` default | `claude`), `claude_api_key`, `claude_model`,
`claude_timeout_s`, `embedding_provider` (`voyage` default | `openai` | `ollama`), `embedding_model`,
`embedding_api_key_openai` / `embedding_api_key_voyage`, `curate_top_k`, `curate_min_score`,
`pdf_match_threshold`, `pdf_match_agg`, `pdf_index_max_chunks`. `browser_dock_enabled` is a dead legacy key
kept only so old `meta.json` files don't error. `_migrate_config()` (on `profile_did_open`) renames legacy
`chat_*` keys to `klaus_engine` / `claude_*` — keep it until users have upgraded.

Mode-specific `max_tokens` and Ollama `stop` sequences are defined in `_MODE_PARAMS` in `__init__.py`, not in config.

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| Ollama | User-installed, or Klaus-managed under `user_files/runtime/` via `ollama_runtime.py` |
| `pypdf` 6.11.0 | Vendored under `klausmate/vendor/` — the **sole** third-party dependency |
| `PyQt6.QtPdf` / `PyQt6.QtPdfWidgets` | Anki's PyQt6 (PDF viewer; graceful fallback if missing) |
| Anthropic Messages API | Optional, `claude_api.py`, only when `klaus_engine=claude` |
| Voyage / OpenAI embedding APIs | Optional, `embeddings.py`, only when `embedding_provider` selects them |

Every network client (`ollama_client.py`, `claude_api.py`, `embeddings.py`) is **stdlib only**
(`urllib`/SSE parsing by hand) — no `requests`, no `anthropic`/`openai` SDKs (they need compiled
`pydantic-core`, which is banned), no bundled wheels. No numpy either — Anki's venv doesn't have it, so
`card_index.py`/`pdf_index.py` do ranking with `math.sumprod` over `array('f')` memoryviews.

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

Produces `dist/klausmate.ankiaddon`. The script stages files to a tempdir, bumps `manifest.json` `mod`, and zips with these rules:

- Build from **inside** the staging dir (the zip must NOT contain a `klausmate/` wrapper folder — AnkiWeb rejects those).
- Strip every `__pycache__`/`*.pyc`/`.DS_Store` (AnkiWeb rejects archives that contain them).
- Exclude `meta.json` (per-user config) and all `user_files/` contents except `README.txt` (per-user runtime data).

### Type checking

```sh
pip install mypy "aqt[qt6]"
mypy klausmate
```

---

## Code conventions (this project)

- Prefer **gui_hooks** over monkey-patching.
- Background work: always `QueryOp` / `without_collection()` for Ollama; UI updates via `mw.taskman.run_on_main` when needed.
- Import Qt from `aqt.qt`; QtPdf from `PyQt6.QtPdf` behind try/except (`pdf_viewer.py`).
- Editor-attached state via attributes (all `editor._klausmate_*`, guarded with `getattr(..., None)` /
  `is None` checks to stay reload-safe): `_klausmate_panel`, `_klausmate_pdf_container`,
  `_klausmate_pdf_tabs`, `_klausmate_sidebar`, `_klausmate_active_pdf`, `_klausmate_vsplit`,
  `_klausmate_target_field_index` / `_target_field_name`, `_klausmate_crop_open`,
  `_klausmate_sidebar_toggle_btn` / `_editor_toggle_btn`, `_klausmate_search_popover`,
  `_klausmate_settings`, `_klausmate_shortcuts`.
- Post-process all model output through `clean_completion()` (autocomplete) or `strip_markdown()` (ask).
- When adding config keys: update `config.json`, `config.md`, the dialog in `open_settings_dialog`, the Preferences embed in `install_preferences`, and any `klausmateConfig` fields injected in `on_webview_will_set_content`.

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
