"""Stripe in one module: Checkout, the welcome page that mints the key, webhooks, the portal, recovery.

The service stores the key's hash only. The key is shown once on the
welcome page and, when email is enabled, sent once; recovery mints a NEW
key rather than re-sending an old one nobody can read back.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import email, entitlement, keys, templates
from .config import STRIPE_API_VERSION, Settings
from .proxy import RateLimiter, _declared_length, _err, _read_capped, authenticate

router = APIRouter()
WEBHOOK_EVENTS = ("checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
                  "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed")
RECOVER_COOLDOWN_S = 3600  # fix1/K-243, C-2: a customer's key can rotate via /recover at most once an hour


def _stripe(settings: Settings) -> Any:
    import stripe  # the SDK reads its key from the module; set both every call so a reload cannot drift
    stripe.api_key = settings.stripe_secret_key
    stripe.api_version = STRIPE_API_VERSION
    return stripe


def _construct_event(payload: bytes, sig: str, secret: str) -> dict:
    import stripe
    ev = stripe.Webhook.construct_event(payload, sig, secret)
    return ev.to_dict_recursive() if hasattr(ev, "to_dict_recursive") else dict(ev)


def _operator(settings: Settings) -> str:
    return settings.operator_name or "Klaus"


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> str:
    return templates.landing(_operator(request.app.state.settings), "$12", "$99")


@router.get("/subscribe")
def subscribe(request: Request, plan: str = "monthly") -> RedirectResponse:
    s = request.app.state.settings
    price = s.stripe_price_yearly if plan == "yearly" else s.stripe_price_monthly
    session = _stripe(s).checkout.Session.create(
        mode="subscription", line_items=[{"price": price, "quantity": 1}], allow_promotion_codes=True,
        success_url=f"{s.public_base_url}/welcome?session_id={{CHECKOUT_SESSION_ID}}", cancel_url=f"{s.public_base_url}/")
    return RedirectResponse(session.url, status_code=303)


@router.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, session_id: str = "") -> Any:
    st = request.app.state
    s: Settings = st.settings
    if not session_id:
        return HTMLResponse(templates.paywall(_operator(s), "Missing checkout session."), status_code=400)
    session = _stripe(s).checkout.Session.retrieve(session_id, expand=["subscription"])
    if session["payment_status"] not in ("paid", "no_payment_required"):
        return HTMLResponse(templates.paywall(_operator(s), "This checkout has not been paid."), status_code=402)
    now = st.now()
    cus = str(session["customer"])
    email_addr = str(((session.get("customer_details") or {}).get("email")) or "")
    cid = st.store.upsert_customer(cus, email_addr, now)
    sub = session.get("subscription") or {}
    if sub:
        st.store.set_subscription(cus, str(sub.get("status") or "active"), entitlement.period_end_of(sub),
                                  bool(sub.get("cancel_at_period_end")), now)
    row = st.store.customer_by_id(cid)
    if row["key_hash"]:
        return HTMLResponse(templates.welcome(_operator(s), None, False, already=True))
    key = keys.mint()
    # I-3: conditional UPDATE, not check-then-set — a duplicate/concurrent /welcome load for
    # the same session can no longer hand out a key that a following write silently kills.
    if not st.store.set_key_hash_if_unset(cid, keys.hash_key(key), now):
        return HTMLResponse(templates.welcome(_operator(s), None, False, already=True))
    emailed = email.send_key_email(s, email_addr, key)
    return HTMLResponse(templates.welcome(_operator(s), key, emailed, already=False))


@router.post("/stripe/webhook")
async def webhook(request: Request) -> JSONResponse:
    st = request.app.state
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    # K-262: this route is public and unauthenticated — the cap has to survive a body
    # that declares no length at all, and it has to land before the signature check.
    payload = await _read_capped(request, st.settings.max_json_bytes)
    try:
        event = _construct_event(payload, request.headers.get("stripe-signature", ""), st.settings.stripe_webhook_secret)
    except Exception:
        raise HTTPException(status_code=400, detail={"type": "stripe", "message": "bad signature"})
    if event.get("type") in WEBHOOK_EVENTS:
        entitlement.apply_event(st.store, event, st.now())
    return JSONResponse({"received": True})


@router.post("/v1/portal")
def portal(request: Request) -> JSONResponse:
    # C-1: a lapsed customer (card declined, subscription cancelled) must still reach the
    # portal to fix a card or resubscribe — only the entitlement check is skipped; identity,
    # the version floor, the paused gate and the rate limit all still apply.
    row = authenticate(request, purpose_required=False, require_active=False)
    s = request.app.state.settings
    session = _stripe(s).billing_portal.Session.create(customer=row["stripe_customer_id"], return_url=f"{s.public_base_url}/")
    return JSONResponse({"url": session.url})


@router.get("/recover", response_class=HTMLResponse)
def recover_form(request: Request) -> str:
    s = request.app.state.settings
    return templates.recover_form(_operator(s), email.enabled(s), s.operator_email)


def _recover_limiter(st: Any) -> RateLimiter:
    # ponytail: app.py (out of this fix round's file scope) is where every other limiter is
    # built per-app; lazy-create this one on first use instead, scoped identically (it lives
    # on st, so each create_app() gets its own — no state leaking between apps or tests).
    limiter = getattr(st, "recover_limiter", None)
    if limiter is None:
        limiter = RateLimiter(5)
        st.recover_limiter = limiter
    return limiter


@router.post("/recover", response_class=HTMLResponse)
async def recover(request: Request) -> str:
    st = request.app.state
    # I-2: refuse an oversized body before it is ever buffered. K-262: the declared
    # length is only the cheap half of that — a chunked form declares none.
    if _declared_length(request) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    await _read_capped(request, st.settings.max_json_bytes)
    form = await request.form()
    email_addr = str(form.get("email") or "").strip()
    now = st.now()
    client_ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "")
    # C-2: two independent throttles, both answering the IDENTICAL recover_done page and
    # doing no work at all when they trip, so nothing becomes enumerable either way —
    # a per-caller-IP burst limit, and (below) a per-customer rotation cooldown.
    if not _recover_limiter(st).allow(client_ip, now):
        return templates.recover_done(_operator(st.settings), email.enabled(st.settings), st.settings.operator_email)
    row = st.store.customer_by_email(email_addr)
    if (row is not None
            and entitlement.verdict(row, now, st.settings.grace_days)[0] == "active"
            and email.enabled(st.settings)
            and now - float(row["key_rotated_at"] or 0) > RECOVER_COOLDOWN_S):
        key = keys.mint()
        # I-4: only retire the old key once the new one is confirmed delivered.
        # round2: recover() is async now — run the blocking Resend POST off the event
        # loop, or an in-flight /recover stalls every other request on this process.
        if await run_in_threadpool(email.send_key_email, st.settings, str(row["email"]), key):
            st.store.set_key_hash(int(row["id"]), keys.hash_key(key), now)
    return templates.recover_done(_operator(st.settings), email.enabled(st.settings), st.settings.operator_email)
