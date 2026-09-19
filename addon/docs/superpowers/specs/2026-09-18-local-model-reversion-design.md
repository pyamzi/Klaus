# Local-model reversion: killing API-first, Klaus Plus, and the embedded copilot — design

**Date:** 2026-09-18. **Asked by Pouya:** "remove all of the API and
subscription stuff for now and go back to the local model concept."
Refined over several rounds: the embedded Claude-Code-CLI assistant
("the copilot thing") is dropped too, not kept as a local-model
equivalent — replaced by exposing Klaus's existing MCP server so an
**external** client (Claude Desktop today) can drive Anki directly.
Card-duplicate judging drops to plain cosine thresholds, no reasoning
pass. Lecture recording survives, rewired to a local transcription
binary instead of OpenAI's Whisper API.

**Supersedes** (these stay in git history and on disk as a record of
what was built and why — never deleted, but no longer the live design):
`2026-09-15-api-first-klaus-design.md` (Plans 1 and 2 built; this spec
reverts both), `2026-09-16-klaus-plus-subscription-design.md` (built;
this spec deletes it), `2026-09-01-klaus-assistant-claude-code-design.md`
(built; this spec deletes the dock it describes). Each superseded file
gets a one-line header pointing here, per the doc-inversion section
below — the text itself stays untouched as history.

## Why now, and what "local model concept" resolves to

Four rounds of clarifying questions (see chat) settled the shape:

1. **Embeddings** go back to local — Ollama, no cloud key, no
   subscription.
2. **Duplicate/pertinence judging** loses its reasoning pass entirely —
   back to the pre-judge cosine-threshold-only matching. No local
   stand-in for the judge is being built.
3. **The embedded assistant dock is not being ported to a local model.**
   It's deleted outright. In its place: Klaus's existing internal MCP
   server (`anki_endpoint.py`, today used only to hand tools to the
   `claude` CLI child it spawns) becomes reachable from an **external**
   MCP client the user already runs and pays for separately — Claude
   Desktop. Klaus's job shrinks to "run and expose an AnkiConnect-
   compatible MCP server," not "host a chat UI."
4. **Lecture transcription** survives but moves off OpenAI's Whisper API
   onto a local binary, discovered the same way `agent_host.find_claude`
   discovers the `claude` CLI (`shutil.which` → login shell → known
   paths) — because GUI-launched Anki inherits a minimal `PATH` and
   never sources shell rc files, the same trap `find_claude`'s own
   comment documents.

## Two verified facts that shape the design (don't skip past these)

- **Claude Desktop's `mcpServers` config is stdio-only.** It does not
  speak HTTP or Streamable-HTTP directly for local servers — that's
  Custom Connectors, for remote/cloud servers. `anki_endpoint.py`'s
  `/mcp` route is HTTP. Bridging needs a small stdio↔HTTP shim script
  that Claude Desktop launches as its `command`; there is no way around
  writing that piece. (Source: MCP client transport docs, search cited
  in chat — Claude Desktop supports stdio for local servers, Streamable
  HTTP only via Custom Connectors for remote ones.)
- **ChatGPT is out of scope for this spec.** Its connector/actions story
  wants a public HTTPS endpoint, not a localhost socket. Exposing
  `anki_endpoint.py` — which can WRITE to the collection — to the public
  internet is a real security question this spec does not answer.
  "Claude Desktop now, ChatGPT later if OpenAI ships a comparable local
  transport" is the honest scope; promising it today would be guessing.

## D1 — Delete Klaus Plus

Remove entirely: `service/` (the FastAPI billing service — never shipped
with the add-on per `scripts/package.sh`'s own exclude rule, so deleting
it from this repo loses nothing a user has), `klausmate/plus.py`,
`tests/test_plus.py`. Strip every caller: `embeddings.py`,
`lecture_recorder.py`, `manage_models.py` (the "Klaus Plus" Preferences
group — licence key field, status line, Subscribe/Manage/Check buttons),
`setup_flow.py`.
Config keys `klaus_plus_key`, `klaus_plus_cache`, `klaus_plus_base` are
dropped from `config.json` and scrubbed by `_migrate_config` (the same
pattern every prior key retirement in `__init__.py` already uses).
`openai_client.py` and `anthropic_client.py` both die too, but not from
this decision directly — `anthropic_client.py` loses its sole caller in
D2, `openai_client.py` loses its two callers (`embed`, `transcribe`)
across D4 and D6.

## D2 — Delete the pertinence judge

Remove `klausmate/pertinence.py` and `tests/test_pertinence.py`
entirely. Unwire phase four of `index_queue.py`'s five-phase chain (back
to four phases: `ensure_index` → `ensure_pdf_index` → `ensure_matches` →
`tag_sync.sync_after_matches`) and its `ask_judge`/`RunnerState.phase ==
"judge"` handling. `tag_sync.py` loses `DOUBTFUL_TAG` and
`doubtful_members`; `retention.py` loses the `rejected` parameter
threaded through `pdf_retention`/`note_card_counts`/`priority_rows` (back
to matched-only, no confirmed/rejected split); `pdf_drive.py` loses the
"Doubtful cards…" context-menu item and the `· m doubtful` Cards-cell
suffix; `pdf_map.py` loses the rejected-set argument to its retention
fill. `cost.py` loses `estimate_judge` and the judge row from `PRICES`.
`anthropic_client.py` has no remaining caller once this lands — delete
it and `tests/test_anthropic_client.py` too.

## D3 — Delete the embedded assistant, keep and repurpose its context tracker

Delete: `klausmate/agent_host.py`, `klausmate/assistant_dock.py`,
`klausmate/assistant_sessions.py`, and their tests. Unwire from
`__init__.py`: the `Ctrl+Shift+K` `QAction`, its Tools-menu entry
(`menu_action()`), the Library toolbar button, `_LEGACY_KEYS_DROPPED`'s
assistant-key entries (already-dead scrubbing, leave as-is). Delete the
"Assistant" Preferences page's `assistant_reopen`/Clear-Sessions row from
`manage_models.py` (the free-text `reasoning_model` field on that page
was already orphaned once D2 lands — remove it too, nothing reads it
after the judge is gone).

**`viewer_context.py` is kept, not deleted.** Its only consumer today is
the dock being removed, but "what page is the user looking at" is
exactly the kind of tool an external MCP client benefits from. D5 wires
it into `anki_endpoint.py` as a new read-only tool (`get_current_page` or
similar) rather than leaving it orphaned.

`page_store.py`'s `render_page_png`/page-text plumbing stays — D5's new
tool reads through it the same way `assistant_dock._page_context` used
to.

## D4 — Restore local (Ollama) embeddings

Two shapes exist in this repo's own history, and they are NOT the same
size:

- **Lean, client-only** (`git show f74a09e^:klausmate/embeddings.py`):
  Ollama's `/api/embed` called inline in `embeddings.py` itself, ~220
  extra lines total. Assumes the user already has Ollama installed and
  running (`ollama pull nomic-embed-text`, `ollama serve`) — Klaus
  doesn't manage that.
- **Full runtime management** (`ollama_client.py` 222 lines +
  `ollama_runtime.py` 1013 lines + `ollama_setup.py` 121 lines, deleted
  at commit `1b6fccd`): Klaus detects/installs/starts/stops Ollama
  itself and offers a "Local model library" Preferences page for pulling
  models with progress bars.

**This spec restores the lean shape.** ~1,356 lines of process-
management code is a second project, not a revert, and nothing in the
four clarifying rounds asked for Klaus to manage an Ollama install.
`DEFAULT_PROVIDER` goes back to `"ollama"`, `DEFAULT_MODELS` gains
`"ollama": "nomic-embed-text"`, `provider_name`/`embedding_model` regain
real branching instead of the current hardcoded `"openai"`. Voyage is
**not** restored — no clarifying answer asked for it back, and adding a
second cloud provider back in contradicts "local model concept." If a
cloud fallback is wanted later, that's its own follow-up ask.

`openai_client.py` loses its `embed` caller here; it loses its last
remaining caller (`transcribe`) once D6 lands — delete the module and
its tests together with D6, not here.

Config: `api_key_openai` and `api_key_anthropic` both go. Preferences'
"API keys & models" page reverts toward its pre-2026-09-15 shape: a
provider is a config value (`"ollama"` only, for now — no combo box
needed for a single option, matching the "no model picker" convention
already in place elsewhere), an embedding model free-text field, no key
field at all for the local provider.

## D5 — Make `anki_endpoint.py`'s MCP server reachable from outside Anki

Today: `ThreadingHTTPServer(("127.0.0.1", 0), ...)` binds an ephemeral
port and mints a fresh 32-byte token on every Anki launch
(`AnkiEndpoint.start()`). That's correct for a child process Klaus
itself spawns and can hand the live values to on the command line — it
is unusable for a static `claude_desktop_config.json` entry, which is
written once and expected to keep working across restarts.

**Keep the ephemeral-port-and-per-launch-token scheme exactly as-is**
(the security rationale in `anki_endpoint.py`'s own module docstring
still holds — a stable, guessable port/token pair sitting on disk is a
bigger attack surface than one written fresh per launch). Instead:

1. On `start()`, also write `{host, port, token}` to a well-known
   discovery file: `user_files/mcp_connection.json`, atomic
   tmp+`os.replace`, same pattern every other Klaus JSON store uses.
   Deleted/absent on `stop()`/shutdown, so a stale file can never claim
   the server is up when Anki is closed.
2. New stdlib-only script, `klausmate/scripts/mcp_stdio_bridge.py` (or
   similar — exact path is an implementation-plan decision): reads that
   discovery file, opens a connection to the live `/mcp` endpoint with
   the current token, and relays JSON-RPC frames between its own
   stdin/stdout (what Claude Desktop's `command`/`args` launches) and
   the HTTP endpoint. No third-party deps — stdlib `urllib`/`json`/
   `sys.stdin`/`sys.stdout` only, matching every other client module in
   this repo (`openai_client.py`'s own stdlib-urllib precedent).
3. Preferences grows a small read-only panel (name TBD in the plan)
   showing the exact `claude_desktop_config.json` block to paste, built
   from the live discovery file plus the absolute path to the bridge
   script — copy-to-clipboard, no live network call needed to render
   it.
4. The `Origin`-header refusal in `anki_endpoint.py`'s request handler
   stays untouched — the bridge script is a local process talking plain
   HTTP with no browser involved, so it sends no `Origin` header at all,
   which already passes today's check (only a *present* disallowed
   Origin is refused).

Anki must be running for the bridge to work at all (there is no
"headless Klaus"); document that plainly rather than pretend otherwise.

## D6 (separate phase — spike before build) — Local lecture transcription

`lecture_recorder.Uploader._one` currently calls
`openai_client.transcribe`. There is no local speech-to-text anywhere in
this repo's history to restore — Whisper-via-OpenAI was new work in the
API-first turn, so this is new work now too, not a revert.

**This machine has neither Ollama nor a whisper.cpp binary installed
today** (checked: `command -v whisper-cli whisper-cpp whisper ollama` —
all absent). Ollama itself does not do speech-to-text. The only shape
that fits this repo's standing constraints (no third-party Python deps,
no native code, no venv — `faster-whisper` needs `ctranslate2`, a
compiled dependency Anki's bundled Python cannot install) is shelling
out to a **user-installed** `whisper.cpp` binary (`whisper-cli` or
`main`, depending on build), discovered with the same
`shutil.which` → `[$SHELL, "-lc", "command -v ..."]` → known-paths
ladder `agent_host.find_claude` used — that module is gone by the time
this lands (D3), so this is a pattern to re-implement as a small local
helper (in `lecture_recorder.py` or a new sibling module, an
implementation-plan decision), not an import from deleted code. Model
file path is a Preferences field (whisper.cpp models are a separate
download the user points Klaus at, same relationship Klaus already has
with Ollama models via `ollama pull`).

**Recommend running this as a short spike before committing to the
plan**, not building blind: confirm whisper.cpp's actual CLI invocation
shape (flags, stdout format — plain text vs SRT vs JSON) against a real
build, since that determines the parser `Uploader._one` needs. Until
this lands, `Uploader._one` must fail loudly (a clear "no local
transcriber configured" tooltip once, not a silent drop) rather than
call a deleted `openai_client`.

## Execution shape

**Demolition (D1–D3) is sequential, not swarmable.** `plus.py` is
imported by nine modules; `pertinence.py` by five; deleting either
breaks every concurrent card's `verify:` at once — this is the
agent-board skill's "disjointness is not isolation" case. One session,
cluster by cluster (D1, then D2, then D3), full test suite green between
each cluster, before starting the next.

**Rebuild (D4, D5, and D6 once its spike lands) parallelizes normally**
once the tree is clean — these touch mostly-disjoint files
(`embeddings.py`+config vs. `anki_endpoint.py`+a new script+Preferences
vs. `lecture_recorder.py`) and can be board cards in the usual
file-disjoint-claim shape.

## Doc inversion (its own card, not cleanup-after)

`CLAUDE.md` currently instructs future sessions not to resurrect the
Ollama language, not to invent a second UI surface for the assistant,
and describes Klaus Plus as live — all now wrong. `AGENTS.md`,
`PRODUCT.md`, and `config.md` carry the same API-first assumptions. A
swarm worker reading `CLAUDE.md` mid-rebuild without this update would
fight the very changes it's implementing. This has to land as part of
the plan, not as a follow-up pass: rewrite the affected `CLAUDE.md`
sections in place (module map entries for every deleted/changed module,
the "Klaus went API-first" / "Klaus grew a second AI capability" /
"Klaus Plus" narrative paragraphs get a short "reverted 2026-09-18, see
`docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`"
note rather than being deleted outright — CLAUDE.md's own house style is
to keep dated history, not erase it), and add a one-line "superseded by"
header to the top of each of the three specs listed above.

## Open question for sign-off before the plan is written

D4 assumes the **lean** Ollama restoration (no install/runtime
management, no "Local model library" page). If a runtime-managed
experience is actually wanted, that's a materially bigger plan (~1,350
extra lines) and should be scoped as its own follow-up rather than
folded into this one.
