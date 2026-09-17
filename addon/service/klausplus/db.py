"""SQLite storage: customers, monthly usage, daily audio, seen events.

One writer lock around every mutation — the service is a single machine
and the handlers are threaded; WAL keeps readers unblocked. No request
body is ever stored here, only counters and billing state.
"""
from __future__ import annotations

import calendar
import sqlite3
import threading
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY,
  stripe_customer_id TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL DEFAULT '',
  key_hash TEXT UNIQUE,
  key_rotated_at REAL,
  status TEXT NOT NULL DEFAULT 'incomplete',
  period_end INTEGER NOT NULL DEFAULT 0,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
  past_due_since INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_event_created INTEGER
);
CREATE TABLE IF NOT EXISTS usage (
  customer_id INTEGER NOT NULL,
  month TEXT NOT NULL,
  embed_tokens INTEGER NOT NULL DEFAULT 0,
  audio_seconds INTEGER NOT NULL DEFAULT 0,
  judge_tokens INTEGER NOT NULL DEFAULT 0,
  assistant_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (customer_id, month)
);
CREATE TABLE IF NOT EXISTS daily_audio (
  customer_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  seconds INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (customer_id, day)
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL
);
"""

USAGE_COLUMNS = ("embed_tokens", "audio_seconds", "judge_tokens", "assistant_tokens")

# K-263. A subscription has ENDED at its period end; with no period end, when it
# went past due; failing both, when the row was created (paid page never reached,
# never subscribed). `active`/`trialing` rows are never ended by us — only Stripe
# ends those — so a past_due row inside its 3-day grace is safe here too: the
# customer window is 30 days.
_ENDED_BEFORE = ("status NOT IN ('active', 'trialing') AND "
                 "(CASE WHEN MAX(period_end, past_due_since) > 0 THEN MAX(period_end, past_due_since) "
                 "ELSE created_at END) < ?")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Columns added after the first deploy. The volume already holds a database,
    and `CREATE TABLE IF NOT EXISTS` never revisits an existing table — so each
    later column needs its own guarded ALTER."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}
    if "last_event_created" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN last_event_created INTEGER")


def month_key(now: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(now))


def day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def next_month_start(now: float) -> float:
    t = time.gmtime(now)
    y, m = (t.tm_year + 1, 1) if t.tm_mon == 12 else (t.tm_year, t.tm_mon + 1)
    return float(calendar.timegm((y, m, 1, 0, 0, 0, 0, 0, 0)))


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        # M-3: RLock, not Lock -- add_daily_audio (below) takes the lock and then
        # calls daily_audio(), which now takes it too; a plain Lock would deadlock
        # the very first call from the same thread.
        self._lock = threading.RLock()

    # -- events -----------------------------------------------------------
    def record_event(self, event_id: str, now: float) -> bool:
        with self._lock:
            try:
                self._c.execute("INSERT INTO events (id, received_at) VALUES (?, ?)", (event_id, int(now)))
                return True
            except sqlite3.IntegrityError:
                return False

    def claim_event_created(self, stripe_customer_id: str, created: int) -> bool:
        """K-263: compare-and-set on the last applied subscription event's `created`.
        False — and nothing written — when a NEWER event already landed on this row;
        equal or newer applies. Stripe does not promise delivery order, and a
        delayed older `customer.subscription.updated` must not revive a cancelled row."""
        with self._lock:
            row = self._c.execute("SELECT last_event_created FROM customers WHERE stripe_customer_id = ?",
                                  (stripe_customer_id,)).fetchone()
            prev = row["last_event_created"] if row else None
            if prev is not None and int(created) < int(prev):
                return False
            self._c.execute("UPDATE customers SET last_event_created = ? WHERE stripe_customer_id = ?",
                            (int(created), stripe_customer_id))
            return True

    # -- customers --------------------------------------------------------
    def upsert_customer(self, stripe_customer_id: str, email: str, now: float) -> int:
        with self._lock:
            row = self._c.execute("SELECT id FROM customers WHERE stripe_customer_id = ?", (stripe_customer_id,)).fetchone()
            if row:
                if email:
                    self._c.execute("UPDATE customers SET email = ?, updated_at = ? WHERE id = ?", (email, int(now), row["id"]))
                return int(row["id"])
            cur = self._c.execute(
                "INSERT INTO customers (stripe_customer_id, email, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (stripe_customer_id, email or "", int(now), int(now)))
            return int(cur.lastrowid)

    def set_subscription(self, stripe_customer_id: str, status: str, period_end: int,
                         cancel_at_period_end: bool, now: float) -> None:
        with self._lock:
            self._c.execute(
                "UPDATE customers SET status = ?, period_end = ?, cancel_at_period_end = ?, "
                "past_due_since = CASE WHEN ? = 'past_due' THEN CASE WHEN past_due_since = 0 THEN ? ELSE past_due_since END ELSE 0 END, "
                "updated_at = ? WHERE stripe_customer_id = ?",
                (status, int(period_end or 0), 1 if cancel_at_period_end else 0, status, int(now), int(now), stripe_customer_id))

    def mark_past_due(self, stripe_customer_id: str, now: float) -> None:
        with self._lock:
            self._c.execute(
                "UPDATE customers SET status = 'past_due', past_due_since = CASE WHEN past_due_since = 0 THEN ? ELSE past_due_since END, "
                "updated_at = ? WHERE stripe_customer_id = ?", (int(now), int(now), stripe_customer_id))

    def clear_past_due(self, stripe_customer_id: str, now: float) -> None:
        with self._lock:
            self._c.execute("UPDATE customers SET status = 'active', past_due_since = 0, updated_at = ? "
                            "WHERE stripe_customer_id = ? AND status = 'past_due'", (int(now), stripe_customer_id))

    def set_key_hash(self, customer_id: int, key_hash: str, now: float = 0.0) -> None:
        """Unconditional rotation. `now` (fix1/K-243) stamps `key_rotated_at`, the
        recovery cooldown clock; defaults to 0.0 for the one pre-existing caller
        (`tests/test_app.py`, out of this fix round's file scope) that predates it."""
        with self._lock:
            self._c.execute("UPDATE customers SET key_hash = ?, key_rotated_at = ? WHERE id = ?",
                            (key_hash, now, customer_id))

    def set_key_hash_if_unset(self, customer_id: int, key_hash: str, now: float) -> bool:
        """Atomic mint (fix1/K-243, I-3): only writes when no key exists yet.
        True iff this call won the race and the hash now stored is this one."""
        with self._lock:
            cur = self._c.execute(
                "UPDATE customers SET key_hash = ?, key_rotated_at = ? WHERE id = ? AND (key_hash IS NULL OR key_hash = '')",
                (key_hash, now, customer_id))
            return cur.rowcount == 1

    def customer_by_hash(self, key_hash: str) -> Any:
        with self._lock:
            return self._c.execute("SELECT * FROM customers WHERE key_hash = ?", (key_hash,)).fetchone()

    def customer_by_stripe_id(self, stripe_customer_id: str) -> Any:
        with self._lock:
            return self._c.execute("SELECT * FROM customers WHERE stripe_customer_id = ?", (stripe_customer_id,)).fetchone()

    def customer_by_email(self, email: str) -> Any:
        with self._lock:
            return self._c.execute("SELECT * FROM customers WHERE lower(email) = lower(?) ORDER BY id DESC", (email,)).fetchone()

    def customer_by_id(self, customer_id: int) -> Any:
        with self._lock:
            return self._c.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()

    # -- usage ------------------------------------------------------------
    def usage(self, customer_id: int, month: str) -> dict:
        with self._lock:
            row = self._c.execute("SELECT * FROM usage WHERE customer_id = ? AND month = ?", (customer_id, month)).fetchone()
        return {c: int(row[c]) for c in USAGE_COLUMNS} if row else {c: 0 for c in USAGE_COLUMNS}

    def add_usage(self, customer_id: int, month: str, column: str, amount: int) -> int:
        if column not in USAGE_COLUMNS:
            raise ValueError(column)
        with self._lock:
            self._c.execute("INSERT OR IGNORE INTO usage (customer_id, month) VALUES (?, ?)", (customer_id, month))
            self._c.execute(f"UPDATE usage SET {column} = {column} + ? WHERE customer_id = ? AND month = ?",
                            (int(amount), customer_id, month))
            return int(self._c.execute(f"SELECT {column} FROM usage WHERE customer_id = ? AND month = ?",
                                       (customer_id, month)).fetchone()[0])

    def daily_audio(self, customer_id: int, day: str) -> int:
        with self._lock:
            row = self._c.execute("SELECT seconds FROM daily_audio WHERE customer_id = ? AND day = ?", (customer_id, day)).fetchone()
        return int(row[0]) if row else 0

    def add_daily_audio(self, customer_id: int, day: str, seconds: int) -> int:
        with self._lock:
            self._c.execute("INSERT OR IGNORE INTO daily_audio (customer_id, day) VALUES (?, ?)", (customer_id, day))
            self._c.execute("UPDATE daily_audio SET seconds = seconds + ? WHERE customer_id = ? AND day = ?",
                            (int(seconds), customer_id, day))
            return self.daily_audio(customer_id, day)

    # -- retention --------------------------------------------------------
    def purge_expired(self, now: float, *, usage_days: int, customer_grace_days: int) -> dict:
        """K-263: the promise `/privacy` publishes, enforced. Usage counters, daily
        audio and the Stripe event ledger are kept `usage_days`; a customer record
        is deleted `customer_grace_days` after its subscription ended, together with
        its usage, audio and its licence-key hash (a column on the row). Counts per
        table, so the one log line can say what went.

        ponytail: plain DELETEs under the store's single writer lock, once a day on
        one machine's SQLite file. Batch them only if that ever stops being true.
        """
        cutoff = now - usage_days * 86400
        ended = now - customer_grace_days * 86400
        doomed = "SELECT id FROM customers WHERE " + _ENDED_BEFORE
        with self._lock:
            usage = self._c.execute("DELETE FROM usage WHERE month < ?", (month_key(cutoff),)).rowcount
            audio = self._c.execute("DELETE FROM daily_audio WHERE day < ?", (day_key(cutoff),)).rowcount
            # the events table is the Stripe idempotency ledger -- same window as usage,
            # never shorter, or a replayed old webhook would apply a second time.
            events = self._c.execute("DELETE FROM events WHERE received_at < ?", (int(cutoff),)).rowcount
            usage += self._c.execute("DELETE FROM usage WHERE customer_id IN (%s)" % doomed, (int(ended),)).rowcount
            audio += self._c.execute("DELETE FROM daily_audio WHERE customer_id IN (%s)" % doomed, (int(ended),)).rowcount
            customers = self._c.execute("DELETE FROM customers WHERE " + _ENDED_BEFORE, (int(ended),)).rowcount
        return {"usage": usage, "daily_audio": audio, "events": events, "customers": customers}
