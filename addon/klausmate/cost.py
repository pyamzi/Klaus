"""Paid-pass estimates, before Klaus spends anything (spec D8).

Prices are constants you edit; they are dollars per million tokens
(input, output) for text models and dollars per minute (price, None) for
audio. Tokens are estimated at four characters each — an estimate, shown
as one, never a bill.
"""
from __future__ import annotations

from typing import NamedTuple

# Prices as published 2026-09-15; edit when they change.
PRICES: dict[str, tuple[float, float | None]] = {
    "text-embedding-3-large": (0.13, None),
    "text-embedding-3-small": (0.02, None),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "gpt-4o-mini-transcribe": (0.003, None),   # per minute
    "gpt-4o-transcribe": (0.006, None),        # per minute
}
CHARS_PER_TOKEN = 4
JUDGE_PROMPT_OVERHEAD_TOKENS = 350
JUDGE_OUTPUT_TOKENS_PER_CARD = 40


class Estimate(NamedTuple):
    tokens: int
    dollars: float


def _tokens(chars: int) -> int:
    return max(0, int(chars)) // CHARS_PER_TOKEN


def estimate_embed(chars: int, model: str = "text-embedding-3-large") -> Estimate:
    price_in, _ = PRICES[model]
    t = _tokens(chars)
    return Estimate(t, t / 1_000_000 * price_in)


def estimate_judge(n_cards: int, page_chars_mean: int, card_chars_mean: int = 600,
                   batch: int = 8, model: str = "claude-sonnet-5") -> Estimate:
    price_in, price_out = PRICES[model]
    n_batches = -(-max(0, int(n_cards)) // max(1, int(batch)))
    per_batch_in = JUDGE_PROMPT_OVERHEAD_TOKENS + _tokens(page_chars_mean) + batch * _tokens(card_chars_mean)
    tokens_in = n_batches * per_batch_in
    tokens_out = max(0, int(n_cards)) * JUDGE_OUTPUT_TOKENS_PER_CARD
    return Estimate(tokens_in + tokens_out, tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * (price_out or 0.0))


def estimate_transcribe(seconds: float, model: str = "gpt-4o-mini-transcribe") -> Estimate:
    per_minute, _ = PRICES[model]
    minutes = max(0.0, float(seconds)) / 60.0
    return Estimate(0, minutes * per_minute)


def add(*estimates: Estimate) -> Estimate:
    return Estimate(sum(e.tokens for e in estimates), sum(e.dollars for e in estimates))


def format_estimate(e: Estimate) -> str:
    money = "under $0.01" if e.dollars < 0.005 else f"about ${e.dollars:.2f}"
    return f"~{e.tokens:,} tokens · {money}"
