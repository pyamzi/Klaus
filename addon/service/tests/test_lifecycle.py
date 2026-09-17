"""K-263: the retention purge the published privacy policy promises.

`templates.py` tells every subscriber two things: usage counters are kept
for 13 months, and the customer record is deleted 30 days after the
subscription ends. Nothing deleted anything until this card. These are the
pins that keep the promise true — plus the periodic task that runs it, which
must never take the service down when it fails.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from klausplus import app as app_mod
from klausplus.app import create_app
from klausplus.config import Settings

DAY = 86400


def test_retention_windows_are_settings_with_the_policy_defaults(monkeypatch):
    d = Settings()
    assert (d.retention_usage_days, d.retention_customer_grace_days) == (395, 30)
    monkeypatch.setenv("RETENTION_USAGE_DAYS", "40")
    monkeypatch.setenv("RETENTION_CUSTOMER_GRACE_DAYS", "7")
    s = Settings.from_env()
    assert (s.retention_usage_days, s.retention_customer_grace_days) == (40, 7)
    monkeypatch.setenv("RETENTION_USAGE_DAYS", "not a number")
    assert Settings.from_env().retention_usage_days == d.retention_usage_days


def test_rows_older_than_the_window_go_and_younger_ones_stay(store, now):
    cid = store.upsert_customer("cus_live", "", now)
    store.set_subscription("cus_live", "active", int(now) + 30 * DAY, False, now)
    # months and days far from the cutoff on purpose: the keys are UTC strings and
    # the fixture clock is local, so a boundary month would be timezone-dependent.
    store.add_usage(cid, "2025-06", "judge_tokens", 10)
    store.add_usage(cid, "2026-09", "judge_tokens", 10)
    store.add_daily_audio(cid, "2025-06-01", 60)
    store.add_daily_audio(cid, "2026-09-16", 60)
    store.record_event("evt_old", now - 400 * DAY)
    store.record_event("evt_new", now - 10 * DAY)

    counts = store.purge_expired(now, usage_days=395, customer_grace_days=30)

    assert counts == {"usage": 1, "daily_audio": 1, "events": 1, "customers": 0}
    assert store.usage(cid, "2025-06")["judge_tokens"] == 0
    assert store.usage(cid, "2026-09")["judge_tokens"] == 10
    assert store.daily_audio(cid, "2025-06-01") == 0
    assert store.daily_audio(cid, "2026-09-16") == 60
    # the id is free again = the ledger row went; the recent one is still refused as a replay
    assert store.record_event("evt_old", now) is True
    assert store.record_event("evt_new", now) is False


def test_an_active_customer_is_never_deleted_even_with_ancient_rows(store, now):
    cid = store.upsert_customer("cus_live", "", now - 900 * DAY)
    # period_end long past AND a stale row: the verdict would refuse this one, and
    # the purge must still not delete it — only Stripe ends a subscription.
    store.set_subscription("cus_live", "active", int(now) - 400 * DAY, False, now - 400 * DAY)
    store.add_usage(cid, "2026-09", "judge_tokens", 5)
    assert store.purge_expired(now, usage_days=395, customer_grace_days=30)["customers"] == 0
    assert store.customer_by_stripe_id("cus_live") is not None
    assert store.usage(cid, "2026-09")["judge_tokens"] == 5


def test_trialing_and_past_due_within_grace_survive(store, now):
    store.upsert_customer("cus_trial", "", now - 900 * DAY)
    store.set_subscription("cus_trial", "trialing", 0, False, now - 900 * DAY)
    store.upsert_customer("cus_pd", "", now - 900 * DAY)
    store.mark_past_due("cus_pd", now - 2 * DAY)
    assert store.purge_expired(now, usage_days=395, customer_grace_days=30)["customers"] == 0
    assert store.customer_by_stripe_id("cus_trial") is not None
    assert store.customer_by_stripe_id("cus_pd") is not None


def test_a_cancelled_customer_past_grace_goes_with_all_its_rows(store, now):
    gone = store.upsert_customer("cus_gone", "", now - 400 * DAY)
    store.set_subscription("cus_gone", "canceled", int(now) - 45 * DAY, False, now - 45 * DAY)
    store.set_key_hash(gone, "h" * 64, now - 400 * DAY)
    store.add_usage(gone, "2026-09", "judge_tokens", 7)
    store.add_daily_audio(gone, "2026-09-16", 30)
    kept = store.upsert_customer("cus_recent", "", now - 400 * DAY)
    store.set_subscription("cus_recent", "canceled", int(now) - 5 * DAY, False, now - 5 * DAY)
    store.add_usage(kept, "2026-09", "judge_tokens", 3)

    counts = store.purge_expired(now, usage_days=395, customer_grace_days=30)

    assert counts == {"usage": 1, "daily_audio": 1, "events": 0, "customers": 1}
    assert store.customer_by_stripe_id("cus_gone") is None
    assert store.customer_by_hash("h" * 64) is None
    assert store.usage(gone, "2026-09")["judge_tokens"] == 0
    assert store.daily_audio(gone, "2026-09-16") == 0
    assert store.customer_by_stripe_id("cus_recent") is not None
    assert store.usage(kept, "2026-09")["judge_tokens"] == 3


def test_a_customer_that_never_subscribed_counts_from_its_creation(store, now):
    store.upsert_customer("cus_stale", "", now - 40 * DAY)
    store.upsert_customer("cus_fresh", "", now - 5 * DAY)
    assert store.purge_expired(now, usage_days=395, customer_grace_days=30)["customers"] == 1
    assert store.customer_by_stripe_id("cus_stale") is None
    assert store.customer_by_stripe_id("cus_fresh") is not None


def test_the_periodic_task_purges_at_startup_then_waits_a_day(settings, now, monkeypatch):
    app = create_app(settings, upstream=object(), now=lambda: now)
    seen = []
    monkeypatch.setattr(app_mod, "purge_once", seen.append)

    async def drive():
        task = asyncio.create_task(app_mod._purge_loop(app))
        for _ in range(100):  # bounded: a bare sleep(0) does not guarantee the task a turn
            if seen:
                break
            await asyncio.sleep(0.01)
        task.cancel()  # long before PURGE_INTERVAL_S: if the loop slept first, `seen` is empty
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert seen == [app]
    assert app_mod.PURGE_INTERVAL_S == 24 * 3600


def test_purge_once_logs_the_counts_and_a_failure_never_raises(settings, now, caplog):
    app = create_app(settings, upstream=object(), now=lambda: now)
    app.state.store.upsert_customer("cus_stale", "", now - 400 * DAY)
    with caplog.at_level(logging.INFO, logger="klausplus"):
        app_mod.purge_once(app)
    line = "\n".join(r.getMessage() for r in caplog.records)
    assert "purge" in line and "customers=1" in line

    class Boom:
        def purge_expired(self, *a, **k):
            raise RuntimeError("disk gone")

    app.state.store = Boom()
    app_mod.purge_once(app)  # a broken purge must never take the service down
