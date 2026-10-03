# AnkiWeb listing — KlausNote

Paste the body below into the **description** box on the AnkiWeb shared-add-on page when publishing or updating. Keep it under AnkiWeb's character limit.

---

## Short tagline (page subtitle / GitHub About)

A lecture-PDF library with semantic card matching for Anki. Uses local Ollama embeddings.

---

## Full description

```
KlausNote — find the cards that match a lecture, and keep your lecture PDFs organized alongside your deck.

Features
• Add a lecture PDF — drop it on the deck list or a deck's overview screen, use the Browse… button on the square there, or drop it into the Library window.
• Card matching — right-click a PDF in the Library and choose Add to Search Index. Klaus searches your whole collection by meaning and tags every card that lecture covers with the PDF's own !Library tag, so its matches are one click away in Anki's tag sidebar.
• Library — a window listing every PDF you've imported, organized into folders, each showing a retention score (how well you currently recall its matched cards) plus card and note counts, with a right-click menu to index it, tune how close a match must be, show its cards in Browse, suspend or unsuspend them, or chart its retention history.
• Copy the matches into a deck — select the notes you want in Browse and use Notes → KlausNote: Create Curated Deck from Selection…. One undo step; your originals are untouched.
• Native PDF viewer — drag-select text (Cmd+C or right-click Copy), highlights with sticky notes that get baked into the PDF as real annotations, thumbnails, find-in-PDF, and page/slide image capture.
• Image cropping — right-click or double-click any image in a note field to crop it; the crop is saved as a new media file, so the original is untouched.
• Preferences (Tools → KlausNote Preferences…, or the star in the top toolbar) ; configure local embeddings, build the card index, pull or delete local Ollama models, and set the accent colour and backgrounds.

Privacy — read before installing
Embeddings run locally. Downloading runtimes and models uses the network. External MCP clients may request lecture text, page images and card context and send them to their chosen provider. Collection writes require approval in Anki. Matching uses cosine thresholds. There is no subscription service or embedded assistant.

Setup: Tools → KlausNote Preferences… → Local models. Install/Start Ollama, Pull an embedding model, and Save. External clients → Copy Configuration provides a token-free bridge configuration for a separate client; Klaus never edits that client's settings.

Requirements
• Anki with Qt PDF support for the native viewer; verify this build on your installation.
• Ollama with an embedding model; Klaus can manage its runtime.
• Optional external MCP client: Python 3.9 or newer and an open Anki profile.

Support & feedback
Discord: https://discord.gg/uFRgE8RtDY
```

---

## Update / changelog note (optional, for version bumps)

Use this slot on the AnkiWeb upload form to summarise what changed in the new build.
