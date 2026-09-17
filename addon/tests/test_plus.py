from __future__ import annotations
import email.message, io, json, os, sys, time, urllib.request
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, section, report, install
install()
import klausmate.plus as plus  # noqa: E402

section("keys, base and the client version")
check("no key → not active", plus.active({}) is False and plus.key({}) == "")
check("a key alone is active (optimistic until the service says otherwise)", plus.active({"klaus_plus_key": "kp_" + "a" * 32}))
check("whitespace is stripped and a non-key string is not a key", plus.key({"klaus_plus_key": "  kp_" + "b" * 32 + " "}) == "kp_" + "b" * 32
      and plus.key({"klaus_plus_key": "sk-abc"}) == "")
check("K-262: kp_ + 32 chars is not enough — the suffix must be hex, the service's own looks_like_key contract",
      plus.key({"klaus_plus_key": "kp_" + "z" * 32}) == "" and plus.key({"klaus_plus_key": "kp_" + "0123456789abcdef" * 2}) == "kp_" + "0123456789abcdef" * 2)
check("base defaults and strips a trailing slash", plus.base({}) == plus.DEFAULT_BASE and plus.base({"klaus_plus_base": "https://x.test/"}) == "https://x.test")
check("client_version reads manifest.json's human_version", plus.client_version() == json.load(open("klausmate/manifest.json"))["human_version"])

section("the endpoint carries the bearer key, the purpose and the version")
cfg = {"klaus_plus_key": "kp_" + "c" * 32, "klaus_plus_base": "https://svc.test"}
ep = plus.endpoint(cfg, "judge")
check("base is the service", ep.base == "https://svc.test")
check("headers: bearer key, purpose, client version",
      ep.headers["Authorization"] == "Bearer kp_" + "c" * 32 and ep.headers["X-Klaus-Purpose"] == "judge"
      and ep.headers["X-Klaus-Client"] == plus.client_version())
try:
    plus.endpoint(cfg, "mine")
    check("an unknown purpose raises ValueError", False)
except ValueError:
    check("an unknown purpose raises ValueError", True)

section("the verdict cache: fresh, honoured until refused, refusals expire")
now = 1_800_000_000.0
written = {}
snap = {"month": "2026-09", "resets_at": now + 86400, "counters": {}, "human": {"lecture_hours": [4.0, 30.0], "cards": [812, 3000], "turns": [31, 200]}}
cache = plus.remember(dict(cfg), snap, "active", written.update, now=now)
_keys_remember = set(written.keys())
check("remember writes klaus_plus_cache with the snapshot, status and checked_at",
      written["klaus_plus_cache"]["status"] == "active" and written["klaus_plus_cache"]["checked_at"] == now
      and written["klaus_plus_cache"]["quota"]["human"]["cards"] == [812, 3000])
cfg2 = dict(cfg, klaus_plus_cache=cache)
check("fresh active → active", plus.active(cfg2, now=now + 3600))
check("stale (the old 7-day grace boundary) → still active", plus.active(cfg2, now=now + 3 * 86400))
check("older than 7 days → still active — the service is the gate, not a timer "
      "(I-3: nothing here ever re-asks the service on its own, so an expiring cache "
      "could only misroute a paying subscriber to the keyless provider path)",
      plus.active(cfg2, now=now + 8 * 86400))
plus.note_refusal(cfg2, 402, written.update, now=now + 10)
_keys_note_refusal = set(written.keys())
cfg3 = dict(cfg, klaus_plus_cache=written["klaus_plus_cache"])
check("a 402 marks the cache refused and active() is False while fresh", written["klaus_plus_cache"]["status"] == "refused:402"
      and plus.active(cfg3, now=now + 20) is False)
check("a refused verdict expires after the TTL so the service gets asked again", plus.active(cfg3, now=now + 7 * 3600))

section("status_line and parse_quota")
line = plus.status_line({"status": "active", "period_end": now + 15 * 86400, "quota": snap})
check("active status line names the plan, the renewal day and the three counters",
      line.startswith("Plus · renews 2027-01-30") and "4.0 of 30 lecture hours" in line and "812 of 3,000 cards" in line and "31 of 200 turns" in line, line)
canceled_line = plus.status_line({"status": "canceled", "period_end": now + 15 * 86400, "quota": snap})
check("canceled status line says it ENDS, never 'renews' (M-7)",
      canceled_line.startswith("Plus · ends 2027-01-30") and "renews" not in canceled_line, canceled_line)
trialing_line = plus.status_line({"status": "trialing", "period_end": now + 15 * 86400, "quota": snap})
check("trialing status line says the trial ends",
      trialing_line.startswith("Plus · trial ends 2027-01-30"), trialing_line)
past_due_line = plus.status_line({"status": "past_due", "period_end": now + 15 * 86400, "quota": snap})
check("past_due status line tells the subscriber to fix their card, never 'renews' (M-7)",
      "past due" in past_due_line.lower() and "fix your card" in past_due_line.lower()
      and "renews" not in past_due_line, past_due_line)
check("no cache → an honest line", "not checked yet" in plus.status_line({}).lower())
check("parse_quota reads the header and tolerates absence/junk",
      plus.parse_quota({"X-Klaus-Quota": json.dumps(snap)})["human"]["turns"] == [31, 200]
      and plus.parse_quota({}) is None and plus.parse_quota({"X-Klaus-Quota": "{"}) is None)
_msg = email.message.Message()
_msg["x-klaus-quota"] = json.dumps(snap)
check("parse_quota reads an HTTPMessage-style object (email.message.Message)",
      plus.parse_quota(_msg)["human"]["cards"] == [812, 3000])
check("parse_quota reads a plain dict keyed in ANY casing, not just the canonical one",
      plus.parse_quota({"x-klaus-quota": json.dumps(snap)})["human"]["turns"] == [31, 200]
      and plus.parse_quota({"X-KLAUS-QUOTA": json.dumps(snap)})["human"]["turns"] == [31, 200])

section("note_quota: a successful metered call's headers become an active verdict")
recorded = {}
out = plus.note_quota(cfg, {"X-Klaus-Quota": json.dumps(snap)}, recorded.update)
check("note_quota remembers status active with the snapshot and returns the snapshot",
      out == snap and recorded["klaus_plus_cache"]["status"] == "active"
      and recorded["klaus_plus_cache"]["quota"]["human"]["cards"] == [812, 3000])
recorded.clear()
check("note_quota returns None and writes nothing on an absent or garbage header",
      plus.note_quota(cfg, {}, recorded.update) is None and recorded == {}
      and plus.note_quota(cfg, {"X-Klaus-Quota": "{"}, recorded.update) is None and recorded == {})

section("refresh and portal_url go through the seam, never log the key")
calls = []
class _Resp(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body); self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), req.data))
    if req.full_url.endswith("/v1/me"):
        return _Resp(json.dumps({"plan": "plus", "status": "active", "period_end": now + 5 * 86400, "quota": snap,
                                 "min_client_version": "0.2.0"}).encode())
    return _Resp(json.dumps({"url": "https://portal.test/p"}).encode())
written.clear()
out = plus.refresh(lambda: dict(cfg), written.update, urlopen=fake_urlopen)
_keys_refresh = set(written.keys())
check("refresh GETs /v1/me with the bearer key and writes the cache",
      calls[0][0] == "https://svc.test/v1/me" and calls[0][1].get("Authorization") == "Bearer kp_" + "c" * 32
      and written["klaus_plus_cache"]["status"] == "active" and out["quota"]["human"]["cards"] == [812, 3000])
check("remember/note_refusal/refresh each hand the sink a dict with exactly one key, CACHE — "
      "never the full config (a future {**cfg, CACHE: c} would clobber a concurrent "
      "Preferences save through a patch writer)",
      _keys_remember == {plus.CACHE} and _keys_note_refusal == {plus.CACHE} and _keys_refresh == {plus.CACHE})
check("portal_url POSTs /v1/portal and returns the url",
      plus.portal_url(cfg, urlopen=fake_urlopen) == "https://portal.test/p" and calls[1][0] == "https://svc.test/v1/portal")
def failing(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 402, "quota", {}, io.BytesIO(json.dumps({"error": {"message": "used up"}}).encode()))
written.clear()
out = plus.refresh(lambda: dict(cfg), written.update, urlopen=failing)
check("a 402 on refresh is remembered as refused, message kept, key absent from it",
      out["status"] == "refused:402" and out.get("message") == "used up" and "kp_" not in json.dumps(out))
written.clear()
old_checked_at = now - 2 * 86400
old_cache = plus.remember(dict(cfg), snap, "active", written.update, now=old_checked_at)
cfg4 = dict(cfg, klaus_plus_cache=old_cache)
written.clear()
def fake503(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 503, "down", {}, io.BytesIO(b"upstream restarting"))
out = plus.refresh(lambda: dict(cfg4), written.update, urlopen=fake503)
check("a 5xx on refresh keeps the old cached verdict (a restart isn't a refusal), nothing rewritten, still active",
      out.get("status") == "active" and out.get("checked_at") == old_checked_at and written == {} and plus.active(cfg4, now=now))
raise SystemExit(report())
