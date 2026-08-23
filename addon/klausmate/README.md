# Klausmate — Local AI Copilot + PDF Studio for Anki

Copilot-style inline autocomplete, ⌘K Ask, a full lecture-PDF studio
(viewer, highlights, notes), and image cropping — inside Anki, powered by a
**local** model running on your machine via [Ollama](https://ollama.com).

> No data ever leaves your computer. No API keys required. No subscription.

---

## Features at a glance

- **Inline ghost text** as you type — **Tab** accepts, **Esc** dismisses.
- **⌘K Ask** — instruct the model to edit/extend the current field. Answered
  by your local Ollama model by default, or switch **Ask (⌘K)** to the
  Anthropic API with your own key.
- **Semantic deck curation** — the **Klaus panel** (`Ctrl+Shift+K` or
  **Tools → Klaus → Open Klaus**) finds the cards in your collection closest
  to any lecture topic or imported PDF and turns them into a new deck.
- **Lecture-PDF studio** — a tabbed PDF viewer docked around the note editor
  (Add *and* Browse), with Apple-Preview-style selection, highlights with
  sticky notes, thumbnails, search, and image capture. The visible page
  grounds autocomplete/Ask answers.
- **Image cropping** — right-click (or double-click) any image in a note
  field to crop it; the crop saves as a new media file.
- **Model manager** — one-click pulls of curated local models, all runnable
  in under 8 GB RAM.

---

## The PDF viewer

Drop a PDF onto the Klaus bar (or **＋ → Browse…**) to add it. Text is
extracted per page for the AI; the file itself is stored by the addon.

### Tabs & library

- One tab per open PDF; **✕** closes a tab (the stored file survives — reopen
  it from **＋**, which lists your PDFs most-recently-used first).
- **Remove** (Klaus bar) deletes the current PDF from the store.
- Open tabs, panel placement, and thumbnail-strip state persist across
  restarts; each tab remembers your reading position within a session.

### Navigation

| Action | How |
|---|---|
| Thumbnails strip | **◫** in the panel bar — click a thumb to jump |
| Go to page | Click the `Page x / y` label, or **⌘⌥G** |
| Page up / down | `PgUp` / `PgDn` (`Home` / `End` for first/last) |
| Zoom | **⌘=** / **⌘−**, **⌘0** = fit width, or trackpad **pinch** |
| Find in PDF | **⌘F**, then **Enter / ⌘G** next · **⇧Enter / ⇧⌘G** previous |

### Selecting & copying (Apple Preview behavior)

| Action | How |
|---|---|
| Select text | Drag (starts from the nearest text even in margins) |
| Select word / paragraph / page | Double-click / triple-click / **⌘A** |
| Copy selection | **⌘C** or right-click → *Copy* (silent, like Preview) |
| Deselect | Click empty space |
| Copy the slide as an image | **⌘double-click** (opaque white background) |
| Copy a region as an image | **⌥drag** a marquee; it persists for re-copying |
| Drag an image out | After ⌥drag, **drag from inside the marquee** straight into a note field |

Selections survive scrolling, zooming, and multi-page drags.

### Highlights & sticky notes

- Select text → **⇧⌘A** (or right-click → *Highlight*). Highlights are
  saved per-PDF and survive tab switches and restarts.
- Right-click a highlight → *Add note…* attaches a sticky note that renders
  next to the highlight on the page; → *Remove Highlight* deletes it.
- **Highlights and notes are baked into the stored PDF file as real
  annotations** — open the PDF in Preview, Acrobat, or anywhere and they're
  there (a pristine original is kept internally; removing all annotations
  restores it).

### Window management

- Dock the panel **above, below, left, or right of the note editor**, or let
  it **float as a normal macOS window** (minimize to the Dock, Mission
  Control, can sit behind Anki).
- **Drag a tab out of the bar** (or any empty bar space) to tear the panel
  off with a native drag; drop on one of the labeled zones to dock, anywhere
  else to float. Horizontal tab drags just reorder tabs.
- The Klaus bar's **◨** toggles the panel. In Browse, toolbar **◧**/**◨**
  toggle Anki's sidebar and the editor column.

### AI grounding

Autocomplete and ⌘K Ask retrieve context from the **visible tab and page
window (±1 page)** — switch tabs or scroll and the AI follows.

---

## Image cropping (any image, any note)

Right-click an image in a note field → **Crop image** (or double-click it).
Drag a crop box (8 resize handles), hit **Crop** — the result is saved as a
**new** media file and the note updates in place. Other notes using the
original image are unaffected.

---

## Semantic deck curation (the Klaus panel)

Open with **`Ctrl+Shift+K`**, the **Klaus** toolbar button, or
**Tools → Klaus → Open Klaus** (docks on the right; float/move as you like).

1. **Describe the lecture** in the search box (e.g. *"renal physiology:
   nephron transport"*) — or pick one of your imported **Lecture PDFs**, and
   optionally scope to a deck.
2. **Find cards** ranks your whole collection by semantic similarity and
   opens the top matches (default 100) in **Browse**, tagged `klaus::curate`
   for preview. Prune anything you don't want. (*Create deck now* skips the
   preview.)
3. **Notes → Klaus: Create curated deck from selection…** names the new deck
   (e.g. `Klaus::Renal Physiology`) and copies the keepers into it — the
   copies get a permanent `klaus::curated` tag, originals are untouched, and
   the whole thing is **one Ctrl+Z undo step**.

Stuck tag? **Tools → Klaus → Clear curation tag** removes `klaus::curate`
everywhere.

### Card embeddings

The first search offers a one-time **index of your collection** — progress
is shown, cancellable, and **resumes where it stopped** (vectors save in
batches). The index updates automatically when notes are added or edited;
*Re-index* in the panel re-syncs it on demand (a full rebuild only happens
when the embedding provider or model changes).

| Provider | Default model | Notes |
|---|---|---|
| **Voyage** (default) | `voyage-3-lite` | Needs `embedding_api_key_voyage` (free key at voyageai.com) |
| OpenAI | `text-embedding-3-small` | Needs `embedding_api_key_openai` |
| Ollama | `nomic-embed-text` | Local, free, private — limited by your RAM |

Existing installs keep the provider they already had configured — the
Voyage default applies to fresh installs only.

Switch provider/model in **Tools → Klaus → Manage models…** under
*What Klaus uses → Semantic search*. Changing either invalidates the index
(rebuilds on next search).

---

## The Ask (⌘K) engine

Ask runs on **local Ollama by default** — free and fully private. In
**Tools → Klaus → Manage models…** the *Ask (⌘K)* dropdown switches it to the
**Anthropic API**: paste your API key (`claude_model` defaults to
`claude-opus-4-8`).

> ⚠ Running Ask on Claude sends your prompts (including retrieved PDF
> context) to Anthropic's servers and bills your API credits per token.
> Without an API key, Ask silently keeps using the local model.
> Autocomplete ghost text is **always local**, regardless of this setting.

---

## Installation

### 1. Install the add-on — that's it

Either:
- Download from AnkiWeb (recommended once published), **or**
- Copy/symlink the `klausmate/` folder into your Anki `addons21/` folder, then restart Anki.

To find your `addons21/` folder: in Anki go to **Tools → Add-ons → View Files**.

### 2. Click "Set up Klaus" on first run

On first launch Klaus offers **one-click setup**: it downloads the official
Ollama runtime and a starter model, then runs the engine in the background
whenever Anki is open. No terminal, no separate installer.

What the automatic setup does (full disclosure):

- Downloads the standalone Ollama runtime from the official
  [ollama/ollama GitHub release](https://github.com/ollama/ollama/releases)
  (MIT-licensed; ~123 MB on macOS, larger on Windows/Linux where GPU
  libraries are bundled) after you confirm.
- Verifies the download against the release's published SHA-256 checksums.
- Stores it in the add-on's `user_files/runtime/` folder — removable any
  time via **Remove Klaus-managed runtime** in Klaus settings.
- Starts/stops the server with Anki. If you already have Ollama installed,
  Klaus simply uses yours and downloads nothing.
- Models go to the standard `~/.ollama` folder (shared with any other
  Ollama use). Set `runtime_auto_setup: false` in the add-on config to opt
  out entirely.

### Manual alternative

Prefer to manage Ollama yourself? Install it from
<https://ollama.com/download>, pull a model (`ollama pull qwen3:0.6b`), and
Klaus will detect and use it automatically.

---

## Models

**Tools → Klaus → Manage models…** offers one-click pulls, all sized for
machines with **8 GB RAM**:

| Family | Presets | Notes |
|---|---|---|
| Qwen3 | 0.6b · 1.7b · 4b · **4b-instruct-2507** · 8b | Best quality-per-size; the `-2507` variant answers without a thinking delay |
| Gemma 3 / 3n | 1b · 4b · 3n:e2b | 3n is engineered for low-RAM runtime |
| Phi-4 mini | 3.8b | Strong reasoning for its size |
| DeepSeek-R1 | 8b distill | Thinks step-by-step — better for Ask than autocomplete |
| Llama | 3.2:3b · 3.1:8b | Solid generalists |
| BioMistral | community | Medical fine-tune |

Suggested pairing: a tiny model (`qwen3:0.6b` / `gemma3:1b`) for
*autocomplete* (latency matters), `qwen3:4b-instruct-2507` or `gemma3:4b`
for *Ask*. The picker is editable — any Ollama tag works.

---

## Optional: enable PDF support

PDF parsing requires the pure-Python `pypdf` library. To enable it without
the user needing pip:

```sh
cd klausmate
pip install --target vendor pypdf
```

This creates `klausmate/vendor/pypdf/` which the add-on auto-detects.
Without this step, completions still work — only PDF upload is disabled.

---

## Configuration

Open **Tools → Klaus → Settings…** (or Tools → Add-ons → Klaus → Config).
The most useful keys (see `config.md` for the full list):

| Key | Default | Meaning |
|---|---|---|
| `autocomplete_model` / `ask_model` | `qwen3:0.6b` / `qwen3:4b` | Local models per feature |
| `klaus_engine` | `ollama` | Ask engine: `ollama` or `claude` |
| `claude_api_key` / `claude_model` | — / `claude-opus-4-8` | Anthropic API credentials for Ask |
| `embedding_provider` / `embedding_model` | `voyage` / per provider | Card-embedding backend |
| `curate_top_k` / `curate_min_score` | `100` / `0.35` | Curation result size / similarity floor |
| `chat_hotkey` / `ask_hotkey` | `Ctrl+Shift+K` / `Cmd+K` | Klaus panel / Ask popover shortcuts |
| `completion_mode` | `sentence` | Ghost-text length (word…paragraph) |
| `runtime_auto_setup` | `true` | Let Klaus download/start the Ollama engine automatically |
| `endpoint` | `http://localhost:11434` | Ollama server URL |
| `debounce_ms` / `min_chars_before_trigger` | `400` / `8` | Autocomplete trigger tuning |
| `retrieval_top_k` | `4` | PDF chunks injected into prompts |
| `autocomplete_enabled` / `ask_enabled` / `image_crop_enabled` | `true` | Feature toggles |
| `system_prompt` / `ask_system_prompt` | *(see config.json)* | Per-feature system prompts |

---

## Architecture

```
Anki editor field (contenteditable inside shadow DOM)
        │ keystroke → debounce 400ms
        ▼
web/copilot.js   ──pycmd("klausmate:complete:<b64 json>")──▶  __init__.py
                                                                   │
                                                                   ▼
                                                          ollama_client.py
                                                                   │
                                                                   ▼
                                                  POST localhost:11434/api/generate
                                                                   │
                                                                   ▼
                                          editor.web.eval("klausmate.onCompletion(...)")
                                                                   │
                                                                   ▼
                                          ghost <span> rendered at caret rect
                                          Tab → execCommand("insertText", ...)
```

Deck curation pipeline:

```
Klaus panel (web/search.js) ──pycmd("klaus:search")──▶ chat_dock.py
        │
        ▼
curation.py ── sync index (only new/edited notes re-embed; hash-diffed)
        │
        ▼
embeddings.py ── ollama /api/embed · openai · voyage  (unit vectors)
        │
        ▼
card_index.py ── user_files/card_index/: packed float32 vectors + manifest
        │          top-K by dot product (math.sumprod — no numpy needed)
        ▼
tag matches `klaus::curate` → open in Browse → prune →
"Create curated deck" copies selection into a new deck (one undo step)
```

- The PDF studio lives in `pdf_viewer.py` (viewer, selection, highlights,
  find, thumbnails) + `pdf_handler.py` (storage, retrieval, annotation
  baking) + `_PdfTabContainer` in `__init__.py` (tabs, window management).
  Image cropping is `crop_dialog.py`.
- Deck curation is `curation.py` (pipeline + Browse/undo glue) +
  `card_index.py` (vector store) + `embeddings.py` (providers) +
  `chat_dock.py` (panel host). Ask-on-Claude speaks the Anthropic
  API through `claude_api.py` (stdlib SSE client).
- All network/model work runs in a background `QueryOp.without_collection()` — UI never freezes.
- No C extensions, no native code, no per-platform wheels → installs cleanly from AnkiWeb.

---

## Building the .ankiaddon

```sh
cd klausmate
find . -name __pycache__ -exec rm -rf {} +
# user_files is excluded: it holds machine-local state (your PDFs, contexts,
# and the downloaded Ollama runtime — shipping that would blow AnkiWeb's
# 100 MB limit). Anki recreates it on install.
zip -r ../klausmate.ankiaddon * -x "*.DS_Store" -x "user_files/*" -x "meta.json"
```
