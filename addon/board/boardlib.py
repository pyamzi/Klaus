"""Kanban board over a single markdown file — parse, mutate, serialize.

BOARD.md is the source of truth. Both the CLI (board.py) and the dashboard
(serve.py) mutate it exclusively through `mutate()`, which holds an
exclusive lockfile for the whole read-modify-write cycle. Reading *inside*
the lock is what makes concurrent claims safe: two workers racing for the
same card cannot both observe it as unclaimed.

Design notes:

- One file, not one file per card. With a single write path, one lock plus
  one atomic ``os.replace`` covers every mutation; per-card files would
  need a lock *and* an index rebuild — two write sites and a partial-failure
  state between them. Column membership is just position in this file, so a
  move is a text transform and ``git diff`` is the audit log.
- Fields are hand-parsed ``key: value`` lines, not YAML: python 3.9's stdlib
  has no YAML parser and this project allows no third-party dependencies.
- Card body text is preserved byte-for-byte through a round trip. Agents and
  humans write prose there; the serializer must never eat it.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from dataclasses import dataclass, field

COLUMNS = ["Backlog", "Ready", "Doing", "Review", "Done"]

# Ready→Doing is deliberately absent: it is reachable only via claim(),
# which additionally enforces file-disjointness against in-flight work.
TRANSITIONS = {
    ("Backlog", "Ready"),
    ("Ready", "Backlog"),
    ("Doing", "Review"),
    ("Doing", "Ready"),      # release
    ("Review", "Done"),
    ("Review", "Doing"),     # rework
    ("Done", "Backlog"),     # reopen
}

FIELD_ORDER = ["owner", "priority", "tags", "files", "verify", "created", "claimed"]

_CARD_RE = re.compile(r"^### (K-\d{3}): (.+)$")
_FIELD_RE = re.compile(r"^([a-z_]+): ?(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 120.0

BOARD_HEADER = """# klausmate board

<!-- Source of truth for all agent work. State changes (claim/move/comment)
     MUST go through board/board.py so they are serialized by its lockfile.
     Direct edits to this file: card *body* prose only, by the orchestrator
     or designer. See context/ROLES.md. -->
"""


class BoardError(Exception):
    """Validation or contention failure. CLI maps this to exit code 1."""


class LockTimeout(BoardError):
    """Could not acquire the board lock. CLI maps this to exit code 2."""


@dataclass
class Card:
    id: str
    title: str
    fields: dict = field(default_factory=dict)
    body: str = ""           # free prose, preserved verbatim
    comments: list = field(default_factory=list)

    def file_list(self) -> list:
        raw = self.fields.get("files", "")
        return [p.strip() for p in raw.split(",") if p.strip()]

    def tag_list(self) -> list:
        raw = self.fields.get("tags", "")
        return [t.strip() for t in raw.split(",") if t.strip()]


@dataclass
class Board:
    columns: dict = field(default_factory=lambda: {c: [] for c in COLUMNS})
    preamble: str = BOARD_HEADER

    def all_cards(self):
        for col in COLUMNS:
            for card in self.columns[col]:
                yield col, card

    def find(self, card_id: str):
        for col, card in self.all_cards():
            if card.id == card_id:
                return col, card
        return None, None

    def next_id(self) -> str:
        nums = [int(c.id[2:]) for _col, c in self.all_cards()]
        return "K-%03d" % ((max(nums) + 1) if nums else 1)


# ------------------------------------------------------------------ paths


def board_dir() -> str:
    """Overridable so tests can operate on a scratch board."""
    return os.environ.get(
        "KLAUS_BOARD_DIR", os.path.dirname(os.path.abspath(__file__))
    )


def board_path() -> str:
    return os.path.join(board_dir(), "BOARD.md")


def lock_path() -> str:
    return os.path.join(board_dir(), ".lock")


# ----------------------------------------------------------------- parsing


def parse(text: str) -> Board:
    board = Board(columns={c: [] for c in COLUMNS})
    lines = text.split("\n")

    preamble: list = []
    col: str | None = None
    card: Card | None = None
    body: list = []
    in_comments = False
    in_fence = False

    def flush_card() -> None:
        # Trailing blank lines are layout, not content; strip them so a
        # round trip is stable, and re-add exactly one on serialize.
        if card is not None:
            card.body = "\n".join(body).strip("\n")
            board.columns[col].append(card)

    for line in lines:
        # Fence tracking must come first: a "### " inside a fenced code block
        # is sample text, not a card heading.
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            if card is not None:
                body.append(line)
                continue

        if not in_fence:
            if line.startswith("## ") and line[3:].strip() in COLUMNS:
                flush_card()
                card, body, in_comments = None, [], False
                col = line[3:].strip()
                continue

            m = _CARD_RE.match(line)
            if m and col is not None:
                flush_card()
                card = Card(id=m.group(1), title=m.group(2).strip())
                body, in_comments = [], False
                continue

            if card is not None and line.strip() == "#### Comments":
                in_comments = True
                continue

            if card is not None and in_comments:
                if line.strip().startswith("- "):
                    card.comments.append(line.strip()[2:])
                continue

            if card is not None and not body and not in_comments:
                fm = _FIELD_RE.match(line)
                if fm:
                    card.fields[fm.group(1)] = fm.group(2).strip()
                    continue

        if card is not None:
            body.append(line)
        elif col is None:
            preamble.append(line)

    flush_card()
    if preamble:
        board.preamble = "\n".join(preamble).strip("\n") + "\n"
    return board


def serialize(board: Board) -> str:
    out = [board.preamble.rstrip("\n"), ""]
    for col in COLUMNS:
        out.append("## " + col)
        for card in board.columns[col]:
            out.append("")
            out.append("### %s: %s" % (card.id, card.title))
            for key in FIELD_ORDER:
                if key in card.fields:
                    out.append("%s: %s" % (key, card.fields[key]))
            for key in sorted(k for k in card.fields if k not in FIELD_ORDER):
                out.append("%s: %s" % (key, card.fields[key]))
            if card.body:
                out.append("")
                out.append(card.body)
            if card.comments:
                out.append("")
                out.append("#### Comments")
                for c in card.comments:
                    out.append("- " + c)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


# ------------------------------------------------------------------- lock


class Lock:
    """Exclusive board lock via O_EXCL, with a dead-owner escape hatch.

    A crashed worker must not wedge the board forever, but breaking a lock
    that is merely slow would corrupt a live write. So a lock is only broken
    when it is BOTH older than LOCK_STALE_S and owned by a pid that no
    longer exists.
    """

    def __init__(self, timeout: float | None = None) -> None:
        # Read the module global at call time, not as a default argument —
        # a default would bind at import and make the timeout untunable.
        self.timeout = LOCK_TIMEOUT_S if timeout is None else timeout
        self.path = lock_path()
        self.fd: int | None = None

    def _owner_is_dead(self) -> bool:
        try:
            with open(self.path, encoding="utf-8") as f:
                info = json.load(f)
            pid = int(info["pid"])
            if info.get("host") != socket.gethostname():
                return False  # different machine; cannot probe, do not break
        except (OSError, ValueError, KeyError, TypeError):
            return True  # unreadable lock is not a live one
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False  # exists, owned by another user
        return False

    def __enter__(self) -> "Lock":
        os.makedirs(board_dir(), exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(
                    self.fd,
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "host": socket.gethostname(),
                            "ts": time.time(),
                        }
                    ).encode("utf-8"),
                )
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_S and self._owner_is_dead():
                    try:
                        os.unlink(self.path)
                        continue
                    except OSError:
                        pass
                if time.time() >= deadline:
                    raise LockTimeout(
                        "board is locked by another process (waited %.0fs); "
                        "if it crashed, the lock self-clears after %ds"
                        % (self.timeout, LOCK_STALE_S)
                    )
                time.sleep(0.1)

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


def load() -> Board:
    try:
        with open(board_path(), encoding="utf-8") as f:
            return parse(f.read())
    except FileNotFoundError:
        return Board(columns={c: [] for c in COLUMNS})


def _write(board: Board) -> None:
    path = board_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(serialize(board))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def mutate(fn):
    """Run fn(board) under the lock; persist atomically. Returns fn's result.

    The read happens inside the lock — that is the whole point. A caller that
    parsed the board before acquiring could overwrite a concurrent change.
    """
    with Lock():
        board = load()
        result = fn(board)
        _write(board)
        return result


# -------------------------------------------------------------- operations


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _require(board: Board, card_id: str):
    col, card = board.find(card_id)
    if card is None:
        raise BoardError("no such card: %s" % card_id)
    return col, card


def _norm(path: str) -> str:
    return path.strip().strip("/")


def _paths_conflict(a: str, b: str) -> bool:
    """True when two declared paths could touch the same file.

    Directory-aware: 'klausmate/' conflicts with 'klausmate/pdf_viewer.py'.
    """
    a, b = _norm(a), _norm(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def overlaps(board: Board, card: Card, columns=("Doing",)):
    """[(other_id, path)] where card's files collide with cards in columns."""
    hits = []
    mine = card.file_list()
    for col in columns:
        for other in board.columns[col]:
            if other.id == card.id:
                continue
            for p in mine:
                for q in other.file_list():
                    if _paths_conflict(p, q):
                        hits.append((other.id, p))
    return hits


def add(board: Board, column: str, title: str, fields: dict | None = None,
        body: str = "") -> Card:
    if column not in COLUMNS:
        raise BoardError("unknown column: %s" % column)
    card = Card(id=board.next_id(), title=title.strip(), body=body)
    card.fields = {"owner": "-", "created": _today()}
    card.fields.update({k: v for k, v in (fields or {}).items() if v})
    board.columns[column].append(card)
    return card


def move(board: Board, card_id: str, to: str, force: bool = False) -> Card:
    if to not in COLUMNS:
        raise BoardError("unknown column: %s" % to)
    frm, card = _require(board, card_id)
    if frm == to:
        return card
    if not force and (frm, to) not in TRANSITIONS:
        extra = " (use `claim` to take a Ready card)" if (frm, to) == ("Ready", "Doing") else ""
        raise BoardError("illegal transition %s -> %s%s" % (frm, to, extra))
    board.columns[frm].remove(card)
    board.columns[to].append(card)
    return card


def claim(board: Board, card_id: str, owner: str) -> Card:
    col, card = _require(board, card_id)
    if col != "Ready":
        raise BoardError("card %s is in %s, not Ready" % (card_id, col))
    current = card.fields.get("owner", "-")
    if current not in ("", "-"):
        raise BoardError("card %s already owned by %s" % (card_id, current))
    conflicts = overlaps(board, card)
    if conflicts:
        detail = ", ".join("%s (%s)" % (cid, p) for cid, p in conflicts)
        raise BoardError(
            "card %s touches files already in flight: %s" % (card_id, detail)
        )
    card.fields["owner"] = owner
    card.fields["claimed"] = _today()
    board.columns["Ready"].remove(card)
    board.columns["Doing"].append(card)
    return card


def release(board: Board, card_id: str) -> Card:
    col, card = _require(board, card_id)
    if col != "Doing":
        raise BoardError("card %s is in %s, not Doing" % (card_id, col))
    card.fields["owner"] = "-"
    card.fields.pop("claimed", None)
    board.columns["Doing"].remove(card)
    board.columns["Ready"].append(card)
    return card


def comment(board: Board, card_id: str, author: str, text: str) -> Card:
    _col, card = _require(board, card_id)
    one_line = " ".join(text.split())
    card.comments.append("[%s %s] %s" % (_today(), author, one_line))
    return card


def edit(board: Board, card_id: str, title=None, fields=None, body=None) -> Card:
    _col, card = _require(board, card_id)
    if title:
        card.title = title.strip()
    if fields:
        card.fields.update({k: v for k, v in fields.items() if v is not None})
    if body is not None:
        card.body = body
    return card


def delete(board: Board, card_id: str) -> Card:
    col, card = _require(board, card_id)
    if col == "Doing":
        raise BoardError(
            "card %s is in flight (owner %s) — release it first"
            % (card_id, card.fields.get("owner", "?"))
        )
    board.columns[col].remove(card)
    return card


def check_disjoint(board: Board):
    """[(id_a, id_b, path)] for claimable work that would collide."""
    out = []
    cards = [c for col in ("Ready", "Doing") for c in board.columns[col]]
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            for p in a.file_list():
                for q in b.file_list():
                    if _paths_conflict(p, q):
                        out.append((a.id, b.id, p))
    return out


def to_dict(board: Board) -> dict:
    return {
        "columns": [
            {
                "name": col,
                "cards": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "owner": c.fields.get("owner", "-"),
                        "priority": c.fields.get("priority", ""),
                        "tags": c.tag_list(),
                        "files": c.file_list(),
                        "verify": c.fields.get("verify", ""),
                        "body": c.body,
                        "comments": c.comments,
                    }
                    for c in board.columns[col]
                ],
            }
            for col in COLUMNS
        ]
    }
