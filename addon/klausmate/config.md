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

## Klaus panel (semantic deck curation)

The Klaus panel opens from the **Klaus** button in the top-right of Anki's
toolbar (or Tools → Klaus → Open Klaus). It has one job: **curate a deck
from a lecture**. Describe the lecture (and/or pick an imported lecture
PDF), Klaus semantically searches every card in your collection, tags the
best matches `klaus::curate`, and opens them in Browse. Prune the list
there, then **Notes → Klaus: Create curated deck from selection…** copies
them into a new deck — originals are never moved, and the whole copy is
one undo step. Copies get the `klaus::curated` tag.

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

## Feature toggles

- **image_crop_enabled**: Enable the image crop feature (right-click an
  image in a note field → **Crop image**, or double-click the image). The
  crop is always saved as a *new* media file — the original is untouched.
  Default `true`.
