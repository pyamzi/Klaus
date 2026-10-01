# CLAUDE.md — Addons repo / Klaus (klausmate)

## Current architecture: local-model reversion

The approved [local-model reversion](docs/superpowers/specs/2026-09-18-local-model-reversion-design.md)
is implemented locally as of 2026-09-19: D1-D3 removed the subscription service,
reasoning judge and embedded assistant; D4 restores managed Ollama embeddings
and D5 exposes context through a local stdio MCP bridge. D6's whisper.cpp
lecture recording was removed on 2026-09-30 (K-314): recording belongs to the
Klaus app, not the add-on. See [completion evidence and limits](docs/superpowers/reports/2026-09-19-local-model-reversion.md).
Older API-first and cloud-only designs are dated history, not current guidance.

The real project here is **`klausmate/`** — "Klaus", an Anki addon for a
lecture-PDF library with per-PDF retention scoring, semantic card↔PDF
matching (indexing a PDF tags every card it covers), a PDF reader
(pdf.js) with highlights/sticky notes, and image cropping. Around it:
`tests/` (headless logic tests), `board/` + `context/` (the multi-agent
kanban board — see below), `References/` and `scripts/` (vendored
reference repos + packaging), and `AGENTS.md` (deep architecture guide:
hooks registered, JS↔Python protocol, config keys, packaging).
`PRODUCT.md` says what Klaus is for; `DESIGN.md` is the design language —
tokens, surfaces, the "Quiet Clinic" brief, and the mark: Pouya's
hand-drawn k (2026-10-01), one evenodd path in `top_bar._LOGO_PATH`,
verbatim from `docs/reference/brand/klaus-logo.svg`.

Klaus was **embeddings-only** from 2026-08 to 2026-09-01: its one AI
capability was semantic search, which defaulted then to the **Voyage**
cloud embedding API, with a local Ollama alternative and OpenAI as a
second cloud option — history as of 2026-09-15, when the API-first turn
cut that to OpenAI alone. Autocomplete, ⌘K Ask, the Klaus chat
panel, the Settings dialog, and the original Claude/Anthropic
integration were all deleted then — if you find docs, comments, or
instincts that assume THOSE surfaces still exist, they're stale. See
AGENTS.md's "What used to be here".

**Historical architecture, updated 2026-09-19:** the 2026-09-01 assistant
became a Claude Code dock on 2026-09-02. The API-first turn on 2026-09-15
introduced cloud embeddings and page records; its second plan added
recording and a pertinence judge on 2026-09-17. Klaus Plus was a separate
billing/proxy service. Those designs are superseded by the local-model
reversion linked above. D1-D3 have removed the service, judge, dock,
process host and session store. Page records, collection tools,
`anki_endpoint.py` and `viewer_context.py` remain. The cloud assistant
Plan 3 was never built and is not pending work. Historical specs:
[assistant](docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md),
[API-first](docs/superpowers/specs/2026-09-15-api-first-klaus-design.md),
[Plus](docs/superpowers/specs/2026-09-16-klaus-plus-subscription-design.md).

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/Klaus/Klaus Addon/klausmate/`,
  even though worktrees now contain a copy. Anki loads the addon through a
  symlink to the main checkout only, and the PostToolUse compile hook
  compiles that symlink target — so a worktree edit would report success
  without ever being compiled or loaded.
- Commits and diffs for addon work are now expected.

## Commands

- **Run the whole test suite**:
  `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" || failed=1; done; test "$failed" -eq 0`
- **Run one test file**: `python3 tests/test_klausmate.py`. The files that
  need real PyQt6 widgets use offscreen rendering. Set that environment
  explicitly; see "Anki runtime & testing".
- **Add `PYTHONDONTWRITEBYTECODE=1` when you re-run a test after editing the
  module it covers**, not just on a mutation run. This Mac sets
  `sys.pycache_prefix` to `~/Library/Caches/com.apple.python`, so stale
  bytecode is written OUTSIDE the repo — an empty `__pycache__` here proves
  nothing — and CPython validates a `.pyc` on (mtime, size) alone: a
  same-size edit inside one mtime second silently executes the OLD code and
  the test passes on it. `scripts/mutation_audit.py` purges both cache roots
  and aborts on a stray `.pyc` for exactly this reason.
- **Verify syntax through the symlink Anki actually loads** — do this after
  every `klausmate/*.py` edit (the PostToolUse hook already runs it
  automatically):
  `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py`
- **Build the shippable package**: `./scripts/package.sh` → `dist/klausmate.ankiaddon`
- **The vacuity gate**: `python3 scripts/mutation_audit.py --modules <module>`
  breaks the code on purpose to find pins that cannot fail (`--list <module>`
  shows the mutations, `--selftest` checks the tool). It never touches the
  working tree — every mutation is applied in a sandbox copy, and the repo is
  hashed before the run and re-hashed in a `finally`.
- **Board CLI** (see "The agent board" below):
  `python3 board/board.py {list,show,claim,move,comment,check-disjoint}`
- No linter is configured in this repo.

## The agent board

Multi-session work is coordinated through a kanban board:
`board/BOARD.md` is the source of truth, and **every state change
(claim/move/comment) goes through `python3 board/board.py`** — it
serializes writes behind a lockfile; hand-editing BOARD.md to move a card
will eventually lose a write (card *body* prose may be hand-edited by the
orchestrator/designer only). Claiming enforces file-disjointness against
cards already in Doing, and a card's `verify:` command must fail before
the work and pass after. Roles, columns, and gates: `context/ROLES.md`;
the rules a session must hold to share the board safely are the
`agent-board` skill (`.claude/skills/agent-board/`).
Dashboard: `python3 board/serve.py --port 8766` → 127.0.0.1:8766
(preview config "board-dashboard" in `.claude/launch.json`). **Not
8765** — an unrelated long-running `stream_server.py` owns that port on
this machine, so the board silently failed to bind there and the
preview served that server's "you need a WebSocket client" page
instead. Signed-off history is in
`board/ARCHIVE.md` — search it (K-0xx) before re-debugging anything.

**Parking another session's uncommitted hunk (Pouya, 2026-09-01).**
Three sessions routinely work this checkout at once, so you WILL claim
a file that carries someone else's uncommitted change. Never park it
with a checkout to HEAD: that is byte-for-byte indistinguishable from a
revert to every other session, and on 2026-09-01 it was reported as one
("reverted, no stash, no card") for an hour. Park with all three of:
(1) a tagged stash scoped to the file — `git stash push -m "parked:
<your card> <what the hunk is>" -- <file>`; (2) a patch copy in YOUR
scratchpad (`git diff HEAD -- <file> > .../parked-<file>.patch`),
because the stash stack is shared across the main checkout and every
worktree and another session may pop it; (3) a `board.py comment` on
your claiming card naming both the stash message and the patch path.
Re-apply exactly as found when your commit lands, before moving your
card to Review, and say so in a comment. Bare `git stash`/`stash pop`
without `-m` and without the file scope are off-limits here for the
same reason.

## How Anki loads the addon

- Symlink: `~/Library/Application Support/Anki2/addons21/klausmate` →
  `/Users/pyamzi/Documents/Github/Klaus/Klaus Addon/klausmate`. If the repo
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
  logic, with real Qt offscreen where widget behavior matters**. The harness lives in `tests/` (see its
  README) with the bootstrap documented in the `klaus-test` skill — use
  that skill when adding or changing klausmate modules. Run everything:
  `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" || failed=1; done; test "$failed" -eq 0`
- **Offscreen PyQt6 can verify far more than "does it construct"
  (Pouya, 2026-09-01).** Under `QT_QPA_PLATFORM=offscreen` a real
  `ReaderTabs`/`MapCanvas` (or the Browse-sidebar delegate) renders to a `grab()` you can
  pixel-read, and every one of these is reachable headless — do not
  claim they need a live screen: **Retina** (`QT_SCALE_FACTOR=2` before
  `QApplication`, then `devicePixelRatioF()` is 2.0 and strokes render
  at device density); **hover** (`WA_UnderMouse` + a `QtGui.QEnterEvent`
  and `QHoverEvent` — they live in QtGui, not QtCore — then
  `unpolish/polish` so QSS re-evaluates); **pressed** (`setDown(True)`);
  **focus** (`QApplication.focusWidget()` after the same parentless-
  construct → `addWidget` → `show()` sequence the host uses — that is
  what caught K-179's misplaced focus ring in the since-deleted Library
  screen, which a live accessibility probe had missed). Prove a state took by
  diffing pixels inside the widget's rect against the rest frame; zero
  changed pixels means the QSS state never applied. What offscreen
  genuinely CANNOT do: screencapture the live window, or drive the real
  event loop (timers fire only through `processEvents()`, so a
  `singleShot(0)` needs one explicit turn). One live-check limit that is
  not technical: **never drive the user's running Anki as a test
  fixture.** If its process id changes to one you did not launch, Pouya
  is at the machine — stop sending clicks and keystrokes and ask him
  for the glance instead. `PyQt6-WebEngine` is NOT installed for system
  python3, so pdf.js pixels cannot be produced headless; say so rather
  than claim them.
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
  `complete`/`ask` actions are gone with autocomplete/Ask); the
  bootstrap of the **settings store** (`settings.py`, aqt-free; spec
  [settings-seam](docs/superpowers/specs/2026-09-30-settings-seam-design.md),
  2026-09-30): `__init__` installs
  `settings.store = AnkiStore(mw.addonManager, __name__)`, `settings.run_on_main` and
  `settings.current_profile`, and every module reads config through
  `settings.read()` and writes through **`settings.patch(updates,
  remove=())`** — the ONE writer, a merge into a fresh read, inline on
  the main thread and hopped through `run_on_main` from any other,
  dropped if the profile changed before the hop ran. **There is no
  whole-blob writer any more**: the old `write_config(cfg)` replaced the
  stored blob, so a partial dict handed to it wiped API keys and the
  library root (two reviewers found that as a Critical), and
  `patch_config` existed to work around it; both are gone with the six
  `_pkg()` helpers, `index_queue._cfg`, `retention._cfg` and the
  `USER_FILES` copies (`settings.user_files()` is the one path).
  Migrations are pure `dict -> dict` functions registered with
  `settings.register_migration` (retention's two threshold bumps; the
  legacy-key scrub is built in) and run ONCE per profile open by
  `settings.migrate()`, never on read. Tests assign `settings.store =
  DictStore({...})` (or the harness's `LiveStore` over a dict they keep
  mutating) and `settings.user_files_dir = <scratch>`; the ONE PDF reader
  (`reader_panel.PdfSidebar`, `host_key="editor"`, the `ReaderTabs` strip
  above its page) is owned by `reader_host.py` since the Add tab
  (2026-10-01, spec `docs/superpowers/specs/2026-10-01-add-tab-design.md`):
  its permanent parent is the Add tab's reader slot (`set_home`), Browse's
  viewer mode borrows it (`library_viewer.enter` → `lend(box)`, `leave` →
  `give_back()`), `release()` is cleanup + forget and a cleaned reader is
  never reused (the peer's lifecycle rule: `PdfJsViewer.cleanup` drops its
  webview for good). It is NEVER re-parented across top-level windows — a
  lend into another window releases and rebuilds there; in fallback mode
  (stock Browse) it is built under Browse and released when that Browse
  closes. The dock (`PdfDock`, `_PanelBar`, left/right/bottom/float
  placement in `pdf_tabs.json`, migrated by `migrate_placement`), the
  editor-toolbar Library… button (`copilot.js` + the `library` pycmd) and
  the status-bar / bottom-row "Right Sidebar" dock toggles were deleted
  with it; `_load_tabs_file` drops `placement`/`geom` from older files.
  The reader strip's ＋ button: `@_guarded` zero-argument
  slots connected to `clicked` had been swallowing PyQt's `checked`
  argument as a TypeError since the panel was built (both slots now
  take `*_args`); image-crop plumbing;
  Tools menu
  (`install_menu`: ONE entry,
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
  edit mode — right-click → "Edit Widgets" (JS preventDefault beats
  AnkiWebView's menu; pdfjs precedent), iOS jiggle (disabled under
  Anki's `body.reduce-motion` class — Anki ships NO
  prefers-reduced-motion CSS), per-widget shields so deck clicks/drags
  are unreachable while jiggling, ⊖ badge, ＋ popover, Done/outside/
  Esc, and pointer-event drag-reorder. **Other add-ons' blocks are
  widgets too** (Pouya, 2026-09-30: "anytime there's a new thing on the
  screen"). **They are wrapped in PYTHON, in the HTML, and the page never
  moves a widget**: AMBOSS's `<amboss-component-wrapper>` builds a new
  React root in `connectedCallback`, so each DOM move drew another card
  (three, live). `dashboard.wrap_foreign` (tolerant parse, bails to the
  unchanged body) wraps every other direct child of the deck screen's
  `<center>` as `x:<id | .class | tag>` (`FOREIGN_ID` is the only shape
  Python accepts; Anki's table/`<br>`/studied line, `.klaus-*` and scripts
  are skipped); the `<center>` becomes a flex column (`klaus-dash-col`)
  and `applyOrder`/drag/abort write CSS `order` only. Removal writes
  `dashboard_hidden` (`apply_action(action, cfg)`), which `wrap_foreign`
  also writes as `display:none`. Blocks added after load are not
  adopted (wrapping them would mean moving them). The node harness
  counts custom-element connects to pin this. (HTML5 DnD is dead on this
  screen: MainWebView.dragEnterEvent eats non-file drags). **The deck
  screen is a GRID since 2026-10-01** (Pouya: "they should fit within
  square boxes"): the `<center>` is one CSS grid of `GRID_CELL` (160px)
  squares, `GRID_GAP` (16px) apart and around, no `dense` flow (a
  widget's place must follow its order or a drag lands elsewhere).
  Every widget fills a whole COLUMNS x ROWS box (`--kw-cols`/`--kw-rows`
  spans, set by the page and clamped to the columns the window has) and
  scrolls inside its `.klaus-w-body` (the wrapper's own child, so the ⊖
  badge is never clipped; Python's `wrap_foreign` writes the same pair).
  Sizes are Klaus's, not a setting (Pouya: "set up predecided 2x1,
  1x2... then I will just move it around"): `SIZES` per widget id,
  measured once from the rendered content (re-measure in the offscreen
  harness when a widget's content changes shape), `FOREIGN_SIZE` for an
  add-on block not listed. A stale `dashboard_sizes` in meta.json is
  ignored. The grid is at most `GRID_MAX` (800px, 4 columns) wide and
  centred (`width: fit-content; max-width: min(800px, 100%)`, so the
  box sits exactly on its tracks); edit mode shows every cell as a
  dashed slot (`.klaus-dash-cell`, see OWN_HEIGHT below) and outlines the landing box while dragging
  (`.klaus-dash-slot`, absolutely positioned so it takes no cell).
  Add-on cards drawn in an OPEN shadow root (AMBOSS) get
  `SHADOW_CSS[tag]` adopted into the root as a constructed sheet (a
  `<style>` node would be the add-on renderer's to drop): AMBOSS's
  440px div with 2em margins is what sat its card ~30px low.
  `OWN_HEIGHT` (the deck list; Pouya: "let the deck list have its own
  height") takes ONE grid row whose height is its content's: grid rows
  are `minmax(GRID_CELL, auto)`, its body is in flow (`.klaus-w-own`)
  with the SIZES rows as `max-height`, then it scrolls; every other
  body is absolute, so other rows stay exactly a cell. Only full-width
  widgets may be listed (a row it sets would stretch neighbours). So the
  edit-mode cells are drawn by the page from the grid's computed
  `gridTemplateRows` (`.klaus-dash-cell`, inserted first, absolute), not
  a repeating tile, which would drift below a taller row. AMBOSS is
  own-height too (its text wraps taller in 3 columns), so SHADOW_CSS
  fills by FLEX (host a growing column flexbox), never height:100%,
  which an own-height box cannot resolve. **Widget size**
  (`dashboard_scale`, 70-150 in 5s, `valid_scale`): a slider in the edit
  bar, live on `input`, saved on `change`; CSS `zoom` on the grid via
  `--klaus-dash-scale`. Chromium 140 zoom: clientWidth and computed
  tracks stay UNZOOMED, getBoundingClientRect is zoomed, so drag
  translate and the landing outline divide screen distances by zoom().
  The cap is `min(720px, 800px / scale, 100%)`: 4 columns at most and
  never over 800px on screen. It sits ON TOP of Anki's User Interface
  Size (QT_SCALE_FACTOR already scales the webview; `ankiScale` is shown
  in the chip's title). Same Look: card #3A3A3C at night (dark `surface`
  IS Anki's canvas), firmer hairline, no shadow (DESIGN.md), and add-on
  buttons become DESIGN.md primary buttons (`_PRIMARY_BUTTON`, also in
  AMBOSS's root via `:host-context`). Review fixes (2026-10-01): the
  heatmap is own-height too, and `.klaus-widget:has(details[open])`
  lets a popover (its settings menu) out of the scroll box and above
  the next widget; the edit bar never covers the grid (`clearBar` adds
  the overlap as the grid's margin-top while editing); edit-mode cells
  are drawn only where no widget's offset box sits; keyboard: Shift+F10
  or the Menu key opens "Edit Widgets" (no ellipsis: it is a mode, not a
  dialog), menu items are focusable menuitems, each shield is a
  focusable button and arrow keys move it (`moveBy`, saved per press);
  Same Look colours are `theme.palette` tokens (`card_raised`,
  `on_accent`); a month starting in the heatmap's last column keeps its
  gap and loses its name. A box's ONE card stretches to fill it (`:only-child`,
  never Anki's table: a stretched table spreads height into its rows).
  **Same Look** (`dashboard_uniform`, explicit True only, a chip in the
  edit bar): one DESIGN.md card on every box and each widget's own outer
  card switched off, colours inside untouched; its 12px padding
  replaces the child's own, so a box that fits without it still fits
  (the 4x1 heatmap has 3px to spare). The jiggle is iOS-strength
  (±1.5° and a 1px bob, ~0.26 s) with a random phase and period per
  widget, and drag is 2-D: pointer over another widget takes its place
  in the order. Visibility
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
- `browse_toggles.py`: the pane toggles. In the single window they are
  HTML in Anki's top bar, right after the Klaus logo
  (`top_toolbar_will_set_left_tray_content`, `setup_top_bar` called from
  `status_bar.setup`): ◧ ◨ for the Add tab (Library tree, editor) and
  Browse (sidebar, card editor), hidden on Decks; a click is
  `pycmd("klausmate_pane:left|right")`, and every change (click, tab
  switch via `Host.listeners`, a pane hidden elsewhere, toolbar redraw)
  re-pushes `pane_state()` through `klausPanes`. The icon is
  `_PaneToggle`'s geometry as SVG (`pane_icon_svg`); on = `text`, off =
  `text_muted`. The self-painted `_PaneToggle` and `_VisibilityWatcher`
  remain for Browse outside the single window, beside its status-bar
  gear; plus the `browser_will_show` layout repair.
  `pane_keep.py`: a toggle hides or shows one pane and keeps the
  OPPOSITE one at its width (`set_visible_keeping(widget, on,
  opposite)`); the difference goes to the widest other splitter pane
  (the reader, the card table). A plain `setVisible` made Qt share the
  change across every pane, so the opposite sidebar grew or shrank too.
  A dock never matches an outer splitter (the climb stops at a main
  window), and the width is put back now and again a tick later, when a
  main window re-lays its docks.
- `tasks.py` (aqt-free) + `status_bar.py` + `bottom_row.py` (spec
  [status-bar](docs/superpowers/specs/2026-09-30-status-bar-design.md)).
  **Main window: NO Qt bar** (the user's call, 2026-09-30, after the
  copied-buttons version showed Anki's row twice). `bottom_row` extends
  Anki's OWN deck-list / overview bottom row (`webview_will_set_content`,
  `DeckBrowserBottomBar`/`OverviewBottomBar` contexts; review's answer
  row untouched): a gear at its left edge (divs, not
  `<button>` — Anki's bottom CSS frames buttons) → Anki's Preferences,
  and at its RIGHT edge the task readout (newest task, then its
  progress, red on failure; click → the task list). Its height is what
  every Qt bar follows: a resize filter on `mw.bottomWeb` (deck screens
  only, never the taller review row) calls `status_bar.set_row_height`,
  so the bottom edge is one height on every tab (28px floor,
  `STRIP_MAX` cap, both times `bar_scale`). It starts in the rendered state and follows `tasks`
  live via `klausStatus` evals on `mw.bottomWeb` while
  `mw.state` is deckBrowser/overview. Both clicks open a tick later
  (`bridge_reentrancy`'s deferral rule). **Browse** keeps a 28pt Qt bar
  (`status_bar.install_browser`): gear → Anki's Preferences in one click
  (no menu; Klaus's settings are the top bar's k and Tools menu),
  and at the bottom RIGHT the task text ("+N more") then its progress
  bar (click → `show_task_list`, a `Qt.Popup` clamped to the screen by
  its outer frame, with ✕ where a task can be cancelled). The Add tab's
  bar is built the same way (a `QStatusBar` strip, `_strip`), so the two
  cannot differ; neither has pane toggles in the single window (they
  are in the top bar). `visible_tasks`, `gear_points` and
  `show_task_list` are shared by both.
  `tasks` is the one list of running processes — `begin`/`update`/`end`
  from any thread; listeners run only through `run_on_main`
  (`mw.taskman.run_on_main` once a profile opens). Reporters: indexing
  (`index_queue._report_task`, key `index`, ✕ = `cancel_all`), folder
  scan FAILURES only (`rescan`; the running scan is silent by request),
  the Browse retention % (`retention`), Anki's collection and media sync
  hooks (`sync`, `media`), and Preferences' Ollama install/pull
  (`ollama`). An end message lingers `LINGER_S` (4 s); `end(...,
  error=True)` stays, in red, until the next `begin`. Tasks younger than
  `SHOW_DELAY_S` (0.5 s) aren't drawn (no flashing). The QSS goes on Qt's
  QStatusBar (one hairline, no macOS panel line or item frames).
  Anki's own "Processing…" popups are deliberately not mirrored.
  **Bar size** (`bar_scale`, 70-150 in 5s, default 85,
  `dashboard.bar_scale_from_cfg`; 2026-10-01): one factor on top of
  Anki's User Interface Size for the top bar, the deck/overview row and
  the strips. Webviews: `theme.bar_zoom_css` (`body { zoom }`, Anki's
  own `app_zoom_factor` multiplied in) injected by
  `top_bar._on_webview_will_set_content` BEFORE the design gate, so the
  stock bars shrink too; never `setZoomFactor` — Anki's
  `adjustHeightToFit` reads `documentElement.offsetHeight`, which follows
  CSS zoom only. `klausFit` divides screen px by the body zoom. Strips:
  `status_bar.scale()` (cached, reset per profile) scales the floor
  (never under `STRIP_MIN` 20), the cap, the gear and pane toggles
  (`_size`; the icon follows the button, `browse_toggles.icon_size`),
  the progress width and `status_bar_qss`'s text; `set_scale` re-sizes
  every bar. Live: Preferences previews it (appearance preview →
  `top_bar.refresh` redraws both webviews; `set_scale` the strips) and
  reverts on Cancel.
- `addons_menu.py`: every top-level menu bar entry that isn't Anki's own
  (`MAIN_MENUS`/`BROWSE_MENUS`, the `window.form` names from main.ui and
  browser.ui) moves whole under ONE "Add-ons" menu before Help, in the main
  window (`main_window_did_init`, which fires after all add-ons load) and
  Browse (`browser_will_show`). A menu-bar `ActionAdded` watcher re-runs
  it a tick later for menus added afterwards (AnkiHub's). Hidden when empty.
- `single_window.py` + `host_keys.py` (spec
  [single-window](docs/superpowers/specs/2026-09-30-single-window-design.md),
  config `single_window`, default on): the main window is the only daily
  window. Decks (Anki's whole main screen, unchanged), Add and Browse are
  pages of a `QStackedWidget` under Anki's toolbar, whose three links are
  the tabs (`klaus-active` class). The Add page (`build_add_page`,
  `AddPage`) is a splitter of `library_tree.LibraryTree` | the reader
  slot (`reader_host`'s home) | the editor slot Anki's Add is built into,
  with Klaus's status bar (`status_bar.install_add_tab`; its ◧ tree /
  ◨ editor toggles are in the top bar, `browse_toggles`) under it; `a` and the Add link switch to it (`open_add` asks Anki for an
  instance when none is live), Close and Escape go back to
  `Host.previous`, the splitter persists under `klausmate_add_tab`
  (`saveSplitter`), and a click on a PDF row loads it into the reader.
  Edit Current keeps its right dock (the one dock left; it still runs the
  full window height beside the stack — open bug). The Add tab is
  keyboard-scoped exactly like Browse (state keys suspended, bare host
  keys parked, `focus_in_editor` lets typing through in the editor slot
  and the Edit dock). **Anki's windows are never moved** (see the
  Deleted paragraph): each is BUILT as a child of its container from its
  first line — `register` replaces the creators of every hosted name in
  `aqt.dialogs._dialogs` (26.09 has five: Browser, AddCards, NewAddCards,
  EditCurrent, NewEditCurrent) with `_construct`, which puts `_Shim`
  after the class in a subclass's method resolution order (`super().
  __init__(None, Window)` lands in the shim) AND swaps the class's
  module-level `QMainWindow` name for the one constructor call (Browse
  calls `QMainWindow.__init__(self, …)` explicitly); whichever the source
  uses runs once, the other is inert. `build_host` moves whatever the
  central layout holds (AMBOSS and AnkiHub wrap `mw.web` in a splitter
  and find it through `mw.mainLayout`, which now IS the Decks page's
  layout) and never detaches a layout. Browse's menus swap into the host
  bar while its tab is active (`menus_in/out`, exempt from
  `addons_menu`'s watcher via `_klausmate_keep_on_bar`; its Add-ons menu
  reads "Browse Add-ons" there), which is also what scopes their
  shortcuts. `host_keys`: the state shortcuts (review keys) are recorded
  from `state_shortcuts_will_change` and DISABLED (never cleared and
  re-set) while the Add or Browse tab shows; an app-level `ShortcutOverride`
  filter lets those keys type into the hosted editors (the Add editor
  slot and the Edit dock). Escape does nothing in the Browse tab; Add's
  Close and Escape go back to the previous tab (a close filter;
  Anki's own teardown, `_close_event_has_cleaned_up`, passes); Edit
  Current's dock is reaped once the registry shows it closed. Startup:
  Decks, dock closed (`mw.saveState` under `klausmate_host_state`).
  Fallback: any preflight or shim failure restores Anki's creators for
  the session, with a toolbar tooltip and a sticky error task; `false`
  in config is stock Anki. Live-verified 2026-09-30 on 26.09.2 with
  AMBOSS + AnkiHub active: both editors render.
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
  per-surface builders (`dialog_qss`, `panel_header_qss`,
  `pdf_panel_qss` — the reader panel styles itself, K-153 —
  `drop_zone_qss`, `muted_label_qss`, `accent_rgba`). (`library_qss`
  and `accent_mix` went with the Library window in K-308;
  `find_bar_qss`, `thumb_strip_qss` and `pdf_panel_qss`'s splitter rule
  went with the native viewer in PDF reader 5/5.) The pdf.js reader needs no palette roles:
  `css_vars` hands its page `var(--bg)` directly. **UI files must not hardcode colours** — import theme and
  reference tokens; styles are computed at widget creation (a night-mode
  flip catches up on next open). Dialog buttons are blue-primary by
  default with `SecondaryButton`/`DangerButton` objectName opt-outs.
- `pdfjs_viewer.py` + `web/pdfjs_viewer.html` + `web/pdfjs/` (vendored
  pdf.js 3.11.174): the ONE PDF reader (spec
  `docs/superpowers/specs/2026-09-30-pdf-reader-design.md`). The native
  QPdfView renderer (`pdf_viewer.py`) was deleted in PDF reader 5/5
  (2026-10-01); there is no fallback — without QtWebEngine
  (`PDFJS_AVAILABLE` false) `PdfSidebar` shows a "PDF viewer is
  unavailable" label. The PDF loads in pieces: Python hands the page the
  file length and the first 256 KB (`first_chunk`), and pdf.js's
  `PDFDataRangeTransport` asks for the rest on demand over
  `pycmd("klausmate_pdfjs:range:<gen>:<begin>:<end>")`, answered by
  `handle_range` → `pdf_source.range_reply` (at most 1 MB a call; a
  request from an older document generation is refused; a stale
  fingerprint makes the reader reload in place). `teardown()` destroys
  the document. Pages render lazily via IntersectionObserver
  over sized placeholders, and up to 12 pages outside the render zone
  stay rendered (`KEEP_RENDERED` in `web/pdfjs_pure.js`, least recently
  visible evicted first); `klausSetAnnotations` redraws only the pages
  whose records changed; the first find searches visible pages first,
  then the rest in idle batches. Native pinch gestures never reach
  Chromium: the webview's event filter forwards `ZoomNativeGesture` to
  the page and turns `SmartZoomNativeGesture` into a fit-width toggle, and a
  page whose `visualViewport.scale` leaves 1 anyway posts `vv-scale`
  and Python reloads it. The pdf.js text layer gives native selection,
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
  the bridge (`hl-add`/`hl-remove`/`note-edit`/`text-add`/`text-update`),
  `PdfJsViewer` persists via `pdf_handler.save_annotations`, asks
  `annotation_save`'s pipeline for the bake, keeps K-081 tombstones, and
  pushes canonical records back via `klausSetAnnotations`. Pure helpers
  (`first_chunk`, `handle_range`, `build_page_html`, `parse_bridge`,
  `decode_b64_json`, `gesture_action`, `records_from_rect_map`) are
  aqt-free for `tests/test_pdfjs_viewer.py`.
  Parity completed by K-100:
  Cmd/Ctrl-double-click copies the slide (through the shared
  copyPageImage bridge — the clipboard is the "insert into field"
  surface), the marquee persists across zoom/re-render with native
  press semantics + drag-out (PNG dragstart; re-copy+paste is the
  fallback if a drop into a field does not land), and find highlights
  the exact substring via the CSS Custom Highlight API with the
  whole-span ring as guarded fallback. The cutover (K-101) finished with
  PDF reader 5/5. The annotations JSON + bake pipeline belong to no
  reader — never fork them.
- `pdf_source.py` (aqt-free): piece loading's byte source. `DocSource(path,
  snapshot_dir)` hard-links the file into `<user files>/reading/` at load
  (`pdfjs_viewer._reading_dir`, via `pdf_source.user_files_dir()`) and
  reads that link, so Klaus's own bakes (`os.replace` → a new inode)
  never disturb an open reader, while an outside in-place rewrite still
  reads stale; where a hard link is impossible (another volume) it reads
  the live file. Each `read(begin, end)` opens and closes the file (an
  open handle would block `os.replace` on Windows) and checks the load
  fingerprint `(st_ino, st_mtime_ns, st_size)` (`pdf_handler.file_stat`);
  a mismatch raises `StaleSource`. `read` also bounds the range to the
  file and caps it at `MAX_RANGE` (1 MB). `range_reply` refuses an old
  generation, calls `read`, and answers `{"stale": true}` for a changed
  file. `FIRST_CHUNK` = 256 KB.
  The snapshot goes on teardown and at the next load;
  `sweep_snapshots` clears leftovers at a session's first load.
- `doc_sync.py` (aqt-free above its Qt-glue divider): the folder-sync
  engine for open PDFs. A registry of what each reader has open
  (`open_doc`/`close_doc`, per reader instance); every open path sits on
  a `QFileSystemWatcher`, re-added after a save-over drops it. Events to
  subscribers: `changed` (an outside edit, once size and `mtime_ns` hold
  across two checks `STABLE_MS` = 150 ms apart), `moved`, `missing` and
  `back` (the last three from `pdf_drive.rescan_library_root` →
  `_tell_readers`, AFTER the new mapping is applied). Klaus's own writes are
  pinned (`pin_own_write`) and classify as `own`, never `changed`; a
  `changed` drops the stale pristine original first (under `pdf_lock`),
  so the next bake re-captures it from the edited file instead of
  reverting the edit. The
  reader answers `changed` by reloading in place, page and zoom kept,
  with "Updated from disk" (an open text box commits first); `moved` by
  re-pointing with no reload; `missing` by clearing the reader and
  closing that PDF's tab (R50) with "<name> was removed from your
  Library folder." (marks, JSON and tag kept). Klaus's own rename or
  move updates the map before the rescan sees it, so `_tell_readers`
  also re-points every open reader whose mapped path differs.
- `annotation_save.py` (aqt-free above its Qt-glue divider):
  `SavePipeline`, the ONE bake path. `request(name)` restarts a
  `DEBOUNCE_MS` = 500 ms debounce; then `bake_annotations` runs on a
  background worker, at most one per PDF (a request mid-bake sets an
  "again" flag). A main-thread post-step pins the written fingerprint in
  `doc_sync` and `library_stats.json`, removes omitted records and emits
  `saved` / `records`. A failed bake keeps the JSON as the safe copy;
  the reader toasts `SAVE_FAILED_COPY` ("Marks couldn't be saved into
  the file yet; they're kept and will retry.") and the pipeline retries
  on the next change and when `doc_sync` reports the file `back` or
  `moved`. `flush_all()` runs on `profile_will_close`; a reader flushes
  its PDF on `clear()`, `cleanup()` and before a reload from disk.
  Switching to another PDF releases without a flush — the running
  debounce still bakes it. A reader that opens a PDF whose JSON is newer
  than the file requests a bake. On `saved` and `records` every reader
  of that PDF re-reads the JSON and pushes it when it differs, so a
  second reader never writes back a stale list over the first one's
  marks; every mutating bridge handler also re-reads the JSON first
  (`PdfJsViewer._sync_marks`), closing the window before `saved`
  arrives; those re-reads use `load_annotations_strict` (None for an
  unreadable or corrupt file), so a locked or half-synced JSON never
  replaces the marks with `[]`. `save_annotations` writes atomically
  (`_atomic_write_json`) and returns whether the JSON was written: a
  failed write keeps the marks in memory, toasts `SAVE_FAILED_COPY`,
  requests no bake, and is retried by the next save. A bake whose
  working file differs from the stat recorded in `library_stats.json`
  (an outside save doc_sync has not reported yet, or one landing
  mid-bake) drops the stale pristine first; the same stat is the carry
  scan's baseline, so a save landing after the check re-bakes. The
  worker pins (`doc_sync`) and then records each bake's stat itself, so
  doc_sync never reads Klaus's own write as `changed` and the next bake
  in its "again" loop sees it as Klaus's. An UNREADABLE marks file is
  never written over: `save_annotations`, `_update_doc_keys` (atomic
  too) and the outside-mark mirror leave it alone, the bake skips it
  (no un-bake), and a viewer that opens one shows no marks, toasts
  `UNREADABLE_MARKS_COPY` once, keeps new marks in memory and merges them in
  when the file reads again. A stored number too big for a float
  (`10**400`) costs only its own value (`_finite_number`), never the
  whole load. `forget(name)` (`pdf_drive.delete_pdf`, before the readers let
  go) drops a deleted PDF's pending save and failed flag.
- `reader_tabs.py`: `ReaderTabs`, the reader's tab strip (`[＋] [tabs]
  … [page n/m]`), one per `PdfSidebar` (its `tabs` attribute). A tab
  SHOWS the Library's display name (`tab_label`: drive.json, no `.pdf`,
  `&` doubled so QTabBar shows it rather than taking a mnemonic) and
  carries the stored name in `tabData`, which is all the interface ever
  reports. It only shows names and reports `activated` / `closed` /
  `add_requested`;
  `PdfSidebar` loads documents and persists each host's tab set in
  `pdf_tabs.json` under its `host_key` (`editor`, `lecture`).
- `reader_panel.py`: `PdfSidebar`, the reader every host wraps — a
  `PdfJsViewer` (or, without QtWebEngine, the "PDF viewer is
  unavailable" label), its `ReaderTabs`, and the `doc_sync` /
  `annotation_save` wiring above; `cleanup_all_sidebars` sweeps every
  live one on profile close and quit. No toolbar "Copy page"
  button — Cmd/Ctrl-double-click a page, or right-click "Copy slide as
  image", copies it as an image; right-click also offers "Copy page text".
- `pdf_handler.py`: storage + text extraction. `user_files/{contexts,pdfs,
  pdf_originals,annotations}`, state in `pdf_tabs.json` (open tabs per host,
  last_used — all writers MERGE via `_save_tabs_file`; `placement`/
  `geom` from older builds are dropped on read). Since K-070/
  K-073 the PDF *files* live in a user-chosen **library root** (config key
  `library_root`, picked at setup or in Preferences): `library_map.json`
  maps safe basename → path relative to that root, and **`pdf_path_for` is
  the single resolution choke point** (mapped location first, legacy
  `pdfs/<safe>.pdf` fallback; tests pass `root=` explicitly to stay
  aqt-free). No retrieval consumer remains here (autocomplete/Ask, the only
  callers of its old BM25 search, are gone, and the 400-char chunker went
  with the 2026-09-15 page-level index) — what retrieval reads now is
  `load_pages` (`contexts/<safe>.json`, one string per page), which
  `page_store.ensure_records` seeds each page record's `slide_text` from.
  `bake_annotations(dir, name)` writes highlights/notes into the stored
  PDF as REAL annotations
  (vendored pypdf): pristine original captured once in `pdf_originals/`,
  every bake regenerates from pristine + full json (never incremental; empty
  json = un-bake/restore), atomic `os.replace` from a hidden
  `.<base>.pdf.<uuid>.tmp` in the Library root (an open reader reads its
  hard-link snapshot, so the swap never disturbs it). The working path
  is resolved under `pdf_lock(name)` right before the replace — the lock
  rename, move and delete share — so a rename mid-bake writes to the
  new path, and a bake never recreates a mapped file that is gone. A
  file whose stat changed since the carry scan read it (an outside save
  mid-bake) is re-baked once from the new file, never overwritten. The
  pristine is captured with every Klaus mark (any subtype) and every
  outside highlight/text box stripped, so a re-capture after an outside
  edit never doubles Klaus marks. The first rescan of a session sweeps
  bake tmps over an hour old from the root (`sweep_stranded_tmps`).
  Scheduled only through `annotation_save.SavePipeline` (500 ms
  debounce, one worker per PDF).
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
  **hand-drawn k** (Pouya's logo, 2026-10-01, replacing the K-270
  impossible star; the source of record is
  `docs/reference/brand/klaus-logo.svg`, a blue tile with a white k):
  `logo_svg(fill)` draws ONLY the k, never the tile — ONE FILLED
  `fill-rule="evenodd"` path (`_LOGO_PATH`, the file's white path
  verbatim, pinned equal by `tests/test_top_bar.py`) in a 26×26 box on
  `LOGO_VIEWBOX`, the file's 1254 box cropped to the k plus ~4% so it
  fills the seat; `logo_html()` fills it
  `var(--klaus-accent, currentColor)`, never stroked, click → Klaus Preferences via `klausmate:settings` on
  `webview_did_receive_js_message`; the same hook also routes the
  on-screen gradient editor's `klausmate:bggrad` drag-end messages
  into `background.grad_edit_event`). Because it only restyles, Anki's links
  and AnkiHub's toolbar items all keep working and inherit the look via
  the shared `.hitem` class. **Anki draws the toolbar in
  `finish_ui_setup()`, BEFORE any profile opens** — so the accent a
  profile saved reaches the bar only via `_on_profile_open_redraw`
  (profile_did_open, one-tick-deferred toolbar.draw); without it the
  k launched default-blue on every restart. `refresh()` is
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
  gated: the k (fills `var(--klaus-accent, currentColor)` so it
  survives on the stock bar), the heatmap, every functional injection,
  and Klaus's own windows. In native mode the deck screen draws NO
  Klaus widgets: the heatmap's two injections are gated too (at the
  injections, never inside `enabled()` — the same round-trip rule as
  `resolve()` above: a reader whose value any UI seeds from and writes
  back must never be gated, or it persists a `heatmap_enabled` False
  the user never chose). The k is
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
- **The Library is the `!Library` tag branch in Browse's sidebar**
  (K-306..K-309, 2026-09-28/30; spec
  [library-in-browse](docs/superpowers/specs/2026-09-28-library-in-browse-design.md)).
  The Library window (`DriveWindow`), the embedded main-window screen
  (`library_tab.py`), its tree styling (`library_explorer.py`,
  `theme.library_qss`), the top-bar Library link and the map button were
  all deleted in K-308 — do not resurrect them; `pdf_map`/`pdf_graph`
  remain with no entry point for now.
  - `library_sidebar.py`: `on_build_tree` claims the sidebar's TAGS
    stage (builds Anki's own `_tag_tree`, there is no after-hook) and
    lifts the `!Library` branch into its OWN first section with
    library/folder/PDF icons (`web/library-*.svg`, black outlines Anki
    inverts at night) — its rows stay TAG items, so Anki's rename, drag,
    delete and search still work. Also a delegate that DRAWS a
    Library tag by its real name (tags cannot hold spaces; EditRole and
    search still use the tag), a right-aligned muted retention % on EVERY
    tag (mean FSRS recall of ALL its cards, suspended included and
    never-studied ones at 0% — recall times coverage, Pouya's call
    2026-09-30; parents include children; computed in a QueryOp only
    while a Browse is open), warning icons with `helpEvent` tooltips (not embedded / stale /
    indexing, from `retention.index_status` + `index_queue.pending_names`;
    stale includes a text file changed since indexing), excluded rows
    dimmed with "Excluded from the index" and no warning icon,
    the right-click menus (`browser_sidebar_will_show_context_menu`), a
    click that loads the PDF into Browse's PDF panel only when that panel
    is already showing, a drop filter for PDF files, and two actions on
    Anki's own `sidebar.toolbar` beside its search box (`header_actions`:
    ⟳ "Index New and Changed PDFs" → `index_queue.refresh`, +PDF "Import
    PDFs…"; the Add tab's tree puts the same two beside its filter). No
    footer. Right-click "Exclude from Index" / "Include in Index" on a
    PDF or folder (`library_actions.exclude`/`include`): the exclusion
    lives in `drive.json` (`drive_store.set_excluded`, a folder covers its
    subfolders and later imports), excluding DELETES the covered PDFs'
    index dirs after a window-modal confirm when any exist, and card tags
    are never touched (manual indexing, 2026-10-01, spec
    [manual-indexing](docs/superpowers/specs/2026-10-01-manual-indexing-design.md)).
  - `library_actions.py`: the window-free actions those menus call; every
    dialog an instance with `open()`. Import COPIES files into the library
    root and lets the background scan read and import them; ⟳ indexes them.
  - `pdf_drive.py` is now only the disk half: `start_library_rescan`
    (QueryOp without the collection → `pdf_handler.prepare_rescan` reads and
    OCRs new files; applied on main by `rescan_library_root`), renamed files
    matched by CONTENT (`plan_rescan` fingerprints: page count + first three
    pages — a bulk Finder rename once froze the Library for a week), the
    filesystem watcher, `delete_pdf`/`delete_folder` (files go to the
    Trash), `apply_folder_change`, and `refresh_open_library` (Preferences
    calls it). PDFs the scan imports get page records and a tag
    (`_after_ingest`), like every other import; nothing is indexed until ⟳.
- `tag_sync.py`: per-PDF collection tags. THE INVARIANT: every indexed PDF
  owns exactly one tag `!Library::<folder path, / → ::>::<leaf>` (leaf =
  display name minus extension, tag-sanitized), whose members are exactly
  the notes at/above that PDF's sensitivity threshold. Forward direction
  (index/re-index creates + renames tags, K-053) and reverse (a rename in
  Anki's tag sidebar renames the PDF, K-054 — INFERENCE from a
  before/after tag diff, never a real event). Since K-306
  `plan_library_sync` also registers zero-note tags (`set_collapsed`) so
  every PDF and empty folder shows, follows drags and folder renames onto
  disk, and turns a deleted tag with matched cards into a "delete the PDF
  too?" prompt; it runs on profile open AND after every op that changed
  tags (`on_operation_did_execute`, debounced). Tag presence compares
  casefolded, as Anki does. Reserved
  leaves `Curating`/`Curated`/`Matching`/**`Doubtful`** are never
  touched. Historical note, 2026-09-19: D2 removed doubtful-membership
  computation while preserving reserved historical names and existing tags.
- `retention.py`: per-PDF retention/study-priority score shown in the
  Library — embed the PDF's PAGES (`pdf_index.py`, one vector each) →
  score every indexed note against them (max cosine, cached in
  `matches.json`, which since MATCHES_VERSION 2 also stores each note's
  best `"pages"` entry) → pull FSRS retrievability for matched cards →
  aggregate. `do_build` embeds `page_store.page_texts` and REUSES any
  page whose `text_hash` is unchanged (the `card_index` hash rule), so a
  page whose text changed re-embeds alone and a cancelled build
  resumes from `embedded_rows`; an empty page gets a zero vector and can
  never win `best_page`. The old
  `!Library::Matching` preview tag was retired in K-055 — "Show matches
  in Browse" now hops to the per-PDF `tag_sync` tag. Since K-118
  every priority row also carries `note_count`/`card_count`/
  `suspended_count` (matched notes at/above threshold; their cards
  split viewable vs queue −1 via ONE chunked `card_queues` batch —
  900/chunk for SQLite's parameter cap), the return dict adds
  `card_queues` beside `card_r` for col-free re-aggregation, and a
  guarded `retention_history.record_rows` snapshot fires right before
  return. D2 removed the judge filter; scores and counts use matched cards.
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
  swallow upstream is harmless) toggles a panel hosting a standalone
  `PdfSidebar`. **Not a dock since 2026-10-01**: an mw `QDockWidget` runs
  the full window height beside the top bar and the bottom row and
  pushed the whole window aside, so `_install_beside_reviewer` moves
  whatever holds `mw.web` in `mw.mainLayout` (the webview, or AMBOSS's
  and AnkiHub's wrapping splitter) into a horizontal `QSplitter`
  (`REVIEW_SPLIT`) in the same layout slot, with the panel beside it,
  once per session; the panel takes its saved width a tick after show
  (`_size_panel`). Once open it follows
  `reviewer_did_show_question`: note tags → `!Library` candidates
  (prefs.json inverted, casefolded; the tag IS the membership verdict
  — deliberately NO threshold re-gating, `MATCH_FLOOR` sanity only) →
  one seek-read card vector (`card_index.load_row_map`/`read_vector`)
  → `pdf_index.best_page` argmax → that page's stored 1-based number;
  results cached per (nid, tags), revalidated by file stamps. No match
  shows exactly "No lecture page available for this card." pdfjs
  first-load jumps ride a generation-stamped retry ladder (the page
  posts `count:` before its divs exist); leaving review hides the panel
  (mw.web is shared across states); open-state + width persist under
  `pdf_tabs.json`'s `lecture_view` key; EVERY teardown path runs
  `sidebar.cleanup()` (K-095). Config `lecture_view_reopen`. Shortcut
  "l" via `state_shortcuts_will_change` (collision-scanned) + a
  reviewer context-menu toggle; never activateWindow — answer keys
  stay on the reviewer. The panel has no chrome (K-257's Record button
  was removed with recording in K-314).
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
  centroids. Since K-174, stars are hard, square-capped `drawPoints`
  — one C++ call per depth band, antialiasing off — and a focused
  PDF's spokes are crisp, batched 1px lines. The constellation itself
  is `constellation_links` in mode `"constellation"`: a Prim
  spanning-tree backbone (connected by construction, exempt from
  `LINK_MAX`) unioned with kNN density, computed ONCE per canvas and
  deterministic (`link_seed`) — O(n²) on the sampled cloud, ~25 ms at
  520 points and quadratic from there, so the real ceiling today is
  `SAMPLE_NOTES + SAMPLE_PER_PDF × PDFs` until K-199 lands a linear
  replacement. **Since 2026-09-01 the map is a DIM constellation on
  the panel's own ground**: it reads the HOST palette — no
  always-dark special case, no card, no vignette, no border
  (`c = dict(host, bg=host["chrome"])`) — rests at `DIM_LIT` and
  ramps to 1.0 under the pointer (`lit` pyqtProperty, `LIT_MS`,
  quantised into the pen-cache key), lights only the SELECTED PDF's
  ring, core and spokes plus its bare name — no plate, no halo
  (`node_lines` is the display name alone; the hover-only preview is
  `text_muted` and dims with the rest of the field) — and SWAYS
  `±SWAY_AMP` (0.28 rad) over `SWAY_PERIOD_MS` at `CAM_DISTANCE` 2.0
  instead of turning, never crossing ±90° so `band_order`'s flip
  never fires (`sweep_bounds` frames the swept arc, and K-201's pins
  in `scripts/k201_gate.py` make that framing load-bearing). Frame
  time: 1.1–1.4 ms median at 1100×660, floor 4 ms. The light palette
  is now an inverted, faint field on white, not a forced night sky.
  Labels show for the focused or hovered PDF only (K-138 —
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
  tooltip omits the line. The map uses the same matched-card retention
  calculation as the Library after D2 removed judge filtering.
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
- `pdf_index.py` (aqt-free): persistent embedding index over one PDF,
  `card_index.py`'s sibling for the PDF side. **v2 (2026-09-15) is ONE
  VECTOR PER PAGE**: `PdfIndex.pages` is `(page_1based, text_hash)` per
  row, `INDEX_VERSION = 2` so every v1 manifest reads as absent and
  rebuilds (the K-167 rule), and `best_page(index, vec) -> (page,
  score)` replaces `best_chunk`. The 400-char chunker, `chunk_pages`,
  `stride_sample`, `chunk_text_at`, `DEFAULT_MAX_CHUNKS` and the
  `pdf_index_max_chunks` key are gone with it, as is `pdf_match_agg` —
  with one vector per page a note's score simply IS its best-matching
  page, so `retention.match_scores` takes no aggregation argument at
  all (only `floor`), and the row text comes from
  `page_store.page_texts` (slide text), never from a
  chunker here.
- `page_store.py` (aqt-free above its divider; 2026-09-15, spec D2):
  **the shared page record for indexing**; one JSON record per
  (PDF, page) at `user_files/pages/<safe>/<digest12>/<page:04d>.json`,
  holding the slide's own `slide_text`. `combined_text` is that text
  (transcript `segments` were removed with recording in K-314;
  `load_record` drops a legacy key); `text_hash` (blake2b, 16 hex) over
  it is what `pdf_index` stores per row and what decides a re-embed.
  `ensure_records` seeds `slide_text` from `pdf_handler.load_pages` and
  is idempotent. `digest12` is a SHA-256
  over the file's path, size and mtime (moved here from the deleted
  `page_ocr.py`), so a REPLACED file gets a fresh directory rather than
  silently inheriting another PDF's pages. Identity is settled in ONE
  place, `document_identity` (K-268, Copilot on PR #3): `text_digest`
  (the page text) for a document with any text, and a SHA-256 of the
  PRISTINE ORIGINAL's bytes (`pdf_originals/<base>.pdf`, captured by
  `pdf_handler`'s own capture if no bake has made one yet) for a
  TEXT-LESS one, whose pages say nothing and would otherwise hash on
  page count alone and let two scans of equal length share a
  directory; a bake never writes that file, so the digest survives
  bakes and moves and still separates two scans, and any failure
  falls back to `text_digest` with one log line. Writes are atomic
  (tmp + `os.replace`); a corrupt record reads as empty and is logged.
  `render_page_png` (QtPdf, 1400px long edge) is the one Qt import, below
  the divider.
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
- `image_occlusion/`: Image Occlusion Enhanced v1.4.0 (AGPL-3, every
  copyright header kept; provenance and Klaus's edits in `UPSTREAM.md`),
  ported to Klaus rules. `setup()` (called once from `__init__`) registers
  IOE's hooks, "Image Occlusion Options…" in Tools and "Image Occlusion
  Help…" in Help, never `setConfigAction` (Klaus keeps its Config button).
  **Conflict guard**: with add-on `1374772155` installed AND enabled
  (`allAddons()` first: `isEnabled` is True for a missing folder) it
  registers nothing and shows one tooltip a second later. `occlude(editor,
  image_path, initial_svg=None)` opens svg-edit; `initial_svg` loads as
  the starting masks in add mode. Note type, mask SVGs and the `imgocc`
  config stay byte-compatible with IOE. svg-edit loads by file URL; only
  `image_occlusion/web/` and `image_occlusion/excalidraw/` are web exports.
  **Excalidraw diagrams** (Image Occlusion 3/3): "Draw a diagram…"
  (`occlude(..., draw=True)`) opens the same editor on a blank PNG with a
  third tab, Draw (`excal_tab.DrawTab`, the offline bundle in
  `excalidraw/`); "Use drawing" makes the export (PNG, 2×, 20 px padding)
  the image and each text label one mask (`excal_masks.label_rects`).
  Once IOE has added or updated the notes, the scene is saved in media as
  `_<image media name>.excalidraw` (JSON plus a `klaus` block holding the
  export origin), under the name Anki RETURNED; the `_` keeps Check Media
  from listing it as unused. **Re-edit**: edit mode shows Draw (the Masks
  Editor stays current) only when that file reads (`excal_tab.read_diagram`).
  A Use drawing on top of an earlier drawing reads svg-edit's masks back and
  `remap_masks` carries them over: the best mask with IoU >= 0.8 on an old
  label's box follows its label and keeps its id (so the note updates in
  place); every other mask shifts with the scene origin and goes once wholly
  outside the new image. Only a label NEW to the scene gets a new mask (id
  `klaus-new-<n>`, which ngen reads as a new card); one the old scene had
  keeps what the user left, a resized mask stays theirs and a deleted one
  stays deleted (R22). The PNG gets a new media name; the old image and its
  scene stay for notes not yet updated.
- `web/copilot.js`: injected into editor webviews; shadow-DOM-aware
  (`composedPath`). Ghost text and Ask are gone — this file now only tracks
  field focus (for PDF page-insert targeting) and the image-crop dblclick
  trigger.
- **Semantic matching stack**: per-PDF `!Library` tags and retention
  scores use cosine matching after D2 removed the reasoning judge.
  - `embeddings.py` (aqt-free): local Ollama embeddings with normalized vectors.
    `index_signature`/`signature_matches` remain the cache identity check.
  - `ollama_client.py`: local-only endpoint validation, embedding requests,
    model inventory, streaming pull with explicit terminal success, and deletion.
  - `ollama_runtime.py` and `ollama_setup.py`: installed runtime discovery,
    authorized installation/update, archive validation and owned server lifecycle.
    Profile-open readiness starts installed runtimes without downloading. Preferences
    operations can finish after dialog close; profile close cancels runtime work.
    Automatic port relocation uses a profile-fenced endpoint-only compare-and-set;
    newer saved endpoint edits win, and unsaved endpoint/model choices stay Save-owned.

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
    `retention.py` imports it at module top for `index_dir()` (the card
    index folder under `settings.user_files()`), `_fail` and `_busy`, the ONE re-entrancy token every
    embedding phase holds; manage_models, tag_sync and pdf_map read it
    too. Gone with K-146: `run_curation`, `_preview_in_browse`,
    `last_run`, `suggest_deck_name`, `_escape_search` (and long before
    them, the `!Library::Curating` temp tag K-064 retired — CLAUDE.md
    and config.md both went on documenting it until K-146).
  - `index_queue.py` (aqt-free above its "aqt glue" divider; K-152): the
    **index runner**: four phases, `curation.ensure_index` →
    `retention.ensure_pdf_index` → `ensure_matches` →
    `tag_sync.sync_after_matches`. Cancellation spans the chain; each
    embedding phase respects `curation._busy`. D2 removed the judge phase,
    its prompt and progress state. It exists
    because that chain was a METHOD on the Library window
    (`DriveWindow._on_embed`) and a PDF added from the deck screen has
    no Library window. **Indexing is manual (2026-10-01)**: `refresh(parent)`,
    the Library's ⟳, is the only trigger. It queues every PDF that
    `needs_indexing` (missing, partial, older `INDEX_VERSION`, another
    embedding signature, another source signature) or has a stale match
    cache, minus excluded (`drive_store`) and already-queued ones, deletes
    index dirs excluded PDFs still have, and tooltips the count. No import,
    profile open, rescan or model change starts a job (the
    `auto_index_on_add` key, `on_pdf_imported`, `resume_unindexed`, the
    profile-open v2 sweep / re-match and `offer_model_sweep` are gone). A
    PDF excluded while its own job runs loses the index that job wrote
    (`_drop_if_excluded`). **`curation._busy` REFUSES concurrent runs** —
    right for a double-clicked button, wrong for ten dropped PDFs — so
    jobs queue here (dupes collapse, FIFO) and the runner WAITS on that
    token (`_busy_elsewhere`, bounded poll) rather than racing
    Preferences' Index Now, which still calls `ensure_index` directly
    for its own progress bar. Feedback is the shippable part: ONE
    `RunnerState` snapshot is published to every listener and rendered
    by ONE pure `status_line`, which `_report_task` turns into the status
    bar's `index` task (✕ = `cancel_all`) — the old `_StatusDock` and the
    Library footer's status line were removed with the status bar. No profile means no run. Local
    readiness replaces provider-key gates.
    Report readiness failures rather than silently dropping work. A PDF deleted
    before OR during its turn is skipped silently, and a deletion error
    never fails the batch behind it. Cancel bumps `_seq`, which is what
    stops `after_matches` tagging on the PARTIAL ranking
    `ensure_matches` hands back. **Closing the Library no longer
    cancels indexing** (the job may have been started from the deck
    screen). The Preferences `index_sweep` effect only tooltips "Press ⟳
    in the Library to re-index for the new model."; ⟳ then finds every
    index under the old signature. When no PDF needs work but the card
    index needs a from-scratch rebuild, ⟳ queues one `JOB_CARDS`; a PDF
    job's phase one still asks first (K-237, Skip default).
    Signature comparison is ALWAYS `embeddings.signature_matches`,
    never a tuple `==`: a hand-spelled one reads every cache as stale
    and needlessly re-embeds the collection (the exact bug
    eight call sites shipped when the signature grew a third element).
  - `pdf_drop.py` (was `deck_curate.py` until K-151, a misnomer once it
    curated nothing): the deck-screen **PDF import** surface — the
    `MainWebView.dropEvent` wrap (the only thing stopping Anki's own
    importer choking on a dropped PDF) and an **Add to Library** button in
    the deck list's and overview's bottom rows (`add_library_link` on
    `DeckBrowser.drawLinks`, `on_overview_will_render_bottom`), shown
    in Anki's own row beside its buttons, opening the file picker. The dashed drop
    square it replaced is gone (on request). K-146 removed the two
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
    the top bar's k opens it too; Appearance also carries Anki's
    own Follow-System/Light/Dark switch, applied on Save through
    `mw.set_theme` — the one row writing an Anki preference).
    **NON-MODAL since 2026-08-30**
    (`dlg.show()`, NEVER exec() — the 2026-08-26 segfault was
    app-modal exec's nested loop): a live control panel used beside
    the main window while appearance edits preview on it. `_OPEN_DLG`
    keeps it a singleton (a second k click fronts it);
    `profile_will_close` rejects it before the collection goes away. **SynapsePro settings shell
    (K-106 — replaced the K-105 card grid; built from a screenshot of
    SynapsePro 1.5.x, the vendored source only has their older grid)**:
    a fixed `SettingsSidebar` (k-logo pixmap: `QSvgRenderer` over
    `top_bar.logo_svg(<blue_accent hex>)`, the toolbar's own SVG, at the
    label's own `devicePixelRatioF()`, repainted on an accent save — app name + manifest `human_version`, `SettingsNav` list (ONE QListWidget — never
    per-page buttons; three pill-mush rounds proved per-button polish
    timing unfixable) with a row per page) beside a QStackedWidget of pages.
    Each page = `PageTitle`/`PageSubtitle` over ONE rounded `CardFrame`
    group; every simple setting is a `_row()` — bold `SettingName` +
    muted `SettingDesc` left, control right, `RowSeparator` hairlines
    between. Sidebar display order comes from `_finish_nav(...)`,
    decoupled from widget build order; the sidebar header is the
    k logo beside the Excalifont wordmark, over a search field that filters
    setting rows across pages (`_apply_search`; rows carry
    `klaus_search` haystacks, structural hiding via `klaus_hidden` —
    how a background row hides whole for the mode that doesn't use it —
    always beats a search
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
    the shared row-visibility pattern; design off hides the whole block).
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
    General and Appearance remain alongside Local models: Ollama runtime
    management, free-text embedding model and External clients configuration. The embedded Assistant page is removed.
    The `index_sweep` effect tooltips where to re-index (indexing is manual).
    **Preferences are a state machine (2026-10-01, spec
    [prefs-state](docs/superpowers/specs/2026-09-30-prefs-state-design.md))**:
    `prefs_state.PrefsState` (aqt-free) holds EVERY value the dialog
    edits — General, Local models, and Appearance (the two background
    specs as values, the accent pair, the design gate, `anki_theme` as a
    pseudo-key seeded from `mw.pm.theme()`). Widgets are `_Binding`
    adapters (a signal is `state.set`, `paint()` writes the state back
    under the class-wide `syncing` scope, so painting never counts as an
    edit); the Appearance handlers copy-edit-set a spec through
    `_edit_spec`. **Dirty is a fact** (`state.dirty` = pending values
    exist), so a keyboard-only slider edit lights Save. `save_all()` is
    `state.commit()`: ONE `settings.patch` of the changed keys, then the
    effects in fixed order — `index_sweep` (the "Press ⟳" tooltip),
    `threshold_changed` (the tuned-PDFs prompt),
    `anki_theme` (`mw.set_theme`),
    `appearance` (live apply, then drop the preview). Appearance's
    **Bar size** slider (`bar_scale`, after Theme; a % readout, a caption
    naming Anki's UI size with a link to Anki's Preferences) is an
    appearance key, so it previews live. Discard is
    `state.discard()` + `paint_all()`. Endpoint relocation is
    `state.reseed` (a stored value moved; not an edit); a model pick is
    `state.set`. The live preview reads `flatten_appearance(state.view())`
    plus the stored-config keys it always carried. Adding a preference =
    one key in `prefs_state.KEYS` + one `_Binding`; a forgotten binding
    costs a missing edit, never a silently unsaved setting.
  - `setup_flow.py`: first-run library setup and profile-open local readiness.
    Preserve one clear nudge. Profile open starts no indexing.
- **External endpoint and context**: as of 2026-09-19, the embedded dock, host
  and sessions are removed. `scripts/mcp_stdio_bridge.py` is a standalone stdlib
  process launched by an external client with Python 3.9+. It reads private
  `user_files/mcp_connection.json` for each request and forwards to local HTTP.
  Preferences copies token-free absolute-path configuration, never edits another
  application's config. `current_page` returns slide text and optional
  PNG data. Collection writes still require Anki approval. External providers may
  receive requested context. POSIX discovery mode 0600 is tested; native Windows
  ACL privacy, separate-process lifecycle coordination and live Desktop remain limits.

  - `anki_endpoint.py` (aqt-free above its "aqt glue" divider): Klaus's
    own localhost AnkiConnect-compatible server (`/`) plus MCP-over-HTTP
    (`/mcp`), from ONE shared `ACTIONS` registry so the two routes
    cannot drift — no dependency on the separate AnkiConnect add-on.
    Bound to `127.0.0.1:0` (ephemeral port), a fresh 32-byte hex token
    required on every request (`X-Klaus-Token`), any `Origin` header
    refused outright (a browser page must never drive the collection),
    bodies capped at 4 MB — all checked before the body is even read.
    **Every early return in the request handler closes the connection**
    (`close_connection = True`) rather than trusting HTTP/1.1 keep-alive
    to reuse a socket whose unread bytes are still sitting in the pipe:
    two review rounds found this the hard way — draining an unbounded,
    caller-declared `Content-Length` before any auth check is its own
    DoS (a ~50 MB claim with 2 bytes actually sent never returned), so
    the two UNAUTHENTICATED branches (bad token, browser `Origin`) close
    without draining anything at all, while the one branch that still
    drains (413, body too large) may, because it already required a
    valid token, and caps the drain at `BODY_CAP`; the socket's own read
    is separately bounded (`settimeout(READ_TIMEOUT_S)` in `setup()`) so
    a caller that declares a huge length and then stalls cannot hang the
    thread forever either way. Writes never touch the collection without
    a plain-text approval preview: the dialog is **window-modal `open()`,
    never `exec()`** (K-114), built and shown on the main thread while
    the HTTP thread blocks on a `threading.Event` (Rulings R1 — the
    endpoint owns approval, not `anki_tools._confirm_write_dialog`,
    whose own `exec()` cannot be called off the main thread anyway).
    `addNotes` tries each note independently so one bad note (unknown
    deck/model/field) can't sink the notes on either side of it,
    returning `list[noteId or null]` exactly as AnkiConnect's own
    contract does. The duplicate check in that preview is Anki's own
    text search over the front's first eight words (R2) — not the
    embedding ranker `card_forge` uses, which would be a paid network
    call inside a modal dialog, and **the dialog's DEFAULT button is
    Cancel** — it is window-modal on `mw` and takes keyboard focus the
    instant it opens, so with Approve as the default (QDialogButtonBox's
    own choice) a user typing in the assistant input who pressed Enter
    as a card proposal landed had approved a write they never read.
    Agent writes (`X-Klaus-Agent: 1`) tag
    added notes `klaus::assistant` + `klaus::from::<pdf_safe>` +
    `klaus::page::<n>` — **never**
    the PDF's `!Library` tag (R3): that tag is `tag_sync`'s own
    membership invariant, and a hand-applied one would violate it; the
    next index pass tags it for real if the card actually matches.
    `addNote` on the agent path also requires
    `params.note.options.sourcePage` — a missing source page is a clean
    error, never a silent add. Reuses `anki_tools`'s existing
    `_HANDLERS`/`TOOL_SPECS` UNMODIFIED for `create_note`/`update_note`/
    `search_notes`/`search_lecture_pdfs` rather than a second
    implementation — which is exactly why **`klausSearchNotes` is
    LEXICAL, not semantic**: `_h_search_notes` is `col.find_notes`, so
    its description must say "Anki search syntax" and send the model to
    `search_lecture_pdfs` for meaning. Advertising it as semantic had
    the model asking natural-language questions of a substring-AND
    search and reading the empty result as "no notes on this"; a real
    semantic note search is K-207. Every `notifications/*` method is a
    JSON-RPC notification (202, no body) — `notifications/cancelled` is
    what an MCP client sends when it abandons a `tools/call` blocked on
    the approval dialog, and replying to it is forbidden.
  - `viewer_context.py` (aqt-free): a pure dict registry of every live
    `PdfSidebar` (the Library's, Browse's editor pane, the Lecture
    dock) — `report_document`/`report_page`/`report_selection` update
    state, `activate`/`forget` track focus. **`current()` is the LAST
    ACTIVATED viewer that still holds a document**, not the most
    recently opened one or the one under the mouse — an activation-order
    list, most recent last, filtered to viewers that still have a
    document — so a background PDF window that never regained focus
    can't replace the active context from the one the user is
    actually looking at. `subscribe` callbacks run synchronously on the
    caller's thread; a raising subscriber is logged, never left to break
    the reporter.
  - `current_view` in `anki_endpoint.py` already consumes `viewer_context`
    for PDF/page/selection metadata. `current_page` also reads
    page text and PNG content through `page_store.py`.
    Keep these retained modules; do not restore assistant session storage.
- Deleted (2026-08, 2026-09-02 — do not resurrect the language): `claude_api.py`,
  `settings_ui.py`, `chat_dock.py` (the "Klaus panel"),
  `web/search.html|css|js`. The first `single_window.py` (2026-08-25, the
  panes-in-one-window mode from K-059..K-062) was removed as too buggy:
  dark webview panes survived five rework rounds, K-090..K-094;
  `settings._scrub_legacy` still scrubs its `single_window_mode` key. It is
  BACK since 2026-09-30 (Pouya's call) with a different mechanism — see
  the `single_window.py` bullet. **What stays banned is re-parenting a
  window Anki built as a top-level**: a QtWebEngine view presents through
  the window it was born under, so a moved editor is a black pane.
  `workspace.py` (K-102, the sidebar-shell follow-up) lasted one day —
  deleted 2026-08-25 as the wrong shape; the unified-UI ask is served
  by `top_bar.py`'s toolbar restyle instead (`settings._scrub_legacy`
  scrubs `workspace_enabled`). Config lives in `klausmate/config.json` +
  Anki's addon config (`meta.json`) + `config.md`. `settings.migrate()`
  (profile_did_open) cleans up legacy `chat_*`/`claude_*` keys left from the
  deleted Claude-Ask feature; keep it until users have upgraded past it.
  Deleted again, 2026-09-02, for the same "converged, then reversed"
  reason described above: `llm_client.py` (`a494f2d` — the
  `claude_api.py`-derived streaming client didn't survive its own
  reshaping either), `entitlement.py` (`f1b330b`), `podcast.py`
  (`026eb36`), `assistant_session.py` (`1fcdba2`), and the Library's
  short-lived third-pane assistant-panel module (`fed3a33`, guarded
  `451a753`) that the later dock replaced (itself removed in D3).
  `card_forge.py` (`120293f`) and `anki_tools.py` (`e1c023c`) survive
  from the same plan; the retained endpoint still uses `anki_tools`.
  `settings.LEGACY_KEYS_DROPPED` (moved from `__init__.py` on 2026-09-30) scrubs
  `assistant_api_key`/`assistant_backend`/`assistant_token` (retired
  2026-09-01): there was never a separate assistant credential to keep;
  D3 removed the subsequent Claude Code host as well.
  Historical note, 2026-09-15: API-first removed `page_ocr.py` and the
  Ollama client/runtime/setup modules, and retired local-runtime config.
  The 2026-09-19 implementation restores managed Ollama and migrates its
  keys back. OCR and Voyage remain out of scope. D1-D3 retired Plus, judge
  and assistant settings; D4 removed the final cloud client and cost module.
  Current defaults are in `config.json`; preserve migration coverage.
  Historical note, 2026-10-01 (PDF reader 5/5): the native renderer is
  gone — `pdf_viewer.py` (`PdfViewer` on QPdfView, with its own find bar,
  thumbnails and selection overlay), the `pdf_renderer` key (now in
  `settings.LEGACY_KEYS_DROPPED`), Preferences' renderer switch with its
  `renderer_restart` effect, and `pdfjs_viewer.renderer_from_config`.
  `PdfSidebar` lives in `reader_panel.py`; there is no native fallback.

## Hard-won gotchas (each cost real debugging — don't relearn them)

- **A styled QTreeView selection is TWO paint regions** — the item AND
  the branch (disclosure-arrow) cell, plus the style's own selection
  underlay. Style only `::item:selected` and Qt paints the rest in
  palette-highlight dark blue: fragments at the row edge, and corner
  peek-through if the item is rounded. Full fix: `::branch:{hover,
  selected}` rules + `selection-background-color: transparent` + keep
  square geometry (see `theme.sidebar_tree_qss`).
- **Host-window shortcut ambiguity**: widget-scoped QShortcuts that collide
  with Browse/AddCards QActions (⌘F, ⌘G, ⌘⌥G, ⇧⌘G, ⇧⌘H) become *dead keys*.
  The viewer claims them via `QEvent.ShortcutOverride` + KeyPress handling.
- **Reparenting mid-mouse-gesture kills Cocoa tracking** — never
  `setParent` into a new native window while a button is down. Tear-off =
  float on threshold + `startSystemMove()` (which *lies* — returns True even
  when the drag dies; a 300ms/40px watchdog detects that and falls back).
  Since 2026-09-05 Klaus reparents nothing mid-gesture itself; `QDockWidget`
  does its own moving.
- **`QSplitter.setOrientation` transposes its sizePolicy** — re-assert the
  wrapped pane's policy after every orientation change or the host layout's
  stretch hints are lost (blank-space bug in the Add window).
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
- **pdfium (QtPdf) renders annotations only WITH `RenderFlag.Annotations`**
  — `page_store.render_page_png` (the external page tool's image and the
  garbled-page OCR) renders without it, so its images carry no baked
  marks. The bake's coordinate flip from the records' top-left page
  points is `y_pdf = page_mediabox_height − (y + h)` (verified
  pixel-exact).
- **`embeddings.provider_from_config` takes a config GETTER, not a dict**
  (`OllamaEmbeddings` calls it per request). The settings seam (d8a7025)
  deleted curation's `_cfg` helper but left `provider_from_config(_cfg)`
  in `_embed_plan`: every card-index phase with anything to embed died
  with a NameError, `index_queue._fail` dropped the whole queue, and no
  PDF embedded for a day; the first fix passed `settings.read()` (a dict)
  and failed the same way one call later. The index_queue tests fake
  curation entirely, so neither showed up there:
  `tests/test_curation_embed.py` runs the real `_embed_plan`. After a
  refactor that deletes helpers, run `uvx pyflakes klausmate/*.py | grep
  "undefined name"`.
- **A GUI-launched app inherits a minimal PATH**: binary discovery must
  account for GUI launch environments. The removed `agent_host.find_claude`
  used `shutil.which`, a bounded login-shell lookup, then known paths.
- **Historical Claude Code permission lesson (2026-09-02):** the removed
  host needed `ToolSearch` in its allowed tools to expose MCP schemas,
  and static allow/deny lists provided its actual permission boundary.
  Its `control_request` callback alone did not enforce that boundary.
  For the external bridge, preserve endpoint authentication and
  explicit write approvals; client-side permissions are additional gates.

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
  fallbacks (`PDFJS_AVAILABLE` pattern); log with
  `print("[klausmate] ...")`; tooltips only for capture-style actions
  (selection/copy is silent, Preview-style).
- pypdf is vendored in `klausmate/vendor/` (6.11.0, has
  `pypdf.annotations`); no other bundled Python dependencies or native
  Python extensions. Ollama is a separate native executable.
- The embedding model stays free-text with local model inventory and pull
  progress in Preferences. Ollama is the single provider. Defaults live in
  `config.json` and, for embeddings, `embeddings.DEFAULT_MODELS`.
