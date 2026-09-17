from klausplus import meter
from klausplus.db import day_key, month_key, next_month_start


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


# --- K-262 (Codex P1): reserve/settle, so concurrent turns cannot both fit ----


def test_reserve_is_atomic_so_two_in_flight_requests_cannot_both_fit(store, settings, now):
    """check-then-charge let N concurrent requests read the same remaining quota and all
    pass, because the charge only landed after the awaited provider call. A reservation
    records the estimate inside the same lock that decided it."""
    cid = store.upsert_customer("cus_1", "", now)
    store.add_usage(cid, "2026-09", "judge_tokens", settings.quota_judge_tokens - 600)
    first = meter.reserve(store, settings, cid, "judge", 400, now)
    second = meter.reserve(store, settings, cid, "judge", 400, now)
    assert first.ok and not second.ok
    # `before` is the reading the decision was made on: the first reservation is in it,
    # the second (refused, and so never recorded) is not.
    assert second.before["counters"]["judge"]["used"] == settings.quota_judge_tokens - 200


def test_settle_adjusts_a_reservation_down_and_releases_it_in_full(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.reserve(store, settings, cid, "judge", 1000, now).ok
    assert meter.settle(store, settings, cid, "judge", 1000, 120, now)["counters"]["judge"]["used"] == 120
    assert meter.reserve(store, settings, cid, "assistant", 5000, now).ok
    assert meter.settle(store, settings, cid, "assistant", 5000, 0, now)["counters"]["assistant"]["used"] == 0


def test_reserve_and_settle_carry_the_daily_audio_counter_too(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.reserve(store, settings, cid, "transcribe", 300, now).ok
    assert store.daily_audio(cid, "2026-09-16") == 300
    meter.settle(store, settings, cid, "transcribe", 300, 0, now)
    assert store.daily_audio(cid, "2026-09-16") == 0


def test_settle_crosses_80_over_the_whole_request_never_the_reservation(store, settings, now):
    """The notice is owed on what was really used: a high estimate that briefly pushed the
    counter past the line and then settled back under it is not a crossing."""
    cid = store.upsert_customer("cus_1", "", now)
    store.add_usage(cid, "2026-09", "judge_tokens", int(settings.quota_judge_tokens * 0.8) - 10)
    assert meter.reserve(store, settings, cid, "judge", 100, now).ok
    assert meter.settle(store, settings, cid, "judge", 100, 5, now)["crossed_80"] == []
    assert meter.reserve(store, settings, cid, "judge", 100, now).ok
    assert meter.settle(store, settings, cid, "judge", 100, 100, now)["crossed_80"] == ["judge"]


def test_a_reservation_settles_into_the_period_that_admitted_it(store, settings, now):
    """R2 (fix round 1): `settle` adjusts the month (and audio day) `reserve` recorded under,
    which it hands back as `at` — never whatever period the clock has reached by then."""
    cid = store.upsert_customer("cus_1", "", now)
    eve = next_month_start(now) - 1  # 23:59:59 UTC on the last day of the month
    res = meter.reserve(store, settings, cid, "judge", 4000, eve)
    assert res.ok and res.at == eve
    meter.settle(store, settings, cid, "judge", 4000, 125, res.at)
    assert store.usage(cid, month_key(eve))["judge_tokens"] == 125
    assert store.usage(cid, month_key(eve + 61))["judge_tokens"] == 0
    res = meter.reserve(store, settings, cid, "transcribe", 300, eve)
    meter.settle(store, settings, cid, "transcribe", 300, 30, res.at)
    assert store.daily_audio(cid, day_key(eve)) == 30
    assert store.daily_audio(cid, day_key(eve + 61)) == 0
