"""Quotas: check before forwarding, charge after; one snapshot shape everywhere."""
from __future__ import annotations

import time

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


def charge(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int, now: float) -> dict:
    cap = caps(settings)[purpose]
    before = store.usage(customer_id, month_key(now))[COLUMN[purpose]]
    after = store.add_usage(customer_id, month_key(now), COLUMN[purpose], max(0, int(amount)))
    if purpose == "transcribe":
        store.add_daily_audio(customer_id, day_key(now), max(0, int(amount)))
    snap = snapshot(store, settings, customer_id, now)
    line = 0.8 * cap
    snap["crossed_80"] = [purpose] if before < line <= after else []
    return snap


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
