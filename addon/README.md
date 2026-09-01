# KlausMate — a lecture-PDF library with semantic card matching for Anki

Klaus gives you a library for your lecture PDFs and finds the cards in your
collection that each one covers. A native PDF
viewer, highlights, and image cropping come along for the ride. The one AI
capability is semantic search, powered by a cloud embedding API by default
(a local Ollama model is an alternative).

For what the add-on does day to day, see [`klausmate/README.md`](klausmate/README.md)
(the copy that ships inside the package) — this file covers getting the repo
running and building the package. For internals, see [`AGENTS.md`](AGENTS.md).

> **Privacy — read before installing.** Semantic search sends your card text
> to Voyage AI's cloud embedding service by default, to build the search
> index. That's the only thing that leaves your computer. Switch the
> embedding provider to Ollama in **KlausMate Preferences…** for a fully local
> alternative. No telemetry either way.

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY)

---

## What it does

| Feature | How to use |
|---------|------------|
| **Adding a PDF** | Drop a lecture PDF on the deck list or a deck's overview screen (or use **Browse…** on the square there), or drop it straight into the Library window. |
| **Card matching** | Right-click a PDF in the Library → **Add to Search Index**. Klaus searches the whole collection by meaning and tags every card that lecture covers with the PDF's own `!Library::…` tag. |
| **Library** | The **Library** link in the top toolbar opens a window listing every PDF you've imported, in folders you create, each with a retention score, card/note counts, and a right-click menu to index, re-tag, suspend, chart, or open it. |
| **Copying matches into a deck** | Select notes in Browse → **Notes → KlausMate: Create Curated Deck from Selection…**. One undo step, originals untouched. |
| **PDF viewer** | Native viewer opened from the Library or the editor's drop panel — text selection, page/slide image copy, highlights with sticky notes baked in as real PDF annotations. |
| **Image cropping** | Right-click or double-click an image in a note field to crop it; saves as a new media file. |

---

## Requirements

- [Anki](https://apps.ankiweb.net/) **23.10+** (Qt 6.5+ for the PDF viewer; everything else works on earlier 23.10+ builds)
- A free [Voyage AI](https://voyageai.com) key for the default cloud embedding provider — or switch the provider to Ollama (see below) to skip this
- `pypdf` — bundled under `klausmate/vendor/`; PDF features are disabled if it's missing
- (Optional) [Ollama](https://ollama.com/download) running locally, if you pick it as the embedding provider instead of a cloud API

---

## Installation

### 1. Install the add-on

**From `.ankiaddon`** *(recommended)*: build or download `dist/klausmate.ankiaddon`, then in Anki use **Tools → Add-ons → Install from file…** and select it. Restart Anki.

**Manual (dev):** symlink or copy the `klausmate/` folder into your Anki `addons21/` directory, then restart Anki. Find `addons21/` via **Tools → Add-ons → View Files**.

To rebuild the package from source:

```sh
./scripts/package.sh
```

### 2. Choose an embedding provider

Open **Tools → KlausMate Preferences…** (the star in the top toolbar opens it too). **Voyage** (cloud) is the default and needs a free API key. **OpenAI** (cloud) needs your own key. **Ollama** (local) needs Ollama installed — Klaus can download and manage a local copy for you the first time it's needed, or point it at an Ollama you already run.

### 3. (Optional) Vendor pypdf yourself

If your copy lacks `klausmate/vendor/pypdf/`:

```sh
cd klausmate
pip install --target vendor pypdf
```

Restart Anki. Without pypdf, PDF import, the viewer, and Library are all disabled; the Browse deck copier over note text still works.

---

## Project structure

```
KlausMate-Context/
├── README.md                 # This file (repo entry point)
├── AGENTS.md                 # Architecture & contributor guide
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── scripts/package.sh        # Builds dist/klausmate.ankiaddon
└── klausmate/                # Anki add-on package
    ├── README.md             # Ships inside the add-on — user-facing usage
    ├── __init__.py           # Bootstrap, gui_hooks, JS bridge, menu, PDF tab/window management
    ├── embeddings.py         # Embedding provider abstraction (Voyage / OpenAI / Ollama)
    ├── card_index.py         # Embedding index over notes
    ├── curation.py           # Card index build + the Browse deck copier
    ├── pdf_drop.py           # PDF drop square + drop wrap on the deck list / overview screens
    ├── retention.py          # Per-PDF retention/study-priority scoring
    ├── pdf_index.py          # Embedding index over one PDF's text chunks
    ├── pdf_handler.py        # PDF storage, text extraction, annotation baking
    ├── pdf_viewer.py         # Native PDF viewer (selection, highlights, find, thumbnails)
    ├── pdf_drive.py          # The Library window
    ├── drive_store.py        # Library's virtual folders
    ├── manage_models.py      # KlausMate Preferences dialog
    ├── setup_flow.py         # First-run setup + readiness checks
    ├── tag_migrate.py        # One-time klaus:: -> !Library tag migration
    ├── ollama_client.py      # Stdlib HTTP client for Ollama (embeddings, pull/delete)
    ├── ollama_runtime.py     # Managed local Ollama install
    ├── ollama_setup.py       # First-run install detection
    ├── crop_dialog.py        # Image-crop dialog
    ├── config.json / config.md
    ├── manifest.json
    ├── web/copilot.js        # Editor field-focus tracking + image-crop trigger
    ├── vendor/pypdf/         # Bundled PDF library
    └── user_files/           # User data (survives upgrades)
```

---

## Building the `.ankiaddon` package

```sh
./scripts/package.sh
```

This produces `dist/klausmate.ankiaddon` ready for **Tools → Add-ons → Install from file…** or upload to [ankiweb.net/shared/addons](https://ankiweb.net/shared/addons/). The script stages a copy of `klausmate/` into a tempdir, bumps `manifest.json`'s `mod`, excludes `meta.json*` (per-user config, may hold API keys) and everything in `user_files/` except the placeholder `README.txt`, strips `__pycache__`/`*.pyc`/`.DS_Store`, and zips from inside the staging dir so `__init__.py` sits at the archive root (AnkiWeb rejects archives wrapped in an extra folder).

The AnkiWeb listing description lives in [`ANKIWEB.md`](ANKIWEB.md) — paste it into the AnkiWeb shared-add-on description box when publishing or updating.

---

## Support

- Issues & questions: [Discord](https://discord.gg/uFRgE8RtDY)

---

## License

See the repository license file if present. Third-party: `pypdf` (BSD) in `vendor/`.
