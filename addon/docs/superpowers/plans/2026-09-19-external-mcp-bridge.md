# External MCP bridge implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an external Claude Desktop client use Klaus's existing Anki tools and current PDF page through a stable stdio configuration.

**Architecture:** Keep the loopback HTTP endpoint, per-launch token and approval gate. Publish current connection data privately on disk and launch a stdlib stdio-to-HTTP bridge from the external client. Add current-page content and a copyable Preferences configuration without restoring the embedded assistant.

**Tech Stack:** Python stdlib JSON/urllib/subprocess, existing MCP JSON-RPC endpoint, Anki/PyQt6.

**Spec:** `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`, D5.

## Global Constraints

- Loopback only, fresh token/ephemeral port each launch. Keep Origin rejection and approval defaults unchanged.
- No public listener, remote connector, ChatGPT integration, external config writes, telemetry or new dependencies.
- Discovery path is `user_files/mcp_connection.json`. Only production profile wiring uses that real path; every test passes a scratch path.
- Anki must be running. The copied config contains stable script/discovery/interpreter paths, never the bearer token or ephemeral port.
- No live collection or Anki fixtures. Fake collection, injected approval and temporary directories only.
- Preserve unrelated logo work and stage only owned Preferences hunks. No push or merge. No em dash in new prose.
- Actual class is `Endpoint`. Existing `current_view` metadata tool remains compatible; new tool name is `current_page`, action name `klausCurrentPage`.

## Review Focus

- Restart changes credentials: existing bridge reads discovery for every frame and never retains the old token/session across endpoint identity changes.
- Missing/malformed discovery or stopped Anki: clear JSON-RPC error, no token disclosure, no write retry after an ambiguous failure.
- Notification, invalid JSON and paths with spaces: stdout remains newline-framed protocol only, with no unwanted notification response.
- Write request crosses bridge: approval denial/timeout performs no mutation; approval executes exactly once.
- No viewed PDF or no cached page text/image: current-page tool answers explicitly without stale content from a previous view.

### Task 1: Publish discovery and build the stdio transport

**Files:** Modify `klausmate/anki_endpoint.py`, `tests/test_anki_endpoint.py`; create `klausmate/scripts/mcp_stdio_bridge.py`, `tests/test_mcp_stdio_bridge.py`.

**Interfaces:** Extend `Endpoint(..., discovery_path: str | None = None)`; `start_for_profile` passes `os.path.join(USER_FILES,"mcp_connection.json")`. Bridge entry point accepts `--discovery PATH`. No package or aqt import is permitted in the standalone bridge.

- [ ] **Step 1: Add failing endpoint lifecycle tests.** Start an injected fake endpoint with scratch discovery path, inspect JSON and mode, stop and assert removal; restart and assert token/port identity changes. Test discovery-write failure closes the just-started socket and does not publish partial data. Example assertions:

```python
host, port, token = endpoint.start()
check("discovery matches live endpoint", json.loads(discovery.read_text()) ==
      {"host": host, "port": port, "token": token})
check("private discovery", stat.S_IMODE(discovery.stat().st_mode) == 0o600)
endpoint.stop()
check("shutdown removes discovery", not discovery.exists())
```

Use the existing endpoint test's injected collection, main-thread runner and approver. Never construct a production profile for this test.

- [ ] **Step 2: Add failing subprocess bridge tests.** Launch the actual script with `sys.executable` against a fake HTTP server or injected Endpoint and feed newline JSON. Assert initialize response/session header, tools/list, read tool, approval-denied and approval-accepted write, notifications with no stdout, malformed JSON parse error and missing/malformed discovery. Rotate file/server between two frames in the same process and assert only the new token is used. Script/discovery paths include spaces. Count write calls under an HTTP-disconnect failure and assert no replay.
- [ ] **Step 3: Run both focused files and record RED.**
- [ ] **Step 4: Write discovery atomically with restrictive permissions.** Create parent directory, write a same-directory temporary file with mode0600, flush and replace; publish only after server is bound. On failure close the server and remove its temporary file. On stop remove only the discovery record owned by that endpoint so an older instance cannot delete a newer launch's file. Default `discovery_path=None` leaves injected test instances filesystem-free. Product profile close still rejects approvals before stopping.
- [ ] **Step 5: Implement the standalone bridge.** Read one JSON object per stdin line; relay `/mcp` with `X-Klaus-Token` and session header through a no-proxy, no-redirect opener. Accept only validated loopback hosts, integer port1..65535 and a nonempty token, and never log credentials. Use HTTP timeout180seconds to exceed the existing120second approval timeout. Read discovery each frame; clear stored session when connection identity changes. Return JSON-RPC transport errors using the incoming id for requests; notifications produce no response. Pass successful MCP results through unchanged, including image blocks. No automatic retry of a request, especially a write. Keep stdout protocol-only; optional diagnostics use stderr without user content.
- [ ] **Step 6: Run focused subprocess/lifecycle tests and full endpoint suite, compile new script and endpoint, then commit exact files.** No actual Claude Desktop config modification or live collection access.

### Task 2: Expose the current page and copyable client configuration

**Files:** Modify `klausmate/anki_endpoint.py`, `klausmate/manage_models.py`, `klausmate/scripts/mcp_stdio_bridge.py`, `tests/test_anki_endpoint.py`, `tests/test_mcp_stdio_bridge.py`, relevant settings tests and `klausmate/config.md`; add focused current-page/Preferences test file if existing fixtures cannot cover it.

**Interfaces:** `current_view` is unchanged. `current_page` returns a text block containing PDF display/id, one-based page/count, selection, slide text and transcript, plus an MCP `image` block (`mimeType: image/png`, base64 data) when rendering succeeds. No active view returns explicit no-page content. AnkiConnect action result remains JSON serializable.

- [ ] **Step 1: Add failing current-page tests using an injected viewer and page-store scratch directory.** Select PDF A/page2 with transcript and cached PNG, call through real `mcp_dispatch`, inspect metadata and image type/data. Switch to PDF B or close view and assert no A content remains. Stub renderer for absent cache; a render failure still returns available text and an explicit image-unavailable indication. Verify zero collection mutation/approval on this read. Keep original current_view compatibility assertion.

```python
status, reply, headers = mcp_dispatch(endpoint, {
    "jsonrpc":"2.0", "id":7, "method":"tools/call",
    "params":{"name":"current_page","arguments":{}}}, None)
blocks = reply["result"]["content"]
check("page image is MCP content", any(b.get("type")=="image" and
      b.get("mimeType")=="image/png" for b in blocks))
```

- [ ] **Step 2: Add failing config/UI tests.** Build a config from script/discovery/interpreter paths containing spaces, round-trip JSON and assert separate argv values. Assert no current token/port in the block, and rendering requires no live endpoint. Fake `sys.executable` as an Anki executable and verify it is never offered as Python. Real offscreen Preferences test verifies the copy button puts the exact JSON on clipboard and no external configuration file is written.
- [ ] **Step 3: Add the read action to the existing registry.** Resolve `viewer_context.current()` on the main thread through existing `Endpoint.handle` machinery. Load `page_store.load_record` and current PDF text if no indexed record exists, use cached or rendered PNG from the existing helpers, and keep selection/transcript anchored to the same captured view. Preserve native MIME image content in `mcp_dispatch` for this action instead of wrapping it all in a JSON string. Catch an image-render failure without losing text, and expose no unrelated filesystem content.
- [ ] **Step 4: Add an External clients group to the current Preferences shell.** Show read-only JSON plus Copy and concise instructions: Anki running, external Python3 required, add block under Claude Desktop mcpServers, restart client. Resolve a usable external Python interpreter from PATH/known locations; never assume `sys.executable` inside Anki is Python. If none is available, disable Copy and show what is missing, rather than copying a known-invalid command. Do not add a provider picker or auto-write another application's config. The bridge's command line is stable:

```json
{"mcpServers":{"klaus":{"command":"/absolute/path/to/python3","args":["/absolute/path/to/klausmate/scripts/mcp_stdio_bridge.py","--discovery","/absolute/path/to/user_files/mcp_connection.json"]}}}
```

The example paths describe the generated shape; the implementation resolves actual paths at runtime and tests assert those actual arguments.

- [ ] **Step 5: Document actual setup and privacy.** The external client chooses its model provider and may transmit requested context to that provider; Klaus itself exposes only the local endpoint. ChatGPT/public hosting remains out of scope. Do not claim a real Claude Desktop end-to-end session was tested when only the subprocess bridge was tested.
- [ ] **Step 6: Run focused tests, full aggregate suite, both compile paths and package-content check.** Confirm the standalone bridge is included recursively by packaging. Retain origin-refusal and approval tests. No paid API or external messages. Stage only owned hunks and commit; final review covers both tasks.

## Self-review

Discovery lifecycle, restart-safe stdio transport, unchanged write approvals/Origin policy, current-page text/image context, copy configuration and honest Anki-running requirement are assigned above. All five review conditions have direct tests. No public access or external client configuration mutation is introduced.
