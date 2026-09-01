"""Tests for card_forge — the card-drafting engine.

card_forge is import-free by design (no aqt, no network, no LLM client), so
unlike most of this addon almost all of it is genuinely testable here rather
than only by launching Anki.

What these pin is not "does it generate cards" — that is a prompt-quality
question no unit test can answer. It is the four guarantees that make a
generated card reviewable at all: it names its source, that source is real,
duplicates are found before the user sees them, and nothing reaches the
collection without somebody accepting it.
"""
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

cf = importlib.import_module("klausmate.card_forge")

PAGES = {3: "Incidence is new cases over person-time.",
         4: "Prevalence is existing cases at a point in time."}
REQ = cf.build_request(PAGES, objectives="Distinguish incidence from prevalence.")


def _p(front="Front", back="Back", pages=(3,), **kw):
    return cf.Proposal(front=front, back=back, pages=pages, **kw)


section("provenance is mandatory, not encouraged")
try:
    cf.Proposal(front="F", back="B", pages=())
    check("a card with no source page cannot be built", False)
except cf.ForgeError:
    check("a card with no source page cannot be built — an unsourced card "
          "cannot be audited, which is the whole point of the review", True)
try:
    cf.Proposal(front="", back="B", pages=(3,))
    check("a card with no front is refused", False)
except cf.ForgeError:
    check("a card with no front is refused", True)
try:
    cf.Proposal(front="F", back="B", pages=(-1,))
    check("negative page numbers are refused", False)
except cf.ForgeError:
    check("negative page numbers are refused", True)
check("pages are deduplicated and sorted, so provenance has one spelling",
      _p(pages=(4, 3, 3)).pages == (3, 4))

section("the request only ever carries the selected slides")
check("allowed pages are exactly the selection", REQ["allowed_pages"] == [3, 4])
check("only the selected slides' text is sent — shipping the whole PDF and "
      "hoping the model restricts itself is how cards cite slides nobody "
      "chose", set(REQ["pages"]) == {3, 4})
check("the cap scales with the material rather than being a fixed number",
      REQ["max_cards"] == 2 * cf.CARDS_PER_PAGE)
check("a big selection is still capped", cf.build_request(
    {i: "x" for i in range(500)})["max_cards"] == cf.MAX_CARDS)
check("an explicit cap wins",
      cf.build_request(PAGES, max_cards=3)["max_cards"] == 3)
try:
    cf.build_request({})
    check("an empty selection is refused", False)
except cf.ForgeError:
    check("an empty selection is refused", True)
check("objectives reach the instructions when given",
      "Distinguish incidence" in cf.instructions(REQ))
check("the instructions name the allowed slides, so the rule the parser "
      "enforces is the rule the model is given",
      "[3, 4]" in cf.instructions(REQ))

section("cited slides must be real — the hallucination guard")
_raw = ('{"cards": ['
        '{"front":"What is incidence?","back":"New cases per person-time.","pages":[3]},'
        '{"front":"Invented","back":"From a slide nobody selected","pages":[40]},'
        '{"front":"Half","back":"","pages":[3]},'
        '{"front":"Bad pages","back":"B","pages":["x"]},'
        '"not an object"'
        ']}')
_props, _rej = cf.parse_proposals(_raw, REQ)
check("the good card survives", len(_props) == 1)
check("a card citing an unselected slide is dropped — it was not written "
      "from the material supplied, whatever else it is",
      any("unselected slides [40]" in r[1] for r in _rej))
check("a half-written card is dropped", any("front and a back" in r[1] for r in _rej))
check("unparseable pages are dropped", any("not numbers" in r[1] for r in _rej))
check("a non-object entry is dropped", any("not an object" in r[1] for r in _rej))
check("rejections are RETURNED, not swallowed — a model that keeps inventing "
      "sources is a prompt problem, and hiding the evidence is how that goes "
      "unnoticed", len(_rej) == 4)

section("responses arrive wrapped in whatever the model felt like")
check("a ```json fence is stripped",
      len(cf.parse_proposals(
          '```json\n{"cards":[{"front":"F","back":"B","pages":[3]}]}\n```',
          REQ)[0]) == 1)
check("a bare fence is stripped too",
      len(cf.parse_proposals(
          '```\n{"cards":[{"front":"F","back":"B","pages":[3]}]}\n```',
          REQ)[0]) == 1)
check("a single page number, not a list, is accepted",
      cf.parse_proposals(
          '{"cards":[{"front":"F","back":"B","pages":3}]}', REQ)[0][0].pages
      == (3,))
for _bad, _why in (("", "empty"), ("not json", "not JSON"),
                   ("[1,2]", "not an object"), ('{"nope":1}', "no cards list")):
    try:
        cf.parse_proposals(_bad, REQ)
        check(f"{_why} response raises", False)
    except cf.ForgeError:
        check(f"{_why} response raises rather than yielding silence", True)

section("duplicates are found before the user sees anything")
_a, _b = _p(front="What is incidence?"), _p(front="Something else entirely")


def _fake_ranker(index, vecs, k, allowed, min_score):
    """Stands in for card_index.top_k: only the first proposal matches."""
    return [(4242, 0.97)] if vecs[0] == "dup" else []


_n = cf.mark_duplicates([_a, _b], ["dup", "new"], None, ranker=_fake_ranker)
check("a duplicate is flagged with the note it duplicates",
      _n == 1 and _a.duplicate_of == 4242 and _a.is_duplicate)
check("...and carries the score, so a near-miss can be judged",
      _a.duplicate_score == 0.97)
check("a genuinely new card is not flagged",
      _b.duplicate_of is None and not _b.is_duplicate)
check("the threshold is high on purpose — a false 'you already have this' "
      "hides a card the user wanted", cf.DUPLICATE_THRESHOLD >= 0.9)
check("both sides of the card are embedded: a matching front that answers "
      "something else is not a duplicate",
      cf.dedup_text(_p(front="F", back="B")) == "F\nB")
try:
    cf.mark_duplicates([_a], [], None, ranker=_fake_ranker)
    check("a vector per proposal is required", False)
except cf.ForgeError:
    check("a vector per proposal is required", True)
_c = _p()
_c.duplicate_of = 1
cf.mark_duplicates([_c], [None], None, ranker=_fake_ranker)
check("a proposal that could not be embedded is cleared, never left "
      "carrying a stale verdict", _c.duplicate_of is None)

section("nothing reaches the collection without an accept")
_q = cf.ReviewQueue([_p(front="one"), _p(front="two"), _p(front="three")])
check("a fresh queue writes nothing at all", _q.to_write() == [])
_q.accept(_q.items[0].id)
_q.reject(_q.items[1].id)
check("only the accepted card is written", [i.front for i in _q.to_write()] == ["one"])
check("a rejected card is not written", "two" not in [i.front for i in _q.to_write()])
check("an untouched card is not written either — silence is not consent",
      "three" not in [i.front for i in _q.to_write()])
check("the summary accounts for every card",
      _q.summary()["total"] == 3 and _q.summary()["accepted"] == 1
      and _q.summary()["rejected"] == 1 and _q.summary()["pending"] == 1)
try:
    _q.get("nope")
    check("an unknown id raises", False)
except cf.ForgeError:
    check("an unknown id raises rather than silently doing nothing", True)

section("editing keeps the decision with the user")
_e = _p(front="orig", back="orig back")
_e.duplicate_of, _e.duplicate_score = 99, 0.95
_q2 = cf.ReviewQueue([_e])
_q2.edit(_e.id, back="rewritten")
check("an edit is recorded", _e.edited and _e.back == "rewritten")
check("an edited card stays PENDING — editing is not accepting",
      _e.state == cf.PENDING and _q2.to_write() == [])
check("the duplicate verdict is marked stale, because it describes words "
      "that no longer exist", _e.stale_duplicate and not _e.is_duplicate)
check("...but the raw verdict is kept for a re-check rather than erased",
      _e.duplicate_of == 99)
_q2.edit(_e.id, back="rewritten")
check("a no-op edit does not re-flag anything", _e.back == "rewritten")
try:
    _q2.edit(_e.id, front="")
    check("an edit cannot empty a card", False)
except cf.ForgeError:
    check("an edit cannot empty a card", True)
_q2.accept(_e.id)
check("an accepted card that was edited still writes", len(_q2.to_write()) == 1)

section("regeneration replaces in place")
_q3 = cf.ReviewQueue([_p(front="a"), _p(front="b")])
_target = _q3.items[0].id
_q3.replace(_target, _p(front="regenerated"))
check("the card is swapped", _q3.items[0].front == "regenerated")
check("it keeps its place in the queue", len(_q3) == 2 and _q3.items[1].front == "b")
check("and keeps its id, so a surface holding a reference still resolves it",
      _q3.items[0].id == _target and _q3.get(_target).front == "regenerated")
check("a regenerated card is PENDING — regenerating is not accepting",
      _q3.to_write() == [])

section("the engine stays free of the host")
_SRC = open("klausmate/card_forge.py").read()
_CODE = code_only(_SRC)
check("no aqt import at module level — the UI surface is undecided and this "
      "must not presuppose one",
      "import aqt" not in _CODE and "from aqt" not in _CODE)
check("no network client here", "urllib" not in _CODE and "requests" not in _CODE)
check("card_index is imported lazily, inside the one function that needs it",
      "from . import card_index" in _CODE
      and _CODE.index("def mark_duplicates") < _CODE.index("from . import card_index"))

raise SystemExit(report())
