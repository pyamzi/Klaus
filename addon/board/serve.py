#!/usr/bin/env python3
"""Local dashboard for the kanban board.

Serves dashboard.html and a small JSON API over BOARD.md. Every mutation
goes through the same boardlib.mutate() the CLI uses, so the dashboard and
a swarm of workers share one lock and one set of validation rules — the
browser cannot make a move a worker couldn't.

Bound to 127.0.0.1 only. No auth, because it is not reachable off-host.

    python3 board/serve.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boardlib as B  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def board_mtime() -> float:
    try:
        return os.path.getmtime(B.board_path())
    except OSError:
        return 0.0


class Handler(BaseHTTPRequestHandler):
    server_version = "klausboard/1.0"

    def log_message(self, fmt, *args):  # quieter than the default
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ helpers

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    # ---------------------------------------------------------------- GET

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError as exc:
                self._send(500, str(exc).encode(), "text/plain")
            return
        if path == "/api/board":
            payload = B.to_dict(B.load())
            payload["mtime"] = board_mtime()
            self._json(200, payload)
            return
        self._send(404, b"not found", "text/plain")

    # --------------------------------------------------------------- POST

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        data = self._read_json()
        ops = {
            "/api/move": lambda b: B.move(
                b, data["id"], data["to"], bool(data.get("force"))
            ),
            "/api/claim": lambda b: B.claim(b, data["id"], data.get("owner") or "human"),
            "/api/release": lambda b: B.release(b, data["id"]),
            "/api/comment": lambda b: B.comment(
                b, data["id"], data.get("author") or "human", data.get("text") or ""
            ),
            "/api/add": lambda b: B.add(
                b, data.get("col") or "Backlog", data.get("title") or "Untitled",
                data.get("fields") or {}, data.get("body") or "",
            ),
            "/api/edit": lambda b: B.edit(
                b, data["id"], data.get("title"), data.get("fields"), data.get("body")
            ),
            "/api/delete": lambda b: B.delete(b, data["id"]),
            "/api/archive": lambda b: B.archive(b, data["id"]),
            # Sweeps every Done card in one lock hold, rather than the UI
            # firing one /api/archive per card (each a separate lock
            # acquisition racing the same swarm of workers).
            "/api/archive_all": lambda b: B.archive_all_done(b),
        }
        op = ops.get(path)
        if op is None:
            self._send(404, b"not found", "text/plain")
            return
        try:
            result = B.mutate(op)
        except KeyError as exc:
            self._json(400, {"error": "missing field %s" % exc})
        except B.LockTimeout as exc:
            self._json(503, {"error": str(exc)})
        except B.BoardError as exc:
            # 409: the board's rules refused this, which the UI surfaces
            # verbatim rather than guessing at a friendlier wording.
            self._json(409, {"error": str(exc)})
        else:
            # Most ops return one Card; archive_all returns a list (possibly
            # empty, when there was nothing Done to sweep).
            if isinstance(result, list):
                payload = {"ok": True, "ids": [c.id for c in result]}
            else:
                payload = {"ok": True, "id": result.id}
            payload["mtime"] = board_mtime()
            self._json(200, payload)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("board dashboard → http://127.0.0.1:%d" % args.port)
    print("serving %s" % B.board_path())
    print("Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
