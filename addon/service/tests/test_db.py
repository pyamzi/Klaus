import importlib.util
import re
from pathlib import Path

from klausplus import db, keys


def _load_mint_key():
    """I-4: load scripts/mint_key.py by path -- it is a standalone operator
    script, not a package under klausplus, so there is nothing to import it as."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "mint_key.py"
    spec = importlib.util.spec_from_file_location("mint_key", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_mint_key_issues_a_working_key_for_a_known_customer(store, settings, now, monkeypatch, capsys):
    # I-4: the operator's scripted remedy when a paid customer never reached
    # /welcome -- the key it prints must be the one that then authenticates.
    cid = store.upsert_customer("cus_lost", "lost@x.y", now)
    monkeypatch.setenv("DATABASE_PATH", settings.database_path)
    rc = _load_mint_key().main(["cus_lost"])
    assert rc == 0
    out = capsys.readouterr().out
    m = re.search(r"kp_[0-9a-f]{32}", out)
    assert m, out
    assert store.customer_by_id(cid)["key_hash"] == keys.hash_key(m.group(0))


def test_mint_key_refuses_an_unknown_customer_and_prints_no_key(settings, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_PATH", settings.database_path)
    rc = _load_mint_key().main(["cus_ghost"])
    assert rc != 0
    assert "kp_" not in capsys.readouterr().out


def test_claim_event_created_refuses_older_and_takes_equal_or_newer(store, now):
    """K-263: the compare-and-set behind entitlement's ordering guard."""
    store.upsert_customer("cus_1", "", now)
    assert store.customer_by_stripe_id("cus_1")["last_event_created"] is None
    assert store.claim_event_created("cus_1", 500) is True
    assert store.claim_event_created("cus_1", 499) is False
    assert store.claim_event_created("cus_1", 500) is True   # equal applies (a replay of the same stamp)
    assert store.claim_event_created("cus_1", 501) is True
    assert store.customer_by_stripe_id("cus_1")["last_event_created"] == 501


def test_last_event_created_migrates_onto_a_database_created_without_it(settings, now):
    """K-263: the volume already holds a database from an earlier deploy."""
    conn = db.connect(settings.database_path)
    conn.execute("INSERT INTO customers (stripe_customer_id, email, created_at, updated_at) "
                 "VALUES ('cus_old', 'a@b.c', 1, 1)")
    conn.execute("ALTER TABLE customers DROP COLUMN last_event_created")
    conn.close()

    store = db.Store(db.connect(settings.database_path))  # reopening runs the migration
    row = store.customer_by_stripe_id("cus_old")
    assert row["email"] == "a@b.c" and row["last_event_created"] is None
    assert store.claim_event_created("cus_old", 100) is True


def test_claim_recovery_is_won_by_exactly_one_caller_inside_the_window(store, now):
    """K-271: /recover checked the cooldown and rotated the key in two separate statements,
    so two requests in flight could both pass, both mint, and the key in the first email was
    dead on arrival. The window is claimed with ONE conditional UPDATE instead."""
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    assert store.claim_recovery(cid, now, 3600) is True           # never rotated: key_rotated_at IS NULL
    assert store.claim_recovery(cid, now + 1, 3600) is False      # the loser, inside the window
    assert store.customer_by_id(cid)["key_rotated_at"] == now     # and it wrote nothing
    assert store.claim_recovery(cid, now + 3601, 3600) is True    # the window has passed
    store.release_recovery(cid, now, now + 3601)                  # the email never went out
    assert store.customer_by_id(cid)["key_rotated_at"] == now
    assert store.claim_recovery(cid, now + 3601, 3600) is True    # so it is claimable again
    # K-271 review: a release is guarded by the stamp its own claim wrote — a send that
    # outlived a NEWER claim cannot roll that claim back
    store.release_recovery(cid, now, now + 3600)                  # stale stamp: not this claim's
    assert store.customer_by_id(cid)["key_rotated_at"] == now + 3601


def test_seed_subscription_if_unset_wins_once_and_never_overwrites_a_webhook(store, now):
    """K-277: /welcome may seed what the Checkout session says only while no webhook has
    written this row — one conditional UPDATE, the claim_recovery shape."""
    cid = store.upsert_customer("cus_1", "", now)
    assert store.customer_by_id(cid)["status"] == "incomplete"  # exactly what upsert_customer leaves
    assert store.seed_subscription_if_unset(cid, "active", int(now) + 86400, now) is True
    row = store.customer_by_id(cid)
    assert row["status"] == "active" and row["period_end"] == int(now) + 86400
    assert store.seed_subscription_if_unset(cid, "trialing", 5, now) is False
    row = store.customer_by_id(cid)
    assert row["status"] == "active" and row["period_end"] == int(now) + 86400  # the loser wrote nothing
    store.set_subscription("cus_1", "canceled", int(now), False, now)
    assert store.seed_subscription_if_unset(cid, "active", int(now) + 99, now) is False
    assert store.customer_by_id(cid)["status"] == "canceled"
