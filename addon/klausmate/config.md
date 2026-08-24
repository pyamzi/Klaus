# Klausmate Configuration

## Connection

- **endpoint**: URL of your local Ollama server. Default `http://localhost:11434`.
  Only used when `embedding_provider` is `ollama` — cloud providers (the
  default) don't need Ollama at all. If Klaus's managed server has to move
  to another port (something else owned 11434), this is updated
  automatically.

## Local AI engine (automatic Ollama)

- **runtime_auto_setup**: Default `true`. When you choose the local
  (`ollama`) embedding provider, Klaus manages the engine for you: at
  startup it silently starts Ollama when a copy exists (yours or its own),
  and when none exists it offers a **one-click setup** that downloads the
  official Ollama runtime from the [ollama/ollama GitHub release]
  (https://github.com/ollama/ollama/releases) — MIT-licensed, verified against
  the release's published SHA-256 checksums — into the add-on's
  `user_files/runtime/` folder. Nothing is bundled with the add-on, and
  nothing is downloaded before you confirm the setup prompt. A server Klaus
  starts is stopped when Anki quits; an Ollama you installed yourself is
  never touched. Set `false` to disable all automatic startup behavior (no
  silent server start, no setup offers) — the one-click setup then remains
  available only manually via **Manage models…**.
- Limitation: with two Anki instances open at once, the first instance to
  quit stops the shared managed server; the other restarts it on demand.
- **_runtime_setup_declined**: Written automatically when you dismiss the
  setup offer so Klaus stops re-prompting at startup. Delete it (or run the
  setup from **Manage models…**) to see the offer again.
- Models always live in the standard shared `~/.ollama` directory, so they are
  shared with any other Ollama install and survive add-on updates. To reclaim
  the engine's disk space use **Remove Klaus-managed runtime** in Klaus
  settings.

## Semantic library (curation + retention)

One embed per imported PDF now serves two jobs, both driven by the same
match cache: **curating a deck** and **PDF study priorities**. There is no
separate curation embed — indexing a PDF (from the PDF drive's **Add to
index** / **Re-index**, or automatically the first time you curate from an
unindexed PDF) scores every card in your collection against it once, and
that same ranked list is what curation tags and what the priorities view
aggregates into a retention score.

**Curating a deck**: the deck-browser/overview **Curate Deck** button, or
the PDF drive's **Curate deck from this PDF…** action, tags the matches at
or above that PDF's sensitivity with `!Library::Curating` and opens them
in Browse. Prune the list there, then **Notes → Klaus: Create curated deck
from selection…** copies them into a new deck — originals are never
moved, and the whole copy is one undo step. Copies get the
`!Library::Curated` tag.

- **pdf_match_threshold**: The single sensitivity control — how closely a
  card must match a PDF to count, for curation, the priorities score, and
  the `!Library` tags alike. Default `0.75`. Each PDF also has its own
  slider (PDF drive → right-click a PDF → **Match sensitivity…**), which
  overrides this for that PDF only.

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

The PDF drive shows a per-PDF retention score — the share of that PDF's
matched cards (at or above its sensitivity, see `pdf_match_threshold`
above) you'd currently recall — so you know what to study first. It reads
the same match cache curation does; nothing here embeds anything curation
wouldn't already need.

- **pdf_match_agg**: How a card's score against a PDF's chunks is
  aggregated — `max` (default) or `top3_mean` (mean of the 3 best chunk
  matches; stricter, suppresses one-off spurious hits).
- **pdf_index_max_chunks**: Cap on embedded chunks per PDF (default
  `1000`). Very large PDFs are evenly down-sampled to this many chunks.

## Feature toggles

- **image_crop_enabled**: Enable the image crop feature (right-click an
  image in a note field → **Crop image**, or double-click the image). The
  crop is always saved as a *new* media file — the original is untouched.
  Default `true`.
- **library_tags_enabled**: Default `true`. Keeps every indexed PDF's
  per-PDF `!Library` tag (one tag per PDF, holding exactly the notes
  matched at or above its sensitivity — see `pdf_match_threshold` above)
  created, renamed, and pruned automatically as you index, re-sensitize,
  rename, or delete PDFs. Turn off and Klaus stops creating or updating
  those tags entirely; since that same tag is also **Curate Deck**'s
  preview vehicle in Browse, the curation Browse-preview step is skipped
  while this is off (the final deck copy is unaffected).
