"""Stripe events → customer state; the verdict every proxied call asks for.

The service is the ONLY gate (spec, findings). Generosity lives on the
add-on side (a cached active honoured for days); here the rules are
plain: active/trialing work, past_due works for the grace window,
canceled works to its period end, everything else is refused.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .db import Store

ACTIVE, TRIALING, PAST_DUE, CANCELED = "active", "trialing", "past_due", "canceled"
SUBSCRIPTION_EVENTS = ("customer.subscription.created", "customer.subscription.updated",
                       "customer.subscription.deleted")
# K-273: every event that moves a customer's ENTITLEMENT, and so every event that has to
# claim the ordering stamp. `checkout.session.completed` is deliberately absent: it only
# creates the row (the /welcome page sets the subscription), and letting it spend the
# stamp would make a legitimately older subscription event look stale. One stamp for
# both families means an invoice CAN suppress a subscription event created a second
# earlier — acceptable: equal stamps apply (Stripe's signup pair shares a second), and
# /welcome writes set_subscription directly, outside the stamp, so a subscriber who
# reached the key page is never left without a subscription row (K-273 review).
ORDERED_EVENTS = SUBSCRIPTION_EVENTS + ("invoice.payment_failed", "invoice.paid")
_log = logging.getLogger("klausplus")
_warned_no_created = False
_PERIOD_LAG_DAYS = 3  # how long an "active" row may outlive its period_end before we stop trusting a missed webhook


def period_end_of(sub: dict) -> int:
    pe = sub.get("current_period_end")
    if not pe:
        items = ((sub.get("items") or {}).get("data") or [])
        pe = items[0].get("current_period_end") if items else 0
    return int(pe or 0)


def _in_order(store: Store, cus: str, created: Any) -> bool:
    """False when this event is OLDER than the last one already applied to the row.

    K-263 introduced this for the three subscription events, because Stripe does not
    guarantee delivery order and a delayed `customer.subscription.updated` arriving after
    the cancellation put the row back to active. K-273 put the invoice pair behind the
    same guard: a delayed `invoice.payment_failed` landing after the `invoice.paid` that
    settled the account — or after a newer subscription event — moved an active customer
    back to past_due just the same.

    ONE stamp per customer, `Store.claim_event_created`, shared by every branch: a second
    column per event family would simply let an invoice and a subscription event reorder
    against each other instead. A missing `created` applies — logged once, because a
    malformed feed must not fill the log."""
    global _warned_no_created
    try:
        stamp = int(created)
    except (TypeError, ValueError):
        if not _warned_no_created:
            _warned_no_created = True
            _log.warning("subscription event carries no usable `created` — applying in arrival order")
        return True
    return store.claim_event_created(cus, stamp)


def apply_event(store: Store, event: dict, now: float) -> bool:
    """Apply one Stripe webhook event. False when its id was already seen."""
    if not store.record_event(str(event.get("id") or ""), now):
        return False
    etype = str(event.get("type") or "")
    obj = (event.get("data") or {}).get("object") or {}
    cus = str(obj.get("customer") or "")
    if not cus:
        return True
    if etype == "checkout.session.completed":
        email = ((obj.get("customer_details") or {}).get("email")) or obj.get("customer_email") or ""
        store.upsert_customer(cus, str(email), now)
        return True
    if etype not in ORDERED_EVENTS:
        return True
    store.upsert_customer(cus, "", now)
    # K-273: the guard is ahead of ALL of them now, not just the subscription three.
    if not _in_order(store, cus, event.get("created")):
        _log.debug("ignoring out-of-order %s for %s", etype, cus)
        return True  # a newer entitlement event already landed on this row
    if etype in SUBSCRIPTION_EVENTS:
        store.set_subscription(cus, str(obj.get("status") or "incomplete"), period_end_of(obj),
                               bool(obj.get("cancel_at_period_end")), now)
    elif etype == "invoice.payment_failed":
        store.mark_past_due(cus, now)
    elif etype == "invoice.paid":
        store.clear_past_due(cus, now)
    return True


def verdict(row: Any, now: float, grace_days: int) -> tuple[str, str]:
    status = str(row["status"])
    period_end = int(row["period_end"] or 0)
    if status in (ACTIVE, TRIALING):
        if period_end and now > period_end + _PERIOD_LAG_DAYS * 86400:
            return "refused", "subscription period ended"
        return "active", ""
    if status == PAST_DUE:
        since = int(row["past_due_since"] or now)
        return ("active", "payment past due") if now - since <= grace_days * 86400 else ("refused", "payment past due")
    if status == CANCELED:
        return ("active", "cancelled, runs to period end") if period_end and now <= period_end else ("refused", "subscription ended")
    return "refused", f"subscription {status}"
