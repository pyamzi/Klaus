> Superseded by [Local-model reversion](2026-09-18-local-model-reversion-design.md). Retained as historical design, not current implementation guidance.

# API-first Klaus — design

**Date:** 2026-09-15. **Asked by Pouya:** "forget about the local-only
approach … an API-first approach to simplify everything"; "the embedding
model … can also cause a lot of false positives, we need a reasoning layer
to decide whether or not a card is truly pertinent to the lecture"; "I want
each lecture slide to be embedded on the page-level"; "another tool for
STT, where I can have lecture notes embedded into my PDF slides … the
slide that I am on is the one where that STT is being embedded into."

Answers gathered the same day (one question each): all three local pieces
go API (OpenAI embeddings only; no OCR model; the assistant on the
Anthropic Messages API instead of the Claude Code CLI); Claude judges each
candidate card against its best page, after indexing, as a phase of the
index chain; transcripts attach live to the page in view; the OpenAI
transcription API transcribes; rejected cards stay tagged and gain
`!Library::Doubtful`; retention counts confirmed cards only; two keys in
Preferences with a cost estimate before each paid pass; the assistant
keeps its dock and Klaus runs the tool loop; the transcript feeds the
embedding, the judgment, the assistant's context and a viewer pane;
approach A in three plans; migration by one announced sweep.

## The one seam: the page

Every new capability keys on **(PDF, page)**. A page record holds the
slide's text and what the lecturer said on it; one embedding vector per
page; Claude judges a card against one page; the assistant reads one page.
Existing facts this rests on: `pdf_index.chunk_pages` already chunks per
page; `page_ocr.py` already stores one file per page under
`digest12(path)`; `viewer_context.report_page`/`current()` already track
the page in view; `index_queue._run`'s `after_matches` closure is the one
choke point between scoring and tagging.

## Decisions

### D1 — Providers: OpenAI for embeddings and transcription, Anthropic for reasoning and the assistant

- `klausmate/openai_client.py` (new, stdlib `urllib`, the
  `embeddings._post_json` pattern: one retry on 429/5xx, errors with a
  `user_message()`): `embed(texts, model, dims) -> list[list[float]]`
  (`POST https://api.openai.com/v1/embeddings`) and `transcribe(wav_bytes,
  model, language="en", prompt="") -> str` (`POST /v1/audio/transcriptions`,
  multipart, hand-built boundary; `response_format` `json`).
- `klausmate/anthropic_client.py` (new): `git show
  a494f2d:klausmate/llm_client.py` revived without `HostedBackend`,
  `backend_name`/`backend_from_config`: `LLMError` (with `user_message`),
  `consume_sse(resp, on_text, on_block_start, cancel) -> dict`,
  `text_of(result)`, `Client(get_config).stream(payload, **kw) -> dict`
  over `POST https://api.anthropic.com/v1/messages` with
  `anthropic-version: 2023-06-01`, tool_use and thinking blocks finalised
  from partial JSON on a dropped stream. Plus one non-streaming
  `Client.complete(payload) -> dict` for the pertinence phase. Tests revived
  from `a494f2d:tests/test_llm_client.py`.
- `klausmate/embeddings.py` keeps only `OpenAIEmbeddings`, which calls
  `openai_client.embed`; `DEFAULT_PROVIDER = "openai"`; `index_signature`
  and `signature_matches` stay (every cache compares through them);
  `VoyageEmbeddings`, `OllamaEmbeddings`, `OLLAMA_TIMEOUT_S`, the Voyage
  batch clamp go.
- Config keys: `api_key_openai` (migrated from `embedding_api_key_openai`
  by `_migrate_config`), `api_key_anthropic`, `embedding_model` (default
  `text-embedding-3-large`), `embedding_dimensions` (1024), `reasoning_model`
  (default `claude-sonnet-5`; replaces `assistant_model`),
  `transcription_model` (default `gpt-4o-mini-transcribe`). Keys live where
  they live today: Anki's addon config (`meta.json`), never in the repo.
- Deleted with their tests, config keys and docs: `ollama_client.py`,
  `ollama_runtime.py`, `ollama_setup.py`, `page_ocr.py`; `setup_flow.py`'s
  Ollama copy, probes and runtime offers (the first-run dialog keeps the
  library-root pick and the key prompt); keys `embedding_provider`,
  `embedding_api_key_voyage`, `ocr_enabled`, `ocr_model`,
  `runtime_auto_setup`, `claude_binary`, `endpoint`, `pdf_index_max_chunks`,
  `pdf_match_agg`; the "Local model library (Ollama)" Preferences page and
  the Assistant page's OCR rows.
- Preferences: the Semantic Search page becomes **"API keys & models"**:
  OpenAI key, Anthropic key (both `EchoMode.Password`), embedding model,
  reasoning model, transcription model, the global sensitivity slider (as
  today), Index Now. `save_embed` compares `index_signature` before and
  after and, on a change or a first key, calls
  `index_queue.offer_model_sweep(dlg, prev_sig)`, whose message carries the
  estimate from `cost.py`.

### D2 — The page record (`klausmate/page_store.py`, aqt-free)

- Path `user_files/pages/<pdf_safe>/<digest12>/<page:04d>.json` where
  `digest12` is `page_ocr.digest12` moved here (SHA-256 over path, size,
  mtime, 12 hex chars) — a replaced file gets a fresh directory.
- Record: `{"version": 1, "slide_text": str, "segments": [{"t0": float,
  "t1": float, "text": str}], "updated_at": float}`. `combined_text(rec)`
  is `slide_text` followed by a blank line and the segments' text in time
  order; `text_hash(rec)` is blake2b over `combined_text`, 16 hex chars.
- `slide_text` is filled from `pdf_handler.load_pages(user_files, name)`
  (the existing `contexts/<safe>.json`) by `ensure_records(user_files,
  safe, path, pages)` — idempotent, never overwrites segments.
- `append_segment(user_files, safe, path, page_index, t0, t1, text)`
  atomic (tmp + `os.replace`); a corrupt record reads as empty and is logged.
- `render_page_png(path, page_index, long_edge=1400) -> bytes` moves here
  from `page_ocr` (QPdfDocument; the one Qt import, below a divider).
- `subscribe(cb)` / `_notify(safe, page_index)` so the viewer's transcript
  strip and the assistant refresh when a segment lands (the
  `viewer_context.subscribe` shape: synchronous, a raising subscriber is
  logged).

### D3 — One vector per page (`klausmate/pdf_index.py`)

- `PdfIndex.chunks: list[tuple[int, int, int]]` becomes `pages:
  list[tuple[int, str]]` = `(page_1based, text_hash)`; `INDEX_VERSION = 2`
  (a version-1 manifest reads as absent and rebuilds, the K-167 rule).
- `chunk_pages`, `stride_sample`, `chunk_text_at`, `DEFAULT_MAX_CHUNKS`
  and the `pdf_index_max_chunks` key are deleted; `page_texts(user_files,
  safe, path) -> list[tuple[int, str, str]]` = `(page_1based, text_hash,
  combined_text)` from `page_store` replaces them.
- `retention.ensure_pdf_index` embeds only pages whose `text_hash` differs
  from the stored one (the `card_index` hash rule), so a page whose
  transcript grew re-embeds alone; a page with empty `combined_text` gets a
  zero vector and never wins `best_page`.
- `best_chunk` → `best_page(index, vec) -> tuple[int, float]` (page
  1-based, score); `lecture_view.py` and `retention.match_scores` follow
  the rename. `match_scores` keeps `agg="max"` only; `pdf_match_agg` goes.

### D4 — The pertinence phase (`klausmate/pertinence.py`, aqt-free above its divider)

- `CardText(nid, fields_text, text_hash)`, `PageText(page_1based,
  page_hash, combined_text)`, `Verdict(nid, pertinent, reason, page,
  page_hash, card_hash, model)`.
- `judge(client, model, cards: list[CardText], page: PageText,
  lecture_display: str) -> list[Verdict]`: one Messages request per batch of
  up to `BATCH = 8` cards, `tool_choice` forced to a single tool
  `record_verdicts` (declared with `strict: true`, `additionalProperties:
  false` and every field `required`, so the input validates exactly)
  whose input schema is `{"verdicts": [{"nid": int, "pertinent": bool,
  "reason": str}]}`; the system prompt states the test
  ("would studying this card be reasonable preparation for THIS slide's
  content, not merely the same subject") and forbids guessing. A card
  missing from the tool input, or a malformed input, yields NO verdict for
  that card (unjudged, never doubtful).
- Persistence: `user_files/pdf_index/<safe>/judged.json` = `{"version": 1,
  "model": str, "verdicts": {nid: {"pertinent", "reason", "page",
  "page_hash", "card_hash"}}}`; `load_judged`/`save_judged` atomic. A
  verdict is stale when the card's text hash or its page's hash changed, or
  the model changed.
- `candidates(matches, threshold)` = nids at/above threshold (the same
  expression `tag_sync.sync_after_matches` computes); `best_page` per
  candidate comes from `retention.match_scores` recording the argmax page
  per note (a new `pages: dict[int, int]` beside the scores, cached in
  `matches.json` as `"pages": {nid: page}`).
- Index chain (`index_queue._run`): a fourth phase `after_matches` →
  `pertinence.ensure_judged(mw, name, matches, on_done, on_error, cancel,
  on_progress)` → `tag_sync.sync_after_matches(mw, name, matches,
  doubtful=rejected_nids)`. Before the first paid batch of a job the runner
  shows the estimate (`cost.estimate_judge`) through a window-modal
  `QMessageBox.open()` with **Judge** and **Skip**; Skip leaves the
  candidates unjudged. `RunnerState` gains `phase` so `status_line` can say
  "judging 12/40".
- Failure: a batch that fails on the network (after the client's one retry)
  leaves its cards unjudged with one `[klausmate]` line; the job still
  finishes and tags.

### D5 — Tags and counts

- `tag_sync.DOUBTFUL_TAG = "!Library::Doubtful"` (a reserved leaf, never
  renamed by reconcile). `sync_after_matches(parent, pdf_name, matches, *,
  doubtful: set[int] | None = None, on_done=None)`: the lecture tag's
  members are every match at/above threshold, as today; the Doubtful tag's
  members are the union of rejected nids across every PDF, computed from
  every `judged.json` (`pertinence.all_rejected(user_files)`), applied with
  the same `apply_membership` in the same `CollectionOp`. `sync_after_threshold`
  and `sync_after_clear_overrides` recompute both sets from the caches;
  neither re-judges.
- `retention.pdf_retention(...)`, `note_card_counts(...)` and
  `priority_rows` take `rejected: set[int]` (from `judged.json`) and score
  and count **confirmed = matched − rejected**; each row gains
  `doubtful_count`. `library_explorer` shows the Cards cell as
  `n · m doubtful` when `m > 0`; the row's context menu gains **Doubtful
  cards…** → Browse on `tag:!Library::Doubtful "tag:<lecture tag>"`.
- No per-card overrule UI in this design (a board card).

### D6 — The lecture recorder (`klausmate/lecture_recorder.py`)

- Pure core above the divider: `Chunker` state machine — `start(page,
  t)`, `page_changed(page, t)`, `tick(t)`, `stop(t)` → emits `Chunk(page,
  t0, t1)` boundaries: a chunk closes at `CHUNK_S = 30` seconds or on a page
  change, whichever first, so text never straddles pages; pinned without
  Qt.
- Qt glue below: `Recorder` over `PyQt6.QtMultimedia.QAudioSource` with a
  16 kHz mono int16 `QAudioFormat` (the `aqt.sound.QtAudioInputRecorder`
  shape; Anki bundles `QtMultimedia`), reading the device into a buffer and
  writing each `Chunk` as a WAV (`wave` module) to
  `user_files/recordings/<pdf_safe>/<t0:.0f>-p<page:04d>.wav`.
- Page source: `viewer_context.current()` at start and every
  `viewer_context.subscribe` notification (the page the user is looking
  at); no PDF in view → Record is disabled with a tooltip.
- Upload: one daemon worker takes closed chunks FIFO, calls
  `openai_client.transcribe(wav, transcription_model, prompt=<previous
  segment text>)`, and on success `page_store.append_segment(...)` then
  unlinks the WAV; on failure the WAV stays and the queue continues; the
  next Record on that PDF re-queues leftovers. Empty transcripts (silence)
  are dropped.
- UI: **● Record / ■ Stop** on `_PanelBar` (the PDF dock, `__init__.py`)
  and on the Lecture dock's header; while recording the bar shows elapsed
  time and "n to transcribe"; stopping schedules `index_queue.request_pdf`
  for that PDF (behind the sweep's cost prompt) so the changed pages
  re-embed. A **transcript strip** under the page in `PdfSidebar` (both
  renderers; pdf.js receives the text through the existing bridge as a
  `klausSetTranscript` call, the `klausSetAnnotations` shape) shows the current page's segments, collapsible,
  live via `page_store.subscribe`. Colours through `theme` tokens only.

### D7 — The assistant on the Messages API (`klausmate/agent_host.py` rewritten)

- `AgentHost(get_config, user_files)`: `send(user_text, view, on_text,
  on_tool, on_done, on_error, cancel)` builds a Messages request — system
  = `assistant_sessions.ensure_system_prompt`; messages = the PDF's stored
  conversation plus the new user turn, whose first content block is the
  page context (`page_store` `combined_text`, the selection, then the page
  PNG as an image block); tools = `anki_tools.TOOL_SPECS` — and runs the
  loop: `anthropic_client.Client.stream` with text deltas to `on_text`; a
  `tool_use` block is executed through `anki_tools._HANDLERS[name](col,
  args, ctx)` on the main thread (`mw.taskman.run_on_main` + Event, the
  `anki_tools._run_on_main_sync` helper), its result appended as a
  `tool_result` block, and the loop continues, capped at `MAX_TOOL_ROUNDS
  = 12`. Writes (`create_note`, `update_note`) go through the window-modal
  approval dialog moved from `anki_endpoint.qt_approver` into
  `anki_tools.confirm_write` (Cancel stays the default; duplicate check by
  Anki text search; agent notes tagged `klaus::assistant`,
  `klaus::from::<pdf_safe>`, `klaus::page::<n>`, never the `!Library` tag).
- Stop: `cancel` is a `threading.Event` checked per SSE line; the loop
  returns with the partial text and no tool call.
- `assistant_sessions.py`: `sessions.json` (Claude Code session ids) →
  `conversations/<pdf_safe>.json` = `{"version": 1, "messages": [...],
  "summary": str}`; `remember`/`forget`/`clear_all` keep their names;
  history sent to the API is the last `HISTORY_MESSAGES = 40` messages after
  the summary, and when the file exceeds 80 messages the older half is
  folded into `summary` by one Messages call. Slash commands and the
  versioned system prompt are unchanged.
- `assistant_dock.py` keeps its shell, `_Bridge`, transcript, Stop, New
  Session, the completer and the `Ctrl+Shift+K` action; `_ensure_child`,
  `_begin_async_stop`/`_poll_stop`, `_resume_attempt` and the process
  lifecycle go; a turn is a worker thread calling `AgentHost.send` whose
  callbacks emit through `_Bridge`.
- Deleted: `anki_endpoint.py` (server, `/mcp`, token, `X-Klaus-Agent`
  header — its tagging rule moves into `anki_tools._h_create_note` via
  `ctx["agent"] = True`), `find_claude`/`find_claude_cached`/`child_env`/
  `command_line`/`decide_permission`/`control_response`/`classify`/
  `resume_failed`, the `tests/fixtures/claude_stream/` fixtures,
  `scripts/agent_spike.py`, the Preferences "claude binary" row. The
  library-root confinement becomes a check inside the one handler that
  reads files (`search_lecture_pdfs` returns page text through
  `page_store`, never a path the model chose).
- Privacy: AGENTS.md's paragraph names every network call — OpenAI
  (embeddings, transcription), Anthropic (pertinence, the assistant); the
  page image and text go to Anthropic only when the dock is used.

### D8 — Cost and migration (`klausmate/cost.py`, pure)

- `PRICES` = per-model constants `{"text-embedding-3-large": (0.13, None),
  "claude-sonnet-5": (2.0, 10.0), "gpt-4o-mini-transcribe": ...}` in
  dollars per million tokens (input, output) or per minute for audio;
  editable, dated in a comment.
- `estimate_embed(chars) -> Estimate`, `estimate_judge(n_cards,
  page_chars_mean, batch=8) -> Estimate`, `estimate_transcribe(seconds)
  -> Estimate`; `Estimate(tokens, dollars)`; `format_estimate(e)` →
  `"~12,400 tokens · about $0.04"`. Tokens ≈ chars / 4.
- Migration sweep: on the first save of an OpenAI key, or an
  `index_signature` change, `offer_model_sweep` shows the estimate for
  every note plus every PDF with an index on disk, asks once, then
  re-indexes in the background; caches whose signature no longer matches
  are dropped (`signature_matches`, never `==`). `_migrate_config` renames
  `embedding_api_key_openai` → `api_key_openai`, `assistant_model` →
  `reasoning_model`, and scrubs the deleted keys.

## Plans

1. **Page store and API clients** — D1, D2, D3, D8, the deletions of the
   Ollama runtime and OCR, Preferences, `_migrate_config`, docs.
2. **Pertinence and the lecture recorder** — D4, D5, D6, `RunnerState.phase`,
   the transcript strip, docs.
3. **The assistant on the Messages API** — D7, the endpoint and CLI
   deletions, docs.

Each plan is executed as a board-coordinated swarm (file-disjoint cards,
a reviewer per card, orchestrator commits, a final whole-plan review with
one fix wave); each ends with a needs-human live checklist.

## Testing

- Aqt-free pins: page record round-trip, `combined_text` order,
  `text_hash` staleness; one row per page and the hash-only re-embed;
  `best_page`; the estimate arithmetic; `judge`'s parser (missing nid →
  unjudged; malformed → unjudged; never doubtful); `judged.json` staleness
  on card hash, page hash and model; the Doubtful set's membership and the
  confirmed counts; the `Chunker` state machine (30 s cap, page change
  closes early, no straddle); SSE parsing from recorded fixtures for both
  clients (`tests/fixtures/openai/`, `tests/fixtures/anthropic/`); the tool
  loop against a fake client (a tool_use round trip, the 12-round cap,
  Stop mid-stream).
- Offscreen Qt pins: Record on the dock bar and the Lecture dock; the
  transcript strip renders and updates on a `page_store` notification; the
  approval dialog defaults to Cancel; Stop cancels a fake stream through
  `_Bridge`.
- Paid smokes behind `KLAUS_LIVE_API=1`, one per client, skipped
  otherwise: embed one page; transcribe a five-second WAV; one judged batch;
  one assistant turn with a tool call.
- Never the user's running Anki; never the real `user_files`.

## Behaviour lost on purpose

- Local embeddings and the managed Ollama runtime; OCR of slides (the
  text layer plus the page image replace it); the Claude Code CLI as the
  assistant's engine (and with it Claude Code's own subscription billing —
  the assistant now bills the Anthropic key); the AnkiConnect-compatible
  endpoint and MCP server (nothing external drives Klaus).
- Chunk-level matching inside a page; `pdf_match_agg`'s `top3_mean`.
