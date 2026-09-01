# KlausMate — a lecture-PDF library with semantic card matching for Anki

Klaus gives you a library for your lecture PDFs and finds the cards in your
collection that each one covers. A native PDF viewer, highlights, and image
cropping come along for the ride. There's no autocomplete or chat feature —
the one AI capability is semantic search, which runs on a cloud embedding
API by default.

> **Privacy.** Semantic search sends your card text to Voyage AI's cloud
> embedding service to build the search index — that's the default, and the
> only thing that leaves your computer. Switch the embedding provider to
> Ollama in **Manage models…** to keep it fully local instead. No telemetry
> either way.

---

## What it does

- **Adding a lecture PDF** — drop it onto the deck list or a deck's
  overview screen, use the **Browse…** button on the square there, or drop
  it straight into the Library window. Every route lands in the same
  library.
- **Card matching** — right-click a PDF in the Library and choose **Add to
  Search Index**. Klaus reads the PDF, searches your whole collection by
  meaning, and tags every card that lecture covers with its own
  `!Library::…` tag, so the matches are one click away in Anki's tag
  sidebar. Re-run it as **Update Search Index** after you add cards.
- **Library** — the **Library** link in the top toolbar (left of
  Decks…Sync) opens a window listing every PDF you've imported, organized
  into folders you create (mirrored as real folders on disk). Each row
  shows a retention score — the share of that PDF's matched cards you'd
  currently recall — plus its card and note counts, and a right-click menu
  to open, rename, move to a folder, index it, adjust how closely a card
  must relate to count as a match, show matched cards in Browse, suspend or
  unsuspend its cards, see its retention history, or delete it.
- **Copying matches into a deck** — select the notes you want in Browse and
  use **Notes → KlausMate: Create Curated Deck from Selection…**. It's one
  undo step, and your originals are untouched.
- **PDF viewer** — opens PDFs from the Library or the editor's drop panel.
  Drag-select text and copy it (**Cmd+C** or right-click **Copy**);
  **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**,
  to copy it as an image. Highlight text and attach sticky notes — both are
  baked into the stored PDF as real annotations, so they're still there if
  you open the file elsewhere.
- **Image cropping** — right-click or double-click any image in a note
  field, drag a crop box, and the result saves as a **new** media file. The
  original image, and any other note using it, is untouched.

## Setup

**Tools → KlausMate Preferences…** is the one settings dialog (the star in
the top toolbar opens it too):

- **Semantic Search** — pick your embedding provider. **Voyage** (cloud,
  default) needs a free API key from voyageai.com. **OpenAI** (cloud) needs
  your own key. **Ollama** runs locally — free and private, but needs
  Ollama installed (Klaus can download and manage a local copy for you the
  first time it's needed). **Index Now** builds or refreshes the card
  index, and **Test connection** checks whether Ollama is reachable.
- **Local model library** — pull or delete Ollama embedding models
  (`nomic-embed-text` is the default).
- **General** and **Appearance** — image cropping, whether Klaus manages a
  local Ollama install automatically, the accent colour, and the deck and
  study backgrounds.

## Reclaiming disk space

If Klaus downloaded and manages its own local Ollama install for you, it
lives under `user_files/runtime/` inside the add-on folder. There's no
in-app button to remove it: turn off "Manage Ollama automatically" in
**Manage models… → General** first (otherwise Klaus just re-downloads it
next time it's needed), then delete that folder yourself. Find it via
**Tools → Add-ons → View Files**.

## Tags

Klaus's tags live under `!Library` (the leading `!` keeps them near the top
of Anki's tag sidebar). Indexing a PDF gives it one tag of its own —
`!Library::<folder>::<PDF name>` — whose members are exactly the cards that
lecture covers; rename it in Anki's tag sidebar and the PDF is renamed with
it. Notes copied into a deck from Browse also get a permanent
`!Library::Curated`. Upgrading from an older version that used
`klaus::`-prefixed tags renames them automatically, once, the first time you
open Anki after updating.

---

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY)
