"""Standalone stdlib MCP stdio transport for Klaus's private local endpoint."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import urllib.request

HTTP_TIMEOUT_S = 180


def external_python():
    """Find a separate Python 3 executable without launching Anki."""
    candidates = [shutil.which("python3"), shutil.which("python"),
                  "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidate = os.path.abspath(candidate)
        resolved = os.path.realpath(candidate)
        if not os.path.basename(resolved).lower().startswith("python") or not os.path.isfile(candidate):
            continue
        try:
            result = subprocess.run([candidate, "-I", "-c", "import sys; print(3 if sys.version_info >= (3, 9) else 0)"],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip() == "3":
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def client_config(interpreter, script, discovery):
    return json.dumps({"mcpServers": {"klaus": {
        "command": os.path.abspath(interpreter),
        "args": [os.path.abspath(script), "--discovery", os.path.abspath(discovery)],
    }}}, indent=2)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def connection(path):
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    host, port, token = value["host"], value["port"], value["token"]
    address = ipaddress.ip_address(host)
    if not address.is_loopback or "%" in host:
        raise ValueError("invalid loopback host")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("invalid token")
    return host, port, token


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", required=True)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    identity, session = None, None
    for line in sys.stdin:
        try:
            body = json.loads(line)
        except ValueError:
            output = error(None, -32700, "parse error")
        else:
            if not isinstance(body, dict):
                output = error(None, -32600, "invalid request")
            else:
                output = None
                try:
                    current = connection(args.discovery)
                    if identity != current:
                        identity, session = current, None
                    host, port, token = current
                    headers = {"Content-Type": "application/json", "X-Klaus-Token": token}
                    if session:
                        headers["Mcp-Session-Id"] = session
                    url_host = f"[{host}]" if ":" in host else host
                    req = urllib.request.Request(f"http://{url_host}:{port}/mcp",
                                                 data=json.dumps(body).encode("utf-8"), headers=headers)
                    # Never replay: a disconnected write may already have succeeded.
                    with opener.open(req, timeout=HTTP_TIMEOUT_S) as response:
                        session = response.headers.get("Mcp-Session-Id", session)
                        raw = response.read()
                    if "id" in body:
                        output = json.loads(raw) if raw else error(body["id"], -32000, "empty endpoint response")
                except Exception:
                    identity, session = None, None
                    if "id" in body:
                        output = error(body["id"], -32000, "Klaus endpoint unavailable or invalid response")
        if output is not None:
            print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
