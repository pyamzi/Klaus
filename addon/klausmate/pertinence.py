"""Is this card truly about this lecture page? Claude decides (spec D4).

Cosine matching shortlists; this phase judges each candidate card against
the ONE page it matched best, in batches of BATCH per request, through a
strict forced tool so the answer is always well-formed or absent — a card
the model did not answer for is UNJUDGED (counted, tagged as matched),
never doubtful. Verdicts persist in judged.json beside matches.json and go
stale when the card's text, the page's text, or the model changes.

The pure section stays aqt-free; Task 3 adds the aqt glue — ``ensure_judged``,
the index chain's fourth phase — below the divider it draws.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, NamedTuple

BATCH = 8
MAX_TOKENS = 2048
MAX_CARD_CHARS = 4000
MAX_PAGE_CHARS = 12000
JUDGED_FILE = "judged.json"
VERSION = 1

# A REFUSAL, not a hiccup (I-1): a rejected key, an exhausted Klaus Plus
# quota, a forbidden licence, an out-of-date client — every one of these
# answers the next batch exactly the way it answered this one, so re-sending
# the remaining batches only burns time and (off Plus) money on a request
# that cannot succeed. Everything else — 5xx, a dropped connection, a
# malformed tool result — keeps D4's per-batch rule: that batch is unjudged
# and the loop goes on.
FATAL_STATUS = (401, 402, 403, 426)

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


def judge(client: Any, model: str, cards: list[CardText], page: PageText, lecture_display: str, *,
          on_headers: Callable[[Any], None] | None = None,
          cancel: Any = None,
          on_fatal: Callable[[Exception], None] | None = None) -> list[Verdict]:
    """A batch that fails leaves only ITS cards unjudged (fix round 1,
    Finding 2) — one failed `client.complete` must not take an
    already-paid-for earlier batch's verdicts down with it, and the job
    still finishes and tags whatever it did manage to judge. The log line
    names the exception's class (and status, if it carries one) only —
    never the request payload, which holds card and lecture-page text.

    ``on_headers`` (Task 3, Klaus Plus postdates this module's original
    brief) forwards straight to ``client.complete`` — a metered Plus call's
    own response IS a fresh quota reading, and this is the one place every
    judge request actually leaves the process.

    ``on_fatal`` + the FATAL_STATUS break (I-1) are the exception to the
    per-batch rule: a refusal is not a hiccup, so the FIRST one ends this
    call and is reported ONCE — before this, an exhausted Plus quota sent
    and lost every remaining batch in silence, and a rejected key made
    Judge indistinguishable from Skip. A raising ``on_fatal`` is logged,
    never propagated: reporting a refusal must not itself become one.

    ``cancel`` is checked before EVERY batch (M-1), not only between pages
    — Stop mid-page used to keep paying for that page's remaining batches.
    """
    out: list[Verdict] = []
    for i in range(0, len(cards), BATCH):
        if cancel is not None and cancel.is_set():
            break
        batch = cards[i:i + BATCH]
        try:
            resp = client.complete(build_request(batch, page, lecture_display, model), purpose="judge",
                                   on_headers=on_headers)
        except Exception as exc:  # noqa: BLE001 — one batch, not the job
            status = getattr(exc, "status", None)
            detail = f"{type(exc).__name__}" + (f" status={status}" if status is not None else "")
            print(f"[klausmate] pertinence: batch of {len(batch)} left unjudged ({detail})")
            if status in FATAL_STATUS:
                if on_fatal is not None:
                    try:
                        on_fatal(exc)
                    except Exception as cb_exc:  # noqa: BLE001
                        print(f"[klausmate] pertinence: on_fatal failed ({type(cb_exc).__name__})")
                break
            continue
        out.extend(parse_verdicts(resp, batch, page, model))
    return out


def judged_path(user_files: str, safe: str) -> str:
    return os.path.join(user_files, "pdf_index", safe, JUDGED_FILE)


def _empty() -> dict:
    return {"version": VERSION, "model": "", "verdicts": {}}


def load_judged(user_files: str, safe: str, *, strict: bool = False) -> dict:
    """The judged store, or an empty one when the file is missing.

    A file that EXISTS but cannot be read as a store (torn write, hand
    edit, an older version) reads as empty too — the judge rewrites it on
    the next index of that PDF — unless ``strict`` is set, in which case it
    raises ``ValueError``: `tag_sync.doubtful_members` reads strictly,
    because "empty" there would compute an empty rejected set and STRIP
    that PDF's Doubtful members, and unreadable data must never strip a
    tag (Copilot review of PR #4, 2026-09-17).
    """
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
        if strict:
            raise ValueError(f"judged.json unreadable: {p}: {exc}") from exc
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


# ---------------------------------------------------------------------------
# Below this line: aqt glue (Task 3) — the index chain's fourth phase (spec
# D4). Everything above stays pure and importable without Qt.
# ---------------------------------------------------------------------------

try:
    from aqt.operations import QueryOp
    from aqt.utils import tooltip
except Exception:  # headless tests / partial environments
    QueryOp = None  # type: ignore[assignment]
    tooltip = None  # type: ignore[assignment]


def _pkg():
    import importlib

    return importlib.import_module(__package__)


def _matched_pages(pdf_name: str) -> dict[int, int]:
    """Best-matching page per candidate nid, read straight from the
    matches.json cache ``ensure_matches`` just wrote for this job.

    A bare read of the same file rather than a re-validated
    ``retention.load_matches`` call — the freshness check already
    happened this pass, one phase back. Any failure (missing/corrupt
    cache, a PDF whose match pass never ran) reads as "no pages", which
    leaves every candidate with nowhere to be judged against — the safe
    default, never a crash.
    """
    from . import retention

    try:
        with open(retention._matches_path(pdf_name), encoding="utf-8") as f:
            m = json.load(f)
        return {int(k): int(v) for k, v in (m.get("pages") or {}).items()}
    except (OSError, ValueError, AttributeError, TypeError, json.JSONDecodeError) as exc:
        print(f"[klausmate] pertinence: no page cache for {pdf_name!r}: {exc}")
        return {}


def _card_text(col: Any, nid: int, strip: Callable[[str], str]) -> tuple[str, str]:
    """(text, text_hash) for one note, empty on any read failure (a
    deleted note between matching and judging is not this phase's job to
    report — it just leaves that candidate with no text, so it is never
    added to a batch)."""
    from . import card_index

    try:
        fields = col.get_note(nid).fields
    except Exception as exc:
        print(f"[klausmate] pertinence: note {nid} unreadable: {exc}")
        return "", ""
    text = card_index.note_text(fields, strip, cap=MAX_CARD_CHARS)
    return (text, card_index.text_hash(text)) if text else ("", "")


def ensure_judged(
    parent: Any,
    pdf_name: str,
    matches: list[tuple[int, float]] | None,
    *,
    on_done: Callable[[set[int]], None],
    on_error: Callable[[Exception], None],
    cancel: Any,
    on_progress: Callable[[str, int, int], None] | None,
    ask: Callable[[Any, str, Callable[[bool], None]], None],
) -> None:
    """Index chain phase four (spec D4): judge every candidate at/above
    threshold against its best-matching page, batched and cached in
    judged.json. ``on_done(rejected_nids)`` fires exactly once, whatever
    path gets there.

    Klaus Plus subscribers need no Anthropic key; everyone else without
    one is told once and left unjudged rather than shown a paid-pass
    prompt they have no way to pay for — Klaus Plus postdates the spec
    this module was built from, so this gate is a ruling, not the brief.
    """
    from . import anthropic_client, cost, page_store, pdf_handler, plus, retention
    from .index_queue import _cfg, _user_files, display_name

    cfg = _cfg()
    display = display_name(pdf_name)
    if not plus.active(cfg) and not str(cfg.get("api_key_anthropic") or "").strip():
        print(f"[klausmate] pertinence: no Anthropic key and Klaus Plus is not active "
              f"— “{display}” stays unjudged.")
        on_done(set())
        return

    user_files = _user_files()
    safe = pdf_handler._safe_basename(pdf_name)
    path = pdf_handler.pdf_path_for(user_files, safe) or ""
    threshold = retention.get_threshold(pdf_name, cfg)
    pages = _matched_pages(pdf_name)
    cands = candidates(matches or [], threshold)
    model = str(cfg.get("reasoning_model") or "claude-sonnet-5")
    judged = load_judged(user_files, safe)
    strip = _pkg()._strip_html

    page_rows: dict[int, tuple[str, str]] = {}  # page -> (page_hash, combined_text)
    todo: dict[int, list[CardText]] = {}
    for nid in cands:
        page = pages.get(nid) or 0
        if page <= 0:
            continue  # no known best page — nothing to judge this card against
        if page not in page_rows:
            rec = page_store.load_record(user_files, safe, path, page - 1)
            page_rows[page] = (page_store.text_hash(rec), page_store.combined_text(rec))
        text, h = _card_text(parent.col, nid, strip)
        if not text:
            continue
        entry = judged["verdicts"].get(str(nid))
        if entry is not None and not is_stale(entry, h, page_rows[page][0], model):
            continue  # cached and fresh
        todo.setdefault(page, []).append(CardText(nid, text, h))

    if not todo:
        on_done(rejected_nids(judged))
        return

    n_cards = sum(len(v) for v in todo.values())
    mean_card = int(sum(len(c.text) for cards in todo.values() for c in cards) / max(1, n_cards))
    mean_page = int(sum(len(page_rows[p][1]) for p in todo) / max(1, len(todo)))

    if plus.active(cfg):
        # Unmetered-in-dollars from the user's own side (Plus is metered in
        # cards, not tokens), so no reason to touch cost.estimate_judge at
        # all here — never compute a number this branch will never show.
        human = ((cfg.get(plus.CACHE) or {}).get("quota") or {}).get("human") or {}
        used_total = human.get("cards")
        quota_note = (
            f" (you've used {used_total[0]:,} of {used_total[1]:,} cards this month)"
            if isinstance(used_total, (list, tuple)) and len(used_total) == 2 else ""
        )
        text = f"Judge {n_cards} cards against their lecture pages?\n\nIncluded in Klaus Plus{quota_note}."
    else:
        # reasoning_model is free text (no picker, CLAUDE.md's own rule), so
        # cost.PRICES — six entries, only two of them reasoning models — has
        # no guarantee of covering it. Price an unpriced model as Sonnet and
        # SAY SO rather than let
        # cost.estimate_judge's KeyError escape this phase (fix round 1,
        # C1): a raise here reaches ensure_matches' QueryOp callback, which
        # skips the tag write and never clears index_queue._current —
        # wedging the whole queue for the session.
        priced_model = model if model in cost.PRICES else "claude-sonnet-5"
        est = cost.estimate_judge(n_cards, mean_page, card_chars_mean=mean_card, batch=BATCH, model=priced_model)
        priced_note = "" if priced_model == model else " (priced as Sonnet)"
        text = (f"Ask Claude which of {n_cards} matched cards are truly about "
                f"“{display}”?\n\n{cost.format_estimate(est)}{priced_note}, billed to your "
                "Anthropic key. Skipped cards stay tagged as matched.")

    def go(yes: bool) -> None:
        if not yes:
            on_done(rejected_nids(judged))
            return
        client = anthropic_client.Client(_cfg)
        on_plus = plus.active(cfg)
        on_headers = (lambda h: plus.note_quota(cfg, h, _pkg().patch_config)) if on_plus else None
        fatal: list[Exception] = []

        def on_fatal(exc: Exception) -> None:
            """A refused key or licence answers every page the same way, so
            this stops the WHOLE job (the page loop below reads `fatal`),
            remembers the verdict on Plus, and says so once (I-1).

            Runs on the QueryOp's background thread: the config write hops
            to the main thread inside `patch_config` — which is the only
            config writer a background thread may use, since the plain
            `write_config` REPLACES the whole stored blob — and the tooltip
            is marshalled explicitly. Whatever gets judged before the
            refusal is still saved and still tags.
            """
            if fatal:
                return
            fatal.append(exc)
            say = getattr(exc, "user_message", None)
            text = say() if callable(say) else str(exc)
            if on_plus:
                sink = getattr(_pkg(), "patch_config", None)
                if sink is None:
                    print("[klausmate] Klaus Plus refusal not cached: package has no patch_config")
                else:
                    plus.note_refusal(cfg, getattr(exc, "status", 0) or 0, sink, message=text)
            if tooltip is not None:
                parent.taskman.run_on_main(lambda: tooltip(text, period=6000))

        def work(_col: Any = None) -> set[int]:
            done = 0
            for page, cards in todo.items():
                if fatal or (cancel is not None and cancel.is_set()):
                    break
                page_hash, page_text = page_rows[page]
                verdicts = judge(client, model, cards, PageText(page, page_hash, page_text), display,
                                 on_headers=on_headers, cancel=cancel, on_fatal=on_fatal)
                for v in verdicts:
                    judged["verdicts"][str(v.nid)] = entry_for(v)
                done += len(cards)
                if on_progress:
                    parent.taskman.run_on_main(lambda d=done: on_progress("judging", d, n_cards))
            judged["model"] = model
            save_judged(user_files, safe, judged)
            return rejected_nids(judged)

        op = QueryOp(parent=parent, op=lambda _col: work(), success=on_done)
        op.failure(on_error)
        op.without_collection().run_in_background()

    ask(parent, text, go)
