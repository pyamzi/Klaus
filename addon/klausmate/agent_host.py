"""The Claude Code child: find it, spawn it, feed it turns, read its stream.

Klaus is a HOST for Claude Code, not a loop of its own (the in-house loop
was deleted with this module's arrival — Pouya, 2026-09-01: "wrap the
Claude Code CLI, exactly like Claudian"). Everything crossing the process
boundary is injected (``spawn``, ``which``, ``run``), so the whole module
runs in tests with a fake process and no binary.

Field paths in ``classify`` are pinned by the recorded fixtures under
tests/fixtures/claude_stream/ (Task 1 of the plan). Where the fixtures were
not recorded they follow the spec's §4.4 table and are PROVISIONAL.

Permission gating is belt-and-braces, not the front line: the recorded
spike (tests/fixtures/claude_stream/README.md §4) saw zero
``control_request`` events and a non-disallowed tool run unprompted under
``--permission-mode default`` (not even a mode this build's own ``--help``
lists), so the real guard is the static ``--disallowedTools`` list
``command_line`` sends — ``decide_permission``/``control_response`` below
still deny everything not explicitly allowlisted, for whatever
``control_request`` traffic a future build or permission mode does send.
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
        # Per the fixtures' README §2: .mcp_servers is an array of {name, status},
        # never a literal mcp_ok boolean, and --strict-mcp-config means it only
        # ever lists "klaus" here — so "every listed server connected" and
        # "our server connected" are the same check; empty never reads as ok.
        servers = event.get("mcp_servers") or []
        ok = bool(servers) and all(isinstance(s, dict) and s.get("status") == "connected" for s in servers)
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
        self._stderr_thread: threading.Thread | None = None
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
        sid = self.session_id  # local: a fast reader thread (fake procs never block on
        # stdout) can race ahead and overwrite self.session_id from an "init"/"result"
        # event before this method returns — the caller still gets the id it started with.
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
        # Continuous, not one-shot (review Important #2): stderr is a PIPE
        # (kwargs above), and a child that fills the OS pipe buffer (~64KB)
        # before exiting would otherwise deadlock — it blocks writing to a
        # full, undrained pipe while _read()'s loop only ever watches stdout.
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="klaus-agent-stderr", daemon=True)
        self._stderr_thread.start()
        return sid

    def send(self, turn_line: str) -> None:
        with self._lock:
            if self._proc is None:
                raise RuntimeError("agent not started")
            # Only claim a turn is in flight if a reader is still around to ever
            # clear it — a reader that already hit EOF (child exited) will never
            # fire another "result", so latching running=True here would strand it.
            if self._reader is not None and self._reader.is_alive():
                self._running = True
            else:
                print("[klausmate] agent: send() with no live reader — turn written, but nothing will report its result")
            try:
                self._proc.stdin.write(turn_line)
                self._proc.stdin.flush()
            except Exception as exc:
                # send() is the public entry point Task 9's dock calls directly
                # from UI code — a dead pipe here must reach the caller as a
                # callback, never a raised exception (review Important #1).
                print(f"[klausmate] agent: stdin write failed: {exc}")
                self._running = False
                self._cb["error"](f"stdin write failed: {exc}")

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

    def _read_stderr(self) -> None:
        """Drains stderr one line at a time for the whole life of the child
        (review Important #2) — started alongside the stdout reader in
        start(), not read once at teardown, or a chatty-enough child could
        fill the OS pipe buffer and deadlock before ever reaching EOF."""
        proc = self._proc
        try:
            for raw in proc.stderr:
                self._append_log(raw)
        except Exception as exc:
            print(f"[klausmate] agent: stderr read failed: {exc}")

    def _append_log(self, text: str) -> None:
        if not text or not text.strip():
            return
        try:
            os.makedirs(os.path.dirname(self._log), exist_ok=True)
            if os.path.exists(self._log) and os.path.getsize(self._log) > LOG_CAP_BYTES:
                os.replace(self._log, self._log + ".1")
            with open(self._log, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            print(f"[klausmate] agent: log write failed: {exc}")

    def _drain_stderr(self) -> None:
        """Joins the continuous stderr thread so any trailing output has
        landed in the log before "exited" fires; bounded so a stuck join
        can't hang teardown forever."""
        t = self._stderr_thread
        if t is not None:
            try:
                t.join(timeout=STOP_GRACE_S)
            except Exception as exc:
                print(f"[klausmate] agent: stderr thread join failed: {exc}")

    def stop(self) -> None:
        """SIGINT, a 2 s grace, then kill. The session id survives.

        Windows uses terminate() unconditionally rather than spec §4.6's
        "CTRL_BREAK_EVENT where available" — that signal only targets a
        specific process cleanly when the child was spawned with
        CREATE_NEW_PROCESS_GROUP, which start() does not set, so sending it
        here could hit the wrong process group, including this one.
        """
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
