"""Create the Klaus Plus product, its two prices and the webhook endpoint. Run by the operator:

    STRIPE_SECRET_KEY=sk_test_... PUBLIC_BASE_URL=https://klausmate.com python scripts/stripe_setup.py

Idempotent: finds an existing 'Klaus Plus' product and endpoint by name/URL. Prints the
`fly secrets set` line for the ids it created. Never prints the secret key."""
from __future__ import annotations

import os
import sys

import stripe

from klausplus.billing import WEBHOOK_EVENTS
from klausplus.config import STRIPE_API_VERSION


def main() -> int:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    base = (os.environ.get("PUBLIC_BASE_URL") or "https://klausmate.com").rstrip("/")
    if not key:
        print("STRIPE_SECRET_KEY is not set", file=sys.stderr)
        return 2
    stripe.api_key, stripe.api_version = key, STRIPE_API_VERSION
    product = next((p for p in stripe.Product.list(active=True, limit=100).auto_paging_iter() if p.name == "Klaus Plus"), None)
    if product is None:
        product = stripe.Product.create(name="Klaus Plus", description="Metered AI for KlausMate: transcription, card judging, the assistant.")
    prices = {p.recurring.interval: p for p in stripe.Price.list(product=product.id, active=True, limit=10).auto_paging_iter() if p.recurring}
    monthly = prices.get("month") or stripe.Price.create(product=product.id, unit_amount=1200, currency="usd", recurring={"interval": "month"})
    yearly = prices.get("year") or stripe.Price.create(product=product.id, unit_amount=9900, currency="usd", recurring={"interval": "year"})
    url = f"{base}/stripe/webhook"
    endpoint = next((e for e in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter() if e.url == url), None)
    secret_note = "(existing endpoint: its signing secret is in the Stripe dashboard → Developers → Webhooks)"
    if endpoint is None:
        endpoint = stripe.WebhookEndpoint.create(url=url, enabled_events=list(WEBHOOK_EVENTS))
        secret_note = f"STRIPE_WEBHOOK_SECRET={endpoint.secret}"
    print("Set these Fly secrets (paste into your shell, not into any chat):")
    print(f"fly secrets set STRIPE_PRICE_MONTHLY={monthly.id} STRIPE_PRICE_YEARLY={yearly.id} {secret_note if secret_note.startswith('STRIPE') else ''}".rstrip())
    if not secret_note.startswith("STRIPE"):
        print(secret_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
