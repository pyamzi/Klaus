"""Tests for podcast — the script half of the audio feature.

No audio anywhere near this: the module is text and arithmetic, so all of it
runs here. What these pin is the part that decides whether spending money on
TTS is worth it — grounding, coverage, and an honest measurement of how long
the thing would run.
"""
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section

install()
import importlib

pod = importlib.import_module("klausmate.podcast")
cf = importlib.import_module("klausmate.card_forge")

PAGES = {1: "Incidence is new cases over person-time.",
         2: "Prevalence is existing cases at a point.",
         3: "Incidence drives risk; prevalence drives burden."}
REQ = pod.build_request(PAGES, title="Measures of Disease Frequency")


def _line(speaker="Host", text="So what is incidence?", pages=(1,)):
    return pod.Line(speaker=speaker, text=text, pages=pages)


section("a spoken line is a real line or it is not built")
check("speakers are normalised", _line(speaker="host").speaker == "Host")
check("whitespace is collapsed — it becomes speech, and a stray newline is "
      "a pause nobody asked for",
      _line(text="a\n\n  b").text == "a b")
for _bad, _why in ((("Narrator", "x", (1,)), "an unknown speaker"),
                   ((("Host"), "   ", (1,)), "an empty line")):
    try:
        pod.Line(speaker=_bad[0], text=_bad[1], pages=_bad[2])
        check(f"{_why} is refused", False)
    except cf.ForgeError:
        check(f"{_why} is refused", True)
check("exactly two voices — a third buys nothing and costs a "
      "distinguishable timbre", len(pod.SPEAKERS) == 2)

section("the request is a word budget, not a minute count")
check("only the selected slides are carried", set(REQ["pages"]) == {1, 2, 3})
# Explicit values, not `== pod.WORDS_PER_MINUTE`: a pin that reads the
# constant it is testing moves with it and can never fail. Fifth time today.
check("conversational speech is 150 words a minute", pod.WORDS_PER_MINUTE == 150.0)
check("a model can count words and cannot count time — eight minutes is a "
      "budget of 1200 words", REQ["word_budget"] == 1200)
check("eight minutes is the default", REQ["target_minutes"] == 8)
check("a wild target is clamped to thirty minutes",
      pod.build_request(PAGES, target_minutes=999)["target_minutes"] == 30
      and pod.MAX_MINUTES == 30)
check("...and so is a zero one",
      pod.build_request(PAGES, target_minutes=0)["target_minutes"] >= 1)
try:
    pod.build_request({})
    check("no slides is refused", False)
except cf.ForgeError:
    check("no slides is refused", True)
_ins = pod.instructions(REQ)
check("the instructions name the allowed slides, so the rule the parser "
      "enforces is the rule the model is given", "[1, 2, 3]" in _ins)
check("...and the word budget", str(REQ["word_budget"]) in _ins)
check("...and forbid unsupported claims, because a listener has nothing on "
      "screen to check against", "slides do not" in _ins)

section("grounding is card_forge's, not a second copy")
_raw = ('{"lines": ['
        '{"speaker":"Host","text":"What is incidence?","pages":[1]},'
        '{"speaker":"Expert","text":"New cases over person-time.","pages":[1]},'
        '{"speaker":"Host","text":"Invented from slide 40","pages":[40]},'
        '{"speaker":"Narrator","text":"A third voice","pages":[1]},'
        '{"speaker":"Host","text":"","pages":[2]},'
        '"not an object"'
        ']}')
_lines, _rej = pod.parse_script(_raw, REQ)
check("the good lines survive", len(_lines) == 2)
check("a line citing an unselected slide is dropped",
      any("unselected slides [40]" in r[1] for r in _rej))
check("a third speaker is dropped", any("unknown speaker" in r[1] for r in _rej))
check("an empty line is dropped", any("cannot be empty" in r[1] for r in _rej))
check("a non-object is dropped", any("not an object" in r[1] for r in _rej))
check("rejections are returned, not swallowed", len(_rej) == 4)
check("a code fence is handled, because that is card_forge's parser",
      len(pod.parse_script(
          '```json\n{"lines":[{"speaker":"Host","text":"hi","pages":[1]}]}\n```',
          REQ)[0]) == 1)
check("the hallucination guard is the SHARED helper, so the two generators "
      "cannot drift apart",
      "cited_pages" in code_only(open("klausmate/podcast.py").read()))
for _bad, _why in (("", "empty"), ("not json", "not JSON"),
                   ('{"nope":1}', "no lines list")):
    try:
        pod.parse_script(_bad, REQ)
        check(f"a {_why} response raises", False)
    except cf.ForgeError:
        check(f"a {_why} response raises rather than yielding silence", True)

section("measuring, before anything is voiced")
_script = [
    _line("Host", "one two three four five", (1,)),
    _line("Expert", "six seven eight nine ten", (2,)),
]
check("words are counted", pod.word_count(_script) == 10)
check("characters are what a TTS provider bills for, and the speaker names "
      "are not spoken",
      pod.tts_characters(_script)
      == len("one two three four five") + len("six seven eight nine ten"))
check("ten words at 150wpm is about four seconds",
      pod.duration_minutes(_script) == 0.1)
check("a longer script scales",
      pod.duration_minutes([_line("Host", "word " * 300, (1,))]) == 2.0)
check("the estimate is rounded to a tenth — two decimals would imply a "
      "precision it does not have",
      pod.duration_minutes([_line("Host", "word " * 77, (1,))])
      == round(77 / 150.0, 1))
try:
    pod.duration_minutes(_script, wpm=0)
    check("a zero speaking rate is refused", False)
except cf.ForgeError:
    check("a zero speaking rate is refused rather than dividing by it", True)

section("cost is computed from a rate the caller supplies")
check("a thousand characters at $15/M is 1.5 cents",
      pod.cost_estimate([_line("Host", "x" * 1000, (1,))], 15.0) == 0.015)
check("a free rate costs nothing", pod.cost_estimate(_script, 0.0) == 0.0)
try:
    pod.cost_estimate(_script, -1)
    check("a negative rate is refused", False)
except cf.ForgeError:
    check("a negative rate is refused", True)
_SRC = open("klausmate/podcast.py").read()
check("NO default price is baked in — TTS rates change and differ per "
      "provider, and a stale number here would be quietly wrong about money",
      "usd_per_million_chars: float)" in _SRC
      and "usd_per_million_chars=15" not in _SRC)

section("coverage: a podcast that skips half the lecture is not one")
_partial = [_line("Host", "only about the first slide", (1,))]
_cov = pod.coverage(_partial, REQ)
check("uncovered slides are named, not just counted", _cov["missed"] == [2, 3])
check("...and counted", _cov["covered"] == 1 and _cov["slides"] == 3)
check("as a fraction, for a progress read", _cov["fraction"] == round(1 / 3, 3))
_full = [_line("Host", "a", (1, 2)), _line("Expert", "b", (3,))]
check("full coverage reports nothing missed",
      pod.coverage(_full, REQ)["missed"] == []
      and pod.coverage(_full, REQ)["fraction"] == 1.0)
check("an empty selection does not divide by zero",
      pod.coverage([], {"allowed_pages": []})["fraction"] == 0.0)

section("alternation: a monologue is not a conversation")
check("a run of one speaker is measured",
      pod.longest_monologue([_line("Host"), _line("Host"), _line("Expert")])
      == 2)
check("alternating is a run of one",
      pod.longest_monologue([_line("Host"), _line("Expert"), _line("Host")])
      == 1)
check("an empty script has no run", pod.longest_monologue([]) == 0)
check("four turns in a row is the limit, and the model is told it",
      pod.MAX_CONSECUTIVE_LINES == 4
      and "more than 4 " in pod.instructions(REQ))

section("the report is what the audio decision gets made on")
_r = pod.report(_full, REQ, usd_per_million_chars=15.0)
check("it carries length, cost and coverage together",
      {"minutes", "characters", "usd", "coverage"} <= set(_r))
check("it names both speakers", _r["speakers"] == ["Expert", "Host"])
check("it repeats the target, so a script half the requested length is "
      "visible without arithmetic", _r["target_minutes"] == 8)
check("cost is omitted when no rate is given", "usd" not in pod.report(_full, REQ))

section("handoff to whatever does the voicing")
_turns = pod.to_tts_turns(_full)
check("one turn per line — merging per speaker would produce two monologues "
      "played back to back", len(_turns) == 2)
check("each turn carries its voice", _turns[0][0] == "Host")
check("a readable transcript exists for someone who would rather read it",
      pod.transcript(_full).startswith("Host: a"))

section("shape")
_CODE = code_only(_SRC)
check("aqt-free", "import aqt" not in _CODE and "from aqt" not in _CODE)
check("no audio and no network here — this half is text and arithmetic",
      "urllib" not in _CODE and "mpv" not in _CODE and "wave" not in _CODE)
check("the grounding helpers are imported from card_forge, not reimplemented",
      "from .card_forge import" in _CODE)

raise SystemExit(report())
