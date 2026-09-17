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


def _agent_host():
    """klausmate.agent_host loaded STANDALONE (by path, not through the
    package, whose __init__ imports aqt). It has no addon imports of its
    own, so this works — and it is what lets this script probe the exact
    argv production spawns rather than a hand-copied approximation."""
    import importlib.util
    path = os.path.join(ROOT, "klausmate", "agent_host.py")
    spec = importlib.util.spec_from_file_location("_spike_agent_host", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AH = _agent_host()


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


def _system_prompt(cwd: str) -> str:
    path = os.path.join(cwd, "system_prompt.md")
    if not os.path.isfile(path):
        with open(path, "w") as f:
            f.write("You are Klaus, a study assistant. Answer briefly.\n")
    return path


def production_cmd(port: int, cwd: str, resume: str = "") -> list[str]:
    """EXACTLY what AgentHost.start() builds — same function, no copy.

    The 2026-09-01 spike hand-copied a nearly-but-not-identical argv (no
    --append-system-prompt-file, no --model, no ToolSearch), so nothing
    had ever spawned the binary with the real command line; a CLI rename
    of a flag only production uses would have taken the feature down
    silently (final review M17). smoke_argv() below is the zero-cost
    check that keeps it that way.
    """
    binary = shutil.which("claude") or "/opt/homebrew/bin/claude"
    return AH.command_line(binary, port=port, library_root=cwd,
                           system_prompt_path=_system_prompt(cwd),
                           session_id=None if resume else str(uuid.uuid4()),
                           resume=resume or None)


def production_env() -> dict:
    """AgentHost's own environment policy — which is also what strips the
    nesting markers this script used to strip by hand. A spike run from
    inside a Claude Code session (CLAUDECODE=1, a messaging socket, …)
    would otherwise have the child detect that host session and behave
    like another orchestrated sub-agent, instead of the plain standalone
    process Klaus spawns from inside Anki. The endpoint token rides in
    KLAUS_TOKEN here too, never argv."""
    binary = shutil.which("claude") or "/opt/homebrew/bin/claude"
    return AH.child_env(os.environ, binary, TOKEN)


def smoke_argv() -> bool:
    """Zero-API-cost check that the real binary PARSES production's argv.

    Spawns with empty stdin: the CLI answers "Input must be provided",
    never "unknown option", unless a flag has been renamed out from
    under us. No turn is sent, so no tokens are billed.
    """
    cwd = tempfile.mkdtemp(prefix="klaus-argv-smoke-")
    cmd = production_cmd(1, cwd)
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=production_env())
    out, err = proc.communicate(input="", timeout=60)
    blob = (out or "") + (err or "")
    bad = [w for w in ("unknown option", "unknown argument", "unknown command",
                       "too many arguments") if w in blob.lower()]
    ok = not bad
    print(f"  [argv smoke] {'OK — every flag parses' if ok else 'FAILED: ' + str(bad)}")
    if not ok:
        print(f"  [argv smoke] {blob[-600:]}")
    return ok


def run_case(name: str, port: int, turns: list[str], cwd: str) -> list[str]:
    cmd = production_cmd(port, cwd)
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1, env=production_env())
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
    ok = smoke_argv()
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
