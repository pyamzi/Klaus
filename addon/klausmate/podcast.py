"""Turn a lecture into a two-host podcast script, and cost it before voicing.

The script half, deliberately alone. Audio on a bad script is an expensive
bad script, and the cost of voicing a real lecture cannot be answered until
a real script exists to measure — so this produces one, reports how long it
would run and what it would cost to speak, and stops there.

TTS itself cannot happen in the add-on: Anki ships bytecode-only Python 3.13
with no pip, and every TTS library is native code that cannot be vendored.
Audio has to be produced outside and downloaded. Playback is fine — Anki
bundles mpv and exposes ``AVPlayer.play_file`` with pause and seek.

**Grounding is card_forge's, deliberately shared rather than copied.** The
failure mode is the one Pouya named about cards: a fluent invention the
listener cannot tell from the material, and a podcast is worse than a card
here because nothing is on screen to check it against. Lines cite the slides
they came from, ``cited_pages`` refuses any that stray outside the
selection, and coverage reports which slides the script never mentioned —
a "podcast on this lecture" that quietly skips half of it is not one.

aqt-free, no network, no audio: everything here is text and arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .card_forge import ForgeError, cited_pages, loads_response

# Two voices, fixed. The format only works because the listener can tell who
# is speaking; a third voice buys nothing and costs a distinguishable timbre.
HOST = "Host"
EXPERT = "Expert"
SPEAKERS = (HOST, EXPERT)

# Conversational speech runs about 150 words a minute. Used to turn a script
# into a duration BEFORE paying to voice it — an estimate, not a promise, and
# the number people quote for audiobooks and podcasts alike.
WORDS_PER_MINUTE = 150.0

# Words per minute of target, at that rate. The prompt gets a word budget
# rather than a minute count because a model can count words and cannot
# count time.
DEFAULT_MINUTES = 8
MAX_MINUTES = 30

# A stretch of one voice this long stops being a dialogue and becomes a
# lecture with an audience, which is the failure mode of the format.
MAX_CONSECUTIVE_LINES = 4


@dataclass
class Line:
    """One spoken turn."""

    speaker: str
    text: str
    pages: tuple = ()

    def __post_init__(self) -> None:
        self.speaker = str(self.speaker or "").strip().title()
        self.text = " ".join(str(self.text or "").split())
        if self.speaker not in SPEAKERS:
            raise ForgeError(
                f"unknown speaker {self.speaker!r}; expected one of {SPEAKERS}"
            )
        if not self.text:
            raise ForgeError("a spoken line cannot be empty")
        self.pages = tuple(sorted({int(p) for p in self.pages}))

    @property
    def words(self) -> int:
        return len(self.text.split())


def build_request(
    pages: dict,
    title: str = "",
    objectives: str = "",
    target_minutes: int = DEFAULT_MINUTES,
) -> dict:
    """The payload for one script generation.

    Carries ONLY the selected slides, for the same reason card_forge does:
    "cite only these slides" is unenforceable if the whole document is in
    the context to cite from.
    """
    if not pages:
        raise ForgeError("no slides selected")
    numbers = sorted(int(p) for p in pages)
    minutes = max(1, min(int(target_minutes or DEFAULT_MINUTES), MAX_MINUTES))
    return {
        "pages": {int(p): str(pages[p] or "") for p in numbers},
        "allowed_pages": numbers,
        "title": str(title or "").strip(),
        "objectives": str(objectives or "").strip(),
        "target_minutes": minutes,
        "word_budget": int(minutes * WORDS_PER_MINUTE),
    }


def instructions(request: dict) -> str:
    """The rules, kept beside the parser that enforces them."""
    lines = [
        f"Write a two-host podcast script about {request['title'] or 'this lecture'}.",
        "",
        f"- Exactly two speakers: {HOST} asks and steers, {EXPERT} explains.",
        f"- Aim for about {request['word_budget']} words "
        f"(~{request['target_minutes']} minutes of speech).",
        "- Every line cites the slide numbers it draws on, in `pages`.",
        f"- Cite ONLY these slides: {request['allowed_pages']}. Never cite a "
        "slide that is not listed, and never state a fact the slides do not "
        "support. A listener has nothing on screen to check you against.",
        "- Cover the material rather than dwelling on the first few slides.",
        f"- Alternate. No speaker gets more than {MAX_CONSECUTIVE_LINES} "
        "turns in a row; a monologue is not a conversation.",
        "- Speech, not prose: contractions, short sentences, no headings, no "
        "bullet points, no stage directions.",
        "- Answer with JSON only: "
        '{"lines": [{"speaker": "Host", "text": ..., "pages": [...]}]}',
    ]
    if request["objectives"]:
        lines += ["", "Serve these learning objectives:", request["objectives"]]
    return "\n".join(lines)


def parse_script(raw: str, request: dict) -> tuple:
    """``(lines, rejections)`` from a model response.

    Rejections are returned rather than dropped, same as card_forge: a model
    that keeps citing slides nobody selected is a prompt problem, and a
    script that silently lost a third of its lines is a mystery.
    """
    data = loads_response(raw)
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list):
        raise ForgeError("response has no `lines` list")
    allowed = set(int(p) for p in request.get("allowed_pages") or ())
    out: list = []
    rejections: list = []
    for i, item in enumerate(raw_lines):
        if not isinstance(item, dict):
            rejections.append((i, "not an object"))
            continue
        pages, why = cited_pages(item, allowed)
        if why:
            rejections.append((i, why))
            continue
        try:
            out.append(
                Line(
                    speaker=item.get("speaker", ""),
                    text=item.get("text", ""),
                    pages=pages,
                )
            )
        except ForgeError as exc:
            rejections.append((i, str(exc)))
    return out, rejections


# ── Measuring, before anything is voiced ─────────────────────────────────


def word_count(lines: list) -> int:
    return sum(line.words for line in lines)


def tts_characters(lines: list) -> int:
    """Characters a TTS provider would bill for. Speaker names are not
    spoken and are not counted."""
    return sum(len(line.text) for line in lines)


def duration_minutes(lines: list, wpm: float = WORDS_PER_MINUTE) -> float:
    """Estimated spoken length. Rounded to a tenth — presenting this to two
    decimal places would imply a precision the estimate does not have."""
    if wpm <= 0:
        raise ForgeError("words per minute must be positive")
    return round(word_count(lines) / float(wpm), 1)


def cost_estimate(lines: list, usd_per_million_chars: float) -> float:
    """What voicing this would cost at a rate the CALLER supplies.

    No default rate on purpose. TTS prices change, differ per provider and
    per voice tier, and a number baked in here would be quietly wrong long
    before anybody noticed — which is exactly the wrong way to be wrong
    about money.
    """
    rate = float(usd_per_million_chars)
    if rate < 0:
        raise ForgeError("rate cannot be negative")
    return round(tts_characters(lines) * rate / 1_000_000.0, 4)


def coverage(lines: list, request: dict) -> dict:
    """Which selected slides the script actually used.

    A podcast "on this lecture" that never mentions half of it is not one,
    and this is the only way to notice before listening to the whole thing.
    """
    allowed = [int(p) for p in request.get("allowed_pages") or ()]
    used = {p for line in lines for p in line.pages}
    missed = [p for p in allowed if p not in used]
    return {
        "slides": len(allowed),
        "covered": len(allowed) - len(missed),
        "missed": missed,
        "fraction": round(
            (len(allowed) - len(missed)) / len(allowed), 3
        ) if allowed else 0.0,
    }


def longest_monologue(lines: list) -> int:
    """The longest run of consecutive turns by one speaker."""
    best = run = 0
    previous = None
    for line in lines:
        run = run + 1 if line.speaker == previous else 1
        previous = line.speaker
        best = max(best, run)
    return best


def report(lines: list, request: dict, usd_per_million_chars: float = 0.0) -> dict:
    """Everything worth knowing before deciding to spend money on audio."""
    data = {
        "lines": len(lines),
        "words": word_count(lines),
        "characters": tts_characters(lines),
        "minutes": duration_minutes(lines),
        "target_minutes": request.get("target_minutes"),
        "longest_monologue": longest_monologue(lines),
        "speakers": sorted({line.speaker for line in lines}),
        "coverage": coverage(lines, request),
    }
    if usd_per_million_chars:
        data["usd"] = cost_estimate(lines, usd_per_million_chars)
    return data


def to_tts_turns(lines: list) -> list:
    """``[(speaker, text)]`` for whatever ends up doing the voicing.

    Deliberately not merged into one blob per speaker: a TTS call per turn
    is what lets the two voices interleave, and merging would produce two
    monologues played back to back.
    """
    return [(line.speaker, line.text) for line in lines]


def transcript(lines: list) -> str:
    """The script as readable text — for the panel, and for a user who would
    rather read it than listen to it."""
    return "\n\n".join(f"{line.speaker}: {line.text}" for line in lines)
