"""Which tier this profile is on, and how much to trust the answer.

**This module is advisory, and that is not a weakness — it is the design.**

An Anki add-on ships as readable Python. Any local check is one line from
being patched out, so nothing here can gate a paid feature and nothing here
tries to. The real gate is Klaus's service refusing a token: a forged
``premium`` in a config file buys exactly nothing, because the hosted
backend still answers 401.

That inverts the usual anxiety about caching. Because a generous local
verdict cannot be exploited, this can afford to be generous — honouring a
cached subscription through a flaky week rather than yanking features away
from somebody who paid. Being stingy here would only ever punish real
customers; it could not stop anybody else.

**Free is not crippled.** Free members bring their own API key and get both
assistants. Premium means Klaus's service holds the keys, so there is no key
to manage and no provider bill to reconcile. Tier decides the BACKEND, not
whether the feature exists — see ``llm_client``.

aqt-free and injectable: ``resolve`` takes its clock and its fetcher, so the
whole state machine is testable without a network or a running Anki.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

FREE = "free"
PREMIUM = "premium"
TIERS = (FREE, PREMIUM)

# How long a verdict is fresh before we ask again. Six hours: long enough
# that a session never spends time on this, short enough that a cancellation
# stops costing us within a day.
CHECK_TTL_S = 6 * 3600

# How long a cached PREMIUM survives when the check itself keeps failing.
# A week, because the alternative is a paying customer losing features
# because their café wifi is bad, and because a stale verdict cannot be
# abused — the service is still the thing that says yes.
GRACE_S = 7 * 86400

CHECK_TIMEOUT_S = 10.0
CACHE_KEY = "entitlement_cache"


@dataclass
class Verdict:
    tier: str = FREE
    checked_at: float = 0.0
    # Subscription end, as the service reported it. 0 means "not stated".
    expires_at: float = 0.0
    # True when this was served from cache after a check we could not make.
    stale: bool = False
    reason: str = ""

    @property
    def premium(self) -> bool:
        return self.tier == PREMIUM

    def hosted_available(self) -> bool:
        """Whether to OFFER the hosted backend. Not whether to allow it —
        that is the service's call, every request."""
        return self.premium


def _expired(verdict: Verdict, now: float) -> bool:
    return bool(verdict.expires_at) and verdict.expires_at <= now


def is_fresh(verdict: Verdict, now: float, ttl: float = CHECK_TTL_S) -> bool:
    return bool(verdict.checked_at) and (now - verdict.checked_at) < ttl


def parse(payload: dict, now: float) -> Verdict:
    """A verdict from the service's reply.

    Unknown tiers read as free. The service is authoritative about what it
    means, but this add-on only knows two words, and guessing at a third
    would be inventing an entitlement nobody granted.
    """
    payload = payload or {}
    tier = str(payload.get("tier") or "").strip().lower()
    if tier not in TIERS:
        tier = FREE
    try:
        expires = float(payload.get("expires_at") or 0.0)
    except (TypeError, ValueError):
        expires = 0.0
    verdict = Verdict(
        tier=tier, checked_at=now, expires_at=expires, reason="checked"
    )
    # A subscription the service itself says has ended is not premium, even
    # if it also said "premium" in the same breath.
    if verdict.premium and _expired(verdict, now):
        return Verdict(
            tier=FREE, checked_at=now, expires_at=expires, reason="expired"
        )
    return verdict


def from_cache(cfg: dict, now: float) -> Verdict | None:
    """The stored verdict, or None when there is nothing usable."""
    raw = (cfg or {}).get(CACHE_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        verdict = Verdict(
            tier=str(raw.get("tier") or FREE),
            checked_at=float(raw.get("checked_at") or 0.0),
            expires_at=float(raw.get("expires_at") or 0.0),
            reason="cached",
        )
    except (TypeError, ValueError):
        return None
    if verdict.tier not in TIERS:
        return None
    if verdict.premium and _expired(verdict, now):
        # An end date that has passed needs no network to act on.
        return Verdict(
            tier=FREE, checked_at=verdict.checked_at,
            expires_at=verdict.expires_at, reason="expired",
        )
    return verdict


def to_cache(verdict: Verdict) -> dict:
    """The dict a caller stores in config. Deliberately plain and
    hand-editable: obfuscating it would imply it were a lock, and it is
    not."""
    return {
        "tier": verdict.tier,
        "checked_at": float(verdict.checked_at),
        "expires_at": float(verdict.expires_at),
    }


def _fetch(token: str, timeout: float = CHECK_TIMEOUT_S) -> dict:
    """Ask the service. Reads llm_client.HOSTED_API_BASE at CALL time so a
    test repointing that one global covers this module too."""
    from . import llm_client

    req = urllib.request.Request(
        f"{llm_client.HOSTED_API_BASE}/v1/entitlement",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


def resolve(cfg: dict, now: float | None = None, fetch=None) -> Verdict:
    """The current tier, checking the service only when it is worth it.

    Order, and the reasoning for each step:

    1. **No token → free.** Nothing to check, and no network call to waste.
    2. **Fresh cache → use it.** Six hours without a round trip.
    3. **Ask the service.** The only authoritative answer.
    4. **Check failed → fall back.** A cached premium stands for GRACE_S,
       then lapses to free. Costing a paying customer their features because
       a request timed out is a worse failure than briefly trusting a stale
       yes that the service will refuse anyway.

    Never raises. A tier lookup that can throw would put a network error in
    front of somebody who only wanted to open a panel.
    """
    now = time.time() if now is None else float(now)
    cfg = cfg or {}
    token = str(cfg.get("assistant_token") or "").strip()
    if not token:
        return Verdict(tier=FREE, checked_at=now, reason="no token")

    cached = from_cache(cfg, now)
    if cached is not None and is_fresh(cached, now):
        return cached

    try:
        payload = (fetch or _fetch)(token)
        return parse(payload, now)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            ValueError, TypeError, KeyError) as exc:
        reason = f"check failed: {exc}"

    if cached is not None and cached.premium:
        if (now - cached.checked_at) < GRACE_S:
            return Verdict(
                tier=PREMIUM,
                checked_at=cached.checked_at,
                expires_at=cached.expires_at,
                stale=True,
                reason=reason + " (within grace)",
            )
        return Verdict(
            tier=FREE, checked_at=cached.checked_at,
            expires_at=cached.expires_at, stale=True,
            reason=reason + " (grace expired)",
        )
    return Verdict(tier=FREE, checked_at=0.0, stale=True, reason=reason)


def describe(verdict: Verdict) -> str:
    """One line for a settings row. Says when a verdict is stale, because a
    user seeing "Premium" while the service disagrees deserves the warning
    before a request fails in front of them."""
    if not verdict.premium:
        if verdict.reason == "expired":
            return "Subscription ended — using your own API key."
        if verdict.stale:
            return "Could not verify your subscription — using your own key."
        return "Free — using your own API key."
    if verdict.stale:
        return "Premium (could not re-check just now)."
    return "Premium — KlausMate provides the keys."
