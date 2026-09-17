# AnkiWeb listing — Klausmate

Paste the body below into the **description** box on the AnkiWeb shared-add-on page when publishing or updating. Keep it under AnkiWeb's character limit.

---

## Short tagline (page subtitle / GitHub About)

A lecture-PDF library with semantic card matching for Anki. Uses a cloud embedding API by default; a local Ollama model is an alternative.

---

## Full description

```
Klausmate — find the cards that match a lecture, and keep your lecture PDFs organized alongside your deck.

Features
• Add a lecture PDF — drop it on the deck list or a deck's overview screen, use the Browse… button on the square there, or drop it into the Library window.
• Card matching — right-click a PDF in the Library and choose Add to Search Index. Klaus searches your whole collection by meaning and tags every card that lecture covers with the PDF's own !Library tag, so its matches are one click away in Anki's tag sidebar.
• Library — a window listing every PDF you've imported, organized into folders, each showing a retention score (how well you currently recall its matched cards) plus card and note counts, with a right-click menu to index it, tune how close a match must be, show its cards in Browse, suspend or unsuspend them, or chart its retention history.
• Copy the matches into a deck — select the notes you want in Browse and use Notes → KlausMate: Create Curated Deck from Selection…. One undo step; your originals are untouched.
• Native PDF viewer — drag-select text (Cmd+C or right-click Copy), highlights with sticky notes that get baked into the PDF as real annotations, thumbnails, find-in-PDF, and page/slide image capture.
• Image cropping — right-click or double-click any image in a note field to crop it; the crop is saved as a new media file, so the original is untouched.
• Preferences (Tools → KlausMate Preferences…, or the star in the top toolbar) — choose your embedding provider, build the card index, pull or delete local Ollama models, and set the accent colour and backgrounds.

Privacy — read before installing
Klaus's only AI-powered feature is semantic search — it's what powers the card matching and the Library's retention scores. By default that means your card text is sent to Voyage AI's cloud embedding service to build the search index. That's the only thing that leaves your computer, and only for that purpose — there's no other AI feature, and no telemetry. Switch the embedding provider to Ollama in KlausMate Preferences for a fully local alternative: a model running on your machine, no account and no key, at somewhat lower search quality.

Requirements
• Anki 23.10+ (Qt 6.5+ recommended for the PDF viewer)
• A free Voyage AI key for the default cloud embedding provider — or switch the provider to Ollama (bring your own install, or let Klaus manage one for you) to skip that

Support & feedback
Discord: https://discord.gg/uFRgE8RtDY
```

---

## Update / changelog note (optional, for version bumps)

Use this slot on the AnkiWeb upload form to summarise what changed in the new build.
