"""Operator tool (I-4): issue a licence key for a customer who paid but never
reached /welcome (redirect closed/blocked/timed out) -- with email off, that
customer had no self-service recovery and the operator had no scripted one.

Run over `fly ssh console` once you have the Stripe customer id (starts with
`cus_`) from the Stripe dashboard or `fly logs`:

    python scripts/mint_key.py cus_abc123

Connects to DATABASE_PATH (the same env var the service itself reads, so on
Fly this finds the live database with no extra flags). Prints the new key
ONCE to stdout -- it replaces any earlier key immediately -- and nothing
else. Never logs the key.
"""
from __future__ import annotations

import sys
import time

from klausplus import keys
from klausplus.config import Settings
from klausplus.db import Store, connect


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: mint_key.py <stripe_customer_id>", file=sys.stderr)
        return 2
    stripe_customer_id = argv[0]
    store = Store(connect(Settings.from_env().database_path))
    row = store.customer_by_stripe_id(stripe_customer_id)
    if row is None:
        print(f"no customer found for {stripe_customer_id}", file=sys.stderr)
        return 1
    key = keys.mint()
    store.set_key_hash(int(row["id"]), keys.hash_key(key), time.time())
    print(key)
    print("Give this to the customer; it replaces any earlier key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
