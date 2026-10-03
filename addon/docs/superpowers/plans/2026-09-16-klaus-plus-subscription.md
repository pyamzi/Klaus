# Klaus Plus Subscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Klaus Plus — a $12/month or $99/year subscription through which Klaus's own Fly.io service holds the OpenAI and Anthropic keys and meters four counters, so a subscriber never pastes a key; bring-your-own-keys stays as the free tier.

**Architecture:** One FastAPI service (`service/`) mirrors the three provider endpoints the add-on already calls, authenticates a per-customer licence key, meters usage per calendar month, and is driven by Stripe Checkout, Portal and webhooks. The add-on gains one aqt-free module (`klausmate/plus.py`) that resolves an `Endpoint` (base URL + headers) per call; the two stdlib clients accept that endpoint with the provider as the default, so every existing pin stands.

**Tech Stack:** Service: Python 3.12 in Docker on Fly.io, FastAPI, uvicorn, httpx, the official `stripe` SDK (API version pinned `2024-06-20`), python-multipart, SQLite (WAL) on a Fly volume, Resend for email, pytest. Add-on: Python 3.9 stdlib only, the house `check/section/report` harness.

**Spec:** `docs/superpowers/specs/2026-09-16-klaus-plus-subscription-design.md` (D1–D7). Builds on `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md` (Plan 1, built).

## Global Constraints

- The add-on ships as readable Python: no provider key, no secret, no price constant that gates anything lives in `klausmate/`. The only gate is the service answering 401/402.
- Service dependencies are fine; the add-on stays stdlib-only, Python 3.9, `from __future__ import annotations` in every module.
- Keys and tokens are never logged, never in an exception message, never in a URL. The service stores licence keys only as SHA-256 hashes. Logs carry method, path, status, an 8-character key-hash prefix, latency and the metered amount — never a request or response body (a test asserts this).
- Quotas, per calendar month (UTC), no rollover: audio 108,000 seconds (30 h), judge 750,000 Anthropic tokens (3,000 cards × 250), assistant 1,200,000 Anthropic tokens (200 turns × 6,000), embeddings unmetered with a 20,000,000-token abuse ceiling. Human units: 250 tokens per card, 6,000 per turn — constants in exactly one place on each side (`service/klausplus/config.py`, `klausmate/plus.py`).
- Grace: `past_due` works 3 days; `canceled` works to `period_end`; the add-on caches a verdict 6 hours and honours a cached active for 7 days without the service.
- Stripe API version pinned to `2024-06-20` in the SDK call (`current_period_end` on the subscription, `subscription` on the invoice); webhook events idempotent by event id.
- Email only when both `RESEND_API_KEY` and `RESEND_FROM` are set (a verified sender needs a domain; Resend's test sender delivers only to the account owner). Without them the welcome page says no email was sent.
- Purpose tags on every proxied call: `X-Klaus-Purpose: embed | transcribe | judge | assistant`; `judge`/`assistant` only on `/v1/messages`; `X-Klaus-Client: <manifest human_version>` on every call, refused with 426 below `MIN_CLIENT_VERSION`.
- The sweep confirm on Plus says "included in Klaus Plus, no charge" (embeddings are unmetered); dollar estimates stay for the free tier.
- Add-on house rules unchanged: no `exec()`, window-modal dialogs, theme tokens only, `mark_dirty`/`save_all` deferred save, every new pin mutated once, tests never touch the real `klausmate/user_files/` or `meta.json`.
- Board discipline: workers never run git write commands; the orchestrator commits after each task's review; column moves are the orchestrator's.

## File Structure

```
service/                              # the private program; excluded from the add-on zip
  pyproject.toml  Dockerfile  fly.toml  README.md
  klausplus/__init__.py
  klausplus/config.py        Settings from env; quota and unit constants (Task 1)
  klausplus/db.py            SQLite schema + Store (Task 1)
  klausplus/keys.py          mint / hash / looks_like_key (Task 1)
  klausplus/entitlement.py   Stripe event → customer state; verdict() (Task 2)
  klausplus/meter.py         caps, check, charge, snapshot, messages (Task 2)
  klausplus/upstream.py      httpx calls to OpenAI/Anthropic (Task 3)
  klausplus/proxy.py         auth, rate limit, the three proxied routes, /v1/me (Task 3)
  klausplus/app.py           create_app(); /healthz; logging middleware (Task 3)
  klausplus/main.py          uvicorn entry (Task 3)
  klausplus/billing.py       /subscribe /welcome /stripe/webhook /v1/portal /recover / (Task 4; stub by Task 3)
  klausplus/email.py         Resend (Task 4)
  klausplus/pages.py         /terms /privacy (Task 5; stub by Task 3)
  klausplus/templates.py     HTML strings (Tasks 4, 5)
  scripts/stripe_setup.py    products, prices, webhook endpoint (Task 4)
  tests/conftest.py test_keys.py test_db.py test_entitlement.py test_meter.py test_proxy.py test_app.py test_billing.py test_pages.py
klausmate/plus.py + tests/test_plus.py                       (Task 6)
klausmate/openai_client.py anthropic_client.py embeddings.py index_queue.py setup_flow.py + their tests  (Task 7)
klausmate/manage_models.py config.json config.md + tests/test_dialog_logic.py test_manage_models_assistant.py test_api_first_config.py  (Task 8)
LICENSE klausmate/LICENSE README.md CLAUDE.md AGENTS.md scripts/package.sh  (Task 9)
```

Lanes for the swarm: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 (Task 5 appends to Task 4's `templates.py`); Task 6 (add-on) may run alongside Task 2; Tasks 7 and 8 after Task 6, in parallel; Task 9 after Tasks 5, 7, 8; Task 10 last. Card files are the lists above; Tasks 3 and 4/5 share `app.py` only through the two stub modules Task 3 creates; Task 10 (last) edits `upstream.py`, `app.py` and `tests/test_proxy.py` once every other task is committed.

---

### Task 1: Service skeleton — settings, database, keys

**Files:**
- Create: `service/pyproject.toml`, `service/Dockerfile`, `service/fly.toml`, `service/klausplus/__init__.py`, `service/klausplus/config.py`, `service/klausplus/db.py`, `service/klausplus/keys.py`
- Test: `service/tests/conftest.py`, `service/tests/test_keys.py`, `service/tests/test_db.py`

**Interfaces:**
- Produces: `Settings` (frozen dataclass, `Settings.from_env()`), the quota constants; `db.connect(path) -> sqlite3.Connection`, `db.Store(conn)` with `record_event`, `upsert_customer`, `set_subscription`, `mark_past_due`, `clear_past_due`, `customer_by_hash/by_stripe_id/by_email/by_id`, `set_key_hash`, `usage(customer_id, month) -> dict`, `add_usage(customer_id, month, column, amount) -> int`, `daily_audio(customer_id, day) -> int`, `add_daily_audio`; `db.month_key(now)`, `db.day_key(now)`, `db.next_month_start(now)`; `keys.mint()`, `keys.hash_key(key)`, `keys.looks_like_key(s)`.

- [ ] **Step 1: The venv and the failing tests**

```bash
cd /Users/pyamzi/Documents/Github/KlausMate-Context/service && python3 -m venv .venv && . .venv/bin/activate && pip install -q -e ".[dev]"
```
(`pyproject.toml` first, below; `.venv/` is git-ignored — add `service/.venv/` to the repo's `.gitignore` in this task.)

`service/tests/conftest.py`:
```python
from __future__ import annotations
import time
import pytest
from klausplus.config import Settings
from klausplus.db import Store, connect


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=str(tmp_path / "k.sqlite3"), stripe_secret_key="sk_test_x",
                    stripe_webhook_secret="whsec_x", stripe_price_monthly="price_m", stripe_price_yearly="price_y",
                    openai_api_key="oa", anthropic_api_key="an", public_base_url="https://klaus.test",
                    operator_name="Klaus Test", operator_email="ops@klaus.test", operator_country="Testland")


@pytest.fixture
def store(settings):
    return Store(connect(settings.database_path))


@pytest.fixture
def now():
    return float(time.mktime((2026, 9, 16, 12, 0, 0, 0, 0, 0)))
```

`service/tests/test_keys.py`:
```python
from klausplus import keys


def test_mint_shape_and_uniqueness():
    a, b = keys.mint(), keys.mint()
    assert a != b and a.startswith("kp_") and len(a) == 35 and keys.looks_like_key(a)


def test_hash_is_sha256_hex_and_stable():
    h = keys.hash_key("kp_" + "0" * 32)
    assert len(h) == 64 and h == keys.hash_key("kp_" + "0" * 32)


def test_looks_like_key_rejects_junk():
    assert not keys.looks_like_key("sk-abc") and not keys.looks_like_key("kp_xyz") and not keys.looks_like_key("")
```

`service/tests/test_db.py`:
```python
from klausplus import db


def test_schema_and_month_keys(store, now):
    assert db.month_key(now) == "2026-09" and db.day_key(now) == "2026-09-16"
    assert db.month_key(db.next_month_start(now)) == "2026-10"


def test_customer_round_trip(store, now):
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    assert store.customer_by_stripe_id("cus_1")["id"] == cid
    assert store.upsert_customer("cus_1", "a@b.c", now) == cid  # idempotent
    store.set_key_hash(cid, "h" * 64)
    assert store.customer_by_hash("h" * 64)["email"] == "a@b.c"
    store.set_subscription("cus_1", "active", 1_800_000_000, False, now)
    row = store.customer_by_id(cid)
    assert row["status"] == "active" and row["period_end"] == 1_800_000_000


def test_usage_and_daily_audio(store, now):
    cid = store.upsert_customer("cus_2", "", now)
    assert store.usage(cid, "2026-09")["judge_tokens"] == 0
    assert store.add_usage(cid, "2026-09", "judge_tokens", 700) == 700
    assert store.add_usage(cid, "2026-09", "judge_tokens", 50) == 750
    assert store.usage(cid, "2026-10")["judge_tokens"] == 0
    assert store.add_daily_audio(cid, "2026-09-16", 90) == 90 and store.daily_audio(cid, "2026-09-16") == 90


def test_events_are_idempotent(store, now):
    assert store.record_event("evt_1", now) is True
    assert store.record_event("evt_1", now) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd service && . .venv/bin/activate && python -m pytest -q`
Expected: ImportError on `klausplus` (no package yet).

- [ ] **Step 3: Write the package**

`service/pyproject.toml`:
```toml
[project]
name = "klausplus"
version = "0.1.0"
description = "Klaus Plus: the metered service behind the KlausMate Anki add-on"
requires-python = ">=3.9"
dependencies = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "httpx>=0.27", "stripe>=10", "python-multipart>=0.0.9"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["klausplus*"]
```

`service/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY klausplus ./klausplus
RUN pip install --no-cache-dir .
ENV DATABASE_PATH=/data/klausplus.sqlite3
EXPOSE 8080
CMD ["uvicorn", "klausplus.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`service/fly.toml` (set `primary_region` to the region nearest Pouya from `fly platform regions`; `iad` is the default):
```toml
app = "klausmate"
primary_region = "iad"

[build]

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

[[mounts]]
  source = "klausplus_data"
  destination = "/data"

[checks]
  [checks.health]
    port = 8080
    type = "http"
    interval = "30s"
    timeout = "5s"
    path = "/healthz"
```

`service/klausplus/__init__.py`: empty.

`service/klausplus/config.py`:
```python
"""Settings from the environment (Fly secrets in production).

Every quota and unit constant lives here — the one place on the service
side; ``klausmate/plus.py`` holds the add-on's copy of the two human
units. Keys are read once and never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Human units (spec D1): a judged card is ~250 Anthropic tokens, an assistant turn ~6,000.
TOKENS_PER_CARD = 250
TOKENS_PER_TURN = 6000
STRIPE_API_VERSION = "2024-06-20"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_path: str = "/data/klausplus.sqlite3"
    public_base_url: str = "https://klausmate.fly.dev"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_base: str = "https://api.openai.com/v1"
    anthropic_base: str = "https://api.anthropic.com"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_monthly: str = ""
    stripe_price_yearly: str = ""
    resend_api_key: str = ""
    resend_from: str = ""
    min_client_version: str = "0.2.0"
    paused: bool = False
    operator_name: str = "Klaus"
    operator_email: str = ""
    operator_country: str = ""
    quota_audio_seconds: int = 30 * 3600
    quota_judge_tokens: int = 3000 * TOKENS_PER_CARD
    quota_assistant_tokens: int = 200 * TOKENS_PER_TURN
    embed_ceiling_tokens: int = 20_000_000
    grace_days: int = 3
    rate_per_minute: int = 60
    audio_day_seconds: int = 240 * 60
    max_json_bytes: int = 4 * 1024 * 1024
    max_audio_bytes: int = 25 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        d = cls()
        return cls(
            database_path=e("DATABASE_PATH") or d.database_path,
            public_base_url=(e("PUBLIC_BASE_URL") or d.public_base_url).rstrip("/"),
            openai_api_key=e("OPENAI_API_KEY") or "",
            anthropic_api_key=e("ANTHROPIC_API_KEY") or "",
            stripe_secret_key=e("STRIPE_SECRET_KEY") or "",
            stripe_webhook_secret=e("STRIPE_WEBHOOK_SECRET") or "",
            stripe_price_monthly=e("STRIPE_PRICE_MONTHLY") or "",
            stripe_price_yearly=e("STRIPE_PRICE_YEARLY") or "",
            resend_api_key=e("RESEND_API_KEY") or "",
            resend_from=e("RESEND_FROM") or "",
            min_client_version=e("MIN_CLIENT_VERSION") or d.min_client_version,
            paused=_truthy(e("KLAUS_PLUS_PAUSED")),
            operator_name=e("OPERATOR_NAME") or d.operator_name,
            operator_email=e("OPERATOR_EMAIL") or "",
            operator_country=e("OPERATOR_COUNTRY") or "",
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.resend_from)
```

`service/klausplus/keys.py`:
```python
"""Licence keys: minted once, stored only as a SHA-256 hash."""
from __future__ import annotations

import hashlib
import secrets

PREFIX = "kp_"
_HEX = set("0123456789abcdef")


def mint() -> str:
    return PREFIX + secrets.token_hex(16)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_key(s: str) -> bool:
    return isinstance(s, str) and s.startswith(PREFIX) and len(s) == 35 and set(s[3:]) <= _HEX
```

`service/klausplus/db.py`:
```python
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
  status TEXT NOT NULL DEFAULT 'incomplete',
  period_end INTEGER NOT NULL DEFAULT 0,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
  past_due_since INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
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


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


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
        self._lock = threading.Lock()

    # -- events -----------------------------------------------------------
    def record_event(self, event_id: str, now: float) -> bool:
        with self._lock:
            try:
                self._c.execute("INSERT INTO events (id, received_at) VALUES (?, ?)", (event_id, int(now)))
                return True
            except sqlite3.IntegrityError:
                return False

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

    def set_key_hash(self, customer_id: int, key_hash: str) -> None:
        with self._lock:
            self._c.execute("UPDATE customers SET key_hash = ? WHERE id = ?", (key_hash, customer_id))

    def customer_by_hash(self, key_hash: str) -> Any:
        return self._c.execute("SELECT * FROM customers WHERE key_hash = ?", (key_hash,)).fetchone()

    def customer_by_stripe_id(self, stripe_customer_id: str) -> Any:
        return self._c.execute("SELECT * FROM customers WHERE stripe_customer_id = ?", (stripe_customer_id,)).fetchone()

    def customer_by_email(self, email: str) -> Any:
        return self._c.execute("SELECT * FROM customers WHERE lower(email) = lower(?) ORDER BY id DESC", (email,)).fetchone()

    def customer_by_id(self, customer_id: int) -> Any:
        return self._c.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()

    # -- usage ------------------------------------------------------------
    def usage(self, customer_id: int, month: str) -> dict:
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
        row = self._c.execute("SELECT seconds FROM daily_audio WHERE customer_id = ? AND day = ?", (customer_id, day)).fetchone()
        return int(row[0]) if row else 0

    def add_daily_audio(self, customer_id: int, day: str, seconds: int) -> int:
        with self._lock:
            self._c.execute("INSERT OR IGNORE INTO daily_audio (customer_id, day) VALUES (?, ?)", (customer_id, day))
            self._c.execute("UPDATE daily_audio SET seconds = seconds + ? WHERE customer_id = ? AND day = ?",
                            (int(seconds), customer_id, day))
            return self.daily_audio(customer_id, day)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd service && . .venv/bin/activate && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Mutate once, restore.** Flip `record_event`'s `except sqlite3.IntegrityError: return False` to `return True` → `test_events_are_idempotent` fails; restore byte-identical (md5 before/after in the report). Add `service/.venv/` to `.gitignore`. Report to the orchestrator; no git write commands.

---

### Task 2: Entitlement and metering

**Files:**
- Create: `service/klausplus/entitlement.py`, `service/klausplus/meter.py`
- Test: `service/tests/test_entitlement.py`, `service/tests/test_meter.py`

**Interfaces:**
- Consumes: `Store`, `Settings`, `db.month_key/day_key/next_month_start` (Task 1).
- Produces: `entitlement.period_end_of(sub) -> int`; `entitlement.apply_event(store, event, now) -> bool` (False when the event id was seen); `entitlement.verdict(row, now, grace_days) -> tuple[str, str]` where the first element is `"active"` or `"refused"`; `meter.PURPOSES`, `meter.COLUMN`, `meter.caps(settings) -> dict`, `meter.check(store, settings, customer_id, purpose, amount, now) -> tuple[bool, int]`, `meter.charge(store, settings, customer_id, purpose, amount, now) -> dict` (returns the snapshot plus `"crossed_80": [purposes]`), `meter.snapshot(store, settings, customer_id, now) -> dict`, `meter.quota_message(purpose, resets_at) -> str`, `meter.check_daily_audio(store, settings, customer_id, seconds, now) -> bool`.

- [ ] **Step 1: Write the failing tests**

`service/tests/test_entitlement.py`:
```python
from klausplus import entitlement as ent


def _sub(status, period_end, cancel=False, items_only=False):
    sub = {"customer": "cus_1", "status": status, "cancel_at_period_end": cancel}
    if items_only:
        sub["items"] = {"data": [{"current_period_end": period_end}]}
    else:
        sub["current_period_end"] = period_end
    return sub


def _event(eid, etype, obj):
    return {"id": eid, "type": etype, "data": {"object": obj}}


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
```

`service/tests/test_meter.py`:
```python
from klausplus import meter
from klausplus.db import next_month_start


def test_caps_come_from_settings(settings):
    assert meter.caps(settings) == {"embed": 20_000_000, "transcribe": 108_000, "judge": 750_000, "assistant": 1_200_000}


def test_check_and_charge_against_month(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    ok, remaining = meter.check(store, settings, cid, "judge", 749_999, now)
    assert ok and remaining == 750_000
    snap = meter.charge(store, settings, cid, "judge", 749_999, now)
    assert snap["counters"]["judge"]["used"] == 749_999 and snap["crossed_80"] == ["judge"]
    assert meter.check(store, settings, cid, "judge", 2, now) == (False, 1)
    assert meter.check(store, settings, cid, "judge", 2, next_month_start(now) + 1) == (True, 750_000)


def test_crossed_80_fires_once(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.charge(store, settings, cid, "assistant", 900_000, now)["crossed_80"] == []
    assert meter.charge(store, settings, cid, "assistant", 100_000, now)["crossed_80"] == ["assistant"]
    assert meter.charge(store, settings, cid, "assistant", 10, now)["crossed_80"] == []


def test_snapshot_human_units_and_reset(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    meter.charge(store, settings, cid, "transcribe", 7200, now)
    meter.charge(store, settings, cid, "judge", 2500, now)
    snap = meter.snapshot(store, settings, cid, now)
    assert snap["month"] == "2026-09" and snap["resets_at"] == next_month_start(now)
    assert snap["human"]["lecture_hours"] == [2.0, 30.0]
    assert snap["human"]["cards"] == [10, 3000] and snap["human"]["turns"] == [0, 200]


def test_daily_audio_cap(store, settings, now):
    cid = store.upsert_customer("cus_1", "", now)
    assert meter.check_daily_audio(store, settings, cid, 240 * 60, now)
    store.add_daily_audio(cid, "2026-09-16", 240 * 60)
    assert not meter.check_daily_audio(store, settings, cid, 1, now)
    assert meter.check_daily_audio(store, settings, cid, 1, now + 86400)


def test_quota_message_names_the_reset():
    msg = meter.quota_message("transcribe", next_month_start(0))
    assert "lecture hours" in msg and "1970-02-01" in msg
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest -q service/tests/test_entitlement.py service/tests/test_meter.py` → ImportError.

- [ ] **Step 3: Implement**

`service/klausplus/entitlement.py`:
```python
"""Stripe events → customer state; the verdict every proxied call asks for.

The service is the ONLY gate (spec, findings). Generosity lives on the
add-on side (a cached active honoured for days); here the rules are
plain: active/trialing work, past_due works for the grace window,
canceled works to its period end, everything else is refused.
"""
from __future__ import annotations

import time
from typing import Any

from .db import Store

ACTIVE, TRIALING, PAST_DUE, CANCELED = "active", "trialing", "past_due", "canceled"
_PERIOD_LAG_DAYS = 3  # how long an "active" row may outlive its period_end before we stop trusting a missed webhook


def period_end_of(sub: dict) -> int:
    pe = sub.get("current_period_end")
    if not pe:
        items = ((sub.get("items") or {}).get("data") or [])
        pe = items[0].get("current_period_end") if items else 0
    return int(pe or 0)


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
    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        store.upsert_customer(cus, "", now)
        store.set_subscription(cus, str(obj.get("status") or "incomplete"), period_end_of(obj),
                               bool(obj.get("cancel_at_period_end")), now)
    elif etype == "invoice.payment_failed":
        store.upsert_customer(cus, "", now)
        store.mark_past_due(cus, now)
    elif etype == "invoice.paid":
        store.upsert_customer(cus, "", now)
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
```

`service/klausplus/meter.py`:
```python
"""Quotas: check before forwarding, charge after; one snapshot shape everywhere."""
from __future__ import annotations

import time

from .config import Settings, TOKENS_PER_CARD, TOKENS_PER_TURN
from .db import Store, day_key, month_key, next_month_start

PURPOSES = ("embed", "transcribe", "judge", "assistant")
COLUMN = {"embed": "embed_tokens", "transcribe": "audio_seconds", "judge": "judge_tokens", "assistant": "assistant_tokens"}
_HUMAN = {"transcribe": "lecture hours", "judge": "judged cards", "assistant": "assistant turns", "embed": "embedding tokens"}


def caps(settings: Settings) -> dict:
    return {"embed": settings.embed_ceiling_tokens, "transcribe": settings.quota_audio_seconds,
            "judge": settings.quota_judge_tokens, "assistant": settings.quota_assistant_tokens}


def check(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int, now: float) -> tuple[bool, int]:
    used = store.usage(customer_id, month_key(now))[COLUMN[purpose]]
    cap = caps(settings)[purpose]
    return used + max(0, int(amount)) <= cap, max(0, cap - used)


def check_daily_audio(store: Store, settings: Settings, customer_id: int, seconds: int, now: float) -> bool:
    return store.daily_audio(customer_id, day_key(now)) + max(0, int(seconds)) <= settings.audio_day_seconds


def charge(store: Store, settings: Settings, customer_id: int, purpose: str, amount: int, now: float) -> dict:
    cap = caps(settings)[purpose]
    before = store.usage(customer_id, month_key(now))[COLUMN[purpose]]
    after = store.add_usage(customer_id, month_key(now), COLUMN[purpose], max(0, int(amount)))
    if purpose == "transcribe":
        store.add_daily_audio(customer_id, day_key(now), max(0, int(amount)))
    snap = snapshot(store, settings, customer_id, now)
    line = 0.8 * cap
    snap["crossed_80"] = [purpose] if before < line <= after else []
    return snap


def snapshot(store: Store, settings: Settings, customer_id: int, now: float) -> dict:
    used = store.usage(customer_id, month_key(now))
    cap = caps(settings)
    counters = {p: {"used": used[COLUMN[p]], "cap": cap[p]} for p in PURPOSES}
    return {
        "month": month_key(now),
        "resets_at": next_month_start(now),
        "counters": counters,
        "human": {
            "lecture_hours": [round(used["audio_seconds"] / 3600, 1), round(cap["transcribe"] / 3600, 1)],
            "cards": [used["judge_tokens"] // TOKENS_PER_CARD, cap["judge"] // TOKENS_PER_CARD],
            "turns": [used["assistant_tokens"] // TOKENS_PER_TURN, cap["assistant"] // TOKENS_PER_TURN],
        },
    }


def quota_message(purpose: str, resets_at: float) -> str:
    day = time.strftime("%Y-%m-%d", time.gmtime(resets_at))
    return (f"Your Klaus Plus quota of {_HUMAN.get(purpose, purpose)} for this month is used up; "
            f"it resets on {day}. You can add your own API key under KlausMate Preferences meanwhile.")
```

- [ ] **Step 4: Run to verify they pass.** Both files green.
- [ ] **Step 5: Mutate once each, restore**: in `verdict`, make `PAST_DUE` always active → `test_payment_failed_then_paid` fails; in `charge`, drop the `before < line` half → `test_crossed_80_fires_once` fails. Restore byte-identical, md5s in the report.

---

### Task 3: The proxy — upstream calls, auth, rate limit, the three routes, `/v1/me`, the app

**Files:**
- Create: `service/klausplus/upstream.py`, `service/klausplus/proxy.py`, `service/klausplus/app.py`, `service/klausplus/main.py`, stubs `service/klausplus/billing.py` and `service/klausplus/pages.py` (each: `from fastapi import APIRouter` / `router = APIRouter()` / a docstring "filled by Task 4/5")
- Test: `service/tests/test_proxy.py`, `service/tests/test_app.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `upstream.Upstream(settings)` with `async openai_json(path, body) -> httpx.Response`, `async openai_multipart(path, fields, filename, content, content_type) -> httpx.Response`, `async anthropic(body, stream) -> httpx.Response`; `proxy.router`; `proxy.authenticate(request) -> row` (raises `HTTPException` 401/402/426/503/429); `proxy.wav_seconds(data) -> float` (raises ValueError); `proxy.RateLimiter`; `app.create_app(settings=None, upstream=None, now=time.time) -> FastAPI` with `app.state.settings/store/upstream/now/limiter`; `X-Klaus-Quota` header on every proxied response; `main.app`.

- [ ] **Step 1: Write the failing tests**

`service/tests/test_proxy.py` (a fake upstream records what it was sent and answers canned bodies; the SSE fake emits Anthropic's event framing):
```python
from __future__ import annotations
import io
import json
import struct
import httpx
import pytest
from fastapi.testclient import TestClient
from klausplus import keys
from klausplus.app import create_app
from klausplus.db import next_month_start


def _wav(seconds: float, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(data)) + data


class FakeUpstream:
    def __init__(self):
        self.calls = []

    async def openai_json(self, path, body):
        self.calls.append(("openai_json", path, body))
        n = len(body.get("input") or [])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2]} for i in range(n)],
                                         "usage": {"total_tokens": 7 * n}})

    async def openai_multipart(self, path, fields, filename, content, content_type):
        self.calls.append(("openai_multipart", path, fields, filename, len(content), content_type))
        return httpx.Response(200, json={"text": "hello lecture"})

    async def anthropic(self, body, stream):
        self.calls.append(("anthropic", body, stream))
        if not stream:
            return httpx.Response(200, json={"id": "m", "content": [{"type": "text", "text": "ok"}],
                                             "usage": {"input_tokens": 100, "output_tokens": 20}})
        events = [
            'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":100,"output_tokens":1}}}\n\n',
            'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n',
            'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":25}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b"".join(e.encode() for e in events))


@pytest.fixture
def world(settings, now):
    up = FakeUpstream()
    clock = {"t": now}
    app = create_app(settings, upstream=up, now=lambda: clock["t"])
    store = app.state.store
    cid = store.upsert_customer("cus_1", "a@b.c", now)
    key = keys.mint()
    store.set_key_hash(cid, keys.hash_key(key))
    store.set_subscription("cus_1", "active", int(now) + 20 * 86400, False, now)
    return {"app": app, "client": TestClient(app), "up": up, "store": store, "cid": cid, "key": key, "clock": clock}


def _h(world, purpose, version="0.2.0", key=None):
    return {"Authorization": f"Bearer {key or world['key']}", "X-Klaus-Purpose": purpose, "X-Klaus-Client": version}


def test_healthz_is_open(world):
    assert world["client"].get("/healthz").json() == {"ok": True}


def test_embeddings_forward_and_meter(world):
    r = world["client"].post("/v1/embeddings", json={"model": "text-embedding-3-large", "input": ["a", "b"], "dimensions": 1024},
                             headers=_h(world, "embed"))
    assert r.status_code == 200 and len(r.json()["data"]) == 2
    assert world["up"].calls[0][:2] == ("openai_json", "/embeddings")
    q = json.loads(r.headers["X-Klaus-Quota"])
    assert q["counters"]["embed"]["used"] == 14


def test_unknown_key_401_and_missing_purpose_400(world):
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed", key="kp_" + "0" * 32)).status_code == 401
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]},
                                headers={"Authorization": f"Bearer {world['key']}", "X-Klaus-Client": "0.2.0"}).status_code == 400


def test_version_floor_426_and_pause_503(world, settings):
    assert world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed", version="0.1.9")).status_code == 426
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "paused": True})
    r = world["client"].post("/v1/embeddings", json={"input": ["a"]}, headers=_h(world, "embed"))
    assert r.status_code == 503 and "maintenance" in r.json()["error"]["message"].lower()


def test_transcription_meters_audio_seconds_and_refuses_non_wav(world):
    wav = _wav(90.0)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "gpt-4o-mini-transcribe", "response_format": "json", "language": "en"},
                             files={"file": ("chunk.wav", wav, "audio/wav")}, headers=_h(world, "transcribe"))
    assert r.status_code == 200 and r.json()["text"] == "hello lecture"
    assert json.loads(r.headers["X-Klaus-Quota"])["counters"]["transcribe"]["used"] == 90
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", b"not a wav", "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 400


def test_transcription_402_at_month_cap_and_daily_cap(world, settings):
    world["store"].add_usage(world["cid"], "2026-09", "audio_seconds", settings.quota_audio_seconds - 10)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(30.0), "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 402 and "resets on 2026-10-01" in r.json()["error"]["message"]
    world["clock"]["t"] = next_month_start(world["clock"]["t"]) + 1
    world["store"].add_daily_audio(world["cid"], "2026-10-01", settings.audio_day_seconds)
    r = world["client"].post("/v1/audio/transcriptions", data={"model": "x"}, files={"file": ("c.wav", _wav(30.0), "audio/wav")},
                             headers=_h(world, "transcribe"))
    assert r.status_code == 402 and "today" in r.json()["error"]["message"]


def test_messages_purpose_routing_and_non_stream_metering(world):
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "embed")).status_code == 400
    r = world["client"].post("/v1/messages", json=body, headers=_h(world, "judge"))
    assert r.status_code == 200 and json.loads(r.headers["X-Klaus-Quota"])["counters"]["judge"]["used"] == 120
    assert world["up"].calls[-1][2] is False


def test_messages_stream_relays_sse_and_meters_after(world):
    body = {"model": "claude-sonnet-5", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with world["client"].stream("POST", "/v1/messages", json=body, headers=_h(world, "assistant")) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = b"".join(r.iter_bytes()).decode()
    assert "message_stop" in text and '"text":"hi"' in text
    assert world["store"].usage(world["cid"], "2026-09")["assistant_tokens"] == 125


def test_messages_402_when_judge_quota_spent(world, settings):
    world["store"].add_usage(world["cid"], "2026-09", "judge_tokens", settings.quota_judge_tokens)
    body = {"model": "claude-sonnet-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
    assert world["client"].post("/v1/messages", json=body, headers=_h(world, "judge")).status_code == 402


def test_refused_subscription_402_with_reason(world):
    world["store"].set_subscription("cus_1", "unpaid", 0, False, world["clock"]["t"])
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    assert r.status_code == 402 and "unpaid" in r.json()["error"]["message"]


def test_me_snapshot(world):
    r = world["client"].get("/v1/me", headers=_h(world, "embed"))
    j = r.json()
    assert j["plan"] == "plus" and j["status"] == "active" and j["quota"]["human"]["cards"] == [0, 3000]
    assert j["min_client_version"] == "0.2.0" and j["period_end"] > 0


def test_rate_limit_429(world, settings):
    world["app"].state.limiter.per_minute = 3
    for _ in range(3):
        assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 200
    assert world["client"].get("/v1/me", headers=_h(world, "embed")).status_code == 429


def test_wav_seconds():
    from klausplus.proxy import wav_seconds
    assert abs(wav_seconds(_wav(12.5)) - 12.5) < 0.01
    with pytest.raises(ValueError):
        wav_seconds(b"RIFFxxxxWAVEjunk")
```

`service/tests/test_app.py` (the log never carries a body):
```python
import logging
from fastapi.testclient import TestClient
from klausplus import keys
from klausplus.app import create_app


def test_logs_carry_no_body_and_no_key(settings, now, caplog):
    class Up:
        async def openai_json(self, path, body):
            import httpx
            return httpx.Response(200, json={"data": [], "usage": {"total_tokens": 3}})
    app = create_app(settings, upstream=Up(), now=lambda: now)
    cid = app.state.store.upsert_customer("cus_1", "", now)
    key = keys.mint()
    app.state.store.set_key_hash(cid, keys.hash_key(key))
    app.state.store.set_subscription("cus_1", "active", int(now) + 86400, False, now)
    with caplog.at_level(logging.INFO, logger="klausplus"):
        TestClient(app).post("/v1/embeddings", json={"input": ["SECRET LECTURE TEXT"]},
                             headers={"Authorization": f"Bearer {key}", "X-Klaus-Purpose": "embed", "X-Klaus-Client": "0.2.0"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "POST /v1/embeddings 200" in text and keys.hash_key(key)[:8] in text
    assert "SECRET" not in text and key not in text
```

- [ ] **Step 2: Run to verify they fail** — ImportError on `klausplus.app`.

- [ ] **Step 3: Implement**

`service/klausplus/upstream.py`:
```python
"""The only module that talks to a provider. Keys enter here from Settings and nowhere else."""
from __future__ import annotations

import httpx

from .config import Settings

ANTHROPIC_VERSION = "2023-06-01"


class Upstream:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0))

    async def openai_json(self, path: str, body: dict) -> httpx.Response:
        return await self._client.post(f"{self._s.openai_base}{path}", json=body,
                                       headers={"Authorization": f"Bearer {self._s.openai_api_key}"})

    async def openai_multipart(self, path: str, fields: dict, filename: str, content: bytes, content_type: str) -> httpx.Response:
        return await self._client.post(f"{self._s.openai_base}{path}", data=fields,
                                       files={"file": (filename, content, content_type)},
                                       headers={"Authorization": f"Bearer {self._s.openai_api_key}"})

    async def anthropic(self, body: dict, stream: bool) -> httpx.Response:
        req = self._client.build_request("POST", f"{self._s.anthropic_base}/v1/messages", json=body, headers={
            "x-api-key": self._s.anthropic_api_key, "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"})
        return await self._client.send(req, stream=stream)

    async def aclose(self) -> None:
        await self._client.aclose()
```

`service/klausplus/proxy.py`:
```python
"""Auth, limits and the three proxied routes. Bodies pass through; only counters stay."""
from __future__ import annotations

import json
import struct
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import entitlement, keys, meter

router = APIRouter()


def _err(status: int, message: str, kind: str = "klaus_plus") -> HTTPException:
    return HTTPException(status_code=status, detail={"type": kind, "message": message})


def _version_tuple(v: str) -> tuple:
    out = []
    for part in (v or "0").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


class RateLimiter:
    """Requests per minute per customer — a single-machine service, memory is fine."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, customer_id: int, now: float) -> bool:
        with self._lock:
            hits = [t for t in self._hits.get(customer_id, []) if now - t < 60.0]
            if len(hits) >= self.per_minute:
                self._hits[customer_id] = hits
                return False
            hits.append(now)
            self._hits[customer_id] = hits
            return True


def authenticate(request: Request, purpose_required: bool = True) -> Any:
    st = request.app.state
    settings, store, now = st.settings, st.store, st.now()
    if settings.paused:
        raise _err(503, "Klaus Plus is paused for maintenance — try again later, or use your own API key.")
    if _version_tuple(request.headers.get("X-Klaus-Client", "")) < _version_tuple(settings.min_client_version):
        raise _err(426, "This Klaus is too old for Klaus Plus — update it from Tools → Add-ons.")
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    row = store.customer_by_hash(keys.hash_key(token)) if keys.looks_like_key(token) else None
    if row is None:
        raise _err(401, "Klaus Plus key not recognised — check it under KlausMate Preferences.")
    state, reason = entitlement.verdict(row, now, settings.grace_days)
    if state != "active":
        raise _err(402, f"Klaus Plus is not active ({reason}) — manage your subscription under KlausMate Preferences.")
    if not st.limiter.allow(int(row["id"]), now):
        raise _err(429, "Too many requests — Klaus Plus allows 60 a minute; wait a moment.")
    purpose = request.headers.get("X-Klaus-Purpose", "")
    if purpose_required and purpose not in meter.PURPOSES:
        raise _err(400, "Missing or unknown X-Klaus-Purpose header.")
    request.state.customer = row
    request.state.purpose = purpose
    return row


def _quota_header(request: Request, customer_id: int) -> dict:
    st = request.app.state
    return {"X-Klaus-Quota": json.dumps(meter.snapshot(st.store, st.settings, customer_id, st.now()))}


def _log(request: Request, status: int, metered: int, started: float) -> None:
    row = getattr(request.state, "customer", None)
    prefix = (row["key_hash"] or "")[:8] if row is not None else "-"
    request.app.state.log.info("%s %s %d key=%s ms=%d metered=%d", request.method, request.url.path, status, prefix,
                               int((time.time() - started) * 1000), metered)


def wav_seconds(data: bytes) -> float:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, rate, channels, bits, data_len = 12, 0, 0, 0, 0
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt " and size >= 16:
            _fmt, channels, rate, _br, _ba, bits = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            data_len = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if not (rate and channels and bits and data_len):
        raise ValueError("WAVE header incomplete")
    return data_len / float(rate * channels * (bits // 8))


@router.get("/v1/me")
def me(request: Request) -> JSONResponse:
    started = time.time()
    row = authenticate(request, purpose_required=False)
    st = request.app.state
    body = {"plan": "plus", "status": row["status"], "period_end": int(row["period_end"] or 0),
            "cancel_at_period_end": bool(row["cancel_at_period_end"]),
            "quota": meter.snapshot(st.store, st.settings, int(row["id"]), st.now()),
            "min_client_version": st.settings.min_client_version}
    _log(request, 200, 0, started)
    return JSONResponse(body, headers=_quota_header(request, int(row["id"])))


@router.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "embed":
        raise _err(400, "X-Klaus-Purpose must be 'embed' for /v1/embeddings.")
    raw = await request.body()
    if len(raw) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    body = json.loads(raw or b"{}")
    inputs = body.get("input") if isinstance(body.get("input"), list) else [body.get("input") or ""]
    guess = sum(len(str(t)) for t in inputs) // 4
    ok, _ = meter.check(st.store, st.settings, int(row["id"]), "embed", guess, st.now())
    if not ok:
        raise _err(402, meter.quota_message("embed", meter.snapshot(st.store, st.settings, int(row["id"]), st.now())["resets_at"]))
    resp = await st.upstream.openai_json("/embeddings", body)
    metered = 0
    if resp.status_code == 200:
        try:
            metered = int(resp.json().get("usage", {}).get("total_tokens") or guess)
        except ValueError:
            metered = guess
        meter.charge(st.store, st.settings, int(row["id"]), "embed", metered, st.now())
    _log(request, resp.status_code, metered, started)
    return Response(resp.content, status_code=resp.status_code, media_type="application/json",
                    headers=_quota_header(request, int(row["id"])))


@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    if request.state.purpose != "transcribe":
        raise _err(400, "X-Klaus-Purpose must be 'transcribe' for /v1/audio/transcriptions.")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise _err(400, "Missing multipart field 'file'.")
    content = await upload.read()
    if len(content) > st.settings.max_audio_bytes:
        raise _err(413, "Audio chunk too large (25 MB max).")
    try:
        seconds = int(round(wav_seconds(content)))
    except ValueError:
        raise _err(400, "Only WAV audio is accepted.")
    cid = int(row["id"])
    if not meter.check_daily_audio(st.store, st.settings, cid, seconds, st.now()):
        raise _err(402, "Klaus Plus transcribes at most 240 minutes a day and you have reached today's limit; more tomorrow.")
    ok, _ = meter.check(st.store, st.settings, cid, "transcribe", seconds, st.now())
    if not ok:
        raise _err(402, meter.quota_message("transcribe", meter.snapshot(st.store, st.settings, cid, st.now())["resets_at"]))
    fields = {k: str(v) for k, v in form.items() if k != "file" and isinstance(v, str)}
    resp = await st.upstream.openai_multipart("/audio/transcriptions", fields, getattr(upload, "filename", "chunk.wav") or "chunk.wav",
                                              content, getattr(upload, "content_type", "audio/wav") or "audio/wav")
    metered = 0
    if resp.status_code == 200:
        metered = seconds
        meter.charge(st.store, st.settings, cid, "transcribe", seconds, st.now())
    _log(request, resp.status_code, metered, started)
    return Response(resp.content, status_code=resp.status_code, media_type="application/json", headers=_quota_header(request, cid))


def _usage_from_sse_line(line: bytes, acc: dict) -> None:
    if not line.startswith(b"data: "):
        return
    try:
        obj = json.loads(line[6:])
    except ValueError:
        return
    if obj.get("type") == "message_start":
        acc["in"] = int(((obj.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
    elif obj.get("type") == "message_delta":
        acc["out"] = int((obj.get("usage") or {}).get("output_tokens") or 0)


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    started = time.time()
    row = authenticate(request)
    st = request.app.state
    purpose = request.state.purpose
    if purpose not in ("judge", "assistant"):
        raise _err(400, "X-Klaus-Purpose must be 'judge' or 'assistant' for /v1/messages.")
    raw = await request.body()
    if len(raw) > st.settings.max_json_bytes:
        raise _err(413, "Request too large.")
    body = json.loads(raw or b"{}")
    cid = int(row["id"])
    ok, _ = meter.check(st.store, st.settings, cid, purpose, 1, st.now())
    if not ok:
        raise _err(402, meter.quota_message(purpose, meter.snapshot(st.store, st.settings, cid, st.now())["resets_at"]))
    stream = bool(body.get("stream"))
    resp = await st.upstream.anthropic(body, stream)
    if not stream or resp.status_code != 200:
        content = await resp.aread() if hasattr(resp, "aread") else resp.content
        metered = 0
        if resp.status_code == 200:
            try:
                u = json.loads(content).get("usage") or {}
                metered = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
            except ValueError:
                metered = 0
            meter.charge(st.store, st.settings, cid, purpose, metered, st.now())
        _log(request, resp.status_code, metered, started)
        return Response(content, status_code=resp.status_code, media_type="application/json", headers=_quota_header(request, cid))

    acc = {"in": 0, "out": 0}

    async def relay():
        buf = b""
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    _usage_from_sse_line(line.rstrip(b"\r"), acc)
        finally:
            metered = acc["in"] + acc["out"]
            meter.charge(st.store, st.settings, cid, purpose, metered, st.now())
            _log(request, 200, metered, started)
            await resp.aclose()

    return StreamingResponse(relay(), media_type="text/event-stream", headers=_quota_header(request, cid))
```

`service/klausplus/app.py`:
```python
"""create_app(): the one place routers, state and logging are wired."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import billing, pages, proxy
from .config import Settings
from .db import Store, connect
from .upstream import Upstream


def create_app(settings: Settings | None = None, upstream: Any = None, now: Callable[[], float] = time.time) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Klaus Plus", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.store = Store(connect(settings.database_path))
    app.state.upstream = upstream or Upstream(settings)
    app.state.now = now
    app.state.limiter = proxy.RateLimiter(settings.rate_per_minute)
    app.state.log = logging.getLogger("klausplus")

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"type": "klaus_plus", "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    app.include_router(proxy.router)
    app.include_router(billing.router)
    app.include_router(pages.router)
    return app
```

`service/klausplus/main.py`:
```python
import logging
from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = create_app()
```

Stubs `service/klausplus/billing.py` and `service/klausplus/pages.py`:
```python
"""Filled by Task 4 (billing) / Task 5 (pages)."""
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 4: Run to verify they pass** — `python -m pytest -q` in `service/`: all green. `uvicorn klausplus.main:app --port 8080` with `DATABASE_PATH=/tmp/k.sqlite3` starts and `/healthz` answers (no keys needed to boot).
- [ ] **Step 5: Mutate once, restore**: drop the `message_delta` branch in `_usage_from_sse_line` → the stream metering pin fails (100 ≠ 125); make `authenticate` skip the version check → the 426 pin fails. Restore byte-identical, md5s recorded.


---

### Task 4: Billing — Checkout, welcome and the key, webhooks, portal, recovery, email, the Stripe setup script

**Files:**
- Modify: `service/klausplus/billing.py` (replace the stub)
- Create: `service/klausplus/email.py`, `service/klausplus/templates.py` (the billing pages; Task 5 appends the legal pages to the same module), `service/scripts/stripe_setup.py`
- Test: `service/tests/test_billing.py`

**Interfaces:**
- Consumes: Tasks 1–3 (`Store`, `keys`, `entitlement.apply_event/period_end_of`, `proxy.authenticate`, `Settings.email_enabled`, `STRIPE_API_VERSION`).
- Produces: `billing.router` with `GET /` (landing), `GET /subscribe?plan=monthly|yearly`, `GET /welcome?session_id=`, `POST /stripe/webhook`, `POST /v1/portal`, `GET /recover` + `POST /recover`; seams `billing._stripe(settings)`, `billing._construct_event(payload, sig, secret) -> dict`; `email.enabled(settings)`, `email.send(settings, to, subject, html) -> bool`, `email.send_key_email(settings, to, key)`, `email.send_quota_notice(settings, to, purpose, human_line)`; `templates.landing(...)`, `templates.welcome(...)`, `templates.recover_form()`, `templates.recover_done()`.

- [ ] **Step 1: Write the failing tests**

`service/tests/test_billing.py`:
```python
from __future__ import annotations
import re
import types
import pytest
from fastapi.testclient import TestClient
from klausplus import billing, email, keys
from klausplus.app import create_app


class FakeStripe:
    """The four calls billing makes, recorded; shaped like the SDK's objects (attribute access)."""

    def __init__(self):
        self.created = []
        self.api_key = None
        self.api_version = None
        self.checkout = types.SimpleNamespace(Session=types.SimpleNamespace(create=self._create_session, retrieve=self._retrieve))
        self.billing_portal = types.SimpleNamespace(Session=types.SimpleNamespace(create=self._portal))
        self.session = {"id": "cs_1", "payment_status": "paid", "customer": "cus_1",
                        "customer_details": {"email": "a@b.c"},
                        "subscription": {"id": "sub_1", "status": "active", "current_period_end": 1_900_000_000,
                                         "cancel_at_period_end": False, "customer": "cus_1"}}

    def _create_session(self, **kw):
        self.created.append(kw)
        return types.SimpleNamespace(url="https://checkout.stripe.test/cs_1")

    def _retrieve(self, sid, expand=None):
        assert sid == "cs_1" and "subscription" in (expand or [])
        return _Obj(self.session)

    def _portal(self, **kw):
        self.created.append(("portal", kw))
        return types.SimpleNamespace(url="https://portal.stripe.test/p")


class _Obj(dict):
    """Stripe objects allow both obj.key and obj['key']."""
    def __getattr__(self, k):
        v = self[k]
        return _Obj(v) if isinstance(v, dict) else v


@pytest.fixture
def world(settings, now, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(billing, "_stripe", lambda s: fake)
    sent = []
    monkeypatch.setattr(email, "_post", lambda settings, payload: sent.append(payload) or True)
    app = create_app(settings, upstream=object(), now=lambda: now)
    return {"app": app, "client": TestClient(app), "stripe": fake, "sent": sent, "store": app.state.store}


def test_subscribe_redirects_to_checkout_with_the_right_price(world, settings):
    r = world["client"].get("/subscribe?plan=yearly", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://checkout.stripe.test/cs_1"
    kw = world["stripe"].created[0]
    assert kw["mode"] == "subscription" and kw["line_items"] == [{"price": "price_y", "quantity": 1}]
    assert kw["success_url"] == "https://klaus.test/welcome?session_id={CHECKOUT_SESSION_ID}"
    world["client"].get("/subscribe", follow_redirects=False)
    assert world["stripe"].created[1]["line_items"][0]["price"] == "price_m"


def test_welcome_mints_once_shows_once_and_emails(world, settings):
    r = world["client"].get("/welcome?session_id=cs_1")
    assert r.status_code == 200 and "kp_" in r.text
    row = world["store"].customer_by_stripe_id("cus_1")
    assert row["status"] == "active" and row["period_end"] == 1_900_000_000 and row["key_hash"]
    key = re.search(r"kp_[0-9a-f]{32}", r.text).group(0)
    assert keys.hash_key(key) == row["key_hash"]
    assert not settings.email_enabled and "no email was sent" in r.text.lower() and world["sent"] == []
    r2 = world["client"].get("/welcome?session_id=cs_1")
    assert r2.status_code == 200 and "kp_" not in r2.text and "already" in r2.text.lower()


def test_welcome_emails_when_enabled(world, settings):
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    r = world["client"].get("/welcome?session_id=cs_1")
    assert r.status_code == 200 and len(world["sent"]) == 1
    assert world["sent"][0]["to"] == ["a@b.c"] and "kp_" in world["sent"][0]["html"]


def test_welcome_unpaid_session_is_refused(world):
    world["stripe"].session["payment_status"] = "unpaid"
    assert world["client"].get("/welcome?session_id=cs_1").status_code == 402


def test_webhook_verifies_and_applies_once(world, monkeypatch, now):
    events = [{"id": "evt_1", "type": "customer.subscription.updated",
               "data": {"object": {"customer": "cus_9", "status": "active", "current_period_end": int(now) + 86400}}}]
    monkeypatch.setattr(billing, "_construct_event", lambda payload, sig, secret: events[0])
    r = world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200 and world["store"].customer_by_stripe_id("cus_9")["status"] == "active"
    events[0]["data"]["object"]["status"] = "canceled"
    r = world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200 and world["store"].customer_by_stripe_id("cus_9")["status"] == "active"  # replay ignored


def test_webhook_bad_signature_400(world, monkeypatch):
    def boom(payload, sig, secret):
        raise ValueError("bad sig")
    monkeypatch.setattr(billing, "_construct_event", boom)
    assert world["client"].post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"}).status_code == 400


def test_portal_needs_a_key_and_returns_a_url(world, now):
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    key = keys.mint()
    world["store"].set_key_hash(cid, keys.hash_key(key))
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    h = {"Authorization": f"Bearer {key}", "X-Klaus-Client": "0.2.0"}
    assert world["client"].post("/v1/portal", headers=h).json() == {"url": "https://portal.stripe.test/p"}
    assert world["client"].post("/v1/portal", headers={"Authorization": "Bearer kp_" + "1" * 32, "X-Klaus-Client": "0.2.0"}).status_code == 401
    assert world["stripe"].created[-1][1]["customer"] == "cus_1"


def test_recover_rotates_the_key_and_never_enumerates(world, settings, now):
    world["app"].state.settings = settings.__class__(**{**settings.__dict__, "resend_api_key": "re_x", "resend_from": "Klaus <plus@klaus.test>"})
    cid = world["store"].upsert_customer("cus_1", "a@b.c", now)
    world["store"].set_key_hash(cid, "old" * 21 + "x")
    world["store"].set_subscription("cus_1", "active", int(now) + 86400, False, now)
    r = world["client"].post("/recover", data={"email": "A@B.C"})
    assert r.status_code == 200 and "on its way" in r.text.lower()
    new_hash = world["store"].customer_by_id(cid)["key_hash"]
    assert new_hash != "old" * 21 + "x" and len(world["sent"]) == 1
    r = world["client"].post("/recover", data={"email": "nobody@x.y"})
    assert r.status_code == 200 and "on its way" in r.text.lower() and len(world["sent"]) == 1


def test_landing_links(world):
    t = world["client"].get("/").text
    assert "/subscribe?plan=monthly" in t and "/subscribe?plan=yearly" in t and "/terms" in t and "/privacy" in t


def test_email_disabled_without_sender(settings):
    assert not email.enabled(settings)
    assert email.send(settings, "a@b.c", "s", "<p>x</p>") is False
```

- [ ] **Step 2: Run to verify they fail** — the stub router answers 404 for every route.

- [ ] **Step 3: Implement**

`service/klausplus/email.py`:
```python
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


def send_quota_notice(settings: Settings, to: str, human_line: str) -> bool:
    html = (f"<p>Heads-up: you have used 80% of one of your Klaus Plus quotas this month ({human_line}).</p>"
            f"<p>Quotas reset on the 1st. If you hit a cap, Klaus will say so and you can add your own API key meanwhile.</p>")
    return send(settings, to, "Klaus Plus: 80% of a quota used", html)
```

`service/klausplus/templates.py` (Task 5 appends `terms(...)` and `privacy(...)` below the same `_PAGE` frame):
```python
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
```

`service/klausplus/billing.py`:
```python
"""Stripe in one module: Checkout, the welcome page that mints the key, webhooks, the portal, recovery.

The service stores the key's hash only. The key is shown once on the
welcome page and, when email is enabled, sent once; recovery mints a NEW
key rather than re-sending an old one nobody can read back.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import email, entitlement, keys, templates
from .config import STRIPE_API_VERSION, Settings
from .proxy import authenticate

router = APIRouter()
WEBHOOK_EVENTS = ("checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
                  "customer.subscription.deleted", "invoice.paid", "invoice.payment_failed")


def _stripe(settings: Settings) -> Any:
    import stripe  # the SDK reads its key from the module; set both every call so a reload cannot drift
    stripe.api_key = settings.stripe_secret_key
    stripe.api_version = STRIPE_API_VERSION
    return stripe


def _construct_event(payload: bytes, sig: str, secret: str) -> dict:
    import stripe
    ev = stripe.Webhook.construct_event(payload, sig, secret)
    return ev.to_dict_recursive() if hasattr(ev, "to_dict_recursive") else dict(ev)


def _operator(settings: Settings) -> str:
    return settings.operator_name or "Klaus"


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> str:
    return templates.landing(_operator(request.app.state.settings), "$12", "$99")


@router.get("/subscribe")
def subscribe(request: Request, plan: str = "monthly") -> RedirectResponse:
    s = request.app.state.settings
    price = s.stripe_price_yearly if plan == "yearly" else s.stripe_price_monthly
    session = _stripe(s).checkout.Session.create(
        mode="subscription", line_items=[{"price": price, "quantity": 1}], allow_promotion_codes=True,
        success_url=f"{s.public_base_url}/welcome?session_id={{CHECKOUT_SESSION_ID}}", cancel_url=f"{s.public_base_url}/")
    return RedirectResponse(session.url, status_code=303)


@router.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, session_id: str = "") -> Any:
    st = request.app.state
    s: Settings = st.settings
    if not session_id:
        return HTMLResponse(templates.paywall(_operator(s), "Missing checkout session."), status_code=400)
    session = _stripe(s).checkout.Session.retrieve(session_id, expand=["subscription"])
    if session["payment_status"] not in ("paid", "no_payment_required"):
        return HTMLResponse(templates.paywall(_operator(s), "This checkout has not been paid."), status_code=402)
    now = st.now()
    cus = str(session["customer"])
    email_addr = str(((session.get("customer_details") or {}).get("email")) or "")
    cid = st.store.upsert_customer(cus, email_addr, now)
    sub = session.get("subscription") or {}
    if sub:
        st.store.set_subscription(cus, str(sub.get("status") or "active"), entitlement.period_end_of(sub),
                                  bool(sub.get("cancel_at_period_end")), now)
    row = st.store.customer_by_id(cid)
    if row["key_hash"]:
        return HTMLResponse(templates.welcome(_operator(s), None, False, already=True))
    key = keys.mint()
    st.store.set_key_hash(cid, keys.hash_key(key))
    emailed = email.send_key_email(s, email_addr, key)
    return HTMLResponse(templates.welcome(_operator(s), key, emailed, already=False))


@router.post("/stripe/webhook")
async def webhook(request: Request) -> JSONResponse:
    st = request.app.state
    payload = await request.body()
    try:
        event = _construct_event(payload, request.headers.get("stripe-signature", ""), st.settings.stripe_webhook_secret)
    except Exception:
        raise HTTPException(status_code=400, detail={"type": "stripe", "message": "bad signature"})
    if event.get("type") in WEBHOOK_EVENTS:
        entitlement.apply_event(st.store, event, st.now())
    return JSONResponse({"received": True})


@router.post("/v1/portal")
def portal(request: Request) -> JSONResponse:
    row = authenticate(request, purpose_required=False)
    s = request.app.state.settings
    session = _stripe(s).billing_portal.Session.create(customer=row["stripe_customer_id"], return_url=f"{s.public_base_url}/")
    return JSONResponse({"url": session.url})


@router.get("/recover", response_class=HTMLResponse)
def recover_form(request: Request) -> str:
    return templates.recover_form(_operator(request.app.state.settings))


@router.post("/recover", response_class=HTMLResponse)
def recover(request: Request, email_addr: str = Form(alias="email")) -> str:
    st = request.app.state
    row = st.store.customer_by_email(email_addr.strip())
    if row is not None and entitlement.verdict(row, st.now(), st.settings.grace_days)[0] == "active" and email.enabled(st.settings):
        key = keys.mint()
        st.store.set_key_hash(int(row["id"]), keys.hash_key(key))
        email.send_key_email(st.settings, str(row["email"]), key)
    return templates.recover_done(_operator(st.settings))
```

`service/scripts/stripe_setup.py` (Pouya runs it; idempotent; prints the secrets to set):
```python
"""Create the Klaus Plus product, its two prices and the webhook endpoint. Run by the operator:

    STRIPE_SECRET_KEY=sk_test_... PUBLIC_BASE_URL=https://klausmate.fly.dev python scripts/stripe_setup.py

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
    base = (os.environ.get("PUBLIC_BASE_URL") or "https://klausmate.fly.dev").rstrip("/")
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
```

- [ ] **Step 4: Run to verify they pass** — `python -m pytest -q` green (the whole service suite).
- [ ] **Step 5: Mutate once, restore**: in `welcome`, remove the `if row["key_hash"]` guard → `test_welcome_mints_once_shows_once_and_emails` fails; in `recover`, drop the `verdict == "active"` clause → the enumeration pin still passes but `test_recover_rotates_the_key_and_never_enumerates`'s second half must still hold — instead mutate `customer_by_email` to ignore case → the pin's `A@B.C` lookup fails. Restore byte-identical, md5s recorded.

---

### Task 5: Terms and privacy pages

**Files:**
- Modify: `service/klausplus/pages.py` (replace the stub), `service/klausplus/templates.py` (append `terms`, `privacy`)
- Test: `service/tests/test_pages.py`

**Interfaces:**
- Consumes: `templates._frame`, `Settings.operator_*`.
- Produces: `GET /terms`, `GET /privacy` (HTML), `templates.terms(operator, email, country)`, `templates.privacy(operator, email)`.

- [ ] **Step 1: Write the failing test**

`service/tests/test_pages.py`:
```python
from fastapi.testclient import TestClient
from klausplus.app import create_app


def test_terms_and_privacy_render_operator_and_promises(settings, now):
    c = TestClient(create_app(settings, upstream=object(), now=lambda: now))
    t = c.get("/terms").text
    assert "Klaus Test" in t and "Testland" in t and "ops@klaus.test" in t and "14 days" in t and "period end" in t.lower()
    p = c.get("/privacy").text
    for word in ("Stripe", "OpenAI", "Anthropic", "Resend", "Fly.io", "not stored", "13 months", "30 days"):
        assert word in p, word
    assert "lecture" in p.lower() and "ops@klaus.test" in p
```

- [ ] **Step 2: Run to verify it fails** — 404s.

- [ ] **Step 3: Implement**

Append to `service/klausplus/templates.py`:
```python
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
service, or to send content that the providers' own policies prohibit. You are responsible for the material you send through the service.</p>
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
```

`service/klausplus/pages.py`:
```python
"""The two legal pages; the text lives in templates.py, the operator's details in Settings."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from . import templates

router = APIRouter()


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request) -> str:
    s = request.app.state.settings
    return templates.terms(s.operator_name or "Klaus", s.operator_email, s.operator_country or "the operator's country of residence")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> str:
    s = request.app.state.settings
    return templates.privacy(s.operator_name or "Klaus", s.operator_email)
```

- [ ] **Step 4: Run to verify it passes**; the whole service suite stays green.
- [ ] **Step 5: Mutate once, restore**: drop the "14 days" sentence → the pin fails. Restore.


---

### Task 6: The add-on's `plus` module — key, endpoint, verdict cache, quota readout

**Files:**
- Create: `klausmate/plus.py`
- Test: `tests/test_plus.py`

**Interfaces:**
- Consumes: nothing from the service at build time; `klausmate/manifest.json` (`human_version`) at run time.
- Produces (all aqt-free, stdlib): constants `KEY = "klaus_plus_key"`, `CACHE = "klaus_plus_cache"`, `BASE = "klaus_plus_base"`, `DEFAULT_BASE = "https://klausmate.fly.dev"`, `TOKENS_PER_CARD = 250`, `TOKENS_PER_TURN = 6000`, `CACHE_TTL_S = 6 * 3600`, `GRACE_S = 7 * 86400`; `Endpoint(NamedTuple)` with `base: str`, `headers: dict[str, str]`; `client_version() -> str`; `key(cfg) -> str`; `base(cfg) -> str`; `active(cfg, now=None) -> bool`; `endpoint(cfg, purpose) -> Endpoint` (the Plus endpoint for a tagged call); `parse_quota(headers) -> dict | None`; `remember(cfg, snapshot, status, write_config, now=None) -> dict`; `note_refusal(cfg, status_code, write_config, now=None) -> None`; `refresh(get_config, write_config, urlopen=None) -> dict` (GET `/v1/me`; returns the new cache); `status_line(cache) -> str`; `portal_url(cfg, urlopen=None) -> str` (POST `/v1/portal`).

- [ ] **Step 1: Write the failing pins** — `tests/test_plus.py` (bootstrap copied from `tests/test_page_store.py`; the module imports nothing from aqt):

```python
from __future__ import annotations
import io, json, os, sys, time, urllib.request
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, section, report, install
install()
import klausmate.plus as plus  # noqa: E402

section("keys, base and the client version")
check("no key → not active", plus.active({}) is False and plus.key({}) == "")
check("a key alone is active (optimistic until the service says otherwise)", plus.active({"klaus_plus_key": "kp_" + "a" * 32}))
check("whitespace is stripped and a non-key string is not a key", plus.key({"klaus_plus_key": "  kp_" + "b" * 32 + " "}) == "kp_" + "b" * 32
      and plus.key({"klaus_plus_key": "sk-abc"}) == "")
check("base defaults and strips a trailing slash", plus.base({}) == plus.DEFAULT_BASE and plus.base({"klaus_plus_base": "https://x.test/"}) == "https://x.test")
check("client_version reads manifest.json's human_version", plus.client_version() == json.load(open("klausmate/manifest.json"))["human_version"])

section("the endpoint carries the bearer key, the purpose and the version")
cfg = {"klaus_plus_key": "kp_" + "c" * 32, "klaus_plus_base": "https://svc.test"}
ep = plus.endpoint(cfg, "judge")
check("base is the service", ep.base == "https://svc.test")
check("headers: bearer key, purpose, client version",
      ep.headers["Authorization"] == "Bearer kp_" + "c" * 32 and ep.headers["X-Klaus-Purpose"] == "judge"
      and ep.headers["X-Klaus-Client"] == plus.client_version())
try:
    plus.endpoint(cfg, "mine")
    check("an unknown purpose raises ValueError", False)
except ValueError:
    check("an unknown purpose raises ValueError", True)

section("the verdict cache: fresh, stale-with-grace, refused")
now = 1_800_000_000.0
written = {}
snap = {"month": "2026-09", "resets_at": now + 86400, "counters": {}, "human": {"lecture_hours": [4.0, 30.0], "cards": [812, 3000], "turns": [31, 200]}}
cache = plus.remember(dict(cfg), snap, "active", written.update, now=now)
check("remember writes klaus_plus_cache with the snapshot, status and checked_at",
      written["klaus_plus_cache"]["status"] == "active" and written["klaus_plus_cache"]["checked_at"] == now
      and written["klaus_plus_cache"]["quota"]["human"]["cards"] == [812, 3000])
cfg2 = dict(cfg, klaus_plus_cache=cache)
check("fresh active → active", plus.active(cfg2, now=now + 3600))
check("stale but within 7-day grace → active", plus.active(cfg2, now=now + 3 * 86400))
check("older than 7 days → not active", plus.active(cfg2, now=now + 8 * 86400) is False)
plus.note_refusal(cfg2, 402, written.update, now=now + 10)
cfg3 = dict(cfg, klaus_plus_cache=written["klaus_plus_cache"])
check("a 402 marks the cache refused and active() is False while fresh", written["klaus_plus_cache"]["status"] == "refused:402"
      and plus.active(cfg3, now=now + 20) is False)
check("a refused verdict expires after the TTL so the service gets asked again", plus.active(cfg3, now=now + 7 * 3600))

section("status_line and parse_quota")
line = plus.status_line({"status": "active", "period_end": now + 15 * 86400, "quota": snap})
check("status line names the plan, the renewal day and the three counters",
      line.startswith("Plus · renews 2027-01-30") and "4.0 of 30 lecture hours" in line and "812 of 3,000 cards" in line and "31 of 200 turns" in line, line)
check("no cache → an honest line", "not checked yet" in plus.status_line({}).lower())
check("parse_quota reads the header and tolerates absence/junk",
      plus.parse_quota({"X-Klaus-Quota": json.dumps(snap)})["human"]["turns"] == [31, 200]
      and plus.parse_quota({}) is None and plus.parse_quota({"X-Klaus-Quota": "{"}) is None)

section("refresh and portal_url go through the seam, never log the key")
calls = []
class _Resp(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body); self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), req.data))
    if req.full_url.endswith("/v1/me"):
        return _Resp(json.dumps({"plan": "plus", "status": "active", "period_end": now + 5 * 86400, "quota": snap,
                                 "min_client_version": "0.2.0"}).encode())
    return _Resp(json.dumps({"url": "https://portal.test/p"}).encode())
written.clear()
out = plus.refresh(lambda: dict(cfg), written.update, urlopen=fake_urlopen)
check("refresh GETs /v1/me with the bearer key and writes the cache",
      calls[0][0] == "https://svc.test/v1/me" and calls[0][1].get("Authorization") == "Bearer kp_" + "c" * 32
      and written["klaus_plus_cache"]["status"] == "active" and out["quota"]["human"]["cards"] == [812, 3000])
check("portal_url POSTs /v1/portal and returns the url",
      plus.portal_url(cfg, urlopen=fake_urlopen) == "https://portal.test/p" and calls[1][0] == "https://svc.test/v1/portal")
def failing(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 402, "quota", {}, io.BytesIO(json.dumps({"error": {"message": "used up"}}).encode()))
written.clear()
out = plus.refresh(lambda: dict(cfg), written.update, urlopen=failing)
check("a 402 on refresh is remembered as refused, message kept, key absent from it",
      out["status"] == "refused:402" and out.get("message") == "used up" and "kp_" not in json.dumps(out))
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails** — `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_plus.py` → ModuleNotFoundError.

- [ ] **Step 3: Write `klausmate/plus.py`**

```python
"""Klaus Plus on the add-on side: the key, the endpoint every tagged call uses, a cached verdict.

Nothing here can gate anything (spec: the add-on is readable Python); the
service refusing the key is the gate. What this module CAN do is be
generous — a cached "active" is honoured for a week when the service is
unreachable — and be honest: a 401/402/426 is remembered so the UI can
say why, and the key never appears in any message or log.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, NamedTuple

KEY = "klaus_plus_key"
CACHE = "klaus_plus_cache"
BASE = "klaus_plus_base"
DEFAULT_BASE = "https://klausmate.fly.dev"
TOKENS_PER_CARD = 250   # the service's own constants (spec D1); shown, never enforced, here
TOKENS_PER_TURN = 6000
CACHE_TTL_S = 6 * 3600
GRACE_S = 7 * 86400
PURPOSES = ("embed", "transcribe", "judge", "assistant")
TIMEOUT_S = 15.0
_urlopen = urllib.request.urlopen


class Endpoint(NamedTuple):
    base: str
    headers: dict


def client_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(__file__), "manifest.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("human_version") or "0")
    except (OSError, ValueError):
        return "0"


def key(cfg: dict) -> str:
    k = str((cfg or {}).get(KEY) or "").strip()
    return k if k.startswith("kp_") and len(k) == 35 else ""


def base(cfg: dict) -> str:
    return (str((cfg or {}).get(BASE) or "").strip() or DEFAULT_BASE).rstrip("/")


def _cache(cfg: dict) -> dict:
    c = (cfg or {}).get(CACHE)
    return c if isinstance(c, dict) else {}


def active(cfg: dict, now: float | None = None) -> bool:
    if not key(cfg):
        return False
    c = _cache(cfg)
    if not c:
        return True
    now = time.time() if now is None else now
    age = now - float(c.get("checked_at") or 0)
    status = str(c.get("status") or "")
    if status.startswith("refused"):
        return age > CACHE_TTL_S  # ask again after the TTL; the service decides
    return age <= GRACE_S


def endpoint(cfg: dict, purpose: str) -> Endpoint:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    return Endpoint(base(cfg), {"Authorization": f"Bearer {key(cfg)}", "X-Klaus-Purpose": purpose,
                                "X-Klaus-Client": client_version()})


def parse_quota(headers: Any) -> dict | None:
    try:
        raw = headers.get("X-Klaus-Quota") if hasattr(headers, "get") else None
        obj = json.loads(raw) if raw else None
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def remember(cfg: dict, snapshot: dict | None, status: str, write_config: Callable[[dict], None],
             now: float | None = None, period_end: float = 0.0, message: str = "") -> dict:
    now = time.time() if now is None else now
    c = {"status": status, "checked_at": now, "period_end": float(period_end or _cache(cfg).get("period_end") or 0)}
    if snapshot is not None:
        c["quota"] = snapshot
    elif _cache(cfg).get("quota"):
        c["quota"] = _cache(cfg)["quota"]
    if message:
        c["message"] = message
    write_config({CACHE: c})
    return c


def note_refusal(cfg: dict, status_code: int, write_config: Callable[[dict], None], now: float | None = None,
                 message: str = "") -> None:
    remember(cfg, None, f"refused:{int(status_code)}", write_config, now=now, message=message)


def _call(cfg: dict, method: str, path: str, urlopen=None) -> tuple[int, dict, dict]:
    ep = endpoint(cfg, "embed")
    req = urllib.request.Request(ep.base + path, data=b"{}" if method == "POST" else None, method=method,
                                 headers={**ep.headers, "Content-Type": "application/json"})
    try:
        with (urlopen or _urlopen)(req, timeout=TIMEOUT_S) as resp:
            return int(getattr(resp, "status", 200) or 200), json.loads(resp.read().decode("utf-8") or "{}"), dict(getattr(resp, "headers", {}) or {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        return int(e.code), body, {}


def refresh(get_config: Callable[[], dict], write_config: Callable[[dict], None], urlopen=None) -> dict:
    cfg = get_config() or {}
    if not key(cfg):
        return {}
    try:
        status, body, _ = _call(cfg, "GET", "/v1/me", urlopen)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[klausmate] Klaus Plus check failed: {exc.__class__.__name__}")
        return _cache(cfg)
    if status == 200 and isinstance(body, dict):
        return remember(cfg, body.get("quota") if isinstance(body.get("quota"), dict) else None,
                        str(body.get("status") or "active"), write_config, period_end=float(body.get("period_end") or 0))
    msg = str(((body or {}).get("error") or {}).get("message") or "")
    return remember(cfg, None, f"refused:{status}", write_config, message=msg)


def portal_url(cfg: dict, urlopen=None) -> str:
    status, body, _ = _call(cfg, "POST", "/v1/portal", urlopen)
    return str(body.get("url") or "") if status == 200 else ""


def status_line(cache: dict) -> str:
    if not cache:
        return "Klaus Plus: not checked yet — press Check."
    status = str(cache.get("status") or "")
    if status.startswith("refused"):
        return f"Klaus Plus: {cache.get('message') or 'refused by the service'} (checked {_day(cache.get('checked_at'))})."
    q = (cache.get("quota") or {}).get("human") or {}
    h, c, t = q.get("lecture_hours") or [0, 0], q.get("cards") or [0, 0], q.get("turns") or [0, 0]
    renews = f" · renews {_day(cache.get('period_end'))}" if cache.get("period_end") else ""
    return (f"Plus{renews} · {h[0]} of {h[1]:g} lecture hours, {c[0]:,} of {c[1]:,} cards, {t[0]} of {t[1]} turns this month")


def _day(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return "?"
```

- [ ] **Step 4: Run to verify it passes** — `0 failed`. Then `python3 -m py_compile "$HOME/Library/Application Support/Anki2/addons21/klausmate/plus.py"`.
- [ ] **Step 5: Mutate once, restore**: make `active` ignore `GRACE_S` (always True with a key) → the "older than 7 days" pin fails; drop `X-Klaus-Purpose` from `endpoint` → the headers pin fails. Restore byte-identical, md5s recorded.

---

### Task 7: The clients take an endpoint; the gates learn about Plus; the sweep says "included"

**Files:**
- Modify: `klausmate/openai_client.py`, `klausmate/anthropic_client.py`, `klausmate/embeddings.py`, `klausmate/index_queue.py` (`missing_key_provider`, `missing_key_message`, `sweep_message`, `offer_model_sweep`), `klausmate/setup_flow.py` (`_embedding_ready`, `KEYS_COPY`)
- Test: `tests/test_openai_client.py`, `tests/test_anthropic_client.py`, `tests/test_klausmate.py` (embeddings section), `tests/test_index_queue.py`, `tests/test_bridge_reentrancy.py` (if it censuses `KEYS_COPY`), `tests/test_setup_crop_theme.py` (if it pins the copy)

**Interfaces:**
- Consumes: `plus.Endpoint`, `plus.active`, `plus.endpoint`, `plus.key`, `plus.note_refusal`, `plus.parse_quota` (Task 6).
- Produces: `openai_client.embed(key, texts, model, dims, timeout=..., endpoint=None)` and `transcribe(key, wav_bytes, model, language="en", prompt="", timeout=..., endpoint=None)` — with `endpoint` given, the URL is `endpoint.base + path` and its headers replace the bearer header; `OpenAIError.message` carries the service's `error.message` when the body has one; `anthropic_client.Client.stream(payload, purpose="assistant", **kw)` and `complete(payload, timeout=..., purpose="assistant")` route to Plus when `plus.active(cfg)`; `index_queue.sweep_message(n_pdfs, n_notes, model, estimate, plus=False)`; `missing_key_provider(cfg)` is `""` with a Plus key; `setup_flow._embedding_ready` true with a Plus key.

- [ ] **Step 1: Write the failing pins** (each in the file's own style):

`tests/test_openai_client.py` — add after the existing transcription pins:
```python
section("an Endpoint replaces the provider: base URL and headers")
calls.clear()
from klausmate import plus as _plus
ep = _plus.Endpoint("https://svc.test", {"Authorization": "Bearer kp_" + "d" * 32, "X-Klaus-Purpose": "embed", "X-Klaus-Client": "0.2.0"})
vecs = oc.embed("", ["a"], "text-embedding-3-large", 1024, endpoint=ep)
url, headers, data, _ = calls[-1]
check("the endpoint's base and headers are used, no provider key needed",
      url == "https://svc.test/embeddings" and headers.get("Authorization") == "Bearer kp_" + "d" * 32
      and headers.get("X-klaus-purpose", headers.get("X-Klaus-Purpose")) == "embed" and len(vecs) == 1)
check("the default endpoint is still the provider", oc.API_BASE == "https://api.openai.com/v1")

section("the service's error message reaches the user")
def quota_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 402, "quota", {}, io.BytesIO(json.dumps({"error": {"message": "used up; resets on 2026-10-01"}}).encode()))
oc._urlopen = quota_urlopen
try:
    oc.embed("", ["a"], "m", 0, endpoint=ep)
    check("402 raises OpenAIError", False)
except oc.OpenAIError as e:
    check("402 raises OpenAIError carrying the service's message verbatim", e.status == 402 and e.user_message() == "used up; resets on 2026-10-01")
oc._urlopen = fake_urlopen
```
(`fake_urlopen` and `calls` are the file's existing fixtures; `urllib.error` and `io` imported at top if not already.)

`tests/test_anthropic_client.py` — add:
```python
section("Plus routing: the client goes to the service with the purpose tag when a key exists")
seen = []
def svc_urlopen(req, timeout=None):
    seen.append((req.full_url, dict(req.headers)))
    return stream_of(TEXT_TURN)  # the file's existing helper over the recorded text_turn fixture
ac._urlopen = svc_urlopen
client = ac.Client(lambda: {"klaus_plus_key": "kp_" + "e" * 32, "klaus_plus_base": "https://svc.test"})
res = client.stream({"model": "claude-sonnet-5", "max_tokens": 5, "messages": []}, purpose="judge")
check("POSTs the service's /v1/messages with the bearer key and purpose, no x-api-key",
      seen[-1][0] == "https://svc.test/v1/messages" and seen[-1][1].get("Authorization") == "Bearer kp_" + "e" * 32
      and seen[-1][1].get("X-klaus-purpose", seen[-1][1].get("X-Klaus-Purpose")) == "judge" and "X-api-key" not in seen[-1][1] and "x-api-key" not in seen[-1][1])
try:
    ac.Client(lambda: {}).complete({"messages": []})
    check("no key at all → LLMError no_key", False)
except ac.LLMError as e:
    check("no key at all → LLMError no_key", e.error_type == "no_key")
```

`tests/test_index_queue.py` — add:
```python
section("Klaus Plus: the key gate and the sweep wording")
check("a Plus key satisfies the key gate", iq.missing_key_provider({"klaus_plus_key": "kp_" + "f" * 32}) == "")
check("no key of either kind still names OpenAI", iq.missing_key_provider({}) == "OpenAI")
msg = iq.sweep_message(2, 100, "text-embedding-3-large", "~1,000 tokens · under $0.01", plus=True)
check("on Plus the sweep is 'included', not billed", "included in Klaus Plus" in msg and "billed to your OpenAI key" not in msg and "$" not in msg)
check("off Plus the estimate is billed to the key", "billed to your OpenAI key" in iq.sweep_message(2, 100, "m", "~x", plus=False))
```
plus a pin that `offer_model_sweep` passes `plus=plus.active(cfg)` (source/AST, the file's `_iq_src` style): `"plus=plus.active(" in _iq_src`.

`tests/test_klausmate.py` embeddings section — add: with `{"klaus_plus_key": "kp_…", "klaus_plus_base": "https://svc.test"}` and `openai_client._urlopen` faked to capture, `OpenAIEmbeddings.embed(["a"])` posts to `https://svc.test/embeddings` with the bearer key and no `api_key_openai` needed.

`setup_flow` pins (in `tests/test_bridge_reentrancy.py`'s setup_flow section or wherever `KEYS_COPY` is censused): `_embedding_ready({"klaus_plus_key": "kp_" + "a" * 32})` is True (the function is pure — call it through the module the file already loads for its source pins; if the file only reads source, add an AST pin that `_embedding_ready` names `plus.key`), and `KEYS_COPY` mentions "Klaus Plus".

- [ ] **Step 2: Run to verify they fail** — TypeErrors on the new keyword arguments; the gate pin returns "OpenAI".

- [ ] **Step 3: Implement**

`klausmate/openai_client.py`: import `from . import plus` (aqt-free); `_request` learns the message: when an `HTTPError` body parses as JSON with `error.message`, use that text as the exception message instead of the raw body, and `OpenAIError.user_message()` returns the message verbatim for 402, 426 and 503 (the service's own wording; 401/403/429/5xx keep their current copy). `embed(..., endpoint: plus.Endpoint | None = None)`: `url = (endpoint.base if endpoint else API_BASE) + "/embeddings"`; headers = `{"Content-Type": "application/json", **(endpoint.headers if endpoint else {"Authorization": f"Bearer {key}"})}`. Same for `transcribe` with `/audio/transcriptions`. Nothing else changes; the existing literal-URL pins stand because the default endpoint is the provider.

`klausmate/anthropic_client.py`: `Client.stream(self, payload, purpose="assistant", **kw)` and `complete(self, payload, timeout=DEFAULT_TIMEOUT_S, purpose="assistant")` call a new `_target(purpose) -> tuple[str, dict]`: if `plus.active(cfg)`: `ep = plus.endpoint(cfg, purpose)` → `(ep.base + "/v1/messages", {**ep.headers, "Content-Type": "application/json"})`; else `(API_BASE + "/v1/messages", self._headers(self._key()))` — so `_key()`'s `no_key` error fires only off Plus. `LLMError.user_message()` returns the body's `error.message` verbatim for 402/426/503 (the file already parses error bodies in `_parse_error_body`).

`klausmate/embeddings.py` `OpenAIEmbeddings.embed`: `cfg = self._get_config() or {}`; if `plus.active(cfg)`: `openai_client.embed("", texts, model, dims, endpoint=plus.endpoint(cfg, "embed"))`; else the current path (the `api_key_openai` check stays for the free tier). On `OpenAIError` with status in (401, 402, 426) while on Plus, call `plus.note_refusal(cfg, status, self._write_config, message=e.user_message())` before re-raising as `EmbeddingError` — `OpenAIEmbeddings.__init__` gains an optional `write_config` callable (default: a no-op) that `provider_from_config` wires to the package's `write_config`.

`klausmate/index_queue.py`: `missing_key_provider`: `if plus.key(cfg): return ""` first. `missing_key_message` copy gains "…or subscribe to Klaus Plus." `sweep_message(..., plus: bool = False)`: the price line becomes `"Included in Klaus Plus — no charge.\n\n"` when `plus` else the existing `f"{estimate}, billed to your OpenAI key.\n\n"`. `offer_model_sweep`: compute `on_plus = plus.active(_cfg())` and pass `plus=on_plus` (skip the estimate call when on Plus).

`klausmate/setup_flow.py`: `_embedding_ready(cfg)`: `bool(str(cfg.get("api_key_openai") or "").strip()) or bool(plus.key(cfg))`; `KEYS_COPY` gains the sentence "Or subscribe to Klaus Plus there and skip the keys."

- [ ] **Step 4: Run to verify they pass** — the five test files plus the full loop `0 failed`; `py_compile` through the symlink.
- [ ] **Step 5: Mutate once each, restore**: `_target` ignoring Plus → the routing pin fails; `sweep_message` ignoring `plus` → its pin fails; `missing_key_provider` ignoring the Plus key → its pin fails. md5s recorded.

---

### Task 8: Preferences — the Klaus Plus group, the config keys, the docs for them

**Files:**
- Modify: `klausmate/manage_models.py`, `klausmate/config.json`, `klausmate/config.md`
- Test: `tests/test_dialog_logic.py`, `tests/test_manage_models_assistant.py`, `tests/test_api_first_config.py`

**Interfaces:**
- Consumes: `plus.key/base/refresh/portal_url/status_line/DEFAULT_BASE/KEY/CACHE/BASE` (Task 6); `aqt.utils.openLink`; `mw.taskman.run_in_background`.
- Produces: config keys `klaus_plus_key` (`""`), `klaus_plus_cache` (`{}`), `klaus_plus_base` (`DEFAULT_BASE`); widgets `plus_key_edit`, `plus_status` (QLabel), `plus_subscribe_btn`, `plus_manage_btn`, `plus_check_btn`, `plus_base_edit` (General page); `save_embed` writes `klaus_plus_key`; `save_general` writes `klaus_plus_base`; `sync_embed_widgets` seeds both and repaints `plus_status` from `plus.status_line(cfg.get("klaus_plus_cache") or {})`.

- [ ] **Step 1: Write the failing pins**

`tests/test_api_first_config.py`: config.json defines `klaus_plus_key == ""`, `klaus_plus_cache == {}`, `klaus_plus_base == "https://klausmate.fly.dev"`; `config.md` names all three.

`tests/test_dialog_logic.py` (source/AST pins in the file's style over `manage_models.py`): the five widget names exist; `plus_key_edit` is `EchoMode.Password`; `save_embed`'s body writes `"klaus_plus_key"` and `save_general`'s writes `"klaus_plus_base"`; every new control's signal is connected to `mark_dirty` (`plus_key_edit.textEdited`, `plus_base_edit.textEdited`) and the three buttons are NOT (they act, they do not edit); `"exec(" not in` the new code; `openLink(` appears exactly for Subscribe and Manage; the network calls (`plus.refresh`, `plus.portal_url`) run inside `mw.taskman.run_in_background(`; no `.text()` of `plus_key_edit` reaches `print(`/`tooltip(`/`setText(` (extend the existing AST key-leak walker's `_key_edit` suffix rule — `plus_key_edit` already ends in `_key_edit`).

`tests/test_manage_models_assistant.py`: the "API keys & models" page census gains the Klaus Plus rows (row names "Klaus Plus", "Klaus Plus key", "Service" is NOT on this page); the OpenAI/Anthropic rows' descriptions say "Not needed on Klaus Plus" when a key is present — pin the string exists in source.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`klausmate/config.json`: add `"klaus_plus_key": ""`, `"klaus_plus_cache": {}`, `"klaus_plus_base": "https://klausmate.fly.dev"`.

`klausmate/config.md`: a "Klaus Plus" subsection under "API keys & models": `klaus_plus_key` (the licence key from the welcome page or email; with it set, the two provider keys are not needed), `klaus_plus_cache` (state the add-on writes: the last verdict and quota readout; safe to clear), `klaus_plus_base` (the service URL; change only for a staging or self-hosted service).

`klausmate/manage_models.py`, in the keys page BEFORE the OpenAI row:
```python
    plus_key_edit = QLineEdit()
    plus_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    plus_key_edit.setMinimumWidth(220)
    plus_key_edit.setPlaceholderText("kp_…  (from your welcome page or email)")
    _row(keys_layout, "Klaus Plus key",
         "Subscribers paste their licence key here; no other keys are needed then.", plus_key_edit)

    plus_status = QLabel()
    plus_status.setWordWrap(True)
    plus_btns = QHBoxLayout()
    plus_subscribe_btn = QPushButton("Subscribe…")
    plus_manage_btn = QPushButton("Manage subscription…")
    plus_check_btn = QPushButton("Check")
    for b in (plus_subscribe_btn, plus_manage_btn, plus_check_btn):
        b.setObjectName("SecondaryButton")
        plus_btns.addWidget(b)
    _row(keys_layout, "Klaus Plus", plus_status, plus_btns)
```
and in the handlers section:
```python
    def _plus_cfg() -> dict:
        return _pkg().get_config() or {}

    def refresh_plus_status() -> None:
        cfg = _plus_cfg()
        has = bool(plus.key(cfg))
        plus_status.setText(plus.status_line(cfg.get(plus.CACHE) or {}) if has
                            else "Klaus Plus: $12/month or $99/year — no API keys needed.")
        plus_manage_btn.setEnabled(has)
        plus_check_btn.setEnabled(has)
        note = "Not needed on Klaus Plus; kept for the free tier." if has else None
        for roww, base_desc in ((openai_row, "Embeddings and lecture transcription."),
                                (anthropic_row, "The assistant and card pertinence.")):
            roww.klaus_desc.setText(note or base_desc)

    def on_plus_subscribe() -> None:
        openLink(plus.base(_plus_cfg()) + "/subscribe")

    def on_plus_manage() -> None:
        cfg = _plus_cfg()
        def work() -> str:
            return plus.portal_url(cfg)
        def done(fut) -> None:
            try:
                url = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] Klaus Plus portal failed: {exc.__class__.__name__}")
                url = ""
            if url:
                openLink(url)
            else:
                tooltip("Could not open the subscription portal — check the key and try again.")
        mw.taskman.run_in_background(work, done)

    def on_plus_check() -> None:
        def work() -> dict:
            return plus.refresh(_pkg().get_config, _pkg().write_config)
        def done(fut) -> None:
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] Klaus Plus check failed: {exc.__class__.__name__}")
            refresh_plus_status()
        mw.taskman.run_in_background(work, done)
```
(`openai_row`/`anthropic_row` are the return values of the two existing `_row(...)` calls — capture them; `openLink` from `aqt.utils`, `tooltip` is already imported.) `sync_embed_widgets` seeds `plus_key_edit` from `cfg.get("klaus_plus_key")` inside the `syncing` guard and calls `refresh_plus_status()`; `save_embed` writes `cfg["klaus_plus_key"] = plus_key_edit.text().strip()` and, when the key changed, clears `cfg["klaus_plus_cache"] = {}` so the next Check is honest; the connect block gains `plus_key_edit.textEdited.connect(lambda _t: mark_dirty())` and the three button clicks; `update_embed_status`'s no-key branch reads "Add your OpenAI API key above — or a Klaus Plus key — to enable semantic search." General page: a "Klaus Plus service" row with `plus_base_edit` (placeholder `plus.DEFAULT_BASE`), written by `save_general` as `klaus_plus_base`, `textEdited → mark_dirty`. The keys page subtitle gains one sentence: "Or subscribe to Klaus Plus and skip the keys."

- [ ] **Step 4: Run to verify they pass** — the three test files, then the full loop; `py_compile` through the symlink; an offscreen construction smoke in the report (the dialog builds with a Plus key in config; the status line shows; no exception) as Task 7 of Plan 1 did.
- [ ] **Step 5: Mutate once, restore**: drop the `plus_key_edit.textEdited` connect → the dirty-mark pin fails; write the key from `save_general` too → the "each key written by exactly one save_*" pin fails. Restore, md5s recorded.


---

### Task 9: Licence, docs, packaging, the deploy runbook

**Files:**
- Create: `LICENSE`, `klausmate/LICENSE`, `service/README.md`
- Modify: `README.md`, `CLAUDE.md`, `AGENTS.md`, `scripts/package.sh`
- Test: `tests/test_imports.py` (or the nearest census file) gains a pin that both `LICENSE` files exist and start with the AGPL header; `scripts/package.sh` is exercised by running it to a temp dir and asserting the zip lists no `service/` entry (a shell check in the report is acceptable if no test file owns packaging).

**Interfaces:** none new.

- [ ] **Step 1: The licence.** Fetch the canonical text: `curl -sL https://www.gnu.org/licenses/agpl-3.0.txt -o LICENSE` and copy it to `klausmate/LICENSE`. Verify the first non-blank line reads `GNU AFFERO GENERAL PUBLIC LICENSE` and the second `Version 3, 19 November 2007`; never edit the text. `README.md`'s "License" section becomes: "The add-on (`klausmate/`) is licensed under the GNU AGPL v3 — see `LICENSE`. The Klaus Plus service (`service/`) is a separate program and is not part of the add-on's licence. Third-party: `pypdf` (BSD) in `vendor/`."
- [ ] **Step 2: Packaging.** `scripts/package.sh` already stages `klausmate/` only; add an explicit `--exclude 'service/'` beside the existing excludes and a comment that the service is never shipped. Run it to a temp dir: `unzip -l` shows no `service/`, no `meta.json`, no `user_files/` content beyond the README.
- [ ] **Step 3: Docs.** CLAUDE.md: a new intro paragraph after the API-first one — "Klaus Plus (2026-09-16)": the two tiers, the service in `service/`, `plus.py` as the seam (one paragraph in the module map, in the existing style: what it owns, its one non-obvious rule — "generous by design: a cached active is honoured for a week, because the service is the only gate"), the Preferences group, the config keys, and the rule that the add-on never holds a secret. AGENTS.md: the privacy paragraph gains the subscriber path (a subscriber's requests go to Klaus's service, which relays them to OpenAI and Anthropic and stores counters only — link `/privacy`), the repository layout gains `service/`, the dependencies table gains Fly.io/Stripe/Resend as service-side only, config keys section gains the three keys. `klausmate/config.md` was done in Task 8 — verify.
- [ ] **Step 4: `service/README.md`** — the operator's runbook, complete commands, no secrets:
  1. `brew install flyctl && fly auth login`
  2. `cd service && fly launch --no-deploy --copy-config --name klausmate` (accept the generated app; keep `fly.toml` as committed), `fly volumes create klausplus_data --size 1 --region <primary_region>`
  3. Secrets: `fly secrets set OPENAI_API_KEY=… ANTHROPIC_API_KEY=… STRIPE_SECRET_KEY=… STRIPE_WEBHOOK_SECRET=… STRIPE_PRICE_MONTHLY=… STRIPE_PRICE_YEARLY=… RESEND_API_KEY=… RESEND_FROM='Klaus <plus@yourdomain>' OPERATOR_NAME='…' OPERATOR_EMAIL='…' OPERATOR_COUNTRY='…' PUBLIC_BASE_URL=https://klausmate.fly.dev MIN_CLIENT_VERSION=0.2.0` — typed in his own shell, never pasted anywhere else; provider spend caps set in each provider's dashboard first.
  4. Stripe: `STRIPE_SECRET_KEY=sk_test_… PUBLIC_BASE_URL=https://klausmate.fly.dev python scripts/stripe_setup.py` (from `service/` with the venv active); paste the printed `fly secrets set …` line.
  5. `fly deploy`; `curl https://klausmate.fly.dev/healthz` → `{"ok":true}`; `open https://klausmate.fly.dev`.
  6. Test purchase with Stripe's test card `4242 4242 4242 4242`; the welcome page shows the key; paste into Preferences; Check → the status line fills.
  7. Going live: repeat step 4 with the live key, set `MIN_CLIENT_VERSION` to the shipped add-on version, `fly deploy`.
  8. The kill switch: `fly secrets set KLAUS_PLUS_PAUSED=1` (and unset with `fly secrets unset KLAUS_PLUS_PAUSED`).
  9. Backups: Fly's daily volume snapshots (`fly volumes snapshots list klausplus_data`); restore by creating a volume from a snapshot.
  10. Logs: `fly logs` — paths, statuses, hash prefixes, metered amounts only.
- [ ] **Step 5: Verify**: the full add-on loop `0 failed`; `python3 -m py_compile` through the symlink; `grep -rn "klaus_plus\|Klaus Plus" CLAUDE.md AGENTS.md klausmate/config.md` finds the new paragraphs; the packaging check passes. No mutation for prose; the licence pin is mutated once (rename `LICENSE` on a scratch copy → the pin fails).

---

### Task 10: Integration — the fake upstream for a local end-to-end, the loop, the rollout checklist (needs-human)

**Files:**
- Modify: `service/klausplus/upstream.py` (add `FakeUpstream`), `service/klausplus/app.py` (`KLAUS_PLUS_FAKE_UPSTREAM=1` selects it in `create_app` when no upstream is injected)
- Test: `service/tests/test_upstream_fake.py`; scratch only for the rest.

**Interfaces:**
- Produces: `upstream.FakeUpstream` — the Task 3 test double promoted to the package (canned embeddings, a canned transcript, a canned non-stream message and a four-event SSE stream), so the service can run locally with no provider key.

- [ ] **Step 1: Pin** — `test_upstream_fake.py`: `create_app(settings)` with `KLAUS_PLUS_FAKE_UPSTREAM=1` in the environment uses `FakeUpstream`; without it, `Upstream`. Move the Task 3 fake into `upstream.py` and make `tests/test_proxy.py` import it from there (one fake, two users).
- [ ] **Step 2: Local end-to-end**, all scratch, all offline: start the service (`DATABASE_PATH=$SCRATCH/e2e.sqlite3 KLAUS_PLUS_FAKE_UPSTREAM=1 STRIPE_PRICE_MONTHLY=price_x uvicorn klausplus.main:app --port 8089`), insert a customer row with a minted key through a tiny Python snippet against the same database, point a scratch config at `http://127.0.0.1:8089` with that key, and drive the ADD-ON's real code paths from the house harness in a scratch test file: `embeddings.OpenAIEmbeddings.embed(["a", "b"])` through `plus.endpoint` → two vectors, `X-Klaus-Quota` parsed, the cache written; `anthropic_client.Client.stream(..., purpose="judge")` → the relayed SSE parses to the canned text; `plus.refresh` → the status line; then set the customer `unpaid` in the database → `plus.refresh` remembers `refused:402` and `plus.active` is False; `missing_key_provider` returns `""` with the key. Record the transcript in the report. No paid call is possible in this mode.
- [ ] **Step 3: The loops** — `service/`: `python -m pytest -q` all green; add-on: `for t in tests/test_*.py …` 43+ files `0 failed`; `python3 scripts/mutation_audit.py --modules plus` (register `plus` in `AUDIT_MODULES` — it is aqt-free with its own test file) → no `gut` survivor; `py_compile` through the symlink.
- [ ] **Step 4: The rollout checklist**, posted verbatim on the card for Pouya (needs-human):
  1. `brew install flyctl`, `fly auth login`; from `service/`: `fly launch --no-deploy --copy-config --name klausmate`, `fly volumes create klausplus_data --size 1`.
  2. Set the Fly secrets from `service/README.md` step 3, with the Stripe TEST key and spend caps set at OpenAI and Anthropic.
  3. Run `scripts/stripe_setup.py` in test mode; paste its `fly secrets set` line. `fly deploy`. `/healthz` answers.
  4. Open `https://klausmate.fly.dev`, subscribe monthly with card `4242 4242 4242 4242` → the welcome page shows a `kp_` key (and emails it if Resend is configured).
  5. In Anki: Preferences → API keys & models → paste the key → Save → Check: the status line reads "Plus · renews … · 0 of 30 lecture hours, 0 of 3,000 cards, 0 of 200 turns"; the OpenAI and Anthropic rows say "Not needed on Klaus Plus".
  6. Drop a PDF on the deck screen with no OpenAI key in config → it indexes through the service (`fly logs` shows `POST /v1/embeddings 200` with a hash prefix and a metered amount, never text); the Library row fills in.
  7. Manage subscription… opens Stripe's portal; cancel at period end → Check still says active with "renews" replaced by the end date; in the Stripe dashboard, mark the subscription unpaid (or end the test clock) → Check reads refused with the service's message; a drop refuses with the same message and offers the free tier.
  8. Set `KLAUS_PLUS_PAUSED=1` → a drop shows the maintenance message; unset it.
  9. Going live: the live Stripe key, `MIN_CLIENT_VERSION` = the shipped add-on version, `fly deploy`, ship the add-on.
- [ ] **Step 5: Report** the loop tables, the e2e transcript, the audit line, and the checklist as posted.

---

## Self-review

**Spec coverage.** D1 (tiers, price, quotas, grace): Tasks 1–2 (constants, verdict, meter), 7 (gates, "included" wording), 8 (the Preferences copy). D2 (the service): Tasks 1, 3, 10. D3 (billing, webhooks, portal, email, recovery): Task 4. D4 (the add-on): Tasks 6, 7, 8. D5 (terms, privacy, refunds): Task 5. D6 (licence, layout, packaging): Task 9. D7 (rollout): Tasks 9 (runbook) and 10 (checklist). Testing list: every item has a pin in the task that builds it; the live checklist is Task 10's.

**Placeholders.** None: every code step carries its code; the operator's name, email and country are runtime settings, not blanks; the AGPL text is fetched, not typed.

**Type consistency.** `Endpoint(base, headers)` is defined in Task 6 and consumed by that name in Task 7; `plus.endpoint(cfg, purpose)` / `plus.active(cfg)` / `plus.key(cfg)` match their uses in Tasks 7 and 8; `meter.snapshot` produces the `{"month","resets_at","counters","human"}` shape that `plus.parse_quota`/`status_line` read and `/v1/me` wraps under `"quota"`; `sweep_message(..., plus=False)` matches its Task 7 pin; `authenticate(request, purpose_required=False)` is what `/v1/portal` calls; `Settings` field names match `from_env` and the runbook's secret names one to one; `STRIPE_API_VERSION` lives in `config.py` and is what `billing._stripe` and `stripe_setup.py` set.

**Execution.** Run as a board-coordinated swarm (Pouya's standing choice): one card per task with the file lists above, the lane order from "File Structure", a reviewer per card, orchestrator commits, a final whole-plan review with one fix wave.
