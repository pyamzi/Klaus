"""Is this card truly about this lecture page? Claude decides (spec D4).

Cosine matching shortlists; this phase judges each candidate card against
the ONE page it matched best, in batches of BATCH per request, through a
strict forced tool so the answer is always well-formed or absent — a card
the model did not answer for is UNJUDGED (counted, tagged as matched),
never doubtful. Verdicts persist in judged.json beside matches.json and go
stale when the card's text, the page's text, or the model changes.

The module is aqt-free throughout (Task 3 adds the glue below a divider
it will draw).
"""
from __future__ import annotations

import json
import os
from typing import Any, NamedTuple

BATCH = 8
MAX_TOKENS = 2048
MAX_CARD_CHARS = 4000
MAX_PAGE_CHARS = 12000
JUDGED_FILE = "judged.json"
VERSION = 1

SYSTEM = (
    "You judge whether flashcards are pertinent to ONE lecture slide. For each card, "
    "answer pertinent=true only if studying that card would be reasonable preparation "
    "for the content of THIS slide — the specific facts, mechanisms or terms on it — "
    "not merely the same subject or organ system. Use the lecture title only as context. "
    "Give a one-sentence reason. Never guess: judge only the cards given, by their nid."
)


class CardText(NamedTuple):
    nid: int
    text: str
    text_hash: str


class PageText(NamedTuple):
    page: int
    page_hash: str
    text: str


class Verdict(NamedTuple):
    nid: int
    pertinent: bool
    reason: str
    page: int
    page_hash: str
    card_hash: str
    model: str


TOOL: dict[str, Any] = {
    "name": "record_verdicts",
    "description": "Record one verdict per card given.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nid": {"type": "integer"},
                        "pertinent": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["nid", "pertinent", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["verdicts"],
        "additionalProperties": False,
    },
}


def build_request(cards: list[CardText], page: PageText, lecture_display: str, model: str) -> dict:
    cards_json = json.dumps([{"nid": c.nid, "card": c.text[:MAX_CARD_CHARS]} for c in cards], ensure_ascii=False)
    page_text = page.text[:MAX_PAGE_CHARS]
    user = (
        f"Lecture: {lecture_display}\nSlide {page.page}:\n<<<\n{page_text}\n>>>\n\n"
        f"CARDS_JSON={cards_json}\n\nRecord a verdict for every card above."
    )
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "record_verdicts"},
        "messages": [{"role": "user", "content": user}],
    }


def parse_verdicts(response: dict, cards: list[CardText], page: PageText, model: str) -> list[Verdict]:
    """Never raises: a malformed shape anywhere in the turn returns ``[]``
    rather than guessing (fix round 1, Finding 1) — a non-dict ``response``,
    a non-list ``content``, a non-dict content block, and a non-dict tool
    ``input`` all read as "nothing to parse", the same as a well-formed
    turn with no verdicts in it.

    A duplicate ``nid`` inside one tool call keeps only the FIRST verdict;
    later ones for the same card are dropped (fix round 1, Finding 5) —
    ``strict: true`` cannot forbid array duplicates, so the model can
    legally send one; this module resolves it instead of leaving the
    choice to whichever writer reads ``judged.json`` next.
    """
    by_nid = {c.nid: c for c in cards}
    out: list[Verdict] = []
    blocks = response.get("content") if isinstance(response, dict) else None
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "record_verdicts":
            continue
        inp = block.get("input")
        if not isinstance(inp, dict):
            return []
        items = inp.get("verdicts")
        if not isinstance(items, list):
            return []
        for it in items:
            if not isinstance(it, dict):
                return []
            nid, pert, reason = it.get("nid"), it.get("pertinent"), it.get("reason")
            if not isinstance(nid, int) or isinstance(nid, bool) or not isinstance(pert, bool) or not isinstance(reason, str):
                return []
            c = by_nid.get(nid)
            if c is None or any(v.nid == nid for v in out):
                continue
            out.append(Verdict(nid, pert, reason.strip(), page.page, page.page_hash, c.text_hash, model))
    return out


def judge(client: Any, model: str, cards: list[CardText], page: PageText, lecture_display: str) -> list[Verdict]:
    """A batch that fails leaves only ITS cards unjudged (fix round 1,
    Finding 2) — one failed `client.complete` must not take an
    already-paid-for earlier batch's verdicts down with it, and the job
    still finishes and tags whatever it did manage to judge. The log line
    names the exception's class (and status, if it carries one) only —
    never the request payload, which holds card and lecture-page text.
    """
    out: list[Verdict] = []
    for i in range(0, len(cards), BATCH):
        batch = cards[i:i + BATCH]
        try:
            resp = client.complete(build_request(batch, page, lecture_display, model), purpose="judge")
        except Exception as exc:  # noqa: BLE001 — one batch, not the job
            status = getattr(exc, "status", None)
            detail = f"{type(exc).__name__}" + (f" status={status}" if status is not None else "")
            print(f"[klausmate] pertinence: batch of {len(batch)} left unjudged ({detail})")
            continue
        out.extend(parse_verdicts(resp, batch, page, model))
    return out


def judged_path(user_files: str, safe: str) -> str:
    return os.path.join(user_files, "pdf_index", safe, JUDGED_FILE)


def _empty() -> dict:
    return {"version": VERSION, "model": "", "verdicts": {}}


def load_judged(user_files: str, safe: str) -> dict:
    p = judged_path(user_files, safe)
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        if not isinstance(j, dict) or j.get("version") != VERSION or not isinstance(j.get("verdicts"), dict):
            raise ValueError("not a judged store")
        return j
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as exc:
        print(f"[klausmate] judged.json unreadable, treating as empty: {p}: {exc}")
        return _empty()


def save_judged(user_files: str, safe: str, judged: dict) -> None:
    p = judged_path(user_files, safe)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def is_stale(entry: dict, card_hash: str, page_hash: str, model: str) -> bool:
    """An entry with no ``"model"`` key is stale, never vacuously fresh
    (fix round 1, Finding 4) — the old ``entry.get("model", model)``
    default compared the argument to itself, so a model-less entry
    matched whatever model it was asked about. Callers should build
    entries with `entry_for` so this case cannot arise in practice.
    """
    return not (entry.get("card_hash") == card_hash and entry.get("page_hash") == page_hash and entry.get("model") == model)


def entry_for(v: Verdict) -> dict:
    """The one shape a `judged.json` entry is minted in — so a writer
    (Task 3) cannot forget `"model"` and silently make `is_stale`'s model
    check inert (fix round 1, Finding 4)."""
    return {
        "pertinent": v.pertinent,
        "reason": v.reason,
        "page": v.page,
        "page_hash": v.page_hash,
        "card_hash": v.card_hash,
        "model": v.model,
    }


def rejected_nids(judged: dict) -> set[int]:
    out: set[int] = set()
    for k, e in (judged.get("verdicts") or {}).items():
        try:
            if isinstance(e, dict) and e.get("pertinent") is False:
                out.add(int(k))
        except (TypeError, ValueError):
            continue
    return out


def all_rejected(user_files: str) -> set[int]:
    base = os.path.join(user_files, "pdf_index")
    out: set[int] = set()
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for safe in names:
        if os.path.isfile(judged_path(user_files, safe)):
            out |= rejected_nids(load_judged(user_files, safe))
    return out


def candidates(matches: list[tuple[int, float]], threshold: float) -> list[int]:
    return [nid for nid, score in sorted(matches, key=lambda m: -m[1]) if score >= threshold]
