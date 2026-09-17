from klausplus import entitlement as ent


def _sub(status, period_end, cancel=False, items_only=False):
    sub = {"customer": "cus_1", "status": status, "cancel_at_period_end": cancel}
    if items_only:
        sub["items"] = {"data": [{"current_period_end": period_end}]}
    else:
        sub["current_period_end"] = period_end
    return sub


def _event(eid, etype, obj, created=None):
    e = {"id": eid, "type": etype, "data": {"object": obj}}
    if created is not None:
        e["created"] = created  # K-263: Stripe's own ordering stamp
    return e


def test_period_end_reads_subscription_then_items():
    assert ent.period_end_of(_sub("active", 100)) == 100
    assert ent.period_end_of(_sub("active", 200, items_only=True)) == 200
    assert ent.period_end_of({"status": "active"}) == 0


def test_checkout_creates_customer_then_subscription_updates_it(store, now):
    assert ent.apply_event(store, _event("e1", "checkout.session.completed",
                                         {"customer": "cus_1", "customer_details": {"email": "a@b.c"}}), now)
    assert ent.apply_event(store, _event("e2", "customer.subscription.updated", _sub("active", int(now) + 30 * 86400)), now)
    row = store.customer_by_stripe_id("cus_1")
    assert row["email"] == "a@b.c" and row["status"] == "active" and row["period_end"] == int(now) + 30 * 86400
    assert ent.apply_event(store, _event("e2", "customer.subscription.updated", _sub("active", 1)), now) is False  # replay ignored
    assert store.customer_by_stripe_id("cus_1")["period_end"] == int(now) + 30 * 86400


def test_payment_failed_then_paid(store, now):
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.updated", _sub("active", int(now) + 10 * 86400)), now)
    ent.apply_event(store, _event("e2", "invoice.payment_failed", {"customer": "cus_1"}), now)
    row = store.customer_by_stripe_id("cus_1")
    assert row["status"] == "past_due" and row["past_due_since"] == int(now)
    assert ent.verdict(row, now + 2 * 86400, 3)[0] == "active"
    assert ent.verdict(row, now + 4 * 86400, 3)[0] == "refused"
    ent.apply_event(store, _event("e3", "invoice.paid", {"customer": "cus_1"}), now + 5 * 86400)
    row = store.customer_by_stripe_id("cus_1")
    assert row["status"] == "active" and row["past_due_since"] == 0


def test_cancelled_runs_to_period_end(store, now):
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.deleted", _sub("canceled", int(now) + 5 * 86400)), now)
    row = store.customer_by_stripe_id("cus_1")
    assert ent.verdict(row, now + 4 * 86400, 3)[0] == "active"
    assert ent.verdict(row, now + 6 * 86400, 3)[0] == "refused"


def test_active_far_past_period_end_is_refused(store, now):
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.updated", _sub("active", int(now) - 10 * 86400)), now)
    assert ent.verdict(store.customer_by_stripe_id("cus_1"), now, 3)[0] == "refused"


def test_unknown_statuses_refuse(store, now):
    store.upsert_customer("cus_1", "", now)
    for st in ("incomplete", "incomplete_expired", "unpaid", "paused"):
        ent.apply_event(store, _event("e_" + st, "customer.subscription.updated", _sub(st, int(now) + 86400)), now)
        assert ent.verdict(store.customer_by_stripe_id("cus_1"), now, 3)[0] == "refused"


def test_trialing_is_active(store, now):
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.updated", _sub("trialing", 0)), now)
    assert ent.verdict(store.customer_by_stripe_id("cus_1"), now, 3)[0] == "active"
    ent.apply_event(store, _event("e2", "customer.subscription.updated", _sub("trialing", int(now) + 7 * 86400)), now)
    assert ent.verdict(store.customer_by_stripe_id("cus_1"), now + 6 * 86400, 3)[0] == "active"


def test_a_stale_update_after_a_cancellation_does_not_revive_the_row(store, now):
    """K-263: Stripe delivers out of order. A delayed older `updated` arriving
    after the cancellation must not put the row back to active."""
    store.upsert_customer("cus_1", "", now)
    assert ent.apply_event(store, _event("e1", "customer.subscription.deleted",
                                         _sub("canceled", int(now)), created=2000), now)
    assert ent.apply_event(store, _event("e2", "customer.subscription.updated",
                                         _sub("active", int(now) + 30 * 86400), created=1000), now)
    row = store.customer_by_stripe_id("cus_1")
    assert row["status"] == "canceled" and row["period_end"] == int(now)
    # the same event id is still the idempotency key, and a NEWER event still applies
    assert ent.apply_event(store, _event("e3", "customer.subscription.updated",
                                         _sub("active", int(now) + 30 * 86400), created=2000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "active"
    assert ent.apply_event(store, _event("e4", "customer.subscription.deleted",
                                         _sub("canceled", int(now)), created=2001), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "canceled"


def test_an_event_without_a_created_stamp_still_applies(store, now):
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.updated",
                                  _sub("active", int(now) + 86400), created=5000), now)
    ent.apply_event(store, _event("e2", "customer.subscription.deleted", _sub("canceled", int(now))), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "canceled"


# --- K-273: the created-order guard covers the invoice pair too ---------------


def test_a_stale_invoice_payment_failed_never_reopens_a_settled_account(store, now):
    """K-273: the guard covered the three subscription events only, so the delayed retry
    notice — created before the payment that settled the account, delivered after it —
    put an active customer back to past_due."""
    store.upsert_customer("cus_1", "", now)
    assert ent.apply_event(store, _event("e1", "customer.subscription.updated",
                                         _sub("active", int(now) + 30 * 86400), created=1000), now)
    assert ent.apply_event(store, _event("e2", "invoice.payment_failed", {"customer": "cus_1"}, created=2000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "past_due"
    assert ent.apply_event(store, _event("e3", "invoice.paid", {"customer": "cus_1"}, created=3000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "active"
    assert ent.apply_event(store, _event("e4", "invoice.payment_failed", {"customer": "cus_1"}, created=2500), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "active"


def test_an_older_invoice_failure_after_a_newer_subscription_event_is_ignored(store, now):
    """One stamp per customer, shared by both families — an invoice event and a
    subscription event must order against each other, not each within its own kind."""
    store.upsert_customer("cus_1", "", now)
    assert ent.apply_event(store, _event("e1", "customer.subscription.updated",
                                         _sub("active", int(now) + 30 * 86400), created=5000), now)
    assert ent.apply_event(store, _event("e2", "invoice.payment_failed", {"customer": "cus_1"}, created=4000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "active"
    # and one that really is newer still bites: this guard refuses staleness, not invoices
    assert ent.apply_event(store, _event("e3", "invoice.payment_failed", {"customer": "cus_1"}, created=6000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "past_due"


def test_a_stale_invoice_paid_does_not_clear_a_newer_past_due(store, now):
    """The other direction: an old success must not un-refuse an account a newer failure
    just suspended."""
    store.upsert_customer("cus_1", "", now)
    ent.apply_event(store, _event("e1", "customer.subscription.updated",
                                  _sub("active", int(now) + 30 * 86400), created=1000), now)
    assert ent.apply_event(store, _event("e2", "invoice.payment_failed", {"customer": "cus_1"}, created=9000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "past_due"
    assert ent.apply_event(store, _event("e3", "invoice.paid", {"customer": "cus_1"}, created=8000), now)
    assert store.customer_by_stripe_id("cus_1")["status"] == "past_due"
