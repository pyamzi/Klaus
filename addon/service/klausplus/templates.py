"""HTML pages the service serves. Plain, no framework, one frame."""
from __future__ import annotations

from html import escape

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;color:#222}}
code{{background:#f2f2f2;padding:.2em .4em;border-radius:4px}} a{{color:#0a58ca}} .btn{{display:inline-block;padding:.6em 1em;border:1px solid #0a58ca;border-radius:6px;margin-right:.5em}}
footer{{margin-top:3rem;font-size:.9em;color:#666}}</style></head><body>{body}
<footer><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · {operator}</footer></body></html>"""


def _frame(title: str, body: str, operator: str) -> str:
    return _PAGE.format(title=escape(title), body=body, operator=escape(operator))


def landing(operator: str, monthly: str, yearly: str) -> str:
    body = (f"<h1>Klaus Plus</h1><p>Lecture transcription, card judging and the assistant in KlausMate, with no API keys to manage.</p>"
            f"<p>30 lecture hours, 3,000 judged cards and 200 assistant turns a month; embeddings included.</p>"
            f"<p><a class=\"btn\" href=\"/subscribe?plan=monthly\">{escape(monthly)} a month</a>"
            f"<a class=\"btn\" href=\"/subscribe?plan=yearly\">{escape(yearly)} a year</a></p>"
            f"<p>Lost your key? <a href=\"/recover\">Recover it</a>.</p>")
    return _frame("Klaus Plus", body, operator)


def welcome(operator: str, key: str | None, emailed: bool, already: bool) -> str:
    if already:
        body = ("<h1>You are already set up</h1><p>This purchase already issued a key. If you lost it, "
                "<a href=\"/recover\">recover it</a> — a new key will be sent and the old one stops working.</p>")
    else:
        note = ("It was also emailed to you." if emailed else "No email was sent — save it now; it is shown only once.")
        body = (f"<h1>Welcome to Klaus Plus</h1><p>Your licence key:</p><p><code style=\"font-size:1.3em\">{escape(key or '')}</code></p>"
                f"<p>{note}</p><p>Paste it in Anki under Tools → KlausMate Preferences → API keys &amp; models → Klaus Plus, then Save.</p>")
    return _frame("Welcome to Klaus Plus", body, operator)


def _recovery_by_email_line(operator_email: str) -> str:
    # M-6: the one line both recovery pages fall back to when email is off --
    # never promise a send that cannot happen.
    return f"<p>Key recovery is by email to {escape(operator_email)} — write from the address you paid with.</p>"


def recover_form(operator: str, email_enabled: bool, operator_email: str) -> str:
    if not email_enabled:
        body = f"<h1>Recover your key</h1>{_recovery_by_email_line(operator_email)}"
        return _frame("Recover your Klaus Plus key", body, operator)
    body = ("<h1>Recover your key</h1><p>Enter the email you paid with. A new key will be sent and the old one stops working.</p>"
            "<form method=\"post\" action=\"/recover\"><input type=\"email\" name=\"email\" required placeholder=\"you@example.com\"> "
            "<button class=\"btn\" type=\"submit\">Send a new key</button></form>")
    return _frame("Recover your Klaus Plus key", body, operator)


def recover_done(operator: str, email_enabled: bool, operator_email: str) -> str:
    if not email_enabled:
        body = f"<h1>Recover your key</h1>{_recovery_by_email_line(operator_email)}"
        return _frame("Recover your Klaus Plus key", body, operator)
    return _frame("Recover your Klaus Plus key", "<h1>Check your inbox</h1><p>If that address has a subscription, a new key is on its way.</p>", operator)


def paywall(operator: str, message: str) -> str:
    return _frame("Klaus Plus", f"<h1>Not yet</h1><p>{escape(message)}</p><p><a href=\"/\">Back</a></p>", operator)


def terms(operator: str, email_addr: str, country: str) -> str:
    o, e, c = escape(operator), escape(email_addr), escape(country)
    body = f"""<h1>Klaus Plus — Terms of Service</h1>
<p>Klaus Plus is a subscription operated by {o} ("we") that gives the KlausMate Anki add-on metered access to third-party
AI providers through our service, so that you do not have to manage API keys yourself. By subscribing you agree to these terms.</p>
<h2>What you get</h2>
<p>Each calendar month (UTC), a subscription includes 30 hours of lecture audio transcribed, 3,000 cards judged and 200 assistant
turns, with embeddings included. Quotas do not carry over. We may change quotas or prices with 30 days' notice by email; a change
does not affect a period already paid for. When a quota is used up, the add-on tells you and you may use your own API keys instead.</p>
<h2>Your licence key</h2>
<p>The key is personal to you and may be used on the computers you study on. Do not share it or resell access. We may revoke a key
that is shared or used to abuse the service, and we may rate-limit unusual traffic.</p>
<h2>Acceptable use</h2>
<p>Klaus Plus is for personal study. You may not use it to bulk-process content you have no right to use, to build a competing
service, or to send content that the providers' own policies prohibit. Access is through the Klaus add-on with your own licence key:
no automated, scripted or bulk use of the service, and no scraping of it. You are responsible for the material you send through the service.</p>
<h2>Payment, cancellation, refunds</h2>
<p>Payments are handled by Stripe. Subscriptions renew automatically until cancelled. Cancel any time from the "Manage subscription"
link in KlausMate Preferences; access continues until the period end and no further charge is made. If Klaus Plus is not
what you expected, email us within 14 days of your first payment for a full refund of that payment.</p>
<h2>Availability and liability</h2>
<p>The service depends on third-party providers and is offered as is. We aim for continuous availability but do not guarantee it;
if we pause the service for maintenance, quotas are not consumed. To the extent the law allows, our liability is limited to the fees
you paid in the three months before a claim.</p>
<h2>Contact and law</h2>
<p>Questions and refund requests: <a href="mailto:{e}">{e}</a>. These terms are governed by the law of {c}.</p>"""
    return _frame("Klaus Plus — Terms of Service", body, operator)


def privacy(operator: str, email_addr: str) -> str:
    o, e = escape(operator), escape(email_addr)
    body = f"""<h1>Klaus Plus — Privacy Policy</h1>
<p>This policy describes what the Klaus Plus service, operated by {o}, stores and what it does not.</p>
<h2>What we store</h2>
<ul><li>Your Stripe customer id and the billing email Stripe reports to us.</li>
<li>A hash of your licence key (the key itself is not stored and cannot be read back).</li>
<li>Your subscription status and period end, as reported by Stripe.</li>
<li>Monthly usage counters: audio seconds transcribed, tokens used for judging and for the assistant, embedding tokens.</li>
<li>Service logs with the request path, status, timing and the metered amount, keyed by a short prefix of your key's hash.</li></ul>
<h2>What we do not store</h2>
<p>Your lecture text, audio, page images, notes, cards and transcripts are <strong>not stored</strong>. Requests are relayed to the provider
and the response relayed back; the content is discarded as soon as the response is delivered. Logs never contain request or response bodies.</p>
<h2>Who receives your data</h2>
<ul><li><strong>Stripe</strong> processes payments and holds your card details; we never see them.</li>
<li><strong>OpenAI</strong> receives the text you embed and the audio you transcribe, to produce the result.</li>
<li><strong>Anthropic</strong> receives the pages, cards and messages you send to the judge and the assistant, to produce the result.</li>
<li><strong>Resend</strong> delivers our emails (your key, quota notices).</li>
<li><strong>Fly.io</strong> hosts the service.</li></ul>
<p>Each provider handles the content under its own terms; we send them nothing beyond what a request needs.</p>
<h2>Retention and deletion</h2>
<p>Usage counters are kept for 13 months for billing questions. Your customer record is deleted 30 days after your subscription ends.
Email <a href="mailto:{e}">{e}</a> to have it deleted sooner, or to ask what we hold about you.</p>"""
    return _frame("Klaus Plus — Privacy Policy", body, operator)
