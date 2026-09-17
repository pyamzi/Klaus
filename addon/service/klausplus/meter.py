"""Quotas: reserve before forwarding, settle after; one snapshot shape everywhere."""
from __future__ import annotations

import threading
import time
from typing import NamedTuple

from .config import Settings, TOKENS_PER_CARD, TOKENS_PER_TURN
from .db import Store, day_key, month_key, next_month_start

PURPOSES = ("embed", "transcribe", "judge", "assistant")
COLUMN = {"embed": "embed_tokens", "transcribe": "audio_seconds", "judge": "judge_tokens", "assistant": "assistant_tokens"}
_HUMAN = {"transcribe": "lecture hours", "judge": "judged cards", "assistant": "assistant turns", "embed": "embedding tokens"}


def caps(settings: Settings) -> dict:
    return {"embed": settings.embed_ceiling_tokens, "transcribe": settings.quota_audio_seconds,
            "judge": settings.quota_judge_tokens, "assistant": settings.quota_assistant_tokens}


def check(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int, now: float) -> tuple[bool, int]:
    used = store.usage(customer_id, month_key(now))[COLUMN[purpose]]
    cap = caps(settings)[purpose]
    return used + max(0, int(amount)) <= cap, max(0, cap - used)


def check_daily_audio(store: Store, settings: Settings, customer_id: int, seconds: int, now: float) -> bool:
    return store.daily_audio(customer_id, day_key(now)) + max(0, int(seconds)) <= settings.audio_day_seconds


# K-262 (Codex P1): `check` is a READ and the charge only lands after the awaited
# provider call, so N concurrent requests for one customer all saw the same remaining
# quota and all passed. reserve() decides and records inside this one lock; settle()
# corrects it to the real usage afterwards.
# ponytail: one process-wide lock — the service is one Fly Machine with one process
# (the same premise RateLimiter is built on). Several workers would need the decision
# in SQL (`UPDATE ... WHERE col + ? <= cap`), which is a db.py change, not this one.
_lock = threading.RLock()


class Reservation(NamedTuple):
    """What `reserve` decided, and everything `settle` needs to undo it."""

    ok: bool
    before: dict
    """The snapshot the decision was read from — this reservation is NOT in it. That is
    what makes it the honest reading for a response whose headers must go out before the
    real usage is known (the SSE branch of /v1/messages)."""
    at: float
    """The clock the period keys were taken from. `settle` must be handed THIS, never a
    fresh `now` — see its docstring."""
    reason: str = ""
    """Which ceiling refused: "day" for the audio-per-day one, "month" for the monthly
    quota, "" when granted. The route turns it into that ceiling's own message."""


def reserve(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int,
            now: float) -> Reservation:
    """Take `amount` out of the quota up front, or refuse. The estimate is spent the
    moment it is granted, so the next request in flight sees it gone; `settle` gives
    back whatever was not used. Refusing records nothing.

    K-267: the per-day audio ceiling is decided HERE too, in the same lock and the same
    breath as the monthly one — `check_daily_audio` outside it let two concurrent uploads
    read the same daily total, both reserve, and push past the 240-minute cap, because
    this function then added to that counter without ever re-reading it. It is asked
    first, so a caller over both ceilings still hears about the one that lifts soonest."""
    amount = max(0, int(amount))
    with _lock:
        if purpose == "transcribe" and not check_daily_audio(store, settings, customer_id, amount, now):
            ok, reason = False, "day"
        else:
            ok, _remaining = check(store, settings, customer_id, purpose, amount, now)
            reason = "" if ok else "month"
        before = snapshot(store, settings, customer_id, now)
        if ok:
            store.add_usage(customer_id, month_key(now), COLUMN[purpose], amount)
            if purpose == "transcribe":
                store.add_daily_audio(customer_id, day_key(now), amount)
    return Reservation(ok, before, now, reason)


def settle(store: Store, settings: Settings, customer_id: int, purpose: str, reserved: int,
           actual: int, at: float) -> dict:
    """Adjust a reservation by `actual - reserved` — negative when the estimate was high,
    and `actual=0` releases it in full (an upstream failure, or anything but a 200).

    R2 (fix round 1): `at` is the reservation's OWN `Reservation.at`, not the clock now.
    A request can be admitted minutes before it settles (up to the upstream timeout), so a
    settle keyed on its own clock straddles a UTC month or audio-day boundary: it charges
    one period and releases out of the NEXT, where `check` reads the negative counter as
    spendable quota. A request bills entirely to the period that admitted it.

    `crossed_80` is measured over the WHOLE request (before = after - actual), never over
    the reservation, so a high estimate that briefly crossed the line and settled back
    under it sends no notice, and the notice still fires exactly once when it is owed."""
    reserved, actual = max(0, int(reserved)), max(0, int(actual))
    with _lock:
        after = store.add_usage(customer_id, month_key(at), COLUMN[purpose], actual - reserved)
        if purpose == "transcribe":
            store.add_daily_audio(customer_id, day_key(at), actual - reserved)
        snap = snapshot(store, settings, customer_id, at)
    line = 0.8 * caps(settings)[purpose]
    snap["crossed_80"] = [purpose] if after - actual < line <= after else []
    return snap


def charge(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int, now: float) -> dict:
    """A settle with nothing reserved — for a caller that never reserved. Nothing was
    admitted earlier, so the period that admitted it IS now."""
    return settle(store, settings, customer_id, purpose, 0, amount, now)


def snapshot(store: Store, settings: Settings, customer_id: int, now: float) -> dict:
    used = store.usage(customer_id, month_key(now))
    cap = caps(settings)
    counters = {p: {"used": used[COLUMN[p]], "cap": cap[p]} for p in PURPOSES}
    return {
        "month": month_key(now),
        "resets_at": next_month_start(now),
        "counters": counters,
        "human": {
            "lecture_hours": [round(used["audio_seconds"] / 3600, 1), round(cap["transcribe"] / 3600, 1)],
            "cards": [used["judge_tokens"] // TOKENS_PER_CARD, cap["judge"] // TOKENS_PER_CARD],
            "turns": [used["assistant_tokens"] // TOKENS_PER_TURN, cap["assistant"] // TOKENS_PER_TURN],
        },
    }


def quota_message(purpose: str, resets_at: float) -> str:
    day = time.strftime("%Y-%m-%d", time.gmtime(resets_at))
    return (f"Your Klaus Plus quota of {_HUMAN.get(purpose, purpose)} for this month is used up; "
            f"it resets on {day}. You can add your own API key under KlausMate Preferences meanwhile.")
