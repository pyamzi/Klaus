# Klausmate — Local AI for Anki

Copilot-style **inline ghost-text autocomplete** for Anki's card editor, powered by a **local** LLM via [Ollama](https://ollama.com). Optionally ground suggestions in your **lecture PDF** with BM25 retrieval and a built-in PDF viewer.

> No data leaves your computer. No API keys. No subscription. No telemetry.

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY)

---

## What it does

| Feature | How to use |
|---------|------------|
| **Ghost autocomplete** | Type in any editor field (Add / Browse). After a pause, gray italic text appears at the cursor. **Tab** accept · **Esc** dismiss · keep typing to ignore. |
| **Cycle suggestions** | **Cmd+Shift+]** / **Cmd+Shift+[** (configurable) — browse alternate completions; past the last one, Klaus requests a new variant. |
| **Inline Ask** | **Cmd+K** (configurable) — popover for a free-form instruction ("make this a cloze", "rephrase this", "shorten", …). Replaces or fills the focused field. |
| **PDF context** | Drop a lecture PDF into the editor panel; relevant chunks are injected into prompts automatically (BM25). |
| **PDF dock** *(Add window)* | Toggle with **◨** on the editor panel. Native PDF viewer beside your cards — the page you're viewing becomes the primary context. |
| **PDF text copy** | Drag-select text in the viewer, then **Cmd+C** or right-click **Copy**. |
| **PDF page → image** | Toolbar **Copy page** button copies the current page as an image to the clipboard. Paste with **Cmd+V**. |

Autocomplete only fires when the caret is at the **end** of the field and you're starting a new word (whitespace before the cursor). Mid-word edits, selections, IME composition, and recent paste/dismiss/accept events suppress it.

---

## Requirements

- [Anki](https://apps.ankiweb.net/) **23.10+** (Qt 6.5+ for the PDF viewer; everything else works on earlier 23.10+ builds)
- [Ollama](https://ollama.com/download) running locally (`http://localhost:11434`)
- `pypdf` — bundled under `klausmate/vendor/`; PDF features are disabled if it's missing

---

## Installation

### 1. Install Ollama

Download from [ollama.com/download](https://ollama.com/download). The background server listens on port **11434**.

If Ollama isn't installed yet, open **Tools → Klaus → Manage models…** in Anki — Klaus shows an install page with a link to the download site and, on macOS (Homebrew) or Windows (winget), an optional one-click install command (with confirmation before anything runs).

### 2. Pull a model

```sh
ollama pull qwen3:0.6b      # fastest, ~0.8 GB — good starting point
ollama pull qwen3:4b        # balanced, ~2.5 GB (default for Ask)
ollama pull qwen3:8b        # best quality, ~5.2 GB
ollama pull llama3.2:3b     # general alternative, ~2 GB
```

You can also pull, switch, and delete models from **Tools → Klaus → Manage models…** inside Anki.

### 3. Install the add-on

**From `.ankiaddon`** *(recommended)*: build or download `dist/klausmate.ankiaddon`, then in Anki use **Tools → Add-ons → Install from file…** and select it. Restart Anki.

**Manual (dev):** symlink or copy the `klausmate/` folder into your Anki `addons21/` directory, then restart Anki. Find `addons21/` via **Tools → Add-ons → View Files**.

To rebuild the package from source:

```sh
./scripts/package.sh
```

### 4. (Optional) Vendor pypdf yourself

If your copy lacks `klausmate/vendor/pypdf/`:

```sh
cd klausmate
pip install --target vendor pypdf
```

Restart Anki. Without pypdf, autocomplete and Ask still work — only PDF upload/viewer are disabled.

---

## Usage

### Autocomplete

1. Open **Add** or **Browse** and edit a card field.
2. Type until the caret is at the end of a word boundary (`"mitral valve |"` triggers; `"mitral|"` does not).
3. Wait for the ghost suggestion → **Tab** to insert.
4. **Cmd+Shift+]** / **Cmd+Shift+[** cycle through alternates; past the last one Klaus fetches a fresh variant.

### Ask (Cmd+K)

1. Place the caret in a field.
2. Press **Cmd+K** (or your configured `ask_hotkey`).
3. Type an instruction and submit — the result replaces or fills the field with a typing animation.

### Lecture PDF (one at a time)

- **Editor panel** (below the tag bar in Add / Browse) — drag-and-drop or **Browse…** to load your lecture PDF. Loading a new file asks to replace the current one.
- **PDF dock** (Add window only) — toggle with **◨** on the panel. One continuous scrollable PDF; Klaus uses the visible page (±1) as primary context, overriding BM25 while open.
- **In the viewer:**
  - Drag-select text, then **Cmd+C** or right-click **Copy**.
  - **Copy page** in the toolbar copies the current page as an image to the clipboard — paste with **Cmd+V**.

Extracted text and the raw PDF live under `addons21/klausmate/user_files/` (`contexts/`, `pdfs/`).

### Settings & models

- **Tools → Klaus → Settings…** — models, sampling, completion length, hotkeys, retrieval top-K, prompts.
- **Tools → Klaus → Manage models…** — pull / delete / pick your autocomplete and Ask models.
- **Tools → Klaus → Test connection** — verify Ollama is reachable.
- **Tools → Add-ons → Klausmate → Config** — opens the same Settings dialog.
- **Edit → Preferences** — Klaus group with the most common knobs.

---

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `autocomplete_model` | `qwen3:0.6b` | Model for inline ghost autocomplete |
| `ask_model` | `qwen3:4b` | Model for Cmd+K Ask |
| `endpoint` | `http://localhost:11434` | Ollama server URL |
| `generate_timeout_s` | `180` | Timeout for long generations |
| `completion_mode` | `sentence` | `word` · `phrase` · `sentence` · `paragraph` · `long` |
| `temperature` | `0.2` | Sampling temperature |
| `top_p` | `0.9` | Nucleus sampling |
| `top_k` | `40` | Top-k sampling |
| `repeat_penalty` | `1.1` | Repetition penalty |
| `ask_hotkey` | `Cmd+K` | Inline Ask popover |
| `cycle_forward_hotkey` | `Cmd+Shift+]` | Next suggestion |
| `cycle_backward_hotkey` | `Cmd+Shift+[` | Previous suggestion |
| `debounce_ms` | `400` | Idle ms before autocomplete request |
| `min_chars_before_trigger` | `8` | Minimum field length before autocomplete |
| `paste_cooldown_ms` | `800` | Suppress after paste |
| `dismissal_cooldown_ms` | `600` | Suppress after Esc-dismiss |
| `accept_cooldown_ms` | `200` | Suppress after Tab-accept |
| `retrieval_top_k` | `4` | BM25 chunks injected per request |
| `retrieval_method` | `keyword` | BM25 today; `semantic` reserved (falls back) |
| `autocomplete_enabled` | `true` | Master switch for ghost-text autocomplete |
| `ask_enabled` | `true` | Master switch for the ⌘K Ask popover |
| `system_prompt` | *(see config.json)* | Prepended to every autocomplete request |
| `ask_system_prompt` | *(see config.json)* | Prepended to every Ask request |

**Completion modes:** `word` (≤8 tokens) · `phrase` (first `.!?`) · `sentence` (one complete sentence) · `paragraph` (2–3 sentences) · `long` (multi-line lists). Klaus may **auto-promote** to `long` when the field ends with a list cue (`…are:`, `…include:`, trailing `:`) and PDF retrieval score is strong (≥ 6.0).

Full key documentation: [`klausmate/config.md`](klausmate/config.md).

---

## Architecture

```
Editor field (contenteditable, shadow DOM)
        │ keystroke → debounce
        ▼
  web/copilot.js ── pycmd("klausmate:complete:…") ──▶ __init__.py
        │                    │                         ├─ pdf_handler (BM25 or dock page)
        │                    │                         ├─ build_prompt / clean_completion
        │                    │                         └─ ollama_client → Ollama /api/generate
        │                    ▼
        └◀── editor.web.eval("klausmate.onCompletion(…)") ── inline ghost <span>
```

- **Non-blocking:** all Ollama I/O runs in `QueryOp.without_collection()`.
- **No native wheels:** stdlib HTTP + optional vendored `pypdf` only.
- **Editor state:** PDF dock sets `editor._klausmate_active_pdf` for page-aware retrieval.

---

## Project structure

```
Klausmate/
├── README.md                 # This file
├── AGENTS.md                 # Architecture & contributor guide
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── scripts/package.sh        # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package
    ├── __init__.py           # Core logic, hooks, dialogs
    ├── ollama_client.py      # Ollama HTTP client
    ├── ollama_setup.py       # First-run install detection
    ├── pdf_handler.py        # Extraction + BM25 retrieval (single active PDF)
    ├── pdf_viewer.py         # Native PDF view + selection + Copy page
    ├── settings_ui.py        # Settings panel (Preferences + dialog)
    ├── config.json / config.md
    ├── manifest.json
    ├── web/copilot.js        # Editor UI behavior (ghost, ask, cycle)
    ├── web/copilot.css
    ├── vendor/pypdf/         # Bundled PDF library
    └── user_files/           # User data (survives upgrades)
```

---

## Supported models (presets)

| Model | Size | Notes |
|-------|------|-------|
| `qwen3:0.6b` | ~0.8 GB | Fast, low RAM |
| `qwen3:1.7b` | ~1.4 GB | Fast |
| `qwen3:4b` | ~2.5 GB | Balanced (default for Ask) |
| `qwen3:8b` | ~5.2 GB | Best quality |
| `llama3.2:3b` | ~2 GB | General alternative |
| `llama3.1:8b` | ~4.7 GB | General purpose |
| `cniongolo/biomistral` | varies | Medical / scientific |

Any Ollama model name works if pulled locally.

---

## Building the `.ankiaddon` package

```sh
./scripts/package.sh
```

This produces `dist/klausmate.ankiaddon` ready for **Tools → Add-ons → Install from file…** or upload to [ankiweb.net/shared/addons](https://ankiweb.net/shared/addons/). The script:

1. Stages a copy of `klausmate/` into a tempdir.
2. Bumps `manifest.json` `mod` so Anki recognizes the upgrade.
3. Excludes `meta.json` (per-user config), all of `user_files/` except the placeholder `README.txt`, and every `__pycache__` / `*.pyc` / `.DS_Store`.
4. Zips from inside the staging dir so `__init__.py` sits at the archive root (AnkiWeb rejects archives wrapped in an extra folder).

Verify the archive:

```sh
unzip -l dist/klausmate.ankiaddon | grep -E "__pycache__|\.pyc|meta\.json|^klausmate/" \
  && echo "BAD: forbidden entries found" \
  || echo "OK: archive is AnkiWeb-compliant"
```

The AnkiWeb listing description lives in [`ANKIWEB.md`](ANKIWEB.md) — paste it into the AnkiWeb shared-add-on description box when publishing or updating.

---

## Support

- Issues & questions: [Discord](https://discord.gg/uFRgE8RtDY)

---

## License

See the repository license file if present. Third-party: `pypdf` (BSD) in `vendor/`.
