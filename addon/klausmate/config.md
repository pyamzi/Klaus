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

## Semantic library (matching + retention)

One embed per imported PDF serves two jobs, both driven by the same match
cache: **which cards a PDF covers** and **PDF study priorities**. Indexing
a PDF — the Library's **Add to Search Index** / **Update Search Index** —
refreshes the card index, then scores every card in your collection
against that PDF once. The same ranked list fills the PDF's `!Library`
tag and aggregates into its retention score.

**Seeing a PDF's cards**: the Library's **Show Matched Cards in Browse**
opens the PDF's own `!Library` tag, which holds exactly its matches at or
above that PDF's sensitivity. Indexing writes that tag; nothing extra is
needed to produce it.

**Copying cards into a new deck**: select notes in Browse — the tag above
is one good way to find them — then **Notes → KlausMate: Create Curated
Deck from Selection…**. Originals are never moved and the whole copy is
one undo step; copies get the `!Library::Curated` tag.

*(A "Curate Deck" button used to sit on the deck screens and in the
Library's right-click menu. It never created a deck: it tagged the
matches and opened Browse on that same `!Library` tag, so it has been
removed. An earlier version of this file also described a temporary
`!Library::Curating` tag, which was retired two releases before that.)*

- **pdf_match_threshold**: The single sensitivity control — how closely a
  card must match a PDF to count, for the priorities score and the
  `!Library` tags alike. Default `0.75`. Each PDF also has its own
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
- **assistant_backend**: `direct` (your own API key) or `hosted`
  (KlausMate's service holds the keys). Hosted is only used when
  `assistant_token` is set — an empty token would otherwise fail every
  call on a machine with a working key beside it.
- **assistant_api_key**: your own provider key, used by the `direct`
  backend. Never sent to KlausMate's service.
- **assistant_token**: your KlausMate sign-in token, used by the
  `hosted` backend. The subscription is checked by the service; the
  add-on ships as readable Python and cannot enforce it locally.
- **embedding_dimensions**: output width for OpenAI's v3 embedding
  models, which are MRL-trained so a shorter vector keeps the most
  significant components. `1024` is the default: better retrieval than
  `text-embedding-3-small` at 1536, while being cheaper to rank and
  smaller on disk. `0` means the model's own width (3072 for -large).
  Ignored by Voyage and Ollama, whose APIs have no such parameter.
  Changing it forces a full re-index.
- **embedding_model**: Embedding model ID. Empty means the provider
  default (`voyage-3-lite` / `text-embedding-3-small` /
  `nomic-embed-text`). Changing provider or model rebuilds the index.
- **embedding_api_key_openai** / **embedding_api_key_voyage**: API key for
  the matching cloud provider. Stored in this add-on's config
  (`meta.json`, plain text — standard for Anki add-ons).

### PDF study priorities

The Library shows a per-PDF retention score — the share of that PDF's
matched cards (at or above its sensitivity, see `pdf_match_threshold`
above) you'd currently recall — so you know what to study first. It reads
the same match cache the `!Library` tags do; nothing here embeds anything
indexing wouldn't already need.

- **pdf_match_agg**: How a card's score against a PDF's chunks is
  aggregated — `max` (default) or `top3_mean` (mean of the 3 best chunk
  matches; stricter, suppresses one-off spurious hits).
- **pdf_index_max_chunks**: Cap on embedded chunks per PDF (default
  `1000`). Very large PDFs are evenly down-sampled to this many chunks.

### Lecture view (review screen)

- **`lecture_view_reopen`** (default `true`): when the Lecture panel was
  left open, reopen it automatically the next time a review starts.
  The panel itself is toggled from the reviewer's bottom-bar
  **Library** button (next to More), the **L** key, or the reviewer's
  context menu -> Lecture View. It shows the lecture page that best
  matches the current card (resolved from the same embeddings the
  Library's matching uses — the note's `!Library` tag picks the PDF,
  the argmax chunk picks the page) and follows along as cards change;
  when a card has no matching lecture it says "No lecture page
  available for this card." Panel width and open-state live in
  `pdf_tabs.json` (`lecture_view` key) — state, not preferences.

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
  those tags entirely; **Show Matched Cards in Browse** then has no tag
  to open, so it is the one feature this switch costs you. Retention
  scores and the deck copier are unaffected.

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
  `"color"` (gradient spheres — there is no flat-colour mode), or
  `"image"`. The Preferences rows below it only appear for the mode
  that is actually selected (and only while the KlausBook design is
  on); a chosen image can be removed again from its caption's
  **Remove** link. Sets the background of Anki's deck and
  overview screens; the panel family itself follows `klausbook_design`
  in every mode — native mode is where Anki looks stock. The top and
  bottom toolbars are independent of this setting — they always show
  flat chrome matching the window's own colour, whatever wallpaper (or
  none) is chosen here.
- **background_color**: `#rrggbb` fill for `"color"` mode (also the
  colour behind a transparent or still-loading image). Default
  `"#FFFFFF"` — both screens default to a plain white ground. When a
  gradient is armed (below) this is its CENTRE colour.
- **background_gradients**: the gradient SPHERES — a list of up to 4
  `{color, x, y, size}` entries, each painted as its own radial blob
  (its colour at the centre fading to transparent at its edge) over
  the plain ground; the backdrop is not configurable and follows
  Anki's theme — white in light mode, dark at night. A sphere still
  wearing the default white counts as UNSET and paints nothing (its
  handles stay on screen — click its dot to give it a colour).
  Edited entirely ON the deck screen while Preferences is open: drag
  a sphere's dot to move it, its ring grip to resize, click the dot
  to recolor, right-click it to remove, and the ＋ pill adds another.
  When this list is missing it is built from the legacy
  single-gradient keys below. (A `background_color2` from the brief
  era the backdrop was configurable is ignored.)
- **background_grad_x** / **background_grad_y** /
  **background_grad_size**: legacy single-gradient geometry (mirrors
  of the first sphere; defaults `50`/`42`/`100`) — kept so a
  pre-sphere config renders unchanged.
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
  **reviewer_background_wash** / **reviewer_background_gradients** /
  **reviewer_background_grad_x/_y/_size**: the SAME settings, `"theme"`-mode
  default, but for the study screen — completely independent of
  `background_*` above, so you can show a different picture while
  reviewing cards than the one behind the deck list. No matching
  panel-frost key: the study screen has no panels to frost, so
  nothing would consume it — the wash is its own layer and does
  apply. While a study background is set, the CARD's own background
  is neutralised so the wallpaper is actually visible (many shared
  notetypes — AnKing's among them — paint the card opaque with
  `!important`, which hid the wallpaper behind a hard edge at the
  card's bottom). Only the background: the card's text colours,
  borders and layout are untouched. Choose **Anki's Own** for the
  study screen to hand the card its background back. Set it under **KlausMate Preferences → Appearance → Study
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
- **heatmap_history_days**: how much past the grid draws, in days —
  `91`, `182` or `365` (default). Set it from the heatmap's own corner
  menu (the ⚙-style glyph at the panel's top right) → **Range**. Any
  other value reads as 365 rather than being allowed to size the grid.
- **heatmap_forecast**: `true` (default) ghosts the next four weeks of
  scheduled cards to the right of today; `false` stops the grid at
  today. Same corner menu → **Upcoming**. Only an explicit `false`
  hides them.
- **dashboard_order**: the order of the deck-screen widgets, top to
  bottom (default `["decks", "heatmap"]`). Normally written by the
  dashboard itself: right-click a widget → *Edit Widgets…*, then drag
  to rearrange, ⊖ to remove, ＋ to add back (removal/re-adding writes
  the widget's own toggle, e.g. `heatmap_enabled`). Unknown entries are
  ignored; missing ones reappear in default order. Inert while
  `klausbook_design` is off — native mode draws no widgets at all, and
  the saved order waits for the design layer.

Apart from `heatmap_enabled` and `dashboard_order` (written from the
deck screen's own Edit Widgets mode) and the two `heatmap_*` display
keys above (the heatmap's own corner menu), all of these live in **KlausMate
Preferences → Appearance**; press **Save** and they apply immediately
(no restart).
