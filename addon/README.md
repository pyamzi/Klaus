# KlausMate — a lecture-PDF library with semantic card matching for Anki

Klaus gives you a library for your lecture PDFs and finds the cards in your
collection that each one covers. A native PDF
viewer, highlights, and image cropping come along for the ride. The AI
capabilities are semantic search (OpenAI embeddings) and an assistant that
rides the Claude Code CLI under your own login.

Two ways to pay for the AI: **bring your own keys** (free, your own OpenAI
and Anthropic keys, your own bill) or **Klaus Plus** ($12/month or $99/year,
no keys — Klaus's own service holds them and meters what you use). Either
way the add-on is the same code; see [Klaus Plus](#klaus-plus) below.

For what the add-on does day to day, see [`klausmate/README.md`](klausmate/README.md)
(the copy that ships inside the package) — this file covers getting the repo
running and building the package. For internals, see [`AGENTS.md`](AGENTS.md).

> **Privacy — read before installing.** Klaus makes network calls for two
> things — three on Klaus Plus — and nothing else. No telemetry, ever.
>
> - **Indexing** sends your card text and your lecture pages' text to
>   OpenAI's embeddings API. On the free tier that goes straight to OpenAI
>   with your own key; on **Klaus Plus** it goes to Klaus's service, which
>   relays it to the same API and keeps usage counters only — never your
>   text, audio or images, and never in a log.
> - **The assistant**, and only while you use it, sends your message plus the
>   page you are viewing (its text, its image, your selection) to Anthropic
>   through the `claude` CLI under **your own Claude login** — Klaus stores no
>   key for it, and Klaus Plus does not change that today.
> - **On Klaus Plus only**, two more calls go to Klaus's service, and neither
>   carries any of your content: **Check** in Preferences asks
>   `GET /v1/me` for your plan and this month's usage, and **Manage
>   subscription…** asks `POST /v1/portal` for a one-time Stripe portal link.
>   Both send your licence key and nothing else. Without a licence key
>   neither ever fires.

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
- **Either** your own [OpenAI](https://platform.openai.com) key (indexing) — plus an [Anthropic](https://console.anthropic.com) key for what Klaus's designed-but-unbuilt Plans 2 and 3 will use — **or** a Klaus Plus licence key, which replaces both
- `pypdf` — bundled under `klausmate/vendor/`; PDF features are disabled if it's missing
- (Optional) the [Claude Code CLI](https://claude.com/claude-code) for the assistant dock — it runs under your own login and Klaus stores no key for it

---

## Installation

### 1. Install the add-on

**From `.ankiaddon`** *(recommended)*: build or download `dist/klausmate.ankiaddon`, then in Anki use **Tools → Add-ons → Install from file…** and select it. Restart Anki.

**Manual (dev):** symlink or copy the `klausmate/` folder into your Anki `addons21/` directory, then restart Anki. Find `addons21/` via **Tools → Add-ons → View Files**.

To rebuild the package from source:

```sh
./scripts/package.sh
```

### 2. Pay for the AI: your own keys, or Klaus Plus

Open **Tools → KlausMate Preferences… → API keys & models** (the star in the top toolbar opens the dialog too). There is one provider, OpenAI, and no provider picker: paste `api_key_openai` (and `api_key_anthropic`, stored for the designed-but-unbuilt Plans 2 and 3) and you are on the free tier, paying OpenAI directly.

<a id="klaus-plus"></a>
**Klaus Plus** is the alternative: one subscription, one licence key, no provider keys. Press **Subscribe…** in the Klaus Plus group at the top of that page, pay, and paste the `kp_…` key the welcome page shows into the **Klaus Plus key** field; **Check** fills in the status line. Klaus then sends its API calls to Klaus's own service, which relays them to the same providers and counts what you use: per UTC month, 30 lecture hours of audio, 3,000 judged cards, 200 assistant turns, and unmetered embeddings. *Today that means indexing* — it is the only call Klaus actually makes through an API key; transcription, card judging and the assistant-on-the-API are designed and not yet built, and their quotas are waiting for them. The provider-key rows stay editable the whole time — delete the licence key and you are back on your own keys with nothing else to change.

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
├── LICENSE                   # GNU AGPL v3 — the add-on's licence
├── scripts/package.sh        # Builds dist/klausmate.ankiaddon
├── service/                  # Klaus Plus: the hosted metered service — a SEPARATE
│                             # program, never shipped to users (see service/README.md)
└── klausmate/                # Anki add-on package
    ├── README.md             # Ships inside the add-on — user-facing usage
    ├── LICENSE               # The same AGPL v3 text, shipped inside the package
    ├── __init__.py           # Bootstrap, gui_hooks, JS bridge, menu, PDF tab/window management
    ├── embeddings.py         # Embeddings (OpenAI) over openai_client.py
    ├── plus.py               # Klaus Plus on the add-on side: the licence key, the per-call endpoint, the cached verdict
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
    ├── openai_client.py      # Stdlib HTTP to OpenAI: embed() and transcribe()
    ├── anthropic_client.py   # Stdlib HTTP to the Anthropic Messages API (no caller yet)
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

This produces `dist/klausmate.ankiaddon` ready for **Tools → Add-ons → Install from file…** or upload to [ankiweb.net/shared/addons](https://ankiweb.net/shared/addons/). The script stages a copy of `klausmate/` into a tempdir, bumps `manifest.json`'s `mod`, excludes `meta.json*` (per-user config, may hold API keys) and everything in `user_files/` except the placeholder `README.txt`, strips `__pycache__`/`*.pyc`/`.DS_Store`, and zips from inside the staging dir so `__init__.py` sits at the archive root (AnkiWeb rejects archives wrapped in an extra folder). `service/` is never staged — it lives outside `klausmate/` and carries an explicit `--exclude` besides.

The AnkiWeb listing description lives in [`ANKIWEB.md`](ANKIWEB.md) — paste it into the AnkiWeb shared-add-on description box when publishing or updating.

---

## Support

- Issues & questions: [Discord](https://discord.gg/uFRgE8RtDY)

---

## License

The add-on (`klausmate/`) is licensed under the GNU AGPL v3 — see `LICENSE`. The Klaus Plus service (`service/`) is a separate program and is not part of the add-on's licence. Third-party: `pypdf` (BSD) in `vendor/`.
