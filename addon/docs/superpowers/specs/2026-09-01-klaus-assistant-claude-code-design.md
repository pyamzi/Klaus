# Klaus Assistant on Claude Code — Design

**Date:** 2026-09-01
**Status:** approved by Pouya in conversation (shape, then all three sections), 2026-09-01 evening
**Supersedes:** the Ask / Practice / Podcast panel (`assistant_panel.py`, K-162..K-164) and the in-house loop it drove

## 1. Goal

One assistant, docked on Anki's main window, that works like Claudian: an agentic chat whose engine is the **Claude Code CLI** running as a child process, and whose context is **whatever the user is viewing in a Klaus PDF viewer** — the current page as OCR text plus image, and any selected text — attached to every turn. It can read the lecture library, search and read the user's notes, and make cards from the page, every write behind Klaus's approval dialog.

Pouya's words, 2026-09-01: "remove the podcast multiple choice, just have the assistant, and make it work like Claudian, and it is basically viewing whatever we're viewing on the PDF viewer." Runtime: "Wrap the Claude Code CLI, exactly like Claudian." Context: "I want to use GLM-OCR or something similar to get the PDF image and text. You can ensure that manage models classifies each model type." Reach: "Library files + Anki tools via MCP (AnkiConnect)." Placement: one dock following the active viewer. Delivery of AnkiConnect: Klaus serves the protocol itself. Old modules: delete the dead ones now. Features: streaming transcript with inline tool calls and Stop; sessions that persist and resume, one per PDF; selection-aware asking; slash commands.

## 2. Decisions (binding)

| # | Decision | Consequence |
|---|---|---|
| D1 | Engine = Claude Code CLI child process (`claude`, print mode, streaming JSON both ways) | No API keys in Klaus; the user's own Claude login and subscription; Klaus is a host, not a loop |
| D2 | Page context = OCR text via a vision-OCR model served by Ollama (`glm-ocr` default) + the page image + selection, on every turn | New OCR pipeline with a per-page cache; text-layer fallback |
| D3 | Reach = library root as working directory (read-only tools) + Anki tools over MCP speaking AnkiConnect's action protocol | Klaus hosts one localhost HTTP server with two routes |
| D4 | One dock on the main window that follows the last active PDF viewer | A viewer registry every `PdfSidebar` reports into |
| D5 | Klaus serves an AnkiConnect-compatible endpoint itself (no dependency on the AnkiConnect add-on; port 8765 is taken on Pouya's Mac anyway) | Ephemeral port, token-authenticated |
| D6 | Delete `llm_client.py`, `entitlement.py`, `assistant_session.py`, `podcast.py`, `assistant_panel.py` and their tests; keep `card_forge.py` and `anki_tools.py` | Git history keeps them (a494f2d, f1b330b, 026eb36, 120293f, e1c023c) |
| D7 | First version carries: streaming transcript + inline tool lines + Stop; persistent per-PDF sessions; selection-aware asking; slash commands | Nothing else (no plan mode, no model/thinking picker in the dock, no @mentions, no tabs) |

Process architecture (approved): **one long-lived `claude` process per session**, resumed by session id after Stop or a crash. Fallback if the control protocol misbehaves in the spike: one process per turn with `--resume`.

## 3. Components

```
klausmate/
  agent_host.py        Claude Code child: discovery, spawn, stream parse, turn assembly, stop   (aqt-free above divider)
  anki_endpoint.py     localhost HTTP server: "/" AnkiConnect protocol, "/mcp" MCP over HTTP     (aqt-free above divider)
  viewer_context.py    registry of live PDF viewers; current view = last active                  (aqt-free)
  page_ocr.py          page → PNG → OCR text; cache; text-layer fallback                          (aqt-free above divider)
  assistant_dock.py    the QDockWidget: header, transcript, input, Send/Stop, New Session, slash  (Qt)
  assistant_sessions.py per-PDF session-id store + slash-command templates                        (aqt-free)
  ollama_client.py     + generate(model, prompt, images)                                          (existing)
  manage_models.py     + model-type classification, Assistant page                                (existing)
  theme.py             + assistant_dock_qss(night); − KlausAssistantPanel block                   (existing)
  pdf_viewer.py / pdfjs_viewer.py   report page, selection, activity into viewer_context          (existing)
  pdf_drive.py         − third pane; + Assistant toolbar button                                   (existing)
  __init__.py          start/stop endpoint on profile open/close; dock toggle, menu, shortcut     (existing)
scripts/agent_spike.py live probe of the real binary; records fixtures
tests/fixtures/claude_stream/*.jsonl   recorded stream lines the parser tests run against
```

Data flow for one turn:

1. The dock reads `viewer_context.current()` → `(pdf, page, count, selection)`.
2. `page_ocr.context_for(pdf, page)` returns the cached `PageContext` (text, text source, PNG) or the text-layer fallback; OCR of a page never blocks a send.
3. `agent_host.build_turn(user_text, page_context)` produces one stream-json user message.
4. `AgentHost.send(turn)` writes it to the child's stdin; the reader thread emits events; the dock renders them.
5. Tool calls the model makes against `mcp__klaus__*` arrive at `anki_endpoint` over HTTP, run on the main thread through the `anki_tools` handlers, and writes block on the approval dialog.
6. The `result` event ends the turn; the session id is stored for the PDF.

## 4. `agent_host.py`

### 4.1 Binary discovery

`find_claude(config_override: str, env: dict, which: Callable, login_shell: Callable) -> str | None`, in order:

1. `config["claude_binary"]` if non-empty and executable.
2. `shutil.which("claude")` on the current PATH.
3. The login shell's PATH: `[$SHELL, "-lc", "command -v claude"]` with a 3 s timeout (GUI-launched Anki has a minimal PATH; this is Claudian's documented trap).
4. Known locations: `/opt/homebrew/bin/claude`, `/usr/local/bin/claude`, `~/.claude/local/claude`, `~/.local/bin/claude`, `%LOCALAPPDATA%\Programs\claude\claude.exe` on Windows.

The result is cached in memory for the profile session and shown (not written) in Preferences; `claude_binary` is written only when the user sets it.

### 4.2 Spawn

```
<claude> -p --input-format stream-json --output-format stream-json --include-partial-messages --verbose
  --permission-mode default
  --mcp-config '{"mcpServers":{"klaus":{"type":"http","url":"http://127.0.0.1:<port>/mcp","headers":{"X-Klaus-Token":"<token>"}}}}'
  --strict-mcp-config
  --add-dir <library_root>
  --allowedTools Read Grep Glob ToolSearch "mcp__klaus__*"
  --disallowedTools Bash Edit Write MultiEdit NotebookEdit WebFetch WebSearch Task
  --append-system-prompt-file <user_files/assistant/system_prompt.md>
  (--session-id <uuid4> | --resume <session_id>)
  [--model <assistant_model>]
```

`cwd` = the library root (`pdf_handler.library_root()`); when no library root is configured, `cwd` = `user_files/assistant/` and `--add-dir` is omitted. Environment: the parent's, with PATH extended by the directory of the resolved binary. stdin/stdout are pipes; stderr goes to a rotating log `user_files/assistant/claude.log` (cap 1 MB). Windows: `CREATE_NO_WINDOW`.

### 4.3 Turn shape (stdin)

One line, newline-terminated:

```json
{"type":"user","message":{"role":"user","content":[
  {"type":"text","text":"<user text, slash-expanded>"},
  {"type":"text","text":"<context block>"},
  {"type":"image","source":{"type":"base64","media_type":"image/png","data":"<png>"}}
]}}
```

Context block, exact format (`build_context_block(ctx)`):

```
[Klaus context]
Viewing: <display name> — page <n> of <count>   (or: Viewing: nothing — no PDF is open)
Selection:
```<selected text or (none)>```
Page text (<ocr|text layer|none>):
```<page text>```
```

The image block is omitted when no page image is available. The context block is present on every turn, including turns with no PDF (then it says so), so the model never has to guess whether context was dropped.

### 4.4 Events (stdout)

The reader thread parses one JSON object per line and maps them to callbacks; unknown or malformed lines are logged (`print("[klausmate] agent: ...")`) and skipped:

| Line `type` | Meaning | Callback |
|---|---|---|
| `system` / `subtype: init` | session id, tool list, MCP server status | `on_init(session_id, mcp_ok: bool)` |
| `stream_event` with `content_block_delta` / `text_delta` | streamed assistant text | `on_delta(text)` |
| `assistant` | a complete assistant message; `tool_use` blocks name the tool and input | `on_tool_use(name, input)` per block |
| `user` with `tool_result` blocks | a tool finished | `on_tool_result(tool_use_id, is_error)` |
| `result` | turn end: `session_id`, `is_error`, `duration_ms`, `total_cost_usd` | `on_result(info)` |
| `control_request` / `can_use_tool` | Claude Code asks permission | answered on stdin (4.5) |

The exact field paths are pinned by the recorded fixtures from the spike (§12), not by memory.

### 4.5 Approvals

`decide_permission(tool_name, input) -> ("allow" | "deny", message)`: names beginning `mcp__klaus__` are allowed (the endpoint holds the real gate); `Read`/`Grep`/`Glob`/`ToolSearch` are allowed (`ToolSearch` because this build defers MCP tool schemas behind it — denying it cuts off every Klaus tool, found by the spike); everything else is denied with "Klaus allows only reading the library and its own Anki tools." The answer is written as a `control_response` for the request id. The dock shows a denied request as one muted line.

### 4.6 Stop and lifecycle

- `stop()`: SIGINT (Windows: `CTRL_BREAK_EVENT` where available, else terminate), wait 2 s, then `kill()`. The turn is marked stopped; the session id is retained.
- A child that exits while a turn is open: the dock shows one error line with the exit code and the last stderr line; the next send spawns a new child with `--resume`.
- `close()` on profile close, dock destruction, and Anki quit; never leaves an orphan (the reader thread is a daemon and the process handle is joined with a timeout).
- One child at a time per dock; `send` while a turn is running is refused by the UI (Send is Stop then).

### 4.7 System prompt

`user_files/assistant/system_prompt.md` is written by Klaus on first use (and rewritten when its embedded version marker is older than the shipped one). It states: what Klaus is; that every user turn ends with a `[Klaus context]` block describing the page in view; to answer from the page and the library, citing pages as `(p. N)`; that `mcp__klaus__*` tools reach the user's Anki collection; that making a card means one `add_note` per card with a `source_page`, proposed in prose first, and that the user approves each in a dialog; never to claim a card was added unless the tool result says so.

**Spike finding (2026-09-02):** under `--permission-mode default` the control request never fired and a non-disallowed Bash ran unprompted, so the PRIMARY guard is the `--disallowedTools` list; §4.5 stays as belt-and-braces, and the mode is re-probed with `manual` in Task 13's live check.

## 5. `anki_endpoint.py`

### 5.1 Server

`ThreadingHTTPServer` bound to `127.0.0.1:0` (ephemeral port), started on `profile_did_open`, stopped on `profile_will_close`. A random 32-byte hex token is generated per start. Every request must carry `X-Klaus-Token: <token>`; a mismatch is 403. Any request carrying an `Origin` header is 403 (a browser page must never drive the collection). Bodies over 4 MB are 413. Handlers run on the HTTP thread and marshal collection work to the main thread through the `anki_tools.execute_tool` pattern (`mw.taskman.run_on_main` + an `Event`), waiting at most 30 s for reads and 120 s for writes (the approval dialog).

### 5.2 Route `/` — AnkiConnect protocol

Request `{"action": str, "version": 6, "params": {...}}`; response `{"result": ..., "error": null | str}`, HTTP 200 always (AnkiConnect's convention). `version` other than 6 → error `"unsupported version"`. Supported actions (the ONLY ones; everything else → error `"unsupported action"`):

| Action | Params | Result |
|---|---|---|
| `version` | — | 6 |
| `deckNames` | — | list[str] |
| `deckNamesAndIds` | — | {name: id} |
| `modelNames` | — | list[str] |
| `modelFieldNames` | modelName | list[str] |
| `findNotes` | query | list[int] |
| `notesInfo` | notes: list[int] | list[{noteId, modelName, tags, fields:{name:{value,order}}, cards}] |
| `findCards` | query | list[int] |
| `cardsInfo` | cards: list[int] | list[{cardId, noteId, deckName, queue, interval, due, ...}] |
| `addNote` | note: {deckName, modelName, fields, tags, options?} | noteId (after approval) |
| `addNotes` | notes: [...] | list[noteId or null] (ONE approval dialog listing all) |
| `updateNoteFields` | note: {id, fields} | null (after approval) |
| `addTags` | notes, tags | null (after approval) |
| `removeTags` | notes, tags | null (after approval) |
| `guiBrowse` | query | list[int] (opens Browse) |
| `klausSearchNotes` | query, limit=20 | list[{noteId, score, snippet}] — semantic, via `anki_tools.search_notes` |
| `klausSearchLecturePdfs` | query, limit=10 | list[{pdf, page, score, snippet}] — via `anki_tools.search_lecture_pdfs` |
| `klausCurrentView` | — | {pdf, display, page, count, selection} from `viewer_context` |

`addNote` from the agent path additionally requires `params.note.options.sourcePage` (int ≥ 1) when the request carries the `X-Klaus-Agent: 1` header the MCP route sets; a missing source page is an error, never a silent add. Before the dialog, `card_forge.mark_duplicates` runs against the collection and the preview says "similar existing card: <front>" when one scores above its threshold. Added notes get the viewed PDF's `!Library` tag (from `tag_sync`) plus `klaus::assistant`.

### 5.3 Route `/mcp` — MCP over HTTP

JSON-RPC 2.0 over POST; responses are `application/json` (no SSE stream; GET → 405). Methods: `initialize` (echo the client's `protocolVersion`, capabilities `{"tools": {}}`, serverInfo `{"name": "klaus", "version": <addon version>}`, and a `Mcp-Session-Id` header), `notifications/initialized` (202, empty), `ping`, `tools/list`, `tools/call`. Unknown method → JSON-RPC error −32601.

Tools (names as the model sees them, `mcp__klaus__<name>`), each mapped one-to-one onto a `/` action through ONE shared registry (`ACTIONS`), so the two routes cannot drift:

| Tool | → action | Input schema (required *) |
|---|---|---|
| `current_view` | klausCurrentView | — |
| `search_notes` | klausSearchNotes | query*, limit |
| `find_notes` | findNotes | query* (Anki search syntax) |
| `get_notes` | notesInfo | note_ids* |
| `search_lecture_pdfs` | klausSearchLecturePdfs | query*, limit |
| `list_decks` | deckNames | — |
| `list_models` | modelNames | — |
| `model_fields` | modelFieldNames | model* |
| `add_note` | addNote | deck*, model*, fields*, tags, source_page* |
| `update_note_fields` | updateNoteFields | note_id*, fields* |
| `add_tags` / `remove_tags` | addTags / removeTags | note_ids*, tags* |
| `open_in_browse` | guiBrowse | query* |

`tools/call` returns `{"content":[{"type":"text","text": <json result>}], "isError": bool}`; an action error is `isError: true` with the message, never a JSON-RPC error, so the model can recover.

### 5.4 Approval dialog

Writes call `anki_tools`' plain-text preview confirmation on the main thread, opened window-modal with `open()` (K-114: never `exec()`), with the HTTP thread waiting on an `Event`. The dialog text lists deck, model, every field as plain text, tags, and the source page; for `addNotes`, one dialog lists every note. Decline → action error `"declined by user"`; no answer in 120 s → the dialog closes and the action errors `"approval timed out"`.

## 6. `viewer_context.py`

```python
@dataclass
class ViewState: viewer_id: int; pdf_safe: str; display: str; page_index: int; page_count: int; selection: str; path: str
def report_document(viewer_id, pdf_safe, display, path, page_count) -> None
def report_page(viewer_id, page_index) -> None
def report_selection(viewer_id, text) -> None
def activate(viewer_id) -> None          # focus-in, show, click
def forget(viewer_id) -> None            # viewer closed / document cleared
def current() -> ViewState | None        # the last ACTIVATED viewer that still has a document
def subscribe(cb: Callable[[ViewState | None], None]) -> Callable[[], None]   # returns unsubscribe
```

Pure dict state, no Qt; callbacks are invoked synchronously on the calling thread (always the main thread in practice). `PdfSidebar` (both renderers) calls these from its existing document-load and `on_page_changed` paths, from selection changes (native: the selection overlay's change; pdf.js: a new `sel:` bridge message carrying the current selection text, debounced 150 ms in the page), and from `focusInEvent`/`showEvent`. `viewer_id` is `id(sidebar)`. Hosts need no changes: the Library, the Browse pane and the Lecture dock all construct `PdfSidebar`.

## 7. `page_ocr.py`

- `render_page_png(path, page_index, long_edge=1400) -> bytes`: `QPdfDocument` → `render(page, QSize)` → PNG bytes. Aqt glue below the divider; the pure part is everything else.
- `ocr_page(client, model, png, timeout=60.0) -> str`: `client.generate(model, PROMPT, images=[b64(png)])`; `PROMPT` = "Transcribe this lecture slide faithfully as Markdown: keep headings, bullets, tables and equations (LaTeX); describe each figure in one line in brackets; no commentary."
- Cache: `user_files/ocr/<pdf_safe>/<digest12>/<page:04d>.md` and `.png`, where `digest12` is the first 12 hex of SHA-256 over the PDF file's size and mtime and path (cheap, invalidates when the file is replaced). Atomic tmp + `os.replace`.
- `PageContext(display, page_index, page_count, text, text_source: "ocr"|"text-layer"|"none", png: bytes|None, selection)`.
- `context_for(view: ViewState) -> PageContext`: cached OCR text if present; else the page's text layer through `pdf_handler`'s existing extraction (`text_source="text-layer"`); PNG from the cache or rendered now (render is ~50 ms; OCR is not).
- Scheduling (`OcrScheduler`, aqt glue): on every `viewer_context` change, debounce 400 ms, then OCR the current page on one daemon worker (queue of 1 + prefetch of page±1 when the queue is idle). A page already cached is skipped. `ocr_enabled` false, no `ocr_model`, or Ollama unreachable → no OCR, no error dialogs, one log line; the fallback is the text layer.
- `ollama_client.OllamaClient.generate(model, prompt, images: list[str], timeout: float) -> str`: POST `/api/generate` with `{"model","prompt","images","stream": false}` → `response["response"]`.

## 8. Manage Models (`manage_models.py`)

- `classify_model(show: dict) -> str` (pure): `"embedding"` if `"embedding"` in `show["capabilities"]`; `"ocr"` if `"vision"` in capabilities; else `"chat"`. Unknown/missing → `"chat"`.
- Presets: `_EMBED_PRESETS` (existing) and new `_OCR_PRESETS = [("glm-ocr", "GLM-OCR — multimodal OCR for complex documents"), ("deepseek-ocr", "DeepSeek-OCR — token-efficient OCR")]`.
- Local model library: a Type column (Embedding / OCR / Chat) from `classify_model` over `/api/show` per installed model (fetched once per refresh, cached for the dialog's life).
- New **Assistant** page: `ocr_enabled` (Md3Switch), `ocr_model` (combo of installed vision models + the OCR presets, Pull button reusing the existing pull flow), `claude_binary` (read-only auto-detected path with an Override… button), `assistant_model` (free text, empty = Claude Code's default), `assistant_reopen` (reopen the dock where it was on next start), and a Clear Sessions button (deletes `assistant_sessions.json` after a window-modal confirm). All deferred-save through `mark_dirty` / `save_all` like every other row.
- Config keys (config.json + config.md): `ocr_enabled` (true), `ocr_model` ("glm-ocr"), `claude_binary` (""), `assistant_model` (""), `assistant_reopen` (false), `assistant_dock_width` (420). `_migrate_config` deletes `assistant_backend`, `assistant_token`, `assistant_hosted_url`, and any `podcast_*` key if present.

## 9. `assistant_dock.py`

- `QDockWidget` on `mw`, right area, `WA_DeleteOnClose` off (it hides), width persisted; built lazily on first open; `open_assistant()` toggles. Entry points: a Library toolbar button "Assistant" beside Map, Tools → "Klaus Assistant", shortcut `Ctrl+Shift+A` registered through `state_shortcuts_will_change` with the same collision scan `lecture_view` uses for "l". Never `activateWindow`.
- Header: "Following: <display> · p. <n>/<count>" or "No PDF in view"; a selection chip "selection: <first 40 chars>" when a selection exists; a small status dot for the child (idle / running / error) with the MCP status in its tooltip.
- Transcript: read-only `QTextEdit`; user turns right-aligned muted; assistant text streamed in place (deltas appended to the open block); each tool call one collapsed line `▸ <label>` where labels come from a table (`search_notes` → "searched notes: <query>", `get_notes` → "read <n> notes", `add_note` → "added a card to <deck>" / "card declined", `Read` → "read <basename>", …); errors and denials in the muted colour. Rendering is markdown-lite: fenced code → `<pre>`, `**bold**`, `- ` bullets, everything HTML-escaped.
- Input: `QPlainTextEdit`; Enter sends, Shift+Enter breaks a line; Send becomes Stop while a turn runs; New Session; a `/` at the start of the input opens a `QCompleter` over slash commands.
- Empty states: no binary → the transcript shows "Claude Code is not installed or not on the PATH. Install it and run `claude` once to log in." with a link, input disabled, a Re-check button. Binary present but MCP failed at init → a warning line; chat still works without Anki tools.
- Styling: `theme.assistant_dock_qss(night)` (tokens only), joining the `dialog_qss` family; the dock's ground is `chrome` like the panels.

## 10. Sessions and slash commands (`assistant_sessions.py`)

- Store: `user_files/assistant/sessions.json` = `{"by_pdf": {"<pdf_safe>": {"session_id": "<uuid>", "last_used": "<iso>"}}, "global": {"session_id": ..., "last_used": ...}}`, atomic write, corrupt reads as empty. `session_for(pdf_safe | None)`, `remember(pdf_safe | None, session_id)`, `forget(pdf_safe | None)`.
- The dock resumes the session for the followed PDF when the followed PDF changes (stopping any running turn first, after a confirm-free swap: the transcript clears and shows "Resumed session for <display>"); New Session forgets the mapping and spawns fresh.
- Slash commands: `user_files/assistant/prompts/<name>.md`; `list_commands()`, `expand(text, ctx) -> str` replacing `$SELECTION`, `$PAGE`, `$PDF`; a leading `/name` is replaced by the file's content, the rest of the line appended. Defaults written on first open when the folder is empty: `explain.md` ("Explain this page to me as if for an exam, then list the three facts most likely to be tested."), `cards.md` ("Propose Anki cards for this page: one fact per card, front/back, cite the page. Wait for my go-ahead before adding any."), `quiz.md` ("Quiz me on this page, one question at a time; grade my answer before the next.").

## 11. Deletions and edits to existing files

- Delete: `klausmate/llm_client.py`, `klausmate/entitlement.py`, `klausmate/assistant_session.py`, `klausmate/podcast.py`, `klausmate/assistant_panel.py`, and `tests/test_llm_client.py`, `tests/test_entitlement.py`, `tests/test_assistant_session.py`, `tests/test_podcast.py`, `tests/test_assistant_panel.py` (whichever of these exist).
- `pdf_drive.py`: remove the third-pane `AssistantPanel` mount and its splitter share; add the Assistant toolbar button.
- `theme.py`: delete the `KlausAssistantPanel` QSS block; add `assistant_dock_qss`.
- `manage_models.py:1660` copy that promises practice and podcast: rewritten.
- `card_forge.py`: its `podcast.py` cross-reference (line ~178) rewritten; module otherwise untouched.
- `anki_tools.py`: unchanged handlers; gains the shared `ACTIONS` registry consumer only if it does not already expose a name → handler map (if it does, the endpoint reuses it).
- `__init__.py`: endpoint start/stop on profile hooks; dock registration; `_migrate_config` keys.
- CLAUDE.md, AGENTS.md, config.md: rewritten for the new shape; the 2026-08 "embeddings-only" paragraph and the 2026-09-01 "four layers, surface undecided" paragraph both replaced.

## 12. Spike (first task of the plan)

`scripts/agent_spike.py` (throwaway-grade, kept only as the fixture recorder):

1. Starts `anki_endpoint` against a stub collection (the `anki_tools` test stub) on an ephemeral port.
2. Spawns the real `claude` with the §4.2 flags, sends one turn with a rendered slide PNG image block and the text "In one sentence, what is on this slide? Then call current_view.", and reads the stream to `result`.
3. Asserts: `init` lists `mcp__klaus__current_view`; the assistant text mentions something visible on the slide; one `tools/call` reached the endpoint; a `result` arrived with `is_error: false`.
4. Sends a second turn "Add a card about it to deck Default" and asserts an `addNote` reached the endpoint (the stub auto-approves) and, separately, that a disallowed tool request (a Bash call the prompt provokes) produces a `control_request` we answer with deny.
5. Writes every raw stdout line to `tests/fixtures/claude_stream/<case>.jsonl`. The parser tests in `tests/test_agent_host.py` run against those files.

Needs a logged-in Claude Code; if the login is missing the task is `needs-human` and everything downstream is built against the fixture SHAPES documented in §4.4 with the parser's field paths marked provisional in its docstring.

## 13. Error handling, security, performance

- **Errors** never reach Qt as exceptions: every reader-thread callback and every endpoint handler is try/except-log; the dock shows one line per failure. Timeouts: OCR 60 s, endpoint reads 30 s, approvals 120 s, stop grace 2 s, login-shell discovery 3 s.
- **Security:** endpoint on 127.0.0.1 only, token required, `Origin` refused, body cap 4 MB, writes only through the dialog, the agent's own tools read-only and confined to the library root, no shell. The token and port are never written to disk. Session transcripts live where Claude Code keeps them.
- **Performance:** turn assembly < 10 ms (cached PNG + text); OCR async and cached; the dock is built lazily; the endpoint thread pool never touches Qt directly. Anki's startup path gains one server bind (< 5 ms).

## 14. Testing

- `tests/test_agent_host.py`: discovery with a fake PATH and fake login shell; the exact command line; `build_turn` / `build_context_block` (with and without PDF, selection, image); the stream parser over the recorded fixtures (every event type, a malformed line, a truncated line); `decide_permission`; stop semantics with a fake process.
- `tests/test_anki_endpoint.py`: a real `ThreadingHTTPServer` on an ephemeral port hit with `urllib`: token missing/wrong → 403, `Origin` → 403, version 5 → error, every action in §5.2 against the stub collection, `addNote` without source page on the agent path → error, approval decline and timeout paths with an injected approver, the MCP handshake (`initialize`, `initialized`, `tools/list` equals the `ACTIONS` registry, `tools/call` round trip, unknown method −32601), and that both routes map through one registry.
- `tests/test_viewer_context.py`: registry semantics, last-active wins, forget, subscribe/unsubscribe.
- `tests/test_page_ocr.py`: cache keying and atomic writes in a temp dir, fallback selection, scheduler debounce/prefetch with a fake clock and fake client, `generate` payload shape; `render_page_png` under offscreen Qt if `PyQt6.QtPdf` imports, honest SKIP otherwise.
- `tests/test_assistant_sessions.py`: store round trip, corrupt file, slash expansion and defaults.
- `tests/test_manage_models.py` additions: `classify_model`, presets, the Assistant page rows' `mark_dirty` wiring.
- `tests/test_assistant_dock.py` (offscreen): construction, header follows a fake registry, deltas render, tool lines render, Send↔Stop state, empty-state copy, no `exec()` anywhere (grep pin).
- Deletion pins: the deleted module names absent from `klausmate/` and from every test bootstrap; `test_bridge_reentrancy`'s handler roster updated.
- Every new pin is mutated once (house rule).

## 15. Out of scope (explicitly)

Plan mode, model/thinking picker in the dock, @mentions, multiple tabs, voice, the podcast audio half, multiple-choice practice, the hosted/premium tier, AnkiConnect actions beyond §5.2, an SSE stream on `/mcp`, OCR of pages not near the current one, Windows testing on this machine (the code paths exist; verification is a later card).
