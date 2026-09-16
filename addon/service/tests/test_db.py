from klausplus import db


def test_schema_and_month_keys(store, now):
    assert db.month_key(now) == "2026-09" and db.day_key(now) == "2026-09-16"
    assert db.month_key(db.next_month_start(now)) == "2026-10"


def test_customer_round_trip(store, now):
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    assert store.customer_by_stripe_id("cus_1")["id"] == cid
    assert store.upsert_customer("cus_1", "a@b.c", now) == cid  # idempotent
    store.set_key_hash(cid, "h" * 64, now)
    assert store.customer_by_hash("h" * 64)["email"] == "a@b.c"
    assert store.customer_by_id(cid)["key_rotated_at"] == now
    store.set_subscription("cus_1", "active", 1_800_000_000, False, now)
    row = store.customer_by_id(cid)
    assert row["status"] == "active" and row["period_end"] == 1_800_000_000


def test_set_key_hash_if_unset_is_the_atomic_mint_guard(store, now):
    """fix1/K-243, I-3: the conditional UPDATE is the proof a concurrency test would need."""
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    assert store.customer_by_id(cid)["key_hash"] is None
    assert store.set_key_hash_if_unset(cid, "first" * 12 + "1234", now) is True
    assert store.customer_by_id(cid)["key_hash"] == "first" * 12 + "1234"
    # a second mint attempt (the "someone else already won the race" case) is a no-op
    assert store.set_key_hash_if_unset(cid, "second" * 10 + "123456", now + 1) is False
    row = store.customer_by_id(cid)
    assert row["key_hash"] == "first" * 12 + "1234" and row["key_rotated_at"] == now


def test_usage_and_daily_audio(store, now):
    cid = store.upsert_customer("cus_2", "", now)
    assert store.usage(cid, "2026-09")["judge_tokens"] == 0
    assert store.add_usage(cid, "2026-09", "judge_tokens", 700) == 700
    assert store.add_usage(cid, "2026-09", "judge_tokens", 50) == 750
    assert store.usage(cid, "2026-10")["judge_tokens"] == 0
    assert store.add_daily_audio(cid, "2026-09-16", 90) == 90 and store.daily_audio(cid, "2026-09-16") == 90


def test_events_are_idempotent(store, now):
    assert store.record_event("evt_1", now) is True
    assert store.record_event("evt_1", now) is False
