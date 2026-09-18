"""HTML pages the service serves. Plain, no framework, one frame.

The frame's colors come from docs/reference/design-tokens.json (canonical
in KlausBook-Context, byte-synced here — scripts/check-token-sync.sh) so
this website, klausmate's own UI, and KlausBook read the same palette.
tests/test_brand.py asserts the emitted CSS actually matches that file.
"""
from __future__ import annotations

from html import escape

# The impossible-star mark (docs/reference/brand/klaus-logo.svg), inlined so
# it recolors via currentColor like every other Klaus surface rather than
# shipping as a separate asset request.
_LOGO_SVG = """<svg class="klaus-logo" viewBox="0 0 1254 1254" role="img" aria-label="Klaus"><g fill="currentColor">
<path d="M 724 578 L 719 582 L 718 588 L 728 619 L 744 651 L 769 731 L 791 780 L 794 797 L 835 893 L 859 963 L 853 970 L 846 968 L 754 897 L 747 896 L 638 972 L 634 979 L 637 984 L 659 996 L 698 1026 L 824 1098 L 896 1120 L 912 1119 L 944 1110 L 973 1094 L 1002 1057 L 1009 1032 L 1010 997 L 992 936 L 982 920 L 980 906 L 962 855 L 945 825 L 941 806 L 931 789 L 905 715 L 886 674 L 852 577 L 845 566 L 836 565 Z"/>
<path d="M 658 131 L 610 131 L 576 144 L 543 171 L 522 203 L 506 244 L 496 260 L 475 320 L 467 333 L 462 361 L 455 373 L 443 421 L 420 485 L 419 499 L 403 535 L 402 550 L 379 616 L 381 624 L 485 692 L 492 690 L 509 631 L 521 604 L 532 567 L 532 557 L 568 449 L 575 415 L 590 379 L 612 309 L 620 297 L 627 297 L 634 307 L 642 340 L 674 428 L 711 428 L 760 421 L 794 422 L 803 414 L 802 405 L 790 383 L 783 355 L 775 342 L 754 273 L 739 246 L 734 227 L 718 195 L 692 153 Z"/>
<path d="M 753 731 L 749 727 L 740 729 L 679 775 L 638 799 L 607 824 L 570 846 L 472 916 L 399 960 L 393 959 L 389 952 L 424 837 L 321 765 L 316 766 L 305 789 L 299 816 L 289 834 L 281 866 L 268 894 L 266 911 L 256 931 L 254 947 L 246 967 L 238 1005 L 238 1034 L 247 1064 L 273 1093 L 298 1109 L 314 1114 L 353 1111 L 380 1103 L 521 1030 L 547 1009 L 654 941 L 792 841 L 776 790 L 760 758 Z"/>
<path d="M 1159 507 L 1147 473 L 1127 449 L 1110 437 L 1072 421 L 1026 418 L 973 425 L 902 427 L 884 432 L 803 434 L 733 443 L 694 443 L 673 448 L 589 451 L 584 455 L 570 496 L 549 571 L 555 576 L 613 574 L 717 558 L 849 545 L 872 546 L 889 542 L 913 543 L 963 538 L 993 540 L 999 545 L 999 551 L 992 559 L 891 634 L 891 642 L 934 744 L 941 745 L 1022 684 L 1042 673 L 1067 648 L 1084 637 L 1138 590 L 1156 557 Z"/>
<path d="M 107 469 L 97 502 L 94 530 L 99 557 L 116 587 L 187 647 L 211 661 L 232 683 L 273 711 L 286 724 L 426 814 L 503 869 L 512 869 L 605 800 L 605 794 L 532 740 L 494 719 L 339 617 L 264 562 L 256 553 L 260 546 L 267 543 L 378 541 L 385 538 L 421 429 L 417 422 L 376 424 L 358 421 L 340 424 L 279 419 L 245 422 L 220 418 L 184 421 L 153 431 L 132 443 Z"/>
</g></svg>"""

# Values below are hand-transcribed from design-tokens.json's colors.dark /
# colors.light — tests/test_brand.py re-parses this block and fails if it
# drifts from that file, same discipline as KlausBook-Context's
# tests/design_tokens_test.mjs applied to a third (Python) consumer.
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root {{
  --bg-primary: #1e1e1e; --bg-secondary: #262626; --border: #363636;
  --text-normal: #dadada; --text-muted: #9e9e9e; --text-faint: #6e6e6e;
  --accent: #7f6df2; --veil-hover: rgba(255, 255, 255, 0.055); --veil-press: rgba(255, 255, 255, 0.1);
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg-primary: #ffffff; --bg-secondary: #f6f6f6; --border: #e0e0e0;
    --text-normal: #222222; --text-muted: #808080; --text-faint: #b3b3b3;
    --accent: #705dcf; --veil-hover: rgba(0, 0, 0, 0.05); --veil-press: rgba(0, 0, 0, 0.09);
  }}
}}
body{{font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;background:var(--bg-primary);color:var(--text-normal)}}
.klaus-logo{{width:28px;height:28px;display:block;margin-bottom:1.5rem;color:var(--accent)}}
h1,h2{{color:var(--text-normal)}}
code{{background:var(--bg-secondary);border:1px solid var(--border);padding:.2em .4em;border-radius:6px}}
a{{color:var(--accent)}}
.btn{{display:inline-block;padding:.6em 1em;border:1px solid var(--accent);border-radius:8px;margin-right:.5em;color:var(--accent);text-decoration:none}}
.btn:hover{{background:var(--veil-hover)}}
.btn:active{{background:var(--veil-press)}}
form input{{background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:.5em .7em;color:var(--text-normal);font:inherit}}
footer{{margin-top:3rem;font-size:.9em;color:var(--text-muted);border-top:1px solid var(--border);padding-top:1rem}}
</style></head><body>{logo}{body}
<footer><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · {operator}</footer></body></html>"""


def _frame(title: str, body: str, operator: str) -> str:
    return _PAGE.format(title=escape(title), body=body, operator=escape(operator), logo=_LOGO_SVG)


def landing(operator: str, monthly: str, yearly: str) -> str:
    body = (f"<h1>Klaus Plus</h1><p>Lecture transcription, card judging and the assistant in KlausMate, with no API keys to manage.</p>"
            f"<p>30 lecture hours, 3,000 judged cards and 200 assistant turns a month; embeddings included.</p>"
            f"<p><a class=\"btn\" href=\"/subscribe?plan=monthly\">{escape(monthly)} a month</a>"
            f"<a class=\"btn\" href=\"/subscribe?plan=yearly\">{escape(yearly)} a year</a></p>"
            f"<p>Lost your key? <a href=\"/recover\">Recover it</a>. "
            f"Prefer signing in from the app? <a href=\"/forgot-password\">Set a password</a>.</p>")
    return _frame("Klaus Plus", body, operator)


def welcome(operator: str, key: str | None, emailed: bool, already: bool) -> str:
    if already:
        body = ("<h1>You are already set up</h1><p>This purchase already issued a key. If you lost it, "
                "<a href=\"/recover\">recover it</a> — a new key will be sent and the old one stops working.</p>")
    else:
        note = ("It was also emailed to you." if emailed else "No email was sent — save it now; it is shown only once.")
        body = (f"<h1>Welcome to Klaus Plus</h1><p>Your licence key:</p><p><code style=\"font-size:1.3em\">{escape(key or '')}</code></p>"
                f"<p>{note}</p><p>Paste it in Anki under Tools → KlausMate Preferences → API keys &amp; models → Klaus Plus, then Save.</p>"
                f"<p>Prefer signing in from the app instead? <a href=\"/forgot-password\">Set a password</a>.</p>")
    return _frame("Welcome to Klaus Plus", body, operator)


def _recovery_by_email_line(operator_email: str) -> str:
    # M-6: the one line both recovery pages fall back to when email is off --
    # never promise a send that cannot happen.
    return f"<p>Key recovery is by email to {escape(operator_email)} — write from the address you paid with.</p>"


def _password_by_email_line(operator_email: str) -> str:
    # Same M-6 rule, worded for the account flow rather than key recovery --
    # caught in browser testing (K-287): the two pages read confusingly
    # alike but are different actions and must not share the same sentence.
    return f"<p>Setting a password is by email to {escape(operator_email)} — write from the address you paid with.</p>"


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


def forgot_password_form(operator: str, email_enabled: bool, operator_email: str) -> str:
    if not email_enabled:
        body = f"<h1>Set a password</h1>{_password_by_email_line(operator_email)}"
        return _frame("Set your Klaus Plus password", body, operator)
    body = ("<h1>Set a password</h1><p>Enter the email you subscribed with. We'll send a link to set a "
            "password, so you can sign in from the app instead of pasting a key.</p>"
            "<form method=\"post\" action=\"/forgot-password\"><input type=\"email\" name=\"email\" required "
            "placeholder=\"you@example.com\"> <button class=\"btn\" type=\"submit\">Send the link</button></form>")
    return _frame("Set your Klaus Plus password", body, operator)


def forgot_password_done(operator: str, email_enabled: bool, operator_email: str) -> str:
    if not email_enabled:
        body = f"<h1>Set a password</h1>{_password_by_email_line(operator_email)}"
        return _frame("Set your Klaus Plus password", body, operator)
    return _frame("Set your Klaus Plus password",
                  "<h1>Check your inbox</h1><p>If that address has a subscription, a link is on its way.</p>", operator)


def reset_password_form(operator: str, token: str, error: str | None = None) -> str:
    note = f"<p style=\"color:var(--accent)\">{escape(error)}</p>" if error else ""
    body = (f"<h1>Set a password</h1>{note}"
            f"<form method=\"post\" action=\"/reset-password\">"
            f"<input type=\"hidden\" name=\"token\" value=\"{escape(token)}\">"
            f"<input type=\"password\" name=\"password\" required minlength=\"8\" placeholder=\"New password\"> "
            f"<button class=\"btn\" type=\"submit\">Set password</button></form>")
    return _frame("Set your Klaus Plus password", body, operator)


def reset_password_done(operator: str) -> str:
    body = "<h1>Password set</h1><p>Sign in from the app with your email and new password.</p>"
    return _frame("Klaus Plus", body, operator)


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
