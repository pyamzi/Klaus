# Klausmate — semantic deck curation and a lecture-PDF library for Anki

Klaus finds the cards in your collection that match a lecture PDF, and gives
you a library to keep those PDFs organized alongside your deck. A native PDF
viewer, highlights, and image cropping come along for the ride. There's no
autocomplete or chat feature — the one AI capability is semantic search,
which runs on a cloud embedding API by default.

> **Privacy.** Semantic search sends your card text to Voyage AI's cloud
> embedding service to build the search index — that's the default, and the
> only thing that leaves your computer. Switch the embedding provider to
> Ollama in **Manage models…** to keep it fully local instead. No telemetry
> either way.

---

## What it does

- **Curate Deck** — drop a lecture PDF onto the deck list (or a deck's
  overview screen) to arm it, or pick a previously imported one from the
  **Curate Deck** menu. Klaus searches your whole collection by meaning,
  tags the best matches for review in Browse, and **Create curated deck**
  copies the keepers into a new deck — one undo step, originals untouched.
- **Library** — the **Library** link in the top toolbar (left of
  Decks…Sync) opens a window listing every PDF you've imported, organized
  into folders you create (nothing moves on disk). Each row shows a
  retention score — the share of that PDF's matched cards you'd currently
  recall — and a right-click menu to open, rename, move to a folder, adjust
  how closely a card must relate to count as a match, show matched cards in
  Browse, curate a deck from it, or delete it.
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

**Tools → Klaus → Manage models…** is the one settings dialog:

- **Semantic search** — pick your embedding provider. **Voyage** (cloud,
  default) needs a free API key from voyageai.com. **OpenAI** (cloud) needs
  your own key. **Ollama** runs locally — free and private, but needs
  Ollama installed (Klaus can download and manage a local copy for you the
  first time it's needed).
- **Local model library** — pull or delete Ollama embedding models
  (`nomic-embed-text` is the default).
- **General** — toggle image cropping, and whether Klaus manages a local
  Ollama install automatically.

**Tools → Klaus → Test connection** checks whether Ollama is reachable.
**Tools → Klaus → Clear library tag** removes any leftover Klaus curation
tags from every note.

## Reclaiming disk space

If Klaus downloaded and manages its own local Ollama install for you, it
lives under `user_files/runtime/` inside the add-on folder. There's no
in-app button to remove it: turn off "Manage Ollama automatically" in
**Manage models… → General** first (otherwise Klaus just re-downloads it
next time it's needed), then delete that folder yourself. Find it via
**Tools → Add-ons → View Files**.

## Tags

Klaus's tags live under `!Library` (the leading `!` keeps them near the top
of Anki's tag sidebar): a temporary tag on cards awaiting review after a
curation search, a permanent one on cards copied into a curated deck, and a
temporary one from a Library row's "Show matched cards in Browse". Upgrading
from an older version that used `klaus::`-prefixed tags renames them
automatically, once, the first time you open Anki after updating.

---

Questions or feedback: [Discord](https://discord.gg/uFRgE8RtDY)
