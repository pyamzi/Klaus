# Klausmate Configuration

## Model & connection

- **autocomplete_model**: Ollama model for inline ghost-text autocomplete
  (e.g. `qwen3:0.6b` — a small/fast model is ideal).
- **ask_model**: Ollama model for **Cmd+K Ask** and the per-field pen autofill
  (e.g. `qwen3:4b` — a larger model often gives better answers).
- **model**: Legacy fallback; kept in sync with `autocomplete_model` when you
  save settings. If only `model` is set (older configs), both flows use it.
  You must `ollama pull <model>` for each tag you use, or assign them in
  **Tools → Klaus → Manage models…** under *What Klaus uses*, where each job
  has one dropdown.
- **endpoint**: URL of your local Ollama server. Default `http://localhost:11434`.
  If Klaus's managed server has to move to another port (something else owned
  11434), this is updated automatically.
- **generate_timeout_s**: Seconds to wait for autofill, Ask, and long completions
  (default `180`). Health checks and model listing still use a short 30s timeout.

## Local AI engine (automatic Ollama)

- **runtime_auto_setup**: Default `true`. Klaus manages the local AI engine for
  you: at startup it silently starts Ollama when a copy exists (yours or its
  own), and when none exists it offers a **one-click setup** that downloads the
  official Ollama runtime from the [ollama/ollama GitHub release]
  (https://github.com/ollama/ollama/releases) — MIT-licensed, verified against
  the release's published SHA-256 checksums — into the add-on's
  `user_files/runtime/` folder. Nothing is bundled with the add-on, and
  nothing is downloaded before you confirm the setup prompt (which states
  both the engine size and, on first-run setup, the starter model it will
  pull). A server Klaus starts is stopped when Anki quits; an Ollama you
  installed yourself is never touched. Set `false` to disable all automatic
  startup behavior (no silent server start, no setup offers) — the one-click
  setup then remains available only manually via **Manage models…**.
- Limitation: with two Anki instances open at once, the first instance to
  quit stops the shared managed server; the other restarts it on demand.
- **_runtime_setup_declined**: Written automatically when you dismiss the
  setup offer so Klaus stops re-prompting at startup. Delete it (or run the
  setup from **Manage models…**) to see the offer again.
- Models always live in the standard shared `~/.ollama` directory, so they are
  shared with any other Ollama install and survive add-on updates. To reclaim
  the engine's disk space use **Remove Klaus-managed runtime** in Klaus
  settings.

## Sampling

- **temperature**: Sampling temperature (0.0–2.0). Lower = more conservative.
- **top_p**: Nucleus sampling cutoff. `0.9` is a sensible default.
- **top_k**: Top-K sampling cutoff. `40` is typical.
- **repeat_penalty**: Penalty for repeated tokens. `1.1` is mild.

## Hotkeys & triggering

Ghost-text suggestions auto-fire while you type (debounced, with smart
gates that suppress mid-word edits, pastes, IME composition, and recent
dismissals). Tab accepts the visible ghost; Esc dismisses it.

- **ask_hotkey**: Opens the inline ASK popover so you can type a free-form
  prompt. Default `Cmd+K`. Examples: `Ctrl+K`, `Alt+Enter`, `Cmd+/`.
- **debounce_ms**: Milliseconds of idle time after the last keystroke before
  a suggestion request is fired. Default `400`. Lower = snappier but noisier.
  Suggestions only fire when the caret is at the very end of the field AND
  the character immediately before the caret is whitespace (`"word |"` fires,
  `"word|"` does not) — never mid-text, never touching the last word.
- **min_chars_before_trigger**: Minimum field length before auto-suggest
  fires. Default `8`. (A hard floor still prevents firing on visually-blank
  fields regardless of this value.)
- **paste_cooldown_ms**: After a paste, suppress auto-suggest for this many
  ms. Default `800`.
- **dismissal_cooldown_ms**: After you press Esc on a suggestion, suppress
  re-firing for this many ms unless the field grows/shrinks by more than
  5 characters. Default `600`.
- **accept_cooldown_ms**: After you Tab-accept, suppress auto-suggest for
  this many ms so the just-inserted text doesn't immediately trigger a
  fresh request. Default `200`.

Hotkey strings accept these modifiers: `Cmd` / `Meta` / `Command`, `Ctrl` /
`Control`, `Shift`, `Alt` / `Option`. The key name comes last (e.g. `K`,
`Space`, `Enter`, `/`).

## Klaus panel (semantic deck curation)

The Klaus panel opens from the **Klaus** button in the top-right of Anki's
toolbar (or Tools → Klaus → Open Klaus). It has one job: **curate a deck
from a lecture**. Describe the lecture (and/or pick an imported lecture
PDF), Klaus semantically searches every card in your collection, tags the
best matches `klaus::curate`, and opens them in Browse. Prune the list
there, then **Notes → Klaus: Create curated deck from selection…** copies
them into a new deck — originals are never moved, and the whole copy is
one undo step. Copies get the `klaus::curated` tag.

- **chat_hotkey**: Shortcut for toggling the panel. Default `Ctrl+Shift+K`
  (Cmd+Shift+K on macOS).
- **curate_top_k**: How many of the best-matching notes a search tags for
  review. Default `100`.
- **curate_min_score**: Minimum cosine similarity (0–1) for a match.
  Default `0.35`. Raise it for stricter matches, lower it if searches come
  back empty.

### Card embeddings

Semantic search needs a one-time index of your cards (then it updates
incrementally — only new/edited notes are re-embedded). Configure and
build it in **Tools → Klaus → Manage models… → What Klaus uses →
Semantic search**; the index itself lives in
the add-on's `user_files/card_index/` folder. With a cloud provider
(the default), card text is sent to that provider's API when indexing
and searching; pick `ollama` if you want embeddings to stay fully on
your machine.

- **embedding_provider**: `voyage` (default — cloud API, needs a free key
  from voyageai.com), `openai` (cloud, needs a key), or `ollama` (local,
  free, private — limited by your machine's RAM). Existing installs keep
  whatever provider they already had configured.
- **embedding_model**: Embedding model ID. Empty means the provider
  default (`voyage-3-lite` / `text-embedding-3-small` /
  `nomic-embed-text`). Changing provider or model rebuilds the index.
- **embedding_api_key_openai** / **embedding_api_key_voyage**: API key for
  the matching cloud provider. Stored in this add-on's config
  (`meta.json`, plain text — standard for Anki add-ons).

### PDF study priorities

Each imported PDF can be embedded and semantically matched against your
cards; the Klaus panel then shows a per-PDF retention score so you know
what to study first.

- **pdf_match_threshold**: Default similarity cutoff (0–1) for counting a
  card as "about" a PDF. Default `0.35`. Each PDF also has its own slider
  in the panel, which overrides this.
- **pdf_match_agg**: How a card's score against a PDF's chunks is
  aggregated — `max` (default) or `top3_mean` (mean of the 3 best chunk
  matches; stricter, suppresses one-off spurious hits).
- **pdf_index_max_chunks**: Cap on embedded chunks per PDF (default
  `1000`). Very large PDFs are evenly down-sampled to this many chunks.

## Ask (⌘K) engine

This answers **Cmd+K Ask** in the editor. Inline ghost-text
autocomplete always stays on the local Ollama model — per-keystroke cloud
calls would be slow and expensive. Configure in **Tools → Klaus →
Manage models…**.

- **klaus_engine**: `ollama` (default — the local Ask model) or `claude`
  (single-shot Anthropic API call; needs `claude_api_key`, billed to your
  API credits; your prompt, the field text, and retrieved PDF excerpts are
  sent to Anthropic).
- **claude_api_key**: Your Anthropic API key (get one at
  https://platform.claude.com). Stored in this add-on's config
  (`meta.json`, plain text; anyone with file access to your Anki profile
  can read it). Leave empty to stay fully local.
- **claude_model**: Model ID used when Ask runs on Claude. Default
  `claude-opus-4-8` (most capable); `claude-sonnet-5` and
  `claude-haiku-4-5` are cheaper options.
- **claude_timeout_s**: Network timeout for a Claude Ask call, in seconds.
  Default `300`.

## Feature toggles

- **autocomplete_enabled**: Master switch for inline ghost-text suggestions.
  Default `true`. Set `false` to disable autocomplete entirely while keeping
  ⌘K Ask available.
- **ask_enabled**: Master switch for the ⌘K Ask popover. Default `true`.
  Set `false` to disable Ask while keeping inline autocomplete.
- **image_crop_enabled**: Enable the image crop feature (right-click an
  image in a note field → **Crop image**, or double-click the image). The
  crop is always saved as a *new* media file — the original is untouched.
  Default `true`.

## How long the suggestion is

- **completion_mode**: One of `word`, `phrase`, `sentence` (default),
  `paragraph`, or `long`.
  - `word` — up to ~8 tokens, cut at the first whitespace.
  - `phrase` — up to ~40 tokens, cut at the first sentence boundary (`.!?`).
  - `sentence` — up to ~60 tokens, one **complete** sentence (must end with
    `.`, `!`, or `?`; no dependent-clause fragments). Smart about abbreviations
    like `e.g.` and `Dr.`.
  - `paragraph` — up to ~100 tokens, two or three complete sentences.
  - `long` — up to ~120 tokens, multi-line output allowed (enumerations).

  **Auto-promotion to `long`**: When your field ends with a list/definition
  cue (e.g. `…the three foo are:`, `…include:`, `…defined as`, or anything
  ending in `:`) AND the top retrieved PDF chunk's BM25 score clears the
  threshold (≥ 6.0), Klausmate temporarily upgrades to **long** (unless you
  chose `word` mode). Otherwise it stays in your selected mode.

## PDF retrieval

- **retrieval_method**: `keyword` (BM25) or `semantic`.
  - `keyword` is the default. Pure-Python BM25 across all chunks of all loaded PDFs.
    Catches term overlap (medical names, drug names, anatomy).
  - `semantic` is reserved for a future release that uses Ollama embeddings. Setting
    it today logs a notice and falls back to keyword.
- **retrieval_top_k**: How many of the highest-scoring chunks to include in the prompt.
  Default `4` (~1600 chars). Higher values give the model more context but slow it down
  and risk drowning the actual question.

PDFs added via **Tools → Klausmate → Manage lecture PDFs…** are chunked lazily on
first use (~400 chars per chunk, 50-char overlap, preferring paragraph boundaries).
The chunk index is cached and invalidated automatically when files change.

## Prompt

- **system_prompt**: Instruction for **inline autocomplete** only (ghost text).
- **ask_system_prompt**: Instruction for **Cmd+K Ask** (defaults to a field-editing prompt).
