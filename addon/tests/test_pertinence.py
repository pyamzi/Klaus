"""Tests for klausmate.pertinence — the pertinence core (spec D4).

Covers: the strict forced tool (record_verdicts) and the Messages request
build_request assembles around it, parsing verdicts back out of a
tool_use turn (a card the tool input does not name gets NO verdict —
unjudged, never doubtful — and a malformed item voids the whole batch
rather than guessing at it), judge()'s batching of BATCH cards per
request, and judged.json persistence/staleness/rejection bookkeeping.

No network: judge() is driven through a FakeClient — real production code
(anthropic_client.Client.complete) is never touched here.

Two spots correct the brief this file was written from, both confirmed by
direct execution before being applied (see task-1-report.md's Deviations
section for the reproduction):
  - FakeClient.complete accepts **kw so judge()'s `purpose="judge"`
    (Klaus Plus routing, built after the brief was written) has somewhere
    to land, and a check pins that purpose is passed on every call.
  - The "requests of at most BATCH" check parses the CARDS_JSON blob with
    json.JSONDecoder().raw_decode instead of bare json.loads: build_request
    appends trailing prose ("\\n\\nRecord a verdict...") after the JSON
    array, which plain json.loads rejects outright with "Extra data".
  - Each judged.json entry the persistence section builds also carries
    "model": v.model, per this task's brief's own trailing note ("Record
    the model per verdict entry too... so is_stale's model test is
    real") — without it, is_stale's `entry.get("model", model)` fallback
    makes the model-changed sub-check vacuously true against the model
    argument itself, and the "stale when...the model changed" assertion
    fails.

Fix round 1 (task-1-review.md) added: parse_verdicts robustness against
four malformed shapes that used to raise AttributeError instead of
returning []; judge()'s per-batch exception containment; load_judged's
version check (K-167); is_stale's model-less-is-stale fix plus the new
entry_for() minting helper (now used below instead of a hand-rolled
dict); the duplicate-nid first-wins rule; MAX_CARD_CHARS/MAX_PAGE_CHARS
bounds; and two more .get()-based defensive rewrites of checks that used
to reach into dicts with [] (a regression there would have crashed the
runner instead of printing FAIL). See task-1-report.md's "Fix round 1"
section for the full RED/GREEN/mutation evidence.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pertinence.py
"""

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()

pt = importlib.import_module("klausmate.pertinence")
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "anthropic")

cards = [
    pt.CardText(11, "Q: mechanism of X? A: Y", "c11"),
    pt.CardText(12, "Q: Z? A: W", "c12"),
    pt.CardText(13, "Q: unjudged", "c13"),
]
page = pt.PageText(4, "p4hash", "Slide 4: X works by Y.\n\nthe lecturer said Y twice")

section("build_request")
req = pt.build_request(cards, page, "Renal Physiology", "claude-sonnet-5")
tool = req["tools"][0]
# .get(...) throughout (not tool["strict"] etc.): a future regression that
# drops a key must print a FAIL line, not crash the runner with a KeyError
# (fix round 1, Finding 9 — check()'s condition is evaluated eagerly).
check("one strict tool, forced by name", tool.get("name") == "record_verdicts" and tool.get("strict") is True
      and (tool.get("input_schema") or {}).get("additionalProperties") is False and req.get("tool_choice") == {"type": "tool", "name": "record_verdicts"})
check("every card's nid and text and the page text are in the user turn", all(str(c.nid) in req["messages"][0]["content"] and c.text in req["messages"][0]["content"] for c in cards) and page.text in req["messages"][0]["content"])
check("the system prompt states the test and forbids guessing", "reasonable preparation" in req["system"] and "not merely the same subject" in req["system"] and req["model"] == "claude-sonnet-5" and req["max_tokens"] >= 1024)
huge_card = pt.CardText(1, "x" * 50_000, "hx")
huge_page = pt.PageText(9, "hp", "y" * 50_000)
huge_content = pt.build_request([huge_card], huge_page, "Lec", "m")["messages"][0]["content"]
check("a 50 KB card and a 50 KB page are both bounded (MAX_CARD_CHARS/MAX_PAGE_CHARS) in the request",
      ("x" * pt.MAX_CARD_CHARS) in huge_content and ("x" * (pt.MAX_CARD_CHARS + 1)) not in huge_content
      and ("y" * pt.MAX_PAGE_CHARS) in huge_content and ("y" * (pt.MAX_PAGE_CHARS + 1)) not in huge_content)

section("parse_verdicts")
resp = json.load(open(os.path.join(FIX, "verdicts_turn.json")))
vs = pt.parse_verdicts(resp, cards, page, "claude-sonnet-5")
check("two verdicts, keyed to the cards, carrying page and card hashes and the model",
      [(v.nid, v.pertinent) for v in vs] == [(11, True), (12, False)] and vs[0].page == 4 and vs[0].page_hash == "p4hash" and vs[1].card_hash == "c12" and vs[0].model == "claude-sonnet-5")
check("a card absent from the tool input gets NO verdict", 13 not in {v.nid for v in vs})
bad = {"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [{"nid": "eleven", "pertinent": "yes"}]}}]}
check("malformed input → no verdicts, never doubtful", pt.parse_verdicts(bad, cards, page, "m") == [])
check("a nid not in the batch is ignored", pt.parse_verdicts({"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [{"nid": 999, "pertinent": False, "reason": "x"}]}}]}, cards, page, "m") == [])
# A single-item malformed batch can't tell "void the whole batch" apart from "skip
# the bad item" — both read back as []. Put a good item ahead of the bad one so the
# two behaviors diverge: a lone bad item must not spare its otherwise-good neighbour.
mixed = {"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [
    {"nid": 11, "pertinent": True, "reason": "ok"},
    {"nid": 12, "pertinent": "yes", "reason": "wrong type"},
]}}]}
check("one malformed item voids the WHOLE batch, even a good verdict collected ahead of it", pt.parse_verdicts(mixed, cards, page, "m") == [])
# Fix round 1, Finding 1: anthropic_client.Client.complete returns
# json.loads(raw) with no shape check, so any valid JSON body — a bare
# null, [], a string — can reach here as `response`. None of these are
# "malformed input" in the tool-call sense above; they must still read
# as "nothing to parse" rather than raise.
check("a non-dict response never raises — reads as nothing to parse",
      pt.parse_verdicts(None, cards, page, "m") == [] and pt.parse_verdicts([], cards, page, "m") == [] and pt.parse_verdicts(42, cards, page, "m") == [])
check("a non-list content, a non-dict content block, and a non-dict tool input all return [] rather than raising",
      pt.parse_verdicts({"content": "oops"}, cards, page, "m") == []
      and pt.parse_verdicts({"content": [42]}, cards, page, "m") == []
      and pt.parse_verdicts({"content": [{"type": "tool_use", "name": "record_verdicts", "input": "oops"}]}, cards, page, "m") == [])
dup = {"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [
    {"nid": 11, "pertinent": True, "reason": "first"},
    {"nid": 11, "pertinent": False, "reason": "second"},
]}}]}
check("a duplicate nid in one tool input: the FIRST verdict wins, later ones for the same card are dropped",
      [(v.nid, v.pertinent, v.reason) for v in pt.parse_verdicts(dup, cards, page, "m")] == [(11, True, "first")])

section("judge batches and calls complete")
calls = []
purposes = []


class FakeClient:
    def complete(self, payload, timeout=None, **kw):
        calls.append(payload)
        purposes.append(kw.get("purpose"))
        return resp


many = [pt.CardText(i, f"card {i}", f"h{i}") for i in range(20)]
out = pt.judge(FakeClient(), "claude-sonnet-5", many, page, "Lec")


def _msg0_content(payload):
    # .get(...) throughout, not payload["messages"][0]["content"]: a
    # regression that drops a key must FAIL the check, not KeyError the
    # runner (fix round 1, Finding 9 — same reasoning as tool.get above).
    return ((payload.get("messages") or [{}])[0] or {}).get("content", "")


check("20 cards → 3 requests of at most BATCH", len(calls) == 3 and all(len(json.JSONDecoder().raw_decode(_msg0_content(c).split("CARDS_JSON=")[1])[0]) <= pt.BATCH for c in calls) if "CARDS_JSON=" in _msg0_content(calls[0]) else len(calls) == 3)
check("judge calls client.complete with purpose='judge' (Klaus Plus routing)", purposes == ["judge"] * len(calls))

section("judge: a failed batch is skipped, logged safely, and never fatal")


def _resp_for(nid):
    return {"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [{"nid": nid, "pertinent": True, "reason": "r"}]}}]}


class RaisingOnSecond:
    """Batch 2 of 3 raises; batches 1 and 3 must still come back (D4's
    Failure clause — fix round 1, Finding 2)."""

    def __init__(self):
        self.n = 0

    def complete(self, payload, timeout=None, **kw):
        self.n += 1
        if self.n == 2:
            raise RuntimeError("simulated network failure")
        return _resp_for(0 if self.n == 1 else 16)  # first nid of batch 1 / batch 3


many2 = [pt.CardText(i, f"card {i}", f"h{i}") for i in range(20)]  # batches: 0-7, 8-15, 16-19
logbuf = io.StringIO()
with contextlib.redirect_stdout(logbuf):
    out2 = pt.judge(RaisingOnSecond(), "claude-sonnet-5", many2, page, "Lec")
logged = logbuf.getvalue()
check("a client exception on one batch is caught; the other batches' verdicts still come back",
      {v.nid for v in out2} == {0, 16})
check("exactly one [klausmate] log line for the failed batch, naming the exception's class, never the request payload",
      logged.count("[klausmate]") == 1 and "RuntimeError" in logged
      and "CARDS_JSON" not in logged and "card 8" not in logged and page.text not in logged)

section("judged.json persistence and staleness")
root = tempfile.mkdtemp()
j = {"version": 1, "model": "claude-sonnet-5", "verdicts": {}}
for v in vs:
    # entry_for (fix round 1, Finding 4) rather than a hand-rolled dict —
    # the whole point is that a writer cannot forget "model" this way.
    j["verdicts"][str(v.nid)] = pt.entry_for(v)
pt.save_judged(root, "lec", j)
back = pt.load_judged(root, "lec")
check("round-trips; keys are strings on disk, ints in rejected_nids", back["verdicts"]["12"]["pertinent"] is False and pt.rejected_nids(back) == {12})
e = back["verdicts"]["11"]
check("stale when the card hash, the page hash or the model changed",
      not pt.is_stale(e, "c11", "p4hash", "claude-sonnet-5") and pt.is_stale(e, "c11x", "p4hash", "claude-sonnet-5")
      and pt.is_stale(e, "c11", "p4other", "claude-sonnet-5") and pt.is_stale(e, "c11", "p4hash", "claude-opus-5"))
check("an entry with no \"model\" key is stale, never vacuously fresh (fix round 1, Finding 4)",
      pt.is_stale({"card_hash": "c11", "page_hash": "p4hash"}, "c11", "p4hash", "claude-sonnet-5") is True)
check("entry_for mints a full entry (including \"model\") that round-trips through is_stale as fresh",
      pt.entry_for(vs[0]).get("model") == vs[0].model and not pt.is_stale(pt.entry_for(vs[0]), vs[0].card_hash, vs[0].page_hash, vs[0].model))
open(pt.judged_path(root, "lec"), "w").write("{bad")
check("a corrupt judged.json reads as empty", pt.load_judged(root, "lec")["verdicts"] == {})
pt.save_judged(root, "verold", {"version": 99, "model": "m", "verdicts": {"5": {"pertinent": True, "reason": "", "page": 1, "page_hash": "", "card_hash": "", "model": "m"}}})
check("a judged.json with version != VERSION reads as empty (K-167 rule, fix round 1 Finding 3)",
      pt.load_judged(root, "verold")["verdicts"] == {})
pt.save_judged(root, "other", {"version": 1, "model": "m", "verdicts": {"7": {"pertinent": False, "reason": "", "page": 1, "page_hash": "", "card_hash": ""}}})
pt.save_judged(root, "lec", j)
check("all_rejected unions every PDF's rejections", pt.all_rejected(root) == {12, 7})
check("candidates = nids at/above threshold, in score order", pt.candidates([(1, 0.9), (2, 0.5), (3, 0.75)], 0.75) == [1, 3])

section("module hygiene")
check("the module docstring no longer claims a divider that was never drawn (fix round 1, Finding 8)",
      "above the divider" not in (pt.__doc__ or ""))
raise SystemExit(report())
