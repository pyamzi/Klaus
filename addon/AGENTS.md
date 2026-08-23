# Klausmate — Agent Guide

Klausmate is an **Anki 2.1 add-on** that adds Copilot-style inline ghost-text autocomplete to the card editor, powered by a **local [Ollama](https://ollama.com)** server. A drop-in lecture PDF supplies retrieval context (BM25), and the Add window can dock a native PDF viewer beside the editor for page-aware retrieval.

**Privacy:** autocomplete and ⌘K Ask can run fully on-device via Ollama. No API keys, no cloud calls, and no telemetry are required for that path. Semantic deck search is the exception — it defaults to the **Voyage** cloud embedding API, so card text is sent to Voyage's servers unless you switch `embedding_provider` to `ollama` in settings. Ask can also be switched to the Claude API, which does require an API key.

---

## Repository layout

```
Klausmate/                    # Git repo root
├── AGENTS.md                 # This file — architecture & dev conventions
├── README.md                 # User-facing install/usage guide
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── scripts/
│   └── package.sh            # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package (copy/symlink into addons21/)
    ├── __init__.py           # Hooks, menus, completion/ask routing, panel, dock
    ├── ollama_client.py      # Stdlib HTTP client for Ollama (/api/generate, pull, delete)
    ├── ollama_setup.py       # First-run install detection (Homebrew, winget)
    ├── pdf_handler.py        # PDF extraction, BM25 retrieval, single active-PDF state
    ├── pdf_viewer.py         # Native QPdfView, text selection, Copy / Copy page (image)
    ├── settings_ui.py        # KlausSettingsPanel for Preferences / config dialog
    ├── config.json           # Default add-on config
    ├── config.md             # Config key documentation (shown in Anki config UI)
    ├── manifest.json         # Package name and version for non–AnkiWeb distribution
    ├── web/
    │   ├── copilot.js        # Ghost text, debounce, Tab/Esc, Cmd+K ask, cycle hotkeys
    │   └── copilot.css       # Ghost / hint / ask popover styling
    ├── vendor/               # Vendored pure-Python deps (pypdf) — optional at runtime
    └── user_files/           # Persisted across upgrades
        ├── contexts/         # *.txt (BM25) + *.json (per-page text)
        ├── pdfs/             # Raw PDF copies for QPdfView
        └── active_pdf.txt    # Name of the currently loaded lecture PDF
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
2. **Page-aware (dock):** When `editor._klausmate_active_pdf = (name, (start, end))` is set by `PdfSidebar`, the visible page ±1 is injected as a synthetic chunk with sentinel `score=999.0` (see `retrieve_chunks_for`), bypassing BM25.

`choose_mode()` may auto-promote to `long` when the field ends with a list/definition cue **and** the top retrieval score ≥ 6.0.

### Single-PDF model

Klausmate keeps **one active lecture PDF at a time**, stored in `user_files/active_pdf.txt`. Loading a new PDF replaces the old one (after confirmation). The migration helper `pdf_handler.migrate_to_single_pdf` is invoked on `editor_did_init` to clean up legacy multi-PDF state.

### Hooks registered at import

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)
gui_hooks.webview_will_set_content.append(on_webview_will_set_content)  # inject JS/CSS + runtime config
gui_hooks.webview_did_receive_js_message.append(on_js_message)           # pycmd routing
gui_hooks.editor_will_munge_html.append(strip_ghost_html)                # never persist ghost spans
gui_hooks.main_window_did_init.append(install_menu)                      # Tools → Klaus
gui_hooks.main_window_did_init.append(install_preferences)               # Edit → Preferences embed
gui_hooks.profile_did_open.append(first_run_check)                       # Ollama onboarding
gui_hooks.profile_did_open.append(setup_readiness_check)                 # re-warn after install
gui_hooks.editor_did_init.append(on_editor_did_init)                     # panel + PDF dock
gui_hooks.editor_did_focus_field.append(_on_editor_field_focus)          # remember target field
gui_hooks.browser_will_show.append(on_browser_will_show)                 # Browse-window wiring
```

`on_webview_will_set_content` only runs for `Editor` contexts and injects `window.klausmateConfig` (debounce, hotkeys, cooldowns, completion mode, enabled flags).

### JS ↔ Python message protocol

Payloads are **base64-encoded JSON** after the action name:

| Action | JS → Python | Python → JS |
|--------|-------------|-------------|
| `complete` | `{id, text, avoid?, variant?}` | `klausmate.onCompletion({id, completion, source, variant})` |
| `ask` | `{id, prompt, text}` | `klausmate.onAskResult({id, text})` |
| `focus` | `{field}` | — (sets `editor._klausmate_target_field_index`) |
| `log` | plain string | — |

### Ghost text (important)

Ghost suggestions are **inline** `<span data-klausmate-ghost>` nodes inside the contenteditable (not a fixed overlay). A separate fixed-position hint label shows "Tab to accept" and optional source attribution. `editor_will_munge_html` strips any stray ghost spans before save.

`copilot.js` only auto-triggers when the caret is at the **end** of the field and the character before the caret is whitespace (mid-word does not fire). Cycle hotkeys reuse the active ghost; pressing past the last candidate requests a fresh `variant`.

### PDF viewer (`pdf_viewer.py`)

- One `QPdfView` in **MultiPage / FitToWidth** mode inside a `PdfSidebar` widget.
- Layout math mirrors Qt's `QPdfViewPrivate::calculateDocumentLayout` (screen DPI / 72, margins, page spacing, centered page width) — required so hit-testing and selection highlights line up.
- Text selection: viewport `eventFilter` drags map to `(page, QPointF)` via `_viewport_to_page_point`; `QPdfDocument.getSelection()` is called per page (multi-page drags supported); highlights painted by `_SelectionOverlay` using `QPdfSelection.bounds()`.
- **Cmd+C** and right-click **Copy** copy selected text to the clipboard.
- Toolbar **Copy page** renders the current page at ~150 DPI and puts the image on the clipboard.

---

## Configuration

- Defaults: `klausmate/config.json`
- User overrides: stored in `meta.json` by Anki's add-on manager
- UI: **Tools → Klaus → Settings…**, **Edit → Preferences** (Klaus group via `install_preferences` + `KlausSettingsPanel`), **Tools → Add-ons → Klausmate → Config** (`open_config` → Settings dialog)
- Key docs: `klausmate/config.md`

Notable keys: `autocomplete_model`, `ask_model`, `endpoint`, `completion_mode` (`word` | `phrase` | `sentence` | `paragraph` | `long`), `temperature`, `top_p`, `top_k`, `repeat_penalty`, `retrieval_top_k`, `retrieval_method` (`keyword` only; `semantic` logs and falls back), `ask_hotkey`, `cycle_forward_hotkey`, `cycle_backward_hotkey`, debounce/cooldown timings, `system_prompt`, `ask_system_prompt`, feature toggles `autocomplete_enabled` / `ask_enabled`.

Mode-specific `max_tokens` and Ollama `stop` sequences are defined in `_MODE_PARAMS` in `__init__.py`, not in config.

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| Ollama | User-installed, `localhost:11434` |
| `pypdf` | Vendored under `klausmate/vendor/` (optional at runtime — `PDF_AVAILABLE` flag) |
| `PyQt6.QtPdf` / `PyQt6.QtPdfWidgets` | Anki's PyQt6 (PDF viewer; graceful fallback if missing) |

`ollama_client.py` uses **stdlib only** (`urllib`) — no `requests`, no bundled wheels.

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
- Editor-attached state via attributes: `_klausmate_panel`, `_klausmate_dock`, `_klausmate_sidebar`, `_klausmate_active_pdf`, `_klausmate_target_field_index`.
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
