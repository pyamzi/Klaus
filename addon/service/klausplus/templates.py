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


def recover_form(operator: str) -> str:
    body = ("<h1>Recover your key</h1><p>Enter the email you paid with. A new key will be sent and the old one stops working.</p>"
            "<form method=\"post\" action=\"/recover\"><input type=\"email\" name=\"email\" required placeholder=\"you@example.com\"> "
            "<button class=\"btn\" type=\"submit\">Send a new key</button></form>")
    return _frame("Recover your Klaus Plus key", body, operator)


def recover_done(operator: str) -> str:
    return _frame("Recover your Klaus Plus key", "<h1>Check your inbox</h1><p>If that address has a subscription, a new key is on its way.</p>", operator)


def paywall(operator: str, message: str) -> str:
    return _frame("Klaus Plus", f"<h1>Not yet</h1><p>{escape(message)}</p><p><a href=\"/\">Back</a></p>", operator)
