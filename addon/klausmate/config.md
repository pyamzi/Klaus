# KlausMate Configuration

## Local models

Runtime and model downloads use the network. Embedding and transcription
inference runs locally; external-client processing follows its provider choice.
Sources: [defaults](config.json), [Preferences](manage_models.py),
[local adapter](local_transcription.py) and [Ollama runtime](ollama_runtime.py).

Semantic search uses local Ollama embeddings, configured in
**KlausMate Preferences → Local models**. Provider credentials are removed
from existing profiles during migration.

- **embedding_provider**: `"ollama"`, the only embedding provider.
- **endpoint**: Local Ollama HTTP address. Default `"http://127.0.0.1:11434"`.
- **runtime_auto_setup**: Default `true`. On profile open Klaus checks for
  an existing Ollama server or starts an installed runtime in the background.
  This does not install a runtime or download models. Set `false` to manage
  the server yourself.
The **Ollama runtime** row shows the estimated runtime download size before
**Install/start** or **Update runtime** is clicked. These buttons authorize a
runtime download if needed. **Install/start** reuses or starts an installed
runtime first. **Update runtime** is enabled after **Refresh** when Klaus owns
a running managed runtime older than the bundled target version. Runtime files
live under `user_files/runtime/` in the add-on. **Stop managed server** only
stops a process Klaus started or adopted; an external Ollama process must be
stopped in the application that started it.

**Refresh** checks runtime health and reloads **Installed models**. Opening
Preferences does not start Ollama or download anything. Select a listed model
to populate **Embedding model**, then **Save** to apply it and receive the
ordinary re-index offer. Refresh, Pull and Delete never change the saved
embedding model. Enter a name under **Download model** and click **Pull** to
download it; **Download progress** reports runtime and model transfers.
**Delete** asks for confirmation. Models are stored by the configured Ollama
server. Closing Preferences allows an active local operation to finish in the
background. Closing the Anki profile cancels its runtime work and stops owned
servers; the next profile waits for any late startup to be cleaned up.
If starting or updating the runtime chooses a free port for the saved endpoint,
the new address is saved automatically, even after Preferences closes. A newer
saved endpoint edit takes precedence. Manual unsaved endpoint and model choices
still require **Save**; starting from an unsaved endpoint does not apply it.

- **embedding_model**: The model name in **Embedding model**, initially
  `"nomic-embed-text"`. It must be installed on the configured Ollama server.
- **runtime_auto_setup** is controlled by **Automatic management**; toggle it
  and click **Save**. This controls profile-open startup of installed runtimes.

- **_local_embeddings_migrated**: Internal one-time migration marker. The first
  migration selects `nomic-embed-text` with native dimensions and removes old
  credentials. Later migrations preserve your local model selection.

- **transcription_model_path**: Local whisper.cpp model file. Default `""`.
  Install whisper.cpp and download a compatible model using the
  [official setup instructions](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/cli/README.md).
  Select the model in **Preferences > Local models > Transcription model**.
- **transcription_binary**: Optional path to the whisper.cpp executable.
  Default `""` uses automatic discovery. Use Browse for a custom installation.
- **transcription_language**: Language code for recorded lectures, default `"en"`.
  Transcription runs locally. Failed audio stays on disk for the next attempt.
- **_v2_index_sweep_offered**: Written automatically after Klaus offers,
  once per profile, to rebuild PDF indexes written before the one-vector-
  per-page format (those read as no index at all). Set whether you accept
  or decline. Delete it to be asked again.

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

### Cosine matching

Matching and retention use the configured cosine threshold. No reasoning pass
or Doubtful menu remains. Historical `!Library::Doubtful` tags are reserved and
preserved, but do not exclude cards from scores. See [tag sync](tag_sync.py).

### Recording a lecture

The **●** button on the PDF panel's title bar (and on the Lecture panel
during review) records your microphone while you follow along in the
slides. Every 30 seconds or when you turn the page, whichever comes first,
the recording is cut and processed locally by whisper.cpp,
and the text is stored **on the page you were looking at when you said
it**. Press **■** to stop; the bar shows elapsed time and how many pieces
are still waiting to be transcribed. Once the last piece has been transcribed,
Klaus re-indexes that PDF, so the pages you spoke over are searchable by
what was said on them, and external clients can request them too (if transcription
hangs, the re-index runs anyway after about twenty minutes).

- Only one recording at a time, across every panel. Klaus says so rather
  than quietly opening a second microphone.
- Nothing is recorded until you press ●, and there is no recording
  without a PDF open.
- A piece that cannot be transcribed because a local dependency is unavailable
  or a subprocess fails **keeps its audio** in the add-on's
  `user_files/recordings/<pdf>/` folder and is retried the next time you
  record that lecture. Once successfully transcribed, the audio file is deleted; only the
  text is kept. An empty transcript is dropped.
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
its own status area. Nothing starts before a profile is open. Ollama connection or model errors
are reported by the indexing operation. Stopping or failing
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
the model in KlausMate Preferences,
saving offers to re-embed your notes and every indexed PDF from scratch.
It tells you how many of each first, and you can decline and keep
working on stale vectors, or stop the sweep part-way from the same bar.

- **pdf_match_threshold**: The single sensitivity control — how closely a
  card must match a PDF to count, for the priorities score and the
  `!Library` tags alike. Default `0.75`. Each PDF also has its own
  slider (PDF drive → right-click a PDF → **Match sensitivity…**), which
  overrides this for that PDF only.

### Card embeddings

Semantic search indexes your cards once and then updates changed notes.
Configure and build the index in **KlausMate Preferences → Local models**.
Vectors are stored in `user_files/card_index/`. Card and page text are sent
only to the configured local Ollama endpoint.

- **embedding_model**: Default `"nomic-embed-text"`. The model must be
  available in Ollama. Changing it offers a full local re-index.
- **embedding_dimensions**: `0`, using the model's native output width.
  Other values are ignored by the local adapter.

### PDF study priorities

The Library shows a per-PDF retention score — the share of that PDF's
matched cards (at or above its sensitivity, see
`pdf_match_threshold` above) you'd currently recall, so you know what to study first. It
reads the same match cache the `!Library` tags do; nothing here embeds
anything indexing wouldn't already need. The Cards count and the
sensitivity slider's live preview use the same matched-card figure, so
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

## Assistant history

As of 2026-09-19 the embedded assistant, its sessions and dock settings are
removed. Use the external MCP client setup below.

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
- **library_tags_enabled**: Optional stored override, read as `true` when
  absent; not a key in the shipped defaults. Controls creation, renaming and
  pruning of per-PDF `!Library` tags. Turning it off leaves cosine retention
  scoring and deck copying available, but stops automatic membership updates.
  See [tag sync](tag_sync.py).

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


## External MCP clients

In **KlausMate Preferences → Local models → MCP**, copy the
configuration. Install a separate Python 3.9 or newer first if Copy is disabled,
then reopen Preferences. Keep Anki running with your profile open. Merge the
`klaus` entry into `mcpServers` in Claude Desktop's configuration and restart
Claude Desktop. See the [official local-server setup guide](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers).

The generated JSON uses absolute paths to Python, the bundled stdio bridge,
and `user_files/mcp_connection.json`. It contains no token or current port.
The bridge reads that private discovery file for each request, so an Anki
restart does not require copying new credentials. Klaus never writes another
application's configuration. Copy the block again if you move the add-on or
Python installation.

`current_page` returns the active PDF's ID, name, page number, selection, slide
text and transcript, plus a page image when available. Set `include_image: false`
for text only. `get_page` accepts `pdf_id` and a one-based `page` for any imported
lecture, without changing the viewer; set `include_image: true` to request its
image. Lecture search now returns a `pdf` ID alongside its existing `source`.
Closing the viewer clears `current_page`; other imported lectures remain
accessible through `get_page`. `current_view` retains its metadata-only behavior.

MCP `add_note` now requires both `source_pdf` and `source_page`. Use the `pdf`
and `page` returned by a page or lecture-search tool. A missing source is rejected
before approval, rather than attributed to whichever PDF is currently open.
Reconnect the external client after upgrading so it refreshes the tool schemas.
`add_notes` accepts 1-20 notes with those same fields, shows one approval, and
returns a zero-based `index`, `note_id` and `error` for each note. A batch can
partially succeed. Check its outcomes and Anki before retrying a failed or
interrupted request; requests are never automatically replayed.

Collection writes still require approval in Anki. Lecture content is untrusted
input and is not an instruction to the external client.

Your external client chooses its model provider and may transmit requested
lecture text, transcripts, images and card context to that provider. Klaus
exposes only its authenticated local endpoint. This setup does not provide
public hosting or direct ChatGPT access. Automated checks cover the stdio
bridge and Preferences clipboard. The official MCP Python client is also tested
against a scratch endpoint; a real Claude Desktop session has not been verified
by those checks. See [MCP interface and verification](../docs/reference/mcp-interface.md).

## Stored state and optional overrides

The shipped defaults are exactly [config.json](config.json). `library_tags_enabled`
is an optional override with a code fallback, not a shipped default.
`background_gradients` and `reviewer_background_gradients` are saved sphere lists
created by Appearance; legacy scalar coordinates supply missing-list fallback.
`library_root` is written after choosing a library folder.
`_local_embeddings_migrated`, `_v2_index_sweep_offered` and
`_library_tag_migrated` are automatic migration/offer state, not user controls.
The old cloud credential, subscription, judge and dock keys are removed during
[migration](__init__.py). Other historical keys are not current settings.
