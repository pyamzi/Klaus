# Klaus MCP interface

K-300 and K-301, 2026-09-19. Implementation:
[endpoint](../../klaus_note/anki_endpoint.py),
[bridge and diagnostic](../../klaus_note/scripts/mcp_stdio_bridge.py).

## Reference and design decisions

Reviewed [AnkiMCP](https://github.com/ankimcp/anki-mcp-server-addon) at
`dd5aa40bd40369c2833a671e78460903a37e6f9a` as a reference for an in-Anki
tool registry, main-thread dispatch and connection diagnostics. Klaus retains
its stdlib implementation, private discovery file, per-launch credentials and
existing approval gate. No upstream code, SDK, tunnel or native dependencies
were added to the add-on.

The implemented protocol version is `2025-06-18`. Initialization returns that
supported version when a client proposes a different version, following
[MCP version negotiation](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle).
Clients decide whether they support the negotiated version. Klaus does not
claim a newer protocol merely because a client asks for one.

Tool arguments are validated against the subset of JSON Schema used in the
registry before conversion or dispatch: objects, required/unknown properties,
strings, booleans, integers, arrays, item types and size/range constraints.
Unknown tools and malformed calls produce JSON-RPC errors; valid calls with
invalid argument values produce recoverable `isError` results. Definitions
include behavior annotations and an output envelope schema. Successful results
include `structuredContent: {"result": ...}` alongside existing text/image
content. These are the [MCP tool contracts](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

## Page and source contracts

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `current_page` | `include_image` optional, default true | Captures the active page once; returns its PDF ID, display name, one-based page/count, selection, text and transcript. Images are optional. No active page gives explicit text and a null structured result. |
| `get_page` | `pdf_id`, `page`, `include_image` optional, default false | Resolves an exact imported Library ID and checks page bounds. Does not switch the viewer or accept arbitrary filesystem paths. |
| `search_lecture_pdfs` | Existing `query` and optional `limit` | Adds `pdf` to each hit, preserving `source`, so its ID can be passed directly to page and note tools. |

MCP `add_note` requires `deck`, `model`, `fields`, `source_pdf` and
`source_page`; `tags` is optional. This intentionally tightens the prior MCP
contract: refresh the client's tool list after upgrading. The explicit source
is validated before approval and used for both the preview and written tags,
independent of the active viewer. Source IDs identify imported Library documents,
not immutable document revisions.

```json
{
  "deck": "Default",
  "model": "Basic",
  "fields": {"Front": "Question", "Back": "Answer"},
  "source_pdf": "lecture-id-from-page-tool",
  "source_page": 2
}
```

`add_notes` accepts `{"notes": [ ... ]}` with 1-20 notes of that shape.
Every source is validated before the single approval dialog. Each note is then
attempted independently. The result array contains `{index, note_id, error}`;
indices are zero-based and exactly one of `note_id` and `error` is populated.
Partial failures do not roll back successful notes. Do not replay the entire
batch after a partial result or transport failure. There is no idempotency-key
guarantee, and the bridge never retries writes.

AnkiConnect `addNote` and `addNotes` keep their existing parameter and result
shapes, including legacy viewer-based provenance when no explicit source is
provided. Existing authentication, Origin rejection and write approval still
apply to both transports.

## Connection diagnostic

Preferences exposes **Local models → MCP → Test connection** beside Copy.
Interpreter discovery and testing run in a collection-free QueryOp; the button
is disabled until Python is found and while testing. Completion callbacks ignore
closed dialogs and cancelled profiles. The existing theme supplies its styling.

`test_connection(interpreter, script, discovery)` starts the actual configured
stdio bridge, sends initialization and tool discovery, and validates the server
identity, protocol and tool list. It does not call collection or page tools.
The diagnostic times out after ten seconds and reports missing profile,
invalid discovery, rejected credentials, unavailable endpoint or launch failure
without exposing credentials or subprocess output. Normal bridge requests retain
the longer timeout needed for user approval.

## Verification

Run focused contracts and transport checks from the add-on repository:

```sh
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_mcp_updates.py
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_anki_endpoint.py
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_mcp_stdio_bridge.py
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_current_page.py
env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_external_client_settings.py
```

The optional [official client](https://github.com/modelcontextprotocol/python-sdk)
integration gate uses an isolated development environment. It is not an add-on
runtime dependency:

```sh
uv run --no-project --python 3.12 --with mcp==2.2.0 python tests/integration_mcp_sdk.py
```

It exercises real subprocess stdio against a scratch Endpoint, including
negotiation, schema validation, explicit page reads, an approved fake batch and
reconnection after restart. This establishes SDK interoperability, not a live
Claude Desktop or Codex application session. No tests use a real Anki collection
or the user's `user_files`.

Verification on 2026-09-19: 40 new contract checks, 117 endpoint checks,
37 bridge/diagnostic checks, 11 current-page checks and 30 Preferences checks
passed. The official SDK gate passed all 10 checks. All 53 repository test files
passed after the backend changes; after adding the Preferences button, its
focused test plus dialog logic, local models, transcription settings, switches,
retired-assistant settings and Apple design regressions passed again. Syntax
checks used the installed Anki symlink. A running Anki must be restarted to load
these source changes.
