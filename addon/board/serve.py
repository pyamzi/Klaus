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
import base64
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boardlib as B  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ATTACH_DIR = os.path.join(HERE, "attachments")

# Paste/drop targets. Keyed by the mime type the browser reports, valued
# by the extension we store — an allowlist, not a sanitiser, so a crafted
# type can never choose its own extension.
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


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

    def _send_attachment(self, name: str) -> None:
        """Serve one stored image by bare filename.

        The name is never joined and hoped for: it must match a file we
        actually wrote, so `..%2f..%2fetc%2fpasswd` and absolute paths
        cannot escape ATTACH_DIR. Bound is `os.path.basename` plus a
        realpath containment check — belt and braces, because this server
        answers unauthenticated requests (it is loopback-only, but a
        browser tab on any site can still reach 127.0.0.1).
        """
        from urllib.parse import unquote

        safe = os.path.basename(unquote(name))
        full = os.path.realpath(os.path.join(ATTACH_DIR, safe))
        if not full.startswith(os.path.realpath(ATTACH_DIR) + os.sep):
            self._send(403, b"forbidden", "text/plain")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = next(
            (m for m, e in IMAGE_TYPES.items() if e == ext), None
        )
        if ctype is None or not os.path.isfile(full):
            self._send(404, b"not found", "text/plain")
            return
        try:
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError as exc:
            self._send(500, str(exc).encode(), "text/plain")

    def _upload(self, data: dict) -> None:
        """Store one pasted/dropped image, return its markdown path.

        Content-addressed: the filename is a hash of the bytes, so pasting
        the same screenshot into three comments stores it once and a retry
        after a failed post cannot litter duplicates.
        """
        ctype = str(data.get("type") or "")
        ext = IMAGE_TYPES.get(ctype)
        if ext is None:
            self._json(415, {"error": f"unsupported image type {ctype!r}"})
            return
        try:
            raw = base64.b64decode(data.get("b64") or "", validate=True)
        except Exception:
            self._json(400, {"error": "malformed image data"})
            return
        if not raw:
            self._json(400, {"error": "empty image"})
            return
        if len(raw) > MAX_IMAGE_BYTES:
            self._json(413, {
                "error": "image is %.1f MB; the limit is %d MB"
                         % (len(raw) / 1048576, MAX_IMAGE_BYTES // 1048576)
            })
            return
        name = hashlib.blake2b(raw, digest_size=8).hexdigest() + ext
        try:
            os.makedirs(ATTACH_DIR, exist_ok=True)
            full = os.path.join(ATTACH_DIR, name)
            if not os.path.exists(full):
                tmp = full + ".part"
                with open(tmp, "wb") as f:
                    f.write(raw)
                os.replace(tmp, full)
        except OSError as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, {"ok": True, "path": "attachments/" + name,
                         "bytes": len(raw)})

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
        if path.startswith("/attachments/"):
            self._send_attachment(path[len("/attachments/"):])
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
        if path == "/api/upload":
            self._upload(data)
            return
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
