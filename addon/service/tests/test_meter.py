from klausplus import meter
from klausplus.db import next_month_start


def test_caps_come_from_settings(settings):
    assert meter.caps(settings) == {"embed": 20_000_000, "transcribe": 108_000, "judge": 750_000, "assistant": 1_200_000}


def test_check_and_charge_against_month(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    ok, remaining = meter.check(store, settings, cid, "judge", 749_999, now)
    assert ok and remaining == 750_000
    snap = meter.charge(store, settings, cid, "judge", 749_999, now)
    assert snap["counters"]["judge"]["used"] == 749_999 and snap["crossed_80"] == ["judge"]
    assert meter.check(store, settings, cid, "judge", 2, now) == (False, 1)
    assert meter.check(store, settings, cid, "judge", 2, next_month_start(now) + 1) == (True, 750_000)


def test_crossed_80_fires_once(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.charge(store, settings, cid, "assistant", 900_000, now)["crossed_80"] == []
    assert meter.charge(store, settings, cid, "assistant", 100_000, now)["crossed_80"] == ["assistant"]
    assert meter.charge(store, settings, cid, "assistant", 10, now)["crossed_80"] == []


def test_snapshot_human_units_and_reset(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    meter.charge(store, settings, cid, "transcribe", 7200, now)
    meter.charge(store, settings, cid, "judge", 2500, now)
    snap = meter.snapshot(store, settings, cid, now)
    assert snap["month"] == "2026-09" and snap["resets_at"] == next_month_start(now)
    assert snap["human"]["lecture_hours"] == [2.0, 30.0]
    assert snap["human"]["cards"] == [10, 3000] and snap["human"]["turns"] == [0, 200]


def test_daily_audio_cap(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.check_daily_audio(store, settings, cid, 240 * 60, now)
    store.add_daily_audio(cid, "2026-09-16", 240 * 60)
    assert not meter.check_daily_audio(store, settings, cid, 1, now)
    assert meter.check_daily_audio(store, settings, cid, 1, now + 86400)


def test_quota_message_names_the_reset():
    msg = meter.quota_message("transcribe", next_month_start(0))
    assert "lecture hours" in msg and "1970-02-01" in msg
