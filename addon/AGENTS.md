# Klausmate — Agent Guide

Klausmate ("Klaus") is an **Anki 2.1 add-on** built around the
**Library**: a window over your imported lecture PDFs where each
one is indexed, the cards it covers are tagged with its own `!Library` tag,
and a per-PDF retention/study-priority score says how well you still recall
them. Semantic search over notes and lecture pages is what finds those
cards; since 2026-09-17 two more AI capabilities sit on the same seam —
**lecture transcription** (● Record on either PDF dock writes what you
say into the page record you said it over) and the **pertinence judge**
(Claude re-checks each shortlisted card against the page it matched, and
the ones it rejects get `!Library::Doubtful` and drop out of the
retention score). Copying a set of matched cards into a new deck is a
separate, manual Browse action. A
native PDF viewer (selection, highlights, sticky notes baked in as real
annotations) and an image-crop dialog round out the add-on. There is no
autocomplete and no chat panel — both were removed in 2026-08, along with
the Claude/Anthropic integration that powered them (see "What used to be
here" below if you're archaeology-diving through git history) — though
Claude is back since 2026-09-02, in a different shape, as the Claude Code
CLI behind the assistant dock (see "The assistant" below).

**Privacy:** Klaus makes network calls for two things — three on Klaus
Plus, where the subscription itself is checked against Klaus's own
service (`GET /v1/me` behind Preferences' **Check**, `POST /v1/portal`
behind **Manage subscription…**; both carry the licence key and nothing
else, and neither fires without one) — and nothing else
— no telemetry, ever. (Accurate as of 2026-09-15, the API-first turn:
there is no local engine any more, so nothing stays on the machine by
being local — it stays on the machine by not being sent.)

- **Embeddings** (the search index): **OpenAI**, through your own
  `api_key_openai`. Card text and lecture-page text (the slide's text
  plus any transcript stored with it) are sent to OpenAI's embeddings
  API when indexing and when searching.
- **Lecture transcription**, and only while you record: pressing ●
  Record captures your microphone and sends each closed 30-second (or
  page-change) chunk as a WAV to **OpenAI**, through the same
  `api_key_openai` and `transcription_model` (`lecture_recorder.py`,
  2026-09-17). Nothing is recorded or sent unless you press the button,
  and a chunk that fails to upload stays on disk under
  `user_files/recordings/` rather than being retried into the void.
- **The pertinence judge**, and only while indexing: phase four of the
  index chain sends each shortlisted card's text plus the ONE lecture
  page it matched best to **Anthropic**, through your own
  `api_key_anthropic` and `reasoning_model` (`pertinence.py`,
  2026-09-17). It never runs unpaid-for and never runs silently: the
  runner shows a **Judge / Skip** confirm with the estimated cost first,
  with **Skip** as the default button, and with no Anthropic key and no
  Klaus Plus the phase is skipped with one log line and no prompt at
  all.
- **The assistant**, and only while you use it: each turn you send goes
  to **Anthropic**, through the `claude` binary running under your own
  Claude Code login — Klaus stores no key for it. A turn carries your
  message plus the page you are viewing: its text, its image, and any
  text you have selected. Nothing is sent when the Assistant dock is
  closed or unused.
- **`api_key_anthropic` pays for the judge, and only the judge.** Since
  2026-09-17 `anthropic_client.Client.complete` has exactly one caller —
  `pertinence.ensure_judged` — and `stream()` still has none. The
  assistant does NOT read this key: it reaches Anthropic only the
  indirect way above, through your own Claude Code login. Moving the
  assistant onto the Messages API is the spec's Plan 3, still unbuilt.
- **On Klaus Plus, one hop is added and nothing else changes** (2026-09-16).
  A subscriber has no provider keys; the same request bodies go to
  **Klaus's own service** (`service/` in this repo, `klausmate.fly.dev`),
  which relays them to OpenAI and Anthropic with the operator's keys and
  **stores counters only** — the Stripe customer id, the email Stripe
  reports, the licence key's SHA-256 hash, the subscription status and
  period end, and the month's four usage numbers. Lecture text, audio and
  page images pass through and are gone: no request or response body is
  stored, and none is logged (logs carry method, path, status, an
  8-character key-hash prefix, latency and the metered amount — a service
  test asserts it). Nothing about WHAT you study is retained. The service's
  own statement of this is `<PUBLIC_BASE_URL>/privacy` — on the built-in
  base, <https://klausmate.fly.dev/privacy> — and the
  add-on's cache of the verdict never leaves the machine. Still no
  telemetry: a free-tier profile makes exactly the calls above and never
  contacts `klausmate.fly.dev` on its own — with no `klaus_plus_key`,
  `plus.key` is `""`, `plus.active` is False and no Plus code path opens a
  socket. (Pressing **Subscribe…** opens that URL in your browser; that is
  you, not Klaus reporting anything.) Scope, today: **three of the four
  purposes take this hop** — `embed` (`embeddings.py`), `transcribe`
  (`lecture_recorder.Uploader`) and `judge` (`pertinence.ensure_judged`),
  each with no provider key, each metered; only `assistant` is still
  plumbing without a caller, and it stays that way until Plan 3 lands. A
  metered 2xx also carries `X-Klaus-Quota`, which the clients hand back
  through `on_headers` so the Preferences readout refreshes from real
  traffic rather than only from **Check**. Two
  calls to the service carry no lecture content at all and are the
  subscription talking about itself: `plus.refresh` → `GET /v1/me` (the
  **Check** button and the verdict cache) and `plus.portal_url` →
  `POST /v1/portal` (**Manage subscription…**), each sending the licence
  key and nothing else.

---

## Repository layout

```
Addons/                       # Git repo root
├── AGENTS.md                 # This file — architecture & dev conventions
├── CLAUDE.md                 # Module map + hard-won gotchas (authority for internals)
├── README.md                 # Repo entry point — build/install from source
├── ANKIWEB.md                # Description blurb for the AnkiWeb listing
├── LICENSE                   # GNU AGPL v3 (the add-on; `service/` is a separate program)
├── scripts/
│   └── package.sh            # Builds dist/klausmate.ankiaddon
├── service/                  # Klaus Plus — a SEPARATE program, NEVER shipped to users.
│   ├── README.md              # The operator's deploy runbook (Fly, Stripe, secrets, kill switch)
│   ├── klausplus/             # FastAPI app: proxy.py (the three metered routes + /v1/me),
│   │                          #   entitlement.py, meter.py, keys.py, db.py (SQLite), billing.py
│   │                          #   (Stripe + the pages), email.py (Resend), config.py (every quota)
│   ├── tests/                 # pytest — `cd service && .venv/bin/python -m pytest -q`
│   ├── Dockerfile             # python:3.12-slim, uvicorn klausplus.main:app on :8080
│   ├── fly.toml               # One Fly Machine, /data volume, /healthz check
│   └── pyproject.toml         # fastapi, uvicorn, httpx, stripe — server-side deps only
└── klausmate/                # Anki add-on package (copy/symlink into addons21/)
    ├── README.md              # Ships inside the add-on — user-facing usage
    ├── __init__.py             # Bootstrap, gui_hooks, JS bridge, Tools→Klaus menu, PDF tab/window management, image-crop context menu
    ├── embeddings.py           # Embeddings: OpenAI only, unit-normalized vectors, the index signature (aqt-free)
    ├── openai_client.py        # Stdlib HTTP to OpenAI: embed() and transcribe(), one retry (aqt-free)
    ├── anthropic_client.py     # Stdlib HTTP to the Anthropic Messages API — complete() judges; stream() still has no caller (aqt-free)
    ├── plus.py                 # Klaus Plus: the licence key, the per-call Endpoint both clients take, the cached verdict (aqt-free)
    ├── LICENSE                 # The same AGPL v3 text, shipped inside the package
    ├── cost.py                 # Dated prices + estimates shown before any paid pass (pure)
    ├── page_store.py           # One record per (PDF, page): slide text + transcript segments; the API-first seam
    ├── lecture_recorder.py     # ● Record: Chunker (30 s / page change), WAV chunks, the upload worker that writes segments (aqt-free above its Qt glue)
    ├── pertinence.py           # Index phase four: Claude judges each matched card against its best page; judged.json (aqt-free above its glue)
    ├── card_index.py           # Persistent embedding index over the user's notes (aqt-free)
    ├── curation.py             # Card index build (ensure_index) + the undoable Browse deck copier
    ├── pdf_drop.py             # PDF drop square + MainWebView.dropEvent wrap on the deck list / overview screens
    ├── pdf_index.py            # Persistent embedding index over one PDF — ONE vector per page (aqt-free)
    ├── retention.py            # Per-PDF retention/study-priority scoring for the Library
    ├── pdf_handler.py          # PDF import/storage, text extraction, per-tab state, annotation baking
    ├── pdf_viewer.py           # PdfViewer (QPdfView + selection/highlight overlay, find, thumbnails) and PdfSidebar
    ├── pdf_drive.py            # The Library window — virtual-folder tree + PdfSidebar
    ├── drive_store.py          # Library's virtual folder layer (user_files/drive.json); nothing on disk moves
    ├── manage_models.py        # KlausMate Preferences: the two API keys, the three model fields, general/appearance toggles
    ├── setup_flow.py           # First-run dialog + per-profile-open readiness checks (library root, then one key nudge)
    ├── tag_migrate.py          # One-time klaus:: -> !Library:: tag rename for upgrading collections
    ├── browse_toggles.py       # Browse toolbar ◧/◨ sidebar and editor-column toggles
    ├── crop_dialog.py          # Image-crop dialog (crop saved as a new media file)
    ├── config.json             # Default add-on config
    ├── config.md               # Config key documentation (shown in Anki config UI)
    ├── manifest.json           # Package name and version for non–AnkiWeb distribution
    ├── web/
    │   └── copilot.js          # Editor field-focus tracking (for PDF page-insert targeting) + image-crop dblclick trigger
    ├── vendor/                 # Vendored pure-Python deps (pypdf 6.11.0) — the sole third-party exception
    └── user_files/             # Persisted across upgrades — never write here from a test
        ├── contexts/           # *.json (per-page PDF text), one per imported PDF
        ├── pdfs/                # Stored PDF copies (post-bake, real annotations included)
        ├── pdf_originals/       # Pristine copy captured once, used to regenerate bakes
        ├── annotations/         # Per-PDF highlight/note JSON, source of truth for baking
        ├── pdf_tabs.json        # Open tabs, placement (dock left/right/bottom/float), thumbs, last_used
        ├── drive.json           # Library's virtual folders + window geometry (drive_store.py)
        ├── card_index/          # Packed vectors.f32 + manifest.json for semantic deck search
        ├── pdf_index/           # Per-PDF embedding indexes (one vector per page) + judged.json (pertinence verdicts)
        ├── recordings/          # <pdf_safe>/<t0>-p<page>.wav — chunks awaiting transcription; empty once they land
        └── pages/               # <pdf_safe>/<digest12>/<page:04d>.json — slide text + transcript segments (page_store.py)
```

**Install path:** `addons21/klausmate/` (folder name must be alphanumeric per Anki conventions).

**Do not store user data outside `user_files/`** — everything else in the add-on folder is wiped on upgrade.

---

## Architecture

### Semantic card matching (indexing a PDF)

```
Library row → right-click → "Add to Search Index" / "Update Search Index"
        │
        ▼
index_queue.py :: _run(job) — FIVE phases, one cancel token threaded
        │        through all of them (K-146, K-152, K-255). The Library's
        │        _on_embed is now just one request_pdf() call into this.
        ▼
curation.py :: ensure_index() — sync the card index (only new/edited notes
        │        re-embed; text-hash diffed). This is the only user-facing
        │        path that refreshes it; the Curate button used to do it
        │        invisibly, which is why K-146 had to add it here.
        ▼
embeddings.py — OpenAI (openai_client.embed), unit-normalized vectors
        │
        ▼
card_index.py — user_files/card_index/: packed float32 vectors + manifest,
        │        top-K via math.sumprod over memoryviews (no numpy)
        ▼
retention.py :: ensure_pdf_index() → ensure_matches() — embed the PDF's
        │        PAGES (one vector each, from page_store.page_texts; a page
        │        whose text_hash is unchanged keeps its vector), score every
        │        indexed note (max cosine, cached in matches.json with the
        │        winning page)
        ▼
pertinence.py :: ensure_judged() — Claude judges each candidate against
        │        that winning page, 8 per request, through a strict forced
        │        tool; verdicts cached in pdf_index/<safe>/judged.json.
        │        Paid, so it asks first (Judge / Skip, Skip the default) —
        │        and skips itself silently with no Anthropic key and no
        │        Klaus Plus. A card it does not answer for is UNJUDGED,
        │        which counts as confirmed, never as doubtful.
        ▼
tag_sync.py :: sync_after_matches() — the notes at/above this PDF's
          sensitivity threshold become the members of its one
          "!Library::<folder>::<leaf>" tag; the rejected nids across
          EVERY PDF become the members of "!Library::Doubtful"
```

Copying matches into a deck is a SEPARATE, manual action with no PDF and no
deck scope: **Browse → Notes → "KlausMate: Create Curated Deck from
Selection…"** (`curation.prompt_and_create` / `create_curated_deck`), one
undo step, tagged `!Library::Curated`, originals untouched. There is no
free-text search box and no Curate Deck button — K-146 removed the button
(it never created a deck; it tagged and opened Browse on the tag indexing
already writes) and K-151 removed the last of its vocabulary.

### The Library and retention scoring

```
pdf_drive.py — the Library window: a tree of virtual folders (drive_store.py,
        │       user_files/drive.json — nothing on disk moves) next to a
        │       standalone PdfSidebar
        ▼
retention.py — per PDF: embed its pages (pdf_index.py, one vector each) →
        │       score every indexed note against those pages (max cosine,
        │       cached in matches.json) → drop the nids pertinence
        │       rejected (confirmed = matched − rejected; an unjudged card
        │       counts as confirmed) → pull FSRS retrievability for the
        │       confirmed cards → aggregate into a study-priority score
        ▼
Library row shows the score, and "n · m doubtful" in its Cards cell when
any of its cards were rejected; right-click can index/re-index, adjust match
sensitivity, show matches in Browse (it hops to the PDF's own !Library tag —
the "!Library::Matching" preview tag was retired in K-055), open Doubtful
cards… (that tag intersected with !Library::Doubtful), suspend or
unsuspend its cards, or chart its retention history
```

Everything that shows that number passes the same `rejected` set —
`priority_rows`, Match Sensitivity's live preview, and the embedding
map's retention fill — or two surfaces describe one PDF differently.
`!Library::Doubtful` is the one **global** tag here (the union across
every `judged.json`), so a card rejected for lecture A but confirmed for
B stays Doubtful; that is the spec's rule, and the per-card overrule
that would resolve it is a board card, not this design.

### PDF viewer (`pdf_viewer.py`)

- One `QPdfView` in **MultiPage / FitToWidth** mode inside a `PdfSidebar` widget, opened from the Library or the editor's drop panel.
- Layout math mirrors Qt's `QPdfViewPrivate::calculateDocumentLayout` (screen DPI / 72, margins, page spacing, centered page width) — required so hit-testing and selection highlights line up.
- Text selection: viewport `eventFilter` drags map to `(page, QPointF)` via `_viewport_to_page_point`; `QPdfDocument.getSelection()` is called per page (multi-page drags supported); highlights painted by `_SelectionOverlay` using `QPdfSelection.bounds()`.
- **Cmd+C** / right-click **Copy** copy selected text; **Cmd/Ctrl-double-click** a page, or right-click **Copy slide as image**, copies it as an image (there is no toolbar button for this — it was removed).
- Highlights and sticky notes are baked into the stored PDF as real annotations by `pdf_handler.bake_annotations` (vendored `pypdf`).
- **Transcript strip** (2026-09-17): a collapsible readout under the page showing what was *said* over it (the page record's `segments`, never its slide text). Native = a NoFocus Qt strip; pdf.js = a docked footer outside `#pages`, pushed as `klausSetTranscript` and re-pushed on the page's ready signal. It refreshes on a page change and on `page_store.subscribe` — and that notification arrives on the uploader's worker thread, so `_on_page_store_notify` defers its whole body through `_run_on_main`.

### Editor-side PDF panel

`PdfDock` — a `QDockWidget`, one per host window (Browse and Add Cards),
created from `editor_did_init` exactly as the panel's earlier container
was — hosts any number of open PDFs, with `_PanelBar` as its title-bar
widget (`[◫] [＋] [tabs] … [page n/m] [⧉] [✕]`), which ignores presses it
does not handle so Qt itself moves, docks and floats the dock from the
bar's empty space. Allowed areas are left, right and bottom; floating is
Qt's own attached tool window above the host, never a parentless real
window — the old pane-anchored placements and the native
`startSystemMove()` tear-off with its watchdog/ghost fallback are gone.
`placement` (`left`/`right`/`bottom`/`float`, old values migrated once by
`pdf_handler.migrate_placement`) and `geom` persist the same way and
apply on the first `panel_show`, never from Anki's own saved
`QMainWindow` state. One
`PdfViewer`/`PdfSidebar` instance is reused across tabs. The open tab set,
dock placement, thumbnails, and last-used page persist in
`user_files/pdf_tabs.json` (all writers merge via `pdf_handler._save_tabs_file`,
never overwrite wholesale). `web/copilot.js` only tracks field focus (for
PDF-page-insert targeting) and the image-crop double-click trigger now —
the ghost-text/Ask bridge it used to carry is gone.

### The assistant

```
assistant_dock.py — the QDockWidget on Anki's main window (Ctrl+Shift+K,
        │  Tools → Klaus Assistant, or a Library toolbar button)
        ▼
viewer_context.py :: current() — the LAST ACTIVATED PdfSidebar (Library,
        │  Browse's editor pane, or the Lecture dock) that still has a
        │  document open, plus its page and selection
        ▼
page_store.py — that page's record (the slide's own text, plus any
        │  transcript segments stored with it) and render_page_png(); read
        │  at Send time by assistant_dock._page_context, neither half able
        │  to fail the turn
        ▼
agent_host.py :: build_turn() — one stream-json user message (text +
        │  a "[Klaus context]" block + image) written to the `claude`
        │  child's stdin; a reader thread parses its stdout stream back
        ▼
anki_endpoint.py — mcp__klaus__* tool calls from the child arrive here
           over HTTP (see "Localhost endpoint" below); reads run right
           away, writes wait on an approval dialog
```

One assistant, one engine: Klaus hosts the **Claude Code CLI** as a
child process (`agent_host.py`) rather than running a chat loop of its
own — no assistant key stored in Klaus, the user's own `claude` login and
subscription pay for it. (The 2026-09-15 spec's Plan 3 replaces this
engine with `anthropic_client.py` and deletes `anki_endpoint.py`; it is
not built, so what follows is current, not historical.) Five modules,
one concern each:
`agent_host.py` (finds, spawns, and streams with the `claude` binary —
binary discovery falls back to the user's login shell before known
install paths, since a GUI-launched Anki has a minimal `PATH`),
`anki_endpoint.py` (the localhost server both the wider AnkiConnect
ecosystem and the child's own MCP tools reach), `viewer_context.py` (a
registry of every live `PdfSidebar`; the assistant follows whichever one
was activated last),
`assistant_sessions.py` (one Claude Code session id per PDF, plus slash-
command prompt files, under `user_files/assistant/`), and
`assistant_dock.py` itself (header, transcript, input, Send/Stop, New
Session, slash completion). The page in view comes from `page_store.py`,
which the index shares — see the layout above.

Every write the assistant makes — adding a note, editing fields, tagging
— goes through the SAME kind of plain-text approval dialog Klaus shows
for any other write (deck, every field, tags, the source page); a
declined or timed-out approval comes back to the model as an error, not
a silent no-op. Cards the assistant adds carry `klaus::assistant` and
`klaus::from::<pdf_safe>` — never the PDF's own `!Library` tag, which is
`tag_sync`'s membership invariant and would be wrong to set by hand; the
next index pass tags the card for real if it actually matches.

Design: `docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md`.
Per-module non-obvious rules are in CLAUDE.md's module map.

### Hooks registered at import (`__init__.py`, approximate)

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
mw.addonManager.setConfigAction(__name__, open_config)              # -> manage_models_dialog
gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)      # pycmd routing ("klausmate:" prefix)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)  # right-click crop
gui_hooks.main_window_did_init.append(install_menu)                 # Tools → KlausMate Preferences…
gui_hooks.profile_did_open.append(_migrate_config)                  # legacy chat_*/claude_* key cleanup
gui_hooks.profile_did_open.append(tag_migrate.migrate_on_profile_open)  # one-time klaus:: -> !Library:: rename
gui_hooks.profile_did_open.append(first_run_check)                  # first-run: library root + the API-key nudge
gui_hooks.profile_did_open.append(setup_readiness_check)
gui_hooks.profile_did_open.append(_start_assistant_endpoint)        # anki_endpoint bind (mw.col must exist)
gui_hooks.editor_did_init.append(on_editor_did_init)                # PDF panel + tab container
gui_hooks.browser_will_show.append(on_browser_will_show)            # Browse toolbar toggles (◧ / ◨)
curation.setup_hooks()                                              # gui_hooks.browser_menus_did_init
pdf_drop.setup()                                                    # PDF drop square + drop wrap on deck screens (independent try/except)
pdf_drive.setup()                                                   # Library window + top-toolbar link (independent try/except)
top_bar.setup()                                                     # toolbar restyle + star logo (independent try/except)
browse_highlight.setup()                                            # Browse search-term highlighting (independent try/except)
heatmap.setup()                                                     # review heatmap on the deck list (independent try/except)
dashboard.setup()                                                   # Control-Center widget editing (independent try/except; MUST stay after heatmap — body order)
window_chrome.setup()                                               # KlausBook chrome for Add/Browse/Stats/reviewer-bar (independent try/except)
assistant_dock.setup()                                              # Ctrl+Shift+K QAction on mw; registers _teardown + reopen_if_configured
gui_hooks.profile_will_close.append(_stop_assistant_on_profile_close)  # MUST stay after assistant_dock.setup() — see below
lecture_view.setup()                                                # review-time Lecture dock (independent try/except)
gui_hooks.profile_did_open.append(_start_lecture_uploader)          # the profile's one lecture_recorder.Uploader
gui_hooks.profile_will_close.append(_stop_lecture_uploader)         # stops every _active_recorders entry FIRST, then the uploader
```

`assistant_dock.setup()` adds two of its own:
`profile_will_close` (`_teardown` — closes the child `claude` process)
and `profile_did_open` (`reopen_if_configured` — honours
`assistant_reopen`). The append ORDER of
`_stop_assistant_on_profile_close` matters: `gui_hooks` fires
`profile_will_close` listeners in append order, and that function stops
the endpoint the child talks to, so `setup()`'s own `_teardown` has to be
registered first or a turn still in flight could hit a refused socket.

`_stop_lecture_uploader` stops every live `Recorder` before it stops the
uploader, not after: a recorder mid-chunk enqueues into that worker, so
tearing the queue down first orphans the WAV it was about to hand over.

`heatmap.setup()` adds four of its own:
`deck_browser_will_render_content` (the panel HTML into `content.stats`),
`webview_will_set_content` (its stylesheet, DeckBrowser only),
`webview_did_receive_js_message` (a clicked day) and `browser_will_search`
(resolving the `klausday:` token those clicks produce).

`pdf_drop.setup()` and `pdf_drive.setup()` are each wrapped in their own
`try/except` at import time — a failure in one must not cost the user the
other, or the editor/menu features above. `tests/test_imports.py` imports
every module directly (bypassing that swallowing try/except) so a genuine
import-time bug fails loudly instead of a buried `print()`.

### JS ↔ Python message protocol

One bridge now: `web/copilot.js` → `on_js_message` in `__init__.py`, prefix
`"klausmate:"`, split `":", 2`. Payloads are **base64-encoded JSON** after
the action name:

| Action | JS → Python | Purpose |
|--------|-------------|---------|
| `focus` | `{field}` | Sets `editor._klausmate_target_field_index` / `_target_field_name` — used for PDF page-insert targeting |
| `crop` | `{...}` | Opens `crop_dialog.py` for the referenced image |
| `log` / `dbg` | plain string | Console logging |

Two more prefixes ride the same gui_hook from other modules:
`klausmate:heatmap:<day>` (a heatmap cell click → Browse) and
`klausmate:dash:<b64 json>` (dashboard edit/order/remove/add —
validated by `dashboard.apply_action`, the only gate to config).

The old `"klaus:"`-prefixed bridge belonged to the deleted chat panel
(`chat_dock.py` / `web/search.js`) and no longer exists.

### Localhost endpoint

`anki_endpoint.py` serves the assistant's Anki reach — and, incidentally,
anything else that speaks AnkiConnect's wire protocol — from a
`ThreadingHTTPServer` bound to `127.0.0.1:0` (an OS-assigned ephemeral
port; AnkiConnect's usual 8765 is never assumed free). Started on
`profile_did_open`, stopped on `profile_will_close`. A fresh 32-byte hex
token is generated per start; every request must carry it as
`X-Klaus-Token`, and any request carrying an `Origin` header is refused
outright (a browser page must never drive the collection) — both
checked before the body is even read. Bodies over 4 MB are rejected.
Writes never touch the collection without the user approving a
plain-text preview in a window-modal dialog (`open()`, never `exec()` —
K-114) while the HTTP thread waits on a `threading.Event`.

Two routes share ONE registry (`ACTIONS`) so they can't drift apart:

- **`/`** — AnkiConnect's own `{"action", "version", "params"}` protocol;
  HTTP 200 always, `{"result", "error"}` in the body (AnkiConnect's own
  convention). Supported actions: `version`, `deckNames`,
  `deckNamesAndIds`, `modelNames`, `modelFieldNames`, `findNotes`,
  `notesInfo`, `findCards`, `cardsInfo`, `addNote`, `addNotes`,
  `updateNoteFields`, `addTags`, `removeTags`, `guiBrowse`, plus three
  Klaus-only ones — `klausSearchNotes` (**lexical**: `anki_tools`'
  handler behind it is `col.find_notes`, i.e. Anki's own search syntax,
  and the tool description and system prompt both say so; the semantic
  note search is a separate future card, K-207),
  `klausSearchLecturePdfs` (the **semantic** one, over the indexed
  lecture PDFs), and `klausCurrentView` (what
  `viewer_context` says the user is looking at). Anything else answers
  `"unsupported action"`. A request carrying `X-Klaus-Agent: 1` (the
  `/mcp` route sets this) additionally requires `addNote`'s
  `params.note.options.sourcePage` — a card proposed with no source page
  is an error, never a silent add.
- **`/mcp`** — the same actions as MCP tools, JSON-RPC 2.0 over POST (no
  SSE stream), for the `claude` child's `--mcp-config`: `initialize`,
  `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Tools
  are named `mcp__klaus__<name>` — `current_view`, `search_notes`,
  `find_notes`, `get_notes`, `search_lecture_pdfs`, `list_decks`,
  `list_models`, `model_fields`, `add_note`, `update_note_fields`,
  `add_tags`, `remove_tags`, `open_in_browse` — each mapped onto one `/`
  action (`mcp_args_to_params` reshapes the flat, snake_case MCP
  arguments into that action's params). A tool error comes back as
  `isError: true` with the message, never a JSON-RPC error, so the model
  can recover instead of aborting the turn.

The endpoint reuses `anki_tools`'s existing handlers for note
create/update and for both searches rather than a second implementation.
The child never sees the token on its command line — `--mcp-config`
carries the literal `${KLAUS_TOKEN}`, which Claude Code expands from the
child's own environment (verified live against build 2.1.228) — because
`ps` is readable by every local process. Its read tools are confined to
the library root: `agent_host.decide_permission` denies any
`file_path`/`path`/`pattern` that resolves outside it, which matters
because a lecture page's own text — attached to every turn as the page
record — is untrusted content.
See CLAUDE.md's module map for the approval-dialog and card-tagging
rules.

### Editor-attached state

Attributes on `editor` (all `editor._klausmate_*`, guarded with
`getattr(..., None)` / `is None` checks to stay reload-safe): `_klausmate_panel`
(the PDF drop bar, `_PdfBar`), `_klausmate_pdf_container`, `_klausmate_pdf_tabs`,
`_klausmate_sidebar`, `_klausmate_active_pdf`, `_klausmate_vsplit`,
`_klausmate_target_field_index` / `_target_field_name`, `_klausmate_crop_open`.
Browse-window toggles carry their own: `_klausmate_sidebar_toggle_btn` /
`_klausmate_editor_toggle_btn`. Deck-screen state is down to the drop
wrap's own guards since K-151: `_klausmate_drop_wrapped` / `_drop_orig`.

---

## Configuration

- Defaults: `klausmate/config.json`
- User overrides: stored in `meta.json` by Anki's add-on manager
- UI: **Tools → KlausMate Preferences…** (`manage_models_dialog`; the top bar's star opens it too, and raw JSON is still at **Tools → Add-ons → Klausmate → Config**)
- Key docs: `klausmate/config.md`

Notable keys, as of the 2026-09-15 API-first turn — **two keys and three
model names, no provider anywhere**: `api_key_openai` and
`api_key_anthropic` (both empty by default, both entered in Preferences
→ API keys & models, both living in `meta.json` and never in the repo),
`embedding_model` (`text-embedding-3-large`), `embedding_dimensions`
(`1024`), `reasoning_model` (`claude-sonnet-5` — the pertinence judge's
model since 2026-09-17, and Plan 3's when it lands; never the Claude
Code assistant's), `transcription_model`
(`gpt-4o-mini-transcribe` — the lecture recorder's, also since
2026-09-17), `pdf_match_threshold`, `image_crop_enabled`,
`klausbook_design` (default false — master switch for the design
layer: toolbar/bottombar restyle, backgrounds, frosted panels,
dashboard editing; tools always work),
`heatmap_enabled` (the review heatmap under the deck list),
`dashboard_order` (deck-screen widget order; written by the dashboard's
right-click → Edit Widgets mode — drag to reorder, ⊖/＋ toggle the
per-widget bools). The assistant's own remaining keys are
`assistant_reopen` (default false — reopen the Assistant dock on the
next Anki start) and `assistant_dock_width` (default `420` — the dock's
last width, written by dragging it, not a Preferences row).

**Klaus Plus adds three keys** (2026-09-16), all in `meta.json` like
every other key, none of them ever in the repo:

- `klaus_plus_key` (`""`) — the licence key, `kp_` + 32 hex. Its
  presence is what `plus.key()` calls Plus; there is nothing to verify
  against locally, and nothing here gates anything: the service
  answering 401/402/426 is the only gate.
- `klaus_plus_cache` (`{}`) — not a setting but state Klaus writes:
  `status`, `checked_at`, `period_end`, the quota snapshot and the
  service's own message. A refusal is remembered for 6 hours, then the
  service is asked again; an active verdict is honoured until the
  service refuses it — nothing here re-checks on a timer.
- `klaus_plus_base` (`""`) — empty means the built-in
  `plus.DEFAULT_BASE` (`https://klausmate.fly.dev`), which is what the
  field shows as its placeholder. A General row, there only for a
  staging or self-hosted service.

**Every writer of `klaus_plus_cache` uses `patch_config`, never
`write_config`** — `write_config` replaces the whole stored blob, so a
one-key dict through it wipes the user's API keys and every other
setting. `patch_config` (getConfig → update → writeConfig, hopped to the
main thread) is also the only config writer a background thread may use,
which is what Preferences' **Check** task needs.

`_migrate_config()` (on `profile_did_open`) cleans up legacy `chat_*` /
`claude_*` config keys left over from the deleted Ask-on-Claude feature,
plus (retired 2026-09-01) `assistant_api_key` / `assistant_backend` /
`assistant_token` — the hosted/bring-your-own-key split those keys were
for was cut back to Claude Code's own login before it ever shipped —
keep both cleanups until users have upgraded past them. It also carries
the 2026-09-15 migration: `embedding_api_key_openai` → `api_key_openai`
is RENAMED (its destination default is `""`, so the value really does
carry over) before `_LEGACY_KEYS_DROPPED` scrubs the rest.
`assistant_model` is DROPPED, not renamed — Anki's `getConfig` merges
`config.json`'s defaults under the profile's keys, so `reasoning_model`
is never empty and a copy-into-empty could never fire; `reasoning_model`
takes its default. Scrubbed beside it —
`embedding_provider`, `embedding_api_key_voyage`, `ocr_enabled`,
`ocr_model`, `runtime_auto_setup`, `claude_binary`, `endpoint`,
`pdf_index_max_chunks`, `pdf_match_agg`. Those names appearing in
`__init__.py` are the cleanup, not a surviving feature.

---

## Dependencies

| Component | Source |
|-----------|--------|
| Anki / aqt / gui_hooks | Anki runtime |
| `pypdf` 6.11.0 | Vendored under `klausmate/vendor/` — the **sole** third-party dependency *of the add-on* (the `service/` rows below are a separate program) |
| `PyQt6.QtPdf` / `PyQt6.QtPdfWidgets` | Anki's PyQt6 (PDF viewer; graceful fallback if missing) |
| OpenAI embeddings API | Required for indexing — `openai_client.py` behind `embeddings.py`, with the user's own `api_key_openai` (or, on Klaus Plus, relayed by the service) |
| Anthropic Messages API | `anthropic_client.py` — since Plan 2 (2026-09-17) called by `pertinence.ensure_judged` (the judge, `purpose="judge"`, with the user's own `api_key_anthropic` or relayed by the Klaus Plus service); Plan 3, the assistant on this API, is still unbuilt |
| Claude Code CLI (`claude`) | Optional — the assistant's engine; the user installs and logs into it themselves |
| **Fly.io** | **`service/` only** — one Machine + a 1 GB volume hosts Klaus Plus. Not a dependency of the add-on; nothing in `klausmate/` knows about Fly beyond a default URL string. |
| **Stripe** (`stripe` SDK, API `2024-06-20`) | **`service/` only** — Checkout, the Customer Portal and the webhooks that drive entitlement. No payment code, no price constant and no Stripe id ships in the add-on. |
| **Resend** | **`service/` only, and optional there** — the one welcome email carrying the licence key. Off unless both `RESEND_API_KEY` and `RESEND_FROM` are set; without them the welcome page simply says no email was sent. |

Every network client in the ADD-ON (`openai_client.py`,
`anthropic_client.py`, `plus.py`) is
**stdlib only** (`urllib`) — no `requests`, no third-party SDKs, no
bundled wheels; `embeddings.py` builds on `openai_client.py` and opens
no socket of its own. The three service-side rows above are the
deliberate exception and are the reason `service/` is a separate
program: its `pyproject.toml` pulls fastapi, uvicorn, httpx and stripe,
none of which an AnkiWeb add-on could vendor, and none of which is ever
packaged.
No numpy either — Anki's venv doesn't have it, so `card_index.py`/
`pdf_index.py` do ranking with `math.sumprod` over `array('f')` memoryviews.

---

## Development workflow

1. Symlink or copy `klausmate/` into `addons21/`.
2. Restart Anki (add-ons load at startup; no hot reload).
3. Debug from terminal: macOS `/Applications/Anki.app/Contents/MacOS/anki` — `print()` goes to stdout.
4. Webview JS: `QTWEBENGINE_REMOTE_DEBUGGING=8080` → Chrome DevTools at `http://localhost:8080`.
5. Anki debug console: `pp(obj)`; avoid `traceback.print_exc()` inside `QueryOp` success/failure callbacks (prints `NoneType: None` outside active `except` blocks).

### Packaging

```sh
./scripts/package.sh
```

Produces `dist/klausmate.ankiaddon`. The script stages files to a tempdir, bumps `manifest.json`'s `mod`, and zips with these rules:

- Build from **inside** the staging dir (the zip must NOT contain a `klausmate/` wrapper folder — AnkiWeb rejects those).
- Strip every `__pycache__`/`*.pyc`/`.DS_Store` (AnkiWeb rejects archives that contain them).
- Exclude `meta.json*` (per-user config, may hold API keys — the glob covers timestamped backups too) and all `user_files/` contents except `README.txt`.
- **Never ship `service/`.** It sits outside `klausmate/`, so staging only `$SRC/` already leaves it out; the explicit `--exclude 'service/'` beside the others is the guard for the day someone widens `$SRC` or adds a `klausmate/service/`. Verify after any change to the script: `unzip -l dist/klausmate.ankiaddon | grep service/` must print nothing.

### Tests

Headless logic tests stub `aqt`/`anki` and never touch real Qt widgets — see `.claude/skills/klaus-test/` and `tests/README.md`. Run them all:

```sh
for t in tests/test_*.py; do
  env QT_QPA_PLATFORM=offscreen python3 "$t" || exit 1
done
```

The Klaus Plus service has its own, separate suite (pytest, its own venv,
never part of the add-on loop):

```sh
cd service && .venv/bin/python -m pytest -q
```

### Type checking

```sh
pip install mypy "aqt[qt6]"
mypy klausmate
```

---

## Code conventions (this project)

- Prefer **gui_hooks** over monkey-patching.
- Background work: always `QueryOp` / `without_collection()` for network calls (OpenAI for embeddings and transcription, Anthropic for the pertinence judge); UI updates via `mw.taskman.run_on_main` when needed. The lecture recorder's uploader is the one exception and a deliberate one — a plain daemon thread with a FIFO queue, because it must outlive any single dialog or dock and survive a failed chunk; anything it hands back to Qt (`on_segment`, `page_store.subscribe`) is the CONSUMER's job to marshal.
- Import Qt from `aqt.qt`; QtPdf from `PyQt6.QtPdf` behind try/except (`pdf_viewer.py`).
- Editor-attached state via attributes — see "Editor-attached state" above.
- When adding config keys: update `config.json`, `config.md`, and the relevant section of `manage_models.py`.

---

## What used to be here

Klaus was originally a Copilot-style inline-autocomplete + ⌘K-Ask tool with
a separate chat panel for semantic search. That product surface is gone:
`copilot.js`'s ghost-text/Ask bridge, `claude_api.py`, `settings_ui.py`,
and `chat_dock.py` (the "Klaus panel") were all deleted, along with the
`autocomplete_model` / `ask_model` / `klaus_engine` / `claude_*` config
keys and the Browse natural-language search. (`anki_tools.py` was
deleted in that same pass — it is no longer gone: it came back on
2026-09-01 as the collection tool layer the new assistant calls; see
"The assistant" above.) What remains from that era — the Library,
semantic card matching, the PDF viewer, and image cropping — plus the
assistant added 2026-09-02, is everything above. Don't resurrect
autocomplete/Ask/chat-panel language in docs or comments; if you find
some, it's stale, not a spec.

A second, much shorter-lived surface came and went the same week. Pouya's
2026-09-01 plan for an AI assistant first took the shape of a chat panel
in the Library (`assistant_panel.py`, its own session store
`assistant_session.py`) fed by a direct-API streaming client
(`llm_client.py`) and an advisory tier check (`entitlement.py`), with a
companion podcast-script generator (`podcast.py`) — all deleted
2026-09-02 when Pouya converged the design onto hosting the Claude Code
CLI instead (`assistant_dock.py`: one dock, one engine). Config keys
`assistant_api_key` / `assistant_backend` / `assistant_token` were
dropped with them — there is no separate assistant credential; the
user's own `claude` login is it. `card_forge.py` and `anki_tools.py` are
the two pieces of that plan that DID survive, now wired into the
endpoint rather than dormant. See CLAUDE.md's header and module map for
the exact commits. Don't resurrect a hosted/bring-your-own-key split, a
separate podcast feature, or a Library-panel assistant — the assistant
is `assistant_dock.py`.

A third clearing-out, **2026-09-15**, was the API-first turn (Pouya:
"forget about the local-only approach … an API-first approach to
simplify everything";
`docs/superpowers/specs/2026-09-15-api-first-klaus-design.md`). Gone with
it: the local embedding engine and everything that managed it
(`ollama_client.py`, `ollama_runtime.py`, `ollama_setup.py`, the
"Local model library" Preferences page, `user_files/runtime/`), the
Voyage embedding provider and the whole notion of choosing a provider,
and slide OCR (`page_ocr.py`, its tests, `user_files/ocr/`, the vision
model and its presets) — the PDF's own text layer inside a page record,
plus the page image, replace it. Chunk-level matching inside a page went
too: one page, one vector. Don't resurrect provider-choice,
local-install or OCR language; `openai_client.py`, `page_store.py`,
`cost.py` and `anthropic_client.py` are what arrived in their place —
all four wired now — `anthropic_client.py` got its caller in Plan 2
(`pertinence.ensure_judged`, 2026-09-17); Plan 3, the assistant on the
Messages API, is the one still waiting.

---

## Anki add-on quick reference

<details>
<summary>General Anki add-on patterns (expand when porting or debugging)</summary>

### Key imports

```python
from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showInfo, tooltip
from aqt.operations import QueryOp
```

### Collection access

Use `mw.col` and high-level APIs (`get_card`, `update_note`, …). Avoid raw SQL schema changes.

### Web asset exports

```python
mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
# In webview_will_set_content:
pkg = mw.addonManager.addonFromModule(__name__)
web_content.js.append(f"/_addons/{pkg}/web/copilot.js")
```

### Config

```python
cfg = mw.addonManager.getConfig(__name__)
mw.addonManager.writeConfig(__name__, cfg)
```

### Background ops

```python
op = QueryOp(parent=mw, op=lambda col: work(), success=on_ok)
op.without_collection().run_in_background()  # no collection lock — use for network
```

### Porting notes

- Anki 23.10+ target; WebEngine (async JS, `pycmd` for JS→Python).
- https://forums.ankiweb.net/t/porting-tips-for-anki-23-10/35916

</details>
