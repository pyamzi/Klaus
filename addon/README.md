# Klausmate — Local AI for Anki

Copilot-style **inline ghost-text autocomplete** for Anki's card editor, powered by a **local** LLM via [Ollama](https://ollama.com). Optionally ground suggestions in your **lecture PDF** with BM25 retrieval and a built-in PDF viewer, plus semantic deck curation across your whole collection.

> **Privacy — read before installing.** Autocomplete and Ask run on a local
> Ollama model by default: nothing leaves your computer for those, no API
> key, no subscription. Curate Deck and PDF drive retention scoring are
> different — they default to Voyage AI's cloud embedding service, so your
> card text is sent to Voyage to build the search index. Switch the
> embedding provider to Ollama in **Manage models…** for a fully local
> alternative. No telemetry either way.

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
| **PDF drive** | **PDFs** link in the top toolbar opens the Klaus PDF drive — a library window with every imported PDF in a foldered tree, a retention score per PDF, and a right-click menu to embed, curate, or browse matches. |
| **Curate Deck** | A **Curate Deck** button on the deck list and on a deck's overview screen finds cards matching a lecture PDF. Drop a PDF on the deck list to arm it, or pick one from the menu. |

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

### PDF drive (library)

- Click **PDFs** in the top toolbar (left of Decks…Sync) to open the Klaus PDF drive — a standalone window listing every PDF you've imported.
- **Left pane:** a folder tree. **New folder** creates a virtual folder — PDFs aren't moved on disk, only organized; a PDF's right-click **Move to folder** files it there. Each row shows its **retention** (the share of that PDF's matched cards you'd currently recall) and how many cards match.
- **Double-click** a PDF to open it in the viewer on the right, the same viewer used elsewhere in Klaus.
- **Right-click** a PDF for **Open**, **Rename…**, **Move to folder**, **Embed / Re-embed for retention**, **Match strictness…** (how closely a card must relate to the PDF to count as a match), **Show matched cards in Browse**, **Curate deck from this PDF…**, and **Delete…**.
- This window replaced the old Priorities tab — retention scoring and deck curation both live here now, in addition to the deck screens below.

### Curate Deck

- On the **deck list** or a **deck's overview** screen, click **Curate Deck** at the bottom to find cards matching a lecture PDF.
- **Drag a PDF onto the deck list** to arm it — an "Armed: *name*" banner appears above the deck list until you click **Curate Deck** (or its **×** to disarm). With nothing armed, **Curate Deck** opens a menu of your imported PDFs, most recently used first.
- You'll be asked which deck to search, unless you're on a deck's overview screen, where it defaults to that deck. Matching cards are tagged and opened in Browse.
- The same curation can also be started from the PDF drive's **Curate deck from this PDF…** right-click action.

### Settings & models

- **Tools → Klaus → Settings…** — models, sampling, completion length, hotkeys, retrieval top-K, prompts.
- **Tools → Klaus → Manage models…** — pull / delete / pick your autocomplete and Ask models.
- **Tools → Klaus → Test connection** — verify Ollama is reachable.
- **Tools → Add-ons → Klausmate → Config** — opens the same Settings dialog.
- **Edit → Preferences** — Klaus group with the most common knobs.

---

## Configuration

**Autocomplete & Ask**

| Key | Default | Description |
|-----|---------|-------------|
| `autocomplete_model` | `qwen3:0.6b` | Model for inline ghost autocomplete |
| `ask_model` | `qwen3:4b` | Model for Cmd+K Ask (when `klaus_engine` is `ollama`) |
| `model` | `qwen3:0.6b` | Legacy alias, kept in sync with `autocomplete_model` |
| `endpoint` | `http://localhost:11434` | Ollama server URL |
| `generate_timeout_s` | `180` | Timeout for long generations |
| `runtime_auto_setup` | `true` | Klaus silently starts/installs its own local Ollama when needed |
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
| `image_crop_enabled` | `true` | Enable right-click/double-click image crop |
| `system_prompt` | *(see config.json)* | Prepended to every autocomplete request |
| `ask_system_prompt` | *(see config.json)* | Prepended to every Ask request |

**Claude Ask engine** — routes Cmd+K Ask to the Anthropic API instead of the local model. Autocomplete always stays local.

| Key | Default | Description |
|-----|---------|-------------|
| `klaus_engine` | `ollama` | `ollama` (local Ask model) or `claude` (cloud Ask) |
| `claude_api_key` | *(empty)* | Anthropic API key; required when `klaus_engine` is `claude` |
| `claude_model` | `claude-opus-4-8` | Model used when Ask runs on Claude |
| `claude_timeout_s` | `300` | Timeout for a Claude Ask call |

**Semantic curation** — powers Curate Deck, the PDF drive, and retention scoring.

| Key | Default | Description |
|-----|---------|-------------|
| `embedding_provider` | `voyage` | `voyage`, `openai` (both cloud, need an API key), or `ollama` (local) |
| `embedding_model` | *(empty)* | Embedding model ID; empty = provider default |
| `embedding_api_key_voyage` / `embedding_api_key_openai` | *(empty)* | API key for the matching cloud embedding provider |
| `chat_hotkey` | `Ctrl+Shift+K` | Toggle the Klaus panel (semantic deck curation) |
| `curate_top_k` | `100` | Best-matching notes tagged for review per curation search |
| `curate_min_score` | `0.35` | Minimum cosine similarity for a curation match |
| `pdf_match_threshold` | `0.35` | Similarity cutoff for a card counting as "about" a PDF (retention scoring) |
| `pdf_match_agg` | `max` | How a card's score against a PDF's chunks is aggregated: `max` or `top3_mean` |
| `pdf_index_max_chunks` | `1000` | Cap on embedded chunks per PDF |

**Completion modes:** `word` (≤8 tokens) · `phrase` (first `.!?`) · `sentence` (one complete sentence) · `paragraph` (2–3 sentences) · `long` (multi-line lists). Klaus may **auto-promote** to `long` when the field ends with a list cue (`…are:`, `…include:`, trailing `:`) and PDF retrieval score is strong (≥ 6.0).

Full key documentation, including how each engine and provider is wired up: [`klausmate/config.md`](klausmate/config.md).

---

## Architecture

**Autocomplete / Ask** — the ghost-text and Cmd+K paths:

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

Ask instead calls `claude_api.py` (a stdlib SSE client for the Anthropic Messages API) when `klaus_engine` is `claude`.

**Semantic curation** — Curate Deck, the PDF drive, and retention scoring all read the same embedding index:

```
Notes / PDF chunks ─▶ embeddings.py (Ollama · OpenAI · Voyage) ─▶ card_index.py (packed vectors + manifest)
                                                                        │
                                                                        ▼
                                                          curation.py — top_k search
                                                                        │
                                        ┌───────────────────────────────┼───────────────────────────┐
                                        ▼                               ▼                            ▼
                              Curate Deck (tag + Browse,        PDF drive retention           Klaus panel
                              undoable deck copy)                score per PDF                (chat_dock.py)
```

- **Non-blocking:** Ollama calls run in `QueryOp.without_collection()`; embedding/indexing runs off the main thread too, resumable if cancelled mid-batch.
- **No native wheels:** stdlib HTTP only, plus the vendored `pypdf` for PDF text/annotations — no pip installs, including for the cloud embedding/Claude calls.
- **Editor state:** PDF dock sets `editor._klausmate_active_pdf` for page-aware retrieval.
- **Index storage:** the card index lives under `user_files/card_index/`; deleting it forces a full rebuild.

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
