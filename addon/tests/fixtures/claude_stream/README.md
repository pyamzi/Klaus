# `claude_stream` fixtures

Raw stdout, one JSON object per line, recorded by `scripts/agent_spike.py`
against the **real** `claude` binary. Not synthesized, not hand-edited.
Task 2's parser tests (`tests/test_agent_host.py`) read these files; where a
field path here differs from design §4.4's table, **this file wins** — the
parser should be written and pinned against what's below, not against
memory or the spec text.

- **Claude Code version:** `2.1.228 (Claude Code)`
- **Recorded:** 2026-09-02
- **Command per case** (from `scripts/agent_spike.py::run_case`):
  ```
  claude -p --input-format stream-json --output-format stream-json \
    --include-partial-messages --verbose --permission-mode default \
    --mcp-config '{"mcpServers":{"klaus":{"type":"http","url":"http://127.0.0.1:<port>/mcp",
                   "headers":{"X-Klaus-Token":"<token>"}}}}' \
    --strict-mcp-config --add-dir <tmpdir> \
    --allowedTools Read Grep Glob "mcp__klaus__*" \
    --disallowedTools Edit Write MultiEdit NotebookEdit WebFetch WebSearch Task \
    --session-id <uuid4>
  ```
  matching design §4.2 (this spike passes `--session-id`, not `--resume`,
  and has no `--append-system-prompt-file`/`--model` since the spike needs
  neither).

## 0. Read this before writing the parser — methodology note

This spike ran from inside a Claude Code agent session itself (this very
swarm task is a `claude` subprocess). That matters for two reasons, both
confirmed empirically below, not assumed:

1. **The spawned child inherits the parent shell's environment by
   default**, including `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT=claude-desktop`,
   a messaging socket/token, and `CLAUDE_CODE_HOST_SESSION_ID`. The first
   full run (all 3 cases) was made this way; I then patched
   `run_case` to spawn with those keys stripped (everything prefixed
   `CLAUDE_CODE_`, plus `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT`,
   `AI_AGENT`, `CLAUDE_AGENT_SDK_VERSION`, `BAGGAGE`) and re-ran all three
   cases a second time. **The fixtures in this directory are from the
   second (clean-env) run.** A copy of the first (nested-env) run is not
   checked in but the diff between the two runs is summarized in §4 below
   — it matters for one specific question (permission gating) and doesn't
   matter for the other two.
2. Even with that env stripped, the child **still** reports the full
   roster of skills/plugins/agents/slash-commands installed under this
   machine's `~/.claude/` (see §3) — that part is not env-inheritance,
   it's simply this account's on-disk Claude Code configuration
   (`~/.claude/settings.json`'s `enabledPlugins`, `~/.claude/skills/`,
   etc.), which `claude` reads regardless of how it was launched. **A
   real Klaus user's `claude` will do the same** — Klaus spawns the
   user's own already-configured `claude`, not a clean/sandboxed one (design
   D1). Whatever plugins/skills/MCP-servers a given user has installed
   globally will show up in `agent_host.py`'s init event too. This is not
   a spike artifact to be dismissed; it is the real shape of the problem.

## 1. Outcome per case

| Case | File | Outcome |
|---|---|---|
| Image block | `turn_with_image.jsonl` | **Accepted.** No error. The model correctly read the rendered slide ("This slide states that in the nephron, the proximal tubule reabsorbs 65% of ... solute") and separately called `current_view` via MCP, reporting page 3 of 10. No `--input-format` fallback was needed. |
| MCP tool call | `tool_call.jsonl` | **Round trip succeeded.** `add_note` reached the stub HTTP endpoint with the exact `{deck, fields, source_page}` shape design §5 implies, and the stub's canned `{"noteId": 1234567890}` came back through to the model, which reported it added. |
| Permission round-trip | `permission_denied.jsonl` | **Not exercised — see §4.** The disallowed-by-omission `Bash` tool ran `ls` and returned its output with **zero** `control_request`/`can_use_tool` events anywhere in the stream, and `result.permission_denials` is `[]`. This is the one case that did not do what the design assumes; treat every `control_request` field path below as **provisional, not pinned**. |

`RESULT:` printed by the script itself was `FAILED — read the fixtures`,
solely because of the case 3 assertion `any('"control_request"' in x for x
in l3)`. Every other assertion in `main()` (init subtype, `mcp__klaus__*`
in the stream, the tool actually reaching the stub server, the slide text
being read back) passed on both the nested-env and clean-env runs.

## 2. Field paths per event type (design §4.4 table)

### `system` / `subtype: "init"`

One per case, always the first line.

```json
{"type":"system","subtype":"init","cwd":"/private/var/folders/.../klaus-spike-kgsj9z1y","session_id":"88c3ed54-de59-4d5e-984b-edd29bc6855d","tools":["Bash","CronCreate", "...", "mcp__klaus__add_note","mcp__klaus__current_view"],"mcp_servers":[{"name":"klaus","status":"connected"}],"model":"claude-sonnet-5","permissionMode":"default", "...", "capabilities":["interrupt_receipt_v1","interrupt_cancel_queued_v1","msg_lifecycle_v1"]}
```

| Field | Path | Notes |
|---|---|---|
| session id | `.session_id` | matches spec |
| tool list | `.tools` | flat array of strings; **includes every built-in tool the account has** (Bash, CronCreate/Delete/List, DesignSync, EnterWorktree/ExitWorktree, ListAgents, Monitor, PushNotification, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Skill, TaskCreate/Get/List/Output/Stop/Update, ToolSearch), not just what `--allowedTools`/`--disallowedTools` named — see §3 |
| MCP status | `.mcp_servers` | **array of `{name, status}`, not a boolean.** Spec's `on_init(session_id, mcp_ok: bool)` must compute `mcp_ok = all(s["status"] == "connected" for s in ev["mcp_servers"])`; there is no literal `mcp_ok` key |
| permission mode actually applied | `.permissionMode` | echoes back the exact string passed to `--permission-mode`, **including `"default"`, which is not one of `claude --help`'s documented choices** for this version (`acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`) — it's accepted silently rather than rejected. See §4. |
| model | `.model` | `"claude-sonnet-5"` in every case (no `--model` override was passed) |
| cwd | `.cwd` | the spike's tmpdir, matches `--add-dir` |

Not in spec, present in every run: `.agents`, `.skills`, `.slash_commands`,
`.plugins`, `.capabilities`, `.apiKeySource`, `.claude_code_version`,
`.output_style`, `.uuid`, `.memory_paths`, `.messaging_socket_path`,
`.fast_mode_state`. None of these are needed by `agent_host.py`; the
parser should ignore unknown keys on this event rather than validate an
exhaustive shape.

### `system` / other subtypes (not in spec's table)

Two more `system` subtypes were observed and should be tolerated (logged
and skipped, per §4.4's own "unknown lines are skipped" rule), not
treated as errors:

```json
{"type":"system","subtype":"status","status":"requesting","uuid":"...","session_id":"..."}
```

The clean-env run only showed `status`; the discarded nested-env run also
showed `post_turn_summary` and `thinking_tokens` subtypes at least once.
None carry data `agent_host.py` needs.

### `stream_event` with `content_block_delta` / `text_delta`

```json
{"type":"stream_event","event":{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"This"}},"session_id":"88c3ed54-de59-4d5e-984b-edd29bc6855d","parent_tool_use_id":null,"uuid":"3aba5dc4-b764-4344-a0c6-ec9ec41d69cf"}
```

| Field | Path | Notes |
|---|---|---|
| delta text | `.event.delta.text` | matches spec's implied path (`content_block_delta`/`text_delta` nested under `.event`) |
| discriminators | `.event.type == "content_block_delta"` and `.event.delta.type == "text_delta"` | both must be checked; `.type` at the outer level is always `"stream_event"` |

**Not in spec:** `stream_event` also wraps `message_start`, `content_block_start`
(carries the *partial* tool_use block — `name` and empty `input` — as it
starts streaming, before the complete `assistant` line arrives),
`content_block_delta` with `delta.type` of `input_json_delta` (streamed
tool-input JSON, character by character), `thinking_delta`, and
`signature_delta`, plus `content_block_stop`, `message_delta`,
`message_stop`. `agent_host.py`'s parser must switch on `.event.type` +
(when applicable) `.event.delta.type`/`.event.content_block.type` and
silently ignore every combination it doesn't act on — do not assume
`content_block_delta` always means text.

### `assistant` (complete message)

```json
{"type":"assistant","message":{"model":"claude-sonnet-5","id":"msg_011Cee2UTHDQ1Xtq2q26P94z","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_017JSbnbcbGHJUzxngnoKY6Y","name":"mcp__klaus__current_view","input":{},"caller":{"type":"direct"}}],"stop_reason":null, "...": "...","request_id":"req_011Cee2USGwP1jvWYR5PY4eM","tool_use_meta":[{"id":"toolu_017JSbnbcbGHJUzxngnoKY6Y","display_name":"Current View","server_display_name":"klaus"}]}}
```

| Field | Path | Notes |
|---|---|---|
| tool name | `.message.content[i].name` | matches spec, for blocks where `.message.content[i].type == "tool_use"` |
| tool input | `.message.content[i].input` | matches spec |
| tool_use id | `.message.content[i].id` | **not named in spec's table but required** — it is the `tool_use_id` the later `user`/`tool_result` line correlates back to |

Extra, not in spec: `.message.content[i].caller.type` (`"direct"` in
every observed call); a sibling **top-level** `tool_use_meta` array (one
entry per MCP `tool_use` block in that message) carrying `{id,
display_name, server_display_name}` — a nicer label than the raw
`mcp__klaus__current_view` name for the dock's inline tool line, if
Task 2/3 wants it.

**The single most important finding at this event type**: before either
MCP tool (`current_view`, `add_note`) was ever called, the model first
called a **built-in, non-`mcp__klaus__` tool**:

```json
{"type":"tool_use","id":"toolu_01MFsCw1j69KVAu9AJfA59Da","name":"ToolSearch","input":{"query":"select:mcp__klaus__current_view","max_results":1},"caller":{"type":"direct"}}
```

See §3 — this changes what `decide_permission` must allow.

### `user` with `tool_result` blocks

Two distinct shapes were observed, both under `.message.content[i]` where
`.type == "tool_result"`:

**A real tool result** (Bash, or an MCP tool that's already resolved):

```json
{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_011At3Kikh4ubMh7hhx3Ayxy","type":"tool_result","content":"notes.txt","is_error":false}]},"parent_tool_use_id":null,"session_id":"...","uuid":"...","timestamp":"...","tool_use_result":{"stdout":"notes.txt","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false}}
```
```json
{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_017JSbnbcbGHJUzxngnoKY6Y","type":"tool_result","content":[{"type":"text","text":"{\"pdf\": \"spike.pdf\", \"page\": 3, \"count\": 10, \"selection\": \"\"}"}]}]},"parent_tool_use_id":null,"session_id":"...","uuid":"...","timestamp":"...","tool_use_result":[{"type":"text","text":"{\"pdf\": \"spike.pdf\", \"page\": 3, \"count\": 10, \"selection\": \"\"}"}]}
```

| Field | Path | Notes |
|---|---|---|
| tool_use_id | `.message.content[i].tool_use_id` | matches spec, correlates to the `assistant` event's `content[i].id` |
| is_error | `.message.content[i].is_error` | **present (`false`/`true`) only for the native `Bash` result. Absent (`KeyError`, not `null`) on both observed MCP tool_result blocks.** `agent_host.py` must do `block.get("is_error", False)`, never `block["is_error"]`, or every successful MCP call trips a `KeyError`. |
| result content | `.message.content[i].content` | shape varies: a bare **string** for Bash, a **list of `{type:"text", text:"<json>"}`** for an MCP tool result (the MCP tool's own JSON-RPC `content` array, passed through verbatim — `text` is a *string* that itself needs a second `json.loads` to reach `{"pdf":...}` / `{"noteId":...}`) |

Extra, not in spec: a sibling **top-level** `tool_use_result` field that
mirrors `.content` in a slightly different shape (a dict for Bash, the
raw list for MCP) — redundant with `.message.content[i].content`; safe to
ignore, `agent_host.py` doesn't need it.

**A deferred-tool resolution** (the `tool_result` for a `ToolSearch`
call, not a real tool call — see §3):

```json
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01MFsCw1j69KVAu9AJfA59Da","content":[{"type":"tool_reference","tool_name":"mcp__klaus__current_view"}]}]},"parent_tool_use_id":null,"session_id":"...","uuid":"...","timestamp":"...","tool_use_result":{"matches":["mcp__klaus__current_view"],"query":"select:mcp__klaus__current_view","total_deferred_tools":18}}
```

`.message.content[i].content[0].type == "tool_reference"` here, not
`"text"`. If `agent_host.py` renders one dock line per `tool_use`/
`tool_result` pair, this pair is a discovery step, not a real Klaus tool
invocation — Task 2/3 should decide whether to show it or fold it away.

### `result`

```json
{"is_error":false,"duration_api_ms":7090,"num_turns":3,"stop_reason":"end_turn","session_id":"88c3ed54-de59-4d5e-984b-edd29bc6855d","total_cost_usd":0.20991520000000002,"usage":{...},"modelUsage":{...},"permission_denials":[],"terminal_reason":"completed","subtype":"success","result":"You're currently viewing page 3 (of 10) in spike.pdf.","ttft_ms":3356,"time_to_request_ms":262,"type":"result","duration_ms":6667,"uuid":"..."}
```

| Field | Path | Notes |
|---|---|---|
| session id | `.session_id` | matches spec |
| is_error | `.is_error` | matches spec; top-level, boolean |
| duration | `.duration_ms` | matches spec **exactly this key** — note there is *also* a `.duration_api_ms` (time inside the API call only, smaller); spec's `on_result` wants `.duration_ms` |
| cost | `.total_cost_usd` | matches spec |

Extra and worth pulling into `on_result`'s info dict even though spec
doesn't list them: `.result` (the final assistant text as a plain
string — handy for a non-streaming fallback or a log line),
`.permission_denials` (an array — **empty in every one of the six runs
recorded for this spike**, i.e. this field alone would tell
`agent_host.py` "no denials occurred" even without ever seeing a
`control_request`; Task 2/3 may want to surface this rather than, or in
addition to, denial events), `.stop_reason`, `.num_turns`, `.subtype`
(`"success"` in every case here).

### `control_request` / `can_use_tool`

**Not observed. Zero occurrences across all six case-runs** (three cases
× two full spikes — the discarded nested-env run and the kept clean-env
run). Every field path design §4.4/§4.5 assumes for this event
(`request_id`, `tool_name`, the `control_response` envelope) is
**provisional, sourced from the spec/Claudian precedent, not from any
real observed line.** See §4 for what was tried and what's still open.

The shape `scripts/agent_spike.py` sends *if* a `control_request` ever
arrives (never confirmed accepted by the real binary, since it was never
prompted for) is:

```json
{"type": "control_response", "response": {"subtype": "success", "request_id": "<echoed>", "response": {"behavior": "deny", "message": "Klaus allows only reading the library and its own Anki tools."}}}
```

## 3. Actionable finding: deferred tools (`ToolSearch`) must be allowed

In every case that used an MCP tool, the model did not call
`mcp__klaus__current_view` or `mcp__klaus__add_note` directly on first
use. It called the built-in `ToolSearch` tool first
(`{"query":"select:mcp__klaus__current_view","max_results":1}`), got back
a `tool_result` confirming the tool was resolved
(`{"matches":["mcp__klaus__current_view"],"total_deferred_tools":18}`),
and only then issued the real `tool_use` for the MCP tool.

This is **not a quirk of the spike's harness** — it reproduced identically
across both the nested-env and clean-env runs, and it's driven by however
many tools/skills/MCP servers are registered in the invoking account's
`~/.claude/` configuration (`total_deferred_tools: 18` here). Since
design D1 spawns the **user's own already-configured `claude`** rather
than a clean/sandboxed one, any real user with enough of their own
plugins/skills/MCP servers installed will hit the same deferral, and
Klaus's two tools will be deferred right alongside all the user's own
tools.

Design §4.5's rule as written — *"names beginning `mcp__klaus__` are
allowed; `Read`/`Grep`/`Glob` are allowed; everything else is denied"* —
would **deny `ToolSearch`**, which would make every `mcp__klaus__*` tool
permanently unreachable for any user whose account defers tools, with no
error surfaced beyond the model silently never being able to complete the
lookup. `decide_permission` needs an explicit allow for `ToolSearch` (or
some equivalent discovery-only built-in) alongside the `mcp__klaus__*`
prefix rule. Flagging this for whoever implements §4.5 — it did not seem
safe for a spike to silently patch the design.

## 4. Open finding: the permission round-trip did not fire

Across both runs (six case-executions total), the `Bash` tool — present
in the `init` tool list, named in neither `--allowedTools` nor
`--disallowedTools` — was simply invoked and its result returned, with no
`control_request` at any point and `result.permission_denials: []`.
Ruled out, concretely, not by assumption:

- **Not the settings files.** This repo's `.claude/settings.json` has
  only `deny` rules for `klaus_note/user_files/**` and
  `meta.json` — nothing that would allow-list `Bash`. The account's
  `~/.claude/settings.json` has no `permissions` block at all.
- **Not env-inheritance from the nested host session.** Stripping every
  `CLAUDE_CODE_*`/`CLAUDECODE`/`AI_AGENT`/messaging-socket variable
  before spawning (§0) made no difference — identical outcome, same
  empty `permission_denials`, same absence of `control_request`, on a
  fresh `--session-id` each time.

What's left unverified, because it would mean a third real invocation
beyond what this task's "run each case once" budget covers: **whether
`--permission-mode default` is actually a recognized mode at all.**
`claude --help` on this exact binary (2.1.228) lists the `--permission-mode`
choices as `acceptEdits`, `auto`, `bypassPermissions`, `manual`,
`dontAsk`, `plan` — **`"default"` is not among them**, yet it was accepted
without a CLI error both times and echoed back verbatim as
`"permissionMode":"default"` in the `init` event. That strongly suggests
`"default"` isn't validated against a real enum and the CLI falls back to
some baseline behavior for an unrecognized mode string — plausibly one
that doesn't gate a plain, non-destructive `Bash` invocation the way an
interactive session's actual default would. Design §4.2's spawn command
and the brief's script both hardcode `--permission-mode default`
verbatim; **before building `decide_permission` (§4.5) and its tests,
re-run this one case with `--permission-mode manual`** (the closest
documented name to "ask before anything not pre-approved") and see
whether `control_request` appears. I did not spend the additional real
`claude` invocation to test this myself — it's a design decision
(which mode Klaus should actually pass), not a fixture-recording task.

## 5. Other CLI-flag observations worth carrying into `agent_host.py`

- **`--allowedTools` is not an exclusive allowlist.** Despite passing
  only `Read Grep Glob mcp__klaus__*`, the `init` event's `.tools` array
  still listed `Bash`, `Artifact`, the Cron* tools, `Monitor`,
  `SendMessage`, the Task* tools, etc. — everything the account normally
  has, minus what `--disallowedTools` named.
- **`--disallowedTools` does work as a removal list** — `Edit`, `Write`,
  `MultiEdit`, `NotebookEdit`, `WebFetch`, `WebSearch`, and `Task` never
  appeared anywhere in the `init` tool list or in any `tool_use` block,
  in any of the six runs.
- No case in either run produced anything on **stderr**. `claude`'s
  stderr was empty for all six invocations.
