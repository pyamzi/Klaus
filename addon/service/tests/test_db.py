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
