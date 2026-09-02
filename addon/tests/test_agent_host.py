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
    permission_denied_has_control_request = False
    for name in ("turn_with_image", "tool_call", "permission_denied"):
        with open(os.path.join(FIX, f"{name}.jsonl")) as f:
            for raw in f:
                ev = ah.parse_line(raw)
                if ev is not None:
                    kinds.append(ah.classify(ev)[0])
                    if name == "permission_denied" and ev.get("type") == "control_request":
                        permission_denied_has_control_request = True
    check("recorded stream yields init, delta, result", {"init", "delta", "result"} <= set(kinds), str(sorted(set(kinds))))
    check("recorded stream yields a tool_use and a tool_result", "tool_use" in kinds and "tool_result" in kinds)
    if permission_denied_has_control_request:
        check("recorded stream yields a permission request", "permission" in kinds)
    else:
        print("  SKIP no control_request in permission_denied.jsonl (build 2.1.228 never emitted one — see the fixtures' README)")
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
check("Read/Grep/Glob allowed", all(ah.decide_permission(t, {})[0] == "allow" for t in ("Read", "Grep", "Glob")))
check("ToolSearch allowed (deferred MCP tool discovery, README §3)", ah.decide_permission("ToolSearch", {})[0] == "allow")
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

section("send() never raises (review round 2, Important #1)")
class RaisingWriteProc:
    class _Stdin:
        def write(self, s): raise BrokenPipeError("broken pipe")
        def flush(self): pass
    def __init__(self):
        self.stdin = self._Stdin(); self.stdout = io.StringIO(""); self.stderr = io.StringIO("")
        self.pid = 7777; self._rc = None; self.signals = []
    def poll(self): return self._rc
    def wait(self, timeout=None): self._rc = 0; return 0
    def send_signal(self, s): self.signals.append(s); self._rc = -2
    def terminate(self): self.signals.append("TERM"); self._rc = -15
    def kill(self): self.signals.append("KILL"); self._rc = -9
got3 = {k: [] for k in got}
cbs3 = {k: (lambda k: (lambda *a: got3[k].append(a)))(k) for k in got3}
host3 = ah.AgentHost("/bin/claude", port=1, token="t", library_root=tmp, system_prompt_path="/sp", model="",
                     log_path=os.path.join(tmp, "c3.log"), callbacks=cbs3, spawn=lambda c, **k: RaisingWriteProc())
host3.start()
host3.send(ah.build_turn("q", blk0, None))
check("send() with a broken pipe never raises, reports error once, and clears running",
      len(got3["error"]) == 1 and host3.running is False)

section("stderr drains continuously (review round 2, Important #2)")
class ManualStream:
    """A read-end stand-in that genuinely BLOCKS between lines (unlike
    io.StringIO, which never blocks and lets an eager reader race straight
    to EOF) -- needed to prove stderr drains WHILE stdout is still open,
    not only once the reader thread's own EOF-triggered teardown runs."""
    def __init__(self):
        self._cond = threading.Condition(); self._lines = []; self._closed = False
    def push(self, line):
        with self._cond:
            self._lines.append(line); self._cond.notify_all()
    def close(self):
        with self._cond:
            self._closed = True; self._cond.notify_all()
    def __iter__(self): return self
    def __next__(self):
        with self._cond:
            while not self._lines and not self._closed:
                self._cond.wait(timeout=5)
            if self._lines:
                return self._lines.pop(0)
            raise StopIteration
class ManualProc:
    def __init__(self):
        self.stdin = io.StringIO(); self.stdout = ManualStream(); self.stderr = ManualStream()
        self.pid = 8888; self._rc = None; self.signals = []
    def poll(self): return self._rc
    def wait(self, timeout=None): self._rc = 0; return 0
    def send_signal(self, s): self.signals.append(s); self._rc = -2
    def terminate(self): self.signals.append("TERM"); self._rc = -15
    def kill(self): self.signals.append("KILL"); self._rc = -9
mproc = ManualProc()
got4 = {k: [] for k in got}
cbs4 = {k: (lambda k: (lambda *a: got4[k].append(a)))(k) for k in got4}
log4 = os.path.join(tmp, "stderr_continuous.log")
host4 = ah.AgentHost("/bin/claude", port=1, token="t", library_root=tmp, system_prompt_path="/sp", model="",
                     log_path=log4, callbacks=cbs4, spawn=lambda c, **k: mproc)
host4.start()
mproc.stderr.push("stderr line one\n")
mproc.stderr.push("stderr line two\n")
def _log_has_both():
    return os.path.exists(log4) and "stderr line one" in open(log4).read() and "stderr line two" in open(log4).read()
deadline = time.time() + 5
while time.time() < deadline and not _log_has_both():
    time.sleep(0.02)
seen_before_exit = _log_has_both()
exited_before_check = bool(got4["exited"])
mproc.stderr.close()
mproc.stdout.close()
deadline = time.time() + 5
while time.time() < deadline and not got4["exited"]:
    time.sleep(0.02)
check("both stderr lines land in the log before the reader thread reports exited",
      seen_before_exit and not exited_before_check and bool(got4["exited"]))
host4.close()

raise SystemExit(report())
