# Klaus Plus — the subscription that removes the keys: design

**Date:** 2026-09-16. **Asked by Pouya:** "Instead of APIs, would it be
possible to create a subscription system to make this work?" Answers the
same day: Pouya pays the AI bills, with quotas; price and quota are the
orchestrator's call; Stripe is the merchant; Fly.io hosts; the
orchestrator drafts the terms and checks AnkiWeb's rules. Approved the
same day: the design below, and the order of work — Klaus Plus next,
then Plans 2 and 3 of the API-first spec routed through it.

Builds on `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md`
(Plan 1 built: page store, the two stdlib clients, page-level vectors,
cost estimates, the "API keys & models" page). This spec adds one
service and one add-on mode; it changes no feature.

## Findings the design rests on

- **AnkiWeb allows it.** AnkiWeb's terms (last updated 2018-10-17) say
  of add-ons only that they "must be licensed under the AGPL3 or a
  compatible license" and that they are unverified third-party code.
  Nothing forbids a paid service behind one, and AnkiHub is the standing
  precedent: a free add-on on AnkiWeb, a subscription sold at its own
  site. Consequence: the add-on stays AGPL3 and is the free client; the
  paid part is the service, a separate program Pouya keeps private.
- **The add-on cannot hold a secret.** It ships as readable Python, so
  every provider key lives on the service and the add-on carries only a
  per-user licence key that the service can revoke. A forged "premium"
  flag in a config file buys nothing because the service still answers
  401 — the deleted `entitlement.py` (`f1b330b`) said this first, and it
  is revived here in spirit.
- **The seams already exist.** Every provider call funnels through
  `openai_client._request` and `anthropic_client._open_stream`, each
  with one base-URL constant and one header builder, so the add-on side
  is an endpoint switch, not a rewrite. The deleted `HostedBackend`
  (`a494f2d`) is the shape.
- **The bill is bounded only by quota.** From `cost.py`'s price table: a
  90-minute lecture transcribed costs $0.27, judging 200 candidate cards
  $0.17, an assistant turn with a page image about $0.02, embedding a
  30k-card collection $0.40 once. A heavy student is about $22 a month,
  a light one under $6. An unlimited plan would lose money on the
  heaviest users; a quota plan does not.

## Decisions

### D1 — The product

- **Two tiers.** *Free*: bring your own OpenAI and Anthropic keys,
  exactly what Plan 1 built, unmetered, unchanged. *Klaus Plus*: no keys
  on the user's side; Klaus's service holds them and meters usage.
- **Price.** $12 a month or $99 a year, one plan, no add-ons. Both are
  constants in the Stripe products the setup script creates; changing
  them is a Stripe price change plus one constant in the service.
- **Quota, per calendar month, reset on the 1st UTC, no rollover:**

  | What | Quota | Metered as (server-visible unit) | Cost to Pouya at the cap |
  |---|---|---|---|
  | Lecture audio transcribed | 30 hours | audio minutes, from the WAV's header | $5.40 |
  | Cards judged | 3,000 cards | Anthropic tokens on calls tagged `judge`, 250 tokens per card → 750,000 tokens | $2.55 |
  | Assistant | 200 turns | Anthropic tokens on calls tagged `assistant`, 6,000 tokens per turn → 1,200,000 tokens | $4.00 |
  | Embeddings | unmetered | OpenAI tokens, hard abuse ceiling 20,000,000 a month | $2.60 at the ceiling |

  Quotas are enforced by the service, before forwarding. At the cap the
  call is refused with `402` and a message naming the quota and the
  reset date; the add-on shows it and offers the free tier's own keys.
  Human-readable quota lines ("30 lecture hours") are derived from the
  token units by the two constants above, both in one place on the
  service and one place in the add-on.
- **Grace.** A subscription Stripe marks `past_due` keeps working for 3
  days, then refuses. A cancelled subscription works until its period
  end. The add-on caches the last verdict for 6 hours and honours a
  cached "active" for 7 days when the service cannot be reached, so a
  flaky week never punishes a paying user (the revived entitlement rule).

### D2 — The service

- **One app, `service/` in this repo**: Python 3.12 in Docker, FastAPI +
  uvicorn, the official `stripe` and `httpx` packages (third-party
  dependencies are fine server-side; only the add-on is stdlib-only).
  Deployed as one Fly Machine at `klausmate.fly.dev`, a custom domain
  later. SQLite on a 1 GB Fly volume, WAL mode, Fly's daily volume
  snapshots as the backup. `/healthz` for Fly's checks.
- **Endpoints mirror the providers**, so the add-on's request bodies do
  not change:
  - `POST /v1/embeddings` → OpenAI embeddings.
  - `POST /v1/audio/transcriptions` → OpenAI transcription (multipart
    passthrough, 25 MB cap).
  - `POST /v1/messages` → Anthropic Messages, streamed or not; SSE bytes
    are relayed as they arrive and the final `message_delta` usage is
    what gets metered.
  - `GET /v1/me` → plan, period end, the four counters and their caps,
    the add-on's version floor. Also returned on every proxied call as
    `X-Klaus-Quota` (JSON), so the add-on's readout is always fresh
    without an extra request.
  - `POST /stripe/webhook`, `GET /subscribe` (creates a Checkout
    Session and redirects), `GET /welcome` (the success page: mints and
    shows the key), `GET /portal` (a Customer Portal session for a key
    holder), `POST /recover` (emails the key to the address that paid),
    `GET /terms`, `GET /privacy`.
- **Auth.** `Authorization: Bearer kp_<32 hex>`. Keys are stored only as
  SHA-256 hashes; a key is minted once, at `/welcome`, and shown once,
  plus emailed. Every request also carries `X-Klaus-Client: <add-on
  version>` and `X-Klaus-Purpose: embed|transcribe|judge|assistant`;
  the purpose decides which counter a call debits, and a `judge`/
  `assistant` tag on a non-`/v1/messages` call is refused.
- **Provider keys** live in Fly secrets (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `RESEND_API_KEY`), never in the repo, never logged; Pouya sets spend
  caps at both providers as the backstop the service cannot be.
- **Retention.** The service stores: the Stripe customer id, the email
  Stripe reports, the key hash, the subscription status and period end,
  and monthly counters. It stores no request or response body — lecture
  text, audio and page images pass through and are gone. Logs carry
  method, path, status, key-hash prefix, latency and the metered amount,
  nothing else.
- **Abuse limits, per key**: 60 requests a minute; 240 audio minutes a
  day; bodies capped (4 MB JSON, 25 MB audio); a revoked or unknown key
  is `401` with no detail. `KLAUS_PLUS_PAUSED=1` in secrets refuses every
  proxied call with a maintenance message — the kill switch for a runaway
  bill. `KLAUS_PLUS_ALLOWED_MODELS` (optional, comma-separated) is the
  finer lever: when set, a request naming any other model is refused
  `400` before any provider call; unset, the caller's model is forwarded
  as-is and the provider spend caps stay the backstop. The quotas are
  priced against Sonnet-class and `text-embedding-3-large` costs, so a
  body hand-crafted for an Opus-class model spends several times the
  priced quota — this knob is what closes that without a redeploy.
- **Version floor.** `MIN_CLIENT_VERSION` on the service; an older add-on
  gets `426` and the message "update Klaus from Tools → Add-ons".

### D3 — Billing

- **Stripe Checkout** in subscription mode, two Prices on one Product
  (monthly, yearly), 7-day free trial off — quota abuse on trials is not
  worth policing at launch. Success URL `/welcome?session_id={CHECKOUT_SESSION_ID}`;
  the page verifies the session with Stripe, creates the customer row,
  mints the key, shows it once, and sends it by email.
- **Webhooks** drive entitlement: `checkout.session.completed` (create),
  `customer.subscription.updated` and `.deleted` (status, period end),
  `invoice.paid` (period rolls, counters reset), `invoice.payment_failed`
  (`past_due`, the 3-day grace starts). Signatures verified with the
  webhook secret; events are idempotent by event id.
- **Customer Portal** for cancel, card and invoice history, reached
  from Preferences' "Manage subscription…" through `/portal`.
- **Email** through Resend's free tier (3,000 emails a month): the key
  on purchase, the key again on `/recover`, a notice at 80% of any
  quota. One more free account for Pouya; the alternative — no email,
  the key shown once on the success page only — is a launch option if
  he prefers zero extra accounts, at the cost of a support burden for
  lost keys.
- **Merchant of record.** Stripe as chosen. Sales tax is Pouya's to
  configure in Stripe Tax when he sells outside his own jurisdiction;
  the design does not depend on it.

### D4 — The add-on

- **One new aqt-free module, `klausmate/plus.py`:** `key(cfg)`,
  `active(cfg)` (a key exists and the cached verdict is not refused),
  `endpoint(cfg, purpose)` → the base URL and headers for a call (the
  service with the bearer key when Plus, else the provider with the
  user's key), `parse_quota(headers)`, and the verdict cache
  (`klaus_plus_cache` in config: status, period end, counters,
  checked-at; 6-hour TTL, 7-day grace — `entitlement.py`'s rules).
- **The clients take an endpoint, not a key.** `openai_client.embed`
  and `transcribe` and `anthropic_client.Client` gain an `Endpoint`
  argument (base URL + a headers builder) with the provider as the
  default, so every existing test stands; `embeddings.OpenAIEmbeddings`
  and the two future callers (Plan 2's judge, Plan 3's assistant) ask
  `plus.endpoint` and tag the purpose. `X-Klaus-Client` carries
  `manifest.json`'s `human_version`.
- **Gates.** `index_queue.missing_key_provider` returns `""` when a Plus
  key is present; `setup_flow._embedding_ready` likewise; `KEYS_COPY`
  gains one sentence naming Klaus Plus as the keyless option. The priced
  sweep confirm, when Plus is active, says "included in Klaus Plus, no
  charge" instead of a dollar estimate — embeddings are unmetered on
  Plus; the dollar estimate stays for the free tier. Quota wording
  belongs to the metered calls (transcription and judging, Plan 2).
- **Preferences.** The "API keys & models" page gains a "Klaus Plus"
  group above the keys: the licence key (`EchoMode.Password`, deferred
  save like every field), a status line ("Plus · renews 2026-10-01 · 4 of
  30 lecture hours, 812 of 3,000 cards, 31 of 200 turns"), and three
  buttons: **Subscribe…** (opens `/subscribe` in the browser),
  **Manage subscription…** (opens the portal link), **Check** (refreshes
  the verdict). When a key is present the two provider-key rows are recaptioned
  "not needed on Klaus Plus" and stay editable — never disabled or
  greyed, the free tier is one deletion away. No `exec()`, theme tokens only, `mark_dirty`
  discipline unchanged.
- **Config keys**: `klaus_plus_key` (`""`), `klaus_plus_cache` (`{}`),
  `klaus_plus_base` (`"https://klausmate.fly.dev"`, a free-text row
  under General for a self-hoster or a staging service — the only
  reason the URL is config at all). Documented in `config.md`.
- **Errors the user sees**: `401` → "Klaus Plus key not recognised —
  check it under Preferences"; `402` → the quota message with the reset
  date; `426` → the update message; anything else → the same wording as
  the provider errors today, with "Klaus Plus" in place of the provider's
  name. The key is never in any message or log.

### D5 — Terms, privacy, refunds

Two static pages served by the service and linked from Preferences:

- **Terms of Service**: what Klaus Plus is (metered access to third-party
  AI providers through Klaus's service), the quotas and that they may
  change with notice, acceptable use (personal study; no resale; no
  automated scraping of the service), the licence key is personal,
  cancellation any time through the portal with access to period end,
  a 14-day refund on the first payment on request, service provided as
  is, liability capped at fees paid, the operator's contact email and
  country as the governing law.
- **Privacy Policy**: what is stored (Stripe customer id, billing email,
  key hash, subscription status, monthly usage counters), what is not
  (no lecture text, audio, images, notes or transcripts are stored;
  requests are relayed and discarded), the subprocessors (Stripe,
  OpenAI, Anthropic, Resend, Fly.io) and what each receives, retention
  (counters for 13 months; the row deleted 30 days after the
  subscription ends), the user's right to deletion by email.
- **Refund policy** folded into the terms; the portal handles cancels.

The operator's name, contact email and country are inputs Pouya
provides before launch (see "What Pouya provides").

### D6 — Licensing and repository layout

- The add-on gains an explicit `LICENSE` (AGPL-3.0) at the repo root and
  in `klausmate/`, and `manifest.json` stays as it is; the README's
  "see the repository license file if present" becomes a sentence.
- `service/` is a separate program in the same private repository, with
  its own `pyproject.toml`, `Dockerfile`, `fly.toml`, `tests/` (pytest;
  a local `service/.venv` for development) and `README.md` (deploy and
  secrets runbook). The add-on's packaging (`scripts/`) excludes it.

### D7 — Rollout

1. Deploy the service to Fly with Stripe in **test mode** and a
   `MIN_CLIENT_VERSION` above the shipped add-on, so nothing live can
   reach it yet.
2. Pouya runs the Stripe setup script (products, prices, webhook
   endpoint) with his own key in his shell; sets the Fly secrets; buys a
   test subscription with a Stripe test card; pastes the key into
   Preferences; runs one embed and one transcription through the
   service; watches the quota readout move; cancels in the portal and
   sees the refusal after period end.
3. Flip Stripe to live mode, lower the version floor, ship the add-on
   update. No migration: existing profiles keep working on their own
   keys; `klaus_plus_key` defaults to empty.

## What the user sees

- Preferences → API keys & models shows a Klaus Plus group first. With
  no key: "Klaus Plus: $12/month or $99/year, no API keys needed" and a
  Subscribe… button. After checkout the browser shows the key once and
  it arrives by email; pasted and saved, the status line fills in and the
  provider-key rows are recaptioned "not needed on Klaus Plus".
- Everything else is unchanged: indexing, the sweep prompt (now in quota
  terms), the assistant, the Lecture panel. At a cap, one message with
  the reset date and the option to add a personal key instead.

## Testing

- **Service (pytest)**: key minting and hashing; the entitlement state
  machine from each webhook event, idempotent by event id; quota
  arithmetic and the 402 at the cap; the grace window; the purpose tag
  routing; streaming passthrough against a fake upstream that emits
  Anthropic's SSE events, including metering from `message_delta`; body
  caps and rate limits; `426` below the version floor; the pause switch;
  `/v1/me` and the `X-Klaus-Quota` header; no request body ever reaches a
  log (a capturing log handler asserts it).
- **Add-on (the house harness)**: `plus.endpoint` picks the service with
  the bearer key when a key exists and the provider otherwise, per
  purpose; the verdict cache's TTL and grace; `parse_quota`;
  `missing_key_provider`/`_embedding_ready` with a Plus key; the sweep
  confirm's quota wording; Preferences' new rows only `mark_dirty` and
  `save_all` writes `klaus_plus_key` once; the dimmed provider rows stay
  editable; every new pin mutated once; `openai_client`/`anthropic_client`
  default endpoints unchanged so every existing pin stands.
- **Live checklist (needs-human)**: the rollout steps in D7, run by Pouya
  against Stripe test mode.

## What Pouya provides

1. Fly.io: `brew install flyctl`, `fly auth login`, a card on the account.
2. One OpenAI and one Anthropic API key with monthly spend caps, set as
   Fly secrets with the commands in `service/README.md`; they never pass
   through the orchestrator.
3. Stripe: run `service/scripts/stripe_setup.py` with `STRIPE_SECRET_KEY`
   in his own shell (test mode first); paste the webhook signing secret
   into Fly secrets.
4. A Resend account (free) and its API key as a Fly secret — or the
   decision to launch without email.
5. For the legal pages: the operator's name, a contact email, and the
   country whose law governs.
6. A domain later, if wanted; `klausmate.fly.dev` is the launch address.

## Out of scope

- Email sign-in and an account page (a licence key is the first version).
- Team or institutional plans, quota top-ups, referral codes.
- Metering the free tier (it is the user's own bill).
- Moving the assistant onto the Messages API (Plan 3) or the judge
  (Plan 2): both route through `plus.endpoint` when they land, which is
  why Klaus Plus is built first.
