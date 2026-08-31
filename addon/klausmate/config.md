# KlausMate Configuration

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
- **browse_highlight_default**: Default `true`. Whether Browse's "Highlight
  Search Results" is on by default in a fresh Browser window — while
  searching, matched terms are highlighted in the editor pane of the
  selected row (View menu → **Highlight Search Results** toggles it per
  window; this config key is only the starting state).
- **library_tags_enabled**: Default `true`. Keeps every indexed PDF's
  per-PDF `!Library` tag (one tag per PDF, holding exactly the notes
  matched at or above its sensitivity — see `pdf_match_threshold` above)
  created, renamed, and pruned automatically as you index, re-sensitize,
  rename, or delete PDFs. Turn off and Klaus stops creating or updating
  those tags entirely; since that same tag is also **Curate Deck**'s
  preview vehicle in Browse, the curation Browse-preview step is skipped
  while this is off (the final deck copy is unaffected).

- **pdf_renderer**: Default `"native"`. Which engine draws PDFs in the
  viewer panel and Library. `"native"` is Qt's built-in QPdfView;
  `"pdfjs"` switches to the bundled pdf.js webview renderer — smoother,
  flicker-free scrolling, but still reaching feature parity (highlights,
  find, and thumbnails land there incrementally — see the K-095 board
  umbrella). Toggle it from **KlausMate Preferences → General → "Use the
  new pdf.js viewer"**, then press **Save**. Requires an Anki restart to
  take effect.


## Appearance

- **color_theme**: Accent-colour preset — SynapsePro's six (`ocean`
  default-blue, `orchid`, `forest`, `deluge`, `horizon`, `dusty`),
  the community palettes (`nord`, `solarized`, `catppuccin`,
  `gruvbox`, `everforest`, `dracula`), `claude` (Anthropic's
  terracotta), or `custom` to use `color_theme_custom`.
  Applied to buttons, pills, highlights and the star logo everywhere
  Klaus draws. Pick it in **KlausMate Preferences → Appearance →
  Accent color** — the row of color squares, last one being your own
  — and press **Save**; applies immediately.
- **color_theme_custom**: `#rrggbb` behind the `custom` preset.
  Default `"#0071D3"`. You pick one colour; the hover, pressed and
  bright variants Klaus needs are derived from it (and the bright tone
  lifts further in dark mode, matching how the built-in presets
  behave). An invalid value falls back to the default rather than
  blanking the accent.
- **klausbook_design**: the master switch for the KlausBook design
  layer — the restyled toolbar and bottom bars, chrome-matched top
  bar, custom backgrounds, frosted panels, the studied-line weld,
  dashboard widget editing, and the harmonized Add Cards, Browse,
  Stats and reviewer-bar chrome (Browse keeps Anki's layout and
  density; the reviewer's scheduling colours and the cards themselves
  are never touched). **Default `false`: Klaus ships as tools
  inside a STOCK Anki**, and the KlausBook look is the opt-in — an
  existing profile that had the design reverts to Anki's native look
  after updating until this is switched on (nothing is lost: every
  background/accent setting stays stored and comes back with the
  switch). Klaus's own windows (Preferences, Library, PDF viewer) keep
  their design either way, and every tool keeps working.
- **background_mode**: `"theme"` (default — no wallpaper: Anki's own
  ground, with the Klaus panels on it whenever the design is on),
  `"color"` (a radial colour gradient — there is no flat-colour mode),
  or `"image"`. Sets the background of Anki's deck and
  overview screens; the panel family itself follows `klausbook_design`
  in every mode — native mode is where Anki looks stock. The top and
  bottom toolbars are independent of this setting — they always show
  flat chrome matching the window's own colour, whatever wallpaper (or
  none) is chosen here.
- **background_color**: `#rrggbb` fill for `"color"` mode (also the
  colour behind a transparent or still-loading image). Default
  `"#1E2225"`. When a gradient is armed (below) this is its CENTRE
  colour.
- **background_color2**: the gradient's EDGE colour. When empty (the
  default) it is derived automatically from the centre colour (~45%
  toward black — a quiet vignette), so colour mode is always a
  gradient; there is no flat mode. Set it via **Edge Color…** next to
  the Color button.
- **background_grad_x** / **background_grad_y**: the gradient's
  centre, as % of the window (defaults `50`/`42`). Adjusted by
  dragging the handle ON the deck screen itself while Preferences is
  open, not with sliders.
- **background_grad_size**: how far out the fade reaches, 10–200 %
  (default `100`) — dragged on-screen as well.
- **background_image**: filename of an image stored in
  `user_files/backgrounds/`. Choosing one in Preferences copies it
  there, so the background survives the original being moved.
- **background_fit**: `"cover"` (default), `"contain"` or `"tile"`.
- **background_blur**: 0–100 px of blur behind the deck panels in
  `"image"` mode (a no-op in `"color"`/`"theme"` mode — blurring a
  flat ground changes nothing). Default `22`. The Preferences row is
  labeled **Panel Frost** — it frosts what sits behind each panel,
  as opposed to the wash below, which treats the whole picture once.
- **background_wash**: 0–100 (default `0` = off) — the **Image Wash**:
  one soft veil plus a Gaussian blur over the WHOLE wallpaper,
  sitting between the picture and everything on it, so a busy photo
  can be muted without re-picking it. Theme-aware: white in light
  mode, near-black in night mode, so a wallpaper dims at night
  instead of glowing. Image mode only.
- **reviewer_background_mode** / **reviewer_background_color** /
  **reviewer_background_image** / **reviewer_background_fit** /
  **reviewer_background_wash** / **reviewer_background_color2** /
  **reviewer_background_grad_x/_y/_size**: the SAME settings, `"theme"`-mode
  default, but for the study screen — completely independent of
  `background_*` above, so you can show a different picture while
  reviewing cards than the one behind the deck list. No matching
  panel-frost key: the study screen has no panels to frost, so
  nothing would consume it — the wash is its own layer and does
  apply. Set it under **KlausMate Preferences → Appearance → Study
  screen background**.
- **heatmap_enabled**: `true` (default) draws the review heatmap — a
  year of study activity, plus the next four weeks of scheduled cards —
  under the deck list. Clicking a day opens it in Browse. `false`
  removes it entirely, hooks and query included. There is no
  Preferences switch for it: right-click the deck screen → **Edit
  Widgets…**, then ⊖ removes the heatmap and ＋ adds it back (that
  writes this key). **Needs `klausbook_design`**: the heatmap is a
  deck-screen widget, so native mode leaves Anki's deck screen stock
  and this setting waits (it is never rewritten by the design switch,
  so it comes back as you left it).
- **dashboard_order**: the order of the deck-screen widgets, top to
  bottom (default `["decks", "heatmap"]`). Normally written by the
  dashboard itself: right-click a widget → *Edit Widgets…*, then drag
  to rearrange, ⊖ to remove, ＋ to add back (removal/re-adding writes
  the widget's own toggle, e.g. `heatmap_enabled`). Unknown entries are
  ignored; missing ones reappear in default order. Inert while
  `klausbook_design` is off — native mode draws no widgets at all, and
  the saved order waits for the design layer.

Apart from `heatmap_enabled` and `dashboard_order` (written from the
deck screen's own Edit Widgets mode), all of these live in **KlausMate
Preferences → Appearance**; press **Save** and they apply immediately
(no restart).
