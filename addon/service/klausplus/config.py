"""Settings from the environment (Fly secrets in production).

Every quota and unit constant lives here — the one place on the service
side; ``klausmate/plus.py`` holds the add-on's copy of the two human
units. Keys are read once and never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

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
    openai_api_key: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)
    openai_base: str = "https://api.openai.com/v1"
    anthropic_base: str = "https://api.anthropic.com"
    stripe_secret_key: str = field(default="", repr=False)
    stripe_webhook_secret: str = field(default="", repr=False)
    stripe_price_monthly: str = ""
    stripe_price_yearly: str = ""
    resend_api_key: str = field(default="", repr=False)
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
    # C-1: the add-on indexes 64 notes per request back to back; 60/min refused
    # every collection above ~3,800 notes on its first index. The money bound is
    # the quotas and the embed ceiling — this limiter only guards CPU.
    rate_per_minute: int = 600
    audio_day_seconds: int = 240 * 60
    max_json_bytes: int = 4 * 1024 * 1024
    max_audio_bytes: int = 25 * 1024 * 1024
    allowed_models: tuple = ()

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
            allowed_models=tuple(m.strip() for m in (e("KLAUS_PLUS_ALLOWED_MODELS") or "").split(",") if m.strip()),
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.resend_from)
