# Agent Board

A kanban board that several agent sessions can share safely.

Running two or three Claude sessions on one repository goes wrong in a
predictable way: they edit the same files, overwrite each other, and neither
notices. This is the coordination layer that stops that. It has been in daily
use on a real multi-session project.

**`BOARD.md` is the only shared state, and `board.py` is the only thing that
writes to it.** Every mutation goes through a lockfile, so concurrent sessions
serialize instead of clobbering each other.

Two mechanisms do the real work:

- **File-disjointness on claim.** A card declares the files it will touch.
  Claiming is refused if another card in Doing already holds any of them, so
  two workers can never be handed the same file.
- **A verify gate per card.** Each card carries a `verify:` command that must
  **fail before** the work and **pass after**. A gate that already passes
  proves nothing.

## Install

Copy this `agent-board/` directory into `.claude/skills/` in any project.
Claude picks it up from there; the scripts run straight from where they sit.

## Quickstart

```bash
python3 .claude/skills/agent-board/scripts/board.py init
```

That writes `./board/BOARD.md` and drops `ROLES.md` beside it, in your
project — never inside this skill folder. Read `ROLES.md`: it defines the columns,
the gates between them, and the grooming rules, and it is the half that makes
the CLI safe.

```bash
board.py add --title "Parser rejects empty input" \
             --files "src/parser.py" \
             --verify "python3 -m pytest tests/test_parser.py"
board.py move  T-001 Ready
board.py claim T-001 --owner alice     # refused if a Doing card holds that file
board.py list
```

Run `board.py --help`, or `board.py <command> --help`, for the rest.

## Dashboard

```bash
python3 .claude/skills/agent-board/scripts/serve.py --port 8766
```

Bound to `127.0.0.1` only, with no auth, because it is not reachable off-host.
It mutates through the same lockfile as the CLI, so the browser cannot make a
move a worker could not.

To open it in Claude Code's preview pane, add to `.claude/launch.json`:

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "board-dashboard", "url": "http://localhost:8766" }
  ]
}
```

Start the server yourself first — this config attaches to a running server
rather than launching one.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BOARD_DIR` | `./board/`, or an existing board found at `./board/` or `./` | where `BOARD.md` and `ARCHIVE.md` live. Resolved against the current project, never against this skill's own directory |
| `BOARD_PREFIX` | `T` | card-id prefix, giving `T-001` |

New ids are minted with `BOARD_PREFIX`, but the board is read with a pattern
that accepts any prefix — changing it mid-project will not orphan existing
cards.

## Tests

```bash
python3 tests/test_board.py
```

68 checks, including concurrent claims, lock timeouts, and stale-lock
breaking. They run against a temporary directory and never touch a real
`BOARD.md`.

## Requirements

Python 3 standard library only. No dependencies, no network access.

## License

MIT — see `LICENSE` in this directory. Licensed separately from the
AGPL v3 covering the `klaus_note/` add-on in the containing repository.
