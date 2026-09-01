"""Draft Anki cards from lecture material, and hold them for review.

The engine behind card creation. Deliberately import-free above the
"collection" divider — no aqt, no network, no LLM client — because the
surface for this is undecided, and everything worth testing lives here.

THE POINT IS NOT GENERATION. Generating plausible cards is easy and nearly
worthless: a pile of cards nobody trusts enough to study costs more than it
saves. Four rules do the actual work, and each is enforced here rather than
left to a prompt:

1. **Provenance is mandatory.** Every proposal names the pages it came from.
   A card with no source page cannot be constructed — see ``Proposal``.
2. **Cited pages must be real.** A card claiming page 40 when pages 3-5 were
   selected is a fabrication, not a card, and ``parse_proposals`` drops it.
   This is the one check that catches a model inventing its own sources.
3. **Duplicates are found before the user sees anything.** ``mark_duplicates``
   ranks each draft against the existing collection, so "you already have
   this" is shown rather than discovered three reviews later.
4. **Nothing reaches the collection without an explicit accept.**
   ``ReviewQueue.to_write`` returns accepted proposals and nothing else.

Anki-facing work — building notes, the undoable write — lives in the caller,
following the pattern in ``curation.py``: ``add_custom_undo_entry`` →
``col.add_notes`` → ``merge_undo_entries``.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

# States a proposal can be in. Editing does NOT change the state: an edited
# card is still awaiting a decision, it is just no longer the model's words.
PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"

# Cosine similarity above which a draft is called a duplicate of an existing
# note. Deliberately high: these are unit vectors from the same embedding
# space, and a false "you already have this" hides a card the user wanted,
# which is worse than showing one near-miss they can reject in a keystroke.
DUPLICATE_THRESHOLD = 0.92

# How many cards to ask for per slide, absent an explicit cap. Low on
# purpose. Asking a model for "as many as possible" is the single most
# reliable way to get padding, and padding is what makes a deck untrustworthy.
CARDS_PER_PAGE = 2
MAX_CARDS = 40


class ForgeError(Exception):
    """A draft could not be turned into a reviewable proposal."""


@dataclass
class Proposal:
    """One card awaiting review.

    ``pages`` is required and validated in ``__post_init__`` — a card whose
    source cannot be named is not reviewable, and an unreviewable card is the
    thing this module exists to prevent.
    """

    front: str
    back: str
    pages: tuple[int, ...]
    objective: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = PENDING
    edited: bool = False
    # Set by mark_duplicates: the nid this looks like, and how strongly.
    duplicate_of: int | None = None
    duplicate_score: float = 0.0
    # True when the text changed after a duplicate verdict was computed, so
    # the verdict describes words that no longer exist. Callers re-embed and
    # re-check rather than trusting it.
    stale_duplicate: bool = False

    def __post_init__(self) -> None:
        self.front = str(self.front or "").strip()
        self.back = str(self.back or "").strip()
        if not self.front or not self.back:
            raise ForgeError("a card needs both a front and a back")
        try:
            self.pages = tuple(sorted({int(p) for p in self.pages}))
        except (TypeError, ValueError):
            raise ForgeError("pages must be integers") from None
        if not self.pages:
            raise ForgeError(
                "a card must name the page it came from — an unsourced card "
                "cannot be audited, which is the whole point of the review"
            )
        if any(p < 0 for p in self.pages):
            raise ForgeError("page numbers are 0-based and cannot be negative")

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None and not self.stale_duplicate


# ── Request ──────────────────────────────────────────────────────────────


def build_request(
    pages: dict,
    objectives: str = "",
    deck: str = "",
    max_cards: int = 0,
) -> dict:
    """The payload for one generation call.

    ``pages`` maps 0-based page number → that page's text, and is the ONLY
    source material sent. Sending the whole PDF and hoping the model restricts
    itself to the selection is how cards end up citing pages nobody chose.

    The cap scales with the material rather than being a fixed number: a
    three-slide selection that comes back with thirty cards has padded.
    """
    if not pages:
        raise ForgeError("no pages selected")
    numbers = sorted(int(p) for p in pages)
    cap = int(max_cards) if max_cards else min(
        MAX_CARDS, max(1, len(numbers) * CARDS_PER_PAGE)
    )
    return {
        "pages": {int(p): str(pages[p] or "") for p in numbers},
        "allowed_pages": numbers,
        "objectives": str(objectives or "").strip(),
        "deck": str(deck or "").strip(),
        "max_cards": cap,
    }


def instructions(request: dict) -> str:
    """The rules the model is asked to follow.

    Kept beside the parser that enforces them, so a rule can never be relaxed
    in the prompt while the parser still rejects on it (or the reverse).
    """
    lines = [
        "Write Anki cards from the numbered slides supplied.",
        "",
        "Rules:",
        "- One fact per card. A card testing two things teaches neither.",
        "- Every card cites the slide numbers it came from, in `pages`.",
        f"- Cite ONLY these slides: {request['allowed_pages']}. Never cite a "
        "slide that is not listed, and never invent material that is not on "
        "the slides supplied.",
        "- If a slide does not support a worthwhile card, skip it. Returning "
        "fewer good cards is correct; padding to a target is not.",
        f"- At most {request['max_cards']} cards.",
        "- Answer with JSON only: "
        '{"cards": [{"front": ..., "back": ..., "pages": [...], '
        '"objective": ...}]}',
    ]
    if request["objectives"]:
        lines += [
            "",
            "Every card must serve one of these learning objectives, named "
            "in `objective`. An objective with no supporting slide gets no "
            "card — say so rather than inventing one:",
            request["objectives"],
        ]
    return "\n".join(lines)


# ── Parsing ──────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def loads_response(raw: str) -> dict:
    """Parse a model response that may be wrapped in a code fence.

    Public because podcast.py needs the identical treatment: both ask a
    model for JSON grounded in slides, and a second copy of fence-stripping
    is a second thing to drift.
    """
    text = _FENCE_RE.sub("", str(raw or "")).strip()
    if not text:
        raise ForgeError("empty response")
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise ForgeError("response was not JSON") from None
    if not isinstance(data, dict):
        raise ForgeError("response was not a JSON object")
    return data


def cited_pages(item: dict, allowed: set) -> tuple:
    """``(pages, error)`` for one model-authored item.

    THE hallucination guard, shared by every generator that works from
    slides. An item citing a slide outside the selection was not written
    from the material supplied, whatever else it is — and since the request
    only ever carries the selected slides, that is a fabrication rather
    than a lookup.

    Returns an empty tuple and a reason on failure; never raises, because
    one bad item should cost that item and not the batch.
    """
    pages = item.get("pages")
    if isinstance(pages, (int, float, str)):
        pages = [pages]
    try:
        cited = {int(p) for p in (pages or ())}
    except (TypeError, ValueError):
        return (), "pages were not numbers"
    stray = sorted(cited - set(allowed))
    if stray:
        return (), f"cites unselected slides {stray}"
    return tuple(sorted(cited)), ""


def parse_proposals(raw: str, request: dict) -> tuple[list, list]:
    """``(proposals, rejections)`` from a model response.

    Rejections are kept rather than silently dropped: a model that keeps
    citing slides nobody selected is a prompt problem, and swallowing that
    evidence is how it goes unnoticed for weeks.
    """
    data = loads_response(raw)
    cards = data.get("cards")
    if not isinstance(cards, list):
        raise ForgeError("response has no `cards` list")
    allowed = set(int(p) for p in request.get("allowed_pages") or ())
    proposals: list = []
    rejections: list = []
    for i, card in enumerate(cards):
        if not isinstance(card, dict):
            rejections.append((i, "not an object"))
            continue
        cited, why = cited_pages(card, allowed)
        if why:
            rejections.append((i, why))
            continue
        try:
            proposals.append(
                Proposal(
                    front=card.get("front", ""),
                    back=card.get("back", ""),
                    pages=tuple(cited),
                    objective=str(card.get("objective") or "").strip(),
                )
            )
        except ForgeError as exc:
            rejections.append((i, str(exc)))
    return proposals, rejections


# ── Duplicate detection ──────────────────────────────────────────────────


def dedup_text(proposal) -> str:
    """What gets embedded when checking a draft against the collection.

    Both sides of the card: a front that matches an existing note but answers
    something else is not a duplicate, and front-only matching calls it one.
    """
    return f"{proposal.front}\n{proposal.back}"


def mark_duplicates(
    proposals: list,
    vectors: list,
    index,
    threshold: float = DUPLICATE_THRESHOLD,
    ranker=None,
) -> int:
    """Flag proposals that already exist in the collection. Returns the count.

    One query per proposal on purpose: ``card_index.top_k`` scores the max
    over ALL query vectors it is given, so passing the whole batch answers
    "does anything here match?" rather than "which of these matches?".

    ``ranker`` is injectable so this is testable without building a real
    index; it defaults to card_index.top_k.
    """
    if len(proposals) != len(vectors):
        raise ForgeError("one vector per proposal is required")
    if ranker is None:
        from . import card_index

        ranker = card_index.top_k
    found = 0
    for proposal, vec in zip(proposals, vectors):
        proposal.duplicate_of = None
        proposal.duplicate_score = 0.0
        proposal.stale_duplicate = False
        if vec is None:
            continue
        hits = ranker(index, [vec], 1, None, threshold)
        if hits:
            nid, score = hits[0]
            proposal.duplicate_of = int(nid)
            proposal.duplicate_score = float(score)
            found += 1
    return found


# ── Review ───────────────────────────────────────────────────────────────


class ReviewQueue:
    """Proposals plus their decisions.

    The queue is the product. A batch is never applied wholesale: every card
    leaves here only because somebody accepted that card.
    """

    def __init__(self, proposals: list | None = None) -> None:
        self._items: list = list(proposals or [])

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list:
        return list(self._items)

    def get(self, proposal_id: str):
        for item in self._items:
            if item.id == proposal_id:
                return item
        raise ForgeError(f"no such proposal: {proposal_id}")

    def accept(self, proposal_id: str) -> None:
        self.get(proposal_id).state = ACCEPTED

    def reject(self, proposal_id: str) -> None:
        self.get(proposal_id).state = REJECTED

    def edit(self, proposal_id: str, front: str = None, back: str = None) -> None:
        """Change a card's text, keeping it PENDING.

        An edit invalidates any duplicate verdict — that verdict describes
        words that no longer exist — so it is marked stale rather than left
        to mislead. Editing does not imply accepting: the decision is still
        the user's to make, separately.
        """
        item = self.get(proposal_id)
        new_front = item.front if front is None else str(front).strip()
        new_back = item.back if back is None else str(back).strip()
        if not new_front or not new_back:
            raise ForgeError("a card needs both a front and a back")
        if (new_front, new_back) != (item.front, item.back):
            item.front, item.back = new_front, new_back
            item.edited = True
            if item.duplicate_of is not None:
                item.stale_duplicate = True
        item.state = PENDING

    def replace(self, proposal_id: str, proposal) -> None:
        """Swap in a regenerated card, keeping its place in the queue."""
        for i, item in enumerate(self._items):
            if item.id == proposal_id:
                proposal.id = proposal_id
                self._items[i] = proposal
                return
        raise ForgeError(f"no such proposal: {proposal_id}")

    def pending(self) -> list:
        return [i for i in self._items if i.state == PENDING]

    def to_write(self) -> list:
        """The accepted cards, and only those.

        The single gate between a generated card and the collection.
        """
        return [i for i in self._items if i.state == ACCEPTED]

    def summary(self) -> dict:
        return {
            "total": len(self._items),
            "accepted": len(self.to_write()),
            "rejected": len([i for i in self._items if i.state == REJECTED]),
            "pending": len(self.pending()),
            "duplicates": len([i for i in self._items if i.is_duplicate]),
            "edited": len([i for i in self._items if i.edited]),
        }
