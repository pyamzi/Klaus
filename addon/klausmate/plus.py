"""Klaus Plus on the add-on side: the key, the endpoint every tagged call uses, a cached verdict.

Nothing here can gate anything (spec: the add-on is readable Python); the
service refusing the key is the gate. What this module CAN do is be
generous — a non-refused verdict is honoured with no expiry of its own
(I-3: nothing here ever re-asks the service on a timer, so a timed-out
"active" could only misroute a paying subscriber to the keyless provider
path; routing the NEXT call to the service is what re-asks it) — and be
honest: a 401/402/426 is remembered for CACHE_TTL_S so the UI can say
why, then forgotten so the next call tries the service again. The key
never appears in any message or log.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, NamedTuple

KEY = "klaus_plus_key"
CACHE = "klaus_plus_cache"
BASE = "klaus_plus_base"
DEFAULT_BASE = "https://klausmate.com"  # 2026-09-17: Pouya's domain, everything on the apex
TOKENS_PER_CARD = 250   # the service's own constants (spec D1); shown, never enforced, here
TOKENS_PER_TURN = 6000
CACHE_TTL_S = 6 * 3600
PURPOSES = ("embed", "transcribe", "judge", "assistant")
_HEX = set("0123456789abcdef")  # the service's own keys.looks_like_key alphabet
TIMEOUT_S = 15.0
_urlopen = urllib.request.urlopen


class Endpoint(NamedTuple):
    base: str
    headers: dict


def client_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(__file__), "manifest.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("human_version") or "0")
    except (OSError, ValueError):
        return "0"


def key(cfg: dict) -> str:
    """K-262: exactly the service's `keys.looks_like_key` contract — `kp_` plus 32 lowercase
    hex, since `keys.mint()` is `token_hex(16)`. A 35-character string that is not one of
    those can only ever earn a 401, so it reads as no key at all."""
    k = str((cfg or {}).get(KEY) or "").strip()
    return k if k.startswith("kp_") and len(k) == 35 and set(k[3:]) <= _HEX else ""


def base(cfg: dict) -> str:
    return (str((cfg or {}).get(BASE) or "").strip() or DEFAULT_BASE).rstrip("/")


def _cache(cfg: dict) -> dict:
    c = (cfg or {}).get(CACHE)
    return c if isinstance(c, dict) else {}


def active(cfg: dict, now: float | None = None) -> bool:
    if not key(cfg):
        return False
    c = _cache(cfg)
    if not c:
        return True
    now = time.time() if now is None else now
    age = now - float(c.get("checked_at") or 0)
    status = str(c.get("status") or "")
    if status.startswith("refused"):
        return age > CACHE_TTL_S  # ask again after the TTL; the service decides
    return True  # not a refusal: honoured until the service says otherwise (I-3)


def endpoint(cfg: dict, purpose: str) -> Endpoint:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    return Endpoint(base(cfg), {"Authorization": f"Bearer {key(cfg)}", "X-Klaus-Purpose": purpose,
                                "X-Klaus-Client": client_version()})


def parse_quota(headers: Any) -> dict | None:
    """The ``X-Klaus-Quota`` header as a dict, from an ``HTTPMessage``
    (case-insensitive by itself) or a plain dict in ANY key casing — a
    metered call's fake response in a test is rarely spelled the
    canonical way, and neither is every real header dict."""
    try:
        items = headers.items() if hasattr(headers, "items") else []
        raw = next((v for k, v in items if str(k).lower() == "x-klaus-quota"), None)
        obj = json.loads(raw) if raw else None
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def note_quota(cfg: dict, headers: Any, patch_config: Callable[[dict], None]) -> dict | None:
    """A metered call's own response IS a fresh active verdict.

    Parses ``headers`` for the quota snapshot and, when present, remembers
    it as an active verdict through ``patch_config`` (see ``remember``'s
    docstring on why that must be a PATCH writer). Absent or garbage
    headers write nothing and answer None — a call that carries no quota
    header must not be read as a refusal or silently invent one.

    INVARIANT: call this only from a guaranteed-2xx path — the clients'
    own ``on_headers`` callback, which fires after a successful response
    and never on an error. It unconditionally records status "active";
    handing it an error response's headers would overwrite a real
    refusal with a false "active" verdict.
    """
    snapshot = parse_quota(headers)
    if snapshot is None:
        return None
    remember(cfg, snapshot, "active", patch_config)
    return snapshot


def remember(cfg: dict, snapshot: dict | None, status: str, write_config: Callable[[dict], None],
             now: float | None = None, period_end: float = 0.0, message: str = "") -> dict:
    """Record a verdict and hand the sink exactly ``{CACHE: c}``.

    Despite the parameter's name, ``write_config`` here must be a PATCH
    writer — the package's ``patch_config`` (getConfig -> update ->
    writeConfig) — never the package's own plain ``write_config``, which
    REPLACES the whole stored config wholesale. Handing this a one-key
    dict through that plain writer wipes every other setting (API keys,
    library root, every preference) on the first refusal. Every
    ``plus.*`` caller (embeddings.py, manage_models.py, ...) must pass
    ``patch_config``.
    """
    now = time.time() if now is None else now
    c = {"status": status, "checked_at": now, "period_end": float(period_end or _cache(cfg).get("period_end") or 0)}
    if snapshot is not None:
        c["quota"] = snapshot
    elif _cache(cfg).get("quota"):
        c["quota"] = _cache(cfg)["quota"]
    if message:
        c["message"] = message
    write_config({CACHE: c})
    return c


def note_refusal(cfg: dict, status_code: int, write_config: Callable[[dict], None], now: float | None = None,
                 message: str = "") -> None:
    remember(cfg, None, f"refused:{int(status_code)}", write_config, now=now, message=message)


def _call(cfg: dict, method: str, path: str, urlopen=None) -> tuple[int, dict, dict]:
    ep = endpoint(cfg, "embed")
    req = urllib.request.Request(ep.base + path, data=b"{}" if method == "POST" else None, method=method,
                                 headers={**ep.headers, "Content-Type": "application/json"})
    try:
        with (urlopen or _urlopen)(req, timeout=TIMEOUT_S) as resp:
            return int(getattr(resp, "status", 200) or 200), json.loads(resp.read().decode("utf-8") or "{}"), dict(getattr(resp, "headers", {}) or {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        return int(e.code), body, {}


def refresh(get_config: Callable[[], dict], write_config: Callable[[dict], None], urlopen=None) -> dict:
    cfg = get_config() or {}
    if not key(cfg):
        return {}
    try:
        status, body, _ = _call(cfg, "GET", "/v1/me", urlopen)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[klausmate] Klaus Plus check failed: {exc.__class__.__name__}")
        return _cache(cfg)
    if status == 200 and isinstance(body, dict):
        return remember(cfg, body.get("quota") if isinstance(body.get("quota"), dict) else None,
                        str(body.get("status") or "active"), write_config, period_end=float(body.get("period_end") or 0))
    if status >= 500 or (200 <= status < 300 and not isinstance(body, dict)):
        print(f"[klausmate] Klaus Plus check failed: HTTP {status}")
        return _cache(cfg)
    msg = str(((body or {}).get("error") or {}).get("message") or "")
    return remember(cfg, None, f"refused:{status}", write_config, message=msg)


def portal_url(cfg: dict, urlopen=None) -> str:
    status, body, _ = _call(cfg, "POST", "/v1/portal", urlopen)
    return str(body.get("url") or "") if status == 200 else ""


def status_line(cache: dict) -> str:
    if not cache:
        return "Klaus Plus: not checked yet — press Check."
    status = str(cache.get("status") or "")
    if status.startswith("refused"):
        return f"Klaus Plus: {cache.get('message') or 'refused by the service'} (checked {_day(cache.get('checked_at'))})."
    if status == "past_due":
        return "Klaus Plus: past due — fix your card under Manage subscription…"
    q = (cache.get("quota") or {}).get("human") or {}
    h, c, t = q.get("lecture_hours") or [0, 0], q.get("cards") or [0, 0], q.get("turns") or [0, 0]
    word = "ends" if status == "canceled" else "trial ends" if status == "trialing" else "renews"
    when = f" · {word} {_day(cache.get('period_end'))}" if cache.get("period_end") else ""
    return (f"Plus{when} · {h[0]} of {h[1]:g} lecture hours, {c[0]:,} of {c[1]:,} cards, {t[0]} of {t[1]} turns this month")


def _day(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return "?"
