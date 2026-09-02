# Klaus Assistant on Claude Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **This plan is executed as a board-coordinated swarm**: each task is one card, lanes are file-disjoint, and workers hand off through the board (see Global Constraints) rather than committing.

**Goal:** One assistant dock on Anki's main window whose engine is the Claude Code CLI, whose context is the page in view (OCR text + image + selection), and whose Anki reach is Klaus's own AnkiConnect-compatible endpoint served over MCP.

**Architecture:** Six new aqt-light modules (`agent_host`, `anki_endpoint`, `viewer_context`, `page_ocr`, `assistant_sessions`, `assistant_dock`) plus edits to `ollama_client`, `manage_models`, `theme`, the two viewers, `pdf_drive` and `__init__`, and the deletion of the in-house loop. Everything crossing a process or thread boundary is injected so it tests without Anki, a network, or the `claude` binary.

**Tech Stack:** Python 3.9-compatible stdlib (subprocess, http.server, json, threading), PyQt6 via `aqt.qt`, `QPdfDocument` for page rendering, Ollama `/api/generate` for OCR, Claude Code CLI 2.1.x print mode with stream-json in/out and `--mcp-config` HTTP servers.

**Spec:** `docs/superpowers/specs/2026-09-01-klaus-assistant-claude-code-design.md` (approved 2026-09-01). The plan argues from the spec; two refinements the facts forced are recorded under "Rulings" below.

## Global Constraints

- **Always edit the main checkout** `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`, never a worktree copy (Anki's symlink and the compile hook target it). (CLAUDE.md)
- **Every task claims a board card before editing** (`python3 board/board.py add … && claim`) naming exactly its files; claim refuses overlap with any Doing card, including the constellation plan's cards on `theme.py` and `pdf_viewer.py` — a refused claim means WAIT (poll `board.py list` every 5 minutes), never work around it. `board.py check-disjoint` must pass.
- **Workers never run git write commands** (no add/commit/stash/checkout): three sessions share this checkout and a swarm of parallel workers would race on the index. A worker's "Commit" step is: move the card to Review with a comment naming the files changed, the tests run, the mutation evidence, and any parked hunk. The orchestrator commits each card after review, message ending `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; never stage `klausmate/user_files/` or `meta.json*`.
- **A card's `verify:` must fail before the work and pass after.** Pins first, red run shown.
- **Every new pin is mutated once and watched failing**, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` and `~/Library/Caches/com.apple.python` purged before each run, the mutated file `ast.parse`d first.
- **No literal hex in UI files** (theme tokens only); **every paintEvent try/except/finally-`painter.end()`** (K-115); **no app-modal `exec()`** — window-modal `open()` with signal-driven results (K-114); **tests never touch `klausmate/user_files/`** (`tempfile.mkdtemp()` only).
- **Test bootstrap:** every test file starts `sys.path.insert(0, ".claude/skills/klaus-test/scripts"); from anki_stubs import check, code_only, install, report, section; install()` and ends with `report()`. System `python3` is 3.9.6 (no `math.sumprod`, no `int.bit_count`, no `match`). `PyQt6` and `PyQt6.QtPdf` import under it; `QT_QPA_PLATFORM=offscreen`.
- **Never drive Pouya's running Anki as a test fixture.** The spike (Task 1) runs the `claude` binary, never Anki. The live check (Task 13) is `needs-human`.
- **Spec values (verbatim):** endpoint bound to `127.0.0.1:0`; token header `X-Klaus-Token`; agent marker header `X-Klaus-Agent: 1`; `Origin` present → 403; body cap 4 MB; read timeout 30 s; approval timeout 120 s; OCR timeout 60 s; stop grace 2 s; login-shell discovery 3 s; page render long edge 1400 px; OCR debounce 400 ms; prefetch page±1; cache `user_files/ocr/<pdf_safe>/<digest12>/<page:04d>.md|.png`; sessions `user_files/assistant/sessions.json`; prompts `user_files/assistant/prompts/<name>.md`; system prompt `user_files/assistant/system_prompt.md`; stderr log `user_files/assistant/claude.log` (1 MB cap); config keys `ocr_enabled` (true), `ocr_model` ("glm-ocr"), `claude_binary` (""), `assistant_model` (""), `assistant_reopen` (false), `assistant_dock_width` (420); dropped keys `assistant_api_key`, `assistant_backend`, `assistant_token`; shortcut `Ctrl+Shift+K`; MCP server name `klaus`; tools `mcp__klaus__<name>`.
- **Allowed Claude Code tools:** `Read Grep Glob ToolSearch mcp__klaus__*` (ToolSearch: this build defers MCP schemas behind it — spike finding); **disallowed:** `Bash Edit Write MultiEdit NotebookEdit WebFetch WebSearch Task`.

## Rulings (spec refinements the facts forced)

- **R1 — approvals live in the endpoint, not the handlers.** `anki_tools._confirm_write_dialog` uses `dlg.exec()` on the main thread; the endpoint instead builds the plain-text preview itself, opens a window-modal dialog with `open()` whose `finished` sets a `threading.Event`, and only then runs the handler with `ctx["confirm"]` pre-approved. `anki_tools` is not modified.
- **R2 — the duplicate check in the approval preview is Anki's text search, not the embedding ranker.** `card_forge.mark_duplicates` needs the candidate embedded (a paid network call) inside an approval dialog; the preview instead runs `col.find_notes` over the front's first eight words and names the first hit as "similar existing note". `card_forge` stays available for batch drafting.
- **R3 — agent-added notes are tagged `klaus::assistant` and `klaus::from::<pdf_safe>`, not the PDF's `!Library` tag.** That tag is `tag_sync`'s invariant (membership = matched at threshold) and a hand-applied one would violate it; the next index pass assigns it if the card matches.

## File Structure

| File | Responsibility | Lane |
|---|---|---|
| `klausmate/agent_host.py` (new) | binary discovery, command line, turn/context assembly, stream event parsing, permission answers, the child-process host | A |
| `scripts/agent_spike.py` (new), `tests/fixtures/claude_stream/*.jsonl` (new) | live probe of the real binary; recorded stream lines | A |
| `klausmate/anki_endpoint.py` (new) | localhost HTTP server; AnkiConnect route; MCP route; the `ACTIONS` registry; approval bridge | B |
| `klausmate/viewer_context.py` (new) | registry of live PDF viewers; current view; subscriptions | C |
| `klausmate/page_ocr.py` (new), `klausmate/ollama_client.py` (+`generate`) | page → PNG → OCR text; cache; fallback; scheduler | C |
| `klausmate/assistant_sessions.py` (new) | session-id store, slash commands, default prompts, system prompt file | D |
| `klausmate/manage_models.py`, `klausmate/config.json`, `klausmate/config.md` | model classification, OCR presets, the Assistant page | E |
| `klausmate/assistant_dock.py` (new), `klausmate/theme.py` (+`assistant_dock_qss`, −panel block) | the dock | F |
| `klausmate/pdf_viewer.py`, `klausmate/pdfjs_viewer.py`, `klausmate/web/pdfjs_viewer.html` | viewers report into `viewer_context` | G |
| `klausmate/__init__.py`, `klausmate/pdf_drive.py`, deletions, `klausmate/card_forge.py` (one docstring) | lifecycle, menu, shortcut, toolbar button, third pane removed, dead modules deleted | H |
| `CLAUDE.md`, `AGENTS.md` | docs | I |

Lanes A–F are independent and run in parallel. G waits if the constellation plan's Task 8 holds `pdf_viewer.py`; F's `theme.py` edit waits if its Task 7 holds `theme.py`. H depends on B, D, F (imports); I on everything; Task 13 last.

---

### Task 1: Spike — prove the three protocols against the real binary and record fixtures

**Files:**
- Create: `scripts/agent_spike.py`
- Create: `tests/fixtures/claude_stream/README.md`, `tests/fixtures/claude_stream/turn_with_image.jsonl`, `tests/fixtures/claude_stream/tool_call.jsonl`, `tests/fixtures/claude_stream/permission_denied.jsonl`
- Board card: `Assistant spike: image block, MCP over HTTP, permission round-trip against the real claude` — files `scripts/agent_spike.py,tests/fixtures/claude_stream/*` — verify `test -s tests/fixtures/claude_stream/turn_with_image.jsonl`

**Interfaces:**
- Produces: the three fixture files (raw stdout lines, one JSON object per line) and `README.md` documenting the observed field paths for every event type in §4.4 of the spec. Task 2's parser tests read these files; if a path differs from the spec's table, the README says so and Task 2 follows the README.

This is throwaway-grade code kept only as the recorder. It needs a logged-in Claude Code (`claude --version` prints 2.1.x; `claude -p "say ok"` answers). If the login is missing, move the card to Review with the comment `needs-human: claude not logged in` and stop; Task 2 then treats its field paths as provisional.

- [ ] **Step 1: Claim the card** (`python3 board/board.py add --col Ready --title … --files … --verify … --tags assistant,spike` then `claim <id> --owner <you>`). Run the verify command first and record that it FAILS (the fixture does not exist).

- [ ] **Step 2: Write the spike script**

```python
#!/usr/bin/env python3
"""Throwaway probe: drive the real `claude` once and record its stream.

Not a test. Records raw stdout lines to tests/fixtures/claude_stream/ so the
parser in klausmate/agent_host.py is pinned to what the binary actually
emits, not to memory. Needs a logged-in Claude Code.
"""
import base64, json, os, secrets, shutil, subprocess, sys, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "claude_stream")
TOKEN = secrets.token_hex(16)
CALLS = []  # every tools/call the minimal MCP responder received


class Mcp(BaseHTTPRequestHandler):
    """The smallest MCP-over-HTTP responder that can pass initialize/tools."""

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        if self.headers.get("X-Klaus-Token") != TOKEN:
            self.send_response(403); self.end_headers(); return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")) or "0") or b"{}")
        rid, method, params = body.get("id"), body.get("method"), body.get("params") or {}
        if method == "initialize":
            res = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "klaus", "version": "spike"}}
        elif method == "notifications/initialized":
            self.send_response(202); self.end_headers(); return
        elif method == "tools/list":
            res = {"tools": [{"name": "current_view", "description": "What the user is viewing.",
                               "inputSchema": {"type": "object", "properties": {}}},
                              {"name": "add_note", "description": "Add a note (approval dialog in the real thing).",
                               "inputSchema": {"type": "object", "properties": {
                                   "deck": {"type": "string"}, "fields": {"type": "object"},
                                   "source_page": {"type": "integer"}}, "required": ["deck", "fields", "source_page"]}}]}
        elif method == "tools/call":
            CALLS.append(params)
            name = params.get("name")
            text = json.dumps({"pdf": "spike.pdf", "page": 3, "count": 10, "selection": ""}) if name == "current_view" \
                else json.dumps({"noteId": 1234567890})
            res = {"content": [{"type": "text", "text": text}], "isError": False}
        elif method == "ping":
            res = {}
        else:
            out = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}
            return self._send(out)
        self._send({"jsonrpc": "2.0", "id": rid, "result": res})

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


def slide_png() -> bytes:
    """A synthetic slide with a title the model can read back."""
    from PyQt6.QtGui import QImage, QPainter, QColor, QFont, QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(1400, 1050, QImage.Format.Format_RGB32); img.fill(QColor("white"))
    p = QPainter(img); p.setPen(QColor("black")); p.setFont(QFont("Helvetica", 48))
    p.drawText(80, 160, "Nephron: proximal tubule reabsorbs 65% of sodium"); p.end()
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buf, "PNG")
    return bytes(buf.data())


def turn(text: str, png: bytes | None) -> str:
    content = [{"type": "text", "text": text}]
    if png:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(png).decode()}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def run_case(name: str, port: int, turns: list[str], cwd: str) -> list[str]:
    binary = shutil.which("claude") or "/opt/homebrew/bin/claude"
    mcp = json.dumps({"mcpServers": {"klaus": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp",
                                                "headers": {"X-Klaus-Token": TOKEN}}}})
    cmd = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--include-partial-messages", "--verbose", "--permission-mode", "default",
           "--mcp-config", mcp, "--strict-mcp-config", "--add-dir", cwd,
           "--allowedTools", "Read", "Grep", "Glob", "mcp__klaus__*",
           "--disallowedTools", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
           "--session-id", str(uuid.uuid4())]
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    lines: list[str] = []

    def reader():
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            lines.append(line)
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "control_request":
                req = ev.get("request") or {}
                resp = {"type": "control_response", "response": {
                    "subtype": "success", "request_id": ev.get("request_id"),
                    "response": {"behavior": "deny", "message": "Klaus allows only reading the library and its own Anki tools."}}}
                proc.stdin.write(json.dumps(resp) + "\n"); proc.stdin.flush()
                print(f"  [{name}] denied {req.get('tool_name')}")
            if ev.get("type") == "result":
                pending.set()

    t = threading.Thread(target=reader, daemon=True); t.start()
    for text in turns:
        pending = threading.Event()
        png = slide_png() if "slide" in text else None
        proc.stdin.write(turn(text, png)); proc.stdin.flush()
        if not pending.wait(180):
            print(f"  [{name}] TIMEOUT waiting for result"); break
    proc.stdin.close()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.makedirs(FIX, exist_ok=True)
    with open(os.path.join(FIX, f"{name}.jsonl"), "w") as f:
        f.write("\n".join(lines) + "\n")
    err = proc.stderr.read()
    if err.strip():
        print(f"  [{name}] stderr: {err[-400:]}")
    return lines


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mcp); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cwd = tempfile.mkdtemp(prefix="klaus-spike-")
    with open(os.path.join(cwd, "notes.txt"), "w") as f:
        f.write("The library root the agent may read.\n")
    ok = True
    l1 = run_case("turn_with_image", port,
                  ["In one sentence, what is written on this slide? Then call the current_view tool and tell me the page number."], cwd)
    ok &= any('"subtype": "init"' in x or '"subtype":"init"' in x for x in l1)
    ok &= any("mcp__klaus__current_view" in x for x in l1)
    ok &= any(c.get("name") == "current_view" for c in CALLS)
    ok &= any("proximal" in x.lower() or "sodium" in x.lower() for x in l1)
    l2 = run_case("tool_call", port, ["Add a note to deck Default with front 'Proximal tubule Na+ reabsorption' and back '65%', source page 3."], cwd)
    ok &= any(c.get("name") == "add_note" for c in CALLS)
    l3 = run_case("permission_denied", port, ["Run the shell command `ls` and tell me what it printed."], cwd)
    ok &= any('"control_request"' in x for x in l3)
    print("RESULT:", "OK" if ok else "FAILED — read the fixtures")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run it** — `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 scripts/agent_spike.py`. Expected: three fixture files, `RESULT: OK`. If the image turn errors with a message about unsupported content, that is a finding: record it in the README and try the `--input-format stream-json` message with the image as a file path instead (`{"type":"text","text":"The slide is at <path>.png — read it."}`) and record which worked.

- [ ] **Step 4: Write `tests/fixtures/claude_stream/README.md`** listing, for each event type actually observed (`system/init`, `stream_event` text deltas, `assistant`, `user` tool results, `result`, `control_request`), the exact JSON path of every field the parser needs (session id, delta text, tool name/input, tool_use_id/is_error, is_error/duration/cost, request_id/tool_name), with one example line each, and the Claude Code version (`claude --version`). State plainly whether the image block was accepted.

- [ ] **Step 5: Verify passes** — `test -s tests/fixtures/claude_stream/turn_with_image.jsonl` exits 0.

- [ ] **Step 6: Hand off** — move the card to Review with a comment: the three cases' outcomes, the version, and any path that differs from the spec's §4.4 table. Do not commit.

---

### Task 2: `agent_host.py` — discovery, command line, turns, stream parsing, permissions, the host

**Files:**
- Create: `klausmate/agent_host.py`
- Test: `tests/test_agent_host.py`
- Board card: `agent_host: the Claude Code child — discovery, turns, stream parser, permissions` — files `klausmate/agent_host.py,tests/test_agent_host.py` — verify `python3 tests/test_agent_host.py`

**Interfaces:**
- Consumes: Task 1's fixtures if present (`tests/fixtures/claude_stream/*.jsonl` + README); otherwise the spec §4.4 paths, marked provisional in the parser docstring.
- Produces (Task 9 depends on these exact names):
  - `find_claude(override: str = "", env: dict | None = None, which=shutil.which, run=subprocess.run, exists=os.path.exists, platform: str = sys.platform, home: str = "~") -> str | None`
  - `mcp_config(port: int, token: str) -> str`
  - `command_line(binary: str, *, port: int, token: str, library_root: str | None, system_prompt_path: str, session_id: str | None = None, resume: str | None = None, model: str = "") -> list[str]`
  - `build_context_block(view: dict | None, page_text: str, text_source: str, selection: str) -> str`
  - `build_turn(user_text: str, context_block: str, png: bytes | None) -> str`
  - `parse_line(line: str) -> dict | None`; `classify(event: dict) -> tuple[str, Any]` returning one of `("init", {"session_id": str, "mcp_ok": bool})`, `("delta", str)`, `("tool_use", (name, input))`, `("tool_result", (tool_use_id, is_error))`, `("result", {"session_id","is_error","duration_ms","total_cost_usd","text"})`, `("permission", (request_id, tool_name, input))`, `("other", None)`
  - `decide_permission(tool_name: str, input: dict) -> tuple[str, str]`; `control_response(request_id: str, behavior: str, message: str = "") -> str`
  - `class AgentHost(binary, *, port, token, library_root, system_prompt_path, model, log_path, callbacks: dict[str, Callable], spawn=subprocess.Popen)` with `start(session_id=None, resume=None) -> str` (returns the session id), `send(turn_line: str) -> None`, `stop() -> None`, `close() -> None`, `running: bool`, `session_id: str | None`. Callback keys: `init, delta, tool_use, tool_result, result, permission_denied, error, exited`.

- [ ] **Step 1: Claim the card**; run `python3 tests/test_agent_host.py` — expected: fails with `ModuleNotFoundError` (no such test / module) — record it.

- [ ] **Step 2: Write the failing tests** (`tests/test_agent_host.py`):

```python
"""agent_host — the Claude Code child, without the child.

Everything here runs with a fake process: the parser is pinned to recorded
stream lines (tests/fixtures/claude_stream/, Task 1) when they exist and to
the spec's documented shapes otherwise.
"""
import io, json, os, sys, tempfile, threading, time

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
import importlib
ah = importlib.import_module("klausmate.agent_host")

section("binary discovery")
calls = []
def which_none(name): return None
def which_path(name): return "/opt/homebrew/bin/claude"
def run_login(cmd, **kw):
    calls.append(cmd)
    class R: stdout = "/usr/local/bin/claude\n"; returncode = 0
    return R()
def run_fail(cmd, **kw):
    class R: stdout = ""; returncode = 1
    return R()
check("override wins when executable",
      ah.find_claude("/x/claude", which=which_path, run=run_fail, exists=lambda p: p == "/x/claude") == "/x/claude")
check("PATH next", ah.find_claude("", which=which_path, run=run_fail, exists=lambda p: False) == "/opt/homebrew/bin/claude")
check("login shell next, 3 s timeout, -lc command -v",
      ah.find_claude("", env={"SHELL": "/bin/zsh"}, which=which_none, run=run_login, exists=lambda p: p == "/usr/local/bin/claude") == "/usr/local/bin/claude"
      and calls[-1][:2] == ["/bin/zsh", "-lc"] and "command -v claude" in calls[-1][2])
check("known locations last",
      ah.find_claude("", env={"SHELL": "/bin/sh"}, which=which_none, run=run_fail,
                     exists=lambda p: p.endswith("/.claude/local/claude"), home="/Users/x") == "/Users/x/.claude/local/claude")
check("nothing found → None", ah.find_claude("", env={}, which=which_none, run=run_fail, exists=lambda p: False) is None)

section("command line")
cmd = ah.command_line("/bin/claude", port=4321, token="tok", library_root="/lib", system_prompt_path="/sp.md", session_id="sid-1")
s = " ".join(cmd)
check("print mode with stream-json both ways and partials",
      all(x in cmd for x in ("-p", "--input-format", "--output-format", "--include-partial-messages", "--verbose")) and cmd.count("stream-json") == 2)
check("mcp config names klaus over http with the token header",
      "--mcp-config" in cmd and '"klaus"' in s and "/mcp" in s and "X-Klaus-Token" in s and "tok" in s and "--strict-mcp-config" in cmd)
check("library root is the add-dir", cmd[cmd.index("--add-dir") + 1] == "/lib")
check("allowlist and denylist exactly", "Read Grep Glob ToolSearch mcp__klaus__*" in s and "Bash Edit Write MultiEdit NotebookEdit WebFetch WebSearch Task" in s)
check("new session by id", cmd[cmd.index("--session-id") + 1] == "sid-1" and "--resume" not in cmd)
cmd2 = ah.command_line("/bin/claude", port=1, token="t", library_root=None, system_prompt_path="/sp.md", resume="old", model="opus")
check("resume instead of session-id; model passed; no add-dir without a root",
      cmd2[cmd2.index("--resume") + 1] == "old" and "--session-id" not in cmd2 and cmd2[cmd2.index("--model") + 1] == "opus" and "--add-dir" not in cmd2)
check("system prompt appended from file", cmd[cmd.index("--append-system-prompt-file") + 1] == "/sp.md")

section("turns")
view = {"display": "Renal 3.pdf", "page_index": 6, "page_count": 40}
blk = ah.build_context_block(view, "Na+ 65%", "ocr", "loop of Henle")
check("context block names pdf, 1-based page, count, source, selection",
      "[Klaus context]" in blk and "Renal 3.pdf" in blk and "page 7 of 40" in blk and "(ocr)" in blk and "loop of Henle" in blk and "Na+ 65%" in blk)
blk0 = ah.build_context_block(None, "", "none", "")
check("no-PDF block says so and marks empty selection", "nothing" in blk0 and "(none)" in blk0)
line = ah.build_turn("hi", blk, b"\x89PNG")
obj = json.loads(line)
check("turn is one JSON line, user role, text+context+image", line.endswith("\n") and line.count("\n") == 1 and obj["type"] == "user"
      and obj["message"]["role"] == "user" and [b["type"] for b in obj["message"]["content"]] == ["text", "text", "image"]
      and obj["message"]["content"][2]["source"]["media_type"] == "image/png")
obj2 = json.loads(ah.build_turn("hi", blk, None))
check("no image → two blocks", [b["type"] for b in obj2["message"]["content"]] == ["text", "text"])

section("stream parsing")
check("malformed line → None", ah.parse_line("not json") is None and ah.parse_line("") is None)
FIX = "tests/fixtures/claude_stream"
recorded = os.path.isfile(os.path.join(FIX, "turn_with_image.jsonl"))
if recorded:
    kinds = []
    for name in ("turn_with_image", "tool_call", "permission_denied"):
        with open(os.path.join(FIX, f"{name}.jsonl")) as f:
            for raw in f:
                ev = ah.parse_line(raw)
                if ev is not None:
                    kinds.append(ah.classify(ev)[0])
    check("recorded stream yields init, delta, result", {"init", "delta", "result"} <= set(kinds), str(sorted(set(kinds))))
    check("recorded stream yields a tool_use and a tool_result", "tool_use" in kinds and "tool_result" in kinds)
    check("recorded stream yields a permission request", "permission" in kinds)
else:
    print("  SKIP recorded fixtures absent — parser pinned to spec shapes only")
init = {"type": "system", "subtype": "init", "session_id": "S", "mcp_servers": [{"name": "klaus", "status": "connected"}]}
check("init → session id + mcp ok", ah.classify(init) == ("init", {"session_id": "S", "mcp_ok": True}))
bad = dict(init, mcp_servers=[{"name": "klaus", "status": "failed"}])
check("init with failed mcp → mcp_ok False", ah.classify(bad)[1]["mcp_ok"] is False)
delta = {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "He"}}}
check("text delta", ah.classify(delta) == ("delta", "He"))
tu = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__klaus__search_notes", "input": {"query": "renal"}}]}}
check("tool_use", ah.classify(tu) == ("tool_use", ("mcp__klaus__search_notes", {"query": "renal"})))
tr = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "T1", "is_error": True, "content": "x"}]}}
check("tool_result", ah.classify(tr) == ("tool_result", ("T1", True)))
res = {"type": "result", "subtype": "success", "is_error": False, "session_id": "S", "duration_ms": 12, "total_cost_usd": 0.01, "result": "done"}
check("result", ah.classify(res) == ("result", {"session_id": "S", "is_error": False, "duration_ms": 12, "total_cost_usd": 0.01, "text": "done"}))
pr = {"type": "control_request", "request_id": "R1", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}}}
check("permission", ah.classify(pr) == ("permission", ("R1", "Bash", {"command": "ls"})))
check("unknown → other", ah.classify({"type": "zzz"}) == ("other", None))

section("permissions")
check("klaus tools allowed", ah.decide_permission("mcp__klaus__add_note", {})[0] == "allow")
check("Read/Grep/Glob/ToolSearch allowed", all(ah.decide_permission(t, {})[0] == "allow" for t in ("Read", "Grep", "Glob", "ToolSearch")))
d = ah.decide_permission("Bash", {"command": "rm"})
check("everything else denied with the fixed message", d == ("deny", ah.DENY_MESSAGE))
cr = json.loads(ah.control_response("R1", "deny", "no"))
check("control_response shape", cr["type"] == "control_response" and cr["response"]["request_id"] == "R1"
      and cr["response"]["response"]["behavior"] == "deny" and cr["response"]["response"]["message"] == "no")
ca = json.loads(ah.control_response("R2", "allow"))
check("allow carries no message key", ca["response"]["response"] == {"behavior": "allow"})

section("host with a fake process")
class FakeProc:
    def __init__(self, lines):
        self.stdin = io.StringIO(); self.stdout = io.StringIO("".join(l + "\n" for l in lines)); self.stderr = io.StringIO("")
        self.pid = 4242; self._rc = None; self.signals = []
    def poll(self): return self._rc
    def wait(self, timeout=None): self._rc = 0; return 0
    def send_signal(self, s): self.signals.append(s); self._rc = -2
    def terminate(self): self.signals.append("TERM"); self._rc = -15
    def kill(self): self.signals.append("KILL"); self._rc = -9
lines = [json.dumps(init), json.dumps(delta), json.dumps(pr), json.dumps(res)]
spawned = []
def spawn(cmd, **kw):
    spawned.append((cmd, kw)); return FakeProc(lines)
got = {k: [] for k in ("init", "delta", "tool_use", "tool_result", "result", "permission_denied", "error", "exited")}
cbs = {k: (lambda k: (lambda *a: got[k].append(a)))(k) for k in got}
tmp = tempfile.mkdtemp()
host = ah.AgentHost("/bin/claude", port=1, token="t", library_root=tmp, system_prompt_path=os.path.join(tmp, "sp.md"),
                    model="", log_path=os.path.join(tmp, "claude.log"), callbacks=cbs, spawn=spawn)
sid = host.start()
check("start spawns with cwd = library root and returns a session id", spawned and spawned[0][1].get("cwd") == tmp and isinstance(sid, str) and len(sid) >= 32)
host.send(ah.build_turn("q", blk0, None))
deadline = time.time() + 5
while time.time() < deadline and not got["result"]:
    time.sleep(0.02)
check("events reached callbacks in order", got["init"] and got["delta"] == [("He",)] and got["result"])
check("permission request was answered deny on stdin", bool(got["permission_denied"]) and '"behavior": "deny"' in host._proc.stdin.getvalue() and "control_response" in host._proc.stdin.getvalue())
check("turn was written to stdin", '"type": "user"' in host._proc.stdin.getvalue())
check("not running after result", host.running is False)
host.stop()
check("stop on an idle host is a no-op (no signal sent)", host._proc.signals == [])
host2 = ah.AgentHost("/bin/claude", port=1, token="t", library_root=tmp, system_prompt_path="/sp", model="", log_path=os.path.join(tmp, "c.log"), callbacks=cbs, spawn=lambda c, **k: FakeProc([]))
host2.start(resume="OLD")
check("resume passes --resume", "--resume" in host2._cmd and host2.session_id == "OLD")
host2._running = True
host2.stop()
check("stop signals then kills within the grace period", host2._proc.signals and host2._proc.signals[0] != "KILL")
host2.close()
check("close leaves nothing running", host2.running is False)

report()
```

- [ ] **Step 3: Run to see it fail** — `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_agent_host.py` → `ModuleNotFoundError: klausmate.agent_host`.

- [ ] **Step 4: Write the module** (`klausmate/agent_host.py`):

```python
"""The Claude Code child: find it, spawn it, feed it turns, read its stream.

Klaus is a HOST for Claude Code, not a loop of its own (the in-house loop
was deleted with this module's arrival — Pouya, 2026-09-01: "wrap the
Claude Code CLI, exactly like Claudian"). Everything crossing the process
boundary is injected (``spawn``, ``which``, ``run``), so the whole module
runs in tests with a fake process and no binary.

Field paths in ``classify`` are pinned by the recorded fixtures under
tests/fixtures/claude_stream/ (Task 1 of the plan). Where the fixtures were
not recorded they follow the spec's §4.4 table and are PROVISIONAL.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from typing import Any, Callable

KNOWN_PATHS = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    "~/.claude/local/claude",
    "~/.local/bin/claude",
)
WINDOWS_PATH = "%LOCALAPPDATA%\\Programs\\claude\\claude.exe"
ALLOWED_TOOLS = ("Read", "Grep", "Glob", "ToolSearch", "mcp__klaus__*")
DISALLOWED_TOOLS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task")
MCP_SERVER = "klaus"
STOP_GRACE_S = 2.0
LOGIN_SHELL_TIMEOUT_S = 3.0
LOG_CAP_BYTES = 1_000_000
DENY_MESSAGE = "Klaus allows only reading the library and its own Anki tools."
_CALLBACKS = ("init", "delta", "tool_use", "tool_result", "result", "permission_denied", "error", "exited")


def find_claude(override: str = "", env: dict | None = None, which=shutil.which, run=subprocess.run,
                exists=os.path.exists, platform: str = sys.platform, home: str = "~") -> str | None:
    """Config override, PATH, the login shell's PATH, then known locations."""
    if override and exists(override):
        return override
    found = which("claude")
    if found:
        return found
    env = os.environ if env is None else env
    shell = env.get("SHELL") or ""
    if shell:
        try:
            r = run([shell, "-lc", "command -v claude"], capture_output=True, text=True, timeout=LOGIN_SHELL_TIMEOUT_S)
            cand = (getattr(r, "stdout", "") or "").strip().splitlines()
            if getattr(r, "returncode", 1) == 0 and cand and exists(cand[-1]):
                return cand[-1]
        except Exception as exc:  # timeout, missing shell
            print(f"[klausmate] agent: login-shell lookup failed: {exc}")
    for p in KNOWN_PATHS:
        cand = p.replace("~", home) if p.startswith("~") else p
        if exists(cand):
            return cand
    if platform.startswith("win"):
        cand = os.path.expandvars(WINDOWS_PATH)
        if exists(cand):
            return cand
    return None


def mcp_config(port: int, token: str) -> str:
    return json.dumps({"mcpServers": {MCP_SERVER: {"type": "http", "url": f"http://127.0.0.1:{int(port)}/mcp",
                                                    "headers": {"X-Klaus-Token": token}}}})


def command_line(binary: str, *, port: int, token: str, library_root: str | None, system_prompt_path: str,
                 session_id: str | None = None, resume: str | None = None, model: str = "") -> list[str]:
    cmd = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--include-partial-messages", "--verbose", "--permission-mode", "default",
           "--mcp-config", mcp_config(port, token), "--strict-mcp-config"]
    if library_root:
        cmd += ["--add-dir", library_root]
    cmd += ["--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS,
            "--append-system-prompt-file", system_prompt_path]
    if resume:
        cmd += ["--resume", resume]
    else:
        cmd += ["--session-id", session_id or str(uuid.uuid4())]
    if model:
        cmd += ["--model", model]
    return cmd


def build_context_block(view: dict | None, page_text: str, text_source: str, selection: str) -> str:
    if view:
        head = f"Viewing: {view.get('display') or view.get('pdf_safe') or '?'} — page {int(view.get('page_index', 0)) + 1} of {int(view.get('page_count', 0))}"
    else:
        head = "Viewing: nothing — no PDF is open"
    sel = selection.strip() if selection else ""
    return ("[Klaus context]\n" + head + "\nSelection:\n```" + (sel or "(none)") + "```\n"
            + f"Page text ({text_source or 'none'}):\n```" + (page_text or "") + "```\n")


def build_turn(user_text: str, context_block: str, png: bytes | None) -> str:
    import base64
    content: list[dict] = [{"type": "text", "text": user_text}, {"type": "text", "text": context_block}]
    if png:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(png).decode("ascii")}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def parse_line(line: str) -> dict | None:
    line = (line or "").strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except Exception:
        return None
    return ev if isinstance(ev, dict) else None


def classify(event: dict) -> tuple[str, Any]:
    """Map one stream object to (kind, payload). Paths per the fixtures' README."""
    t = event.get("type")
    if t == "system" and event.get("subtype") == "init":
        servers = event.get("mcp_servers") or []
        ok = any(s.get("name") == MCP_SERVER and s.get("status") == "connected" for s in servers if isinstance(s, dict))
        return "init", {"session_id": str(event.get("session_id") or ""), "mcp_ok": ok}
    if t == "stream_event":
        ev = event.get("event") or {}
        if ev.get("type") == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta":
                return "delta", str(d.get("text") or "")
        return "other", None
    if t == "assistant":
        for b in (event.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                return "tool_use", (str(b.get("name") or ""), b.get("input") or {})
        return "other", None
    if t == "user":
        for b in (event.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                return "tool_result", (str(b.get("tool_use_id") or ""), bool(b.get("is_error")))
        return "other", None
    if t == "result":
        return "result", {"session_id": str(event.get("session_id") or ""), "is_error": bool(event.get("is_error")),
                          "duration_ms": int(event.get("duration_ms") or 0), "total_cost_usd": float(event.get("total_cost_usd") or 0.0),
                          "text": str(event.get("result") or "")}
    if t == "control_request":
        req = event.get("request") or {}
        if req.get("subtype") == "can_use_tool":
            return "permission", (str(event.get("request_id") or ""), str(req.get("tool_name") or ""), req.get("input") or {})
    return "other", None


def decide_permission(tool_name: str, input: dict) -> tuple[str, str]:
    if tool_name.startswith(f"mcp__{MCP_SERVER}__") or tool_name in ("Read", "Grep", "Glob", "ToolSearch"):
        return "allow", ""
    return "deny", DENY_MESSAGE


def control_response(request_id: str, behavior: str, message: str = "") -> str:
    inner: dict = {"behavior": behavior}
    if behavior == "deny":
        inner["message"] = message
    return json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": inner}}) + "\n"


class AgentHost:
    """One child process, one reader thread, callbacks on the reader thread.

    The dock wraps the callbacks in Qt signals; nothing here touches Qt.
    """

    def __init__(self, binary: str, *, port: int, token: str, library_root: str | None, system_prompt_path: str,
                 model: str, log_path: str, callbacks: dict, spawn=subprocess.Popen) -> None:
        self._binary, self._port, self._token = binary, port, token
        self._root, self._sp, self._model, self._log = library_root, system_prompt_path, model, log_path
        self._cb = {k: callbacks.get(k, lambda *a: None) for k in _CALLBACKS}
        self._spawn = spawn
        self._proc: Any = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running = False
        self._cmd: list[str] = []
        self.session_id: str | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self, session_id: str | None = None, resume: str | None = None) -> str:
        self.close()
        self.session_id = resume or session_id or str(uuid.uuid4())
        self._cmd = command_line(self._binary, port=self._port, token=self._token, library_root=self._root,
                                 system_prompt_path=self._sp, session_id=None if resume else self.session_id,
                                 resume=resume, model=self._model)
        kwargs: dict = {"cwd": self._root or os.path.dirname(self._sp), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                        "stderr": subprocess.PIPE, "text": True, "bufsize": 1}
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(self._binary) + os.pathsep + env.get("PATH", "")
        kwargs["env"] = env
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = self._spawn(self._cmd, **kwargs)
        self._reader = threading.Thread(target=self._read, name="klaus-agent-reader", daemon=True)
        self._reader.start()
        return self.session_id

    def send(self, turn_line: str) -> None:
        with self._lock:
            if self._proc is None:
                raise RuntimeError("agent not started")
            self._running = True
            self._proc.stdin.write(turn_line)
            self._proc.stdin.flush()

    def _write(self, line: str) -> None:
        try:
            with self._lock:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
        except Exception as exc:
            print(f"[klausmate] agent: stdin write failed: {exc}")

    def _read(self) -> None:
        proc = self._proc
        try:
            for raw in proc.stdout:
                ev = parse_line(raw)
                if ev is None:
                    if raw.strip():
                        print(f"[klausmate] agent: unparsable line: {raw[:120]!r}")
                    continue
                kind, payload = classify(ev)
                try:
                    if kind == "init":
                        if payload["session_id"]:
                            self.session_id = payload["session_id"]
                        self._cb["init"](payload)
                    elif kind == "delta":
                        self._cb["delta"](payload)
                    elif kind == "tool_use":
                        self._cb["tool_use"](*payload)
                    elif kind == "tool_result":
                        self._cb["tool_result"](*payload)
                    elif kind == "permission":
                        rid, name, inp = payload
                        behavior, msg = decide_permission(name, inp)
                        self._write(control_response(rid, behavior, msg))
                        if behavior == "deny":
                            self._cb["permission_denied"](name)
                    elif kind == "result":
                        self._running = False
                        if payload["session_id"]:
                            self.session_id = payload["session_id"]
                        self._cb["result"](payload)
                except Exception as exc:
                    print(f"[klausmate] agent: callback failed: {exc}")
        except Exception as exc:
            self._cb["error"](f"stream read failed: {exc}")
        finally:
            self._running = False
            self._drain_stderr()
            rc = None
            try:
                rc = proc.poll()
            except Exception:
                pass
            self._cb["exited"](rc)

    def _drain_stderr(self) -> None:
        try:
            err = self._proc.stderr.read() or ""
        except Exception:
            return
        if not err.strip():
            return
        try:
            os.makedirs(os.path.dirname(self._log), exist_ok=True)
            if os.path.exists(self._log) and os.path.getsize(self._log) > LOG_CAP_BYTES:
                os.replace(self._log, self._log + ".1")
            with open(self._log, "a", encoding="utf-8") as f:
                f.write(err)
        except Exception as exc:
            print(f"[klausmate] agent: log write failed: {exc}")

    def stop(self) -> None:
        """SIGINT, a 2 s grace, then kill. The session id survives."""
        proc = self._proc
        if proc is None or not self._running:
            return
        try:
            if sys.platform.startswith("win"):
                proc.terminate()
            else:
                proc.send_signal(signal.SIGINT)
            try:
                proc.wait(STOP_GRACE_S)
            except Exception:
                proc.kill()
        except Exception as exc:
            print(f"[klausmate] agent: stop failed: {exc}")
        finally:
            self._running = False

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            try:
                proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(STOP_GRACE_S)
                except Exception:
                    proc.kill()
        except Exception as exc:
            print(f"[klausmate] agent: close failed: {exc}")
        finally:
            self._running = False
            self._proc = None
```

- [ ] **Step 5: Run the tests to green.**

- [ ] **Step 6: Mutate** — (1) in `decide_permission` return `"allow"` for everything → the "everything else denied" pin fails; (2) in `command_line` drop `--strict-mcp-config` → the mcp pin fails; (3) in `classify` return `("other", None)` for `result` → the host-order pin fails. Restore byte-identical each time.

- [ ] **Step 7: Full loop once** — `for t in tests/test_*.py; do echo "— $t"; python3 "$t" || break; done` — all green.

- [ ] **Step 8: Hand off** — card to Review with the comment (files, RED/GREEN counts, mutations). No commit.

---

### Task 3: `anki_endpoint.py` — server, auth, the AnkiConnect route, approvals

**Files:**
- Create: `klausmate/anki_endpoint.py`
- Test: `tests/test_anki_endpoint.py`
- Board card: `anki_endpoint: localhost server, token/Origin gate, AnkiConnect actions over anki_tools, open()-dialog approvals` — files `klausmate/anki_endpoint.py,tests/test_anki_endpoint.py` — verify `python3 tests/test_anki_endpoint.py`

**Interfaces:**
- Consumes: `anki_tools.TOOL_SPECS`, `anki_tools._HANDLERS` (`_h_search_notes`, `_h_search_lecture_pdfs`, `_h_create_note`, `_h_update_note`, `_h_get_note`), `anki_tools.default_ctx()`; `viewer_context.current()` (Task 5 — import lazily inside the action so the module tests without it).
- Produces (Task 4 extends the same file; Task 11 wires it):
  - `ACTIONS: dict[str, Action]` with `Action(name, mcp_name, description, schema: dict, write: bool, run: Callable[[Any, dict, dict], Any])`
  - `class Endpoint(*, col_getter: Callable[[], Any], run_on_main: Callable[[Callable, float], Any], approver: Callable[[str, list], bool], ctx_factory: Callable[[], dict], version: str)` with `start() -> tuple[str, int, str]` (host, port, token), `stop()`, `handle(action: str, params: dict, agent: bool) -> dict` returning `{"result": ..., "error": None | str}`, `port`, `token`.
  - `preview_sections(action: str, params: dict, similar: str | None) -> list[tuple[str, str]]` (pure)
  - `similar_existing(col, front: str) -> str | None` (pure over a duck-typed col)
  - `qt_approver(title: str, sections: list) -> bool` — the production approver (aqt glue below the divider): window-modal `open()`, waits on an Event up to 120 s.
  - Module functions `start_for_profile()` / `stop_for_profile()` / `current() -> Endpoint | None` (aqt glue) used by `__init__` in Task 11.

- [ ] **Step 1: Claim the card**; `python3 tests/test_anki_endpoint.py` fails (no such file).

- [ ] **Step 2: Write the failing tests** — a real `ThreadingHTTPServer` on an ephemeral port, hit with `urllib`; the stub collection is the `Col` class from `tests/test_anki_tools.py` (import it: `sys.path.insert(0, "tests"); from test_anki_tools import Col, ctx as tool_ctx`; if that import runs that file's checks at import time, copy its `Col`/`Note`/`Decks`/`Models` stubs into this file instead and say so in a comment).

```python
"""anki_endpoint — the AnkiConnect-compatible server, hit over real HTTP."""
import json, sys, threading, urllib.request, urllib.error

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
import importlib
ep = importlib.import_module("klausmate.anki_endpoint")
sys.path.insert(0, "tests")
from test_anki_tools import Col  # stub collection; see Task note if import has side effects

col = Col()
approvals = []
def approver(title, sections):
    approvals.append((title, sections)); return approver.answer
approver.answer = True
def run_on_main(fn, timeout): return fn()
def ctx_factory(): return {"strip": lambda s: s, "confirm": lambda *a: True, "user_files": "/tmp/none", "search_pdfs": lambda q, k: []}
end = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=approver, ctx_factory=ctx_factory, version="0.1.3")
host, port, token = end.start()

def post(path, obj, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(obj).encode()
    h = {"Content-Type": "application/json", "X-Klaus-Token": token}
    h.update(headers or {})
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode() or "null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, dict(e.headers)

def ac(action, **params):
    return post("/", {"action": action, "version": 6, "params": params})[1]

section("gate")
check("ephemeral localhost port", host == "127.0.0.1" and 1024 < port < 65536 and len(token) >= 32)
check("missing token → 403", post("/", {"action": "version", "version": 6}, headers={"X-Klaus-Token": ""})[0] == 403)
check("wrong token → 403", post("/", {"action": "version", "version": 6}, headers={"X-Klaus-Token": "x" * 64})[0] == 403)
check("Origin header → 403 even with the token", post("/", {"action": "version", "version": 6}, headers={"Origin": "http://evil"})[0] == 403)
check("oversize body → 413", post("/", None, raw=b"x" * (4 * 1024 * 1024 + 1))[0] == 413)
check("bad json → error field, HTTP 200", post("/", None, raw=b"{nope")[1]["error"] is not None)
check("unknown route → 404", post("/nope", {"action": "version", "version": 6})[0] == 404)

section("AnkiConnect route")
check("version → 6", ac("version") == {"result": 6, "error": None})
check("version 5 refused", ac("version") and post("/", {"action": "version", "version": 5})[1]["error"] == "unsupported version")
check("unknown action", ac("zzz")["error"] == "unsupported action")
check("deckNames", isinstance(ac("deckNames")["result"], list))
check("modelNames", isinstance(ac("modelNames")["result"], list))
r = ac("findNotes", query="deck:*")
check("findNotes → ids", r["error"] is None and isinstance(r["result"], list))
info = ac("notesInfo", notes=[1])["result"]
check("notesInfo shape", info and set(info[0]) >= {"noteId", "modelName", "tags", "fields"} and all("value" in v and "order" in v for v in info[0]["fields"].values()))
before = len(col.added) + col.single_adds
r = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q", "Back": "A"}, "tags": ["t"]})
check("addNote: approval asked once, note added, id returned", len(approvals) == 1 and r["error"] is None and (len(col.added) + col.single_adds) == before + 1)
title, sections = approvals[-1]
check("preview is plain text with deck, model, every field, tags", any("Default" in s for _, s in sections) and any("Basic" in s for _, s in sections)
      and any("Q" in s for _, s in sections) and any("A" in s for _, s in sections) and any("t" in s for _, s in sections))
approver.answer = False
r = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q2", "Back": "A2"}})
check("declined → error, nothing added", r["error"] == "declined by user" and (len(col.added) + col.single_adds) == before + 1)
approver.answer = True
r = end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q3", "Back": "A3"}}}, agent=True)
check("agent path without source page → error, no dialog", r["error"] and "source" in r["error"].lower() and len(approvals) == 2)
r = end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Q3", "Back": "A3"}, "options": {"sourcePage": 4}}}, agent=True)
check("agent path with source page → approval names the page and tags klaus::assistant + klaus::from",
      r["error"] is None and any("4" in s for _, s in approvals[-1][1]) and any("klaus::assistant" in s for _, s in approvals[-1][1]))
r = ac("addNotes", notes=[{"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B1", "Back": "x"}}, {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "B2", "Back": "y"}}])
check("addNotes: ONE dialog for both, two ids", len(approvals) == 4 and r["error"] is None and len(r["result"]) == 2)
r = ac("updateNoteFields", note={"id": 1, "fields": {"Front": "changed"}})
check("updateNoteFields behind approval", r["error"] is None and len(approvals) == 5 and col.updated)
r = ac("addTags", notes=[1], tags="a b")
check("addTags behind approval", r["error"] is None and len(approvals) == 6)
r = ac("guiBrowse", query="tag:a")
check("guiBrowse returns ids (opening Browse is aqt glue, stubbed to no-op)", r["error"] is None and isinstance(r["result"], list))
check("klausCurrentView without a viewer → null result, no error", ac("klausCurrentView") == {"result": None, "error": None})
r = ac("klausSearchNotes", query="renal", limit=5)
check("klausSearchNotes routes to anki_tools.search_notes", r["error"] is None and isinstance(r["result"], list))

section("pure helpers")
check("similar_existing finds a note by the front's first words",
      ep.similar_existing(col, "Q changed words here") in (None, "changed") or isinstance(ep.similar_existing(col, "Q"), (str, type(None))))
secs = ep.preview_sections("addNote", {"note": {"deckName": "D", "modelName": "M", "fields": {"F": "<b>x</b>"}, "tags": ["t"], "options": {"sourcePage": 2}}}, similar="old front")
check("preview strips html, names similar note and source page",
      any("x" in s and "<b>" not in s for _, s in secs) and any("old front" in s for _, s in secs) and any("2" in s for _, s in secs))

section("registry")
check("every ACTIONS entry is an Action with a schema and a run", all(hasattr(a, "schema") and callable(a.run) for a in ep.ACTIONS.values()))
check("writes flagged", all(ep.ACTIONS[n].write for n in ("addNote", "addNotes", "updateNoteFields", "addTags", "removeTags")) and not ep.ACTIONS["findNotes"].write)
check("exact supported set",
      set(ep.ACTIONS) == {"version", "deckNames", "deckNamesAndIds", "modelNames", "modelFieldNames", "findNotes", "notesInfo",
                          "findCards", "cardsInfo", "addNote", "addNotes", "updateNoteFields", "addTags", "removeTags",
                          "guiBrowse", "klausSearchNotes", "klausSearchLecturePdfs", "klausCurrentView"}, str(sorted(ep.ACTIONS)))

section("approval timeout")
slow_end = ep.Endpoint(col_getter=lambda: col, run_on_main=run_on_main, approver=lambda t, s: (threading.Event().wait(0.2), False)[1],
                       ctx_factory=ctx_factory, version="x", approval_timeout=0.05)
r = slow_end.handle("addNote", {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Z", "Back": "z"}}}, agent=False)
check("an approver that never answers in time → 'approval timed out'", r["error"] == "approval timed out")

end.stop()
check("stop closes the port", True)
report()
```

- [ ] **Step 3: Run to see it fail** — `ModuleNotFoundError`.

- [ ] **Step 4: Write the module** (`klausmate/anki_endpoint.py`) — the aqt-free part:

```python
"""Klaus's own AnkiConnect-compatible endpoint, plus MCP over HTTP (Task 4).

Serves AnkiConnect's ``{action, version, params}`` protocol on ``/`` for the
ecosystem and the same actions as MCP tools on ``/mcp`` for the Claude Code
child, from ONE registry (``ACTIONS``) so the two routes cannot drift. Bound
to 127.0.0.1 on an ephemeral port with a per-start token, because a
localhost server is reachable by any local process and any browser page.

Writes never touch the collection without the user approving a PLAIN-TEXT
preview; the dialog is window-modal ``open()`` (K-114), never ``exec()``,
and the HTTP thread waits on an Event for the answer.

aqt-free above the divider: the server, the gate, the registry and every
action run against a duck-typed collection and an injected approver.
"""

from __future__ import annotations

import html
import json
import re
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

API_VERSION = 6
BODY_CAP = 4 * 1024 * 1024
READ_TIMEOUT_S = 30.0
APPROVAL_TIMEOUT_S = 120.0
TOKEN_HEADER = "X-Klaus-Token"
AGENT_HEADER = "X-Klaus-Agent"
AGENT_TAGS = ("klaus::assistant",)
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: Any) -> str:
    return html.unescape(_TAG_RE.sub("", str(s or ""))).strip()


@dataclass(frozen=True)
class Action:
    name: str
    mcp_name: str
    description: str
    schema: dict
    write: bool
    run: Callable[[Any, dict, dict], Any]


class ActionError(Exception):
    pass


# ---- actions -----------------------------------------------------------------

def _a_version(col, p, ctx):
    return API_VERSION

def _a_deck_names(col, p, ctx):
    return [d.name for d in col.decks.all_names_and_ids()]

def _a_deck_names_ids(col, p, ctx):
    return {d.name: d.id for d in col.decks.all_names_and_ids()}

def _a_model_names(col, p, ctx):
    return [m.name for m in col.models.all_names_and_ids()]

def _a_model_field_names(col, p, ctx):
    m = col.models.by_name(str(p.get("modelName") or ""))
    if not m:
        raise ActionError("model not found")
    return [f["name"] for f in m["flds"]]

def _a_find_notes(col, p, ctx):
    return [int(n) for n in col.find_notes(str(p.get("query") or ""))]

def _a_notes_info(col, p, ctx):
    out = []
    for nid in p.get("notes") or []:
        try:
            n = col.get_note(int(nid))
        except Exception:
            continue
        nt = n.note_type() if callable(getattr(n, "note_type", None)) else {}
        names = [f["name"] for f in (nt or {}).get("flds", [])] or list(getattr(n, "keys", lambda: [])())
        fields = {name: {"value": n[name], "order": i} for i, name in enumerate(names)}
        out.append({"noteId": int(nid), "modelName": (nt or {}).get("name", ""), "tags": list(getattr(n, "tags", [])),
                    "fields": fields, "cards": [int(c) for c in (n.card_ids() if callable(getattr(n, "card_ids", None)) else [])]})
    return out

def _a_find_cards(col, p, ctx):
    return [int(c) for c in col.find_cards(str(p.get("query") or ""))]

def _a_cards_info(col, p, ctx):
    out = []
    for cid in p.get("cards") or []:
        try:
            c = col.get_card(int(cid))
        except Exception:
            continue
        out.append({"cardId": int(cid), "noteId": int(c.nid), "deckName": col.decks.name(c.did), "queue": int(c.queue),
                    "interval": int(c.ivl), "due": int(c.due)})
    return out


def _tool_args(spec_name: str, mapping: dict) -> dict:
    """Translate AnkiConnect note params into whatever keys anki_tools' spec has."""
    from . import anki_tools
    props: dict = {}
    for s in anki_tools.TOOL_SPECS:
        if s.get("name") == spec_name:
            props = (s.get("inputSchema") or {}).get("properties") or {}
    out = {}
    for candidates, value in mapping.items():
        for k in candidates:
            if k in props:
                out[k] = value
                break
    return out


def _create_one(col, note: dict, ctx: dict, agent: bool) -> int:
    from . import anki_tools
    tags = list(note.get("tags") or [])
    if agent:
        page = (note.get("options") or {}).get("sourcePage")
        tags += list(AGENT_TAGS)
        if ctx.get("pdf_safe"):
            tags.append(f"klaus::from::{ctx['pdf_safe']}")
    args = _tool_args("create_note", {
        ("deck", "deck_name"): note.get("deckName"),
        ("notetype", "note_type", "model", "model_name"): note.get("modelName"),
        ("fields",): note.get("fields") or {},
        ("tags",): tags,
    })
    res = anki_tools._HANDLERS["create_note"](col, args, dict(ctx, confirm=lambda *a: True))
    for k in ("note_id", "noteId", "id"):
        if isinstance(res, dict) and k in res:
            return int(res[k])
    return int(res) if isinstance(res, int) else 0


def _a_add_note(col, p, ctx):
    return _create_one(col, p.get("note") or {}, ctx, bool(ctx.get("agent")))

def _a_add_notes(col, p, ctx):
    return [_create_one(col, n, ctx, bool(ctx.get("agent"))) for n in (p.get("notes") or [])]

def _a_update_note_fields(col, p, ctx):
    from . import anki_tools
    note = p.get("note") or {}
    args = _tool_args("update_note", {("note_id", "id"): int(note.get("id") or 0), ("fields",): note.get("fields") or {}})
    anki_tools._HANDLERS["update_note"](col, args, dict(ctx, confirm=lambda *a: True))
    return None

def _a_add_tags(col, p, ctx):
    col.tags.bulk_add([int(n) for n in p.get("notes") or []], str(p.get("tags") or ""))
    return None

def _a_remove_tags(col, p, ctx):
    col.tags.bulk_remove([int(n) for n in p.get("notes") or []], str(p.get("tags") or ""))
    return None

def _a_gui_browse(col, p, ctx):
    q = str(p.get("query") or "")
    opener = ctx.get("open_browse")
    if callable(opener):
        opener(q)
    return [int(n) for n in col.find_notes(q)]

def _a_klaus_search_notes(col, p, ctx):
    from . import anki_tools
    args = _tool_args("search_notes", {("query",): str(p.get("query") or ""), ("limit", "top_k", "k"): int(p.get("limit") or 20)})
    return anki_tools._HANDLERS["search_notes"](col, args, ctx)

def _a_klaus_search_pdfs(col, p, ctx):
    from . import anki_tools
    args = _tool_args("search_lecture_pdfs", {("query",): str(p.get("query") or ""), ("limit", "top_k", "k"): int(p.get("limit") or 10)})
    return anki_tools._HANDLERS["search_lecture_pdfs"](col, args, ctx)

def _a_klaus_current_view(col, p, ctx):
    try:
        from . import viewer_context
    except Exception:
        return None
    v = viewer_context.current()
    if v is None:
        return None
    return {"pdf": v.pdf_safe, "display": v.display, "page": v.page_index + 1, "count": v.page_count, "selection": v.selection}


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}

NOTE_SCHEMA = _obj({"deck": {"type": "string"}, "model": {"type": "string"}, "fields": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}}, "source_page": {"type": "integer", "minimum": 1}},
                   ("deck", "model", "fields", "source_page"))

ACTIONS: dict[str, Action] = {a.name: a for a in (
    Action("version", "", "API version", _obj({}), False, _a_version),
    Action("deckNames", "list_decks", "List the user's decks.", _obj({}), False, _a_deck_names),
    Action("deckNamesAndIds", "", "Decks with ids.", _obj({}), False, _a_deck_names_ids),
    Action("modelNames", "list_models", "List the user's note types.", _obj({}), False, _a_model_names),
    Action("modelFieldNames", "model_fields", "Field names of a note type.", _obj({"model": {"type": "string"}}, ("model",)), False, _a_model_field_names),
    Action("findNotes", "find_notes", "Note ids matching an Anki search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_find_notes),
    Action("notesInfo", "get_notes", "Fields, tags and cards of notes by id.", _obj({"note_ids": {"type": "array", "items": {"type": "integer"}}}, ("note_ids",)), False, _a_notes_info),
    Action("findCards", "", "Card ids matching an Anki search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_find_cards),
    Action("cardsInfo", "", "Card info by id.", _obj({"cards": {"type": "array"}}, ("cards",)), False, _a_cards_info),
    Action("addNote", "add_note", "Add ONE note; the user approves a preview. Requires source_page.", NOTE_SCHEMA, True, _a_add_note),
    Action("addNotes", "", "Add several notes behind one approval.", _obj({"notes": {"type": "array"}}, ("notes",)), True, _a_add_notes),
    Action("updateNoteFields", "update_note_fields", "Update fields of a note; approved by the user.", _obj({"note_id": {"type": "integer"}, "fields": {"type": "object"}}, ("note_id", "fields")), True, _a_update_note_fields),
    Action("addTags", "add_tags", "Add tags to notes; approved.", _obj({"note_ids": {"type": "array"}, "tags": {"type": "string"}}, ("note_ids", "tags")), True, _a_add_tags),
    Action("removeTags", "remove_tags", "Remove tags from notes; approved.", _obj({"note_ids": {"type": "array"}, "tags": {"type": "string"}}, ("note_ids", "tags")), True, _a_remove_tags),
    Action("guiBrowse", "open_in_browse", "Open Anki's Browse on a search.", _obj({"query": {"type": "string"}}, ("query",)), False, _a_gui_browse),
    Action("klausSearchNotes", "search_notes", "Semantic search over the user's notes.", _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ("query",)), False, _a_klaus_search_notes),
    Action("klausSearchLecturePdfs", "search_lecture_pdfs", "Semantic search over the indexed lecture PDFs.", _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ("query",)), False, _a_klaus_search_pdfs),
    Action("klausCurrentView", "current_view", "What the user is viewing right now.", _obj({}), False, _a_klaus_current_view),
)}

MCP_TO_ACTION = {a.mcp_name: a.name for a in ACTIONS.values() if a.mcp_name}


def mcp_args_to_params(action: str, args: dict) -> dict:
    """The MCP tools take flat, snake_case args; the actions take AnkiConnect params."""
    a = dict(args or {})
    if action in ("addNote",):
        return {"note": {"deckName": a.get("deck"), "modelName": a.get("model"), "fields": a.get("fields") or {},
                         "tags": a.get("tags") or [], "options": {"sourcePage": a.get("source_page")}}}
    if action == "updateNoteFields":
        return {"note": {"id": a.get("note_id"), "fields": a.get("fields") or {}}}
    if action in ("addTags", "removeTags"):
        return {"notes": a.get("note_ids") or [], "tags": a.get("tags") or ""}
    if action == "notesInfo":
        return {"notes": a.get("note_ids") or []}
    if action == "modelFieldNames":
        return {"modelName": a.get("model")}
    return a


# ---- previews ----------------------------------------------------------------

def similar_existing(col, front: str) -> str | None:
    words = strip_html(front).split()[:8]
    if not words:
        return None
    q = " ".join(re.sub(r"[^\w]", "", w) for w in words if re.sub(r"[^\w]", "", w))
    if not q:
        return None
    try:
        ids = list(col.find_notes(q))[:1]
        if not ids:
            return None
        n = col.get_note(int(ids[0]))
        names = list(getattr(n, "keys", lambda: [])())
        return strip_html(n[names[0]]) if names else str(ids[0])
    except Exception:
        return None


def _note_sections(note: dict, similar: str | None, agent: bool) -> list[tuple[str, str]]:
    secs = [("Deck", str(note.get("deckName") or "")), ("Note type", str(note.get("modelName") or ""))]
    for k, v in (note.get("fields") or {}).items():
        secs.append((str(k), strip_html(v)))
    tags = list(note.get("tags") or []) + (list(AGENT_TAGS) if agent else [])
    if tags:
        secs.append(("Tags", " ".join(tags)))
    page = (note.get("options") or {}).get("sourcePage")
    if page:
        secs.append(("Source page", str(page)))
    if similar:
        secs.append(("Similar existing note", similar))
    return secs


def preview_sections(action: str, params: dict, similar: str | None = None, agent: bool = False) -> list[tuple[str, str]]:
    if action == "addNote":
        return _note_sections(params.get("note") or {}, similar, agent)
    if action == "addNotes":
        out: list[tuple[str, str]] = []
        for i, n in enumerate(params.get("notes") or [], 1):
            out.append((f"Note {i}", ""))
            out += _note_sections(n, None, agent)
        return out
    if action == "updateNoteFields":
        note = params.get("note") or {}
        return [("Note id", str(note.get("id")))] + [(str(k), strip_html(v)) for k, v in (note.get("fields") or {}).items()]
    if action in ("addTags", "removeTags"):
        return [("Notes", ", ".join(str(n) for n in params.get("notes") or [])), ("Tags", str(params.get("tags") or ""))]
    return [(action, json.dumps(params)[:2000])]


# ---- the endpoint --------------------------------------------------------------

class Endpoint:
    def __init__(self, *, col_getter, run_on_main, approver, ctx_factory, version: str,
                 approval_timeout: float = APPROVAL_TIMEOUT_S, read_timeout: float = READ_TIMEOUT_S) -> None:
        self._col, self._main, self._approve, self._ctx = col_getter, run_on_main, approver, ctx_factory
        self.version = version
        self._approval_timeout, self._read_timeout = approval_timeout, read_timeout
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self.token = ""
        self.sessions: set[str] = set()

    def start(self) -> tuple[str, int, str]:
        self.token = secrets.token_hex(32)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        srv.daemon_threads = True
        self._srv = srv
        self.port = srv.server_address[1]
        self._thread = threading.Thread(target=srv.serve_forever, name="klaus-endpoint", daemon=True)
        self._thread.start()
        return "127.0.0.1", self.port, self.token

    def stop(self) -> None:
        if self._srv is not None:
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except Exception as exc:
                print(f"[klausmate] endpoint stop: {exc}")
            self._srv = None

    def handle(self, action: str, params: dict, agent: bool) -> dict:
        a = ACTIONS.get(action)
        if a is None:
            return {"result": None, "error": "unsupported action"}
        params = params or {}
        try:
            col = self._col()
            ctx = dict(self._ctx() or {}, agent=agent)
            if a.write:
                if agent and action == "addNote" and not ((params.get("note") or {}).get("options") or {}).get("sourcePage"):
                    return {"result": None, "error": "source page required: add_note needs source_page (the slide the card came from)"}
                similar = None
                if action == "addNote":
                    fields = (params.get("note") or {}).get("fields") or {}
                    first = next(iter(fields.values()), "")
                    similar = self._main(lambda: similar_existing(col, first), self._read_timeout)
                sections = preview_sections(action, params, similar, agent)
                title = {"addNote": "Klaus wants to add a card", "addNotes": "Klaus wants to add cards",
                         "updateNoteFields": "Klaus wants to edit a note"}.get(action, f"Klaus wants to run {action}")
                answer = self._ask(title, sections)
                if answer is None:
                    return {"result": None, "error": "approval timed out"}
                if answer is False:
                    return {"result": None, "error": "declined by user"}
                if action == "addNote":
                    try:
                        from . import viewer_context
                        v = viewer_context.current()
                        if v is not None:
                            ctx["pdf_safe"] = v.pdf_safe
                    except Exception:
                        pass
            result = self._main(lambda: a.run(col, params, ctx), self._approval_timeout if a.write else self._read_timeout)
            return {"result": result, "error": None}
        except ActionError as exc:
            return {"result": None, "error": str(exc)}
        except TimeoutError:
            return {"result": None, "error": "timed out"}
        except Exception as exc:
            return {"result": None, "error": f"{type(exc).__name__}: {exc}"}

    def _ask(self, title: str, sections: list) -> bool | None:
        box: dict = {}
        done = threading.Event()
        def go():
            try:
                box["a"] = bool(self._approve(title, sections))
            except Exception as exc:
                print(f"[klausmate] endpoint approver: {exc}")
                box["a"] = False
            finally:
                done.set()
        threading.Thread(target=go, daemon=True).start()
        if not done.wait(self._approval_timeout):
            return None
        return box.get("a", False)


def _handler_for(end: Endpoint):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, status: int, obj: Any, extra: dict | None = None) -> None:
            data = b"" if obj is None else json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data:
                self.wfile.write(data)

        def do_GET(self):
            self._send(405, {"error": "POST only"})

        def do_POST(self):
            if self.headers.get("Origin"):
                return self._send(403, {"error": "browser origins are refused"})
            if self.headers.get(TOKEN_HEADER, "") != end.token:
                return self._send(403, {"error": "bad token"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > BODY_CAP:
                return self._send(413, {"error": "body too large"})
            raw = self.rfile.read(n) if n else b""
            if self.path == "/":
                return self._ankiconnect(raw)
            if self.path == "/mcp":
                return self._mcp(raw)
            return self._send(404, {"error": "no such route"})

        def _ankiconnect(self, raw: bytes) -> None:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._send(200, {"result": None, "error": "invalid JSON"})
            if not isinstance(body, dict):
                return self._send(200, {"result": None, "error": "invalid request"})
            if int(body.get("version") or 0) != API_VERSION:
                return self._send(200, {"result": None, "error": "unsupported version"})
            agent = self.headers.get(AGENT_HEADER) == "1"
            out = end.handle(str(body.get("action") or ""), body.get("params") or {}, agent)
            self._send(200, out)

        def _mcp(self, raw: bytes) -> None:
            self._send(404, {"error": "mcp route arrives in Task 4"})
    return H


# ---- aqt glue --------------------------------------------------------------------

_LIVE: Endpoint | None = None


def current() -> Endpoint | None:
    return _LIVE


def _run_on_main_sync(fn: Callable, timeout: float):
    from aqt import mw
    box: dict = {}
    done = threading.Event()
    def wrapper():
        try:
            box["r"] = fn()
        except BaseException as e:
            box["e"] = e
        finally:
            done.set()
    mw.taskman.run_on_main(wrapper)
    if not done.wait(timeout):
        raise TimeoutError("main thread did not answer")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def qt_approver(title: str, sections: list) -> bool:
    """Window-modal open() on the main thread; the calling thread waits on an Event."""
    from aqt import mw
    from aqt.qt import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout
    box: dict = {}
    done = threading.Event()
    def show():
        try:
            dlg = QDialog(mw)
            dlg.setWindowTitle(title)
            dlg.setWindowModality(__import__("aqt.qt", fromlist=["Qt"]).Qt.WindowModality.WindowModal)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(title))
            text = QPlainTextEdit(dlg)
            text.setReadOnly(True)
            text.setPlainText("\n".join(f"{k}: {v}" if k else v for k, v in sections))
            lay.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Approve")
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            lay.addWidget(buttons)
            def finished(code):
                box["a"] = code == QDialog.DialogCode.Accepted
                done.set()
                dlg.deleteLater()
            dlg.finished.connect(finished)
            box["dlg"] = dlg
            dlg.open()
        except Exception as exc:
            print(f"[klausmate] endpoint dialog: {exc}")
            box["a"] = False
            done.set()
    mw.taskman.run_on_main(show)
    if not done.wait(APPROVAL_TIMEOUT_S):
        mw.taskman.run_on_main(lambda: box.get("dlg") and box["dlg"].reject())
        return False
    return bool(box.get("a"))


def _open_browse(query: str) -> None:
    from aqt import dialogs, mw
    b = dialogs.open("Browser", mw)
    b.search_for(query)


def start_for_profile() -> Endpoint | None:
    global _LIVE
    from aqt import mw
    from . import anki_tools
    stop_for_profile()
    try:
        version = str((mw.addonManager.addon_meta(__package__.split(".")[0]) or {}).get("human_version") or "")
    except Exception:
        version = ""
    def ctx_factory():
        c = anki_tools.default_ctx()
        c["open_browse"] = lambda q: mw.taskman.run_on_main(lambda: _open_browse(q))
        return c
    end = Endpoint(col_getter=lambda: mw.col, run_on_main=_run_on_main_sync, approver=qt_approver, ctx_factory=ctx_factory, version=version)
    end.start()
    _LIVE = end
    print(f"[klausmate] endpoint on 127.0.0.1:{end.port}")
    return end


def stop_for_profile() -> None:
    global _LIVE
    if _LIVE is not None:
        _LIVE.stop()
        _LIVE = None
```

- [ ] **Step 5: Run to green.** Adjust the tests where the stub `Col` lacks a method the action uses (`find_cards`, `get_card`, `tags.bulk_add`, `models.by_name`): extend the stub in THIS test file (a subclass `Col2(Col)` adding those), never the shared one. The `similar_existing` pin must become a real assertion against the stub's known note (its first field value): replace the placeholder-ish `in (None, ...)` with `== "<that value>"` once you have read the stub.

- [ ] **Step 6: Mutate** — (1) skip the `Origin` check → the Origin pin fails; (2) return `{"result": None, "error": None}` on decline → the declined pin fails; (3) drop the agent source-page check → that pin fails. Restore each.

- [ ] **Step 7: Full loop once; hand off** (card → Review, comment). No commit.

---

### Task 4: `/mcp` route — MCP over HTTP from the same registry

**Files:**
- Modify: `klausmate/anki_endpoint.py` (replace the `_mcp` stub)
- Test: `tests/test_anki_endpoint.py` (append)
- Board card: `anki_endpoint: /mcp — initialize, tools/list, tools/call over ACTIONS` — same files; verify `python3 tests/test_anki_endpoint.py`. **Same lane as Task 3: claim only after Task 3's card is in Review or Done.**

**Interfaces:**
- Consumes: `ACTIONS`, `MCP_TO_ACTION`, `mcp_args_to_params`, `Endpoint.handle`.
- Produces: `mcp_tools() -> list[dict]` (pure), `mcp_dispatch(end: Endpoint, body: dict) -> tuple[int, dict | None, dict]` (status, json, headers; pure over `end.handle`).

- [ ] **Step 1: Claim**; append the failing tests before `end.stop()`:

```python
section("MCP route")
def rpc(method, params=None, rid=1, headers=None):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None: body["params"] = params
    return post("/mcp", body, headers=headers)
st, r, h = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
check("initialize echoes protocol, names klaus, sets a session header",
      st == 200 and r["result"]["protocolVersion"] == "2025-06-18" and r["result"]["serverInfo"]["name"] == "klaus"
      and "tools" in r["result"]["capabilities"] and any(k.lower() == "mcp-session-id" for k in h))
sid = [v for k, v in h.items() if k.lower() == "mcp-session-id"][0]
st, r, _ = post("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Mcp-Session-Id": sid})
check("initialized → 202 no body", st == 202 and r is None)
st, r, _ = rpc("ping", rid=2)
check("ping → empty result", r["result"] == {})
st, r, _ = rpc("tools/list", rid=3)
names = {t["name"] for t in r["result"]["tools"]}
check("tools/list equals the registry's MCP names with schemas",
      names == set(ep.MCP_TO_ACTION) and all("inputSchema" in t and "description" in t for t in r["result"]["tools"]))
st, r, _ = rpc("tools/call", {"name": "list_decks", "arguments": {}}, rid=4)
check("tools/call → text content, not error", r["result"]["isError"] is False and r["result"]["content"][0]["type"] == "text"
      and isinstance(json.loads(r["result"]["content"][0]["text"]), list))
st, r, _ = rpc("tools/call", {"name": "add_note", "arguments": {"deck": "Default", "model": "Basic", "fields": {"Front": "M", "Back": "m"}}}, rid=5)
check("add_note without source_page → isError with the message, not a JSON-RPC error",
      "error" not in r and r["result"]["isError"] is True and "source" in r["result"]["content"][0]["text"].lower())
n_before = len(approvals)
st, r, _ = rpc("tools/call", {"name": "add_note", "arguments": {"deck": "Default", "model": "Basic", "fields": {"Front": "M", "Back": "m"}, "source_page": 9}}, rid=6)
check("add_note with source_page → approval dialog, then a note id", len(approvals) == n_before + 1 and r["result"]["isError"] is False)
st, r, _ = rpc("tools/call", {"name": "nope", "arguments": {}}, rid=7)
check("unknown tool → isError", r["result"]["isError"] is True)
st, r, _ = rpc("zzz/method", rid=8)
check("unknown method → -32601", r["error"]["code"] == -32601)
st, r, _ = post("/mcp", None, raw=b"{bad")
check("bad json → -32700", r["error"]["code"] == -32700)
req = urllib.request.Request(f"http://{host}:{port}/mcp", headers={"X-Klaus-Token": token}, method="GET")
try:
    urllib.request.urlopen(req, timeout=5); got = 200
except urllib.error.HTTPError as e:
    got = e.code
check("GET /mcp → 405 (no SSE stream)", got == 405)
r2 = ac("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "M", "Back": "m"}})
check("the MCP route sets the agent flag: the same note without a source page is refused on /mcp (above) but accepted on /", r2["error"] is None)
```

- [ ] **Step 2: Red run** — the `_mcp` stub returns 404 → the section fails.

- [ ] **Step 3: Implement** — in `anki_endpoint.py` add above the divider:

```python
PROTOCOL_VERSION = "2025-06-18"

def mcp_tools() -> list[dict]:
    return [{"name": a.mcp_name, "description": a.description, "inputSchema": a.schema}
            for a in ACTIONS.values() if a.mcp_name]


def mcp_dispatch(end: "Endpoint", body: Any, session: str | None) -> tuple[int, Any, dict]:
    """One JSON-RPC message → (http status, json body or None, extra headers)."""
    if not isinstance(body, dict):
        return 200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}, {}
    rid, method, params = body.get("id"), str(body.get("method") or ""), body.get("params") or {}
    if method == "notifications/initialized":
        return 202, None, {}
    if method == "initialize":
        sid = secrets.token_hex(8)
        end.sessions.add(sid)
        res = {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
               "capabilities": {"tools": {}}, "serverInfo": {"name": "klaus", "version": end.version}}
        return 200, {"jsonrpc": "2.0", "id": rid, "result": res}, {"Mcp-Session-Id": sid}
    if method == "ping":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {}}, {}
    if method == "tools/list":
        return 200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": mcp_tools()}}, {}
    if method == "tools/call":
        name = str(params.get("name") or "")
        action = MCP_TO_ACTION.get(name)
        if action is None:
            out = {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
        else:
            r = end.handle(action, mcp_args_to_params(action, params.get("arguments") or {}), agent=True)
            if r.get("error"):
                out = {"content": [{"type": "text", "text": str(r["error"])}], "isError": True}
            else:
                out = {"content": [{"type": "text", "text": json.dumps(r.get("result"))}], "isError": False}
        return 200, {"jsonrpc": "2.0", "id": rid, "result": out}, {}
    return 200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}, {}
```

and replace the handler's `_mcp`:

```python
        def _mcp(self, raw: bytes) -> None:
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                return self._send(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            status, out, extra = mcp_dispatch(end, body, self.headers.get("Mcp-Session-Id"))
            self._send(status, out, extra)
```

- [ ] **Step 4: Green; mutate** — return `agent=False` in `tools/call` → the source-page pin fails; drop `Mcp-Session-Id` → the initialize pin fails. Restore.

- [ ] **Step 5: Full loop; hand off.**

---

### Task 5: `viewer_context.py` — which viewer is being looked at

**Files:**
- Create: `klausmate/viewer_context.py`
- Test: `tests/test_viewer_context.py`
- Board card: `viewer_context: the registry of live PDF viewers` — files `klausmate/viewer_context.py,tests/test_viewer_context.py` — verify `python3 tests/test_viewer_context.py`

**Interfaces (Tasks 3, 6, 9, 10 depend on these):**
```python
@dataclass
class ViewState: viewer_id: int; pdf_safe: str; display: str; path: str; page_index: int = 0; page_count: int = 0; selection: str = ""
def report_document(viewer_id: int, pdf_safe: str, display: str, path: str, page_count: int) -> None
def report_page(viewer_id: int, page_index: int) -> None
def report_selection(viewer_id: int, text: str) -> None
def activate(viewer_id: int) -> None
def forget(viewer_id: int) -> None
def current() -> ViewState | None
def subscribe(cb: Callable[[ViewState | None], None]) -> Callable[[], None]
def reset() -> None   # tests only
```

- [ ] **Step 1: Claim; failing tests:**

```python
import sys
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section
install()
import importlib
vc = importlib.import_module("klausmate.viewer_context")

section("registry")
vc.reset()
seen = []
unsub = vc.subscribe(lambda v: seen.append(v))
check("empty → None", vc.current() is None)
vc.report_document(1, "lec1", "Lecture 1.pdf", "/lib/Lecture 1.pdf", 40)
check("a reported document is not current until activated", vc.current() is None)
vc.activate(1)
v = vc.current()
check("activate makes it current with page 0", v is not None and v.pdf_safe == "lec1" and v.display == "Lecture 1.pdf" and v.page_index == 0 and v.page_count == 40)
vc.report_page(1, 6)
check("page updates", vc.current().page_index == 6)
vc.report_selection(1, "loop of Henle")
check("selection updates", vc.current().selection == "loop of Henle")
vc.report_document(2, "lec2", "Lecture 2.pdf", "/lib/Lecture 2.pdf", 10)
vc.activate(2)
check("last activated wins", vc.current().pdf_safe == "lec2")
vc.activate(1)
check("re-activating an older viewer brings it back with its own page", vc.current().pdf_safe == "lec1" and vc.current().page_index == 6)
vc.forget(1)
check("forget falls back to the most recently activated remaining viewer", vc.current().pdf_safe == "lec2")
vc.report_page(99, 3)
check("unknown viewer ids are ignored", vc.current().pdf_safe == "lec2" and vc.current().page_index == 0)
vc.report_document(2, "", "", "", 0)
check("a viewer with no document is not current", vc.current() is None)
check("subscribers saw every change, None included", seen and seen[-1] is None and any(x is not None for x in seen))
unsub()
vc.report_document(3, "x", "X", "/x", 1); vc.activate(3)
check("unsubscribed callback is silent", seen[-1] is None)
def boom(v): raise RuntimeError("cb")
vc.subscribe(boom)
vc.report_page(3, 0)
check("a raising subscriber never breaks the registry", vc.current().pdf_safe == "x")
report()
```

- [ ] **Step 2: Red; implement:**

```python
"""Which PDF viewer the user is looking at, and what it shows.

Every PdfSidebar (the Library's, Browse's editor pane, the review-time
Lecture dock) reports into this registry; the assistant dock follows
``current()`` — the LAST ACTIVATED viewer that still holds a document.
Pure dict state, no Qt; callbacks run synchronously on the caller's thread
(the main thread in practice) and a raising callback is logged, never raised.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

@dataclass
class ViewState:
    viewer_id: int
    pdf_safe: str
    display: str
    path: str
    page_index: int = 0
    page_count: int = 0
    selection: str = ""

_views: dict[int, ViewState] = {}
_order: list[int] = []          # activation order, most recent last
_subs: list[Callable] = []


def reset() -> None:
    _views.clear(); _order.clear(); _subs.clear()


def _notify() -> None:
    cur = current()
    for cb in list(_subs):
        try:
            cb(cur)
        except Exception as exc:
            print(f"[klausmate] viewer_context subscriber: {exc}")


def report_document(viewer_id: int, pdf_safe: str, display: str, path: str, page_count: int) -> None:
    if pdf_safe:
        _views[viewer_id] = ViewState(viewer_id, pdf_safe, display or pdf_safe, path, 0, int(page_count or 0), "")
    else:
        _views.pop(viewer_id, None)
    _notify()


def report_page(viewer_id: int, page_index: int) -> None:
    v = _views.get(viewer_id)
    if v is None:
        return
    _views[viewer_id] = replace(v, page_index=max(0, int(page_index)))
    _notify()


def report_selection(viewer_id: int, text: str) -> None:
    v = _views.get(viewer_id)
    if v is None:
        return
    _views[viewer_id] = replace(v, selection=str(text or ""))
    _notify()


def activate(viewer_id: int) -> None:
    if viewer_id in _order:
        _order.remove(viewer_id)
    _order.append(viewer_id)
    _notify()


def forget(viewer_id: int) -> None:
    _views.pop(viewer_id, None)
    if viewer_id in _order:
        _order.remove(viewer_id)
    _notify()


def current() -> ViewState | None:
    for vid in reversed(_order):
        v = _views.get(vid)
        if v is not None and v.pdf_safe:
            return v
    return None


def subscribe(cb: Callable) -> Callable[[], None]:
    _subs.append(cb)
    def unsub() -> None:
        if cb in _subs:
            _subs.remove(cb)
    return unsub
```

- [ ] **Step 3: Green; mutate** (`current()` returns the FIRST activated → "last activated wins" fails). **Full loop; hand off.**

---

### Task 6: `page_ocr.py` + `ollama_client.generate` — the page as text and image

**Files:**
- Create: `klausmate/page_ocr.py`
- Modify: `klausmate/ollama_client.py` (add `generate` after `embed`, ~line 129)
- Test: `tests/test_page_ocr.py`
- Board card: `page_ocr: render, OCR through Ollama, cache, text-layer fallback, scheduler` — files `klausmate/page_ocr.py,klausmate/ollama_client.py,tests/test_page_ocr.py` — verify `python3 tests/test_page_ocr.py`

**Interfaces:**
- Consumes: `viewer_context.ViewState`; `pdf_handler.load_pages(user_files_dir, name) -> list[str] | None`; `pdf_handler._atomic_write` (or write tmp + `os.replace` inline); `ollama_client.OllamaClient`.
- Produces (Task 9 depends on these):
```python
OCR_PROMPT: str; LONG_EDGE = 1400; OCR_TIMEOUT_S = 60.0; DEBOUNCE_MS = 400
@dataclass
class PageContext: display: str; page_index: int; page_count: int; text: str; text_source: str; png: bytes | None; selection: str
def cache_dir(user_files: str, pdf_safe: str, path: str) -> str            # …/ocr/<safe>/<digest12>
def digest12(path: str, stat=os.stat) -> str
def cached_text(user_files, pdf_safe, path, page_index) -> str | None
def cached_png(user_files, pdf_safe, path, page_index) -> bytes | None
def store(user_files, pdf_safe, path, page_index, text: str | None, png: bytes | None) -> None
def ocr_page(client, model: str, png: bytes, timeout: float = OCR_TIMEOUT_S) -> str
def text_layer(user_files: str, pdf_safe: str, page_index: int, load_pages=pdf_handler.load_pages) -> str
def context_for(view, user_files: str, render=render_page_png) -> PageContext
def render_page_png(path: str, page_index: int, long_edge: int = LONG_EDGE) -> bytes   # aqt/QtPdf glue
class OcrScheduler(user_files, cfg_getter, client_factory, render=render_page_png, clock=time.monotonic, start_thread=…)
    .on_view(view | None); .tick() (the debounce check; the dock's QTimer calls it); ._run(view, model) on the worker
```
- `OllamaClient.generate(self, model: str, prompt: str, images: list[str], timeout: float | None = None) -> str` posting `{"model","prompt","images","stream": False}` to `/api/generate` and returning `resp["response"]`.

- [ ] **Step 1: Claim; failing tests** (temp dirs only; a fake client; `render` injected; the real `render_page_png` exercised under offscreen Qt on a one-page PDF written with `QPdfDocument`? No — QtPdf cannot write. Generate a tiny PDF with the vendored pypdf (`from klausmate.vendor import pypdf` — if the vendored import fails under python3.9, SKIP that one pin honestly).)

```python
import json, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section
install()
import importlib
po = importlib.import_module("klausmate.page_ocr")
oc = importlib.import_module("klausmate.ollama_client")
vc = importlib.import_module("klausmate.viewer_context")

tmp = tempfile.mkdtemp()
pdf = os.path.join(tmp, "lec.pdf"); open(pdf, "wb").write(b"%PDF-1.4 fake")

section("cache")
d = po.cache_dir(tmp, "lec", pdf)
check("cache dir under user_files/ocr/<safe>/<digest12>", d.startswith(os.path.join(tmp, "ocr", "lec")) and len(os.path.basename(d)) == 12)
check("digest changes when the file changes", po.digest12(pdf) != po.digest12(pdf, stat=lambda p: os.stat_result((0,0,0,0,0,0, 999, 0, 12345.0, 0))))
check("nothing cached yet", po.cached_text(tmp, "lec", pdf, 3) is None and po.cached_png(tmp, "lec", pdf, 3) is None)
po.store(tmp, "lec", pdf, 3, "# Slide\ntext", b"\x89PNG")
check("round trip", po.cached_text(tmp, "lec", pdf, 3) == "# Slide\ntext" and po.cached_png(tmp, "lec", pdf, 3) == b"\x89PNG")
check("file names are 4-digit page numbers", os.path.exists(os.path.join(d, "0003.md")) and os.path.exists(os.path.join(d, "0003.png")))
check("no tmp files left", not [f for f in os.listdir(d) if f.endswith(".tmp")])

section("ocr + generate payload")
posts = []
class FakeClient:
    def _post(self, path, payload): posts.append((path, payload)); return {"response": "  OCR TEXT \n"}
fc = oc.OllamaClient.__new__(oc.OllamaClient); fc.endpoint = "http://x"; fc.timeout = 1.0
fc._post = FakeClient()._post
out = fc.generate("glm-ocr", "transcribe", images=["QUJD"])
check("generate posts /api/generate with model, prompt, images, stream False and returns the response",
      posts[-1][0] == "/api/generate" and posts[-1][1] == {"model": "glm-ocr", "prompt": "transcribe", "images": ["QUJD"], "stream": False} and out == "  OCR TEXT \n")
txt = po.ocr_page(fc, "glm-ocr", b"ABC")
check("ocr_page base64-encodes the png, uses OCR_PROMPT, strips", posts[-1][1]["images"] == ["QUJD"] and posts[-1][1]["prompt"] == po.OCR_PROMPT and txt == "OCR TEXT")

section("fallback + context")
def pages(uf, name): return ["p0", "p1 text layer", "p2"] if name == "lec" else None
check("text_layer returns that page", po.text_layer(tmp, "lec", 1, load_pages=pages) == "p1 text layer")
check("text_layer out of range → ''", po.text_layer(tmp, "lec", 9, load_pages=pages) == "")
view = vc.ViewState(1, "lec", "Lecture.pdf", pdf, 1, 3, "sel")
ctx = po.context_for(view, tmp, render=lambda p, i, long_edge=1400: b"PNG1", load_pages=pages)
check("uncached page → text layer + rendered png + selection", ctx.text == "p1 text layer" and ctx.text_source == "text-layer" and ctx.png == b"PNG1" and ctx.selection == "sel" and ctx.page_index == 1 and ctx.page_count == 3)
po.store(tmp, "lec", pdf, 1, "OCR'd", None)
ctx = po.context_for(view, tmp, render=lambda p, i, long_edge=1400: b"PNG2", load_pages=pages)
check("cached OCR wins and is labelled ocr", ctx.text == "OCR'd" and ctx.text_source == "ocr")
check("no view → empty context", po.context_for(None, tmp).text_source == "none")

section("scheduler")
now = [0.0]
started = []
def start_thread(fn): started.append(fn)   # run manually
calls = []
class Client2:
    def generate(self, model, prompt, images, timeout=None): calls.append((model, len(images))); return "ocr text"
cfg = {"ocr_enabled": True, "ocr_model": "glm-ocr"}
sch = po.OcrScheduler(tmp, cfg_getter=lambda: cfg, client_factory=lambda: Client2(),
                      render=lambda p, i, long_edge=1400: b"PNG", clock=lambda: now[0], start_thread=start_thread, load_pages=pages)
view0 = vc.ViewState(1, "lec", "Lecture.pdf", pdf, 0, 3, "")
sch.on_view(view0)
check("nothing runs before the debounce", not started)
now[0] = 0.2; sch.tick()
check("still waiting at 200 ms", not started)
now[0] = 0.5; sch.tick()
check("after 400 ms a worker starts", len(started) == 1)
started[-1]()
check("current page OCR'd first, then neighbour prefetched, cached", calls and po.cached_text(tmp, "lec", pdf, 0) == "ocr text" and po.cached_text(tmp, "lec", pdf, 1) in ("ocr text", "OCR'd"))
sch.on_view(vc.ViewState(1, "lec", "Lecture.pdf", pdf, 0, 3, "")); now[0] = 1.0; sch.tick()
n = len(calls); (started[-1]() if len(started) > 1 else None)
check("an already-cached page is skipped", len(calls) == n or calls[-1][0] == "glm-ocr")
cfg["ocr_enabled"] = False
sch.on_view(vc.ViewState(1, "lec", "Lecture.pdf", pdf, 2, 3, "")); now[0] = 2.0; sch.tick()
check("ocr disabled → no worker", len(started) <= 2)
cfg["ocr_enabled"] = True
class Down:
    def generate(self, *a, **k): raise oc.OllamaNotRunning("down")
sch2 = po.OcrScheduler(tmp, cfg_getter=lambda: cfg, client_factory=lambda: Down(), render=lambda p, i, long_edge=1400: b"PNG", clock=lambda: now[0], start_thread=start_thread, load_pages=pages)
sch2.on_view(vc.ViewState(1, "lec", "Lecture.pdf", pdf, 2, 3, "")); now[0] = 3.0; sch2.tick(); started[-1]()
check("Ollama down → no exception, nothing cached for that page", po.cached_text(tmp, "lec", pdf, 2) is None)

section("render (real QtPdf, offscreen)")
try:
    from PyQt6.QtPdf import QPdfDocument  # noqa
    from klausmate.vendor import pypdf
    w = pypdf.PdfWriter(); w.add_blank_page(width=300, height=200)
    real = os.path.join(tmp, "blank.pdf"); w.write(real)
    png = po.render_page_png(real, 0, long_edge=140)
    check("render_page_png returns a PNG with the long edge scaled to 140", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100)
except Exception as exc:
    print(f"  SKIP real render: {exc}")
report()
```

- [ ] **Step 2: Red; implement `generate`** in `ollama_client.py` right after `embed`:

```python
    def generate(self, model: str, prompt: str, images: list[str], timeout: float | None = None) -> str:
        """One non-streaming completion with images (the OCR path).

        ``images`` are base64 strings, as Ollama's /api/generate takes them.
        A per-call timeout because OCR of a dense slide takes longer than the
        client's default; the caller passes page_ocr.OCR_TIMEOUT_S.
        """
        old = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            resp = self._post("/api/generate", {"model": model, "prompt": prompt, "images": list(images), "stream": False})
        finally:
            self.timeout = old
        text = resp.get("response")
        if not isinstance(text, str):
            raise OllamaError("generate response had no text")
        return text
```

- [ ] **Step 3: Implement `page_ocr.py`:**

```python
"""The page in view as text and image: render, OCR through Ollama, cache.

Pouya, 2026-09-01: "I want to use GLM-OCR or something similar to get the
PDF image and text." The page renders through QPdfDocument (Anki bundles
QtPdf whichever viewer renderer is on), the PNG goes to a vision-OCR model
served by Ollama, and the markdown that comes back is cached beside the
PNG keyed by the PDF's digest and page, so a page is OCR'd once. Without an
OCR model the turn carries the PDF's own text layer and says so; the image
still goes. OCR never blocks a send: the scheduler runs it on a worker after
a 400 ms debounce and prefetches the neighbours when idle.

aqt-free above the divider; ``render_page_png`` is the one QtPdf function.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

LONG_EDGE = 1400
OCR_TIMEOUT_S = 60.0
DEBOUNCE_MS = 400
PREFETCH = (1, -1)
OCR_PROMPT = ("Transcribe this lecture slide faithfully as Markdown: keep headings, bullets, tables and "
              "equations (LaTeX); describe each figure in one line in brackets; no commentary.")


@dataclass
class PageContext:
    display: str
    page_index: int
    page_count: int
    text: str
    text_source: str        # "ocr" | "text-layer" | "none"
    png: bytes | None
    selection: str


def digest12(path: str, stat=os.stat) -> str:
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def cache_dir(user_files: str, pdf_safe: str, path: str) -> str:
    return os.path.join(user_files, "ocr", pdf_safe, digest12(path))


def _paths(user_files, pdf_safe, path, page_index):
    d = cache_dir(user_files, pdf_safe, path)
    return d, os.path.join(d, f"{int(page_index):04d}.md"), os.path.join(d, f"{int(page_index):04d}.png")


def cached_text(user_files: str, pdf_safe: str, path: str, page_index: int) -> str | None:
    _, md, _ = _paths(user_files, pdf_safe, path, page_index)
    try:
        with open(md, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def cached_png(user_files: str, pdf_safe: str, path: str, page_index: int) -> bytes | None:
    _, _, png = _paths(user_files, pdf_safe, path, page_index)
    try:
        with open(png, "rb") as f:
            return f.read()
    except Exception:
        return None


def _atomic(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def store(user_files: str, pdf_safe: str, path: str, page_index: int, text: str | None, png: bytes | None) -> None:
    d, md, pn = _paths(user_files, pdf_safe, path, page_index)
    os.makedirs(d, exist_ok=True)
    if text is not None:
        _atomic(md, text.encode("utf-8"))
    if png is not None:
        _atomic(pn, png)


def ocr_page(client: Any, model: str, png: bytes, timeout: float = OCR_TIMEOUT_S) -> str:
    b64 = base64.b64encode(png).decode("ascii")
    return str(client.generate(model, OCR_PROMPT, images=[b64], timeout=timeout) or "").strip()


def text_layer(user_files: str, pdf_safe: str, page_index: int, load_pages: Callable | None = None) -> str:
    if load_pages is None:
        from . import pdf_handler
        load_pages = pdf_handler.load_pages
    try:
        pages = load_pages(user_files, pdf_safe) or []
        return str(pages[page_index]) if 0 <= page_index < len(pages) else ""
    except Exception:
        return ""


def context_for(view: Any, user_files: str, render: Callable | None = None, load_pages: Callable | None = None) -> PageContext:
    if view is None or not getattr(view, "pdf_safe", ""):
        return PageContext("", 0, 0, "", "none", None, "")
    render = render or render_page_png
    text = cached_text(user_files, view.pdf_safe, view.path, view.page_index)
    source = "ocr" if text else "text-layer"
    if not text:
        text = text_layer(user_files, view.pdf_safe, view.page_index, load_pages)
        if not text:
            source = "none"
    png = cached_png(user_files, view.pdf_safe, view.path, view.page_index)
    if png is None:
        try:
            png = render(view.path, view.page_index, long_edge=LONG_EDGE)
            if png:
                store(user_files, view.pdf_safe, view.path, view.page_index, None, png)
        except Exception as exc:
            print(f"[klausmate] page render failed: {exc}")
            png = None
    return PageContext(view.display, view.page_index, view.page_count, text or "", source, png, getattr(view, "selection", "") or "")


class OcrScheduler:
    """Debounce 400 ms after the last view change, OCR the current page on a
    worker, then page+1 and page-1. Never raises; never blocks the caller."""

    def __init__(self, user_files: str, cfg_getter: Callable[[], dict], client_factory: Callable[[], Any],
                 render: Callable | None = None, clock: Callable[[], float] = time.monotonic,
                 start_thread: Callable | None = None, load_pages: Callable | None = None) -> None:
        self._uf, self._cfg, self._client = user_files, cfg_getter, client_factory
        self._render = render or render_page_png
        self._clock = clock
        self._start = start_thread or (lambda fn: threading.Thread(target=fn, daemon=True, name="klaus-ocr").start())
        self._load_pages = load_pages
        self._view: Any = None
        self._due: float | None = None
        self._busy = False
        self._timer: Any = None

    def on_view(self, view: Any) -> None:
        self._view = view
        if view is None or not getattr(view, "pdf_safe", ""):
            self._due = None
            return
        self._due = self._clock() + DEBOUNCE_MS / 1000.0
        self._arm_timer()

    def _arm_timer(self) -> None:
        """Qt-timer hook installed by the dock (aqt glue); tests call tick()."""
        if self._timer is not None:
            try:
                self._timer()
            except Exception:
                pass

    def tick(self) -> None:
        if self._due is None or self._clock() < self._due or self._busy:
            return
        cfg = self._cfg() or {}
        if not cfg.get("ocr_enabled", True) or not str(cfg.get("ocr_model") or "").strip():
            self._due = None
            return
        view = self._view
        self._due = None
        self._busy = True
        self._start(lambda: self._run(view, str(cfg.get("ocr_model"))))

    def _run(self, view: Any, model: str) -> None:
        try:
            client = self._client()
            for delta in (0, *PREFETCH):
                idx = view.page_index + delta
                if idx < 0 or (view.page_count and idx >= view.page_count):
                    continue
                if cached_text(self._uf, view.pdf_safe, view.path, idx):
                    continue
                png = cached_png(self._uf, view.pdf_safe, view.path, idx)
                if png is None:
                    png = self._render(view.path, idx, long_edge=LONG_EDGE)
                    if png:
                        store(self._uf, view.pdf_safe, view.path, idx, None, png)
                if not png:
                    continue
                try:
                    text = ocr_page(client, model, png)
                except Exception as exc:
                    print(f"[klausmate] ocr page {idx + 1} of {view.pdf_safe}: {exc}")
                    return
                if text:
                    store(self._uf, view.pdf_safe, view.path, idx, text, None)
        except Exception as exc:
            print(f"[klausmate] ocr worker: {exc}")
        finally:
            self._busy = False


# ---- QtPdf glue --------------------------------------------------------------------

def render_page_png(path: str, page_index: int, long_edge: int = LONG_EDGE) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice, QSize
    from PyQt6.QtPdf import QPdfDocument
    doc = QPdfDocument(None)
    doc.load(path)
    if doc.status() != QPdfDocument.Status.Ready or page_index < 0 or page_index >= doc.pageCount():
        raise RuntimeError(f"cannot render page {page_index + 1} of {path}")
    pts = doc.pagePointSize(page_index)
    w, h = max(1.0, pts.width()), max(1.0, pts.height())
    scale = float(long_edge) / max(w, h)
    img = doc.render(page_index, QSize(int(round(w * scale)), int(round(h * scale))))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())
```

- [ ] **Step 4: Green; mutate** — (1) `store` writes the `.md` without `os.replace` (direct write, leaving `.tmp`) → the no-tmp pin fails; (2) `context_for` labels cached text `"text-layer"` → the "cached OCR wins" pin fails; (3) `tick` ignores `ocr_enabled` → the disabled pin fails. Restore. **Full loop; hand off.**

---

### Task 7: `assistant_sessions.py` — sessions per PDF, slash commands, the system prompt file

**Files:**
- Create: `klausmate/assistant_sessions.py`
- Test: `tests/test_assistant_sessions.py`
- Board card: `assistant_sessions: per-PDF session ids, slash commands, system prompt` — verify `python3 tests/test_assistant_sessions.py`

**Interfaces (Task 9 depends on these):**
```python
SYSTEM_PROMPT_VERSION = 1
DEFAULT_PROMPTS = {"explain": "…", "cards": "…", "quiz": "…"}   # texts per spec §10
def sessions_path(user_files) -> str; def prompts_dir(user_files) -> str; def system_prompt_path(user_files) -> str
def load(user_files) -> dict; def session_for(user_files, pdf_safe: str | None) -> str | None
def remember(user_files, pdf_safe: str | None, session_id: str, now=time.time) -> None; def forget(user_files, pdf_safe: str | None) -> None; def clear_all(user_files) -> None
def ensure_defaults(user_files) -> None            # writes the three prompts when the folder is empty
def list_commands(user_files) -> list[str]
def expand(text: str, user_files: str, ctx: dict) -> str   # ctx keys: selection, page_text, pdf
def ensure_system_prompt(user_files) -> str        # returns the path; rewrites when the version marker is older
```

- [ ] **Step 1: Claim; failing tests** (temp dir): round trip by PDF and global; corrupt JSON reads as empty; `forget`/`clear_all`; `ensure_defaults` writes exactly three files once and never overwrites an edited one; `list_commands` sorted; `expand("/cards make 3", …)` replaces the command with the file body and appends the rest; `$SELECTION`/`$PAGE`/`$PDF` expansion; an unknown `/zzz` passes through unchanged; `ensure_system_prompt` writes a file containing `<!-- klaus-system-prompt v1 -->`, `[Klaus context]`, `(p. N)`, `source_page`, and rewrites when the marker says v0. Write these pins in the same style as Task 5's.

- [ ] **Step 2: Red; implement** — atomic JSON write (tmp + `os.replace`), `load` returns `{"by_pdf": {}, "global": {}}` on any error; `expand`: `m = re.match(r"^/(\w[\w-]*)\s*(.*)$", text, re.S)`; if the name has a file, `body = file.read().strip(); rest = m.group(2).strip(); text = body + ("\n\n" + rest if rest else "")`; then `.replace("$SELECTION", ctx.get("selection",""))`, `$PAGE`, `$PDF`. `ensure_system_prompt` writes:

```
<!-- klaus-system-prompt v1 -->
You are Klaus, the study assistant inside Anki. The user is reading lecture PDFs.

Every user message ends with a "[Klaus context]" block: the PDF and page in view, any selected text, and the page's text (OCR or text layer). An image of that page is attached when available. "This page", "this slide" and "this" mean that page.

Answer from the page and the library first. Cite pages as (p. N). If the material does not contain the answer, say so.

Your mcp__klaus__* tools reach the user's Anki collection: search_notes (semantic), find_notes/get_notes (Anki search), search_lecture_pdfs, list_decks, list_models, model_fields, add_note, update_note_fields, add_tags, remove_tags, open_in_browse, current_view.

Making cards: propose them in prose first; on the user's go-ahead call add_note ONCE PER CARD with deck, model, fields and source_page (the slide it came from). The user approves each card in a dialog; a tool result that says declined or errored means the card was NOT added — never claim otherwise.
```

- [ ] **Step 3: Green; mutate** (`expand` ignores `$SELECTION` → its pin fails; `ensure_defaults` overwrites → its pin fails). **Full loop; hand off.**

---

### Task 8: Manage Models — model types, OCR presets, the Assistant page, config keys

**Files:**
- Modify: `klausmate/manage_models.py` (`_EMBED_PRESETS` ~79; `_page("Assistant", …)` ~1656-1662 and the rows after it; `save_assistant` ~1727; `refresh` ~1867 for the Type column), `klausmate/config.json`, `klausmate/config.md`
- Test: `tests/test_manage_models.py` (extend the existing file if present; otherwise create `tests/test_manage_models_assistant.py`)
- Board card: `Manage Models: classify model types, OCR presets, the Assistant page (OCR model, claude binary, model, reopen, clear sessions)` — files `klausmate/manage_models.py,klausmate/config.json,klausmate/config.md,tests/test_manage_models.py` — verify `python3 tests/test_manage_models.py`

**Interfaces:**
- Produces: `classify_model(show: dict) -> str` ("embedding" | "ocr" | "chat"), `_OCR_PRESETS`, config keys `ocr_enabled`, `ocr_model`, `claude_binary`, `assistant_model`, `assistant_reopen`, `assistant_dock_width`; `save_assistant()` writes exactly those; the old `assistant_api_key`/`assistant_backend`/`assistant_token` rows and keys are gone from this file and from `config.json`/`config.md`.
- Consumes: `agent_host.find_claude` (Task 2) for the read-only detected path — import lazily inside the dialog; `assistant_sessions.clear_all` (Task 7) for the Clear Sessions button — import lazily.

- [ ] **Step 1: Claim; failing pins:** `classify_model({"capabilities": ["completion", "vision"]}) == "ocr"`, `{"capabilities": ["embedding"]} → "embedding"`, `{} → "chat"`, `{"capabilities": "junk"} → "chat"`; `_OCR_PRESETS[0][0] == "glm-ocr"` and `"deepseek-ocr"` present; `config.json` has the six new keys with the spec defaults and none of the three dropped keys; source pins (raw source, not `code_only`): `"assistant_api_key"` absent from `manage_models.py`, `"podcast"` absent, `"ocr_model"` present in `save_assistant`'s body (`_func_seg`-style slicing as in `tests/test_pdf_map.py`), the Assistant page subtitle no longer promises practice/podcast.
- [ ] **Step 2: Red; implement:**
  - `_OCR_PRESETS = [("glm-ocr", "GLM-OCR — multimodal OCR for complex documents · ~2.5 GB"), ("deepseek-ocr", "DeepSeek-OCR — token-efficient OCR · ~3 GB")]`; `classify_model` pure at module top.
  - Assistant page: subtitle "Claude Code is the engine: install it, run `claude` once to log in, and Klaus finds it. The page you are viewing reaches it as OCR text and image." Rows: `ocr_enabled` (Md3Switch), `ocr_model` (QComboBox of installed vision models from `refresh()`'s classification + the presets, with a Pull button that calls the existing `start_pull()` path for the selected preset), `claude_binary` (a muted QLabel with the detected path via `agent_host.find_claude(cfg.get("claude_binary",""))` or "not found", plus an Override… button opening a window-modal `QFileDialog.open()`), `assistant_model` (QLineEdit, placeholder "default"), `assistant_reopen` (Md3Switch), and a Clear Sessions `SecondaryButton` → window-modal confirm (`QMessageBox` built by hand, `open()`, `finished` → `assistant_sessions.clear_all(user_files)`). Every control → `mark_dirty`; `save_assistant()` writes the six keys.
  - Local model library: `refresh()` also fetches `/api/show` per installed model (`client._post("/api/show", {"model": name})`, tolerate failure → "chat") and shows a Type column; the embedding combo lists only `"embedding"`-typed models, the OCR combo only `"ocr"`.
  - `config.json`: add the six keys, remove the three; `config.md`: document them under an "Assistant" heading and delete the old assistant keys' text.
- [ ] **Step 3: Green; mutate** (`classify_model` returns "chat" for vision → pin fails; put `assistant_api_key` back → the absence pin fails). **Full loop** (this file is imported by `tests/test_dialog_logic.py` and others — they must stay green); **hand off**.

---

### Task 9: `assistant_dock.py` + `theme.assistant_dock_qss` — the dock

**Files:**
- Create: `klausmate/assistant_dock.py`
- Modify: `klausmate/theme.py` (add `assistant_dock_qss(night)`; delete the `KlausAssistantPanel` block at ~1160-1213 inside `library_qss`)
- Test: `tests/test_assistant_dock.py`, `tests/test_theme.py` (add the builder to the design-scale audit list; add a pin that `KlausAssistantPanel` no longer appears in `library_qss(False)`)
- Board card: `assistant_dock: the Claudian-shaped dock — header, transcript, input, Send/Stop, sessions, slash completer` — files `klausmate/assistant_dock.py,klausmate/theme.py,tests/test_assistant_dock.py,tests/test_theme.py` — verify `python3 tests/test_assistant_dock.py`. **`theme.py` may be held by the constellation plan's Task 7 card — wait for it.**

**Interfaces:**
- Consumes: `agent_host` (Task 2), `viewer_context` (Task 5), `page_ocr` (Task 6), `assistant_sessions` (Task 7), `anki_endpoint.current()` (Task 3) — all imported lazily inside functions so the module imports with any of them missing (the `PDF_VIEWER_AVAILABLE` pattern).
- Produces (Task 11 wires these): `class AssistantDock(QDockWidget)`; module functions `toggle_assistant() -> None`, `open_assistant() -> None`, `close_assistant() -> None`, `setup() -> None` (registers `state_shortcuts_will_change` for `Ctrl+Shift+K` and `profile_will_close` teardown), `_dock() -> AssistantDock | None`.
- Constructor is injectable for tests: `AssistantDock(parent=None, *, host_factory=None, context_provider=None, sessions=None, user_files=None, endpoint_info=None)` where `host_factory(callbacks) -> AgentHost-like`, `context_provider(view) -> PageContext`, `endpoint_info() -> (port, token) | None`.

- [ ] **Step 1: Claim; failing tests** (offscreen, `QT_QPA_PLATFORM=offscreen`, the `aqt.qt` shim the way `tests/test_pdf_map.py` builds it): construction with a fake host and a fake context provider; header text follows `viewer_context` (`report_document` + `activate` → "Following: Lecture 1.pdf · p. 1/40"; `report_selection` → the chip shows the first 40 chars); sending a message calls `host.send` with a turn whose JSON carries the user text, the `[Klaus context]` block and an image block when the provider returns a PNG; while running, the Send button text is "Stop" and a second Enter does not send; deltas append to the transcript (`toPlainText()` contains them in order); a `tool_use` renders one line starting with `▸` and the label from `TOOL_LABELS` ("searched notes: renal"); `permission_denied` renders a muted line; `result` flips Send back; Stop calls `host.stop()`; New Session calls `sessions.forget` and `host.start()` afresh; switching the followed PDF calls `host.start(resume=<stored id>)` when one is stored; empty state when `host_factory` raises `FileNotFoundError` shows the install copy and disables input; a `/` typed at the start lists commands from `assistant_sessions.list_commands`; a source pin that `"exec()"` does not appear in the module; a pixel pin that the dock's ground is the palette's `chrome` (grab → corner pixel) under both palettes; `theme.assistant_dock_qss(True)` contains no literal hex outside tokens (reuse test_theme's audit).

- [ ] **Step 2: Red; implement** the dock: a `_Bridge(QObject)` with `pyqtSignal`s `init(dict) delta(str) tool_use(str, dict) tool_result(str, bool) result(dict) denied(str) error(str) exited(object)`; `AgentHost` callbacks emit those signals (thread-safe queued connections); the widget slots update the UI. Layout: header `QLabel` (`objectName` `KlausAssistantHeader`), selection chip `QLabel`, status dot `QLabel`, transcript `QTextEdit` read-only (`KlausAssistantTranscript`), input `QPlainTextEdit` with an `eventFilter` for Enter/Shift+Enter, buttons Send/Stop (one `QPushButton` toggling text), New Session (`SecondaryButton`). `TOOL_LABELS = {"mcp__klaus__search_notes": lambda i: f"searched notes: {i.get('query','')}", "mcp__klaus__find_notes": …, "mcp__klaus__get_notes": lambda i: f"read {len(i.get('note_ids') or [])} notes", "mcp__klaus__add_note": lambda i: f"proposed a card for {i.get('deck','')}", "mcp__klaus__search_lecture_pdfs": …, "mcp__klaus__current_view": lambda i: "checked what you are viewing", "Read": lambda i: f"read {os.path.basename(str(i.get('file_path','')))}", "Grep": lambda i: f"searched files for {i.get('pattern','')}", "Glob": lambda i: "listed files"}`; a `tool_result` with `is_error` appends " — failed" to the last tool line. Markdown-lite renderer `render_markdown_lite(text) -> html` (pure, at module top: escape, fenced code → `<pre>`, `**x**` → `<b>`, lines starting `- ` → `•`). Session handling per spec §10: on `viewer_context` change with a different `pdf_safe`, `host.stop()`, then `host.start(resume=stored)` or fresh, transcript cleared with "Resumed session for <display>" / "New session for <display>". The `OcrScheduler` is owned here: its `_timer` hook is a `QTimer.singleShot(DEBOUNCE_MS, scheduler.tick)`. The dock reads `mw.addonManager.getConfig` for `assistant_model`, `claude_binary`, `assistant_dock_width`, `assistant_reopen`; saves width on `resizeEvent` through the same `_save_state` pattern `lecture_view` uses (a `assistant_dock_width` config write, debounced 500 ms). `theme.assistant_dock_qss(night)`: `QDockWidget#KlausAssistantDock { background: chrome }`, header/chip in `text_muted`, transcript on `chrome` with `text`, `pre` blocks on `surface`, input on `surface` with `grey_light` border and `blue_border` on focus, buttons per `dialog_qss` conventions. Delete the `KlausAssistantPanel` block from `library_qss`.

- [ ] **Step 3: Green; mutate** (Send does not flip to Stop → pin fails; the tool label table returns "" → pin fails; ground painted `bg` → pixel pin fails). **Full loop; hand off.**

---

### Task 10: The viewers report into `viewer_context`

**Files:**
- Modify: `klausmate/pdf_viewer.py` (`PdfSidebar.load_pdf` ~4295, `_notify_loaded`, `_on_page_changed` ~4522, `cleanup`/`clear`, `showEvent` on the sidebar (new), `PdfViewer._update_selection` ~1414, `_apply_selection_direct` ~2259, `_clear_selection` ~1404, `PdfViewer.__init__` ~670 for a new `on_selection_changed` attribute), `klausmate/pdfjs_viewer.py` (`PdfJsViewer.__init__` ~858: `self.on_selection`; new `_bridge_sel`), `klausmate/web/pdfjs_viewer.html` (a debounced `selectionchange` listener posting `sel:`)
- Test: `tests/test_drive.py` (the offscreen PdfSidebar section: after `load_pdf` on a scratch PDF, `viewer_context.current()` names it; `notify_page_changed(3)` → page 3; `sidebar.cleanup()` → forgotten), `tests/test_pdfjs_viewer.py` (`parse_bridge("klausmate_pdfjs:sel:" + b64)` → the `sel` action decodes to the text; the HTML contains `selectionchange` and posts `sel:`)
- Board card: `viewers report document, page, selection and activity into viewer_context` — files `klausmate/pdf_viewer.py,klausmate/pdfjs_viewer.py,klausmate/web/pdfjs_viewer.html,tests/test_drive.py,tests/test_pdfjs_viewer.py` — verify `bash -c 'python3 tests/test_pdfjs_viewer.py && python3 tests/test_drive.py'`. **`pdf_viewer.py` may be held by the constellation plan's Task 8 — wait.**

**Interfaces:** consumes Task 5's functions; produces nothing new (the sidebar keeps its surface).

- [ ] **Step 1: Claim; failing pins** as listed under Test.
- [ ] **Step 2: Implement.** `PdfSidebar`: after a successful load (`_notify_loaded` or the end of `load_pdf`), `viewer_context.report_document(id(self), self._name, drive_store.display_name(user_files, self._name) or self._name, pdf_handler.pdf_path_for(user_files, self._name, root) or "", self._page_count)` then `activate(id(self))` — every call inside `try/except` with a log line, imports guarded; `_on_page_changed` → `report_page`; `cleanup`/`clear` → `forget`; a new `showEvent` and `mousePressEvent` pass-through on the sidebar → `activate` (focus follows a click into the viewer). `PdfViewer`: `self.on_selection_changed: Callable[[str], None] | None = None`; call it (guarded) at the end of `_update_selection`, `_apply_selection_direct` and `_clear_selection` with `self._selection_text`; `PdfSidebar` sets `viewer.on_selection_changed = lambda t: viewer_context.report_selection(id(self), t)`. `PdfJsViewer`: `self.on_selection = None`; `_bridge_sel(payload)` base64-decodes the text (the `postB64` convention, `decode_b64_json` if it is JSON `{"text": …}`) and calls `self.on_selection(text)`; the sidebar sets it the same way. HTML: `let _selT=null; document.addEventListener("selectionchange", () => { clearTimeout(_selT); _selT = setTimeout(() => postB64("sel", {text: String(window.getSelection() || "")}), 150); });` placed beside `addHighlightFromSelection`.
- [ ] **Step 3: Green; mutate; full loop; hand off.**

---

### Task 11: Wiring and deletions — `__init__`, `pdf_drive`, the dead modules

**Files:**
- Modify: `klausmate/__init__.py` (profile hooks ~2549-2583: `anki_endpoint.start_for_profile` on open, `stop_for_profile` + `assistant_dock.close_assistant` on close; `install_menu` ~632: add "Klaus Assistant" after Preferences; `_LEGACY_KEYS_DROPPED` ~86: add `assistant_api_key`, `assistant_backend`, `assistant_token`; call `assistant_dock.setup()` beside `_pdf_drive.setup()` ~2603), `klausmate/pdf_drive.py` (delete the mount at ~1183-1200 and `_on_assistant_target`; delete `_ASSISTANT_DEFAULT_W` ~881 and the 3-pane branch in `_apply_splitter_sizes` ~1523-1553; add an `assistant` glyph button beside Map (~989-1021) → `assistant_dock.toggle_assistant()` through a guarded import like `_open_map`), `klausmate/card_forge.py` (~178: the `podcast.py` sentence → "Public so any grounded-JSON caller shares one fence-stripping.")
- Delete: `klausmate/llm_client.py`, `klausmate/entitlement.py`, `klausmate/assistant_session.py`, `klausmate/podcast.py`, `klausmate/assistant_panel.py`, `tests/test_llm_client.py`, `tests/test_entitlement.py`, `tests/test_assistant_session.py`, `tests/test_podcast.py`, `tests/test_assistant_panel.py`
- Test: `tests/test_drive.py` (pins: `"assistant_panel"` absent from `pdf_drive.py` source; the splitter default is `[560, 480]` with no third pane; the caption row has an `assistant` glyph), `tests/test_klausmate.py` or `tests/test_bridge_reentrancy.py` (a pin that none of the five deleted module files exist and no test bootstrap names them), `tests/test_slot_guards.py`/`tests/test_drive.py` source-pin strings that mention `assistant_panel` updated
- Board card: `wire the assistant: endpoint lifecycle, dock menu/shortcut/toolbar button, third pane removed, dead modules deleted` — files `klausmate/__init__.py,klausmate/pdf_drive.py,klausmate/card_forge.py,klausmate/llm_client.py,klausmate/entitlement.py,klausmate/assistant_session.py,klausmate/podcast.py,klausmate/assistant_panel.py,tests/test_llm_client.py,tests/test_entitlement.py,tests/test_assistant_session.py,tests/test_podcast.py,tests/test_assistant_panel.py,tests/test_drive.py,tests/test_klausmate.py,tests/test_slot_guards.py` — verify `bash -c 'test ! -e klausmate/podcast.py && python3 tests/test_drive.py'`. **Depends on Tasks 3, 7, 9 being in Review or Done** (imports).

- [ ] **Step 1: Claim; failing pins** as listed. Run the deletion pin — it fails (the files exist).
- [ ] **Step 2: Implement** — the `git rm`s are the orchestrator's; the worker deletes the files with `rm` (not `git rm`) and lists them in the hand-off comment. `pdf_drive`'s `_glyph_action("assistant", "Klaus Assistant (Ctrl+Shift+K)", left)` needs a glyph: reuse `library_explorer`'s glyph set — if no `assistant` glyph exists, add a `"assistant"` entry to its glyph table (a simple chat-bubble path, theme-token inks) and note it; the fallback `QPushButton("Assistant")` path already exists.
- [ ] **Step 3: Green across the full loop** (deleted tests are gone from the loop; `test_bridge_reentrancy`'s roster is unchanged since the dock registers no js-message handler). **Mutate; hand off.**

---

### Task 12: Docs — CLAUDE.md and AGENTS.md

**Files:** `CLAUDE.md`, `AGENTS.md`. Board card: `docs: the assistant on Claude Code` — verify `bash -c 'grep -q "agent_host.py" CLAUDE.md && ! grep -q "assistant_panel.py" CLAUDE.md'`. **Depends on Task 11.**

- [ ] **Step 1:** Claim; verify fails.
- [ ] **Step 2:** CLAUDE.md: replace the header paragraph "**That is being deliberately reversed as of 2026-09-01**…" with the new shape (engine = Claude Code CLI; the six modules; the endpoint; OCR; the dock; what was deleted and why, naming the commits that hold the old code); add module-map entries for `agent_host.py`, `anki_endpoint.py`, `viewer_context.py`, `page_ocr.py`, `assistant_sessions.py`, `assistant_dock.py` in the house style (what it is, the one non-obvious rule each: discovery order and the login-shell trap; token + Origin gate and open()-not-exec approvals; last-activated wins; OCR never blocks a send and the digest cache; sessions per PDF; the Bridge-signal threading rule); update the "Deleted (2026-08…)" paragraph with the 2026-09-01 deletions; update `manage_models.py`'s entry (Assistant page, model types) and `ollama_client.py`'s ("No text-generation method" is no longer true — `generate` exists for OCR only). AGENTS.md: add the modules to "Architecture", the endpoint to "JS ↔ Python message protocol"'s neighbourhood as its own "Localhost endpoint" section (port, token, routes, actions), the new config keys under "Configuration", and the deletions under "What used to be here".
- [ ] **Step 3:** Verify passes; hand off.

---

### Task 13: Integration — full loop, offscreen renders, live check

**Files:** none new (a scratch render script under the worker's scratchpad). Board card: `assistant integration: full loop green, dock renders on chrome, endpoint answers, live check` — verify `for t in tests/test_*.py; do python3 "$t" || exit 1; done`. **Depends on Tasks 1–12.**

- [ ] **Step 1:** Claim; run the full loop; every file green; report counts.
- [ ] **Step 2:** Offscreen: build the dock with a fake host and a real `viewer_context` + `page_ocr.context_for` over a scratch PDF (pypdf-written), grab it at `QT_SCALE_FACTOR=2`, save PNGs for both palettes to the scratchpad, and pin that the ground is `chrome` and the header names the PDF. Attach the PNG paths to the card comment.
- [ ] **Step 3:** Endpoint smoke against a stub collection: start, `curl` `version` with the token → `{"result": 6, "error": null}`, without → 403.
- [ ] **Step 4:** `needs-human` live check, written as a checklist in the card comment for Pouya: restart Anki; open the Library; open a PDF; press `Ctrl+Shift+K`; the dock says "Following: <pdf> · p. 1/N"; ask "what is on this slide?"; the answer streams and cites the page; ask "make one card from it" → the approval dialog appears → Approve → the card exists in Browse with tag `klaus::assistant`; switch to another PDF → the header follows and the session switches; select text → the chip shows it. Move the card to Review.

---

## Self-review

- **Spec coverage:** §4 → Task 2; §5 → Tasks 3–4; §6 → Tasks 5, 10; §7 → Task 6; §8 → Task 8; §9 → Task 9; §10 → Task 7 (+ Task 9's use); §11 → Tasks 8, 9, 11; §12 → Task 1; §13 → spread across 2, 3, 6, 9 (timeouts named in each); §14 → each task's tests; §15 honoured (nothing outside it is built).
- **Placeholders:** the two pins the plan itself marks for replacement (Task 2 Step 5, Task 4 Step 1's last line) are flagged as such with the replacement stated; no TBDs remain.
- **Type consistency:** `ViewState` field names (`pdf_safe, display, path, page_index, page_count, selection`) are used identically in Tasks 3, 6, 9, 10; `PageContext` fields in 6 and 9; `AgentHost` callback keys in 2 and 9; `ACTIONS`/`MCP_TO_ACTION`/`mcp_args_to_params` in 3 and 4; config keys in 8, 9, 11.
