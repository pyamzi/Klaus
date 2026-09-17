# Pertinence Phase and Lecture Recorder Implementation Plan (API-first Klaus, Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After indexing, Claude judges each candidate card against the lecture page it matched best; rejected cards gain `!Library::Doubtful` and drop out of the retention score and counts. During a lecture, Klaus records audio in 30-second chunks stamped with the page in view, transcribes them through OpenAI, and appends the text to that page's record, which the index, the judgment and the assistant then read.

**Architecture:** `pertinence.py` (aqt-free core) batches candidate cards per page into one forced-tool Messages request each, persists verdicts in `judged.json` keyed on card and page hashes, and becomes phase four of `index_queue._run`. `tag_sync.py` gains the Doubtful tag; `retention.py` scores confirmed cards. `lecture_recorder.py` is a pure chunking state machine plus Qt glue over the bundled `QAudioSource`, with a worker that uploads chunks and appends segments to `page_store`. The viewer gains a transcript strip; the dock bar and the Lecture dock gain Record.

**Tech Stack:** Python 3.9-compatible source, stdlib (`wave`, `threading`, `queue`), PyQt6 `QtMultimedia` (bundled with Anki 26.8.1), the `tests/` harness, offscreen Qt.

**Spec:** `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md` — decisions D4, D5, D6.

## Global Constraints

- The Plan 1 constraints (main checkout, headless testing, no paid calls without `KLAUS_LIVE_API=1`, conventions, board rules, workers never commit) apply verbatim.
- Plan 1 is committed before this plan starts: `page_store.py`, `openai_client.py`, `anthropic_client.py`, `cost.py`, `pdf_index.pages`, `retention.match_scores -> (scores, pages)`, `matches.json["pages"]`, config keys `api_key_openai`, `api_key_anthropic`, `reasoning_model`, `transcription_model`.
- Every verdict is a strict tool call: the `record_verdicts` tool is declared `strict: true`, `additionalProperties: false`, all fields `required`; a card missing from the tool input or a malformed input yields NO verdict (unjudged), never doubtful.
- The Doubtful tag is exactly `!Library::Doubtful`; `tag_sync.RESERVED_LEAVES` gains `"doubtful"` so reconcile never renames it.
- Retention and counts use `confirmed = matched − rejected`; unjudged cards count as confirmed.
- No paid pass runs without the estimate prompt (Judge / Skip); a network failure leaves cards unjudged with one log line.
- Chunks close at 30 seconds or on a page change, whichever first; text never straddles pages. A chunk whose upload fails keeps its WAV. Never record without a PDF in view.
- Colours only through `theme` tokens; no app-modal `exec()`.

---

## File structure

- Create: `klausmate/pertinence.py`, `klausmate/lecture_recorder.py`; tests `tests/test_pertinence.py`, `tests/test_lecture_recorder.py`; fixture `tests/fixtures/anthropic/verdicts_turn.json`.
- Modify: `klausmate/index_queue.py` (phase four, `RunnerState.phase`, the Judge/Skip prompt), `klausmate/tag_sync.py` (Doubtful), `klausmate/retention.py` (`rejected` in scoring and counts, `doubtful_count`), `klausmate/library_explorer.py` + `klausmate/pdf_drive.py` (Cards cell copy, "Doubtful cards…" menu item), `klausmate/__init__.py` (`_PanelBar` Record button), `klausmate/lecture_view.py` (Record button), `klausmate/pdf_viewer.py` (transcript strip), `klausmate/pdfjs_viewer.py` + `klausmate/web/pdfjs_viewer.html` (transcript strip via the bridge), `klausmate/theme.py` (a `transcript_strip_qss`), `CLAUDE.md`, `AGENTS.md`, `klausmate/config.md`, plus tests `tests/test_index_queue.py`, `tests/test_klausmate.py` (tag_sync/retention sections), `tests/test_drive.py`, `tests/test_library_explorer.py`, `tests/test_pdf_dock.py`, `tests/test_lecture_view.py`, `tests/test_pdfjs_viewer.py`, `tests/test_theme.py`.

Lanes: Task 1 (`pertinence` core) ∥ Task 4 (`lecture_recorder` core + Qt) ∥ Task 6 (theme + transcript strip in both viewers). Task 2 (`tag_sync` + `retention` + Library copy) after Task 1. Task 3 (`index_queue` phase four + prompt) after Tasks 1–2. Task 5 (Record buttons + upload worker wiring) after Task 4. Task 7 (docs + integration) last.

---

### Task 1: The pertinence core

**Files:**
- Create: `klausmate/pertinence.py`, `tests/test_pertinence.py`, `tests/fixtures/anthropic/verdicts_turn.json`

**Interfaces:**
- Consumes: `anthropic_client.Client.complete(payload) -> dict`; `card_index.text_hash(text) -> str`; `page_store.text_hash`.
- Produces: `CardText(nid: int, text: str, text_hash: str)`, `PageText(page: int, page_hash: str, text: str)`, `Verdict(nid, pertinent, reason, page, page_hash, card_hash, model)` (NamedTuples); `BATCH = 8`; `TOOL` (the strict tool dict); `build_request(cards, page, lecture_display, model) -> dict` (the Messages payload); `parse_verdicts(response: dict, cards, page, model) -> list[Verdict]`; `judge(client, model, cards, page, lecture_display) -> list[Verdict]`; `judged_path(user_files, safe) -> str`; `load_judged(user_files, safe) -> dict`; `save_judged(user_files, safe, judged: dict) -> None`; `is_stale(entry: dict, card_hash: str, page_hash: str, model: str) -> bool`; `rejected_nids(judged: dict) -> set[int]`; `all_rejected(user_files) -> set[int]`; `candidates(matches, threshold) -> list[int]`.

- [ ] **Step 1: Write the fixture and the failing tests.** `tests/fixtures/anthropic/verdicts_turn.json`:

```json
{"id": "msg_v", "role": "assistant", "stop_reason": "tool_use",
 "content": [{"type": "tool_use", "id": "toolu_v", "name": "record_verdicts",
   "input": {"verdicts": [
     {"nid": 11, "pertinent": true, "reason": "the card asks for the mechanism this slide states"},
     {"nid": 12, "pertinent": false, "reason": "same organ, different disease; the slide never mentions it"}]}}]}
```

`tests/test_pertinence.py`:

```python
pt = importlib.import_module("klausmate.pertinence")
cards = [pt.CardText(11, "Q: mechanism of X? A: Y", "c11"), pt.CardText(12, "Q: Z? A: W", "c12"), pt.CardText(13, "Q: unjudged", "c13")]
page = pt.PageText(4, "p4hash", "Slide 4: X works by Y.\n\nthe lecturer said Y twice")

section("build_request")
req = pt.build_request(cards, page, "Renal Physiology", "claude-sonnet-5")
tool = req["tools"][0]
check("one strict tool, forced by name", tool["name"] == "record_verdicts" and tool["strict"] is True
      and tool["input_schema"]["additionalProperties"] is False and req["tool_choice"] == {"type": "tool", "name": "record_verdicts"})
check("every card's nid and text and the page text are in the user turn", all(str(c.nid) in req["messages"][0]["content"] and c.text in req["messages"][0]["content"] for c in cards) and page.text in req["messages"][0]["content"])
check("the system prompt states the test and forbids guessing", "reasonable preparation" in req["system"] and "not merely the same subject" in req["system"] and req["model"] == "claude-sonnet-5" and req["max_tokens"] >= 1024)

section("parse_verdicts")
resp = json.load(open(os.path.join(FIX, "verdicts_turn.json")))
vs = pt.parse_verdicts(resp, cards, page, "claude-sonnet-5")
check("two verdicts, keyed to the cards, carrying page and card hashes and the model",
      [(v.nid, v.pertinent) for v in vs] == [(11, True), (12, False)] and vs[0].page == 4 and vs[0].page_hash == "p4hash" and vs[1].card_hash == "c12" and vs[0].model == "claude-sonnet-5")
check("a card absent from the tool input gets NO verdict", 13 not in {v.nid for v in vs})
bad = {"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [{"nid": "eleven", "pertinent": "yes"}]}}]}
check("malformed input → no verdicts, never doubtful", pt.parse_verdicts(bad, cards, page, "m") == [])
check("a nid not in the batch is ignored", pt.parse_verdicts({"content": [{"type": "tool_use", "name": "record_verdicts", "input": {"verdicts": [{"nid": 999, "pertinent": False, "reason": "x"}]}}]}, cards, page, "m") == [])

section("judge batches and calls complete")
calls = []
class FakeClient:
    def complete(self, payload, timeout=None):
        calls.append(payload); return resp
many = [pt.CardText(i, f"card {i}", f"h{i}") for i in range(20)]
out = pt.judge(FakeClient(), "claude-sonnet-5", many, page, "Lec")
check("20 cards → 3 requests of at most BATCH", len(calls) == 3 and all(len(json.loads(c["messages"][0]["content"].split("CARDS_JSON=")[1])) <= pt.BATCH for c in calls) if "CARDS_JSON=" in calls[0]["messages"][0]["content"] else len(calls) == 3)

section("judged.json persistence and staleness")
root = tempfile.mkdtemp()
j = {"version": 1, "model": "claude-sonnet-5", "verdicts": {}}
for v in vs:
    j["verdicts"][str(v.nid)] = {"pertinent": v.pertinent, "reason": v.reason, "page": v.page, "page_hash": v.page_hash, "card_hash": v.card_hash}
pt.save_judged(root, "lec", j)
back = pt.load_judged(root, "lec")
check("round-trips; keys are strings on disk, ints in rejected_nids", back["verdicts"]["12"]["pertinent"] is False and pt.rejected_nids(back) == {12})
e = back["verdicts"]["11"]
check("stale when the card hash, the page hash or the model changed",
      not pt.is_stale(e, "c11", "p4hash", "claude-sonnet-5") and pt.is_stale(e, "c11x", "p4hash", "claude-sonnet-5")
      and pt.is_stale(e, "c11", "p4other", "claude-sonnet-5") and pt.is_stale(e, "c11", "p4hash", "claude-opus-5"))
open(pt.judged_path(root, "lec"), "w").write("{bad")
check("a corrupt judged.json reads as empty", pt.load_judged(root, "lec")["verdicts"] == {})
pt.save_judged(root, "other", {"version": 1, "model": "m", "verdicts": {"7": {"pertinent": False, "reason": "", "page": 1, "page_hash": "", "card_hash": ""}}})
pt.save_judged(root, "lec", j)
check("all_rejected unions every PDF's rejections", pt.all_rejected(root) == {12, 7})
check("candidates = nids at/above threshold, in score order", pt.candidates([(1, 0.9), (2, 0.5), (3, 0.75)], 0.75) == [1, 3])
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `ModuleNotFoundError`.

- [ ] **Step 3: Implement `klausmate/pertinence.py`.**

```python
"""Is this card truly about this lecture page? Claude decides (spec D4).

Cosine matching shortlists; this phase judges each candidate card against
the ONE page it matched best, in batches of BATCH per request, through a
strict forced tool so the answer is always well-formed or absent — a card
the model did not answer for is UNJUDGED (counted, tagged as matched),
never doubtful. Verdicts persist in judged.json beside matches.json and go
stale when the card's text, the page's text, or the model changes.

aqt-free above the divider.
"""
from __future__ import annotations

import json
import os
from typing import Any, NamedTuple

BATCH = 8
MAX_TOKENS = 2048
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
    cards_json = json.dumps([{"nid": c.nid, "card": c.text} for c in cards], ensure_ascii=False)
    user = (
        f"Lecture: {lecture_display}\nSlide {page.page}:\n<<<\n{page.text}\n>>>\n\n"
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
    by_nid = {c.nid: c for c in cards}
    out: list[Verdict] = []
    for block in response.get("content") or []:
        if block.get("type") != "tool_use" or block.get("name") != "record_verdicts":
            continue
        items = (block.get("input") or {}).get("verdicts")
        if not isinstance(items, list):
            return []
        for it in items:
            if not isinstance(it, dict):
                return []
            nid, pert, reason = it.get("nid"), it.get("pertinent"), it.get("reason")
            if not isinstance(nid, int) or isinstance(nid, bool) or not isinstance(pert, bool) or not isinstance(reason, str):
                return []
            c = by_nid.get(nid)
            if c is None:
                continue
            out.append(Verdict(nid, pert, reason.strip(), page.page, page.page_hash, c.text_hash, model))
    return out


def judge(client: Any, model: str, cards: list[CardText], page: PageText, lecture_display: str) -> list[Verdict]:
    out: list[Verdict] = []
    for i in range(0, len(cards), BATCH):
        batch = cards[i:i + BATCH]
        resp = client.complete(build_request(batch, page, lecture_display, model))
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
        if not isinstance(j, dict) or not isinstance(j.get("verdicts"), dict):
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
    return not (entry.get("card_hash") == card_hash and entry.get("page_hash") == page_hash and entry.get("model", model) == model)


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
```

Record the model per verdict entry too (`"model": v.model`) when Task 3 writes entries, so `is_stale`'s model test is real.

- [ ] **Step 4: Run to verify it passes.** → `0 failed`. Compile through the symlink.

- [ ] **Step 5: Mutate once.** In `parse_verdicts` change `return []` on a malformed item to `continue` → the malformed pin fails; restore with md5s. Board comment; card stays in Doing.

---

### Task 2: The Doubtful tag, confirmed-only retention, the Library's copy

**Files:**
- Modify: `klausmate/tag_sync.py` (`DOUBTFUL_TAG`, `RESERVED_LEAVES`, `sync_after_matches(..., doubtful=None)`, `_do_sync_one` applies both tags, `sync_after_threshold`/`sync_after_clear_overrides` recompute Doubtful from `pertinence.all_rejected`)
- Modify: `klausmate/retention.py` (`pdf_retention(..., rejected: set[int] | None = None)`, `note_card_counts(..., rejected=None) -> (note_count, card_count, suspended_count, doubtful_count)`, `priority_rows` reads `pertinence.load_judged` per PDF and passes `rejected`; rows gain `doubtful_count`)
- Modify: `klausmate/library_explorer.py` (Cards cell `f"{n} · {m} doubtful"` when `m > 0`), `klausmate/pdf_drive.py` (context-menu item "Doubtful cards…" → `browser.search_for(f'tag:{DOUBTFUL_TAG} "tag:{lecture_tag}"')`)
- Test: `tests/test_klausmate.py` (tag_sync + retention sections), `tests/test_library_explorer.py`, `tests/test_drive.py`

**Interfaces:**
- Consumes: `pertinence.all_rejected`, `pertinence.load_judged`, `pertinence.rejected_nids` (Task 1).
- Produces: `tag_sync.DOUBTFUL_TAG = "!Library::Doubtful"`; `tag_sync.sync_after_matches(parent, pdf_name, matches, *, doubtful: set[int] | None = None, on_done=None)`; `retention.priority_rows` row key `doubtful_count`; `pdf_drive.DOUBTFUL_MENU_LABEL = "Doubtful cards…"`.

- [ ] **Step 1: Write the failing pins** (`tests/test_klausmate.py`):

```python
section("Doubtful tag membership")
check("the tag is reserved and named", tag_sync.DOUBTFUL_TAG == "!Library::Doubtful" and "doubtful" in tag_sync.RESERVED_LEAVES)
col = FakeCol(tags={"!Library::Renal": {1, 2, 3}, "!Library::Doubtful": {9}})
res = tag_sync._do_sync_one(col, "renal", "!Library::Renal", desired_nids={1, 2, 3}, doubtful={2, 5})
check("the lecture tag keeps every match; Doubtful becomes exactly the rejected set across PDFs",
      col.members("!Library::Renal") == {1, 2, 3} and col.members("!Library::Doubtful") == {2, 5})
section("retention counts confirmed cards only")
n, c, s, d = retention.note_card_counts(matches=[(1, .9), (2, .8), (3, .7)], threshold=.75, card_r={1: [(0.9, False)], 2: [(0.5, False)]}, card_queues={1: [0], 2: [0]}, rejected={2})
check("note_count excludes rejected, doubtful_count reports them", n == 1 and d == 1)
r_all = retention.pdf_retention([(1, .9), (2, .8)], .75, {1: [(0.9, False)], 2: [(0.1, False)]})
r_conf = retention.pdf_retention([(1, .9), (2, .8)], .75, {1: [(0.9, False)], 2: [(0.1, False)]}, rejected={2})
check("the score ignores rejected cards", r_conf > r_all)
```

(use the fake collection the file already has, extended with a `members(tag)` helper; adapt argument names to the real signatures at `retention.py:226-290`.) `tests/test_library_explorer.py`: a row with `doubtful_count=3` renders "12 · 3 doubtful"; with 0 renders "12". `tests/test_drive.py`: the row menu source contains `DOUBTFUL_MENU_LABEL` and the search string shape.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** `tag_sync.py`: `DOUBTFUL_TAG = "!Library::Doubtful"`; `RESERVED_LEAVES = frozenset({"curating", "curated", "matching", "doubtful"})`; `_do_sync_one(col, safe, tag, desired_nids, doubtful=None)` applies `apply_membership(col, tag, desired_nids)` then, when `doubtful is not None`, `apply_membership(col, DOUBTFUL_TAG, doubtful)`, returning both diffs in the result dict (`"doubtful_added"`, `"doubtful_removed"`); `sync_after_matches` gains `doubtful` and passes it; `sync_after_threshold` and `sync_after_clear_overrides` compute `doubtful = pertinence.all_rejected(user_files)` (lazy import) and pass it, so the slider never re-judges. `retention.py`: `pdf_retention(matches, threshold, card_r, rejected=None)` filters `nid in rejected` out before aggregating; `note_card_counts(..., rejected=None)` returns a 4-tuple with `doubtful_count = |{nid at/above threshold} ∩ rejected|`; `priority_rows` loads `pertinence.load_judged(USER_FILES, safe)` per PDF (guarded), passes `rejected_nids(...)`, and writes `doubtful_count` into each row (0 when unjudged). `library_explorer.py`: the Cards column text builder appends `f" · {m} doubtful"` when `row.get("doubtful_count")`. `pdf_drive.py`: the row context menu gains `DOUBTFUL_MENU_LABEL` after "Show matches in Browse", enabled when `doubtful_count > 0`, opening Browse with `f'tag:{tag_sync.DOUBTFUL_TAG} "tag:{stored_tag}"'` through the same `_show_in_browse` path the existing item uses.

- [ ] **Step 4: Run to verify it passes.** `tests/test_klausmate.py`, `tests/test_library_explorer.py`, `tests/test_drive.py` → `0 failed`.

- [ ] **Step 5: Mutate once.** Drop the `rejected` filter in `pdf_retention` → the score pin fails; restore. Board comment; card stays in Doing.

---

### Task 3: Phase four in the index chain, with the Judge/Skip prompt

**Files:**
- Modify: `klausmate/index_queue.py` (`RunnerState.phase: str = ""`, `status_line` shows it; `_run`'s `after_matches` → `pertinence_phase`; the prompt; `cost.estimate_judge`)
- Modify: `klausmate/pertinence.py` (below a divider: `ensure_judged(mw, pdf_name, matches, *, on_done, on_error, cancel, on_progress, ask)`) — the same file as Task 1, so this task runs after Task 1's card is Done.
- Test: `tests/test_index_queue.py`, `tests/test_pertinence.py` (the glue section with a fake `mw`/`col`)

**Interfaces:**
- Consumes: `retention.load_matches(...) -> (matches, pages)`, `retention.get_threshold(name, cfg)`, `card_index.load_row_map`/`note_text`/`text_hash` (existing) for card texts, `page_store.page_texts`, `anthropic_client.Client`, `cost.estimate_judge/format_estimate`, `tag_sync.sync_after_matches(..., doubtful=)`.
- Produces: `pertinence.ensure_judged(parent, pdf_name, matches, *, on_done: Callable[[set[int]], None], on_error, cancel, on_progress, ask: Callable[[str, Callable[[bool], None]], None]) -> None` — `on_done(rejected_nids)`; `index_queue.RunnerState.phase`; `index_queue.ask_judge(parent, text, answer)` (window-modal `QMessageBox.open()`, buttons Judge/Skip, Skip default).

- [ ] **Step 1: Write the failing pins.** `tests/test_index_queue.py`: `status_line(RunnerState(active=True, name="Lec", label="judging", phase="judge", done=12, total=40))` contains `"judging 12/40"`; the `_run` source calls `pertinence.ensure_judged` between `ensure_matches` and `sync_after_matches` and passes `doubtful=`; `ask_judge`'s source uses `.open()` and sets Skip as the default button (source pins, the file's existing style). `tests/test_pertinence.py` glue section: with a fake client returning the fixture and a fake `mw` whose `col.get_note(nid).fields` yields texts, `ensure_judged` on matches `[(11,.9),(12,.85),(13,.5)]` with threshold .75 writes `judged.json` with entries for 11 and 12 (13 below threshold, never sent), calls `on_done({12})`, and a second call with unchanged hashes makes NO client call (cached); after `ask` answers False, no client call and `on_done(set())`.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** `index_queue.RunnerState` gains `phase: str = ""`; `status_line`: when `state.phase == "judge"` render `f"{name} — judging {done}/{total}"`. In `_run`:

```python
    def after_judged(rejected: set[int], matches: Any) -> None:
        if not live():
            return
        try:
            tag_sync.sync_after_matches(mw, name, matches, doubtful=pertinence.all_rejected(_user_files()))
        except Exception as exc:
            print(f"[klausmate] tag sync after index failed: {exc}")
        _job_done(f"Indexed “{label}”.", finished=name)

    def after_matches(matches: Any) -> None:
        if not live():
            return
        pertinence.ensure_judged(
            mw, name, matches,
            on_done=lambda rejected: after_judged(rejected, matches),
            on_error=on_error, cancel=cancel,
            on_progress=lambda text, d, t: _publish(_state._replace(phase="judge", label=text, done=d, total=t)) if live() else None,
            ask=ask_judge,
        )
```

`ask_judge(parent, text, answer)`: a `QMessageBox` with `setText(text)`, buttons `Judge` (AcceptRole) and `Skip` (RejectRole), `setDefaultButton(skip)`, `theme.dialog_qss`, `finished` → `answer(clicked is judge)`, `open()`. `pertinence.ensure_judged` (below the divider):

```python
def ensure_judged(parent, pdf_name, matches, *, on_done, on_error, cancel, on_progress, ask) -> None:
    from . import anthropic_client, card_index, cost, page_store, pdf_handler, retention
    from .index_queue import _user_files, _cfg
    cfg = _cfg(); user_files = _user_files()
    safe = pdf_handler._safe_basename(pdf_name)
    threshold = retention.get_threshold(pdf_name, cfg)
    _m, pages = retention.load_matches_pages(pdf_name)          # the cached nid → best page
    cands = candidates(matches or [], threshold)
    model = str(cfg.get("reasoning_model") or "claude-sonnet-5")
    judged = load_judged(user_files, safe)
    path = pdf_handler.pdf_path_for(user_files, safe) or ""
    page_rows = {p: (h, t) for p, h, t in page_store.page_texts(user_files, safe, path, len(pdf_handler.load_pages(user_files, pdf_name) or []))}
    texts = card_index.note_texts_for(parent.col, cands)        # {nid: (text, hash)} — add beside note_text if absent
    todo: dict[int, list[CardText]] = {}
    for nid in cands:
        text, h = texts.get(nid, ("", ""))
        page = pages.get(nid) or 0
        ph = page_rows.get(page, ("", ""))[0]
        entry = judged["verdicts"].get(str(nid))
        if entry is not None and not is_stale(entry, h, ph, model):
            continue
        if text and page in page_rows:
            todo.setdefault(page, []).append(CardText(nid, text, h))
    if not todo:
        on_done(rejected_nids(judged)); return
    n_cards = sum(len(v) for v in todo.values())
    mean_page = int(sum(len(page_rows[p][1]) for p in todo) / max(1, len(todo)))
    est = cost.estimate_judge(n_cards, mean_page, model=model)
    text = (f"Ask Claude which of {n_cards} matched cards are truly about “{pdf_handler.display_name(pdf_name)}”?\n\n"
            f"{cost.format_estimate(est)}, billed to your Anthropic key. Skipped cards stay tagged as matched.")

    def go(yes: bool) -> None:
        if not yes:
            on_done(rejected_nids(judged)); return
        client = anthropic_client.Client(_cfg)
        def work(_col=None):
            done = 0
            for page, cards in todo.items():
                if cancel is not None and cancel.is_set():
                    break
                h, t = page_rows[page]
                try:
                    for v in judge(client, model, cards, PageText(page, h, t), pdf_handler.display_name(pdf_name)):
                        judged["verdicts"][str(v.nid)] = {"pertinent": v.pertinent, "reason": v.reason, "page": v.page, "page_hash": v.page_hash, "card_hash": v.card_hash, "model": v.model}
                except anthropic_client.LLMError as exc:
                    print(f"[klausmate] pertinence batch failed, cards left unjudged: {exc.user_message()}")
                done += len(cards)
                if on_progress:
                    mw.taskman.run_on_main(lambda d=done: on_progress("judging", d, n_cards))
            judged["model"] = model
            save_judged(user_files, safe, judged)
            return rejected_nids(judged)
        op = QueryOp(parent=parent, op=lambda col: work(), success=on_done)
        op.failure(on_error); op.without_collection().run_in_background()
    ask(parent, text, go)
```

(`retention.load_matches_pages(pdf_name)` is a thin reader over `matches.json["pages"]` — add it in this task if Plan 1 left only the tuple return; `card_index.note_texts_for(col, nids)` = `{nid: (note_text(fields, strip), text_hash(text))}` using the same strip function `curation.ensure_index` uses — add beside `note_text`.)

- [ ] **Step 4: Run to verify it passes.** `tests/test_index_queue.py`, `tests/test_pertinence.py` → `0 failed`; full loop.

- [ ] **Step 5: Mutate once.** Make `is_stale` always False → the "second call makes no client call" pin still passes but the "changed hash re-judges" pin (add it) fails; restore. Board comment; card stays in Doing.

---

### Task 4: The lecture recorder core and Qt glue

**Files:**
- Create: `klausmate/lecture_recorder.py`, `tests/test_lecture_recorder.py`

**Interfaces:**
- Consumes: `viewer_context.current()` / `subscribe`, `page_store.append_segment`, `openai_client.transcribe`, `PyQt6.QtMultimedia.QAudioSource/QAudioFormat/QMediaDevices`.
- Produces: `CHUNK_S = 30.0`; `Chunk(page: int, t0: float, t1: float)`; `Chunker` with `start(page, t)`, `page_changed(page, t) -> Chunk | None`, `tick(t) -> Chunk | None`, `stop(t) -> Chunk | None`, `.page`, `.t0`, `.active`; `wav_bytes(pcm: bytes, rate: int = 16000) -> bytes`; `chunk_path(user_files, pdf_safe, chunk) -> str`; `Recorder(user_files, pdf_safe, pdf_path, get_page, on_status)` with `start()`, `stop()`, `is_recording`, `elapsed`, `queued`; `Uploader(user_files, get_config, on_segment)` with `enqueue(pdf_safe, pdf_path, chunk, wav_path)`, `requeue_leftovers(pdf_safe, pdf_path)`, `stop()`.

- [ ] **Step 1: Write the failing tests** (pure part; the Qt part is pinned offscreen in Task 5):

```python
lr = importlib.import_module("klausmate.lecture_recorder")
section("Chunker: 30 s cap, page change closes early, no straddle")
c = lr.Chunker()
c.start(page=3, t=100.0)
check("no chunk before 30 s", c.tick(120.0) is None and c.active and c.page == 3)
ch = c.tick(130.0)
check("closes at exactly CHUNK_S with the page it opened on", ch == lr.Chunk(3, 100.0, 130.0) and c.t0 == 130.0)
ch = c.page_changed(4, 140.0)
check("a page change closes the open chunk on the OLD page and reopens on the new", ch == lr.Chunk(3, 130.0, 140.0) and c.page == 4 and c.t0 == 140.0)
check("page_changed to the same page is a no-op", c.page_changed(4, 141.0) is None and c.t0 == 140.0)
ch = c.stop(150.0)
check("stop closes the last chunk; a stopped chunker emits nothing", ch == lr.Chunk(4, 140.0, 150.0) and not c.active and c.tick(200.0) is None)
c2 = lr.Chunker(); c2.start(1, 0.0)
check("a zero-length chunk is never emitted", c2.page_changed(2, 0.0) is None and c2.page == 2)

section("wav_bytes")
w = lr.wav_bytes(b"\x00\x00" * 160, 16000)
check("RIFF/WAVE 16 kHz mono int16", w[:4] == b"RIFF" and w[8:12] == b"WAVE" and len(w) == 44 + 320)
import wave, io
with wave.open(io.BytesIO(w)) as wf:
    check("header fields", wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getnframes() == 160)

section("chunk_path and the uploader")
root = tempfile.mkdtemp()
p = lr.chunk_path(root, "lec", lr.Chunk(3, 100.0, 130.0))
check("recordings/<safe>/<t0>-p<page:04d>.wav", p.endswith(os.path.join("recordings", "lec", "100-p0003.wav")))
segs = []
calls = []
def fake_transcribe(key, wav, model, language="en", prompt="", timeout=None):
    calls.append((key, model, prompt)); return "hello" if b"OK" in wav else ""
lr._transcribe = fake_transcribe
up = lr.Uploader(root, lambda: {"api_key_openai": "k", "transcription_model": "gpt-4o-mini-transcribe"}, on_segment=lambda safe, page: segs.append((safe, page)))
os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b"RIFF OK")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(3, 100.0, 130.0), p); up.drain()
check("a chunk transcribes, lands on page index 2 (page 3 is 1-based), and its WAV is deleted",
      segs == [("lec", 2)] and not os.path.exists(p) and calls[-1][1] == "gpt-4o-mini-transcribe")
p2 = lr.chunk_path(root, "lec", lr.Chunk(3, 130.0, 160.0)); open(p2, "wb").write(b"RIFF silence")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(3, 130.0, 160.0), p2); up.drain()
check("an empty transcript is dropped and the WAV still deleted", len(segs) == 1 and not os.path.exists(p2))
def boom(*a, **k): raise lr.openai_client.OpenAIError("down", status=500)
lr._transcribe = boom
p3 = lr.chunk_path(root, "lec", lr.Chunk(4, 160.0, 190.0)); open(p3, "wb").write(b"RIFF OK")
up.enqueue("lec", os.path.join(root, "lec.pdf"), lr.Chunk(4, 160.0, 190.0), p3); up.drain()
check("a failed upload keeps the WAV for the next Record", os.path.exists(p3))
lr._transcribe = fake_transcribe
n = up.requeue_leftovers("lec", os.path.join(root, "lec.pdf")); up.drain()
check("requeue_leftovers picks the leftover up by its filename (page and t0) and transcribes it", n == 1 and segs[-1] == ("lec", 3) and not os.path.exists(p3))
check("the prompt to the API is the previous segment's text (continuity), capped", calls[-1][2] == "hello")
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `ModuleNotFoundError`.

- [ ] **Step 3: Implement `klausmate/lecture_recorder.py`.** Pure part above the divider: `Chunker` as pinned (state: `page`, `t0`, `active`; `_close(t)` returns a `Chunk` only when `t > t0`), `wav_bytes` via the `wave` module, `chunk_path` (`f"{int(chunk.t0)}-p{chunk.page:04d}.wav"`), `_transcribe = openai_client.transcribe` (module-level for tests), and `Uploader`:

```python
class Uploader:
    """One daemon worker; FIFO; a failed chunk keeps its WAV."""
    def __init__(self, user_files, get_config, on_segment=None):
        self._q: "queue.Queue[tuple[str, str, Chunk, str] | None]" = queue.Queue()
        self._user_files, self._get_config, self._on_segment = user_files, get_config, on_segment
        self._last_text: dict[str, str] = {}
        self._thread = None
    def enqueue(self, pdf_safe, pdf_path, chunk, wav_path): self._q.put((pdf_safe, pdf_path, chunk, wav_path)); self._ensure_thread()
    def queued(self) -> int: return self._q.qsize()
    def _ensure_thread(self): ...  # start a daemon thread running _loop once
    def _loop(self):
        while True:
            item = self._q.get()
            if item is None: return
            self._one(*item); self._q.task_done()
    def drain(self): self._q.join()  # tests; runs _one synchronously when no thread was started
    def _one(self, pdf_safe, pdf_path, chunk, wav_path):
        cfg = self._get_config() or {}
        key = str(cfg.get("api_key_openai") or "").strip()
        model = str(cfg.get("transcription_model") or "gpt-4o-mini-transcribe")
        try:
            wav = open(wav_path, "rb").read()
            text = _transcribe(key, wav, model, prompt=self._last_text.get(pdf_safe, "")[-800:])
        except Exception as exc:
            print(f"[klausmate] transcription failed, keeping {os.path.basename(wav_path)}: {exc}"); return
        if text.strip():
            page_store.append_segment(self._user_files, pdf_safe, pdf_path, chunk.page - 1, chunk.t0, chunk.t1, text.strip())
            self._last_text[pdf_safe] = text.strip()
            if self._on_segment: self._on_segment(pdf_safe, chunk.page - 1)
        try: os.unlink(wav_path)
        except OSError: pass
    def requeue_leftovers(self, pdf_safe, pdf_path) -> int:
        d = os.path.join(self._user_files, "recordings", pdf_safe); n = 0
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            m = re.match(r"(\d+)-p(\d{4})\.wav$", name)
            if m: self.enqueue(pdf_safe, pdf_path, Chunk(int(m.group(2)), float(m.group(1)), float(m.group(1)) + CHUNK_S), os.path.join(d, name)); n += 1
        return n
    def stop(self): self._q.put(None)
```

(In tests, `drain()` with no started thread processes the queue inline — implement `drain` to pop and run `_one` synchronously when `self._thread is None`; `enqueue` starts the thread only when `_start_thread=True`, a constructor flag defaulting to True that the tests pass as False.) Qt glue below the divider: `Recorder` builds a `QAudioFormat` (16000 Hz, 1 channel, `SampleFormat.Int16`), a `QAudioSource(QMediaDevices.defaultAudioInput(), fmt)`, starts it (`self._io = source.start()`), reads `self._io.readAll()` on a 250 ms `QTimer` into a `bytearray`, drives a `Chunker` with `time.monotonic()` and `get_page()`, and on every `Chunk` writes `wav_bytes(buffer)` to `chunk_path(...)` then hands it to the `Uploader`; `stop()` closes the last chunk and stops the source; `on_status(elapsed_s, queued)` fires each tick. Every Qt call in `try/except` with a `[klausmate]` line; a missing input device → `start()` returns False with one log line.

- [ ] **Step 4: Run to verify it passes.** → `0 failed`; compile through the symlink.

- [ ] **Step 5: Mutate once.** Make `page_changed` not close the open chunk → the straddle pin fails; restore. Board comment; card stays in Doing.

---

### Task 5: Record buttons and the wiring

**Files:**
- Modify: `klausmate/__init__.py` (`_PanelBar.record_btn` "●"/"■", `PdfDock._toggle_record`, status text in the bar), `klausmate/lecture_view.py` (the same button on the Lecture dock's header), `klausmate/__init__.py` (module-level `_uploader` created at profile open, `requeue_leftovers` for the PDF when Record starts, stopped at profile close; stopping a recording calls `index_queue.request_pdf(name)`)
- Test: `tests/test_pdf_dock.py` (offscreen: the button exists, disabled with no PDF in view, toggles text, the recorder's `start` is called with the current page getter), `tests/test_lecture_view.py`

**Interfaces:**
- Consumes: `lecture_recorder.Recorder/Uploader` (Task 4), `viewer_context.current()`, `index_queue.request_pdf`.
- Produces: `PdfDock.record_btn`, `PdfDock._recorder`, `__init__.uploader() -> Uploader`.

- [ ] **Step 1: Write the failing pins** in `tests/test_pdf_dock.py`'s real-Qt section: `bar.record_btn` is a `QToolButton` with text "●" and tooltip naming a lecture; with no document loaded it is disabled; after `sb.load_pdf("lec.pdf")` it is enabled; clicking it constructs a recorder through a patched `K.lecture_recorder.Recorder` fake (record the `get_page` callable and call it → the sidebar's `_current_page`), the text becomes "■", clicking again calls `stop()` and `K.index_queue.request_pdf` (patched) with the PDF name.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** The button after `add_btn` on the bar; `PdfDock._toggle_record()`:

```python
    @_guarded
    def _toggle_record(self, *_args) -> None:
        from . import lecture_recorder, index_queue, viewer_context
        if self._recorder is not None and self._recorder.is_recording:
            name = self._recorder.pdf_name
            self._recorder.stop(); self._recorder = None
            self._bar.set_recording(False, "")
            index_queue.request_pdf(name)
            return
        name = getattr(self._sidebar, "_name", None)
        path = pdf_handler.pdf_path_for(USER_FILES, pdf_handler._safe_basename(name)) if name else None
        if not name or not path:
            tooltip("Open a PDF first"); return
        rec = lecture_recorder.Recorder(USER_FILES, pdf_handler._safe_basename(name), path,
                                        get_page=lambda: int(getattr(self._sidebar, "_current_page", 0)) + 1,
                                        on_status=lambda s, q: self._bar.set_recording(True, f"{int(s)//60}:{int(s)%60:02d} · {q} to transcribe"),
                                        uploader=uploader())
        rec.pdf_name = name
        uploader().requeue_leftovers(pdf_handler._safe_basename(name), path)
        if rec.start():
            self._recorder = rec; self._bar.set_recording(True, "0:00")
        else:
            tooltip("No microphone available")
```

`_PanelBar.set_recording(on, status)` flips the glyph and a small status `QLabel` beside the page label (theme tokens). The same button and slot on `LectureDock` reuse the module-level helper `start_or_stop_recording(sidebar, bar)` factored into `lecture_recorder`'s glue so both surfaces share one implementation. `uploader()` in `__init__.py` is a lazy singleton created with `get_config`, stopped in `profile_will_close`.

- [ ] **Step 4: Run to verify it passes.** `tests/test_pdf_dock.py`, `tests/test_lecture_view.py` → `0 failed`; compile.

- [ ] **Step 5: Mutate once.** Skip `requeue_leftovers` on start → its pin fails; restore. Board comment; card stays in Doing.

---

### Task 6: The transcript strip in both viewers

**Files:**
- Modify: `klausmate/theme.py` (`transcript_strip_qss(night) -> str`, tokens only), `klausmate/pdf_viewer.py` (`PdfSidebar._transcript` strip under the page: a collapsible `QLabel` in a `QScrollArea`, max height 120 px, toggled by a "Transcript" chevron; refreshed from `page_store.load_record` on `_on_page_changed` and on `page_store.subscribe` for the sidebar's PDF), `klausmate/pdfjs_viewer.py` + `klausmate/web/pdfjs_viewer.html` (the same strip inside the page: Python pushes `klausSetTranscript(page_index, text)` over the existing bridge; the HTML renders it under `#pages`' current page container, collapsible)
- Test: `tests/test_theme.py` (the builder emits tokens only), `tests/test_drive.py` (offscreen: after `append_segment` the strip shows the text for the current page and hides on an empty record), `tests/test_pdfjs_viewer.py` (the JS bridge function exists and the Python side calls it on page change)

**Interfaces:**
- Consumes: `page_store.load_record/combined_text/subscribe` (Plan 1), `viewer_context` (existing).
- Produces: `theme.transcript_strip_qss(night)`; `PdfSidebar.set_transcript(page_index, text)`; the bridge call name `klausSetTranscript`.

- [ ] **Step 1: Write the failing pins.** `tests/test_theme.py`: `transcript_strip_qss(True)` contains `c["chrome"]` and `c["text_muted"]` and no literal hex outside the palette (the file's existing audit loop admits the new builder). `tests/test_drive.py` offscreen: build a `PdfSidebar` with the native renderer over a scratch PDF, `page_store.append_segment(...)` for page 0, then `sb.set_transcript(0, text)` → the strip is visible and its label text equals the text; `set_transcript(1, "")` → hidden. `tests/test_pdfjs_viewer.py`: `web/pdfjs_viewer.html` defines `window.klausSetTranscript` and `pdfjs_viewer.py` evaluates `klausSetTranscript(` on page change.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** `theme.transcript_strip_qss` (a `QWidget#KlausTranscriptStrip` on `chrome`, `QLabel` in `text_muted`, 12 px, a `grey_light` hairline top). `PdfSidebar`: build the strip once (hidden), `set_transcript(page_index, text)` sets the label and visibility; `_on_page_changed` calls `_refresh_transcript()` which reads `page_store.load_record(USER_FILES, safe, path, page)` and joins the segments' text (the transcript only, not the slide text); subscribe in `__init__`, unsubscribe in `cleanup()`. pdf.js: `klausSetTranscript(pageIndex, text)` fills a `<div class="klaus-transcript">` appended to that page's container, hidden when empty; the same `_refresh_transcript` on the Python side evaluates it through the existing `eval`/bridge helper the viewer uses for `klausSetAnnotations`.

- [ ] **Step 4: Run to verify it passes.** `tests/test_theme.py`, `tests/test_drive.py`, `tests/test_pdfjs_viewer.py` → `0 failed`; compile.

- [ ] **Step 5: Mutate once.** Make `set_transcript` ignore the empty case → the hidden pin fails; restore. Board comment; card stays in Doing.

---

### Task 7: Docs and integration (needs-human)

- [ ] **Step 1:** CLAUDE.md gains entries for `pertinence.py` and `lecture_recorder.py` (one paragraph each: the strict forced tool and "unjudged is never doubtful"; the 30-second page-stamped chunk and "a failed upload keeps its WAV"); the `tag_sync.py` entry names the Doubtful tag as a reserved leaf; `retention.py`'s entry says confirmed-only; `index_queue.py`'s entry names phase four and the Judge/Skip prompt; AGENTS.md's network paragraph adds transcription and pertinence; `config.md` documents `transcription_model` and `reasoning_model`'s two uses.
- [ ] **Step 2:** Full loop; `scripts/mutation_audit.py --modules pertinence,lecture_recorder` (add both to `AUDIT_MODULES`).
- [ ] **Step 3:** Paid smokes behind `KLAUS_LIVE_API=1` and the env keys `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`: one `judge` batch of two cards against one page (report both verdicts and the reasons); one `transcribe` of a generated 5-second WAV containing silence (expect empty). SKIP honestly without the keys.
- [ ] **Step 4:** The live checklist on the card: restart Anki; open a lecture in Browse's dock; press ● Record, speak for 60 s while turning pages every 15 s; press ■ → the transcript strip under each page you spoke on shows what you said, on the right page; the index runs; the Judge/Skip prompt shows an estimate; Judge → the Library row shows "n · m doubtful"; right-click → Doubtful cards… opens Browse on the Doubtful tag; ask the assistant about a page you spoke on → it quotes the transcript.

## Self-review

**Spec coverage.** D4: Tasks 1, 3. D5: Task 2. D6: Tasks 4, 5, 6. Docs: Task 7. Testing list: strict parser and staleness (Task 1), Doubtful membership and confirmed counts (Task 2), the Chunker state machine (Task 4), offscreen Record and strip (Tasks 5, 6), paid smokes behind the flag (Task 7).

**Placeholders.** The `Uploader` sketch names every method and its behaviour; `_ensure_thread` is the one line `threading.Thread(target=self._loop, daemon=True).start()` guarded by `self._thread is None`.

**Type consistency.** `Chunk.page` is 1-based everywhere; `append_segment` takes the 0-based `page_index`, hence `chunk.page - 1` in the uploader; `pertinence.PageText.page` is 1-based and `page_rows` is keyed 1-based from `page_texts`; `retention.load_matches_pages` and `card_index.note_texts_for` are introduced in Task 3 and named nowhere else.
