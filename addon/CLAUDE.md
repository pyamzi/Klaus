# CLAUDE.md — Addons repo / Klaus (klausmate)

The real project here is **`klausmate/`** — "Klaus", an Anki addon for a
lecture-PDF library with per-PDF retention scoring, semantic card↔PDF
matching (indexing a PDF tags every card it covers), a native
PDF viewer with highlights/sticky notes, and image cropping. Around it:
`tests/` (headless logic tests), `board/` + `context/` (the multi-agent
kanban board — see below), `References/` and `scripts/` (vendored
reference repos + packaging), and `AGENTS.md` (deep architecture guide:
hooks registered, JS↔Python protocol, config keys, packaging).
`PRODUCT.md` says what Klaus is for; `DESIGN.md` is the design language —
tokens, surfaces, the "Quiet Clinic" brief — **and its star section is
stale**: six passages still describe a hand-drawn point-down pentagram and
name `top_bar._STAR_PATH`, but K-270 replaced that on 2026-09-17 with the
impossible star's five filled paths (`_STAR_PATHS`, sourced from
`klausmate/web/klaus-logo.svg`). Trust the code over that section until it
is rewritten.

Klaus was **embeddings-only** from 2026-08 to 2026-09-01: its one AI
capability was semantic search, which defaulted then to the **Voyage**
cloud embedding API, with a local Ollama alternative and OpenAI as a
second cloud option — history as of 2026-09-15, when the API-first turn
below cut that to OpenAI alone. Autocomplete, ⌘K Ask, the Klaus chat
panel, the Settings dialog, and the original Claude/Anthropic
integration were all deleted then — if you find docs, comments, or
instincts that assume THOSE surfaces still exist, they're stale. See
AGENTS.md's "What used to be here".

**Klaus grew a second AI capability starting 2026-09-01** (Pouya, that
evening: "Wrap the Claude Code CLI, exactly like Claudian"), landing as
six new modules overnight into 2026-09-02. One assistant, docked on
Anki's main window (`assistant_dock.py`, shortcut `Ctrl+Shift+K`), whose
engine is the **Claude Code CLI** running as a child process
(`agent_host.py`) — no loop of Klaus's own, no assistant API key in
Klaus's config, the user's own `claude` login and subscription pay for
it. Its context
is whatever the user is viewing in a Klaus PDF viewer — the current
page's own record (`page_store.py`: the slide's text plus any transcript
said over it) rendered to a PNG, and any selected text, tracked
by `viewer_context.py` — attached to every turn. It reads the lecture
library, searches and reads the user's notes, and can draft cards, every
write behind Klaus's own approval dialog, all reached through Klaus's
own localhost AnkiConnect-and-MCP server (`anki_endpoint.py`) rather
than a dependency on the separate AnkiConnect add-on. Sessions persist
per PDF (`assistant_sessions.py`). Design:
`docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md`;
each module's one non-obvious rule is in the module map below.

Pouya's original 2026-09-01 shape for that reversal — two assistants
(one to query notes and the lecture-PDF index, one to draft cards from
lecture material) behind a free/hosted split, four aqt-light layers, and
**a deliberately undecided UI surface** — didn't ship: that same evening
he converged it (Pouya: "remove the podcast multiple choice, just have
the assistant, and make it work like Claudian, and it is basically
viewing whatever we're viewing on the PDF viewer"). Deleted in the
convergence, 2026-09-02: `llm_client.py` (`a494f2d`, the streaming
transport), `entitlement.py` (`f1b330b`, the advisory tier check),
`podcast.py` (`026eb36`, built and cut inside the same window), the
Library's short-lived third-pane assistant-panel module this reversal's
dock replaces (`fed3a33`, slot-guard patch `451a753`) — and its session
store `assistant_session.py` (`1fcdba2`). Two of the original four
layers survive, now WIRED rather than dormant:
`card_forge.py` (`120293f`) stays available for batch card drafting
outside the dock, and `anki_tools.py` (`e1c023c`, the collection tool
layer, restored from `30847b9^`) is what `anki_endpoint.py` calls
straight into for every read and write — its handlers untouched, only
reused. Don't resurrect the two-assistant/hosted-tier language, and
don't invent a second UI surface — this dock is the decided one.

**Klaus went API-first on 2026-09-15** (Pouya: "forget about the
local-only approach … an API-first approach to simplify everything").
Two keys, both the user's own, both in Anki's addon config:
`api_key_openai` embeds cards and lecture pages, `api_key_anthropic` is
the reasoning key. There is no local engine left to install, start or
update — `ollama_client.py`, `ollama_runtime.py`, `ollama_setup.py` and
`page_ocr.py` were deleted that day, along with the Voyage and Ollama
embedding providers, the "Local model library (Ollama)" Preferences
page, and slide OCR (the PDF's own text layer plus the page image
replace it). **The seam is the page**: one record per (PDF, page)
holding the slide's text and what was said over it (`page_store.py`),
ONE embedding vector per page (`pdf_index.py` v2 — no chunker inside a
page any more), and the assistant reading that same record. Design:
`docs/superpowers/specs/2026-09-15-api-first-klaus-design.md`. **Plans 1
and 2 of that spec are built; Plan 3 is not** — Plan 1 landed
2026-09-15 (D1/D2/D3/D8: the page store, the two API clients,
page-level vectors, cost estimates, Preferences, the config migration)
and Plan 2 on 2026-09-17 (see the next paragraph). Plan 3 (the
assistant moved onto the Anthropic Messages API, deleting
`anki_endpoint.py` and the Claude Code child) is DESIGNED, NOT BUILT:
don't document it as present and don't code against it. Today the
assistant is still the Claude Code child described above — the only
thing `api_key_anthropic` buys is the pertinence judge, never the
assistant.

**Plan 2 landed 2026-09-17** (K-252..K-259, spec D4/D5/D6): the page
record grew a WRITER and the matching stack grew a JUDGE. Two new
modules — `pertinence.py` (Claude decides whether a cosine-matched card
is really about the page it matched) and `lecture_recorder.py` (mic
audio in, transcript segments out) — plus phase four of the index
chain, the `!Library::Doubtful` tag, confirmed-only retention and
counts, ● Record on both docks, and a transcript strip under the page
in both renderers. Each module's own entry is in the map below; the
one shape to carry: **the page record is now written from two ends** —
`pdf_handler.load_pages` seeds `slide_text` at import, the recorder
appends `segments` as you speak — and everything downstream (the page
vector, the assistant's context, the strip) reads that one record. The
spec's D7 stays unbuilt, so `agent_host.py` is untouched by any of it.

**Klaus Plus, 2026-09-16** (Pouya: "Instead of APIs, would it be
possible to create a subscription system?"): a SECOND way to pay for the
AI, not a second Klaus. **Free** is exactly the API-first turn above —
the user's own `api_key_openai`/`api_key_anthropic`, their own bill,
unmetered, unchanged. **Klaus Plus** is $12/month or $99/year (Pouya
chose Fly.io and pays the AI bills; the orchestrator set the price and
the quotas) for one `kp_` licence key instead of provider keys: Klaus
sends the same request bodies to **its own service** — `service/` in
this repo, FastAPI on one Fly Machine at `https://klausmate.com` (Pouya's
domain, everything on the apex since 2026-09-17; `klausmate.fly.dev` is
the same Machine),
SQLite on a volume, Stripe for billing, Resend for the one welcome
email — which holds Pouya's provider keys, relays to OpenAI and
Anthropic, and counts. Per UTC month, no rollover: 30 lecture hours of
audio, 3,000 judged cards (750,000 `judge` tokens at 250 a card),
200 assistant turns (1,200,000 `assistant` tokens at 6,000 a turn),
embeddings unmetered under a 20,000,000-token abuse ceiling; `past_due`
works 3 days, `canceled` to `period_end`. Design:
`docs/superpowers/specs/2026-09-16-klaus-plus-subscription-design.md`.
**The add-on holds no secret and gates nothing** — it ships as readable
Python, so the ONLY gate is the service answering 401/402/426, and
every "am I on Plus?" answer in `klausmate/` is a hint for wording, not
an entitlement check. Three config keys, all in Anki's addon config and
never in the repo: `klaus_plus_key`, `klaus_plus_cache` (the verdict
cache) and `klaus_plus_base` (default `""` = the built-in
`plus.DEFAULT_BASE`, shown as the field's placeholder, for a staging or
self-hosted service). The surface is Preferences → **API keys & models**,
where a "Klaus Plus" group sits ABOVE the keys — licence key
(`EchoMode.Password`), a `plus.status_line` readout, and Subscribe… /
Manage subscription… / **Check** (which refreshes the verdict on a
background task) — and the provider-key rows are RECAPTIONED "not
needed on Klaus Plus" while staying EDITABLE: never dimmed, never
disabled, because the free tier has to be one deletion away. `service/`
is a separate program, never shipped (`scripts/package.sh` stages only
`klausmate/`, plus an explicit `--exclude 'service/'`); its deploy
runbook is `service/README.md` and nothing in it belongs in the
add-on. **Three of the four purposes are live since Plan 2**
(2026-09-17): `embed` from `embeddings.py`, `transcribe` from
`lecture_recorder.Uploader._one`, and `judge` from
`pertinence.ensure_judged` — each reaching the service through
`plus.endpoint(cfg, <purpose>)` with no provider key. Only `assistant`
is still plumbing without a caller, and it stays that way until the
API-first spec's Plan 3 lands. A metered call's own 2xx response is
also a fresh quota reading: both clients take an `on_headers` callback
(K-252), and the two metered callers pass
`plus.note_quota(cfg, h, patch_config)` on the Plus path, so
Preferences' `status_line` catches up from real traffic rather than
only from **Check**.

**`klausmate/` is tracked in git** as of 2026-08-23. Its `user_files/`
(personal PDFs, annotations, card index) and `meta.json*` (live config,
holds API keys) stay ignored — never stage those.

- **Always edit the main checkout**, `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`,
  even though worktrees now contain a copy. Anki loads the addon through a
  symlink to the main checkout only, and the PostToolUse compile hook
  compiles that symlink target — so a worktree edit would report success
  without ever being compiled or loaded.
- Commits and diffs for addon work are now expected.

## Commands

- **Run the whole test suite**:
  `for t in tests/test_*.py; do echo "— $t"; python3 "$t" || break; done`
- **Run one test file**: `python3 tests/test_klausmate.py`. The files that
  need real PyQt6 widgets set `QT_QPA_PLATFORM=offscreen` themselves (12 of
  the 49 do), so the bare command is enough — see "Anki runtime & testing".
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
- **The service is a separate program with its own suite**, never part of the
  add-on loop above: `service/.venv/bin/python -m pytest -q`, and
  `DATABASE_PATH=./dev.sqlite3 service/.venv/bin/uvicorn klausplus.main:app
  --reload --port 8080` to run it locally — the default `DATABASE_PATH` is
  the Fly volume mount, so a bare `uvicorn` fails on import. Setup, secrets
  and deploy: `service/README.md`.
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
- **Offscreen PyQt6 can verify far more than "does it construct"
  (Pouya, 2026-09-01).** Under `QT_QPA_PLATFORM=offscreen` a real
  `DriveWindow`/`PdfSidebar`/`MapCanvas` renders to a `grab()` you can
  pixel-read, and every one of these is reachable headless — do not
  claim they need a live screen: **Retina** (`QT_SCALE_FACTOR=2` before
  `QApplication`, then `devicePixelRatioF()` is 2.0 and strokes render
  at device density); **hover** (`WA_UnderMouse` + a `QtGui.QEnterEvent`
  and `QHoverEvent` — they live in QtGui, not QtCore — then
  `unpolish/polish` so QSS re-evaluates); **pressed** (`setDown(True)`);
  **focus** (`QApplication.focusWidget()` after the same parentless-
  construct → `addWidget` → `show()` sequence `library_tab.mount()`
  uses — that exact mount is what caught K-179's misplaced focus ring,
  which a live accessibility probe had missed). Prove a state took by
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
  `complete`/`ask` actions are gone with autocomplete/Ask); the config
  accessors — **`write_config(cfg)` REPLACES the whole stored blob**
  (that is exactly why `_migrate_config` can scrub a key by popping it),
  so a partial dict handed to it wipes every other setting, API keys and
  library root included. **`patch_config(updates)`** (getConfig → update
  → writeConfig, hopped onto the main thread via `mw.taskman.run_on_main`
  and applied inline when there is no taskman) is the merge writer, and
  the ONE config writer a background thread may use — which is why every
  `plus.*` sink takes it and never the plain writer (two reviewers found
  that wipe as a Critical; `plus.remember`'s parameter is still *named*
  `write_config`, so read the type, not the name); `PdfDock` (a
  `QDockWidget` of the host window — Browse and Add Cards — since
  2026-09-05): the PDF viewer panel. Its title bar is `_PanelBar` (`[◫]
  [＋] [●] [tabs] … [page n/m] [⧉] [✕]`), which IGNORES presses it does not
  handle so Qt moves, docks and floats the dock from the empty bar
  (`setTitleBarWidget`'s contract; the tab bar does not stretch over that
  space). Allowed areas: left, right, bottom; floating is Qt's attached
  tool window, above the host and hidden with it — the parentless
  Mission-Control window, the six pane-anchored placements (K-169's note
  anchor included) and the `startSystemMove` tear-off with its watchdog
  and ghost were all deleted with the 2026-09-05 dock. `pdf_tabs.json`
  keeps `placement` (`left`/`right`/`bottom`/`float`, old values migrated
  once by `pdf_handler.migrate_placement`) and `geom`; applied on the
  first `panel_show`, never from Anki's saved `QMainWindow` state.
  `setDockNestingEnabled(True)` on the host lets it sit beside Anki's
  Browse sidebar dock. Host close still runs `PdfSidebar.cleanup()`
  before the window's C++ objects die. Anki's three editor windows —
  Browse, Add Cards and Edit Current — are all `QMainWindow`s and all
  get the dock; only an editor whose window is not a `QMainWindow` (a
  third-party add-on's) gets none — `hasattr(parent_window,
  'addDockWidget')` declines it with one log line — and the bar's ＋
  button only started working with the dock: `@_guarded` zero-argument
  slots connected to `clicked` had been swallowing PyQt's `checked`
  argument as a TypeError since the panel was built (both slots now
  take `*_args`); image-crop plumbing; **the lecture recorder's wiring**
  (K-257, spec D6): `_PanelBar.record_btn` is the ● / ■ toggle beside ＋,
  with a `status_label` reading `m:ss · n to transcribe` while a
  recording runs, and the Lecture dock's header carries the same pair.
  Both call ONE body, `start_or_stop_recording(owner, sidebar)` — a dock
  supplies `_recorder` and `set_recording(on, status)` and nothing else,
  so the Recorder/Uploader wiring exists once. `uploader()` is the
  profile's ONE `lecture_recorder.Uploader`, started on
  `profile_did_open` and stopped on `profile_will_close` **after** every
  recorder in `_active_recorders` (a recorder mid-chunk enqueues into it;
  tear the queue down first and that WAV is orphaned against a dead
  worker). `_active_recorders` is main-thread-only by convention — four
  call sites, no lock. Three rules the wiring exists to hold: a SECOND
  concurrent recording is refused with a named tooltip (each dock only
  ever knew its own `_recorder`, so three docks could open three
  `QAudioSource`s on one mic and double the metered minutes); `get_page`
  is scoped to the recording's OWN PDF and returns **0** — which
  `Recorder._tick` reads as "no page update", freezing on the last known
  page — once the sidebar has switched documents, because a `PdfSidebar`
  is reused across PDFs and the alternative is filing segments under the
  old PDF at the new one's page numbers; and every teardown path
  (`PdfDock._on_host_closing`, `LectureDock.shutdown`) runs
  `_release_recorder(owner)` BEFORE the sidebar's `cleanup()`, or closing
  Browse leaves the microphone hot. Stopping schedules the
  re-index through `_request_index_when_idle` (final review,
  2026-09-17): a 500 ms main-thread poll that calls
  `index_queue.request_pdf` only once `uploader().pending()` is 0 —
  the tail chunk is still uploading when ■ is pressed, so a direct
  request re-embedded every lecture WITHOUT its last 30 seconds —
  de-duplicated per PDF and capped at about twenty minutes so a hung
  upload cannot strand the re-index; never an idle callback inside the
  uploader, whose queue also empties mid-recording;
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
  `accent_rgba`). Since 2026-09-01 `library_qss` grounds the Library
  window, its tree, its header and the window-scoped
  `QSplitter::handle` all on `chrome` — the top bar's own token;
  `pdf_panel_qss`'s own scoped copy of that same handle rule stays on
  `bg` on purpose, because the pane it grabs (the PDF viewer's own
  internal splitter) is `bg` too. `accent_mix(night, alpha,
  base="surface")` takes a `base` at all because a tinted band has to
  mix over whatever paper it actually sits on — `"chrome"` for the
  Library's own selection band now. A documentless native `QPdfView`
  paints `bg` the same way — through palette roles rather than a
  stylesheet (Window/Base/Dark/Mid, set once at construction on both
  the view and its viewport in `pdf_viewer.py`, K-178, closed by
  K-208) — since a `QPdfView` answers to Qt's palette, not QSS;
  pdf.js needs no equivalent, since its own `css_vars` already hands
  the page `var(--bg)` directly. **UI files must not hardcode colours** — import theme and
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
  **The transcript strip** (K-258, spec D6) is this renderer's own copy
  of what `pdf_viewer` builds as a Qt widget: a **docked footer, a
  sibling of `#pages` and outside it**, pushed over the bridge as
  `klausSetTranscript(pageIndex, text)` and written with `textContent`,
  never `innerHTML`. In-flow inside the fixed-height `.page` div — the
  first shape — was painted over by the next page; that is why the
  footer never touches the pages' geometry. `_push_transcript` re-pushes
  the STORED text on the page's own ready signal, the same reason
  annotations re-push: `load_path` returns before `klausPdfLoad`
  resolves, so a transcript pushed during a fresh load is otherwise
  dropped on the floor.
- `pdf_viewer.py`: `PdfViewer` (QPdfView + selection/marquee/highlight
  overlay, find bar, thumbnails, zoom/nav, per-gesture eventFilter) and
  `PdfSidebar` (one instance reused across tabs). No toolbar "Copy page"
  button — Cmd/Ctrl-double-click a page, or right-click "Copy slide as
  image", copies it as an image; right-click also offers "Copy page text".
  `PdfSidebar` owns the **transcript strip** (K-258): for the native
  renderer a NoFocus collapsible strip under the page — never in the
  tab order, it is a readout, not a control — and for pdf.js the bridge
  push above, dispatched inside one `set_transcript`. `_refresh_transcript`
  shows what was SAID over the current page and deliberately excludes
  the slide's own text. It is reached two ways: a page change, and
  `page_store.subscribe` → `_on_page_store_notify`, whose WHOLE body
  (the pdf_safe/page check included, so it reads the freshest state)
  goes through `_run_on_main` — the uploader appends segments from its
  own daemon thread, and touching a QWidget from there is a crash
  waiting for a busy machine.
- `pdf_handler.py`: storage + text extraction. `user_files/{contexts,pdfs,
  pdf_originals,annotations}`, state in `pdf_tabs.json` (open tabs, placement,
  thumbs, last_used — all writers MERGE via `_save_tabs_file`). Since K-070/
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
  **impossible star** (K-270, Pouya's `klaus-logo.svg`, 2026-09-17; the
  design source of record is `klausmate/web/klaus-logo.svg`): five
  FILLED paths inline in a 26×26 box on a `viewBox="0 0 1254 1254"`,
  each `fill="var(--klaus-accent, currentColor)"` and none of them
  stroked, click → Klaus Preferences via `klausmate:settings` on
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
  gated: the star (fills `var(--klaus-accent, currentColor)` so it
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
  (theme.library_qss: flat 22px rows on `chrome` — K-117 put them on
  `surface`, K-175 on `bg` — one full-width
  hover/selection band, chevron twisties via
  `web/chevron-right-{day,night}.svg`, uppercase LIBRARY caption with
  New Folder/Refresh/Map beside it (Map opens `pdf_map.open_map_window`
  through a guarded import — K-124), quiet flat buttons — PrimaryButton
  opt-in kept). The move to `chrome` is 2026-09-01, Pouya's ask: "I
  want the panels, like the left panel, to be the same color as the top
  bar." The window-scoped `QSplitter::handle` grab
  follows onto `chrome` too, with only a 1px `grey_light` hairline
  marking the seam — a `bg` grab between two now-chrome panes had
  measured as a 7px stripe belonging to neither, fixed in the same
  round (K-206). The map box shares that same chrome surface (its
  canvas already painted chrome, K-185); the documentless viewer pane
  alone is `bg`, a step darker (K-178, closed by K-208).
  `library_explorer.BAND_BASE` moved to `"chrome"` with it, so the
  tree delegate's column-0 selection band and the sheet's own
  `accent_mix(..., 'chrome')` rules composite over the same real
  ground instead of drifting apart (K-130). Columns are
  PDF/Retention/Cards/Notes (Cards =
  VIEWABLE cards only, counts from priority_rows' K-118 keys via
  .get; a fully suspended PDF renders dimmed with "suspended" in its
  Cards cell; since K-254 that same cell appends
  `· m doubtful` when pertinence rejected any of the PDF's cards — in
  CARDS, the cell's own unit, so "suspended · 3 doubtful" is a real
  state); the context menu gains Suspend/Unsuspend Cards
  (stored-tag-first membership, ONE CollectionOp, undoable),
  **Doubtful cards…** (`tag:!Library::Doubtful "tag:<this PDF's lecture
  tag>"` — tag membership already IS the confirmed/rejected split, so no
  threshold math; offered on EVERY row, never gated on that row's own
  `doubtful_count`, because `DOUBTFUL_TAG` is the global union and a
  per-row gate would disagree with the search in both directions),
  Retention History… (guarded retention_history import, omitted when
  absent), and the clarity renames Update/Add to Search Index with
  setToolTipsVisible tooltips; the folder TREE also accepts external
  .pdf drops filed into the hovered folder (internal moves
  byte-equivalent); Match Sensitivity opens window-modal (dlg.open,
  K-114 — pdf_drive carries an exec-ban pin) and **scores its live
  preview with the rejected set**, read ONCE beside `matches` rather
  than per keystroke: without it a confirmed OK rewrote the row from the
  confirmed-only number to the matched-everything one (90% → 52%) with
  the user having changed nothing. An empty Library is not
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
  leaves `Curating`/`Curated`/`Matching`/**`Doubtful`** are never
  touched. `DOUBTFUL_TAG` = `!Library::Doubtful` (K-254, spec D5) is
  the one tag here that is NOT per-PDF: its members are the UNION, across
  every `judged.json`, of the pertinence-rejected nids that are STILL
  that PDF's candidates — `tag_sync.doubtful_members(cfg)` intersects
  each PDF's rejected set with its raw `matches.json` at/above the
  PDF's threshold (final review, 2026-09-17: a card that stops matching
  a lecture stops being doubtful for it; a PDF whose `matches.json`
  cannot be read keeps its whole rejected set, since missing data never
  strips a tag) — recomputed in full through the same
  `apply_membership` diff inside the same `CollectionOp` whenever a
  caller hands `_do_sync_one` a `doubtful` set. `doubtful=None` — the
  default, and what a plain index pass with no judge run uses — leaves
  it untouched rather than wiping real verdicts. **The union is the
  spec's rule and it has a consequence worth knowing**: a card rejected
  for lecture A but confirmed for B is still Doubtful, because
  membership is global. That is why "Doubtful cards…" in the Library
  intersects with the PDF's own lecture tag, and why the menu item is
  offered on every row (a per-row `doubtful_count` gate would disagree
  with the tag both ways). Pouya's design debt, unresolved on purpose:
  per-card overrule is a board card, not this design.
- `retention.py`: per-PDF retention/study-priority score shown in the
  Library — embed the PDF's PAGES (`pdf_index.py`, one vector each) →
  score every indexed note against them (max cosine, cached in
  `matches.json`, which since MATCHES_VERSION 2 also stores each note's
  best `"pages"` entry) → pull FSRS retrievability for matched cards →
  aggregate. `do_build` embeds `page_store.page_texts` and REUSES any
  page whose `text_hash` is unchanged (the `card_index` hash rule), so a
  page whose transcript grew re-embeds alone and a cancelled build
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
  return. **Since K-254 the score and the counts are CONFIRMED-ONLY**:
  `pdf_retention` and `note_card_counts` take a `rejected` nid set
  (pertinence's verdicts for that PDF, loaded per row inside
  `priority_rows`, guarded — an unreadable `judged.json` reads as
  "nothing rejected" and never breaks the pass), and confirmed =
  matched − rejected, with an UNJUDGED nid counting as confirmed. Every
  other reader of the same number passes the same set, or the Library
  and the thing beside it would disagree: Match Sensitivity's live
  preview and its OK path (read once, not per keystroke), and
  `pdf_map`'s retention fill. A fifth row key, `doubtful_count`, is
  reported on its own — and it counts **CARDS, not notes**, because it
  is read straight into the Cards cell (`"{card_count} · {doubtful_count}
  doubtful"`) and must share that cell's unit; a rejected note's
  suspended cards count toward neither side.
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
  → `pdf_index.best_page` argmax → that page's stored 1-based number;
  results cached per (nid, tags), revalidated by file stamps. No match
  shows exactly "No lecture page available for this card." pdfjs
  first-load jumps ride a generation-stamped retry ladder (the page
  posts `count:` before its divs exist); leaving review hides the dock
  (mw.web is shared across states); open-state + width persist under
  `pdf_tabs.json`'s `lecture_view` key; EVERY teardown path runs
  `sidebar.cleanup()` (K-095) — and, since K-257, `_release_recorder`
  BEFORE it. Config `lecture_view_reopen`. Shortcut
  "l" via `state_shortcuts_will_change` (collision-scanned) + a
  reviewer context-menu toggle; never activateWindow — answer keys
  stay on the reviewer. The dock's header was an empty `QWidget` until
  K-257 gave it a real one: the ● / ■ Record button and a
  `record_status` label, both driven by `__init__`'s shared
  `start_or_stop_recording` — the same body the PDF dock's bar calls, so
  recording a lecture mid-review and recording it from Browse are one
  code path.
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
  tooltip omits the line. That fill passes pertinence's `rejected` set
  per PDF (K-254, guarded per PDF), so the map's number is the same
  confirmed-only score the Library row shows — a second reader of
  `pdf_retention` that forgot it would quietly disagree with the tree.
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
  `page_store.page_texts` (slide text plus transcript), never from a
  chunker here.
- `page_store.py` (aqt-free above its divider; 2026-09-15, spec D2):
  **the seam every API-first capability keys on** — one JSON record per
  (PDF, page) at `user_files/pages/<safe>/<digest12>/<page:04d>.json`,
  holding the slide's own `slide_text` plus `segments` (what was said
  over it, `{t0,t1,text}`). `combined_text` is slide text then the
  segments in time order; `text_hash` (blake2b, 16 hex) over that is
  what `pdf_index` stores per row and what decides a re-embed.
  `ensure_records` seeds `slide_text` from `pdf_handler.load_pages` and
  is **idempotent — it never overwrites segments**, so re-importing or
  re-indexing a PDF cannot erase a transcript. `digest12` is a SHA-256
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
  the divider. `subscribe(cb)` is `viewer_context`'s shape — synchronous,
  a raising subscriber logged — and since 2026-09-17 it HAS its consumer:
  `PdfSidebar._on_page_store_notify` repaints the transcript strip. That
  callback fires **on the uploader's daemon worker thread**, because
  `append_segment` notifies inline on whatever thread wrote the segment;
  `pdf_viewer` marshals the whole body through `_run_on_main`, and any
  future subscriber must do the same rather than assume the main thread.
- `lecture_recorder.py` (aqt-free above its "Qt glue" divider; K-256,
  spec D6): **mic audio in, transcript segments out** — the page
  record's other writer. The `Chunker` is a pure state machine with one
  open span, closed by whichever of "`CHUNK_S` = 30 seconds elapsed" or
  "the page changed" comes first, so a segment can never straddle two
  pages (a page record keys on exactly one). A closed chunk is labelled
  with the **ACTUAL tick time**, never an idealised `t0 + CHUNK_S`: the
  WAV holds exactly the audio between the old `t0` and now, so after a
  stall an idealised boundary would both mislabel the bytes and then
  chase the schedule with a burst of near-empty catch-up chunks. Times
  are EPOCH seconds (`_epoch0` at Record, advanced by monotonic deltas),
  so two lectures a day apart still sort against each other while a
  mid-recording NTP jump can't run one chunk backwards. WAVs land in
  `user_files/recordings/<safe>/<t0>-<t1>-p<page:04d>.wav` — the REAL end
  time is in the name (K-280, Copilot on PR #4) because the Chunker closes
  a chunk early on a page change and on Stop, and `requeue_leftovers` would
  otherwise refile a 7-second chunk as 30 seconds running past the page it
  was said over; the two older name shapes still parse and fall back to
  `t0 + CHUNK_S`, and the match is anchored at both ends so a backup or a
  copy of a well-formed name is never requeued — headered with the rate and
  channel count actually NEGOTIATED with the device — ideal
  16 kHz mono Int16 first, then `device.preferredFormat()` as it is, both
  checked against `isFormatSupported` — because the Klaus Plus service
  meters lecture minutes by reading that header back. **The width is
  always 2** (K-279, Copilot on PR #4): forcing Int16 onto the preferred
  format, which is what shipped, meant a device whose only sample format
  is Float32 never started and Record was a dead button, so `_ingest`
  converts every captured buffer through the pure `pcm_to_int16`
  (Float32/Int32/UInt8 → Int16, a 0–3 byte tail carried into the next
  read so a torn sample cannot desync the stream). A device that supports
  neither format, or whose sample type Klaus cannot read, refuses to
  record with one log line naming it — never a silent dead button. The `Uploader` is one daemon worker, FIFO: transcribe, append to
  the page record, unlink. **A failed upload keeps its WAV** — network
  error, missing key, a Plus refusal — but a SPENT one never survives as a
  leftover: once `append_segment` has happened, `_spend` unlinks the WAV and,
  if that fails, renames it out of `_LEFTOVER_RE`'s namespace (`.spent`, which
  the next `requeue_leftovers` sweeps away), because a swallowed unlink failure
  meant the next Record transcribed and appended that same segment a second
  time (K-280) — and the next Record on that PDF
  re-queues leftovers (numerically by `t0`, not by filename); an empty
  transcript is dropped. Nothing a single chunk throws may kill the
  worker, or one bad chunk stops transcription for the session, which is
  also why the stop sentinel gets its own `task_done()` and
  `_ensure_thread` re-checks `is_alive()`. On Plus it calls
  `openai_client.transcribe` with no provider key through
  `plus.endpoint(cfg, "transcribe")`, remembers the quota from the
  response headers and a 401/402/426 through `plus.note_refusal` — both
  sinks reached lazily as the package's **`patch_config`**, never
  `write_config`. `ensure_records` is seeded once per PDF before the
  first segment ever lands (marked seeded only AFTER it succeeds), so a
  transcript can be the first thing a PDF that nobody has indexed ever
  grows. `on_segment` (no caller in the add-on today — the strip listens on
  `page_store.subscribe`) **would be called on the worker thread**, as
  `page_store`'s own notify chain behind it IS — which is why
  `pdf_viewer._on_page_store_notify` marshals through `_run_on_main`.
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
  retention score — the embedding side of Klaus's AI, with
  `pertinence.py` the reasoning phase bolted onto its end since
  2026-09-17; the assistant,
  Claude Code hosted as a child process, is the other one — see
  "The assistant (Claude Code)" below):
  - `embeddings.py` (aqt-free): **OpenAI only** since 2026-09-15 —
    `provider_name` answers `"openai"` whatever the config says,
    `DEFAULT_MODELS` has one entry (`text-embedding-3-large`), the key is
    `api_key_openai`, and the HTTP lives in `openai_client.py` (this
    module no longer opens a socket, so the old `OPENAI_API_BASE`/
    `VOYAGE_API_BASE` monkeypatch globals are gone — point
    `openai_client._urlopen` at a fake instead). `embedding_dimensions`
    (default 1024) is sent only for the Matryoshka-trained v3 models
    (`DIMENSION_CAPABLE_MODELS`), so a future model can't be handed a
    width it will reject. Vectors are **unit-normalized at write time**,
    and `index_signature`/`signature_matches` stay the ONE way any cache
    compares provider/model/dims.
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
    **index runner** — the ONE copy of the chain, FIVE phases since
    K-255 (`curation.ensure_index` → `retention.ensure_pdf_index` →
    `ensure_matches` → **`pertinence.ensure_judged`** →
    `tag_sync.sync_after_matches`, cancel token
    threaded through, each phase taking `curation._busy` in its own
    turn per K-146 — **except phase four, which never takes it at
    all**: its wait is a Judge/Skip dialog plus however long the
    Anthropic batches run, and holding the token across an interactive
    dialog is exactly K-146's leak. The one visible consequence is
    documented in the module docstring — Preferences' Index Now can
    start a concurrent card-index embed for that stretch). Phase four's
    progress is the ONLY one that counts things rather than percent:
    `RunnerState.phase` is `"judge"`, so `status_line` renders
    "judging 12/40" instead of a rounded percentage, and `ask_judge` is
    the paid-pass confirm the phase calls back into — window-modal
    `open()` (K-114), **Judge** and **Skip** with **Skip the
    default**, because a stray Enter must never start a paid batch (the
    same rule `offer_model_sweep`'s confirm follows). The phase itself
    composes the text: dollars off Plus, quota terms on it. Whatever
    escapes `pertinence`'s own defences is caught here and turned into
    `after_judged(set(), matches)` — untagged pertinence beats a wedged
    queue, since a raise would skip the tag write AND leave `_current`
    set forever. It exists
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
    describe one job differently. Gates: no profile, no OpenAI key
    (`missing_key_provider` reads `api_key_openai` — one provider, so
    the name it returns is a constant — but answers `""` for a
    `plus.key` too, since a Klaus Plus subscriber needs no provider key;
    that is a wording gate, not an entitlement one, and the service
    still has the last word), no run (the refusal is a
    MESSAGE, not a shrug). A PDF deleted
    before OR during its turn is skipped silently, and a deletion error
    never fails the batch behind it. Cancel bumps `_seq`, which is what
    stops `after_matches` tagging on the PARTIAL ranking
    `ensure_matches` hands back. **Closing the Library no longer
    cancels indexing** (the job may have been started from the deck
    screen). `offer_model_sweep(parent, prev_sig, first_key=…)`, called
    from `manage_models.save_embed` with the signature captured BEFORE
    the widgets overwrite config, re-indexes the card index plus every
    PDF with an index on disk — announced first, counted in notes and
    PDFs, and **priced**: `sweep_message` carries
    `cost.format_estimate(sweep_estimate(names))` (note text plus page
    text, falling back to the stored slide text), and the confirm's
    DEFAULT BUTTON IS NO, because it is the one dialog in Klaus that can
    spend money — and says so, including what declining does NOT buy
    (the card index still rebuilds unpriced on the next PDF add).
    `first_key` exists because pasting the first key does
    NOT move the signature — nothing was ever embedded — yet that is
    exactly when the offer is worth making; rotating a key is not a
    first key, those vectors are still valid. The THIRD trigger is
    `stale_index_names()` (K-236) — manifests whose `version !=
    pdf_index.INDEX_VERSION` — because an upgrade moves no signature
    either, yet every one of those indexes reads as absent; that is
    also why `indexed_pdf_names` tests for the manifest FILE and never
    `stats_from_disk`, which answers None for any version but the
    current one and so hid the whole upgrade population from the sweep.
    Signature comparison is ALWAYS `embeddings.signature_matches`,
    never a tuple `==`: a hand-spelled one reads every cache as stale
    and re-embeds the collection on a paid API, silently (the exact bug
    eight call sites shipped when the signature grew a third element).
  - `pertinence.py` (aqt-free above its own "aqt glue" divider;
    K-253/K-255, spec D4): **the judge** — cosine shortlists, Claude
    decides. Phase four of the chain above scores nothing: for every
    candidate at/above threshold it asks whether that card is really
    about the ONE page it matched best, `BATCH = 8` cards per Messages
    request, card text capped at `MAX_CARD_CHARS` and page text at
    `MAX_PAGE_CHARS` so eight cards can't assemble a 400 KB body. The
    answer is a **strict forced tool**: `record_verdicts`, declared
    `strict: true` with `additionalProperties: false` and every field
    required, `tool_choice` pinned to it. **A card the tool input does
    not name is UNJUDGED, never doubtful** — and so is every card in a
    batch whose tool input is malformed, since `parse_verdicts` returns
    `[]` rather than guess at a shape (a `null` body from a proxy must
    not crash the phase). A duplicate nid inside one call keeps the
    FIRST verdict: `strict` cannot forbid array duplicates, so the rule
    lives here rather than in whichever writer reads the store next.
    One failed batch leaves only ITS cards unjudged — the job still
    finishes and tags what it did judge — and the log line names the
    exception's CLASS and status only, never the payload, which holds
    card and lecture-page text. A REFUSAL is different (final review,
    2026-09-17): a 401/402/403/426 stops the job's remaining batches —
    `judge` calls `on_fatal` once and breaks, since re-sending 3,000
    refused cards one batch at a time was the bug — is remembered on
    Plus through `plus.note_refusal` → `patch_config` so the status
    line and the next Judge/Skip prompt say so, and reaches the user as
    ONE tooltip; `cancel` is checked per batch, so Stop mid-page sends
    nothing more. Verdicts persist in
    `user_files/pdf_index/<safe>/judged.json` keyed on the card's text
    hash, the page's text hash AND the model; `entry_for(v)` is the one
    place an entry is minted, precisely so a writer cannot forget
    `"model"` and make `is_stale`'s model check vacuously true (a
    model-less entry reads as STALE). **`judged_path` takes a
    pre-safened name** — it joins `safe` straight onto `pdf_index/`,
    the same as `retention`'s own paths; hand it a display name and you
    get a second, empty store. Below the divider, `ensure_judged` is
    the glue: **on Klaus Plus the judge is metered by cards and needs
    no Anthropic key at all** (`Client.complete(..., purpose="judge")`,
    quota refreshed from the response's own headers); off Plus with no
    key the phase is SKIPPED with one log line and no prompt — a paid
    confirm nobody can pay for is worse than silence — and verdicts from
    an earlier judged run STAND until their card or page changes: a
    removed key never un-doubts a card (Copilot on PR #4, 2026-09-17). The prompt itself
    prices the free tier through `cost.estimate_judge`, and because
    `reasoning_model` is a free-text field with no picker, a model
    outside `cost.PRICES` is priced as Sonnet and SAYS SO rather than
    letting a `KeyError` escape into the runner's callback. The best
    page per candidate is read straight out of the `matches.json` the
    previous phase just wrote (`_matched_pages`) — the freshness check
    already happened one phase back, and any failure reads as "no
    pages", which judges nothing rather than crashing.
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
    a fixed `SettingsSidebar` (star-logo pixmap FILLED from
    `top_bar.star_polygons()` — five polygons into ONE `QPainterPath` on
    `WindingFill`, SVG's own rule, at the label's own
    `devicePixelRatioF()` — app name + manifest `human_version`, `SettingsNav` list (ONE QListWidget — never
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
    Pages, in `_finish_nav` order: **General** (`image_crop_enabled`
    and `pdf_renderer` — no other UI touches these keys; the pdf.js
    checkbox maps "native"/"pdfjs" and needs a restart — plus the
    library folder and **Check Keys**, which since 2026-09-15 is a
    PRESENCE check on the two keys, not a probe of a local server),
    **Appearance**, **Assistant** (free-text `reasoning_model` lives on
    the keys page; here it is `assistant_reopen` and a Clear Sessions
    button that wipes `assistant_sessions.json` behind a window-modal
    confirm — notes, PDFs, and highlights are never touched by it), and
    **API keys & models** (2026-09-15, replacing "Semantic Search" and
    the deleted "Local model library (Ollama)" page): a **Klaus Plus**
    group ABOVE the keys (2026-09-16) — the licence key as a third
    password field, a `plus.status_line` readout, and Subscribe… /
    Manage subscription… / Check. Only **Subscribe…** is a bare
    `openLink` (`base + "/subscribe"` — a browser hop is the ONLY way
    Klaus touches payment). The other two are NETWORK calls, and both
    run `run_in_background` for the same reason: `plus.TIMEOUT_S` is
    15 s, and a `urlopen` that long on the click handler freezes Anki's
    whole UI. **Manage subscription…** fetches `plus.portal_url()`
    (`POST /v1/portal`) on that task and only THEN opens the URL it
    returns — an empty answer is a tooltip, never a blank browser tab —
    and **Check** runs `plus.refresh` with `patch_config` as its sink —
    then both keys as
    `EchoMode.Password` line edits, RECAPTIONED "Not needed on Klaus
    Plus; kept for the free tier." while a licence key is present and
    **still editable** (never disabled: the free tier is one deletion
    away), the embedding / reasoning /
    transcription model fields, the global sensitivity slider, the card
    index's status line with **Index Now**, and **Stop Indexing**. There
    is no provider combo — there is one provider — and no OCR row, no
    model-pull table and no Claude-binary picker. Changing the licence
    key CLEARS `klaus_plus_cache` on save, so a new key is never judged
    by the old key's verdict; `klaus_plus_base` is a General row whose
    placeholder is `plus.DEFAULT_BASE`. `save_embed` captures
    `index_signature` BEFORE the widgets overwrite config and hands it to
    `index_queue.offer_model_sweep(..., first_key=…)`, so a first OpenAI
    key (which does not move the signature) offers the sweep too; the
    sweep's confirm carries a `cost` estimate and **defaults to No** —
    it is the one dialog that can spend money. **Preferences are deferred-save**: widgets only
    call `mark_dirty()`; `save_all()` behind the **Save** button is the
    single writer of preference keys, closing dirty prompts to discard,
    and `sync_embed_widgets`/`sync_threshold_widget` bail while dirty so
    a background `refresh()` can't clobber unsaved edits. Adding a
    preference = widget + `mark_dirty` signal + a line in the matching
    `save_*`; a forgotten signal now costs a missing dirty mark, not a
    silently unsaved setting (which is exactly how `pdf_renderer`
    shipped broken). `sync_embed_widgets()` takes no arguments any
    more — with one provider there is no provider switch to reload the
    key and model fields for, and `ui_state["shown_provider"]` went with
    it; what `save_embed` compares is `embeddings.index_signature`
    before and after.
  - `setup_flow.py`: first-run "Welcome to Klaus" dialog + per-profile-open
    readiness checks. Two steps since 2026-09-15: the library-root
    pick, then ONE missing-key nudge whose wording is the module-level
    `KEYS_COPY` constant — the welcome dialog and the profile-open nudge
    quote the same string so setup can never be described two ways.
    When the key IS set, that second step instead runs
    `_offer_v2_index_sweep` (K-236): once per profile, and only while
    `index_queue.stale_index_names()` finds pre-v2 manifests, it opens
    the priced sweep confirm and writes `_v2_index_sweep_offered`
    whether the answer was yes or no — a refused whole-collection
    re-embed is an answer, not a snooze. Preferences' Save shares this
    same trigger (`index_queue.offer_model_sweep`) and MAY re-offer
    while stale manifests remain; this profile-open call is the
    once-per-profile one, gated by `_v2_index_sweep_offered`. No
    provider branch, no local-server probe and no runtime offer survive;
    readiness is `missing_keys(cfg)` — the provider keys not set, `[]`
    when a Klaus Plus key covers both (K-246) — and `keys_missing_copy(cfg)`
    narrows `KEYS_COPY` to exactly those, so the welcome dialog and the
    profile-open nudge NAME WHAT WAS ACTUALLY CHECKED (K-231, 2026-09-17:
    the copy named both keys while readiness tested one, so a user who
    pasted only the OpenAI key was told setup was done and met the first
    failure at the judge). `_embedding_ready` survives as the EMBEDDING
    half and still gates the v2 sweep alone; `KEYS_COPY` is built from the
    `KEY_COPY` table rather than written out, and `_offer_v2_index_sweep`
    returns whether it asked, so the sweep confirm and the key nudge cannot
    stack on one profile open. Still ONE nudge and ONE
    `_embed_key_setup_declined` flag for both keys, and it is a WORDING
    gate, never an entitlement check.
  - `openai_client.py` (aqt-free, stdlib): the ONE place Klaus talks to
    OpenAI — `embed(key, texts, model, dims)` and `transcribe(key,
    wav_bytes, model, …)` (multipart with a hand-built boundary), one
    retry on 429/5xx, `OpenAIError.user_message()` for the dialog copy.
    stdlib `urllib` because the official SDK needs compiled wheels an
    AnkiWeb add-on cannot vendor. **The key is passed in by the caller
    and NEVER logged** — no config read here, no key in an exception
    string. Tests point `_urlopen` at a fake. Since 2026-09-16 both
    functions take an optional `endpoint: plus.Endpoint` — None means
    OpenAI with the caller's own key, an Endpoint means the Klaus Plus
    service with its bearer and purpose headers — so every existing
    test stands unchanged; `anthropic_client.Client._target(purpose)`
    is the same seam on the Anthropic side. `transcribe` HAS a caller
    since 2026-09-17 — `lecture_recorder.Uploader._one` — and both
    functions also take `on_headers` (K-252), called with the response's
    headers on a 2xx and only a 2xx, since `plus.note_quota` records an
    "active" verdict unconditionally and must never see an error's
    headers; a raising `on_headers` is logged and never fails the call.
  - `anthropic_client.py` (aqt-free, stdlib): the Anthropic Messages
    client, revived on 2026-09-15 from the `llm_client.py` deleted in the
    2026-09-02 convergence (`a494f2d`) — without the second backend, its
    token, and the hosted-tier copy. `Client(get_config).stream(payload)`
    over `POST /v1/messages` with `anthropic-version: 2023-06-01`, plus
    one non-streaming `complete()`;
    `consume_sse` **finalises a `tool_use` block from its partial JSON
    when the stream drops**, which is what stops a cut connection turning
    a half-received tool call into a silent no-op. **Its one caller is
    the pertinence judge** (`complete(payload, purpose="judge")`, since
    2026-09-17); `stream()` still has none, and the assistant does NOT
    run on this client — that is Plan 3, unbuilt. Both entry points take
    `on_headers` (K-252) on the same 2xx-only contract as
    `openai_client`.
  - `cost.py` (pure): what a paid pass would cost, before Klaus spends
    anything — `PRICES` (dollars per million tokens, or per minute for
    audio, **dated in a comment: edit them when they change**),
    `estimate_embed`/`estimate_judge`/`estimate_transcribe` →
    `Estimate(tokens, dollars)`, and `format_estimate` → "~12,400 tokens
    · about $0.04". Tokens are chars ÷ 4: an estimate, shown as one,
    never a bill. Two callers: `index_queue`'s model sweep
    (`estimate_embed`) and `pertinence.ensure_judged`'s Judge/Skip
    confirm (`estimate_judge`). Still the FREE
    tier's number only — on Plus both prompts say "included in Klaus
    Plus" (the judge's in quota terms, cards used of cards allowed) and
    no estimate is computed. `PRICES` has exactly two REASONING entries
    (Sonnet and Opus, beside two embedding and two transcription rows) and
    `reasoning_model` is a free-text field, so a caller pricing a
    reasoning model **must** handle a model that isn't in it —
    `ensure_judged` prices it as Sonnet and says so; a bare `PRICES[…]`
    raises into the runner.
  - `plus.py` (aqt-free, stdlib): the **Klaus Plus seam** — `key(cfg)`
    (a `kp_` prefix and 35 chars, nothing else; there is no secret to
    check against), `base(cfg)` (`klaus_plus_base` or `DEFAULT_BASE`),
    `endpoint(cfg, purpose)` → the `Endpoint(base, headers)` NamedTuple
    both clients take (`Authorization: Bearer …`, `X-Klaus-Purpose` from
    `PURPOSES`, `X-Klaus-Client` = manifest `human_version`, which is
    what a `426` refuses), `parse_quota`, `refresh`, `portal_url`,
    `status_line`, and the verdict cache. **Its one non-obvious rule
    (2026-09-16, I-3): the SERVICE is the gate, so nothing here may
    expire an active verdict on a timer of its own.** `active()` is true
    with a key and no cache at all (nothing has refused yet), and stays
    true for any cached status that is not `refused:*` — there is no
    grace window and no separate offline fallback, because nothing here
    ever re-asks the service on a schedule; the only thing that DOES ask
    again is routing the next real call there, so a timed-out "active"
    could only ever misroute a paying subscriber onto the keyless
    provider path (idle a week, add a PDF, told to go paste an OpenAI
    key — the bug this rule replaced). A `refused:` verdict is the one
    thing that expires: after `CACHE_TTL_S` (6 hours) it is ignored and
    the next call simply routes to the service again, which either
    refuses afresh (re-caching) or succeeds. `refresh()` (Preferences'
    Check, the only caller) keeps the old cache untouched on a 5xx, a
    timeout or an unparseable body, recording a refusal only for an
    answer the service actually meant (4xx) — a restart or an outage is
    never mistaken for a refusal. `note_quota(cfg, headers, patch_config)`
    (K-252) is the other direction: a metered call's own 2xx response IS
    a fresh active verdict, so the two metered callers
    (`lecture_recorder`, `pertinence`) hand it the response headers
    through the clients' `on_headers` seam and the Preferences readout
    catches up without anyone pressing Check. **Call it only from a
    guaranteed-2xx path** — it records "active" unconditionally, so an
    error's headers would overwrite a real refusal. `parse_quota` reads
    `X-Klaus-Quota` case-insensitively out of an `HTTPMessage` or a
    plain dict in any casing, and answers None (writing nothing) for an
    absent or garbage header rather than inventing a verdict.
    **Every `plus.*` sink is
    `patch_config`, never `write_config`** (see the
    `__init__.py` entry): `remember`'s parameter is *named*
    `write_config` and handing it the package's actual `write_config`
    wipes every other setting on the first refusal. The key is never
    logged, never in an exception message, never in a URL.
- **The assistant (Claude Code)** — Klaus hosts the `claude` binary as a
  child process rather than running a loop of its own (that spec's D1:
  no assistant key in Klaus, the user's own login and subscription —
  `api_key_anthropic` pays for the pertinence judge and Plan 3, and
  buys this dock nothing). **The dock passes the child NO `--model`**
  (K-235, 2026-09-17): `assistant_model` was scrubbed by the API-first
  migration and the read was dead, `reasoning_model` is the JUDGE's
  Anthropic-API id with no authority over the user's own Claude Code
  subscription (a Claude Code alias is not a Messages-API id — the
  migration itself says so), and there is no assistant-model UI anywhere,
  so the model is whatever the user's own `claude` resolves;
  `command_line` omits the flag entirely rather than passing an empty one.
  `find_claude_cached()` is likewise called with no argument now.
  Design:
  `docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md`.
  **Still true today**, and the 2026-09-15 spec's Plan 3 — which moves
  this onto `anthropic_client.py` and deletes `anki_endpoint.py` and
  `agent_host.py` — is NOT built: describe and change what is here, not
  what is planned. One piece of it went early, though: the Preferences
  "claude binary" row and the `claude_binary` config key were deleted
  with the Ollama surfaces on 2026-09-15, so `find_claude`'s override
  argument is now always `""` and discovery is `shutil.which` → login
  shell → known paths. Five modules, plus the page store above:
  - `agent_host.py` (aqt-free): finds, spawns, and feeds the `claude`
    child. `find_claude` tries, in order, a config override (inert since
    the key went — see above), then
    `shutil.which`, then **the login shell's own PATH**
    (`[$SHELL, "-lc", "command -v claude"]`, 3 s timeout), then known
    install locations — GUI-launched Anki inherits launchd's minimal
    PATH and never sources the user's shell rc files, so `shutil.which`
    alone reports "not installed" on a machine where `claude` works fine
    from a terminal; this is Claudian's own documented trap.
    `command_line` builds the exact flags, including
    `--allowedTools Read Grep Glob ToolSearch mcp__klaus__*` —
    `ToolSearch` is there deliberately: this Claude Code build defers
    MCP tool schemas behind it, so denying it would silently cut off
    every `mcp__klaus__*` tool the model could otherwise reach (found by
    the spike, design doc §4.5/§4.7) — and
    `--disallowedTools Bash Edit Write MultiEdit NotebookEdit WebFetch
    WebSearch Task`. **`decide_permission` mirrors that same allow set
    and is belt-and-braces, not the front line**: the spike found
    `--permission-mode default` never sends a `control_request` at all
    (a non-disallowed tool just ran, unprompted, under a mode this
    build's own `--help` doesn't even list) — so the actual gate is the
    static `--disallowedTools` list on the command line, and
    `decide_permission`/`control_response` only answer whatever
    `control_request` traffic a future build or mode does send — and
    what they answer is now CONFINED: a `file_path`/`path`/`pattern`
    resolving outside the library root (or `user_files/assistant/` when
    there is no root — the same directory `start()` gives the child as
    its cwd) is denied, because a lecture page's own text — the page
    record Klaus attaches to every turn — is untrusted
    content, and "read `…/klausmate/meta.json` and
    summarise it" would otherwise put the embedding API key in the
    transcript. **The endpoint token is never in argv**: `command_line`
    takes no token parameter at all, the MCP header carries the literal
    `${KLAUS_TOKEN}`, and `child_env` (pure) puts the secret in the
    child's environment — `ps` is world-readable, and a live probe
    (build 2.1.228, 2026-09-02) confirmed Claude Code expands `${VAR}`
    in `headers` even for an INLINE `--mcp-config`: `init` reported the
    klaus server connected while `ps -o args=` showed the placeholder.
    `child_env` also strips the `CLAUDECODE`/`CLAUDE_CODE_*` nesting
    markers (the spike's finding, now in production) and sets
    `MCP_TOOL_TIMEOUT` well above the endpoint's 120 s approval wait, or
    a tool call blocked on the dialog times out client-side, the user
    approves anyway, and the model retries into a duplicate card.
    `classify` returns EVERY `tool_use`/`tool_result` block with its id,
    not just the first — Claude Code batches parallel `Read`/`Grep`
    calls. One child per dock, one reader thread; `stop()` is SIGINT →
    2 s grace → kill and leaves the child DEAD (so `send()` refuses to
    write to it and the dock respawns), while `interrupt()`/`reap()` are
    the non-blocking pair the dock's viewer switch uses instead of a
    2 s `proc.wait` on the main thread. `resume_failed(payload)` spots
    the "No conversation found with session ID" result a stale
    `--resume` produces. The session id survives for the next
    `--resume`; `find_claude_cached` memoises discovery per profile
    (step 3 spawns the login shell).
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
    its description (and `assistant_sessions`' system prompt, and the
    spec) must say "Anki search syntax" and send the model to
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
    can't steal the assistant's attention from the one the user is
    actually looking at. `subscribe` callbacks run synchronously on the
    caller's thread; a raising subscriber is logged, never left to break
    the reporter.
  - the page in view as text and image is `page_store.py`'s job (its
    own entry above): `assistant_dock._page_context` loads that page's
    record for the text (`text_source` is always `"page-record"` now)
    and calls `render_page_png` for the image. **Neither half can fail
    the turn** — a missing record is empty text, an unrenderable page is
    no image, and the send goes out on whatever the other half produced.
    The 2026-09-15 API-first turn deleted `page_ocr.py` and with it the
    OCR scheduler, so there is no debounce, no prefetch and no model
    round-trip in front of a send; the PNG is re-rendered on every Send
    and is not cached yet (board K-230).
  - `assistant_sessions.py` (aqt-free, stdlib-only): three stores under
    `user_files/assistant/` — `sessions.json` (**one Claude Code session
    id per PDF**, plus one "global" slot for no-PDF chats, so switching
    the followed PDF resumes THAT PDF's own conversation instead of
    dragging an unrelated one along), `prompts/<name>.md` (the slash
    commands, seeded with `explain`/`cards`/`quiz` only the FIRST time
    the folder is looked at — never re-seeded once a user has edited or
    deleted one), and `system_prompt.md` (versioned by a leading
    `<!-- klaus-system-prompt vN -->` comment so a later Klaus release
    can ship a revised prompt to an already-set-up profile). All three
    are atomic-written (tmp + `os.replace`); a missing file reads back
    as the ordinary empty case, a corrupt one is logged and STILL reads
    back empty — a torn store must never take session resume down with
    it.
  - `assistant_dock.py` (Qt): the `QDockWidget` UI — header, transcript,
    input, Send/Stop, New Session, a `/`-triggered `QCompleter` over the
    slash commands. Opens via a Library toolbar button, Tools → "Klaus
    Assistant", or **`Ctrl+Shift+K`** — deliberately not `Ctrl+Shift+A`,
    the spec's original binding: an offscreen repro found the native PDF
    viewer's OWN `Ctrl+Shift+A` (`pdf_viewer.py`, "highlight the current
    selection", a `WidgetWithChildrenShortcut`) claims that chord first
    via `ShortcutOverride` whenever a PDF pane has focus — exactly the
    two places (the Lecture dock, the embedded Library) this assistant
    is meant to be used from, so `Ctrl+Shift+A` would never have reached
    the dock at all. The shortcut is ONE window-scoped `QAction` added
    to `mw` at import time (`assistant_dock.setup()`), not the
    `state_shortcuts_will_change` mechanism `lecture_view.py` uses for
    its own "l" key — that hook fires only from `Overview.show`/
    `Reviewer.show`, never the deck browser and never
    `library_tab.mount()`'s embedded screen; `install_menu`'s Tools
    entry reuses this SAME `QAction` (`menu_action()`) rather than
    registering a second one on the same chord. **`AgentHost`'s
    callbacks reach Qt only through `_Bridge`, a `QObject` of
    `pyqtSignal`s** — the reader thread only ever calls `.emit()`, and
    Qt's auto-connection queues that onto the main thread when the
    emitting thread differs from the slot's (a real `AgentHost`) and
    calls directly when it doesn't (a synchronous fake host in tests),
    so no widget is ever touched off the main thread either way. The
    dock follows `viewer_context` (session switches; the page record and
    its PNG are read at Send time by `_page_context`, not scheduled
    ahead) and
    resumes the right `assistant_sessions` entry on every switch.
    **The child is spawned LAZILY, by `_ensure_child` on Send** — never
    at construction, never on a viewer switch (which only signals the
    old child and polls `reap()` on a QTimer, so the main thread never
    waits): an idle Claude Code emits nothing until the first message,
    so eager spawning bought a Node process and a blocking kill per PDF
    glanced at during review. `_ensure_child` also RESPAWNS after a
    Stop, a crash, or a PDF change — without it every Send after the
    first Stop wrote into a dead pipe and showed "stdin write failed"
    until New Session. The session id is remembered on `result`, keyed
    by `_sending_pdf_safe` (the PDF the turn was SENT for, captured at
    send time): `init` arrives a second later through `_Bridge`, so
    remembering there under whatever PDF was current stored A's id
    against B and made B resume A's conversation forever. A `--resume`
    Claude Code rejects (`agent_host.resume_failed`) drops that PDF's
    mapping, says so, and the next Send starts fresh.
- Deleted (2026-08, 2026-09-02 — do not resurrect the language): `claude_api.py`,
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
  Deleted again, 2026-09-02, for the same "converged, then reversed"
  reason described above: `llm_client.py` (`a494f2d` — the
  `claude_api.py`-derived streaming client didn't survive its own
  reshaping either), `entitlement.py` (`f1b330b`), `podcast.py`
  (`026eb36`), `assistant_session.py` (`1fcdba2`), and the Library's
  short-lived third-pane assistant-panel module (`fed3a33`, guarded
  `451a753`) that `assistant_dock.py` replaces.
  `card_forge.py` (`120293f`) and `anki_tools.py` (`e1c023c`) survive
  from the same plan, now wired rather than dormant — see "The
  assistant" above. `_LEGACY_KEYS_DROPPED` in `__init__.py` scrubs
  `assistant_api_key`/`assistant_backend`/`assistant_token` (retired
  2026-09-01): there was never a separate assistant credential to keep;
  the user's own `claude` login is it.
  Deleted a third time, **2026-09-15**, by the API-first turn
  (`docs/superpowers/specs/2026-09-15-api-first-klaus-design.md`, D1 —
  "forget about the local-only approach"): `page_ocr.py` with
  `tests/test_page_ocr.py` (removed in `1198041`, K-226 — slide OCR is replaced by
  the PDF's own text layer in the page record plus the page image), and
  `ollama_client.py`, `ollama_runtime.py`, `ollama_setup.py`
  (removed in `1b6fccd`, K-227 — with the Ollama and Voyage embedding providers,
  the "Local model library (Ollama)" Preferences page and the Assistant
  page's OCR rows). There is no local engine and no managed runtime any
  more; `user_files/runtime/` and `user_files/ocr/` are dead directories
  a user may simply delete. `_migrate_config` renames
  `embedding_api_key_openai` → `api_key_openai` (`assistant_model` is
  DROPPED, not renamed — Anki's `getConfig` merges `config.json`'s
  defaults under the user's keys, so `reasoning_model` is never empty
  and takes its default), clears `embedding_model` when the scrubbed
  `embedding_provider` was not OpenAI (the model belonged to the
  provider), drops `_embed_key_setup_declined` once so the API-first
  regime gets one fresh key nudge, and scrubs `embedding_provider`,
  `embedding_api_key_voyage`, `ocr_enabled`, `ocr_model`,
  `runtime_auto_setup`, `claude_binary`, `endpoint`,
  `pdf_index_max_chunks` and `pdf_match_agg` — those names in
  `__init__.py` are the migration, not a surviving feature.

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
  Since 2026-09-05 Klaus reparents nothing mid-gesture itself; `QDockWidget`
  does its own moving.
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
- **A GUI-launched app inherits a minimal PATH — check the login shell,
  not just `PATH`**: `shutil.which("claude")` reports "not found" on a
  machine where `claude` works fine from a terminal, because Anki
  launched from the Dock/Finder never sources `~/.zshrc` and friends.
  `agent_host.find_claude` falls back to
  `[$SHELL, "-lc", "command -v claude"]` (3 s timeout) before trying
  known install paths — Claudian's own documented trap, and worth
  remembering for any future external-binary discovery in this add-on,
  not just this one.
- **Claude Code defers MCP tool schemas behind its own `ToolSearch`
  tool — never drop it from `--allowedTools`**: with `mcp__klaus__*`
  allowed but `ToolSearch` denied, the model can see the tools exist but
  can never fetch their schemas, so every `mcp__klaus__*` call becomes
  unreachable — found by the assistant's spike when a real run went
  silent on Klaus's own tools. The same spike found
  `--permission-mode default` never sends a `control_request` at all (a
  non-disallowed tool just ran, unprompted): the actual gate is the
  static `--allowedTools`/`--disallowedTools` list on the command line,
  not `agent_host.decide_permission`, which only answers whatever
  `control_request` traffic a future build or mode does send.

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
- There is no model PICKER anywhere any more — no preset list, no pull
  table, no provider combo. Every model is a free-text field on
  Preferences → API keys & models (`embedding_model`, `reasoning_model`,
  `transcription_model`), each with the default as its placeholder, so a
  model released tomorrow needs no code change. Defaults live in
  `config.json` and, for embeddings, `embeddings.DEFAULT_MODELS`.
