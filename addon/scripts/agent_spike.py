#!/usr/bin/env python3
"""Throwaway probe: drive the real `claude` once and record its stream.

Not a test. Records raw stdout lines to tests/fixtures/claude_stream/ so the
parser in klausmate/agent_host.py is pinned to what the binary actually
emits, not to memory. Needs a logged-in Claude Code.
"""
from __future__ import annotations  # system python3 is 3.9.6; `bytes | None` below needs this
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
    # This agent itself runs inside a nested Claude Code Desktop session
    # (CLAUDECODE=1, a messaging socket, etc.) and subprocess.Popen inherits
    # the parent's environment by default. Left alone, the spawned `claude`
    # detects that host session and behaves like another orchestrated
    # sub-agent (huge inherited tool/skill/plugin roster, permission
    # decisions possibly deferred to the host) instead of the plain
    # standalone process Klaus will actually spawn from inside Anki. Strip
    # the nesting markers so the recorded stream reflects that real target
    # environment — finding recorded in the README.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_")
           and k not in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT", "CLAUDE_AGENT_SDK_VERSION", "BAGGAGE")}
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
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
