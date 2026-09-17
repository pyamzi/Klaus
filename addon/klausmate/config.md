# KlausMate Configuration

## API keys & models

Klaus is API-first: semantic search runs on OpenAI, through **your own**
`api_key_openai`. The assistant is separate — it runs on your own Claude
Code login (the `claude` CLI, launched as a child process), not on a key
stored here. There is no local engine to install, start or update any
more. Set both keys in **KlausMate Preferences → API keys & models**;
they are stored in this add-on's config (`meta.json`, plain text —
standard for Anki add-ons) and never in the repo.

- **api_key_openai**: Your OpenAI API key. Default `""`. Powers card and
  PDF embeddings (see **Card embeddings** below) and lecture
  transcription. Without it nothing indexes, and Klaus says so rather
  than failing quietly.
- **api_key_anthropic**: Your Anthropic API key. Default `""`. Used for
  exactly one thing: the **pertinence check** at the end of indexing (see
  **Doubtful cards** below), which asks Claude whether each matched card
  is really about the lecture page it matched. Without it, indexing still
  works — the check is skipped for new matches and every match counts, as
  it did before; verdicts from an earlier judged run stay until that card
  or page changes. The assistant does not read this key; it runs on your
  own Claude Code login instead (see **Assistant** below).
- **reasoning_model**: Free text, default `"claude-sonnet-5"`. Two uses,
  one live: it is the model the **pertinence check** asks, and it is what
  a future release (Plan 3) will move the assistant onto. The assistant's
  Claude Code child does not read it today. Because the field is free
  text, a model Klaus has no price for is estimated as Sonnet and the
  confirm says so.
- **transcription_model**: Which OpenAI model transcribes recorded
  lecture audio. Default `"gpt-4o-mini-transcribe"`. Used whenever a
  recorded chunk is uploaded (see **Recording a lecture** below).
- **_embed_key_setup_declined**: Written automatically when you dismiss
  the "needs an API key" nudge, so Klaus stops re-prompting at startup.
  Delete it to see the nudge again. Cleared ONCE by the 2026-09-15
  migration: it was a "no thanks" to an optional key, back when a local
  engine existed, and the API-first release genuinely requires one — so
  an upgrading profile gets exactly one fresh nudge.
- **_v2_index_sweep_offered**: Written automatically after Klaus offers,
  once per profile, to rebuild PDF indexes written before the one-vector-
  per-page format (those read as no index at all). Set whether you accept
  or decline. Delete it to be asked again.

### Klaus Plus

Klaus Plus is the alternative to the two keys above: one subscription,
one key, and Klaus talks to its own service instead of to OpenAI and
Anthropic directly. Bring-your-own-keys stays free and unchanged — a
Plus key simply makes the provider keys unnecessary, and deleting it
puts you straight back on them.

- **klaus_plus_key**: Your Klaus Plus licence key — the `kp_…` string
  from the welcome page after you subscribe, or from the email that
  follows it. Default `""`. With it set, `api_key_openai` and
  `api_key_anthropic` are not needed; the provider-key rows in
  Preferences stay editable anyway, so the free tier is one deletion
  away. Stored like every other key, in this add-on's config
  (`meta.json`, plain text), and never sent anywhere but the Klaus Plus
  service.
- **klaus_plus_cache**: Not a setting — state Klaus writes: the last
  verdict the service gave (active, past due, refused) with the date it
  was checked, the renewal date, and the quota readout Preferences shows.
  Default `{}`. Safe to clear: the next **Check** (or the next call that
  needs it) fills it in again. A refusal is remembered for 6 hours, then
  the service is asked again; an active verdict is honoured until the
  service refuses it.
- **klaus_plus_base**: The Klaus Plus service URL. Default `""`, which
  falls back to the built-in service, `https://klausmate.com`
  (`plus.DEFAULT_BASE`) — editable under **KlausMate Preferences →
  General → Klaus Plus service**. Change it only to point at a staging
  or self-hosted service.

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

### Doubtful cards (the pertinence check)

Matching by similarity finds cards about the same *subject*; it cannot
tell "this slide's actual content" from "the same organ system". So the
last step of indexing asks Claude, card by card, whether studying that
card would really be reasonable preparation for the one lecture page it
matched best. Cards it says no to are tagged **`!Library::Doubtful`**,
are left out of that PDF's retention score, and show up in the Library
row's Cards cell as "n · m doubtful". Right-click → **Doubtful cards…**
opens Browse on them.

- It **always asks first**. Before the first paid request of a job, a
  dialog says how many cards it would judge and roughly what that costs
  (on Klaus Plus, what it uses of your monthly allowance instead).
  **Skip** is the default button; skipping leaves those cards simply
  matched, exactly as before, and the index finishes normally.
- It needs `api_key_anthropic` (or a Klaus Plus key). With neither, the
  step is skipped silently — no dialog, nothing to decline: new matches
  stay unjudged (and count), while verdicts from an earlier judged run
  keep standing until their card or page changes. Removing a key never
  un-doubts a card by itself.
- **A card Claude does not answer for is never doubtful.** Unjudged
  counts as confirmed; only an explicit "no" rejects a card.
- Verdicts are cached per PDF and re-used until the card's text, the
  page's text, or the model changes — editing a note re-judges just that
  card on the next index, not the whole lecture.
- `!Library::Doubtful` is **one tag for your whole collection**, not one
  per PDF: its members are every card rejected by a lecture it still matches
  (raise a lecture's sensitivity past a card and that lecture's doubt
  about it lapses). So a card rejected for lecture A but confirmed for
  lecture B still carries the tag. **Doubtful cards…** narrows it to the lecture you clicked by
  searching for both tags at once.
- Nothing is ever suspended, deleted or untagged by this check. It only
  adds a tag and changes what the retention score counts.

### Recording a lecture

The **●** button on the PDF panel's title bar (and on the Lecture panel
during review) records your microphone while you follow along in the
slides. Every 30 seconds — or the moment you turn the page, whichever
comes first — the recording is cut and sent to OpenAI for transcription,
and the text is stored **on the page you were looking at when you said
it**. Press **■** to stop; the bar shows elapsed time and how many pieces
are still waiting to be transcribed. Once the last piece has been transcribed,
Klaus re-indexes that PDF, so the pages you spoke over are searchable by
what was said on them, and the assistant reads them too (if an upload
hangs, the re-index runs anyway after about twenty minutes).

- Only one recording at a time, across every panel. Klaus says so rather
  than quietly opening a second microphone.
- Nothing is recorded until you press ●, and there is no recording
  without a PDF open.
- A piece that cannot be uploaded — no key, no network, a subscription
  refusal — **keeps its audio** in the add-on's
  `user_files/recordings/<pdf>/` folder and is retried the next time you
  record that lecture. Once uploaded, the audio file is deleted; only the
  text is kept. Silence transcribes to nothing and is dropped.
- The transcript for the page you are on shows in a collapsible strip
  under the PDF, filling in live as pieces come back.

**Copying cards into a new deck**: select notes in Browse — the tag above
is one good way to find them — then **Notes → KlausMate: Create Curated
Deck from Selection…**. Originals are never moved and the whole copy is
one undo step; copies get the `!Library::Curated` tag.

*(A "Curate Deck" button used to sit on the deck screens and in the
Library's right-click menu. It never created a deck: it tagged the
matches and opened Browse on that same `!Library` tag, so it has been
removed. An earlier version of this file also described a temporary
`!Library::Curating` tag, which was retired two releases before that.)*

**Indexing starts by itself**: adding a PDF — dropped on the deck
screen, dropped on the Library tree, or picked through either Browse…
button — queues it for indexing straight away; you never have to press
anything. Ten PDFs at once queue ten jobs and run them one at a time, in
the order you added them. Whatever the job was started from, a thin bar
appears at the bottom of the main window with what is running, how far
along it is, and a **Stop** button; the Library shows the same line in
its own status area. Nothing starts before a profile is open, or while a
cloud provider has no API key (the bar says so). Stopping or failing
mid-way is always safe: partial work is saved as partial and the next
run resumes from it, and a PDF's `!Library` tag is only ever written by
a run that finished.

- **auto_index_on_add**: Default `true`. Set `false` to go back to
  indexing by hand from the Library (right-click a PDF → **Add to
  Search Index**). Only the automatic start is affected — the Library's
  button, the queue, the status bar and the model-change sweep all work
  the same either way.

**Changing the embedding model re-indexes everything.** Vectors made by
one model cannot be compared with another's, so when you change
model or `embedding_dimensions` in KlausMate Preferences,
saving offers to re-embed your notes and every indexed PDF from scratch.
It tells you how many of each first, and you can decline and keep
working on stale vectors, or stop the sweep part-way from the same bar.

- **pdf_match_threshold**: The single sensitivity control — how closely a
  card must match a PDF to count, for the priorities score and the
  `!Library` tags alike. Default `0.75`. Each PDF also has its own
  slider (PDF drive → right-click a PDF → **Match sensitivity…**), which
  overrides this for that PDF only.

### Card embeddings

Semantic search needs a one-time index of your cards (then it updates
incrementally — only new/edited notes are re-embedded). Configure and
build it in **KlausMate Preferences → API keys & models**; the index
itself lives in the add-on's `user_files/card_index/` folder. Card text
is sent to OpenAI's embeddings API when indexing and searching.

- **embedding_model**: Embedding model ID. Default
  `"text-embedding-3-large"`. Changing it rebuilds the index.
- **embedding_dimensions**: output width for OpenAI's v3 embedding
  models, which are MRL-trained so a shorter vector keeps the most
  significant components. `1024` is the default: better retrieval than
  `text-embedding-3-small` at 1536, while being cheaper to rank and
  smaller on disk. `0` means the model's own width (3072 for -large).
  Changing it forces a full re-index.

### PDF study priorities

The Library shows a per-PDF retention score — the share of that PDF's
**confirmed** cards (at or above its sensitivity, see
`pdf_match_threshold` above, minus anything the pertinence check
rejected) you'd currently recall — so you know what to study first. It
reads the same match cache the `!Library` tags do; nothing here embeds
anything indexing wouldn't already need. The Cards count and the
sensitivity slider's live preview use the same confirmed-only figure, so
the number never changes just because you opened a dialog.

### Lecture view (review screen)

- **`lecture_view_reopen`** (default `true`): when the Lecture panel was
  left open, reopen it automatically the next time a review starts.
  The panel itself is toggled from the reviewer's bottom-bar
  **Library** button (next to More), the **L** key, or the reviewer's
  context menu -> Lecture View. It shows the lecture page that best
  matches the current card (resolved from the same embeddings the
  Library's matching uses — the note's `!Library` tag picks the PDF,
  and the PDF's best-scoring page is the page) and follows along as
  cards change;
  when a card has no matching lecture it says "No lecture page
  available for this card." Panel width and open-state live in
  `pdf_tabs.json` (`lecture_view` key) — state, not preferences.

## Assistant

The assistant answers about whatever lecture page you are looking at,
reaching it as the page record Klaus keeps for it — the slide's own text
plus any transcript of what was said over it — together with the page
image. It runs on your own Claude Code login today — the `claude` CLI,
launched as a child process, not a Klaus-held key. `api_key_anthropic`
and `reasoning_model` (see **API keys & models** above) belong to the
pertinence check, not to the assistant — it does not read either of them
yet; a future release will move it onto them.

- **assistant_reopen**: Default `false`. Reopen the Assistant dock
  where you left it the next time Anki starts — the same idea as
  `lecture_view_reopen` above. Only reopens it if it was open when you
  last closed the profile (see `assistant_dock_open`).
- **assistant_dock_width**: Default `420`. The Assistant dock's last
  width in pixels, written by dragging the dock itself rather than a
  Preferences row.
- **assistant_dock_open**: Default `false`. Whether the Assistant dock
  was open the last time you opened or closed it. Written by the dock
  itself, never by a Preferences row; `assistant_reopen` is what decides
  whether it is acted on.

**Clear Sessions** (KlausMate Preferences → Assistant) deletes the
saved per-PDF conversation history the Assistant keeps. It never
touches your notes, PDFs, or highlights.

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
  those tags entirely — including `!Library::Doubtful` — so **Show
  Matched Cards in Browse** and **Doubtful cards…** have no tag to open.
  That is all this switch costs you: retention scores (confirmed-only
  included), the doubtful counts in the Library, and the deck copier are
  unaffected, and the pertinence check still runs and still caches its
  verdicts.

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
