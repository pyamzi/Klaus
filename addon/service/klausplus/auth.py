"""Real sign-in: bcrypt-verified login issuing a per-device api_keys row.

An account is created exactly one way — the emailed reset-token flow below,
also used to set the *first* password (a design review on K-287 caught the
alternative, "type an email you claim is yours", as an account-takeover
hole: only possession of the emailed token proves control of the address).
/welcome and /recover are untouched; the raw kp_ key they mint still works
(proxy.authenticate() checks it first) — this is an additive way in, not a
replacement.
"""
from __future__ import annotations

from typing import Any

import bcrypt
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import email, keys, templates
from .proxy import RateLimiter, _declared_length, _err, _json_body, _read_capped, authenticate

router = APIRouter()
RESET_COOLDOWN_S = 3600  # one emailed reset link per customer per hour, same shape as RECOVER_COOLDOWN_S
RESET_TOKEN_TTL_S = 3600  # the link itself is only good for an hour


def _throttle(st: Any) -> RateLimiter:
    # ponytail: lazy-created on st like billing.py's _recover_limiter, so each
    # create_app() (including each test) gets its own with no shared state.
    limiter = getattr(st, "auth_limiter", None)
    if limiter is None:
        limiter = RateLimiter(10)
        st.auth_limiter = limiter
    return limiter


@router.post("/v1/login")
async def login(request: Request) -> JSONResponse:
    st = request.app.state
    s = st.settings
    if _declared_length(request) > s.max_json_bytes:
        raise _err(413, "Request too large.")
    body = _json_body(await _read_capped(request, s.max_json_bytes))
    email_addr = str(body.get("email") or "").strip()
    password = str(body.get("password") or "")
    device = str(body.get("device") or "unknown")[:64]
    now = st.now()
    client_ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "")
    if not _throttle(st).allow(f"login:{client_ip}:{email_addr.lower()}", now):
        raise _err(429, "Too many attempts — wait a moment.")
    user = st.store.user_by_email(email_addr) if email_addr else None
    ok = user is not None and bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8"))
    if not ok:
        raise _err(401, "Email or password not recognised.")
    key = keys.mint()
    st.store.insert_api_key(int(user["customer_id"]), keys.hash_key(key), device, now)
    return JSONResponse({"key": key})


@router.post("/v1/logout")
def logout(request: Request) -> JSONResponse:
    authenticate(request, purpose_required=False, require_active=False)
    st = request.app.state
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    st.store.revoke_api_key(keys.hash_key(token), st.now())
    return JSONResponse({"ok": True})


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_form(request: Request) -> str:
    s = request.app.state.settings
    return templates.forgot_password_form(s.operator_name, email.enabled(s), s.operator_email)


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request) -> str:
    st = request.app.state
    s = st.settings
    if _declared_length(request) > s.max_json_bytes:
        raise _err(413, "Request too large.")
    await _read_capped(request, s.max_json_bytes)
    form = await request.form()
    email_addr = str(form.get("email") or "").strip()
    now = st.now()
    client_ip = request.headers.get("fly-client-ip") or (request.client.host if request.client else "")
    # Same "identical response either way" discipline as /recover (C-2): a
    # throttled or unknown/inactive address must render byte-identically to
    # a real send, so nothing here is enumerable.
    if _throttle(st).allow(f"forgot:{client_ip}", now):
        row = st.store.customer_by_email(email_addr)
        if row is not None and email.enabled(s) and st.store.claim_password_reset(int(row["id"]), now, RESET_COOLDOWN_S):
            token = keys.mint()
            url = f"{s.public_base_url}/reset-password?token={token}"
            if await run_in_threadpool(email.send_reset_email, s, str(row["email"]), url):
                st.store.set_password_reset_token(int(row["id"]), keys.hash_key(token), now)
            else:
                st.store.release_password_reset(int(row["id"]), row["reset_requested_at"], now)
    return templates.forgot_password_done(s.operator_name, email.enabled(s), s.operator_email)


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_form(request: Request, token: str = "") -> Any:
    s = request.app.state.settings
    if not token:
        return HTMLResponse(templates.paywall(s.operator_name, "Missing reset token."), status_code=400)
    return templates.reset_password_form(s.operator_name, token)


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(request: Request) -> Any:
    st = request.app.state
    s = st.settings
    if _declared_length(request) > s.max_json_bytes:
        raise _err(413, "Request too large.")
    await _read_capped(request, s.max_json_bytes)
    form = await request.form()
    token = str(form.get("token") or "")
    password = str(form.get("password") or "")
    if len(password) < 8:
        return HTMLResponse(templates.reset_password_form(s.operator_name, token,
                                                           error="Password must be at least 8 characters."), status_code=400)
    now = st.now()
    row = st.store.customer_by_reset_token_hash(keys.hash_key(token), now, RESET_TOKEN_TTL_S)
    if row is None:
        return HTMLResponse(templates.paywall(s.operator_name, "That reset link is invalid or has expired."), status_code=400)
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    st.store.create_or_update_user(int(row["id"]), str(row["email"]), pw_hash, now)
    st.store.clear_password_reset(int(row["id"]))
    return templates.reset_password_done(s.operator_name)
