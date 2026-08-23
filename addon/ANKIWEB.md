# AnkiWeb listing — Klausmate

Paste the body below into the **description** box on the AnkiWeb shared-add-on page when publishing or updating. Keep it under AnkiWeb's character limit.

---

## Short tagline (page subtitle / GitHub About)

Copilot-style inline AI autocomplete for the Anki editor, powered by a local Ollama server. Local-first. No API keys.

---

## Full description

```
Klausmate — Copilot-style inline AI for Anki, powered by a local Ollama server. No API keys, no cloud, no telemetry. Everything runs on your machine.

Features
• Ghost-text autocomplete as you type — Tab to accept, Esc to dismiss. Only fires at the end of a field, after whitespace, so it never gets in your way.
• Cycle alternates with Cmd+Shift+] / Cmd+Shift+[; past the last suggestion Klaus generates a new variant.
• Cmd+K Ask — small popover for free-form edits ("rephrase this", "make this a cloze", "shorten", "translate", …). Operates on the focused field.
• Lecture PDF support — drop one PDF into the editor panel. Klaus grounds suggestions in BM25-retrieved chunks from your slides.
• PDF dock (Add window only) — scroll the lecture beside your cards. The page you're viewing becomes the primary context, overriding BM25 while the dock is open.
• Native PDF text selection — drag to highlight, then Cmd+C or right-click → Copy.
• Copy page — toolbar button copies the current PDF page as an image to the clipboard. Paste with Cmd+V.
• Settings: Tools → Klaus → Settings… (models, hotkeys, prompts, debounce, retrieval). Tools → Klaus → Manage models… to pull / switch / delete Ollama models.

Requirements
• Anki 23.10+ (Qt 6.5+ recommended for the PDF viewer)
• Ollama running locally: https://ollama.com
• At least one model pulled, e.g.  `ollama pull qwen3:0.6b`

Privacy
Nothing leaves your computer. No accounts, no API keys, no analytics. The add-on talks only to your local Ollama at http://localhost:11434.

Support & feedback
Discord: https://discord.gg/uFRgE8RtDY
```

---

## Update / changelog note (optional, for version bumps)

Use this slot on the AnkiWeb upload form to summarise what changed in the new build (e.g. "Fixed PDF text selection alignment; added 'Copy page' toolbar button; new packaging script.").
