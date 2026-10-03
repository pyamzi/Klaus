"""Exercise the standalone bridge through actual subprocess pipes and scratch HTTP."""
from __future__ import annotations
import importlib
import json
import os
from pathlib import Path
import select
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install, check, report, section
install()
ep = importlib.import_module("klaus_note.anki_endpoint")


def request(rid, method, **params):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


with tempfile.TemporaryDirectory(prefix="klaus bridge spaces ") as scratch:
    root = Path(scratch)
    script = root / "bridge with spaces.py"
    source = Path("klaus_note/scripts/mcp_stdio_bridge.py")
    check("standalone script exists", source.is_file())
    if not source.is_file():
        raise SystemExit(report())
    shutil.copyfile(source, script)
    bridge = runpy.run_path(str(script))
    check("HTTP timeout exceeds approval window", bridge["HTTP_TIMEOUT_S"] == 180 > ep.APPROVAL_TIMEOUT_S)
    discovery = root / "connection with spaces.json"
    env = dict(os.environ, HTTP_PROXY="http://127.0.0.1:1", HTTPS_PROXY="http://127.0.0.1:1",
               ALL_PROXY="http://127.0.0.1:1", NO_PROXY="", no_proxy="", PYTHONIOENCODING="cp1252")
    proc = subprocess.Popen([sys.executable, str(script), "--discovery", str(discovery)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    def send(value):
        proc.stdin.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")); proc.stdin.flush()
    def receive():
        if not select.select([proc.stdout], [], [], 5)[0]:
            raise AssertionError("bridge response timed out")
        return json.loads(proc.stdout.readline())
    def exchange(value):
        send(value); return receive()
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((dict(self.headers), body, self.path))
            if body["method"] == "disconnect_write":
                self.connection.close(); return
            if body["method"] == "redirect":
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/stolen")
                self.end_headers(); return
            data = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result":
                               {"content": [{"type": "image", "mimeType": "image/png", "data": "YWJj"}]}}).encode()
            self.send_response(200)
            if body["method"] == "initialize": self.send_header("Mcp-Session-Id", "session-one")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def publish(token="one", port=None, **changes):
        value = dict(host="127.0.0.1", port=port or server.server_port, token=token)
        value.update(changes); discovery.write_text(json.dumps(value))
    try:
        section("discovery validation and framing")
        check("missing discovery is transport error", exchange(request(1, "ping"))["error"]["code"] == -32000)
        discovery.write_text("broken")
        check("malformed discovery is transport error", exchange(request(2, "ping"))["id"] == 2)
        for changes in ({"host": "example.com"}, {"host": "127.0.0.1/else"}, {"port": True},
                        {"port": 65536}, {"port": "80"}, {"token": ""}, {"token": "bad\r\nHeader: x"}):
            publish(**changes)
            check("invalid discovery rejected before HTTP", "error" in exchange(request(3, "ping")) and not calls)
        proc.stdin.write(b'{broken\n'); proc.stdin.flush()
        check("malformed JSON parse error", receive()["error"]["code"] == -32700)
        check("nonobject invalid request", exchange([])["error"]["code"] == -32600)
        publish()
        image = exchange(request(4, "initialize"))
        check("image content preserved", image["result"]["content"][0]["data"] == "YWJj")
        exchange(request(5, "tools/list"))
        check("session and token forwarded", calls[-1][0].get("Mcp-Session-Id") == "session-one" and calls[-1][0].get("X-Klaus-Token") == "one")
        exchange(request(51, "unicode_read", text="café"))
        check("literal UTF-8 request preserved", calls[-1][1]["params"]["text"] == "café")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("notification has no response", not select.select([proc.stdout], [], [], .2)[0])
        second_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=second_server.serve_forever, daemon=True).start()
        old_server = server
        server = second_server
        old_server.shutdown(); old_server.server_close()
        publish(token="two")
        exchange(request(6, "ping"))
        check("identity rotation resets session", calls[-1][0].get("X-Klaus-Token") == "two" and "Mcp-Session-Id" not in calls[-1][0])
        discovery.write_text("bad")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("failed notification stays silent", not select.select([proc.stdout], [], [], .2)[0])
        publish()
        before = len(calls)
        check("disconnect returns request error", exchange(request(7, "disconnect_write"))["id"] == 7)
        check("write is never replayed", len(calls) == before + 1)
        before = len(calls)
        check("redirect refused", "error" in exchange(request(8, "redirect")) and len(calls) == before + 1)
        section("real injected Endpoint approval gate")
        writes, approvals = [], []
        answer = [False]
        def approve(*args): approvals.append(args); return answer[0]
        class Tags:
            def bulk_add(self, ids, tags): writes.append((ids, tags))
        class Collection:
            tags = Tags()
        endpoint = ep.Endpoint(col_getter=lambda: Collection(), run_on_main=lambda fn, timeout: fn(),
                               approver=approve, ctx_factory=lambda: {}, version="test")
        endpoint.start()
        try:
            publish(token=endpoint.token, port=endpoint.port)
            check("initialize real endpoint", exchange(request(9, "initialize"))["result"]["serverInfo"]["name"] == "klaus")
            check("tools/list real endpoint", bool(exchange(request(10, "tools/list"))["result"]["tools"]))
            check("read tool", not exchange(request(11, "tools/call", name="current_view"))["result"].get("isError"))
            check("write denied", exchange(request(12, "tools/call", name="add_tags", arguments={"note_ids": [1], "tags": "test"}))["result"]["isError"] and not writes)
            answer[0] = True
            check("write accepted with literal UTF-8", not exchange(request(13, "tools/call", name="add_tags", arguments={"note_ids": [1], "tags": "café"}))["result"].get("isError") and writes == [([1], "café")] and len(approvals) == 2)
            diagnose = bridge.get("test_connection")
            check("connection diagnostic exists", callable(diagnose))
            if callable(diagnose):
                before = list(writes)
                diagnosis = diagnose(sys.executable, str(script), str(discovery))
                check("diagnostic starts real stdio bridge and discovers tools", diagnosis['ok'] and diagnosis['tool_count'] == len(ep.mcp_tools()))
                check("diagnostic never calls collection tools", writes == before)
                publish(token='wrong-secret', port=endpoint.port)
                diagnosis = diagnose(sys.executable, str(script), str(discovery))
                check("diagnostic explains rejected authentication without secrets", not diagnosis['ok'] and 'restart Anki' in diagnosis['message'] and 'wrong-secret' not in str(diagnosis))
                discovery.unlink()
                check("diagnostic explains closed profile", 'profile' in diagnose(sys.executable, str(script), str(discovery))['message'])
                discovery.write_text('invalid')
                check("diagnostic explains invalid discovery", 'restart Anki' in diagnose(sys.executable, str(script), str(discovery))['message'])
                publish(token=endpoint.token, port=endpoint.port)
                check("diagnostic explains missing interpreter", 'Python' in diagnose('/missing/python3', str(script), str(discovery))['message'])
                endpoint.stop()
                diagnosis = diagnose(sys.executable, str(script), str(discovery))
                check("diagnostic explains stopped endpoint", not diagnosis['ok'] and 'restart Anki' in diagnosis['message'])
        finally: endpoint.stop()
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
        check("stdout contains only expected frames", proc.stdout.read() == b"")
        check("stderr contains no diagnostics or secrets", proc.stderr.read() == b"")
        server.shutdown(); server.server_close()
raise SystemExit(report())
