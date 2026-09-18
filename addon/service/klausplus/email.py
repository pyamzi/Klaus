"""Resend, behind one seam. Disabled unless both the key and a verified sender exist."""
from __future__ import annotations

import httpx

from .config import Settings

_URL = "https://api.resend.com/emails"


def enabled(settings: Settings) -> bool:
    return settings.email_enabled


def _post(settings: Settings, payload: dict) -> bool:
    try:
        r = httpx.post(_URL, json=payload, headers={"Authorization": f"Bearer {settings.resend_api_key}"}, timeout=15.0)
        return r.status_code < 300
    except httpx.HTTPError:
        return False


def send(settings: Settings, to: str, subject: str, html: str) -> bool:
    if not enabled(settings) or not to:
        return False
    return _post(settings, {"from": settings.resend_from, "to": [to], "subject": subject, "html": html})


def send_key_email(settings: Settings, to: str, key: str) -> bool:
    html = (f"<p>Thanks for subscribing to Klaus Plus.</p><p>Your licence key:</p>"
            f"<p><code style=\"font-size:1.2em\">{key}</code></p>"
            f"<p>Paste it in Anki under Tools → KlausMate Preferences → API keys &amp; models → Klaus Plus.</p>"
            f"<p>Manage or cancel any time from the same page. Questions: {settings.operator_email}</p>")
    return send(settings, to, "Your Klaus Plus key", html)


def send_reset_email(settings: Settings, to: str, url: str) -> bool:
    html = (f"<p>Set a password for Klaus Plus so you can sign in from the app instead of pasting a key.</p>"
            f"<p><a href=\"{url}\">Set your password</a></p>"
            f"<p>This link works once and expires in an hour. If you didn't request it, ignore this email.</p>")
    return send(settings, to, "Set your Klaus Plus password", html)


def send_quota_notice(settings: Settings, to: str, purpose: str, human_line: str) -> bool:
    """I-5/spec D3: the 80%-of-quota notice. `purpose` and `human_line` are always
    fixed, code-controlled strings (a klausplus.meter purpose key and its human
    wording) — never a key, never anything Stripe- or user-supplied."""
    html = (f"<p>Heads-up: you have used 80% of your Klaus Plus {purpose} quota this month ({human_line}).</p>"
            f"<p>Quotas reset on the 1st. If you hit a cap, Klaus will say so and you can add your own API key meanwhile.</p>")
    return send(settings, to, f"Klaus Plus: 80% of your {purpose} quota", html)
