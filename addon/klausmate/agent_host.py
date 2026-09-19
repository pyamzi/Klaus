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
still deny everything not explicitly allowlisted, AND confine every
read tool's path argument to the library root, for whatever
``control_request`` traffic a future build or permission mode does send.

The endpoint token never appears in the child's argv (``ps`` is world-
readable): ``command_line`` emits the ``${KLAUS_TOKEN}`` placeholder and
``child_env`` puts the secret in the child's environment. See TOKEN_ENV.
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
OUT_OF_ROOT_MESSAGE = "Klaus only reads files inside your lecture library."
_CALLBACKS = ("init", "delta", "tool_use", "tool_result", "result", "permission_denied", "error", "exited")

#: The endpoint token travels in the child's ENVIRONMENT, never its argv:
#: any local process (any user) can read another process's command line
#: with `ps -ef`, which would expose the token for the child's whole
#: lifetime and undo exactly the boundary it exists to draw. Claude Code
#: expands ``${VAR}`` inside an MCP server's ``headers`` from its own
#: environment, so the command line only ever carries the PLACEHOLDER.
#: Verified live against build 2.1.228 with an inline ``--mcp-config``
#: (the init event's mcp_servers reported "connected" and `ps -o args`
#: on the child showed ``${KLAUS_TOKEN}``, not the secret).
TOKEN_ENV = "KLAUS_TOKEN"
TOKEN_REF = "${" + TOKEN_ENV + "}"

#: Claude Code's own timeout for one MCP ``tools/call``, in MILLISECONDS.
#: It must comfortably exceed anki_endpoint.APPROVAL_TIMEOUT_S (120 s):
#: a write tool call blocks on Klaus's approval dialog, so a shorter
#: client timeout would hand the model a tool error while the dialog is
#: still open — the user then approves, the note IS added, and the model
#: (told by the system prompt that an error means the card was not
#: added) retries into a duplicate. Named as a plain constant rather
#: than imported, to keep this module aqt-free and import-cheap.
MCP_TIMEOUT_ENV = "MCP_TOOL_TIMEOUT"
MCP_TOOL_TIMEOUT_MS = 300_000

#: Nesting markers a Claude-Code-hosted parent leaks into its children.
#: The spike stripped these because a child that detects a host session
#: behaves like an orchestrated sub-agent (inherited tool/skill roster,
#: permission decisions deferred upward) instead of the standalone
#: process Klaus spawns from inside Anki. Production strips the same set
#: so a developer running Anki from a Claude Code terminal gets the same
#: child a normal user does.
NESTING_ENV = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT",
               "CLAUDE_AGENT_SDK_VERSION", "BAGGAGE")
_NESTING_PREFIX = "CLAUDE_CODE_"

#: Tool arguments that name a file or a directory. ``decide_permission``
#: refuses any of these that resolves outside the library root.
PATH_ARG_KEYS = ("file_path", "path", "pattern")


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


_MISS = object()
#: ``path`` holds ``_MISS`` for "never looked up", ``None`` for a CACHED
#: MISS, and a string for a hit — three states, not two.
_binary_cache: dict = {"override": _MISS, "path": _MISS}


def find_claude_cached(override: str = "", **kw) -> str | None:
    """``find_claude`` memoised for the profile session (spec §4.1).

    Step 3 of the search spawns the user's LOGIN SHELL with a 3 s
    timeout, and every caller — the dock's construction, Re-check, and
    every Preferences open — runs on the main thread.

    **A MISS is cached too.** Keying only on "did we find something"
    meant a machine WITHOUT ``claude`` re-ran the whole search, login
    shell and all, on every one of those — the exact main-thread cost
    this memo exists to remove, for the one user who feels it most.
    The ``claude_binary`` config key and the Preferences Override…
    picker that used to invalidate this cache on a changed path were
    both deleted 2026-09-15 (see CLAUDE.md) — ``override`` is always
    ``""`` now, so the one way left to force a fresh lookup is
    ``clear_binary_cache()``, called from Re-check.
    """
    if _binary_cache["override"] == override and _binary_cache["path"] is not _MISS:
        return _binary_cache["path"]
    found = find_claude(override, **kw)
    _binary_cache["override"] = override
    _binary_cache["path"] = found
    return found


def clear_binary_cache() -> None:
    _binary_cache["override"] = _MISS
    _binary_cache["path"] = _MISS


def mcp_config(port: int, token_ref: str = TOKEN_REF) -> str:
    """The inline ``--mcp-config`` JSON. The header value defaults to the
    ``${KLAUS_TOKEN}`` PLACEHOLDER, not the secret — see TOKEN_ENV."""
    return json.dumps({"mcpServers": {MCP_SERVER: {"type": "http", "url": f"http://127.0.0.1:{int(port)}/mcp",
                                                    "headers": {"X-Klaus-Token": token_ref}}}})


def child_env(base: dict, binary: str, token: str) -> dict:
    """The child's environment: the parent's, minus the nesting markers,
    with the binary's own directory ahead on PATH, the endpoint token
    under ``KLAUS_TOKEN`` (never argv), and an MCP tool timeout long
    enough to outlast the approval dialog. Pure — no os.environ read, no
    spawn — so the whole policy is testable without a process."""
    env = {k: v for k, v in dict(base or {}).items()
           if k not in NESTING_ENV and not k.startswith(_NESTING_PREFIX)}
    env["PATH"] = os.path.dirname(binary) + os.pathsep + env.get("PATH", "")
    env[TOKEN_ENV] = str(token or "")
    try:
        inherited = int(env.get(MCP_TIMEOUT_ENV) or 0)
    except (TypeError, ValueError):
        inherited = 0
    env[MCP_TIMEOUT_ENV] = str(max(inherited, MCP_TOOL_TIMEOUT_MS))
    return env


def command_line(binary: str, *, port: int, library_root: str | None, system_prompt_path: str,
                 session_id: str | None = None, resume: str | None = None, model: str = "") -> list[str]:
    """The exact argv. It takes NO token on purpose: the header carries
    the ``${KLAUS_TOKEN}`` placeholder and the secret lives only in the
    child's environment (TOKEN_ENV), so no future caller can leak it
    into `ps` output by passing a literal here."""
    cmd = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--include-partial-messages", "--verbose", "--permission-mode", "default",
           "--mcp-config", mcp_config(port), "--strict-mcp-config"]
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
        # EVERY tool_use block, each with its id — not just the first.
        # Claude Code routinely batches parallel Read/Grep calls into one
        # assistant message; returning only block 0 rendered nothing for
        # the second call and let a later failure decorate the wrong
        # transcript line (final review, M4).
        uses = [(str(b.get("id") or ""), str(b.get("name") or ""), b.get("input") or {})
                for b in ((event.get("message") or {}).get("content") or [])
                if isinstance(b, dict) and b.get("type") == "tool_use"]
        return ("tool_use", uses) if uses else ("other", None)
    if t == "user":
        # Same reason as tool_use above: a batch's results arrive together.
        results = [(str(b.get("tool_use_id") or ""), bool(b.get("is_error")))
                   for b in ((event.get("message") or {}).get("content") or [])
                   if isinstance(b, dict) and b.get("type") == "tool_result"]
        return ("tool_result", results) if results else ("other", None)
    if t == "result":
        # `errors` is carried through because a --resume of a session
        # Claude Code no longer has fails HERE, not on stdout as prose:
        # rc=1 plus a result event whose errors name "No conversation
        # found with session ID" (probed against build 2.1.228). See
        # resume_failed() below.
        errors = event.get("errors")
        return "result", {"session_id": str(event.get("session_id") or ""), "is_error": bool(event.get("is_error")),
                          "duration_ms": int(event.get("duration_ms") or 0), "total_cost_usd": float(event.get("total_cost_usd") or 0.0),
                          "text": str(event.get("result") or ""),
                          "errors": list(errors) if isinstance(errors, list) else []}
    if t == "control_request":
        req = event.get("request") or {}
        if req.get("subtype") == "can_use_tool":
            return "permission", (str(event.get("request_id") or ""), str(req.get("tool_name") or ""), req.get("input") or {})
    return "other", None


_MISSING_SESSION_MARK = "no conversation found"


def resume_failed(payload: dict) -> bool:
    """True when a ``result`` payload says ``--resume`` named a session
    Claude Code does not have. A message-less session is never persisted
    (probe: no transcript file, and ``--resume`` of it exits 1), so a
    remembered id can go stale on its own; the dock drops the mapping
    and starts fresh rather than dying for that PDF."""
    if not isinstance(payload, dict):
        return False
    try:
        blob = json.dumps(payload.get("errors") or []) + " " + str(payload.get("text") or "")
    except Exception:
        blob = str(payload.get("text") or "")
    return _MISSING_SESSION_MARK in blob.lower()


def path_within(value: Any, roots: tuple | list) -> bool:
    """Does ``value`` — a tool's file_path/path/pattern argument — name a
    location inside one of ``roots``?

    A RELATIVE argument is resolved against each root rather than against
    this (Anki's) process cwd, because the child's own cwd IS the library
    root — so `notes/renal.md` and a bare glob are in-root, while
    `~/Library/.../meta.json` and any `..` climb are not (realpath
    collapses the climb before the prefix test). No roots at all means
    nothing is in-root: a host with neither a library root nor an
    assistant directory has nowhere legitimate to read from.
    """
    roots = [str(r) for r in (roots or []) if r]
    if not roots:
        return False
    raw = os.path.expanduser(str(value))
    candidates = [raw] if os.path.isabs(raw) else [os.path.join(r, raw) for r in roots]
    real_roots = []
    for r in roots:
        try:
            real_roots.append(os.path.realpath(os.path.expanduser(r)))
        except Exception:
            continue
    for cand in candidates:
        try:
            p = os.path.realpath(cand)
        except Exception:
            continue
        for rp in real_roots:
            if p == rp or p.startswith(rp + os.sep):
                return True
    return False


def decide_permission(tool_name: str, input: dict, roots: tuple | list = ()) -> tuple[str, str]:
    """Belt-and-braces gate (the front line is ``--disallowedTools``).

    Klaus's own MCP tools are always allowed — the endpoint holds their
    real gate. The four read tools are allowed only for paths inside the
    library root: spec §13 promises the agent's reads are "confined to
    the library root", and an unqualified allow made that untrue for
    exactly the file it matters for — a lecture page's own text, which
    Klaus attaches to every turn as that page's record, is untrusted
    content, and "read
    ~/…/addons21/klausmate/meta.json and summarise it" would put the
    embedding API key into the transcript. Everything else is denied.
    """
    if tool_name.startswith(f"mcp__{MCP_SERVER}__"):
        return "allow", ""
    if tool_name in ("Read", "Grep", "Glob", "ToolSearch"):
        for key in PATH_ARG_KEYS:
            value = (input or {}).get(key)
            if value and not path_within(value, roots):
                return "deny", OUT_OF_ROOT_MESSAGE
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
        # Bumped by every start() (K-211): identifies which spawned child
        # a later `exited` callback belongs to. `_read`'s reader thread
        # captures this LOCALLY at the top, exactly like `proc`, so a
        # child superseded by a later start() while its own thread was
        # still winding down (see `_drain_stderr`'s join on the
        # SUCCESSOR's stderr thread, which delays that stale exit by up
        # to STOP_GRACE_S) can be told apart from the current, live one.
        self._generation = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def alive(self) -> bool:
        """Is there a child process that has NOT exited?

        The dock's respawn gate (final review C1): ``stop()`` leaves the
        child dead — SIGINT, then a 2 s grace, then kill — and nothing
        restarted it, so every later Send wrote into a dead pipe and
        surfaced "stdin write failed: Broken pipe". Reading ``poll()``
        rather than the reader thread's liveness keeps the answer honest
        during the moment between EOF and the thread actually finishing.
        """
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:
            return False

    def permission_roots(self) -> tuple:
        """The directories the agent's read tools may reach — the library
        root, or (with no root configured) the assistant directory. The
        same choice ``start()`` makes for the child's cwd, so the gate
        and the working directory can never disagree."""
        return (self._root,) if self._root else (os.path.dirname(self._sp),)

    def start(self, session_id: str | None = None, resume: str | None = None) -> str:
        self.close()
        self._generation += 1
        self.session_id = resume or session_id or str(uuid.uuid4())
        sid = self.session_id  # local: a fast reader thread (fake procs never block on
        # stdout) can race ahead and overwrite self.session_id from an "init"/"result"
        # event before this method returns — the caller still gets the id it started with.
        self._cmd = command_line(self._binary, port=self._port, library_root=self._root,
                                 system_prompt_path=self._sp, session_id=None if resume else self.session_id,
                                 resume=resume, model=self._model)
        kwargs: dict = {"cwd": self._root or os.path.dirname(self._sp), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                        "stderr": subprocess.PIPE, "text": True, "bufsize": 1}
        kwargs["env"] = child_env(os.environ, self._binary, self._token)
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
            # A child that has already EXITED must never be written to
            # (final review C1): the write lands in a dead pipe, the dock
            # shows "stdin write failed: Broken pipe", and the user's
            # question is gone. Raising instead lets the caller respawn
            # — assistant_dock._ensure_child() does exactly that before
            # every send, so this is the second line of defence.
            try:
                gone = self._proc.poll()
            except Exception:
                gone = None
            if gone is not None:
                raise RuntimeError(f"the Claude Code process has exited (code {gone})")
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
        generation = self._generation
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
                        for tool_id, name, inp in payload:
                            self._cb["tool_use"](tool_id, name, inp)
                    elif kind == "tool_result":
                        for tool_id, is_err in payload:
                            self._cb["tool_result"](tool_id, is_err)
                    elif kind == "permission":
                        rid, name, inp = payload
                        behavior, msg = decide_permission(name, inp, self.permission_roots())
                        self._write(control_response(rid, behavior, msg))
                        if behavior == "deny":
                            self._cb["permission_denied"](name)
                    elif kind == "result":
                        # Same generation compare as the `finally` block
                        # below (K-282): a respawn (start()) may have bumped
                        # self._generation past this thread's own captured
                        # value by the time a "result" line is processed,
                        # and self._running by then belongs to the NEW
                        # child, not this one.
                        if self._generation == generation:
                            self._running = False
                        if payload["session_id"]:
                            self.session_id = payload["session_id"]
                        self._cb["result"](payload)
                except Exception as exc:
                    print(f"[klausmate] agent: callback failed: {exc}")
        except Exception as exc:
            self._cb["error"](f"stream read failed: {exc}")
        finally:
            # K-282: this reader thread's own captured `generation` (set at
            # the top of _read) may be stale by now — _drain_stderr, right
            # below, joins self._stderr_thread, which is the SUCCESSOR's
            # stderr thread once a respawn has happened (the exact delay
            # K-211 documented one level up, for the dock's own `exited`
            # callback). Writing self._running = False here unconditionally
            # would clear it on the object that now describes the LIVE,
            # later-generation child — and stop() no-ops once _running is
            # False, so the live child could never be stopped from the UI
            # until it exited on its own.
            if self._generation == generation:
                self._running = False
            self._drain_stderr()
            rc = None
            try:
                rc = proc.poll()
            except Exception:
                pass
            self._cb["exited"](rc, generation)

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

    def interrupt(self) -> None:
        """Signal the child to stop and RETURN AT ONCE — no wait.

        ``stop()`` blocks up to STOP_GRACE_S on ``proc.wait``, which is
        fine for the explicit Stop button but not for an automatic
        viewer switch: the dock runs that inside viewer_context's
        notifier, on the main thread, so every card that changed PDF
        during review cost a visible hitch (final review I1). The caller
        pairs this with ``reap()`` on a QTimer instead.
        """
        proc = self._proc
        if proc is None:
            return
        try:
            if sys.platform.startswith("win"):
                proc.terminate()
            else:
                proc.send_signal(signal.SIGINT)
        except Exception as exc:
            print(f"[klausmate] agent: interrupt failed: {exc}")
        finally:
            self._running = False

    def reap(self, force: bool = False) -> bool:
        """Has the interrupted child gone? Never blocks.

        Returns True once there is no child left (clearing ``_proc`` so
        ``alive`` is honest), False while one is still exiting. ``force``
        is the caller's grace-period expiry: kill and report gone.
        """
        proc = self._proc
        if proc is None:
            return True
        try:
            rc = proc.poll()
        except Exception:
            rc = 0
        if rc is None and force:
            try:
                proc.kill()
            except Exception as exc:
                print(f"[klausmate] agent: kill failed: {exc}")
            rc = 0
        if rc is None:
            return False
        self._running = False
        self._proc = None
        return True

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
