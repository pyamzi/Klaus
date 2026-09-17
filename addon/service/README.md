# Klaus Plus — the service

The metered service behind the KlausMate add-on's **Klaus Plus** tier. A
subscriber's Klaus sends the same request bodies it would send to OpenAI and
Anthropic here instead; this app checks the licence key, debits the right
counter, relays the call with the operator's own provider keys, and returns
the provider's answer untouched.

**This is a separate program from the add-on.** It is never packaged and
never shipped to a user (`scripts/package.sh` stages only `klausmate/`, and
carries an explicit `--exclude 'service/'`). The add-on stays stdlib-only,
Python 3.9; this is Python 3.12 with FastAPI, uvicorn, httpx and the Stripe
SDK.

**Nothing in this file is a secret.** Every key below is typed into your own
shell — never pasted into a chat, an issue, a commit, or this repository.

---

## What it stores

Per subscriber: the Stripe customer id, the email Stripe reports, the
licence key's **SHA-256 hash** (never the key), the subscription status and
period end, and this month's four counters. **No request or response body is
stored or logged** — lecture text, audio and page images pass through and are
gone. A log line is `METHOD /path STATUS key=<8 hex of the hash> ms=… metered=…`
and nothing more; `service/tests/` asserts that.

## Routes

| Route | What it does |
|---|---|
| `POST /v1/embeddings` | → OpenAI embeddings. Purpose `embed`, unmetered under the abuse ceiling. |
| `POST /v1/audio/transcriptions` | → OpenAI transcription, multipart passthrough. Purpose `transcribe`, debits audio seconds. |
| `POST /v1/messages` | → Anthropic Messages, streamed or not. Purpose `judge` or `assistant`; metered from the final `message_delta` usage. |
| `GET /v1/me` | Plan, period end, the counters and their caps. Also returned on every proxied call as the `X-Klaus-Quota` header. |
| `POST /v1/portal` | A Stripe Customer Portal link for a key holder (this is what Preferences' **Manage subscription…** opens). |
| `GET /`, `/subscribe`, `/welcome`, `/recover` | The landing page, Checkout, the success page that mints and shows the key once, and key recovery by email. |
| `POST /stripe/webhook` | Entitlement from Stripe events, idempotent by event id. |
| `GET /terms` | The terms of service, as HTML. Unauthenticated — anyone can read it — and rendered from the operator settings (`OPERATOR_NAME`, `OPERATOR_EMAIL`, `OPERATOR_COUNTRY`). |
| `GET /privacy` | The privacy statement, same shape: HTML, unauthenticated, rendered from the same operator settings. This is the page the add-on's own privacy note points at. |
| `GET /healthz` | `{"ok":true}` — what Fly's health check hits. |

`/terms` and `/privacy` live in `pages.py`. Set the three `OPERATOR_*`
secrets before you take a payment — both pages name the operator and the
country whose law governs, and a subscriber is entitled to read them first.

## Local development

```sh
cd service
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # the whole suite
.venv/bin/uvicorn klausplus.main:app --reload --port 8080
```

The add-on's own headless loop is separate and lives at the repo root; this
suite is never part of it.

---

## Deploy runbook

### 1. Fly CLI

```sh
brew install flyctl
fly auth login
```

A card must be on the Fly account. Do this once.

### 2. Create the app and its volume

`fly.toml` in this directory is the committed configuration — one Machine,
`min_machines_running = 1`, a `/data` mount and the `/healthz` check. Keep
it; `--copy-config` is what makes `fly launch` use it instead of writing a
new one, and `--no-deploy` stops it shipping before the secrets exist.

```sh
cd service
fly launch --no-deploy --copy-config --name klausmate
fly volumes create klausplus_data --size 1 --region iad
```

Accept the generated app when it asks. The volume **name must be
`klausplus_data`** and the region must match `primary_region` in `fly.toml`
(`iad`) — the `[[mounts]]` block matches on that name, and a mismatch means
the Machine boots with no `/data` and loses every subscriber on restart.

### 3. Secrets

Set the provider **spend caps in each provider's own dashboard first** —
OpenAI and Anthropic. The service's quotas are the fair-use limit; the
provider caps are the backstop against a bug or an abusive key, and they are
the only thing that cannot be defeated by a mistake in this repository.

Then, typed in your own shell — never pasted anywhere else:

```sh
fly secrets set \
  OPENAI_API_KEY=… \
  ANTHROPIC_API_KEY=… \
  STRIPE_SECRET_KEY=… \
  STRIPE_WEBHOOK_SECRET=… \
  STRIPE_PRICE_MONTHLY=… \
  STRIPE_PRICE_YEARLY=… \
  RESEND_API_KEY=… \
  RESEND_FROM='Klaus <plus@yourdomain>' \
  OPERATOR_NAME='…' \
  OPERATOR_EMAIL='…' \
  OPERATOR_COUNTRY='…' \
  PUBLIC_BASE_URL=https://klausmate.fly.dev \
  MIN_CLIENT_VERSION=0.2.0
```

`STRIPE_PRICE_MONTHLY` / `STRIPE_PRICE_YEARLY` / `STRIPE_WEBHOOK_SECRET` come
out of step 4 — run that first if you would rather set them once.

Every knob, with its default from `klausplus/config.py`:

| Secret / env | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | — | Relayed embedding and transcription calls. Required. |
| `ANTHROPIC_API_KEY` | — | Relayed Messages calls. Required. |
| `STRIPE_SECRET_KEY` | — | Checkout, the portal, the webhook. Test key first. |
| `STRIPE_WEBHOOK_SECRET` | — | Signature check on `/stripe/webhook`. From step 4. |
| `STRIPE_PRICE_MONTHLY` / `_YEARLY` | — | The two price ids. From step 4. |
| `RESEND_API_KEY` + `RESEND_FROM` | — | The welcome email. **Both or neither** — with either missing, email is off and the welcome page says so. A verified sender needs a domain; Resend's test sender only delivers to the account owner. |
| `OPERATOR_NAME` | `Klaus` | Named on the legal pages. |
| `OPERATOR_EMAIL` | — | The contact address on those pages. |
| `OPERATOR_COUNTRY` | — | Whose law governs. |
| `PUBLIC_BASE_URL` | `https://klausmate.fly.dev` | Used to build Checkout's return URLs and the webhook URL. Must match reality or checkout returns nowhere. |
| `MIN_CLIENT_VERSION` | `0.2.0` | Add-on version floor. Anything older gets `426` and "update Klaus". |
| `DATABASE_PATH` | `/data/klausplus.sqlite3` | Set by the Dockerfile. Leave it — anywhere off `/data` is wiped on redeploy. |
| `KLAUS_PLUS_PAUSED` | unset | **The kill switch.** `1` refuses every proxied call `503` — "Klaus Plus is paused for maintenance — try again later, or use your own API key." — checked before auth, so it costs nothing. See step 8. |
| `KLAUS_PLUS_FAKE_UPSTREAM` | unset | **Local development only.** `1` makes `create_app` use the canned `FakeUpstream` instead of the providers, so the service runs offline with no provider key (`tests/test_upstream_fake.py`, the offline end-to-end). Never set it on Fly — nothing in `fly.toml` or the Dockerfile does. |
| `KLAUS_PLUS_ALLOWED_MODELS` | unset | Optional, comma-separated. When set, a request naming any other model is refused `400` **before any provider call**. Unset, the caller's model is forwarded as-is and the provider spend caps are the only backstop. The quotas are priced against Sonnet-class and `text-embedding-3-large` costs, so a hand-crafted body asking for an Opus-class model spends several times the quota it debits — this is the lever that closes that without a redeploy. |

Reading them back is safe (`fly secrets list` shows names and digests, never
values); there is no command that prints a secret.

### 4. Stripe: products, prices, webhook

Test mode first — use a `sk_test_…` key. From `service/`, with the venv:

```sh
STRIPE_SECRET_KEY=sk_test_… PUBLIC_BASE_URL=https://klausmate.fly.dev \
  .venv/bin/python scripts/stripe_setup.py
```

The script is **idempotent** — it finds an existing "Klaus Plus" product by
name and an existing webhook endpoint by URL, and creates only what is
missing ($12/month, $99/year). It never prints `STRIPE_SECRET_KEY`. It
prints a ready-made line:

```
Set these Fly secrets (paste into your shell, not into any chat):
fly secrets set STRIPE_PRICE_MONTHLY=price_… STRIPE_PRICE_YEARLY=price_… STRIPE_WEBHOOK_SECRET=whsec_…
```

Paste that line into your shell. If the webhook endpoint already existed,
Stripe will not re-reveal its signing secret, so the script prints the two
price ids and tells you to fetch the secret from **Stripe → Developers →
Webhooks** yourself.

### 5. Deploy and check

```sh
fly deploy
curl https://klausmate.fly.dev/healthz     # -> {"ok":true}
open https://klausmate.fly.dev
```

### 6. Test purchase

Buy a subscription on the landing page with Stripe's test card
`4242 4242 4242 4242` (any future expiry, any CVC). The welcome page shows
the `kp_…` licence key **once** — that is the only time it is displayed, so
copy it then; if email is configured it also arrives by mail, and `/recover`
can re-issue one later to the address that paid.

Paste it into Anki: **Tools → KlausMate Preferences… → API keys & models →
Klaus Plus key**, Save, then press **Check**. The status line fills in with
the plan, the renewal date and the month's usage. Run one index and watch it
move.

With email off (or a redirect back from Stripe that never landed), a customer
can pay and reach neither the welcome page nor `/recover`. Issue their key by
hand from the Stripe customer id (Stripe dashboard, or `fly logs`):
`fly ssh console -C "python scripts/mint_key.py cus_…"` — it prints the key
once and nothing else; give it to the customer, it replaces any earlier key.

> With `MIN_CLIENT_VERSION=0.2.0` and the add-on's shipped `human_version`
> below that, every call is refused `426` **on purpose** — that is the
> rollout's own safety catch (nothing live can reach the service while it is
> in test mode). Lower the floor, or bump the add-on's manifest, when you
> want the end-to-end run.

### 7. Going live

1. Re-run step 4 with the **live** `sk_live_…` key — a separate product,
   prices and webhook endpoint exist in live mode.
2. Set the new price ids and webhook secret, swap `STRIPE_SECRET_KEY`.
3. Set `MIN_CLIENT_VERSION` to the add-on version you are actually shipping.
4. `fly deploy`.

### 8. The kill switch

```sh
fly secrets set KLAUS_PLUS_PAUSED=1      # every proxied call -> a maintenance message
fly secrets unset KLAUS_PLUS_PAUSED      # back to normal
```

Either command restarts the Machine. Use it for a runaway bill or a provider
incident; `KLAUS_PLUS_ALLOWED_MODELS` (step 3) is the narrower lever when the
problem is one expensive model rather than the whole service.

### 9. Backups

The database is one SQLite file on the volume, and Fly takes **daily volume
snapshots** automatically (5-day retention by default).

```sh
fly volumes list                              # -> the vol_… id
fly volumes snapshots list <vol_id>
fly volumes create klausplus_data --snapshot-id <snap_id> --size 1 --region iad
```

Restoring means creating a *new* volume from a snapshot and attaching it —
you cannot restore in place. Detach or destroy the old volume only once the
new one is serving.

### 10. Logs

```sh
fly logs
```

Paths, statuses, 8-character key-hash prefixes, latency and metered amounts.
No request or response bodies, no keys, no emails. If you ever see one of
those in a log line, that is a bug worth stopping the service for.
