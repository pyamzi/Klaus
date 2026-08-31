# CLAUDE.md — Addons repo / Klaus (klausmate)

The real project here is **`klausmate/`** — "Klaus", an Anki addon for
semantic deck curation (find cards matching a lecture PDF, copy them into a
new deck), a lecture-PDF library with per-PDF retention scoring, a native
PDF viewer with highlights/sticky notes, and image cropping. Around it:
`tests/` (headless logic tests), `board/` + `context/` (the multi-agent
kanban board — see below), `References/` and `scripts/` (vendored
reference repos + packaging), and `AGENTS.md` (deep architecture guide:
hooks registered, JS↔Python protocol, config keys, packaging).

Klaus is **embeddings-only**: its one AI capability is semantic search,
which defaults to the **Voyage** cloud embedding API (Ollama is an optional
local alternative, OpenAI a second cloud option). Autocomplete, ⌘K Ask, the
Klaus chat panel, the Settings dialog, and the Claude/Anthropic integration
were all deleted in 2026-08 — if you find docs, comments, or instincts that
assume any of those still exist, they're stale. See AGENTS.md's "What used
to be here" for the full list of what was removed.

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/Addons/klausmate/`,
  even though worktrees now contain a copy. Anki loads the addon through a
  symlink to the main checkout only, and the PostToolUse compile hook
  compiles that symlink target — so a worktree edit would report success
  without ever being compiled or loaded.
- Commits and diffs for addon work are now expected.

## The agent board

Multi-session work is coordinated through a kanban board:
`board/BOARD.md` is the source of truth, and **every state change
(claim/move/comment) goes through `python3 board/board.py`** — it
serializes writes behind a lockfile; hand-editing BOARD.md to move a card
will eventually lose a write (card *body* prose may be hand-edited by the
orchestrator/designer only). Claiming enforces file-disjointness against
cards already in Doing, and a card's `verify:` command must fail before
the work and pass after. Roles, columns, and gates: `context/ROLES.md`.
Dashboard: `python3 board/serve.py` → 127.0.0.1:8765 (preview config
"board-dashboard" in `.claude/launch.json`). Signed-off history is in
`board/ARCHIVE.md` — search it (K-0xx) before re-debugging anything.

## How Anki loads the addon

- Symlink: `~/Library/Application Support/Anki2/addons21/klausmate` →
  `/Users/pyamzi/Documents/Github/Addons/klausmate`. If the repo folder is ever
  renamed, this symlink breaks silently and Anki loads nothing.
- **Never create a second copy under `addons21/`** (e.g. a numbered AnkiWeb
  install). Two copies race on the same hooks and `editor._klausmate_*`
  attribute guards make the collision silent. A removed duplicate is backed up
  at `~/Library/Application Support/Anki2/klausmate-duplicate-1402639583.backup`.
- Anki must be **fully restarted** to pick up code changes.

## Anki runtime & testing

- Anki 26.8.1 lives at `/Applications/Anki.app`; its packages are Python
  3.13 **bytecode-only** in `Contents/Resources/app_packages` (no runnable
  python binary — `aqt`/`_aqt` there are `.pyc`, readable only by
  decompiling/`strings`). There is NO venv anywhere. System `python3` is
  3.9.6: it can `py_compile` every addon file (all use
  `from __future__ import annotations`) but **cannot import `aqt`**.
- So headless testing = **stub `aqt`/`anki` in `sys.modules` and test
  logic only, never Qt widgets**. The harness lives in `tests/` (see its
  README) with the bootstrap documented in the `klaus-test` skill — use
  that skill when adding or changing klausmate modules. Run everything:
  `for t in tests/test_*.py; do echo "— $t"; python3 "$t" || break; done`
- Verify syntax **through the symlink**:
  `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`
  (the PostToolUse hook `.claude/hooks/klausmate-compile.sh` does this
  automatically after every klausmate `*.py` edit, and fails loudly if the
  symlink is missing or dangling — that failure means Anki is not loading
  this code; fix the symlink, don't suppress the hook).
- Never point tests at the real `user_files` — use a scratch copy.
  `.claude/settings.json` denies Edit/Write under `user_files/` and
  Read of `meta.json` (API keys).
- Read-only SQL against the live collection works:
  `sqlite3 "file:...collection.anki2?immutable=1"`. FSRS is ON;
  `cards.data` JSON carries `{"s","d","dr","decay","lrt"}`.

## Module map

- `__init__.py`: bootstrap + gui_hooks; JS bridge
  (`pycmd("klausmate:<action>:<b64 json>")` routed in `on_js_message`, which
  splits `":", 2` — only `focus`/`crop`/`log`/`dbg` actions remain, the
  `complete`/`ask` actions are gone with autocomplete/Ask); `_PdfTabContainer`
  (tabbed PDF panel + window management: embed above/below/left/right of the
  editor pane via a QSplitter wrapper, or float as a parentless real window;
  native drag via `startSystemMove` with a watchdog + ghost fallback);
  image-crop plumbing; Tools menu (`install_menu`: ONE entry,
  "KlausMate Preferences…", inserted ahead of Anki's own items — the old
  Klaus submenu's actions live inside the Preferences dialog now).
- `heatmap.py` (aqt-free above its "aqt glue" divider): the **review
  heatmap** — a GitHub-style year grid under the deck list, past days
  coloured by reviews answered and the next four weeks ghosted by cards
  due, with streak / daily-average / share-of-days stats. Adapted from
  Glutanimate's Review Heatmap (`References/review-heatmap-main`,
  AGPLv3) for its DEFINITIONS only — no code vendored: that 1.0.1 tree
  is four years stale (`anki.lang._`, `addHook`), ships its web layer
  unbuilt (TypeScript + cal-heatmap + 150KB d3 that CSS grid replaces),
  and carries libaddon plus Section 7 terms. **The styling is all
  borrowed, never invented**: the panel joins `background.panel_css`'s
  frosted family by being named in that one selector (`table, .callout,
  .klaus-hm`), so it frosts/tints/rounds exactly like the deck table in
  every background mode; and every cell colour is the ACTIVE accent at
  four alphas from `theme.palette`, so it re-colours with every colour
  theme including a custom one, with zero per-theme code. Both palettes
  ship keyed on `:root.night-mode` (same reason as `toolbar_css`).
  **`ease > 0` is load-bearing, not hygiene**: revlog rows with ease 0
  are manual entries (set due date, forget, bulk FSRS reschedules) — on
  Pouya's collection 155,254 of 189,956 rows, four ~35k spikes on days
  he never studied; unfiltered they set the ramp and flatten every real
  day. Days are integer DAY NUMBERS throughout, bucketed by SQLite with
  `'localtime'` so a DST shift can't smear a day. Clicking a cell opens
  Browse — `prop:due=N` ahead, our own `klausday:<day>` token behind,
  resolved in `browser_will_search` because Anki has no operator for
  "reviewed on this exact day". Deck browser only (the overview would
  need deck-scoped queries). Config `heatmap_enabled` — written ONLY
  by the dashboard's Edit Widgets ⊖/＋ since 2026-08-30 (the
  Preferences switch was removed as redundant); `_bg_preview_cfg`
  still carries the key, read from STORED config live per tick — that
  dict REPLACES config for every `effective_cfg` reader.
- `dashboard.py` (aqt-free above its "aqt glue" divider) +
  `web/dashboard.js`: **Control-Center-style widget editing** on the
  deck browser. Python owns the registry (`WIDGETS`: decks mandatory,
  heatmap removable — future widget = one tuple), the config policy
  (`apply_action` is the ONLY gate between bridge payloads and config;
  JS is never trusted), the chrome stylesheet, and the transient
  `_EDIT` flag (edit mode survives stdHtml rebuilds; reset on profile
  switch). The JS owns the DOM: wraps the deck table (+ in theme mode
  the still-sibling `<br>`+`#studiedToday` trio) and `.klaus-hm` into
  `.klaus-widget` divs, applies `dashboard_order`, and runs the whole
  edit mode — right-click → "Edit Widgets…" (JS preventDefault beats
  AnkiWebView's menu; pdfjs precedent), iOS jiggle (disabled under
  Anki's `body.reduce-motion` class — Anki ships NO
  prefers-reduced-motion CSS), per-widget shields so deck clicks/drags
  are unreachable while jiggling, ⊖ badge, ＋ popover, Done/outside/
  Esc, and pointer-event drag-reorder (HTML5 DnD is dead on this
  screen: MainWebView.dragEnterEvent eats non-file drags). Wrapper
  sizing is `width:fit-content; max-width:100%` — BOTH measured
  necessary (block = full-width badge misplacement; bare fit-content
  can't go below the heatmap grid's min-content, 859px). Visibility
  stays on per-widget bools (`heatmap_enabled`); `dashboard_order` is
  order ONLY. `_bg_preview_cfg` carries it, and `_write_cfg` patches an
  armed preview so a dashboard edit survives the next preview tick.
  Bridge `klausmate:dash:<b64 json>`; only `add` refreshes (deferred,
  guarded on `mw.state`). Hook order: dashboard.setup() AFTER
  heatmap's, so its body script parses after panel_js's weld. DOM
  behaviour is tested by `tests/dashboard_js_dom_test.js` (node, run
  from test_dashboard.py, honest SKIP without node).
- `browse_toggles.py`: Browse toolbar toggles (◧ sidebar / ◨ editor column),
  split out of `__init__.py`.
- `browse_highlight.py` (aqt-free at module top): Browse search-term
  highlighting (K-113), adapted from Glutanimate's
  highlight-search-results (AGPLv3 — its header must stay intact;
  vendored source in `References/highlight-search-results-main`). Pure
  `SearchTokenizer`/`get_searchable_tokens` (ANKI2124 dialect) at top;
  highlighting is `webview.findText` per term on the Browse editor,
  re-run on `browser_did_change_row`, toggled per-browser from a
  checkable View-menu action seeded by config `browse_highlight_default`.
- `theme.py` (aqt-free at module top): central design tokens + shared QSS
  builders, adapted from SynapsePro (`scripts/SynapsePro-main/theme.py`) —
  the Apple system palette as semantic keys, LIGHT/DARK with identical key
  sets, `palette(night)`, `night_mode()` (lazy aqt, light fallback), and
  **accent colour themes (K-107/K-108)**: `COLOR_THEMES` carries
  SynapsePro's six presets plus community palettes (nord, solarized,
  catppuccin, gruvbox, everforest, dracula — via `_community_preset`,
  which derives hover/pressed from one canonical base and takes the
  palette's published bright tone) and `claude` (#D97757 terracotta),
  all as blue-family token overlays ONLY (backgrounds/text never fork
  per theme — pinned). A `custom` theme derives the whole family from
  ONE user colour (`custom_overrides`; config `color_theme_custom`).
  `set_active_theme(name)` + `set_custom_colour(hex)` (from config,
  applied on `profile_did_open` by `__init__._apply_color_theme`
  BEFORE any surface draws, colour before name) make every later
  `palette()` call carry them, so all builders — dialogs, Library,
  panels, toolbar, pdf.js css_vars — recolour with zero per-surface
  code. Disabled-state QSS must repeat any id selector it has to beat
  (`QPushButton#SecondaryButton:disabled` — an id outranks a
  pseudo-state, which is why disabled controls once looked live). Also
  per-surface builders (`dialog_qss`, `panel_header_qss`, `find_bar_qss`,
  `library_qss`, `thumb_strip_qss`, `drop_zone_qss`, `muted_label_qss`,
  `accent_rgba`). **UI files must not hardcode colours** — import theme and
  reference tokens; styles are computed at widget creation (a night-mode
  flip catches up on next open). Dialog buttons are blue-primary by
  default with `SecondaryButton`/`DangerButton` objectName opt-outs; the
  Library window inverts (grey default, `PrimaryButton` opt-in).
- `pdfjs_viewer.py` + `web/pdfjs_viewer.html` + `web/pdfjs/` (vendored
  pdf.js 3.11.174): the flicker-free webview renderer (K-095 umbrella),
  selected by config `pdf_renderer` (`"native"` default until the K-101
  cutover; parity cards K-097..K-100). `PdfSidebar` branches at
  construction; the PDF is fed as chunked base64 into window globals
  (SynapsePro's pattern), pages render lazily via IntersectionObserver
  over sized placeholders, the pdf.js text layer gives native selection,
  and theme tokens arrive as CSS vars (`theme.css_vars`). Parity shipped
  (K-097..K-099): highlights/notes/outside-text render from the SAME
  record schema (0-based page, top-left page-point rects; CSS px = pts ×
  scale), find bar (searches cached text of unrendered pages; rings the
  owning span), thumbnails, zoom (⌘+/−/0), go-to-page, custom context
  menu, marquee/region/page image copies. **The page owns rendering and
  gestures; Python owns the annotations JSON** — mutations arrive over
  the bridge (`hl-add`/`hl-remove`/`note-edit`), `PdfJsViewer` persists
  via `pdf_handler.save_annotations` + the same 500ms debounced bake,
  keeps K-081 tombstones, and pushes canonical records back via
  `klausSetAnnotations`. Pure helpers (`renderer_from_config`,
  `chunk_b64`, `build_page_html`, `parse_bridge`, `decode_b64_json`,
  `records_from_rect_map`) are aqt-free for `tests/test_pdfjs_viewer.py`.
  Remaining gaps live on the K-100 card. The annotations JSON + bake
  pipeline are renderer-independent — parity work must not fork them.
- `pdf_viewer.py`: `PdfViewer` (QPdfView + selection/marquee/highlight
  overlay, find bar, thumbnails, zoom/nav, per-gesture eventFilter) and
  `PdfSidebar` (one instance reused across tabs). No toolbar "Copy page"
  button — Cmd/Ctrl-double-click a page, or right-click "Copy slide as
  image", copies it as an image; right-click also offers "Copy page text".
- `pdf_handler.py`: storage + text extraction. `user_files/{contexts,pdfs,
  pdf_originals,annotations}`, state in `pdf_tabs.json` (open tabs, placement,
  thumbs, last_used — all writers MERGE via `_save_tabs_file`). Since K-070/
  K-073 the PDF *files* live in a user-chosen **library root** (config key
  `library_root`, picked at setup or in Preferences): `library_map.json`
  maps safe basename → path relative to that root, and **`pdf_path_for` is
  the single resolution choke point** (mapped location first, legacy
  `pdfs/<safe>.pdf` fallback; tests pass `root=` explicitly to stay
  aqt-free). No retrieval consumer remains here (autocomplete/Ask, the only
  callers of its old BM25 search, are gone) — `_chunk_text` now only feeds
  the semantic-curation pipeline (`curation.py`, `pdf_index.py`).
  `bake_annotations(dir, name)` writes highlights/notes into the stored
  PDF as REAL annotations
  (vendored pypdf): pristine original captured once in `pdf_originals/`,
  every bake regenerates from pristine + full json (never incremental; empty
  json = un-bake/restore), atomic `os.replace` (safe under the viewer's open
  QPdfDocument inode). Scheduled from `pdf_viewer._save_annotations` via a
  1200ms debounce → daemon thread.
- `top_bar.py`: the **Klaus top bar** — restyles Anki's main-window top
  toolbar IN PLACE (never rebuilds it): `webview_will_set_content` with
  an `aqt.toolbar.TopToolbar` context injects `theme.toolbar_css()`
  into the head (SynapsePro's mechanism). **`toolbar_css()` takes no
  `night` argument on purpose** — Anki's theme switch never re-runs
  that hook, it only toggles classes with JS
  (`documentElement.night-mode`, `body.night_mode`/`nightMode`), so a
  baked palette froze on the theme that was active at draw time; the
  sheet ships BOTH palettes keyed on those classes and the bar (logo
  included) follows live. The bar is **seamless with the OS title
  bar**: no bottom border at all, and its colour is the *live* window
  colour — `native_chrome_color()` reads `mw.palette()`'s Window role
  and pushes it as `--klaus-chrome` (baked into the first paint, and
  re-pushed from our own `theme_did_change` hook, one tick later so
  Qt's palette has updated). That matches system chrome on macOS and
  Windows without touching NSWindow/DWM; the palette `chrome` token is
  only the fallback. Also
  `top_toolbar_will_set_left_tray_content` prepends `logo_html()` — the
  hand-drawn star SVG (inline, `--klaus-accent` CSS var, click →
  Klaus Preferences via `klausmate:settings` on
  `webview_did_receive_js_message`; the same hook also routes the
  on-screen gradient editor's `klausmate:bggrad` drag-end messages
  into `background.grad_edit_event`). Because it only restyles, Anki's links, Klaus's Library link,
  and AnkiHub's toolbar items all keep working and inherit the look via
  the shared `.hitem` class. **Anki draws the toolbar in
  `finish_ui_setup()`, BEFORE any profile opens** — so the accent a
  profile saved reaches the bar only via `_on_profile_open_redraw`
  (profile_did_open, one-tick-deferred toolbar.draw); without it the
  star launched default-blue on every restart. `refresh()` is
  review-safe: in the review state it never calls `mw.reset()` (that
  rebuilds the study queues) — it evals `reviewer_style_push_js`
  (replace-not-stack on the one `#klaus-reviewer-bg` tag the
  will_set_content injection also writes) plus gradient-editor
  clean-then-replant instead. Pure builders are aqt-free for
  `tests/test_top_bar.py`. Night-mode catches up on the toolbar's own
  redraw.
- `background.py` (aqt-free): the custom app background for Anki's deck
  and overview screens + **`design_enabled(cfg)` — the KlausBook design
  gate** (config `klausbook_design`, default FALSE: Klaus ships as
  tools in a stock Anki; the full look is the opt-in). The gate is
  enforced at the PAINTERS, never inside `resolve()` — Preferences
  seeds its widgets through `resolve(stored)` and writes the spec back
  on Save, so a resolve-level gate would wipe a stored image
  background. Gated: `top_bar._background_css` (one early return kills
  main/panel css + the panel_js weld), the toolbar/bottombar restyle,
  the chrome push, and the whole dashboard injection (which also resets
  `_EDIT` so toggling off mid-jiggle can't strand edit mode). NOT
  gated: the star (strokes `var(--klaus-accent, currentColor)` so it
  survives on the stock bar), the heatmap, every functional injection,
  and Klaus's own windows. In native mode the deck screen draws NO
  Klaus widgets: the heatmap's two injections are gated too (at the
  injections, never inside `enabled()` — the same round-trip rule as
  `resolve()` above: a reader whose value any UI seeds from and writes
  back must never be gated, or it persists a `heatmap_enabled` False
  the user never chose). The star is
  the one survivor, and it carries its own geometry inline (`logo_html`)
  so the gate cannot move it. Corrupt values read as OFF — opposite of
  heatmap's rule — so bad config can't surprise-restyle the app.
  `resolve(cfg)` validates the `background_*` keys into a spec —
  mode/color/image/fit/blur plus (2026-08-30) `wash` and the gradient
  quartet `color2`/`grad_x`/`grad_y`/`grad_size` plus `gradients` —
  a list of up to MAX_SPHERES {color,x,y,size} SPHERE dicts, each a
  radial blob fading its own colour to alpha-0 (`{color}00`, same-hue
  transparency) over the DEFAULT WHITE ground as the one backdrop
  (background-color under the background-image stack, which is what
  lets N spheres compose; `color2` is always DEFAULT_COLOR — Pouya:
  the edge "shouldn't be an option at all", so stored color2 values
  are ignored). Colour mode IS this stack — flat colour removed
  2026-08-30; a missing list is built from the legacy single keys. `main_css` paints
  Anki's deck and overview screens — panel_css in
  EVERY mode (panels follow the DESIGN; only the wallpaper follows the
  mode, so theme mode = Klaus panels on Anki's own ground) (NOT the
  congrats screen — it is sveltekit-loaded and never fires
  `webview_will_set_content`; a dead import claiming otherwise was
  removed 2026-08-27). Since the wash, image mode paints the picture
  on `<html>` ALONE with body forced transparent: `_wash_css`'s veil
  (`body::before`, z-index -1, white by day / near-black at night,
  backdrop-blurring the picture) sits exactly between wallpaper and
  content — with body still painting the image it would be buried
  under a second copy. The **on-screen gradient editor** also lives
  here: `set_grad_edit(active, sink)` is armed by the OPEN (non-modal)
  Preferences dialog, `gradient_edit_eval_js`/`gradient_edit_js` grow
  a draggable centre dot + size ring on each gradient screen (JS
  repaints the page inline per pointermove; drag-end lands as a
  `klausmate:bggrad` pycmd carrying an OP — geom / pick / add /
  remove — clamped in `grad_edit_event`, JS never trusted, and flows
  through the sink into the dialog's pending spec: geom stays QUIET
  (never refresh mid-drag), structural ops replant the editor, pick
  opens the colour dialog DEFERRED, the last sphere can never be
  removed, adds cap at MAX_SPHERES). Each sphere's dot is painted in
  its own colour — the dot IS its colour chip. **The top and bottom toolbars are independent of
  this file** (`bar_css`/`_bottom_bar_css` — a manual painted copy of
  the background, blurred, since the toolbar's own webview can't
  `backdrop-filter` through to the window behind it — were deleted
  2026-08-30, Pouya's call): the bars always show flat
  `theme.toolbar_css`/`bottombar_css` chrome, whatever background mode
  the deck screen is painted with. The deck PANELS still frost over an
  image background, but for real — `panel_css`'s `backdrop-filter`,
  since a deck table and the page background it sits on ARE the same
  document. Images are copied into `user_files/backgrounds/`
  (`store_image`, name-versioned) and served by the widened
  `setWebExports` pattern; `safe_image_name` keeps that URL inside the
  folder and to allow-listed extensions. **`resolve(cfg, prefix=...)`**
  reads a SECOND, independent spec off `reviewer_background_*` keys —
  the study screen's own wallpaper, Pouya wanted it decoupled from the
  deck screen's. `reviewer_css(spec, url)` paints `html, body` on the
  reviewer's main webview (`context=self` in `Reviewer._initWeb`,
  verified against Anki's source — NOT `ReviewerBottomBar`, which
  window_chrome owns) with no `panel_css` and no panel-frost blur: a
  card is the user's own notetype, never Klaus's to restyle, so there
  are no panels to frost — the image WASH is a different layer and
  does apply, off the screen's own `reviewer_background_wash` key. Wired from
  `top_bar._on_main_webview_content`'s second branch, gated by its own
  `_reviewer_background_css()` (same shape as `_background_css`, just
  a different prefix and builder).
- `window_chrome.py` (aqt-free above its "aqt glue" divider): the
  **KlausBook layer on Anki's OTHER windows** — Add Cards, Browse,
  Stats, and the reviewer's bottom bar. Every style string is a
  theme.py builder (`browse_qss`, `sidebar_tree_qss`,
  `utility_window_qss`, `editor_tags_qss`, `reviewer_bar_css`,
  `editor_css`, `stats_css` — all under test_theme's design-scale
  audit); this module is glue only, gated on `klausbook_design` at
  every painter. **Tracked refresh, not style-at-open**: aqt.dialogs
  caches Browser/AddCards all session, so widgets register in a
  WeakKeyDictionary at their init hooks UNGATED, and `refresh()`
  (called from the Preferences live-preview seam) applies or restores
  against the gate read at walk time — un-apply restores each
  widget's STASHED original sheet, because the sidebar tree and tag
  bar carry Anki's own widget-level QSS that a bare "" would strip.
  The sidebar tree re-applies its stock sheet on every theme flip
  from a handler registered at Browser construction, so our
  theme_did_change work runs ONE DEFERRED TICK after the whole chain
  (top_bar's pattern). Browse is HARMONIZED only (tokens; layout and
  density stay; flag/marked row tints and the Cards/Notes switch are
  delegate/custom-painted semantics, deliberately untouched). The
  reviewer sheet reuses the shared `_chip_*_rules()` blocks (three
  bars agree by construction; top_bar.py never names that surface —
  its test pin stands) and contains NO rule for
  `.stattxt`/`.new-count`/`.learn-count`/`.review-count`: scheduling
  semantics survive by omission, pinned by absence. Stats (sveltekit
  "graphs" — stdHtml hooks never fire) is reached via
  `webview_did_inject_style_into_page` (hasattr-guarded; kind check +
  URL fallback) with an eval-injected replace-not-stack `<style>`
  overriding ONLY `--canvas/--canvas-elevated/--border/--border-subtle`.
  The editor is dual-path: legacy stdHtml gets `editor_css` via
  web_content.head; the flag-gated Svelte editor degrades to stock.
- `pdf_drive.py`: the **Library** window (renamed from "PDF drive" in the
  UI; file/class names still say drive) — folder tree (`drive_store.py`,
  `user_files/drive.json`) next to a standalone `PdfSidebar`. Since K-073
  the tree is **mirrored two-way with real folders under the library
  root** (single-copy invariant: one file per PDF, living in the root;
  `rescan_library_root` + a debounced filesystem watcher pick up outside
  edits) — `drive_store.py` itself stays a pure aqt-free presentation
  join; the disk sync lives here and in `pdf_handler`. Top-toolbar link
  labeled "Library" (`gui_hooks.top_toolbar_did_init_links`). Right-click
  per row: open, rename, move to folder, re-embed, adjust match
  sensitivity, show matches in Browse, curate deck from this PDF, delete.
- `tag_sync.py`: per-PDF collection tags. THE INVARIANT: every indexed PDF
  owns exactly one tag `!Library::<folder path, / → ::>::<leaf>` (leaf =
  display name minus extension, tag-sanitized), whose members are exactly
  the notes at/above that PDF's sensitivity threshold. Forward direction
  (index/re-index creates + renames tags, K-053) and reverse (a rename in
  Anki's tag sidebar renames the PDF, K-054 — INFERENCE from a
  before/after tag diff on profile open, never a real event). Reserved
  leaves `Curating`/`Curated`/`Matching` are never touched.
- `retention.py`: per-PDF retention/study-priority score shown in the
  Library — embed the PDF's chunks (`pdf_index.py`) → score every indexed
  note against them (max cosine, cached in `matches.json`) → pull FSRS
  retrievability for matched cards → aggregate. The old
  `!Library::Matching` preview tag was retired in K-055 — "Show matches
  in Browse" now hops to the per-PDF `tag_sync` tag.
- `projection.py` (aqt-free, pure stdlib): top-2 PCA by power iteration +
  deflation over one packed `array('d')` buffer (`math.sumprod` on
  memoryview slices, strided slices for the transpose — never the d×d
  covariance matrix). Numeric foundation for the embedding map (Phase D).
- `pdf_graph.py` (aqt-free at module top): assembles the embedding-map
  graph dict — PDF nodes at their matched notes' 2D centroid, edges to
  every note at/above threshold. `retention` (which imports aqt) is
  imported lazily inside `build_graph_data`. No window/canvas yet.
- `pdf_index.py` (aqt-free): persistent embedding index over one PDF's text
  chunks, `card_index.py`'s sibling for the PDF side.
- `md3_switch.py`: `Md3Switch(QCheckBox)` — the MD3 track-and-thumb
  switch used for every settings-row on/off (K-material3 audit;
  replaced bare checkboxes in `manage_models.py`). Pure geometry/colour
  math (`thumb_diameter`, `thumb_center_x`, `_lerp_hex`, `track_color`,
  `thumb_color`) is aqt-free at module top; the widget paints itself
  entirely (no QSS indicator reaches it), animates progress 0→1 over
  200ms, and draws its own focus ring since a self-painted widget
  bypasses `QPushButton:focus`. Checked-state bookkeeping is 100%
  inherited from `QCheckBox` — every call site keeps working unchanged.
- `crop_dialog.py`: image-crop dialog (crop saved as NEW media file).
- `web/copilot.js`: injected into editor webviews; shadow-DOM-aware
  (`composedPath`). Ghost text and Ask are gone — this file now only tracks
  field focus (for PDF page-insert targeting) and the image-crop dblclick
  trigger.
- **Semantic curation stack** (Curate Deck + the Library's retention score;
  this is the only AI-powered feature left):
  - `embeddings.py` (aqt-free): provider abstraction — Voyage
    (default, `voyage-3-lite`), with Ollama `/api/embed` (`nomic-embed-text`)
    and OpenAI (`text-embedding-3-small`) as alternatives. `OPENAI_API_BASE`/
    `VOYAGE_API_BASE` module globals exist for test monkeypatching. Vectors
    are **unit-normalized at write time**.
  - `card_index.py` (aqt-free): `user_files/card_index/` = packed
    `array('f')` vectors + JSON manifest. **Text hash is the change
    detector; `note.mod` only a pre-filter** — the Browse-preview tag bumps
    mod without changing text. A row's (mod, hash) advances only together
    with its vector → cancelled indexing resumes for free. Manifest is
    written AFTER vectors (size mismatch on load ⇒ rebuild). `top_k` =
    `math.sumprod` over memoryview rows (C-speed; **no numpy in Anki's
    bundled Python**) — 30k×768 ranks in ~0.25 s.
  - `curation.py` (aqt glue): two-phase `ensure_index` (snapshot with col
    via `select id, mod, flds from notes` + `flds.split("\x1f")`; embed
    without col, partial save every ~1k vectors), `run_curation`, preview
    via temp tag `!Library::Curating` (+ `Browser.search_for`; `nid:` lists
    break at thousands of ids), undoable deck copy (`add_custom_undo_entry`
    → `col.add_notes` → `merge_undo_entries`) tagged `!Library::Curated`.
    Curation is always PDF-driven now — `run_curation`'s free-text `prompt`
    param has no caller since the chat panel that used to fill it in was
    deleted.
  - `deck_curate.py`: "Curate Deck" button + PDF drop/arm on the deck list
    and deck overview screens; calls into `curation.py` via
    `run_curation_flow(pdf_name, deck_scope)`.
  - `tag_migrate.py`: one-time `klaus::*` → `!Library::*` collection tag
    rename on `profile_did_open`, guarded idempotent (only proposes a rename
    when the old tag still exists), returns `col.merge_undo_entries(pos)`
    (a plain list return here crashed every profile open — `on_op_finished`
    reads `.changes` off a `CollectionOp`'s result).
  - `manage_models.py`: the "Manage models" dialog (`manage_models_dialog`,
    also first-run setup; Tools menu label "KlausMate Preferences…", and
    the top bar's star opens it too; Appearance also carries Anki's
    own Follow-System/Light/Dark switch, applied on Save through
    `mw.set_theme` — the one row writing an Anki preference).
    **NON-MODAL since 2026-08-30**
    (`dlg.show()`, NEVER exec() — the 2026-08-26 segfault was
    app-modal exec's nested loop): a live control panel used beside
    the main window while appearance edits preview on it. `_OPEN_DLG`
    keeps it a singleton (a second star click fronts it);
    `profile_will_close` rejects it before the collection goes away. **SynapsePro settings shell
    (K-106 — replaced the K-105 card grid; built from a screenshot of
    SynapsePro 1.5.x, the vendored source only has their older grid)**:
    a fixed `SettingsSidebar` (star-logo pixmap drawn from
    `top_bar.star_points()`, app name + manifest `human_version`, `SettingsNav` list (ONE QListWidget — never
    per-page buttons; three pill-mush rounds proved per-button polish
    timing unfixable) with a row per page) beside a QStackedWidget of pages.
    Each page = `PageTitle`/`PageSubtitle` over ONE rounded `CardFrame`
    group; every simple setting is a `_row()` — bold `SettingName` +
    muted `SettingDesc` left, control right, `RowSeparator` hairlines
    between. Sidebar display order comes from `_finish_nav(...)`,
    decoupled from widget build order; the sidebar header is the
    star logo beside the Garamond wordmark, over a search field that filters
    setting rows across pages (`_apply_search`; rows carry
    `klaus_search` haystacks, structural hiding via `klaus_hidden` —
    how the API-key row hides whole for Ollama — always beats a search
    hit); Cancel/Save sit under a full-width `ButtonBarLine` hairline
    outside the pages. Appearance also hosts the accent swatch grid —
    bare colour squares 7 per row, names in tooltips, last square =
    custom colour opening QColorDialog (cancelling still selects
    custom with its held colour) — rendered from `theme.COLOR_THEMES`,
    saved as `color_theme`/`color_theme_custom`, applied live in
    `save_all` (custom colour before theme name, both before
    `top_bar.refresh()`; the sheet swap wipes the swatches' inline QSS
    so `sync_accent_swatches()` + a logo repaint follow). The
    background groups (deck + study, one each): ONE mode combo, with
    PROGRESSIVE DISCLOSURE — every other row hides outright unless
    its mode is selected (klaus_hidden + an _apply_search re-walk,
    the API-key row's pattern; design off hides the whole block).
    Image mode shows Choose Image… with a rounded 2× thumbnail
    caption (`_image_thumb`, rendered from the STORED copy; its
    Remove link clears the picture), Fit, Panel Frost (deck only)
    and Image Wash sliders; colour mode shows only the sphere
    caption — no colour buttons, the on-screen dots are the chips. Gradient geometry
    has NO sliders — centre/size are dragged ON the screen itself
    (`background.set_grad_edit` armed while the dialog is open; the
    sink updates the pending spec and arms the preview QUIETLY, never
    refreshing mid-drag; disarm is connected BEFORE the preview revert
    so exactly one refresh clears the handles). No Review-heatmap row
    — Edit Widgets on the deck screen owns `heatmap_enabled`, and
    `_bg_preview_cfg` carries that key from STORED config live per
    tick. Image-only rows disable WHOLE (`bg_fit_row`/`bg_blur_row`/
    `bg_wash_row`) so labels dim with their controls.
    Pages: **Semantic Search** (embedding
    provider/key/model — `_resolve_ollama_model()` guards against silently
    orphaning an existing index when the ollama model config is empty),
    **Local model library (Ollama)** (pull/delete embedding models only —
    `_EMBED_PRESETS`: nomic-embed-text, snowflake-arctic-embed,
    mxbai-embed-large, embeddinggemma), **General**/**Appearance** (`image_crop_enabled`,
    `runtime_auto_setup`, and `pdf_renderer` toggles — no other UI
    touches these keys; the pdf.js checkbox maps "native"/"pdfjs" and
    needs a restart). **Preferences are deferred-save**: widgets only
    call `mark_dirty()`; `save_all()` behind the **Save** button is the
    single writer of preference keys, closing dirty prompts to discard,
    and `sync_embed_widgets`/`sync_threshold_widget` bail while dirty so
    a background `refresh()` can't clobber unsaved edits. Adding a
    preference = widget + `mark_dirty` signal + a line in the matching
    `save_*`; a forgotten signal now costs a missing dirty mark, not a
    silently unsaved setting (which is exactly how `pdf_renderer`
    shipped broken). `sync_embed_widgets(provider_override=...)` is how
    a provider switch reloads the model/key fields without writing, and
    `ui_state["shown_provider"]` — not the stored provider — is what
    `save_embed` compares against.
  - `setup_flow.py`: first-run "Welcome to Klaus" dialog + per-profile-open
    readiness checks, gated on `embeddings.provider_name(cfg)` — a
    Voyage/OpenAI profile never sees Ollama-flavored copy or probes.
  - `ollama_client.py`: stdlib HTTP client — `/api/embed`, pull, delete.
    **No text-generation method** (stripped when autocomplete/Ask were
    removed).
  - `ollama_runtime.py`/`ollama_setup.py`: managed Ollama provisioning.
    **Never kill a user-owned Ollama** — only servers Klaus spawned
    (pidfile + process-identity verify). No UI control removes a
    Klaus-managed install; reclaiming that disk space is a manual delete of
    `user_files/runtime/` (after switching off "Manage Ollama automatically"
    in Manage models → General so it doesn't just come back).
- Deleted (2026-08, do not resurrect the language): `claude_api.py`,
  `anki_tools.py`, `settings_ui.py`, `chat_dock.py` (the "Klaus panel"),
  `web/search.html|css|js`; also `single_window.py` (2026-08-25 — the
  panes-in-one-window mode from K-059..K-062 was removed as too buggy:
  dark webview panes survived five rework rounds, K-090..K-094. Anki is
  stock multi-window again; `_migrate_config` scrubs the
  `single_window_mode` key). **Embedding Anki's windows stays deleted.**
  `workspace.py` (K-102, the sidebar-shell follow-up) lasted one day —
  deleted 2026-08-25 as the wrong shape; the unified-UI ask is served
  by `top_bar.py`'s toolbar restyle instead (`_migrate_config` scrubs
  `workspace_enabled`). Config lives in `klausmate/config.json` +
  Anki's addon config (`meta.json`) + `config.md`. `_migrate_config()`
  (profile_did_open) cleans up legacy `chat_*`/`claude_*` keys left from the
  deleted Claude-Ask feature; keep it until users have upgraded past it.

## Hard-won gotchas (each cost real debugging — don't relearn them)

- **A styled QTreeView selection is TWO paint regions** — the item AND
  the branch (disclosure-arrow) cell, plus the style's own selection
  underlay. Style only `::item:selected` and Qt paints the rest in
  palette-highlight dark blue: fragments at the row edge, and corner
  peek-through if the item is rounded. Full fix: `::branch:{hover,
  selected}` rules + `selection-background-color: transparent` + keep
  square geometry (see `theme.sidebar_tree_qss`).
- **pdfium hit tolerance**: `QPdfDocument.getSelection()` silently returns an
  INVALID selection if an endpoint is >~7pt from a glyph, or if both endpoints
  hit the same character. Never anchor at page corners/edges — use
  `getAllText` / `getSelectionAtIndex` (index space) or the probe helpers
  (`_probe_selection_at`, `_snap_to_char`).
- **Host-window shortcut ambiguity**: widget-scoped QShortcuts that collide
  with Browse/AddCards QActions (⌘F, ⌘G, ⌘⌥G, ⇧⌘G, ⇧⌘H) become *dead keys*.
  The viewer claims them via `QEvent.ShortcutOverride` + KeyPress handling.
- **Reparenting mid-mouse-gesture kills Cocoa tracking** — never
  `setParent` into a new native window while a button is down. Tear-off =
  float on threshold + `startSystemMove()` (which *lies* — returns True even
  when the drag dies; a 300ms/40px watchdog detects that and falls back).
- **`QSplitter.setOrientation` transposes its sizePolicy** — re-assert the
  wrapped pane's policy after every orientation change or the host layout's
  stretch hints are lost (blank-space bug in the Add window).
- **One `QPdfDocument` is reused across tabs** — cache by
  `_doc_generation` (bumped in `set_document`), never `id(doc)`.
- **Anki stores DECODED filenames in note fields** (`reverse_url_quoting` on
  save) and entity-escapes attribute values — `_replace_img_src` matches raw,
  percent-decoded, and html-unescaped forms.
- Safe note mutation from Python:
  `editor.call_after_note_saved(cb, keepFocus=True)` → mutate
  `note.fields` → `_save_current_note()` (non-addMode) →
  `loadNoteKeepingFocus()`.
- `gui_hooks.editor_did_focus_field` signature is `(note, field_idx)` — it
  does NOT provide the editor; focus tracking rides the JS bridge instead.
- Browse `gridLayout` cell (0,0) is occupied at runtime by Anki's Cards/Notes
  switch (added in `Browser.setup_table`), not empty as the form suggests.
- Generated `_qt6.py` forms show the `setupUi` state only — Anki mutates
  layouts afterwards; grep `aqt/` before trusting a form.
- **pdfium renders annotations only WITH `RenderFlag.Annotations`** — the
  viewer and image copies render without it, so baked-in highlights never
  double-draw under the screen overlay. The coordinate flip is
  `y_pdf = page_mediabox_height − (y_qt + h)` (verified pixel-exact).
- **Selection-path perf caches** (pdf_viewer): `_page_geoms_cache` keyed
  (doc generation, viewport width, zoom mode, zoom factor, vsb.max);
  `_alltext_bounds_cache` keyed (generation, page); `_probe_selection_at`
  has a `fast=True` mode for per-mouse-move callers. Rewiring selection
  code must respect these or drag/scroll jank returns.

## Conventions

- Defensive `try/except` around every Qt call; guarded imports with `None`
  fallbacks (`PDF_VIEWER_AVAILABLE` pattern); log with
  `print("[klausmate] ...")`; tooltips only for capture-style actions
  (selection/copy is silent, Preview-style).
- pypdf is vendored in `klausmate/vendor/` (6.11.0, has
  `pypdf.annotations`); no other third-party deps, no native code.
- Ollama embedding-model presets live in `_EMBED_PRESETS`
  (`manage_models.py`) — there is no text-generation model list anymore
  (autocomplete/Ask are gone), and no first-run auto-pull; the user picks a
  provider/model explicitly.
