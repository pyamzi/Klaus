# AnkiWeb listing — Klausmate

Paste the body below into the **description** box on the AnkiWeb shared-add-on page when publishing or updating. Keep it under AnkiWeb's character limit.

---

## Short tagline (page subtitle / GitHub About)

Inline AI autocomplete, ⌘K rewrites, and semantic deck curation for Anki. Local by default — Ollama runs autocomplete and Ask on your machine; semantic search adds an optional cloud step.

---

## Full description

```
Klausmate — inline AI autocomplete for the Anki editor, plus semantic search and deck curation grounded in your lecture PDFs.

Features
• Ghost-text autocomplete as you type — Tab to accept, Esc to dismiss. Only fires at the end of a field, after whitespace, so it never gets in your way.
• Cycle alternates with Cmd+Shift+] / Cmd+Shift+[; past the last suggestion Klaus generates a new variant.
• Cmd+K Ask — popover for free-form edits ("rephrase this", "make this a cloze", "shorten", "translate", …) on the focused field. Runs on a local Ollama model by default; Claude is selectable for tougher rewrites.
• Lecture PDF support — drop a PDF into the editor panel, or dock it beside your cards in the Add window. Klaus grounds suggestions in the page or chunks you're viewing.
• PDF drive — a library window listing every PDF you've imported, each with a retention score (how well you currently recall its matched cards) and a right-click to curate a deck from it.
• Curate Deck — describe a topic or hand Klaus a lecture PDF, and it searches your whole collection by meaning to build a deck from the best-matching cards, tagged for your review first.
• Native PDF tools — drag-select text (Cmd+C or right-click Copy) and a toolbar Copy page button that grabs the current page as an image (Cmd+V to paste).
• Settings: Tools → Klaus → Settings… (models, hotkeys, prompts, retrieval). Tools → Klaus → Manage models… to pull / switch / delete Ollama models.

Privacy — read before installing
Autocomplete and Ask run on a local Ollama model by default: nothing leaves your computer for those. Semantic search and Curate Deck are different — they default to Voyage AI's cloud embedding service, so your card text is sent to Voyage to build the search index. Switch the embedding provider to Ollama in Settings for a fully local alternative (no account, no key, slightly lower quality). Ask can likewise be pointed at Claude for stronger rewrites if you supply your own API key.

Requirements
• Anki 23.10+ (Qt 6.5+ recommended for the PDF viewer)
• Ollama running locally: https://ollama.com
• At least one model pulled, e.g.  `ollama pull qwen3:0.6b`
• A free Voyage AI key for semantic search's cloud default, or switch the embedding provider to Ollama to skip this

Support & feedback
Discord: https://discord.gg/uFRgE8RtDY
```

---

## Update / changelog note (optional, for version bumps)

Use this slot on the AnkiWeb upload form to summarise what changed in the new build (e.g. "Fixed PDF text selection alignment; added 'Copy page' toolbar button; new packaging script.").
