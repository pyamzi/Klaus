"""Tests for klausmate.cost (spec D8 — paid-pass cost estimation).

Covers: price table with dated source, per-model dispatch, embed/
transcribe estimators, format output, and addition. All math is unit-tested
against real token/dollar arithmetic. Unknown models are clear KeyError, not
silent zeros.

Run: env PYTHONDONTWRITEBYTECODE=1 python3 tests/test_cost.py
"""

import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

cost = importlib.import_module("klausmate.cost")

section("price table and arithmetic")
check("every price is dated in the source (a comment naming 2026-09-15 sits above PRICES)", "2026-09-15" in open(cost.__file__).read())
e = cost.estimate_embed(4_000_000)
check("embed: chars/4 tokens at the per-million input price", e.tokens == 1_000_000 and abs(e.dollars - cost.PRICES["text-embedding-3-large"][0]) < 1e-9)
t = cost.estimate_transcribe(3600)
check("transcribe: priced per minute, 60 minutes", abs(t.dollars - 60 * cost.PRICES["gpt-4o-mini-transcribe"][0]) < 1e-9)
check("format_estimate reads like '~1,000,000 tokens · about $0.13'", cost.format_estimate(e) == "~1,000,000 tokens · about $0.13")
check("format_estimate floors tiny sums at 'under $0.01'", cost.format_estimate(cost.Estimate(10, 0.000001)).endswith("under $0.01"))
s = cost.add(e, t)
check("add sums tokens and dollars", s.tokens == e.tokens + t.tokens and abs(s.dollars - (e.dollars + t.dollars)) < 1e-9)
try:
    cost.estimate_embed(1, "no-such-model"); ok = False
except KeyError:
    ok = True
check("unknown model raises KeyError", ok)
raise SystemExit(report())
