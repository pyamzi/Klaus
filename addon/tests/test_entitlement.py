"""Tests for entitlement — which tier a profile is on.

The module is advisory by design: the service is the real gate, so nothing
here can be "bypassed" in any meaningful sense. What these pin is that the
FALLBACK behaviour is the generous one, because the only person a stingy
local verdict can hurt is somebody who actually paid.

resolve() takes its clock and its fetcher, so every branch is reachable
without a network or a running Anki.
"""
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

ent = importlib.import_module("klausmate.entitlement")

NOW = 1_800_000_000.0
DAY = 86400.0
TOKEN = {"assistant_token": "tok"}


def _cached(tier, age_s, expires=0.0):
    return {
        "assistant_token": "tok",
        ent.CACHE_KEY: {
            "tier": tier,
            "checked_at": NOW - age_s,
            "expires_at": expires,
        },
    }


def _ok(tier="premium", expires=0.0):
    return lambda token: {"tier": tier, "expires_at": expires}


def _boom(exc=OSError("no network")):
    def fetch(token):
        raise exc
    return fetch


section("no token is simply free — no network, no ceremony")
_v = ent.resolve({}, now=NOW, fetch=_boom())
check("free without a token", _v.tier == ent.FREE and not _v.premium)
check("...and the fetcher is never called", _v.reason == "no token")
check("an empty token counts as none",
      ent.resolve({"assistant_token": "  "}, now=NOW, fetch=_boom()).reason
      == "no token")

section("a fresh cache answers without a round trip")
_v = ent.resolve(_cached("premium", 60), now=NOW, fetch=_boom())
check("a cache inside the TTL is used even when the network is down",
      _v.premium and _v.reason == "cached")
check("the TTL is hours, not seconds — this must not cost a round trip per "
      "panel open", ent.CHECK_TTL_S >= 3600)
_v = ent.resolve(_cached("premium", ent.CHECK_TTL_S + 1), now=NOW,
                 fetch=_ok("premium"))
check("a stale cache re-checks", _v.reason == "checked")

section("the service is authoritative when it answers")
check("premium is honoured",
      ent.resolve(TOKEN, now=NOW, fetch=_ok("premium")).premium)
check("free is honoured",
      not ent.resolve(TOKEN, now=NOW, fetch=_ok("free")).premium)
check("an unknown tier reads as free — guessing at a third word would "
      "invent an entitlement nobody granted",
      not ent.resolve(TOKEN, now=NOW, fetch=_ok("enterprise")).premium)
check("a premium answer whose end date has PASSED is not premium, even in "
      "the same breath",
      not ent.resolve(TOKEN, now=NOW,
                      fetch=_ok("premium", NOW - DAY)).premium)
check("...and says why", ent.resolve(TOKEN, now=NOW,
                                     fetch=_ok("premium", NOW - DAY)).reason
      == "expired")
check("a future end date is fine",
      ent.resolve(TOKEN, now=NOW, fetch=_ok("premium", NOW + DAY)).premium)
check("a junk expiry does not throw",
      ent.parse({"tier": "premium", "expires_at": "soon"}, NOW).premium)

section("a failed check falls back generously, on purpose")
_v = ent.resolve(_cached("premium", 2 * DAY), now=NOW, fetch=_boom())
check("a cached premium survives a failed check inside the grace window — "
      "losing paid features to bad wifi is a worse failure than briefly "
      "trusting a yes the service will refuse anyway",
      _v.premium and _v.stale)
check("...and is marked stale so the UI can say so", "check failed" in _v.reason)
_v = ent.resolve(_cached("premium", ent.GRACE_S + DAY), now=NOW, fetch=_boom())
check("but the grace window does end", not _v.premium and _v.stale)
check("grace is days, not minutes", ent.GRACE_S >= 86400)
_v = ent.resolve(TOKEN, now=NOW, fetch=_boom())
check("no cache and a failed check is free", not _v.premium and _v.stale)
_v = ent.resolve(_cached("free", 2 * DAY), now=NOW, fetch=_boom())
check("a cached FREE never becomes premium through a failure",
      not _v.premium)

section("resolve never raises")
for _exc in (OSError("down"), ValueError("bad json"), TypeError("nope"),
             KeyError("missing")):
    try:
        _v = ent.resolve(TOKEN, now=NOW, fetch=_boom(_exc))
        check(f"{type(_exc).__name__} degrades to free instead of raising",
              not _v.premium)
    except Exception as e:  # noqa: BLE001 — that is the whole point
        check(f"{type(_exc).__name__} degrades to free instead of raising",
              False, repr(e))

section("a corrupt cache is ignored, not fatal")
for _bad in ("nonsense", 42, {"tier": "wat"}, {"tier": "premium",
                                               "checked_at": "yesterday"}):
    _cfg = {"assistant_token": "tok", ent.CACHE_KEY: _bad}
    check(f"cache {_bad!r} is discarded", ent.from_cache(_cfg, NOW) is None
          or not ent.from_cache(_cfg, NOW).premium)
check("an expired cache short-circuits to free with no network at all",
      ent.from_cache(_cached("premium", DAY, expires=NOW - 1), NOW).reason
      == "expired")

section("the cache round-trips")
_v = ent.parse({"tier": "premium", "expires_at": NOW + DAY}, NOW)
_back = ent.from_cache({"assistant_token": "t", ent.CACHE_KEY: ent.to_cache(_v)},
                       NOW)
check("what to_cache writes, from_cache reads",
      _back.tier == _v.tier and _back.expires_at == _v.expires_at)
check("the stored form is plain and hand-editable — obfuscating it would "
      "imply it were a lock, and it is not",
      set(ent.to_cache(_v)) == {"tier", "checked_at", "expires_at"})

section("what the user is told")
check("free says it is using their own key",
      "own API key" in ent.describe(ent.Verdict(tier=ent.FREE)))
check("an ended subscription says so, not just 'free'",
      "ended" in ent.describe(ent.Verdict(tier=ent.FREE, reason="expired")))
check("a stale premium warns rather than claiming everything is fine — the "
      "user should hear it before a request fails in front of them",
      "could not re-check" in ent.describe(
          ent.Verdict(tier=ent.PREMIUM, stale=True)))
check("healthy premium is plain",
      ent.describe(ent.Verdict(tier=ent.PREMIUM))
      == "Premium — KlausMate provides the keys.")

section("tier chooses the BACKEND, it does not switch the feature off")
check("premium offers the hosted backend",
      ent.Verdict(tier=ent.PREMIUM).hosted_available())
check("free does not — but free still has both assistants via its own key, "
      "which is what llm_client.DirectBackend is for",
      not ent.Verdict(tier=ent.FREE).hosted_available())

section("shape")
_SRC = open("klausmate/entitlement.py").read()
_CODE = code_only(_SRC)
check("aqt-free", "import aqt" not in _CODE and "from aqt" not in _CODE)
check("llm_client is imported lazily, so the hosted base URL is read at "
      "call time and one test repoint covers both modules",
      "from . import llm_client" in _CODE
      and _CODE.index("def _fetch") < _CODE.index("from . import llm_client"))
check("the module says plainly that it cannot enforce anything",
      "advisory" in _SRC and "readable Python" in _SRC)

raise SystemExit(report())
