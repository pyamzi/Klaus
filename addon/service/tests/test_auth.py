"""K-287: accounts (users/api_keys) — login, logout, and the emailed
password-reset flow that is the only way an account gets created.

/welcome and /recover are untouched by this feature (see test_billing.py)
and keep authenticating via customers.key_hash; these tests cover the new,
additive path through api_keys, and the one property the whole feature
exists for: signing in on a second device must not revoke the first.
"""
from __future__ import annotations

import re
import types

import pytest
from fastapi.testclient import TestClient

from klausplus import auth, billing, email, keys
from klausplus.app import create_app


@pytest.fixture
def world(settings, now, monkeypatch):
    sent = []
    monkeypatch.setattr(email, "_post", lambda settings, payload: sent.append(payload) or True)
    # /v1/portal (used below as a Stripe-free-except-here "does this key
    # authenticate" probe, same one test_billing.py's own tests use) still
    # calls Stripe for the portal URL itself -- fake just that one call.
    fake_stripe = types.SimpleNamespace(
        billing_portal=types.SimpleNamespace(
            Session=types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(url="https://portal.test/p"))))
    monkeypatch.setattr(billing, "_stripe", lambda s: fake_stripe)
    active_settings = settings.__class__(**{**settings.__dict__, "resend_api_key": "re_x",
                                            "resend_from": "Klaus <plus@klaus.test>"})
    app = create_app(active_settings, upstream=object(), now=lambda: now)
    return {"app": app, "client": TestClient(app), "sent": sent, "store": app.state.store, "settings": active_settings}


def _reset_url(sent: list) -> tuple[str, str]:
    """The token and email address from the last reset email sent."""
    html = sent[-1]["html"]
    m = re.search(r'href="([^"]+)"', html)
    return m.group(1), sent[-1]["to"][0]


def _set_password(world, now, email_addr: str = "a@b.c", password: str = "hunter2xx") -> int:
    """Full signup: a subscribed customer with no account yet sets one via
    the emailed reset link. Returns the customer id."""
    cid = world["store"].upsert_customer("cus_1", email_addr, now)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    r = world["client"].post("/forgot-password", data={"email": email_addr})
    assert r.status_code == 200 and len(world["sent"]) == 1
    url, _ = _reset_url(world["sent"])
    token = url.split("token=", 1)[1]
    r = world["client"].post("/reset-password", data={"token": token, "password": password})
    assert r.status_code == 200 and "password set" in r.text.lower()
    return cid


def test_reset_password_then_login_issues_a_working_key(world, now):
    _set_password(world, now)
    r = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "hunter2xx", "device": "klausmate"})
    assert r.status_code == 200
    key = r.json()["key"]
    assert keys.looks_like_key(key)
    # the key actually authenticates -- /v1/portal needs nothing but a recognised key
    h = {"Authorization": f"Bearer {key}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/portal", headers=h).status_code == 200


def test_login_wrong_password_and_unknown_email_both_401_generically(world, now):
    _set_password(world, now)
    bad_pw = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "nope"})
    unknown = world["client"].post("/v1/login", json={"email": "nobody@x.y", "password": "whatever"})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_signing_in_on_a_second_device_does_not_revoke_the_first(world, now):
    """The entire reason api_keys is a table and not a rotate-on-login column:
    klausmate and KlausBook share one subscription, and signing in on one
    must not kill the other's session."""
    _set_password(world, now)
    k1 = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "hunter2xx",
                                                  "device": "klausmate"}).json()["key"]
    k2 = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "hunter2xx",
                                                  "device": "klausbook"}).json()["key"]
    assert k1 != k2
    h1 = {"Authorization": f"Bearer {k1}", "X-Klaus-Client": "0.2.0"}
    h2 = {"Authorization": f"Bearer {k2}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/portal", headers=h1).status_code == 200
    assert world["client"].post("/v1/portal", headers=h2).status_code == 200


def test_logout_revokes_only_that_devices_key(world, now):
    _set_password(world, now)
    k1 = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "hunter2xx",
                                                  "device": "klausmate"}).json()["key"]
    k2 = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "hunter2xx",
                                                  "device": "klausbook"}).json()["key"]
    h1 = {"Authorization": f"Bearer {k1}", "X-Klaus-Client": "0.2.0"}
    h2 = {"Authorization": f"Bearer {k2}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/logout", headers=h1).status_code == 200
    assert world["client"].post("/v1/portal", headers=h1).status_code == 401
    assert world["client"].post("/v1/portal", headers=h2).status_code == 200


def test_a_legacy_key_and_a_login_issued_key_both_authenticate(world, now):
    """proxy.authenticate() now checks two tables -- prove both paths work
    for different customers in the same run, not just serially."""
    legacy_cid = world["store"].upsert_customer("cus_legacy", "legacy@x.y", now)
    legacy_key = keys.mint()
    world["store"].set_key_hash(legacy_cid, keys.hash_key(legacy_key), now)
    world["store"].set_subscription("cus_legacy", "active", int(now) + 86400, False, now)

    _set_password(world, now, email_addr="new@x.y")
    new_key = world["client"].post("/v1/login", json={"email": "new@x.y", "password": "hunter2xx"}).json()["key"]

    h_legacy = {"Authorization": f"Bearer {legacy_key}", "X-Klaus-Client": "0.2.0"}
    h_new = {"Authorization": f"Bearer {new_key}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/portal", headers=h_legacy).status_code == 200
    assert world["client"].post("/v1/portal", headers=h_new).status_code == 200


def test_forgot_password_never_enumerates(world, now):
    world["store"].upsert_customer("cus_1", "known@x.y", now)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    known = world["client"].post("/forgot-password", data={"email": "known@x.y"})
    unknown = world["client"].post("/forgot-password", data={"email": "nobody@x.y"})
    assert known.status_code == unknown.status_code == 200
    assert known.content == unknown.content
    assert len(world["sent"]) == 1  # only the known address actually got an email


def test_forgot_password_cooldown_blocks_a_second_link_immediately(world, now):
    world["store"].upsert_customer("cus_1", "a@b.c", now)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    world["client"].post("/forgot-password", data={"email": "a@b.c"})
    world["client"].post("/forgot-password", data={"email": "a@b.c"})
    assert len(world["sent"]) == 1


def test_reset_password_rejects_invalid_or_expired_token(world, now):
    r = world["client"].post("/reset-password", data={"token": "kp_" + "0" * 32, "password": "hunter2xx"})
    assert r.status_code == 400 and "invalid" in r.text.lower()


def test_reset_password_rejects_a_short_password(world, now):
    world["store"].upsert_customer("cus_1", "a@b.c", now)
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    world["client"].post("/forgot-password", data={"email": "a@b.c"})
    url, _ = _reset_url(world["sent"])
    token = url.split("token=", 1)[1]
    r = world["client"].post("/reset-password", data={"token": token, "password": "short"})
    assert r.status_code == 400 and "8 characters" in r.text


def test_login_is_rate_limited(world, now):
    _set_password(world, now)
    for _ in range(10):
        world["client"].post("/v1/login", json={"email": "a@b.c", "password": "wrong"})
    r = world["client"].post("/v1/login", json={"email": "a@b.c", "password": "wrong"})
    assert r.status_code == 429
