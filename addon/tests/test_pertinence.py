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
import types

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
# M-9(1): the OUTER additionalProperties above says nothing about the verdict
# objects themselves. Closing only the wrapper would let the model return
# {"nid":…, "pertinent":…, "reason":…, "confidence":…} — or drop "reason"
# entirely — and still satisfy `strict: true`, which is exactly what this
# schema exists to forbid. Same .get() discipline: a dropped key FAILs here
# rather than KeyError-ing the runner.
_items = (((tool.get("input_schema") or {}).get("properties") or {}).get("verdicts") or {}).get("items") or {}
check("each verdict object is closed too: additionalProperties false and all three fields required",
      _items.get("additionalProperties") is False
      and set(_items.get("required") or []) == {"nid", "pertinent", "reason"}
      and set((_items.get("properties") or {})) == {"nid", "pertinent", "reason"}, _items)
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

section("judge forwards on_headers to client.complete (Task 3: Klaus Plus quota readout)")
_oh_seen = []


class OHClient:
    def complete(self, payload, timeout=None, **kw):
        # "MISSING" (fix round 1, M1): kw.get("on_headers") alone reads
        # back None whether the kwarg was forwarded as None or dropped
        # entirely — this sentinel default is what tells those two apart.
        _oh_seen.append(kw.get("on_headers", "MISSING"))
        return resp


_oh_sentinel = lambda h: None  # noqa: E731 — identity is all this checks
pt.judge(OHClient(), "claude-sonnet-5", cards[:1], page, "Lec", on_headers=_oh_sentinel)
check("judge() forwards on_headers straight through to client.complete", _oh_seen == [_oh_sentinel])
pt.judge(OHClient(), "claude-sonnet-5", cards[:1], page, "Lec")
check("...and omitting it forwards None rather than dropping the kwarg", _oh_seen[-1] is None)

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

section("judge: a refusal ends the call, a hiccup does not (final review I-1/M-1)")


class _Refused(Exception):
    """anthropic_client.LLMError's shape without importing it — a .status
    plus a user_message() already phrased for the user."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status

    def user_message(self):
        return str(self)


class RefusingClient:
    def __init__(self, status):
        self.status = status
        self.n = 0

    def complete(self, payload, timeout=None, **kw):
        self.n += 1
        raise _Refused("Klaus Plus: monthly card quota used up.", self.status)


many3 = [pt.CardText(i, f"card {i}", f"h{i}") for i in range(20)]  # three batches
_fatals = []
_ref = RefusingClient(402)
with contextlib.redirect_stdout(io.StringIO()):
    _out3 = pt.judge(_ref, "m", many3, page, "Lec", on_fatal=_fatals.append)
check("a 402 on batch 1 of 3 sends NO further batch — an exhausted quota answers "
      "every remaining batch the same way", _ref.n == 1 and _out3 == [])
check("...and on_fatal fires exactly once, handed the exception itself",
      len(_fatals) == 1 and getattr(_fatals[0], "status", None) == 402)
_each = {}
for _st in pt.FATAL_STATUS:
    _c, _f = RefusingClient(_st), []
    with contextlib.redirect_stdout(io.StringIO()):
        pt.judge(_c, "m", many3, page, "Lec", on_fatal=_f.append)
    _each[_st] = (_c.n, len(_f))
check("every FATAL_STATUS — 401 key, 402 quota, 403 licence, 426 client version — "
      "breaks after one request and reports once",
      tuple(pt.FATAL_STATUS) == (401, 402, 403, 426) and all(v == (1, 1) for v in _each.values()), _each)
_c500, _f500 = RefusingClient(500), []
with contextlib.redirect_stdout(io.StringIO()):
    pt.judge(_c500, "m", many3, page, "Lec", on_fatal=_f500.append)
check("a 500 is NOT a refusal: all three batches are still attempted and on_fatal never "
      "fires — D4's per-batch rule stands", _c500.n == 3 and _f500 == [])
_fnet = []
with contextlib.redirect_stdout(io.StringIO()):
    _outnet = pt.judge(RaisingOnSecond(), "claude-sonnet-5", many2, page, "Lec", on_fatal=_fnet.append)
check("a status-less network failure is not a refusal either — batches 1 and 3 still land, "
      "on_fatal stays silent", {v.nid for v in _outnet} == {0, 16} and _fnet == [])


def _boom_fatal(_exc):
    raise RuntimeError("reporting blew up")


_boom_c = RefusingClient(401)
_boom_log = io.StringIO()
# Caught here on purpose: without the guard inside judge() this raise would
# abort the whole file instead of printing one FAIL line, and a mutation that
# kills the runner is a mutation nobody reads.
_boom_out, _boom_raised = None, None
try:
    with contextlib.redirect_stdout(_boom_log):
        _boom_out = pt.judge(_boom_c, "m", many3, page, "Lec", on_fatal=_boom_fatal)
except Exception as _boom_exc:  # noqa: BLE001
    _boom_raised = _boom_exc
check("a raising on_fatal is logged and swallowed — reporting a refusal must never become one",
      _boom_raised is None and _boom_out == [] and _boom_c.n == 1
      and "on_fatal failed" in _boom_log.getvalue()
      and "RuntimeError" in _boom_log.getvalue(), (_boom_raised, _boom_log.getvalue()))


class _CountingClient:
    def __init__(self):
        self.n = 0

    def complete(self, payload, timeout=None, **kw):
        self.n += 1
        return _resp_for(0)


class _CancelAfter:
    """Stop landing after `after` requests have gone out — the real cancel
    token is an Event some other thread sets mid-page."""

    def __init__(self, client, after):
        self._c, self._after = client, after

    def is_set(self):
        return self._c.n >= self._after


_cc = _CountingClient()
pt.judge(_cc, "m", many3, page, "Lec", cancel=_CancelAfter(_cc, 1))
check("M-1: Stop landing mid-page stops the very next batch — one paid request, not the "
      "page's remaining three", _cc.n == 1)
_cc2 = _CountingClient()
pt.judge(_cc2, "m", many3, page, "Lec", cancel=_CancelAfter(_cc2, 0))
check("...a cancel already set before the first batch sends nothing at all", _cc2.n == 0)
_cc3 = _CountingClient()
pt.judge(_cc3, "m", many3, page, "Lec")
check("...and cancel=None (the default) is never read as cancelled", _cc3.n == 3)

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
_strict_raised = False
try:
    pt.load_judged(root, "lec", strict=True)
except ValueError:
    _strict_raised = True
check("...but strict=True raises on it (tag_sync.doubtful_members reads strictly so an"
      " unreadable store can never read as 'nobody rejected')", _strict_raised)
check("strict=True still reads a MISSING store as empty — absent is not corrupt",
      pt.load_judged(root, "never-judged", strict=True)["verdicts"] == {})
pt.save_judged(root, "verold", {"version": 99, "model": "m", "verdicts": {"5": {"pertinent": True, "reason": "", "page": 1, "page_hash": "", "card_hash": "", "model": "m"}}})
check("a judged.json with version != VERSION reads as empty (K-167 rule, fix round 1 Finding 3)",
      pt.load_judged(root, "verold")["verdicts"] == {})
pt.save_judged(root, "other", {"version": 1, "model": "m", "verdicts": {"7": {"pertinent": False, "reason": "", "page": 1, "page_hash": "", "card_hash": ""}}})
pt.save_judged(root, "lec", j)
check("all_rejected unions every PDF's rejections", pt.all_rejected(root) == {12, 7})
check("candidates = nids at/above threshold, in score order", pt.candidates([(1, 0.9), (2, 0.5), (3, 0.75)], 0.75) == [1, 3])

section("ensure_judged: the aqt glue (fake mw/col/client; real, disk-backed retention/page_store)")

retention = importlib.import_module("klausmate.retention")
pdf_handler = importlib.import_module("klausmate.pdf_handler")
page_store = importlib.import_module("klausmate.page_store")
iq = importlib.import_module("klausmate.index_queue")
plus = importlib.import_module("klausmate.plus")
cost = importlib.import_module("klausmate.cost")


class SyncOp:
    """QueryOp stand-in that runs `op` synchronously. anki_stubs' own
    aqt.operations.QueryOp (_AnyOp) is chainable but NEVER calls `op` or
    `success` at all — right for tests that don't care what background
    work computes, wrong for this one, which has to see judged.json
    actually written (test_klausmate.py's _SyncOp is the same idea, for
    the same reason)."""

    def __init__(self, parent=None, op=None, success=None):
        self._op = op
        self._success = success
        self._failure = None

    def failure(self, fn):
        self._failure = fn
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        try:
            result = self._op(None)
        except Exception as exc:  # noqa: BLE001
            if self._failure:
                self._failure(exc)
            return
        if self._success:
            self._success(result)


class GlueCol:
    def __init__(self, fields_by_nid):
        self._fields = fields_by_nid

    def get_note(self, nid):
        return types.SimpleNamespace(fields=self._fields[nid])


class GlueAddonManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def getConfig(self, _pkg):
        return self.cfg


class GlueMw:
    def __init__(self, cfg, fields_by_nid):
        self.col = GlueCol(fields_by_nid)
        self.taskman = types.SimpleNamespace(run_on_main=lambda fn: fn())
        self.addonManager = GlueAddonManager(cfg)


class GlueAnthropicClient:
    def __init__(self, _get_config):
        pass

    def complete(self, payload, timeout=None, purpose="assistant", *, on_headers=None, **kw):
        _client_calls.append((payload, purpose, on_headers))
        if _client_raises:  # I-1: armed per test, popped one refusal per request
            raise _client_raises.pop(0)
        if on_headers is not None:
            # Mirrors the real Client: invoke it with something that has
            # .items(), the shape plus.parse_quota expects (fix round 1, M2).
            on_headers({"X-Klaus-Quota": json.dumps({"human": {"cards": [412, 3000]}})})
        return resp  # the verdicts_turn.json fixture: nid 11 pertinent, 12 not


def make_ask(respond):
    """A fake `ask` — records the text it was shown and, unless *respond*
    is None (the "must not even be asked" cases), answers synchronously."""
    log = []

    def ask_fn(_parent, text, go):
        log.append(text)
        if respond is not None:
            go(respond)

    return ask_fn, log


_client_calls = []
_client_raises: list = []
_fake_anthropic = types.ModuleType("klausmate.anthropic_client")
_fake_anthropic.Client = GlueAnthropicClient
sys.modules["klausmate.anthropic_client"] = _fake_anthropic
pkg = sys.modules["klausmate"]
pkg.anthropic_client = _fake_anthropic
# anki_stubs' package stub is a bare types.ModuleType — the real __init__.py
# (and its _strip_html) never runs under it. _pkg()._strip_html (curation.py's
# own pattern, reused here) needs SOMETHING there; the test's card fields
# carry no HTML anyway, so identity is faithful enough.
pkg._strip_html = lambda s: s

_root = tempfile.mkdtemp(prefix="klaus-pertinence-")
retention.USER_FILES = _root
pkg.USER_FILES = _root
pt.QueryOp = SyncOp

_fields = {11: ["Q: mechanism of X?", "A: Y"], 12: ["Q: Z?", "A: W"], 13: ["Q: unjudged"]}
_cfg_no_plus = {"api_key_anthropic": "sk-ant-fake", "pdf_match_threshold": 0.75}
iq.mw = GlueMw(_cfg_no_plus, _fields)

page_store.ensure_records(_root, "lec", "", ["", "", "", "Slide 4: X works by Y."])
os.makedirs(os.path.dirname(retention._matches_path("lec")), exist_ok=True)
with open(retention._matches_path("lec"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"11": 4, "12": 4, "13": 4}}, f)

_done, _errors = [], []
ask_yes, ask_yes_log = make_ask(True)
pt.ensure_judged(
    iq.mw, "lec", [(11, 0.9), (12, 0.85), (13, 0.5)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_yes,
)
check("no on_error fired", _errors == [])
check("threshold .75: 11 and 12 are candidates, 13 (0.5) never sent — the "
      "confirm counts exactly 2 cards", "2 matched cards" in ask_yes_log[-1])
check("off Plus, the estimate is spelled in dollars and billed to the "
      "user's own key", "billed to your Anthropic key" in ask_yes_log[-1] and "Klaus Plus" not in ask_yes_log[-1])
check("one client call for one batch of 2 cards", len(_client_calls) == 1 and _client_calls[0][1] == "judge")
check("on_done reports card 12 rejected (the fixture's own verdict), 11 confirmed by omission", _done == [{12}])
_saved = pt.load_judged(_root, "lec")
check("judged.json carries entries for 11 and 12 only — 13 was never a candidate",
      set(_saved["verdicts"].keys()) == {"11", "12"})
check("...11 pertinent, 12 not, per the fixture", _saved["verdicts"]["11"]["pertinent"] is True and _saved["verdicts"]["12"]["pertinent"] is False)

_done.clear()
ask_should_skip, ask_should_skip_log = make_ask(None)
pt.ensure_judged(
    iq.mw, "lec", [(11, 0.9), (12, 0.85), (13, 0.5)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_should_skip,
)
check("a second call with unchanged hashes makes NO client call — everything is cached",
      len(_client_calls) == 1)
check("...and never even shows the paid-pass prompt — nothing new to pay for", ask_should_skip_log == [])
check("...still reports the same rejection, read back from judged.json", _done == [{12}])

# is_stale is what decides "cached" above — mutation-tests that its actual
# comparison, not just its EFFECT, has teeth: a hardcoded `is_stale ->
# False` would still pass every check so far (nothing has changed yet, so
# "no client call" reads the same whether staleness is computed or faked).
# Only a card whose text really moved can catch that.
_fields[11] = ["Q: mechanism of X, revised?", "A: Y, still"]
_done.clear()
_calls_before_rejudge = len(_client_calls)
ask_yes2, ask_yes2_log = make_ask(True)
pt.ensure_judged(
    iq.mw, "lec", [(11, 0.9), (12, 0.85), (13, 0.5)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_yes2,
)
check("a changed card hash re-judges — only card 11 moved, so only it is "
      "sent (card 12's own cache entry is untouched)",
      len(_client_calls) == _calls_before_rejudge + 1 and "1 matched cards" in ask_yes2_log[-1])
check("...and the fresh verdict lands in judged.json same as before",
      pt.load_judged(_root, "lec")["verdicts"]["11"]["pertinent"] is True)

page_store.ensure_records(_root, "lec2", "", ["", "", "", "Slide 4 of a different lecture."])
os.makedirs(os.path.dirname(retention._matches_path("lec2")), exist_ok=True)
with open(retention._matches_path("lec2"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"11": 4, "12": 4}}, f)
_done.clear()
_calls_before_skip = len(_client_calls)
ask_no, ask_no_log = make_ask(False)
pt.ensure_judged(
    iq.mw, "lec2", [(11, 0.9), (12, 0.85)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_no,
)
check("Skip is honoured — no client call for the declined job", len(_client_calls) == _calls_before_skip)
check("...and every candidate stays unjudged: on_done(set())", _done == [set()])
check("...judged.json for THIS pdf stays empty too", pt.load_judged(_root, "lec2")["verdicts"] == {})

_done.clear()
_calls_before_nokey = len(_client_calls)
ask_must_not_run, ask_must_not_run_log = make_ask(None)
# _cfg() (borrowed from index_queue) reads index_queue's OWN mw global, not
# whatever `parent` a caller hands ensure_judged — true in production too,
# where `parent` passed to ensure_judged always IS index_queue's mw. So the
# no-key config has to be armed on iq.mw itself, not just passed as parent.
_nokey_mw = GlueMw({"pdf_match_threshold": 0.75}, _fields)
iq.mw = _nokey_mw
_nokey_log = io.StringIO()
with contextlib.redirect_stdout(_nokey_log):
    pt.ensure_judged(
        _nokey_mw, "lec", [(11, 0.9), (12, 0.85), (13, 0.5)],
        on_done=_done.append, on_error=_errors.append, cancel=None,
        on_progress=lambda *a: None, ask=ask_must_not_run,
    )
check(
    "no Anthropic key and not on Klaus Plus: do not ask, do not judge — "
    "one [klausmate] line, and on_done reports the verdicts ALREADY ON "
    "DISK (PR #4 second re-review): card 12 was judged and paid for in "
    "the earlier run, and its entry is keyed on that card's and that "
    "page's own text hashes, so pulling the key must never silently "
    "un-doubt it — retention and tag_sync go on reading the same store "
    "whatever this phase answers",
    _nokey_log.getvalue().count("[klausmate]") == 1 and ask_must_not_run_log == [] and _done == [{12}],
    _nokey_log.getvalue(),
)
check("...and the log says the earlier verdicts stand, rather than implying "
      "every match now counts",
      "stays unjudged; earlier verdicts stand" in _nokey_log.getvalue(),
      _nokey_log.getvalue())
check("...and never touches the client either", len(_client_calls) == _calls_before_nokey)

# The other half: nothing on disk really does mean nothing rejected — the
# fix must read the store, not invent members for it.
_done.clear()
_nokey_log2 = io.StringIO()
with contextlib.redirect_stdout(_nokey_log2):
    pt.ensure_judged(
        _nokey_mw, "lec2", [(11, 0.9), (12, 0.85)],
        on_done=_done.append, on_error=_errors.append, cancel=None,
        on_progress=lambda *a: None, ask=ask_must_not_run,
    )
check("a PDF nobody has ever judged still reports nothing rejected on the "
      "same keyless path", _done == [set()], repr(_done))

# ---------------------------------------------------------------------
# PR #4 third re-review (Copilot), finding 3: the keyless early return
# used to sit ABOVE the candidate/staleness pass, so it reported every
# stored `pertinent: false` entry without ever asking is_stale. A card
# (or its page) edited after the last paid run therefore stayed Doubtful
# forever for as long as the user had no key — contradicting the
# documented contract that a verdict lasts until the card, the page or
# the model changes, and contradicting the KEYED path, which retires
# exactly those entries. The gate now sits BELOW the pass: same one log
# line, same no-prompt, but the store is pruned first and the report
# comes off the pruned store.
# ---------------------------------------------------------------------
page_store.ensure_records(_root, "lec3", "", ["", "", "", "Slide 4 of a third lecture."])
os.makedirs(os.path.dirname(retention._matches_path("lec3")), exist_ok=True)
with open(retention._matches_path("lec3"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"12": 4, "13": 4}}, f)
_page_hash3 = page_store.text_hash(page_store.load_record(_root, "lec3", "", 3))
_, _card_hash12 = pt._card_text(_nokey_mw.col, 12, lambda s: s)


def _entry3(card_hash):
    return {"pertinent": False, "reason": "rejected in an earlier paid run",
            "page": 4, "page_hash": _page_hash3, "card_hash": card_hash,
            "model": "claude-sonnet-5"}


pt.save_judged(_root, "lec3", {"version": pt.VERSION, "model": "claude-sonnet-5",
                               "verdicts": {"12": _entry3(_card_hash12),
                                            "13": _entry3("hash-of-text-long-gone")}})
check("the fixture really holds two rejections, one of them stale (or the "
      "pins below prove nothing)",
      pt.rejected_nids(pt.load_judged(_root, "lec3")) == {12, 13}
      and not pt.is_stale(_entry3(_card_hash12), _card_hash12, _page_hash3, "claude-sonnet-5")
      and pt.is_stale(_entry3("hash-of-text-long-gone"),
                      pt._card_text(_nokey_mw.col, 13, lambda s: s)[1],
                      _page_hash3, "claude-sonnet-5"))
_done.clear()
_calls_before_stale = len(_client_calls)
_nokey_log3 = io.StringIO()
with contextlib.redirect_stdout(_nokey_log3):
    pt.ensure_judged(
        _nokey_mw, "lec3", [(12, 0.9), (13, 0.85)],
        on_done=_done.append, on_error=_errors.append, cancel=None,
        on_progress=lambda *a: None, ask=ask_must_not_run,
    )
check("keyless: the FRESH rejection is reported and the STALE one is not — "
      "no key is not a reason to keep a card doubtful over text that no "
      "longer exists",
      _done == [{12}], repr(_done))
check("...and the stale entry is really gone from judged.json, so every "
      "other reader of the store (retention, tag_sync) agrees with what "
      "this phase just reported",
      set(pt.load_judged(_root, "lec3")["verdicts"].keys()) == {"12"},
      repr(pt.load_judged(_root, "lec3")["verdicts"]))
check("...still no prompt, still no client call, still exactly one log line",
      ask_must_not_run_log == [] and len(_client_calls) == _calls_before_stale
      and _nokey_log3.getvalue().count("[klausmate]") == 1,
      _nokey_log3.getvalue())

check("no on_error ever fired across the whole glue section", _errors == [])

section("ensure_judged: fix round 1, C1 — an un-priced reasoning_model never wedges the phase")
check("claude-sonnet-4-5 really is absent from cost.PRICES (or this pin proves nothing)",
      "claude-sonnet-4-5" not in cost.PRICES)
page_store.ensure_records(_root, "lec_unpriced", "", ["", "", "", "Slide 4 of an unpriced-model lecture."])
os.makedirs(os.path.dirname(retention._matches_path("lec_unpriced")), exist_ok=True)
with open(retention._matches_path("lec_unpriced"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"21": 4}}, f)
_unpriced_mw = GlueMw(
    {"api_key_anthropic": "sk-ant-fake", "pdf_match_threshold": 0.75, "reasoning_model": "claude-sonnet-4-5"},
    {21: ["Q: unpriced model?", "A: still judged"]},
)
iq.mw = _unpriced_mw
_done.clear()
ask_unpriced, ask_unpriced_log = make_ask(True)
pt.ensure_judged(
    _unpriced_mw, "lec_unpriced", [(21, 0.9)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_unpriced,
)
check("a model with no published price never raises cost.estimate_judge's KeyError out of ensure_judged",
      bool(ask_unpriced_log))
check("...the off-Plus prompt still appears, priced as Sonnet and saying so",
      ask_unpriced_log and "priced as Sonnet" in ask_unpriced_log[-1] and "billed to your Anthropic key" in ask_unpriced_log[-1])
check("...and the job completes normally: on_done fires, nothing raised", _done == [set()] and _errors == [])

section("ensure_judged: fix round 1, M2 — the Klaus Plus branch")
_patch_calls = []
pkg.patch_config = lambda updates: _patch_calls.append(updates)
page_store.ensure_records(_root, "lec_plus", "", ["", "", "", "Slide 4 of a Plus lecture."])
os.makedirs(os.path.dirname(retention._matches_path("lec_plus")), exist_ok=True)
with open(retention._matches_path("lec_plus"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"31": 4, "32": 4}}, f)
_plus_cfg = {
    plus.KEY: "kp_" + "f" * 32,
    plus.CACHE: {"status": "active", "checked_at": 0.0, "quota": {"human": {"cards": [412, 3000]}}},
}
_plus_mw = GlueMw(_plus_cfg, {31: ["Q: Plus mechanism?", "A: Plus answer"], 32: ["Q: Plus Z?", "A: Plus W"]})
iq.mw = _plus_mw
_done.clear()
_calls_before_plus = len(_client_calls)
ask_plus, ask_plus_log = make_ask(True)
pt.ensure_judged(
    _plus_mw, "lec_plus", [(31, 0.9), (32, 0.85)],
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_plus,
)
check("no Anthropic key is present in the Plus cfg at all, and none is asked for", "api_key_anthropic" not in _plus_cfg)
check("the Plus prompt reads in quota terms — no dollar sign, the live cache's usage named",
      ask_plus_log and "Klaus Plus" in ask_plus_log[-1] and "$" not in ask_plus_log[-1]
      and "412" in ask_plus_log[-1] and "3,000" in ask_plus_log[-1])
check("Plus is metered, not free — one client call still happens", len(_client_calls) == _calls_before_plus + 1)
check("...and on_headers reached judge/client.complete non-None (the fake client recorded it)",
      _client_calls[-1][2] is not None)
check("...which the fake client used exactly like the real one would, routing through "
      "plus.note_quota into patch_config as a PATCH, never a config replace",
      len(_patch_calls) == 1 and _patch_calls[0].get(plus.CACHE, {}).get("status") == "active")
check("no on_error fired on the Plus path either", _errors == [])

section("ensure_judged: final review I-1 — a refusal is remembered on Plus and always shown")
_tips = []
pt.tooltip = lambda text, period=None: _tips.append(text)

# TWO pages, so "the job stopped" is distinguishable from "that page stopped":
# judge() is called once per page, and only a break in ensure_judged's own page
# loop keeps the second page's batch off the wire.
page_store.ensure_records(_root, "lec_refused", "", ["", "", "", "Slide 4 refused.", "Slide 5 refused."])
os.makedirs(os.path.dirname(retention._matches_path("lec_refused")), exist_ok=True)
with open(retention._matches_path("lec_refused"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"41": 4, "42": 5}}, f)
_plus_cfg2 = {plus.KEY: "kp_" + "e" * 32, plus.CACHE: {"status": "active", "checked_at": 0.0}}
_refuse_mw = GlueMw(_plus_cfg2, {41: ["Q: page four?", "A: yes"], 42: ["Q: page five?", "A: also"]})
iq.mw = _refuse_mw
_patch_calls.clear()
_done.clear()
_calls_before_refusal = len(_client_calls)
_client_raises.clear()
_client_raises.extend([_Refused("Klaus Plus: monthly card quota used up.", 402)] * 2)
ask_refuse, ask_refuse_log = make_ask(True)
_refuse_log = io.StringIO()
with contextlib.redirect_stdout(_refuse_log):
    pt.ensure_judged(
        _refuse_mw, "lec_refused", [(41, 0.9), (42, 0.85)],
        on_done=_done.append, on_error=_errors.append, cancel=None,
        on_progress=lambda *a: None, ask=ask_refuse,
    )
check("a 402 on the first page stops the WHOLE job — the second page's batch is never sent",
      len(_client_calls) == _calls_before_refusal + 1, len(_client_raises))
check("...the refusal is cached through patch_config as a PATCH of the ONE cache key, "
      "never a whole-config replace",
      len(_patch_calls) == 1 and set(_patch_calls[0]) == {plus.CACHE}
      and _patch_calls[0][plus.CACHE].get("status") == "refused:402", _patch_calls)
check("...which really flips plus.active off, so the next index stops claiming an active "
      "subscription and re-prompting “Included in Klaus Plus”",
      plus.active(_plus_cfg2) is True and plus.active({**_plus_cfg2, **_patch_calls[0]}) is False)
check("...the user is told exactly once, in the service's own words",
      _tips == ["Klaus Plus: monthly card quota used up."], _tips)
check("...the job still finishes and still reports — Judge stops being indistinguishable "
      "from Skip, but never becomes an error",
      _done == [set()] and _errors == [])
check("...and the licence key is in neither the log nor the tooltip",
      _plus_cfg2[plus.KEY] not in _refuse_log.getvalue() and _plus_cfg2[plus.KEY] not in "".join(_tips))

_client_raises.clear()
page_store.ensure_records(_root, "lec_rej_free", "", ["", "", "", "Slide 4 free-tier."])
os.makedirs(os.path.dirname(retention._matches_path("lec_rej_free")), exist_ok=True)
with open(retention._matches_path("lec_rej_free"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"51": 4}}, f)
_free_mw = GlueMw({"api_key_anthropic": "sk-ant-fake", "pdf_match_threshold": 0.75},
                  {51: ["Q: expired key?", "A: say so"]})
iq.mw = _free_mw
_patch_calls.clear()
_tips.clear()
_done.clear()
_client_raises.append(_Refused("That API key was rejected — check it under KlausMate Preferences.", 401))
ask_free, _ask_free_log = make_ask(True)
with contextlib.redirect_stdout(io.StringIO()):
    pt.ensure_judged(
        _free_mw, "lec_rej_free", [(51, 0.9)],
        on_done=_done.append, on_error=_errors.append, cancel=None,
        on_progress=lambda *a: None, ask=ask_free,
    )
check("off Plus an expired Anthropic key is SHOWN too — the free tier's own 401 was the "
      "other half of the silence", _tips == ["That API key was rejected — check it under KlausMate Preferences."], _tips)
check("...and NOTHING is written to the Klaus Plus cache for a user who has no licence",
      _patch_calls == [])
check("...the job still completes normally", _done == [set()] and _errors == [])
_client_raises.clear()

section("ensure_judged: PR #4 F1 — a stale verdict is RETIRED the moment it is detected")
# Copilot/Codex on stacked PR #4: a stale entry was queued for re-judging
# but LEFT in judged.json, so every completion path that doesn't reach a
# fresh verdict for it — Skip, cancel, a fatal refusal, a batch that
# fails or omits the card — went on reporting the obsolete rejection, and
# retention/tag_sync went on calling the card Doubtful though it is now
# unjudged. D4's rule is that an unjudged card counts as CONFIRMED.
_stale_fields = {11: ["Q: stale mechanism of X?", "A: Y"], 12: ["Q: stale Z?", "A: W"]}
_stale_mw = GlueMw({"api_key_anthropic": "sk-ant-fake", "pdf_match_threshold": 0.75}, _stale_fields)
iq.mw = _stale_mw
page_store.ensure_records(_root, "lec_stale", "", ["", "", "", "Slide 4 of the stale-verdict lecture."])
os.makedirs(os.path.dirname(retention._matches_path("lec_stale")), exist_ok=True)
with open(retention._matches_path("lec_stale"), "w", encoding="utf-8") as f:
    json.dump({"pages": {"11": 4, "12": 4}}, f)
_done.clear()
_stale_matches = [(11, 0.9), (12, 0.85)]
ask_stale_yes, _ = make_ask(True)
pt.ensure_judged(
    _stale_mw, "lec_stale", _stale_matches,
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_stale_yes,
)
check("a first judged pass mints real entries — 11 pertinent, 12 rejected",
      _done == [{12}] and set(pt.load_judged(_root, "lec_stale")["verdicts"]) == {"11", "12"},
      repr(_done))

# Card 11 moves; card 12's own entry is untouched and still FRESH.
_stale_fields[11] = ["Q: stale mechanism of X, rewritten?", "A: Y, still"]
_done.clear()
_calls_before_skip_fresh = len(_client_calls)
ask_skip_fresh, ask_skip_fresh_log = make_ask(False)
pt.ensure_judged(
    _stale_mw, "lec_stale", _stale_matches,
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_skip_fresh,
)
check("Skip with only card 11 stale: no client call, and the prompt really appeared "
      "(so this is the Skip path, not the nothing-to-do shortcut)",
      len(_client_calls) == _calls_before_skip_fresh and len(ask_skip_fresh_log) == 1)
check("...a FRESH negative verdict is still reported — retirement must not wipe "
      "verdicts that still describe the card and page in front of it",
      _done == [{12}], repr(_done))
_after_fresh_skip = pt.load_judged(_root, "lec_stale")
check("...and the STALE entry (11) is gone from judged.json, retired on detection "
      "rather than left to be re-reported forever",
      set(_after_fresh_skip["verdicts"]) == {"12"}, repr(set(_after_fresh_skip["verdicts"])))

# Now card 12 moves too: its NEGATIVE verdict is stale, so nothing may be
# reported and nothing may stay on disk.
_stale_fields[12] = ["Q: stale Z, rewritten?", "A: W, still"]
_done.clear()
_calls_before_skip_stale = len(_client_calls)
ask_skip_stale, ask_skip_stale_log = make_ask(False)
pt.ensure_judged(
    _stale_mw, "lec_stale", _stale_matches,
    on_done=_done.append, on_error=_errors.append, cancel=None,
    on_progress=lambda *a: None, ask=ask_skip_stale,
)
check("Skip with the REJECTION itself stale: no client call, prompt shown",
      len(_client_calls) == _calls_before_skip_stale and len(ask_skip_stale_log) == 1)
check("...on_done reports an EMPTY set — the card is unjudged now, and D4 counts "
      "an unjudged card as confirmed, not Doubtful",
      _done == [set()], repr(_done))
check("...and the obsolete rejection is off disk, so retention and "
      "tag_sync.doubtful_members cannot keep tagging it either",
      pt.load_judged(_root, "lec_stale")["verdicts"] == {},
      repr(pt.load_judged(_root, "lec_stale")["verdicts"]))
check("no on_error fired across the retirement section", _errors == [])

section("module hygiene")
check("the module docstring no longer claims a divider that was never drawn (fix round 1, Finding 8)",
      "above the divider" not in (pt.__doc__ or ""))
raise SystemExit(report())
