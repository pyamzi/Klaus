from __future__ import annotations
import asyncio
import json
import re
import sys
import types
import httpx
import pytest
from fastapi.testclient import TestClient
from klausplus import billing, config, email, keys
from klausplus.app import create_app


class FakeStripe:
    """The four calls billing makes, recorded; shaped like the SDK's objects (attribute access)."""

    def __init__(self):
        self.created = []
        self.api_key = None
        self.api_version = None
        self.checkout = types.SimpleNamespace(Session=types.SimpleNamespace(create=self._create_session, retrieve=self._retrieve))
        self.billing_portal = types.SimpleNamespace(Session=types.SimpleNamespace(create=self._portal))
        self.session = {"id": "cs_1", "payment_status": "paid", "customer": "cus_1",
                        "customer_details": {"email": "a@b.c"},
                        "subscription": {"id": "sub_1", "status": "active", "current_period_end": 1_900_000_000,
                                         "cancel_at_period_end": False, "customer": "cus_1"}}

    def _create_session(self, **kw):
        self.created.append(kw)
        return types.SimpleNamespace(url="https://checkout.stripe.test/cs_1")

    def _retrieve(self, sid, expand=None):
        assert sid == "cs_1" and "subscription" in (expand or [])
        return _Obj(self.session)

    def _portal(self, **kw):
        self.created.append(("portal", kw))
        return types.SimpleNamespace(url="https://portal.stripe.test/p")


class _Obj(dict):
    """Stripe objects allow both obj.key and obj['key']."""
    def __getattr__(self, k):
        v = self[k]
        return _Obj(v) if isinstance(v, dict) else v


@pytest.fixture
def world(settings, now, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(billing, "_stripe", lambda s: fake)
    sent = []
    monkeypatch.setattr(email, "_post", lambda settings, payload: sent.append(payload) or True)
    app = create_app(settings, upstream=object(), now=lambda: now)
    return {"app": app, "client": TestClient(app), "stripe": fake, "sent": sent, "store": app.state.store}


def test_subscribe_redirects_to_checkout_with_the_right_price(world, settings):
    r = world["client"].get("/subscribe?plan=yearly", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://checkout.stripe.test/cs_1"
    kw = world["stripe"].created[0]
    assert kw["mode"] == "subscription" and kw["line_items"] == [{"price": "price_y", "quantity": 1}]
    assert kw["success_url"] == "https://klaus.test/welcome?session_id={CHECKOUT_SESSION_ID}"
    world["client"].get("/subscribe", follow_redirects=False)
    assert world["stripe"].created[1]["line_items"][0]["price"] == "price_m"


def test_welcome_mints_once_shows_once_and_emails(world, settings):
    r = world["client"].get("/welcome?session_id=cs_1")
    assert r.status_code == 200 and "kp_" in r.text
    row = world["store"].customer_by_stripe_id("cus_1")
    assert row["status"] == "active" and row["period_end"] == 1_900_000_000 and row["key_hash"]
    key = re.search(r"kp_[0-9a-f]{32}", r.text).group(0)
    assert keys.hash_key(key) == row["key_hash"]
    assert not settings.email_enabled and "no email was sent" in r.text.lower() and world["sent"] == []
    r2 = world["client"].get("/welcome?session_id=cs_1")
    assert r2.status_code == 200 and "kp_" not in r2.text and "already" in r2.text.lower()


def test_welcome_emails_when_enabled(world, settings):
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    r = world["client"].get("/welcome?session_id=cs_1")
    assert r.status_code == 200 and len(world["sent"]) == 1
    assert world["sent"][0]["to"] == ["a@b.c"] and "kp_" in world["sent"][0]["html"]


def test_welcome_unpaid_session_is_refused(world):
    world["stripe"].session["payment_status"] = "unpaid"
    assert world["client"].get("/welcome?session_id=cs_1").status_code == 402


def test_webhook_verifies_and_applies_once(world, monkeypatch, now):
    events = [{"id": "evt_1", "type": "customer.subscription.updated",
               "data": {"object": {"customer": "cus_9", "status": "active", "current_period_end": int(now) + 86400}}}]
    monkeypatch.setattr(billing, "_construct_event", lambda payload, sig, secret: events[0])
    r = world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200 and world["store"].customer_by_stripe_id("cus_9")["status"] == "active"
    events[0]["data"]["object"]["status"] = "canceled"
    r = world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200 and world["store"].customer_by_stripe_id("cus_9")["status"] == "active"  # replay ignored


def test_webhook_bad_signature_400(world, monkeypatch):
    def boom(payload, sig, secret):
        raise ValueError("bad sig")
    monkeypatch.setattr(billing, "_construct_event", boom)
    assert world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"}).status_code == 400


def test_portal_needs_a_key_and_returns_a_url(world, now):
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    key = keys.mint()
    world["store"].set_key_hash(cid, keys.hash_key(key), now)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    h = {"Authorization": f"Bearer {key}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/portal", headers=h).json() == {"url": "https://portal.stripe.test/p"}
    assert world["client"].post("/v1/portal", headers={"Authorization": "Bearer kp_" + "1" * 32, "X-Klaus-Client": "0.2.0"}).status_code == 401
    assert world["stripe"].created[-1][1]["customer"] == "cus_1"


def test_recover_rotates_the_key_and_never_enumerates(world, settings, now):
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    # rotated well outside the fix1 cooldown window, or this recover() call would be a no-op
    world["store"].set_key_hash(cid, "old" * 21 + "x", now - billing.RECOVER_COOLDOWN_S - 1)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    r = world["client"].post("/recover", data={"email": "A@B.C"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    new_hash = world["store"].customer_by_id(cid)["key_hash"]
    assert new_hash != "old" * 21 + "x" and len(world["sent"]) == 1
    r = world["client"].post("/recover", data={"email": "nobody@x.y"})
    assert r.status_code == 200 and "on its way" in r.text.lower() and len(world["sent"]) == 1


def test_landing_links(world):
    t = world["client"].get("/").text
    assert "/subscribe?plan=monthly" in t and "/subscribe?plan=yearly" in t and "/terms" in t and "/privacy" in t


def test_email_disabled_without_sender(settings):
    assert not email.enabled(settings)
    assert email.send(settings, "a@b.c", "s", "<p>x</p>") is False


def test_recover_pages_never_promise_an_email_that_cannot_be_sent(world, settings):
    # M-6: with email off, the form and done pages must say recovery is by email
    # to the operator, and must never say "sent" or "inbox" -- nothing is sent.
    assert not settings.email_enabled
    form = world["client"].get("/recover").text
    assert "sent" not in form.lower() and "inbox" not in form.lower()
    assert settings.operator_email in form
    done = world["client"].post("/recover", data={"email": "nobody@x.y"}).text
    assert "sent" not in done.lower() and "inbox" not in done.lower() and "on its way" not in done.lower()
    assert settings.operator_email in done


# --- fix round 1 (K-243) -----------------------------------------------------


def test_welcome_loses_the_mint_race_shows_already_issued_and_never_emails(world, monkeypatch):
    """I-3: simulate the TOCTOU window between the read and the atomic write —
    set_key_hash_if_unset says someone else already won, so the freshly minted
    key must be discarded: never shown, never emailed."""
    monkeypatch.setattr(world["store"], "set_key_hash_if_unset", lambda *a, **k: False)
    r = world["client"].get("/welcome?session_id=cs_1")
    assert r.status_code == 200 and "kp_" not in r.text and "already" in r.text.lower()
    assert world["sent"] == []
    assert world["store"].customer_by_stripe_id("cus_1")["key_hash"] is None


def test_recover_does_not_rotate_when_the_email_send_fails(world, settings, now, monkeypatch):
    """I-4: a Resend failure must leave the old key authenticating."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    old = "old" * 21 + "x"
    world["store"].set_key_hash(cid, old, now - billing.RECOVER_COOLDOWN_S - 1)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    monkeypatch.setattr(email, "send_key_email", lambda *a, **k: False)
    r = world["client"].post("/recover", data={"email": "a@b.c"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    assert world["store"].customer_by_id(cid)["key_hash"] == old


def _recoverable(world, settings, now, rotated_at=None):
    """An active customer with a key older than the cooldown, on a world that can send email."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    world["store"].set_key_hash(cid, "old" * 21 + "x",
                                now - billing.RECOVER_COOLDOWN_S - 1 if rotated_at is None else rotated_at)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    return cid


def test_two_recovers_in_flight_rotate_once_and_the_emailed_key_is_the_live_one(world, settings, now, monkeypatch):
    """K-271: the second request arrives while the first is still inside `send_key_email`
    (a real window — the send runs off the event loop). Both used to pass the cooldown,
    both minted, and the LAST `set_key_hash` won: the key in the first email was dead."""
    cid = _recoverable(world, settings, now)
    sent = []

    def send(s, to, key):
        sent.append(key)
        if len(sent) == 1:  # a second request, on its own loop and thread, lands mid-send
            TestClient(world["app"]).post("/recover", data={"email": "a@b.c"})
        return True

    monkeypatch.setattr(email, "send_key_email", send)
    r = TestClient(world["app"]).post("/recover", data={"email": "a@b.c"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    assert len(sent) == 1, "the loser must mint nothing and send nothing"
    assert world["store"].customer_by_id(cid)["key_hash"] == keys.hash_key(sent[0])


def test_a_failed_delivery_releases_the_recovery_window(world, settings, now, monkeypatch):
    """K-271: the window is claimed BEFORE the send (that is what makes it atomic), so a
    send that fails must hand it back — or an email that never arrived costs the customer
    an hour. The 'delivered before rotated' rule is unchanged: the old key still works."""
    cid = _recoverable(world, settings, now)
    old = world["store"].customer_by_id(cid)["key_hash"]
    monkeypatch.setattr(email, "send_key_email", lambda *a, **k: False)
    world["client"].post("/recover", data={"email": "a@b.c"})
    assert world["store"].customer_by_id(cid)["key_hash"] == old
    sent = []
    monkeypatch.setattr(email, "send_key_email", lambda s, to, key: sent.append(key) or True)
    world["client"].post("/recover", data={"email": "a@b.c"})  # immediately, not an hour later
    assert len(sent) == 1
    assert world["store"].customer_by_id(cid)["key_hash"] == keys.hash_key(sent[0])


def test_recover_throttled_by_ip_rotates_the_key_at_most_once(world, settings, now):
    """C-2: 25 POSTs for one known active email must still rotate exactly once."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    old = "old" * 21 + "x"
    world["store"].set_key_hash(cid, old, now - billing.RECOVER_COOLDOWN_S - 1)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    for _ in range(25):
        r = world["client"].post("/recover", data={"email": "a@b.c"})
        assert r.status_code == 200 and "on its way" in r.text.lower()
    assert len(world["sent"]) == 1
    assert world["store"].customer_by_id(cid)["key_hash"] != old


def test_recover_response_bytes_identical_across_every_case(world, settings, now):
    """C-2: unknown / inactive / active / cooled-down / throttled must be byte-identical."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    active_cid = world["store"].upsert_customer("cus_active", "active@x.y", now)
    world["store"].set_key_hash(active_cid, "a" * 63 + "1", now - billing.RECOVER_COOLDOWN_S - 1)
    world["store"].set_subscription("cus_active", "active", int(now) + 86400, False, now)
    inactive_cid = world["store"].upsert_customer("cus_inactive", "inactive@x.y", now)
    world["store"].set_key_hash(inactive_cid, "b" * 63 + "1", now)
    world["store"].set_subscription("cus_inactive", "canceled", int(now) - 86400, False, now)

    unknown = world["client"].post("/recover", data={"email": "nobody@x.y"})
    inactive = world["client"].post("/recover", data={"email": "inactive@x.y"})
    active = world["client"].post("/recover", data={"email": "active@x.y"})   # rotates + sends
    cooled = world["client"].post("/recover", data={"email": "active@x.y"})  # cooldown: no-op
    throttled = None
    for _ in range(10):
        throttled = world["client"].post("/recover", data={"email": "active@x.y"})

    bodies = {unknown.content, inactive.content, active.content, cooled.content, throttled.content}
    assert len(bodies) == 1
    assert all(r.status_code == 200 for r in (unknown, inactive, active, cooled, throttled))
    assert len(world["sent"]) == 1


def test_webhook_oversized_body_is_413_before_verification(world, monkeypatch):
    """I-2: a declared 5MB+ webhook body is refused before it is buffered or verified."""
    called = []
    monkeypatch.setattr(billing, "_construct_event",
                        lambda *a: called.append(1) or {"id": "x", "type": "invoice.paid", "data": {"object": {}}})

    async def probe():
        transport = httpx.ASGITransport(app=world["app"], raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = {"stripe-signature": "t=1,v1=x", "content-length": str(6 * 1024 * 1024)}
            req = ac.build_request("POST", "/stripe/webhook", content=b"{}", headers=headers)
            return await ac.send(req)

    r = asyncio.run(probe())
    assert r.status_code == 413
    assert called == []


def test_webhook_chunked_oversized_body_is_413_before_verification(world, monkeypatch):
    """K-262: a chunked webhook declares no Content-Length, so only a capped stream read
    can refuse it -- still before the payload is buffered or the signature looked at."""
    called = []
    monkeypatch.setattr(billing, "_construct_event",
                        lambda *a: called.append(1) or {"id": "x", "type": "invoice.paid", "data": {"object": {}}})

    def body():
        for _ in range(6):
            yield b"x" * (1024 * 1024)

    r = world["client"].post("/stripe/webhook", content=body(), headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 413
    assert called == []


def test_recover_oversized_body_is_413_before_reading(world):
    """I-2: same cap on /recover's form body."""
    async def probe():
        transport = httpx.ASGITransport(app=world["app"], raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = {"content-type": "application/x-www-form-urlencoded", "content-length": str(6 * 1024 * 1024)}
            req = ac.build_request("POST", "/recover", content=b"email=a@b.c", headers=headers)
            return await ac.send(req)

    r = asyncio.run(probe())
    assert r.status_code == 413


# --- the review's four pins, verbatim (task-4-review.md) --------------------


def test_recover_refuses_an_inactive_customer_without_saying_so(world, settings, now):
    """A known email whose subscription has ended: identical page, old hash kept, no email."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_dead", "gone@x.y", now)
    old = "old" * 21 + "x"
    # round2: stamped outside the cooldown window, or the cooldown clause alone masks
    # a dropped verdict guard (M3) — this pin must exercise the verdict check itself.
    world["store"].set_key_hash(cid, old, now - billing.RECOVER_COOLDOWN_S - 1)
    world["store"].set_subscription("cus_dead", "canceled", int(now) - 86400, False, now)
    r = world["client"].post("/recover", data={"email": "gone@x.y"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    assert world["store"].customer_by_id(cid)["key_hash"] == old
    assert world["sent"] == []


def test_webhook_bad_signature_records_nothing(world, monkeypatch, now):
    def boom(payload, sig, secret):
        raise ValueError("bad sig")
    monkeypatch.setattr(billing, "_construct_event", boom)
    body = json.dumps({"id": "evt_forged", "type": "customer.subscription.updated",
                       "data": {"object": {"customer": "cus_forged", "status": "active",
                                           "current_period_end": int(now) + 86400}}}).encode()
    r = world["client"].post("/stripe/webhook", content=body, headers={"stripe-signature": "x"})
    assert r.status_code == 400
    assert world["store"].customer_by_stripe_id("cus_forged") is None


def test_portal_opens_a_session_for_the_authenticated_customer_only(world, now):
    other = world["store"].upsert_customer("cus_other", "other@x.y", now)
    world["store"].set_key_hash(other, keys.hash_key(keys.mint()), now)
    world["store"].set_subscription("cus_other", "active", int(now) + 86400, False, now)
    mine = world["store"].upsert_customer("cus_mine", "me@x.y", now)
    key = keys.mint()
    world["store"].set_key_hash(mine, keys.hash_key(key), now)
    world["store"].set_subscription("cus_mine", "active", int(now) + 86400, False, now)
    r = world["client"].post("/v1/portal", headers={"Authorization": f"Bearer {key}", "X-Klaus-Client": "0.2.0"})
    assert r.status_code == 200
    assert world["stripe"].created[-1][1]["customer"] == "cus_mine"
    # C-1 fix1: a lapsed customer (canceled, past period_end -> verdict refused) must still
    # reach the portal, for THEIR OWN stripe customer id.
    lapsed = world["store"].upsert_customer("cus_lapsed", "lapsed@x.y", now)
    lapsed_key = keys.mint()
    world["store"].set_key_hash(lapsed, keys.hash_key(lapsed_key), now)
    world["store"].set_subscription("cus_lapsed", "canceled", int(now) - 86400, False, now)
    r = world["client"].post("/v1/portal", headers={"Authorization": f"Bearer {lapsed_key}", "X-Klaus-Client": "0.2.0"})
    assert r.status_code == 200
    assert world["stripe"].created[-1][1]["customer"] == "cus_lapsed"
    # an unknown key is still 401
    r = world["client"].post("/v1/portal", headers={"Authorization": "Bearer kp_" + "1" * 32, "X-Klaus-Client": "0.2.0"})
    assert r.status_code == 401


def test_stripe_seam_sets_the_key_and_pins_the_api_version(settings, monkeypatch):
    fake = types.ModuleType("stripe")
    monkeypatch.setitem(sys.modules, "stripe", fake)
    got = billing._stripe(settings)
    assert got is fake
    assert fake.api_key == settings.stripe_secret_key
    assert fake.api_version == config.STRIPE_API_VERSION == "2024-06-20"


# --- fix round 2 (task-4-fix1-review.md) ------------------------------------


def test_recover_ip_limiter_blocks_a_burst_of_different_emails(world, settings, now):
    """C-2: the per-IP limiter must do its own job, independent of the per-customer
    cooldown — proven with a FRESH customer/email per POST (so the cooldown clock can
    never be what blocks the 6th) all from the SAME caller IP; a different IP is a
    different bucket and is not blocked."""
    world["app"].state.settings = settings.__class__(
        **{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    for i in range(6):
        cid = world["store"].upsert_customer(f"cus_ip{i}", f"user{i}@x.y", now)
        world["store"].set_key_hash(cid, keys.hash_key(keys.mint()), now - billing.RECOVER_COOLDOWN_S - 1)
        world["store"].set_subscription(f"cus_ip{i}", "active", int(now) + 86400, False, now)
    for i in range(5):
        r = world["client"].post("/recover", data={"email": f"user{i}@x.y"})
        assert r.status_code == 200 and "on its way" in r.text.lower()
    assert len(world["sent"]) == 5
    # 6th distinct email, same caller IP within the window: the limiter alone blocks it —
    # no mint, no email — even though this customer is unquestionably eligible otherwise.
    hash_before = world["store"].customer_by_email("user5@x.y")["key_hash"]
    r = world["client"].post("/recover", data={"email": "user5@x.y"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    assert len(world["sent"]) == 5
    assert world["store"].customer_by_email("user5@x.y")["key_hash"] == hash_before
    # a different caller IP is a different bucket: still allowed
    r = world["client"].post("/recover", data={"email": "user5@x.y"}, headers={"fly-client-ip": "9.9.9.9"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    assert len(world["sent"]) == 6
    assert world["store"].customer_by_email("user5@x.y")["key_hash"] != hash_before
