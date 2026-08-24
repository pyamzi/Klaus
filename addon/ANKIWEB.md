# AnkiWeb listing — Klausmate

Paste the body below into the **description** box on the AnkiWeb shared-add-on page when publishing or updating. Keep it under AnkiWeb's character limit.

---

## Short tagline (page subtitle / GitHub About)

Semantic deck curation and a lecture-PDF library for Anki. Uses a cloud embedding API by default; a local Ollama model is an alternative.

---

## Full description

```
Klausmate — find the cards that match a lecture, and keep your lecture PDFs organized alongside your deck.

Features
• Curate Deck — drop a lecture PDF on the deck list (or pick a previously imported one from the menu) and Klaus searches your whole collection by meaning, tagging the best-matching cards for review in Browse before you copy them into a new deck. Fully undoable.
• Library — a window listing every PDF you've imported, organized into folders, each showing a retention score (how well you currently recall its matched cards) and a right-click to curate a deck from it.
• Native PDF viewer — drag-select text (Cmd+C or right-click Copy), highlights with sticky notes that get baked into the PDF as real annotations, thumbnails, find-in-PDF, and page/slide image capture.
• Image cropping — right-click or double-click any image in a note field to crop it; the crop is saved as a new media file, so the original is untouched.
• Manage models (Tools → Klaus → Manage models…) — choose your embedding provider and pull or delete local Ollama models.

Privacy — read before installing
Klaus's only AI-powered feature is semantic search — it's what powers Curate Deck and the Library's retention scores. By default that means your card text is sent to Voyage AI's cloud embedding service to build the search index. That's the only thing that leaves your computer, and only for that purpose — there's no other AI feature, and no telemetry. Switch the embedding provider to Ollama in Manage models for a fully local alternative: a model running on your machine, no account and no key, at somewhat lower search quality.

Requirements
• Anki 23.10+ (Qt 6.5+ recommended for the PDF viewer)
• A free Voyage AI key for the default cloud embedding provider — or switch the provider to Ollama (bring your own install, or let Klaus manage one for you) to skip that

Support & feedback
Discord: https://discord.gg/uFRgE8RtDY
```

---

## Update / changelog note (optional, for version bumps)

Use this slot on the AnkiWeb upload form to summarise what changed in the new build.
