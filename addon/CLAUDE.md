# CLAUDE.md — Addons repo / Klaus (klausmate)

The real project here is **`klausmate/`** — "Klaus", an Anki addon for a
lecture-PDF library with per-PDF retention scoring, semantic card↔PDF
matching (indexing a PDF tags every card it covers), a native
PDF viewer with highlights/sticky notes, and image cropping. Around it:
`tests/` (headless logic tests), `board/` + `context/` (the multi-agent
kanban board — see below), `References/` and `scripts/` (vendored
reference repos + packaging), and `AGENTS.md` (deep architecture guide:
hooks registered, JS↔Python protocol, config keys, packaging).

Klaus was **embeddings-only** from 2026-08: its one AI capability was
semantic search, which defaults to the **Voyage** cloud embedding API
(Ollama is an optional local alternative, OpenAI a second cloud option).
Autocomplete, ⌘K Ask, the Klaus chat panel, the Settings dialog, and the
Claude/Anthropic integration were all deleted then — if you find docs,
comments, or instincts that assume THOSE surfaces still exist, they're
stale. See AGENTS.md's "What used to be here".

**That is being deliberately reversed as of 2026-09-01** (Pouya's call): two
assistants are under construction — one to query notes and the lecture-PDF
index, one to draft cards from lecture material — with a free
bring-your-own-key path and a premium hosted one. Four aqt-light layers have
landed and are NOT yet wired to any surface: `card_forge.py` (drafting +
review), `llm_client.py` (streaming transport, descended from the deleted
`claude_api.py`), `entitlement.py` (tier, advisory only), and `anki_tools.py`
(the collection tool layer, restored from `30847b9^`). **The UI surface is
deliberately undecided** — do not invent one. Do not delete these modules on
the strength of the 2026-08 paragraph above.

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`,
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
Dashboard: `python3 board/serve.py --port 8766` → 127.0.0.1:8766
(preview config "board-dashboard" in `.claude/launch.json`). **Not
8765** — an unrelated long-running `stream_server.py` owns that port on
this machine, so the board silently failed to bind there and the
preview served that server's "you need a WebSocket client" page
instead. Signed-off history is in
`board/ARCHIVE.md` — search it (K-0xx) before re-debugging anything.

## How Anki loads the addon

- Symlink: `~/Library/Application Support/Anki2/addons21/klausmate` →
  `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate`. If the repo
  folder is ever renamed, this symlink breaks silently and Anki loads nothing
  — and this file goes stale with it: the repo WAS `Addons/` until the
  2026-08 rename, and both paths here went on naming a dead directory until
  2026-08-31. `ls -l` the link before trusting a path written here.
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
  Browse with NATIVE searches only (`day_query`, K-131): `prop:due=N`
  ahead, `rated:n -rated:n-1` behind — "answered within n days" minus
  the shorter window is exactly one day, and `rated:` counts `ease > 0`
  rows, the same filter the grid uses, so Browse agrees with the
  tooltip. It also caps at 365 days, which is WHY `RANGE_CHOICES` stops
  at a year. The old private `klausday:` token + `browser_will_search`
  resolver are deleted: they were opaque AND inert — the resolver
  assigned `search_context.card_ids`, and `SearchContext` has no such
  field (it is `ids`), so Anki parsed the token as a field search and
  matched nothing. Its stated justification ("rated: is capped, so it
  cannot address the far end of a year") was wrong on both counts. Deck browser only (the overview would
  need deck-scoped queries). Config `heatmap_enabled` — written ONLY
  by the dashboard's Edit Widgets ⊖/＋ since 2026-08-30 (the
  Preferences switch was removed as redundant); `_bg_preview_cfg`
  still carries the key, read from STORED config live per tick — that
  dict REPLACES config for every `effective_cfg` reader.
  **The panel's own corner menu (K-121)** owns two DISPLAY keys beside
  it: `heatmap_history_days` (91/182/365, `history_window`) and
  `heatmap_forecast` (`forecast_window`) — both validated in Python
  against `RANGE_CHOICES`, never trusted from the page, both carried
  through `_bg_preview_cfg` for the same replace-not-merge reason, and
  both written through `dashboard.write_cfg` so the patch-the-armed-
  preview rule has ONE implementation. The menu is a bare `<details>`:
  no script of ours in Anki's deck-browser document, and the redraw
  after a choice closes it. Its surface is `--klaus-hm-menu` from our
  own palette, not Anki's `--canvas-overlay` — a popover that lands
  white at night is a flashbang, and a missing token fails to the
  fallback silently. Also K-121, all Pouya's calls: no heading (the
  grid says what it is), stats centred (the gear is absolute in the
  corner so it never enters that row's flow, and the row is padded
  equally on both sides to clear it), the left rail names EVERY row as
  initials (`_WEEKDAY_INITIALS`, derived from `_WEEKDAYS` so the rail
  and the tooltips cannot name different days), and a month's first
  column opens a `MONTH_GAP`. Cells and month labels are FLEX rows of
  per-week boxes now, not one auto-column grid — that is what lets a
  single `.klaus-hm-col.ms, .klaus-hm-m.ms` rule move the gap and the
  label that names it together, off one `starts` list.
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
  guarded on `mw.state`). `write_cfg` is PUBLIC (K-121) because it is
  the package's one implementation of "patch the armed appearance
  preview too" — heatmap's corner menu writes through it rather than
  growing a second copy. Hook order: dashboard.setup() AFTER
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
  and theme tokens arrive as CSS vars (`theme.css_vars`) — which must
  emit EVERY var the page hands to `var()`, since an undefined one
  computes that declaration to nothing rather than failing loudly
  (`--hover-subtle` shipped missing through K-116 and killed the
  findbar/annobar/menu/thumbnail hovers; it is now the palette's
  `hover_subtle`, the same fill the Qt-side builders use, and
  test_theme pins the whole set). The page's in-CSS fallbacks are
  safety nets ordered ahead of `__THEME_VARS__` so theme always wins —
  never a second source of truth. Parity shipped
  (K-097..K-099): highlights/notes/outside-text render from the SAME
  record schema (0-based page, top-left page-point rects; CSS px = pts ×
  scale), find bar (searches cached text of unrendered pages; rings the
  owning span), thumbnails, zoom (⌘+/−/0), go-to-page, custom context
  menu, marquee/region/page image copies. Since K-116 every zoom path
  (trackpad pinch = Chromium ctrl-wheel, ⌘ keys, menu, annobar)
  funnels through ONE session: instant compositor-transform preview
  anchored at the cursor (pinch) or viewport centre (steps), then a
  160ms settle that CSS-stretches existing canvases into the new
  layout and swaps crisp re-renders in place, visible pages first —
  zoom never blanks a page; the document-wide non-passive
  preventDefault on ctrl-wheel is what stops QtWebEngine frame-zoom
  fighting the pinned zoomFactor. A floating `#annobar` pill (findbar
  family) carries Highlight, Add Text, an ink-swatch row
  (`theme.HIGHLIGHT_INKS` → `--ink-*` CSS vars — deliberately outside
  LIGHT/DARK and COLOR_THEMES, because the value BAKES INTO THE PDF:
  ink on the page, not chrome), and −/%/+/fit. **Both tools are
  STICKY** (K-159, Pouya: "I want to stay in that mode") — a mark or a
  placed box does not disarm; only the toolbar button (`setTool`
  toggles) and Escape do, and with a text box open Escape is a
  two-step, since the box commits on the first and stops propagation.
  K-149 had made them one-shot and that half was never load-bearing:
  what makes sticky safe is `merge_highlight_records` at MINT time —
  same-ink rects an existing record already covers are dropped, the
  rest union into EVERY same-ink record they touch (all collapsing
  into one; folding into just the FIRST left a bridging drag
  overlapping its right neighbour at two 43% layers, the exact
  double-highlight look, K-159), a different ink CUTS rather than
  composites, and a mint that changes nothing never reaches the JSON.
  Text is edited ON the page since K-150 — a `contenteditable` box
  riding the same page transform, committed on blur/Escape, NOT a
  dialog; the open box swallows CLICK as well as mousedown, or a
  sticky tool reads a caret click inside it as "place another box
  here". `text-add` joins `hl-add`/`hl-remove`/`note-edit` on the
  bridge — Python clamps `{page,x,y}` (`clamp_text_add`, 14,400pt spec
  cap) and mints the K-077 `kind:"text"` record (`make_text_record`,
  explicit #000000/12pt — the validator would backfill highlight
  YELLOW). A window-modal `QInputDialog.open()` (K-114: never exec)
  remains for the note prompt on a highlight and for go-to-page.
  `#pages` is `width:max-content; min-width:100%` so beyond-fit zoom
  stays scrollable (the old fixed-width flex centred overflow off the
  left edge, unreachable). **The page owns rendering and
  gestures; Python owns the annotations JSON** — mutations arrive over
  the bridge (`hl-add`/`hl-remove`/`note-edit`), `PdfJsViewer` persists
  via `pdf_handler.save_annotations` + the same 500ms debounced bake,
  keeps K-081 tombstones, and pushes canonical records back via
  `klausSetAnnotations`. Pure helpers (`renderer_from_config`,
  `chunk_b64`, `build_page_html`, `parse_bridge`, `decode_b64_json`,
  `records_from_rect_map`) are aqt-free for `tests/test_pdfjs_viewer.py`.
  Parity completed by K-100:
  Cmd/Ctrl-double-click copies the slide (through the shared
  copyPageImage bridge — the native "insert into field" surface IS the
  clipboard), the marquee persists across zoom/re-render with native
  press semantics + drag-out (PNG dragstart; the drop-into-field leg
  awaits live-Anki verification on the K-101 soak — re-copy+paste is
  the working fallback), and find highlights the exact substring via
  the CSS Custom Highlight API with the whole-span ring as guarded
  fallback. Cutover gate: K-101 (needs-human). The annotations JSON + bake
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
  transparency) over the THEME-AWARE ground as the one backdrop —
  DEFAULT_COLOR white by day, NIGHT_COLOR = the bars' DARK["chrome"]
  token by reference under `:root.night-mode` (one surface with the
  bars; both palettes in one sheet, house rule; a baked white ground
  was a night floodlight) — painted on `<html>` ALONE with body
  transparent (html+body double-painted every translucent layer and
  drew a seam at the body's bottom edge) via background-color under
  the background-image stack, which is what lets N spheres compose. `color2` is never an
  option (stored values ignored), a sphere still wearing the default
  white is UNSET and paints nothing (handles stay; the editor's
  inline drag-paint mirrors the skip and never touches
  background-color, or a night drag would floodlight the session).
  Colour mode IS this stack — flat colour removed 2026-08-30; a
  missing list is built from the legacy single keys. `main_css` paints
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
  does apply, off the screen's own `reviewer_background_wash` key.
  ONE narrow exception (`_reviewer_body_reset`, 2026-08-31): the
  reviewer's `<body>` IS the card (`class="card nightMode"`), and
  shared notetypes paint it opaque with !important — AnKing's
  `.nightMode.card { background-color: #272828 !important }`,
  (0,2,0), outranked a plain `body{...!important}` and hid the
  wallpaper behind a hard edge at the card's bottom. The reset is a
  specificity ladder (`html body.card.card.nightMode`, (0,3,2)),
  BACKGROUND ONLY, and ships only when a study wallpaper is actually
  configured — theme mode emits nothing, so a default profile's
  cards stay untouched. Wired from
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
- `pdf_drive.py`: the **Library** (renamed from "PDF drive" in the UI;
  file/class names still say drive) — folder tree (`drive_store.py`,
  `user_files/drive.json`) next to a standalone `PdfSidebar`. **It has
  TWO shapes since 2026-09-01**: the toolbar link's `open_library` first
  tries `library_tab.mount()`, which builds ONE `DriveWindow(embedded=True)`
  as a screen inside `mw.mainLayout` and keeps it for the session (unmount
  only HIDES it — hidden is its resting state, not "closed"); the
  standalone window is the fallback when the mount fails. The two live in
  DISJOINT rosters: `_instance` is written only by `_create()` (the window
  path, embedded=False), `_embedded_windows` is a WeakSet joined only by an
  embedded `__init__` (K-173). Any "every open Library" consumer must walk
  BOTH — `refresh_open_library` (settings save) and `_on_fs_tick` (disk
  watcher) are the two that need it, and a consumer that reads only
  `_instance` silently misses the screen the user is actually looking at.
  Since K-073
  the tree is **mirrored two-way with real folders under the library
  root** (single-copy invariant: one file per PDF, living in the root;
  `rescan_library_root` + a debounced filesystem watcher pick up outside
  edits) — `drive_store.py` itself stays a pure aqt-free presentation
  join; the disk sync lives here and in `pdf_handler`. Top-toolbar link
  labeled "Library" (`gui_hooks.top_toolbar_did_init_links`). Right-click
  per row: open, rename, move to folder, re-embed, adjust match
  sensitivity, show matches in Browse, delete. (K-146 removed "Curate
  Deck from This PDF…" — it only tagged and opened Browse on the tag
  indexing already writes, which the show-matches action opens.)
  Since K-152 the window **drives** `index_queue` rather than owning
  the index chain: `_on_embed` is one `request_pdf` call, `_on_cancel`
  stops the whole queue, and `_on_index_state` renders the runner's own
  `status_line` into the status label (so this window and the bottom
  status dock cannot word one job two ways) and re-aggregates the tree
  only on a `finished` snapshot. `busy`/`cancel_event`/`_begin`/
  `_finish`/`_on_progress` went with the chain; `seq` stays as the
  RETENTION-refresh staleness token, and `shutdown` unsubscribes
  instead of cancelling.
  Since K-117 the Library wears the VS Code Explorer vernacular
  (theme.library_qss: flat 22px rows on `surface`, one full-width
  hover/selection band, chevron twisties via
  `web/chevron-right-{day,night}.svg`, uppercase LIBRARY caption with
  New Folder/Refresh/Map beside it (Map opens `pdf_map.open_map_window`
  through a guarded import — K-124), quiet flat buttons — PrimaryButton
  opt-in kept); columns are PDF/Retention/Cards/Notes (Cards =
  VIEWABLE cards only, counts from priority_rows' K-118 keys via
  .get; a fully suspended PDF renders dimmed with "suspended" in its
  Cards cell); the context menu gains Suspend/Unsuspend Cards
  (stored-tag-first membership, ONE CollectionOp, undoable),
  Retention History… (guarded retention_history import, omitted when
  absent), and the clarity renames Update/Add to Search Index with
  setToolTipsVisible tooltips; the folder TREE also accepts external
  .pdf drops filed into the hovered folder (internal moves
  byte-equivalent); Match Sensitivity opens window-modal (dlg.open,
  K-114 — pdf_drive carries an exec-ban pin). An empty Library is not
  a void (K-132): `_LibraryEmptyState`, owned by `_LibraryTree`, is a
  sibling OVERLAY carrying `LIBRARY_EMPTY_TEXT`/`_HINT` and doubling as
  a drop target — `WA_TransparentForMouseEvents` is what keeps the
  K-117 drop path (dropEvent → `_dest_folder_at` → `_on_dropped_paths`)
  reachable through it; a stacked-widget swap would have needed a
  second drop handler. Folders-but-no-PDFs shows the SAME copy, moved
  below the folder rows. **The default splitter is `[560, 480]`, not
  `[300, 740]`** (K-135): the numeric columns are Fixed at 84+88+88, so
  a 300px pane left 24px for the PDF NAME and every row opened nameless
  — Fixed widths do not yield, the pane must fit them; test_drive pins
  that arithmetic against the real constants. tests/test_drive.py
  runs a real-offscreen-PyQt6 section: PyQt6 IS importable under
  system python3 (the klaus-test skill note saying widgets can't be
  instantiated predates this).
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
  in Browse" now hops to the per-PDF `tag_sync` tag. Since K-118
  every priority row also carries `note_count`/`card_count`/
  `suspended_count` (matched notes at/above threshold; their cards
  split viewable vs queue −1 via ONE chunked `card_queues` batch —
  900/chunk for SQLite's parameter cap), the return dict adds
  `card_queues` beside `card_r` for col-free re-aggregation, and a
  guarded `retention_history.record_rows` snapshot fires right before
  return.
- `retention_history.py` (aqt-free above its aqt-glue divider; K-118):
  per-PDF retention snapshots — `user_files/retention_history.json`,
  `{safe: [[YYYY-MM-DD, r], ...]}` local-time chronological, one entry
  per day (same-day refresh replaces), capped 730, atomic
  tmp+os.replace, corrupt reads as empty; recorded by every
  `priority_rows` pass (single writer, guarded — history can never
  break the Library). `open_history_dialog(parent, safe_name,
  display_name)` (the signature is the Library menu's contract) draws
  the QPainter line chart — show() never exec() (K-114),
  WA_DeleteOnClose, K-115 try/finally painter.end(), colours only
  theme.palette tokens (accent line + accent-at-alpha fill).
- `lecture_view.py` (aqt-free above its aqt-glue divider; K-119): the
  review-time Lecture panel. A FUNCTIONAL (never design-gated)
  "Library" button injected beside More on the reviewer's bottom bar
  (`ReviewerBottomBar` name-match; `pycmd("klausmate:lecture")`,
  answered by this module's own js-message handler — the hook filters
  CHAIN and the final return wins, so `__init__`'s blanket non-Editor
  swallow upstream is harmless) toggles a right QDockWidget on mw
  hosting a standalone `PdfSidebar`. Once open it follows
  `reviewer_did_show_question`: note tags → `!Library` candidates
  (prefs.json inverted, casefolded; the tag IS the membership verdict
  — deliberately NO threshold re-gating, `MATCH_FLOOR` sanity only) →
  one seek-read card vector (`card_index.load_row_map`/`read_vector`)
  → `pdf_index.best_chunk` argmax → that chunk's stored 1-based page;
  results cached per (nid, tags), revalidated by file stamps. No match
  shows exactly "No lecture page available for this card." pdfjs
  first-load jumps ride a generation-stamped retry ladder (the page
  posts `count:` before its divs exist); leaving review hides the dock
  (mw.web is shared across states); open-state + width persist under
  `pdf_tabs.json`'s `lecture_view` key; EVERY teardown path runs
  `sidebar.cleanup()` (K-095). Config `lecture_view_reopen`. Shortcut
  "l" via `state_shortcuts_will_change` (collision-scanned) + a
  reviewer context-menu toggle; never activateWindow — answer keys
  stay on the reviewer.
- `projection.py` (aqt-free, pure stdlib): top-2 PCA by power iteration +
  deflation over one packed `array('d')` buffer (`math.sumprod` on
  memoryview slices, strided slices for the transpose — never the d×d
  covariance matrix). Numeric foundation for the embedding map (Phase D).
- `pdf_graph.py` (aqt-free at module top): assembles the embedding-map
  graph dict — PDF nodes at their matched notes' 2D centroid, edges to
  every note at/above threshold. `retention` (which imports aqt) is
  imported lazily inside `build_graph_data`. Since K-138 it positions
  EVERY note: `projection` fits its components on a `DEFAULT_FIT_ROWS`
  stride sample but projects all rows, so a PDF's centroid is computed
  over all of its matches rather than whichever ones landed in a
  sample. **The layout is CACHED since K-167** — `user_files/map_layout/
  layout.bin`, keyed on `retention.card_index_digest` plus the
  embedding signature (compared through `embeddings.signature_matches`,
  never a tuple `==`), atomic tmp+os.replace, corrupt or truncated
  reads as ABSENT so a bad cache rebuilds rather than serving a wrong
  picture. That is the whole reason opening the Library is instant:
  cold 25.6s, warm 0.060s, positions bit-identical. The PCA is 99% of
  a cold build, and its FIT — on a 4,000-row sample — is 29 of those
  seconds while scoring all 28,670 rows is 2. **Do not "tune"
  `MAX_ITERATIONS`**: all three components run the full 40, the
  convergence test at 1e-9 never fires, and truncating moves points
  hundreds of pixels NON-MONOTONICALLY. The reason is that there is no
  eigengap — component stddevs 0.1332/0.1236/0.1190 — so PC3 separates
  at 0.93 per pass (0.93^40 = 0.05) and never converges, and PC2/PC3
  SWAP between samples of the same data. Only the 3-D subspace is
  stable. Two consequences: the fit is NOT reusable across an index
  change (measured: 150px median movement on a pure resample, which is
  why K-167 caches positions and not the fit), and the map reshuffles
  on every re-index (K-171). The canvas is `pdf_map.py`.
- `pdf_map.py` (aqt-free above its aqt-glue divider; K-123/K-124): the
  **embedding map window** — Phase D2. Pure viewport model on top
  (world↔screen transform, `fit_to_view`, cursor-anchored `zoom_at`
  whose fixed-point derivation is in its docstring, `hit_test`,
  `node_radius`, `pdf_note_ids`/`links_for`, `focus_order`, LOD
  `labels_visible`); glue is a
  singleton top-level window (show() never exec, raise_ never
  activateWindow, WA_DeleteOnClose clearing the singleton) painting
  `pdf_graph.build_graph_data` with K-115-guarded QPainter.
  **It is a VIBE, not a census (K-158, Pouya: "make it look like I'm
  accessing the matrix" and "it needs to be immediate")**: the note
  layer is SAMPLED — `SAMPLE_NOTES` across the collection plus a
  `SAMPLE_PER_PDF` stride over each PDF's own matches, so no PDF can
  be sampled out of its own cloud — and ONE PDF is lit at a time,
  every other a `GHOST_ALPHA` ghost. Focus is what makes the K-058
  centroid rule survivable: a PDF sits at the MEAN of its matched
  notes, so PDFs with overlapping note sets land in one knot, and
  ghosting is why that no longer reads as a defect. Arrow keys are
  the picker and the only thing that can separate two stacked
  centroids. Notes are cached glow SPRITES blitted per dot —
  measured cheaper than round `drawPoints` and 5× cheaper than a
  `QRadialGradient` per point at these counts, where K-148's
  opposite finding (square 15× cheaper than round) was true only at
  28,668. Edges are a capped particle trail of those same sprites,
  0.84ms and flat in zoom: glowing antialiased STROKES were measured
  and rejected at 6.35ms fit / 39.8ms for one PDF's full set, and the
  culprit was the AA rasterizer, not the composition mode
  (Plus 18.08 vs SourceOver 18.74). The pre-K-158 edges were not
  missing, they were INVISIBLE — 1px at 0.25 alpha over 28,670 grey
  chips moved 0.59% of the pixels. Names are their own pass AFTER
  every node (`clamp_label` last): drawn inside the depth-sorted node
  loop, a nearer PDF painted its disc straight across the label, which
  is what three rounds of "label clipping" actually were — paint
  order, never the offset. Tooltips are one canvas-drawn plate, not
  QToolTip. Labels show for the focused or hovered PDF only (K-138 —
  Pouya's call, which reversed K-133's always-on labels the same day).
  `select_pdf(safe)` is the seam for the Library dock: a known name
  selects and recentres only if off-view, an unknown or empty name
  CLEARS, no window is a silent no-op. `label_anchor` places the drawn
  name right of its node and mirrors it left at the canvas edge; one muted `HINT_TEXT` line beside the
  caption says what the shapes are and what the mouse does (its QLabel
  raises the window's minimum width to ~625, measured). The viewport is
  range-agnostic (`graph_bounds` measures the data) because projection
  emits [-1,1] per axis. Entry point: the Library caption row's **Map**
  button (`pdf_drive._open_map`, guarded import). Retention fills in
  lazily from the open collection; headless it stays None and the
  tooltip omits the line.
- `pdf_notes.py` (stdlib-only above a "pypdf glue" divider; K-134): the
  per-PDF notes foundation — K-079's storage and layout, built as its
  own module so it needed nothing from `pdf_handler.py` (another
  session held that file). Sidecar `annotations/<safe>.notes.md`
  (atomic tmp+os.replace; **whitespace-only text DELETES the file**,
  which is what makes empty notes un-bake back to pristine), Helvetica
  base-14 AFM widths where text becomes cp1252 bytes in exactly ONE
  place so measurement and emission cannot disagree about a degraded
  character, pure `wrap_lines`/`paginate`/`notes_pages` (30pt heading
  reserve on page one only; a token wider than the column hard-splits),
  and pure `notes_page_stream` returning content-stream BYTES —
  testable without pypdf, which this machine's python3 cannot import
  (vendor/pypdf needs typing_extensions from Anki's bundle). The lone
  glue function `append_notes_pages(writer, text, display)` imports
  pypdf lazily. **Still to wire in K-079**: the viewer pane, and ONE
  call site in `bake_annotations` — whose TWO early returns (the
  nothing-to-bake return and the un-bake branch) must learn about notes
  or a notes-only PDF never bakes; `delete_context` also does not
  unlink the sidecar, so a re-import under the same safe name would
  inherit a stranger's notes.
- `pdf_index.py` (aqt-free): persistent embedding index over one PDF's text
  chunks, `card_index.py`'s sibling for the PDF side. K-119 adds
  `best_chunk(idx, vec)` — match_scores' inner max-dot loop keeping
  the argmax it discards; page for row j = `chunks[j][0]` (1-based).
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
- **Semantic matching stack** (the per-PDF `!Library` tags + the Library's
  retention score; this is the only AI-powered feature left):
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
    bundled Python**) — 30k×768 ranks in ~0.25 s. K-119 adds `RowMap`/`load_row_map`
    (manifest-only) + `read_vector` (single-row seek) so per-card
    lookups never pay the full vector load.
  - `curation.py` (aqt glue): two-phase `ensure_index` (snapshot with col
    via `select id, mod, flds from notes` + `flds.split("\x1f")`; embed
    without col, partial save every ~1k vectors) + the undoable deck copy
    (`prompt_and_create` → `add_custom_undo_entry` → `col.add_notes` →
    `merge_undo_entries`, tagged `!Library::Curated`) behind the Browse
    Notes-menu action `setup_hooks` registers. **`ensure_index` is the
    card index and nothing else refreshes it** — K-146 deleted
    `run_curation`, the composed search that used to be its only
    user-facing caller, and moved that call into `pdf_drive._on_embed`;
    K-152 moved it again, into `index_queue`, where it is phase one of
    the one chain every index request runs. A new PDF-matching surface
    that skips it silently matches against a stale index (missing
    cards, no error). **Never delete this module**:
    `retention.py` imports it at module top for `USER_FILES`/`INDEX_DIR`/
    `_cfg`/`_fail` and for `_busy`, the ONE re-entrancy token every
    embedding phase holds; manage_models, tag_sync and pdf_map read it
    too. Gone with K-146: `run_curation`, `_preview_in_browse`,
    `last_run`, `suggest_deck_name`, `_escape_search` (and long before
    them, the `!Library::Curating` temp tag K-064 retired — CLAUDE.md
    and config.md both went on documenting it until K-146).
  - `index_queue.py` (aqt-free above its "aqt glue" divider; K-152): the
    **index runner** — the ONE copy of the four-phase chain
    (`curation.ensure_index` → `retention.ensure_pdf_index` →
    `ensure_matches` → `tag_sync.sync_after_matches`, cancel token
    threaded through, each phase taking `curation._busy` in its own
    turn per K-146) plus a serialising queue in front of it. It exists
    because that chain was a METHOD on the Library window
    (`DriveWindow._on_embed`) and a PDF added from the deck screen has
    no Library window: `_on_embed` now just calls `request_pdf`, and
    `__init__.import_pdf_file` — the one funnel every import surface
    returns through — calls `on_pdf_imported`, so every add indexes
    itself (config `auto_index_on_add`, default ON; a corrupt value
    reads ON, opposite of `background.design_enabled`'s rule, because
    the failure here is a silently deleted feature rather than an
    unasked-for restyle). **`curation._busy` REFUSES concurrent runs** —
    right for a double-clicked button, wrong for ten dropped PDFs — so
    jobs queue here (dupes collapse, FIFO) and the runner WAITS on that
    token (`_busy_elsewhere`, bounded poll) rather than racing
    Preferences' Index Now, which still calls `ensure_index` directly
    for its own progress bar. Feedback is the shippable part: ONE
    `RunnerState` snapshot is published to every listener and rendered
    by ONE pure `status_line`, so the Library's status line and
    `_StatusDock` — a thin bottom dock on `mw` (a QDockWidget, the
    `lecture_view` pattern; an overlay child over the central webview
    is a z-order gamble) carrying the same text and a Stop button,
    visible on the deck screen, the overview and mid-review — cannot
    describe one job differently. Gates: no profile, no cloud API key,
    no run (the refusal is a MESSAGE, not a shrug). A PDF deleted
    before OR during its turn is skipped silently, and a deletion error
    never fails the batch behind it. Cancel bumps `_seq`, which is what
    stops `after_matches` tagging on the PARTIAL ranking
    `ensure_matches` hands back. **Closing the Library no longer
    cancels indexing** (the job may have been started from the deck
    screen). `offer_model_sweep(parent, prev_sig)`, called from
    `manage_models.save_embed` with the signature captured BEFORE the
    widgets overwrite config, re-indexes the card index plus every PDF
    with an index on disk — announced first, counted in notes and PDFs.
    Signature comparison is ALWAYS `embeddings.signature_matches`,
    never a tuple `==`: a hand-spelled one reads every cache as stale
    and re-embeds the collection on a paid API, silently (the exact bug
    eight call sites shipped when the signature grew a third element).
  - `pdf_drop.py` (was `deck_curate.py` until K-151, a misnomer once it
    curated nothing): the deck-screen **PDF import** surface — the
    `MainWebView.dropEvent` wrap (the only thing stopping Anki's own
    importer choking on a dropped PDF) and the drop square on the deck
    list and overview with its Browse… picker. K-146 removed the two
    bottom-bar buttons, `CURATE_CMD`, `choose_deck_scope`,
    `run_curation_flow` and `_pick_pdf_menu`; **K-151 removed the ARMED
    half whole** — `_armed_pdf`/`arm`/`disarm_if`, `DISARM_CMD` and its
    handler branch, the armed HTML, the deck/overview re-render it
    needed, the `profile_will_close` reset, and `pdf_drive`'s
    `disarm_if` call on delete. Arming staged a PDF for the curate
    button; with the button gone there was nothing to arm FOR, and
    `import_pdf_file` already tooltips every load. The square now has
    ONE state and the module ONE module-level name (`BROWSE_CMD`) —
    both pinned in `tests/test_drive.py`. The js-message handler stays
    registered for that one command, so the roster in
    `tests/test_bridge_reentrancy.py` is still five, one member renamed.
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
- Deleted (2026-08, do not resurrect the language): `claude_api.py`
  (its streaming client lives on, reshaped, as `llm_client.py`),
  `settings_ui.py`, `chat_dock.py` (the "Klaus panel"),
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
- **pypdf writes `/DA` only `if border_color:`** — and a FreeText's font
  size and colour live in `/DA`, the default-appearance string, NOT in
  `/DS`, the rich-text one Preview and most readers ignore. Klaus passes
  `border_color=None` deliberately (K-150: Preview frames a text box only
  while it is selected), so every baked note shipped `/DA ()` and drew at
  the reader's own default — small and black — for two releases.
  `pdf_handler.free_text_da` emits it now (`/Helv <size> Tf <r> <g> <b>
  rg`), and `text_point_size` feeds both it and pypdf's `/DS` so one
  annotation's two appearance strings can never disagree. No `/DR`, no
  `/AcroForm`: `/Helv` is base-14 and both engines resolved it with
  neither present. Highlights were never affected — they carry `/C`.
  **Check annotation appearance in a RENDERER, never a hex dump**:
  `qlmanage -t` draws no annotations at all on this machine, so its blank
  page reads as "broken file" when it is the proxy that is broken;
  PDFKit — the framework Preview.app itself draws with — is the honest
  check, pdf.js with `annotationMode: ENABLE` the second.
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

- **No app-modal `exec()` anywhere** (K-114, completed by K-125): every
  dialog is window-modal `open()`/`show()` with signal-driven results —
  `finished`+`clickedButton`, `textValueSelected`/`intValueSelected`,
  or an accepted-callback CPS where a return value used to be consumed.
  Closures keep shown dialogs referenced (a non-exec dialog with no
  Python ref is GC'd shut); `deleteLater` rides `finished`; `aqt.utils
  .askUser`/static `QInputDialog.getX`/`QMessageBox.question` are in
  the banned class too (they exec internally). QMenu.exec is fine.
  Ban pins live in tests/test_bridge_reentrancy.py + test_drive.py.
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
