#!/usr/bin/env python3
"""Board CLI — the only sanctioned way to change card state.

Exit codes are part of the contract agents rely on:

    0   success
    1   validation or contention rejection (reason on stderr)
    2   could not acquire the board lock

A worker that gets 1 from `claim` should pick a different card. A worker
that gets 2 should wait and retry, then stop and report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boardlib as B


def _print_card(card: B.Card, column: str) -> None:
    print("%s  [%s]  %s" % (card.id, column, card.title))
    for key in B.FIELD_ORDER:
        if key in card.fields:
            print("  %-9s %s" % (key + ":", card.fields[key]))
    if card.body:
        print()
        for line in card.body.split("\n"):
            print("  " + line)
    if card.comments:
        print("\n  comments:")
        for c in card.comments:
            print("    - " + c)


def cmd_add(args) -> int:
    fields = {
        "priority": args.priority,
        "tags": args.tags,
        "files": args.files,
        "verify": args.verify,
    }
    card = B.mutate(lambda b: B.add(b, args.col, args.title, fields, args.body or ""))
    print(card.id)
    return 0


def cmd_claim(args) -> int:
    card = B.mutate(lambda b: B.claim(b, args.id, args.owner))
    print("claimed %s -> Doing (owner %s)" % (card.id, args.owner))
    return 0


def cmd_move(args) -> int:
    card = B.mutate(lambda b: B.move(b, args.id, args.column, args.force))
    print("moved %s -> %s" % (card.id, args.column))
    return 0


def cmd_release(args) -> int:
    card = B.mutate(lambda b: B.release(b, args.id))
    print("released %s -> Ready" % card.id)
    return 0


def cmd_comment(args) -> int:
    B.mutate(lambda b: B.comment(b, args.id, args.author, args.text))
    print("commented on %s" % args.id)
    return 0


def cmd_edit(args) -> int:
    fields = {k: v for k, v in
              (("priority", args.priority), ("tags", args.tags),
               ("files", args.files), ("verify", args.verify)) if v is not None}
    B.mutate(lambda b: B.edit(b, args.id, args.title, fields, args.body))
    print("edited %s" % args.id)
    return 0


def cmd_delete(args) -> int:
    card = B.mutate(lambda b: B.delete(b, args.id))
    print("deleted %s (%s)" % (card.id, card.title))
    return 0


def cmd_archive(args) -> int:
    if args.all_done:
        cards = B.mutate(lambda b: B.archive_all_done(b))
        if not cards:
            print("no Done cards to archive")
        else:
            for card in cards:
                print("archived %s (%s)" % (card.id, card.title))
        return 0
    if not args.id:
        print("board.py: archive requires an id or --all-done", file=sys.stderr)
        return 1
    card = B.mutate(lambda b: B.archive(b, args.id))
    print("archived %s (%s)" % (card.id, card.title))
    return 0


def cmd_list(args) -> int:
    board = B.load()
    if args.json:
        print(json.dumps(B.to_dict(board), indent=2))
        return 0
    cols = [args.col] if args.col else B.COLUMNS
    for col in cols:
        cards = board.columns[col]
        print("## %s (%d)" % (col, len(cards)))
        for c in cards:
            owner = c.fields.get("owner", "-")
            tags = ",".join(c.tag_list())
            suffix = "  [%s]" % tags if tags else ""
            who = "  @%s" % owner if owner not in ("", "-") else ""
            print("  %s  %s%s%s" % (c.id, c.title, who, suffix))
        print()
    return 0


def cmd_show(args) -> int:
    board = B.load()
    col, card = board.find(args.id)
    if card is None:
        print("no such card: %s" % args.id, file=sys.stderr)
        return 1
    _print_card(card, col)
    return 0


def cmd_check_disjoint(args) -> int:
    board = B.load()
    hits = B.check_disjoint(board)
    if not hits:
        print("Ready+Doing cards are file-disjoint ✓")
        return 0
    print("file overlaps (workers could collide):", file=sys.stderr)
    for a, b, path in hits:
        print("  %s <-> %s  on  %s" % (a, b, path), file=sys.stderr)
    return 1



def cmd_init(args) -> int:
    """Create BOARD.md and drop ROLES.md beside it.

    Ships as its own command because a board is useless to a new project
    until the roles/columns/gates document is actually THERE: the protocol
    is the half that makes the CLI safe, and a copy step buried in a README
    is a copy step somebody skips.
    """
    os.makedirs(B.board_dir(), exist_ok=True)
    board_path = B.board_path()
    created = []
    if not os.path.exists(board_path):
        B.mutate(lambda board: None)          # writes the header + columns
        created.append(os.path.basename(board_path))
    # The skill ships templates/ beside scripts/; this live copy sits in
    # board/, so it reads them out of the vendored skill instead.
    here = os.path.dirname(os.path.abspath(__file__))
    roles_src = next((p for p in (
        os.path.join(here, "..", "templates", "ROLES.md"),
        os.path.join(here, "..", ".claude", "skills", "agent-board",
                     "templates", "ROLES.md"),
    ) if os.path.exists(p)), None)
    roles_dst = os.path.join(B.board_dir(), "ROLES.md")
    if roles_src is None and not os.path.exists(roles_dst):
        print("warning: no ROLES.md template found; not installed",
              file=sys.stderr)
    elif roles_src and not os.path.exists(roles_dst):
        with open(roles_src, encoding="utf-8") as fh:
            text = fh.read()
        with open(roles_dst, "w", encoding="utf-8") as fh:
            fh.write(text)
        created.append("ROLES.md")
    if created:
        print("created: %s (in %s)" % (", ".join(created), B.board_dir()))
    else:
        print("already initialised in %s" % B.board_dir())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="board.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="create a card")
    a.add_argument("--col", default="Backlog", choices=B.COLUMNS)
    a.add_argument("--title", required=True)
    a.add_argument("--files", help="comma-separated paths this task touches")
    a.add_argument("--priority", default="P2")
    a.add_argument("--tags", help="comma-separated, e.g. sonnet-safe,design")
    a.add_argument("--verify", help="command that proves the card is done")
    a.add_argument("--body", help="brief / acceptance criteria")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("claim", help="take a Ready card (Ready->Doing)")
    c.add_argument("id")
    c.add_argument("--owner", required=True)
    c.set_defaults(func=cmd_claim)

    m = sub.add_parser("move", help="move a card between columns")
    m.add_argument("id")
    m.add_argument("column", choices=B.COLUMNS)
    m.add_argument("--force", action="store_true", help="skip transition check")
    m.set_defaults(func=cmd_move)

    r = sub.add_parser("release", help="abandon a claim (Doing->Ready)")
    r.add_argument("id")
    r.set_defaults(func=cmd_release)

    cm = sub.add_parser("comment", help="append a comment")
    cm.add_argument("id")
    cm.add_argument("--author", required=True)
    cm.add_argument("--text", required=True)
    cm.set_defaults(func=cmd_comment)

    e = sub.add_parser("edit", help="change title/fields/body")
    e.add_argument("id")
    e.add_argument("--title")
    e.add_argument("--files")
    e.add_argument("--priority")
    e.add_argument("--tags")
    e.add_argument("--verify")
    e.add_argument("--body")
    e.set_defaults(func=cmd_edit)

    dl = sub.add_parser("delete", help="remove a card (not while in flight)")
    dl.add_argument("id")
    dl.set_defaults(func=cmd_delete)

    ar = sub.add_parser("archive", help="move a Done card's record to ARCHIVE.md")
    ar.add_argument("id", nargs="?")
    ar.add_argument("--all-done", action="store_true", help="archive every Done card")
    ar.set_defaults(func=cmd_archive)

    ls = sub.add_parser("list", help="show the board")
    ls.add_argument("--col", choices=B.COLUMNS)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="show one card in full")
    sh.add_argument("id")
    sh.set_defaults(func=cmd_show)

    cd = sub.add_parser("check-disjoint", help="report file collisions")
    cd.set_defaults(func=cmd_check_disjoint)

    i = sub.add_parser("init", help="create BOARD.md + ROLES.md")
    i.set_defaults(func=cmd_init)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except B.LockTimeout as exc:
        print("board.py: %s" % exc, file=sys.stderr)
        return 2
    except B.BoardError as exc:
        print("board.py: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
