---
name: agent-board
description: Use when two or more agent sessions work on one repository at the same time - parallel workers, an orchestrator handing out tasks, or any setup where sessions could edit the same files, overwrite each other, or lose track of who is doing what.
---

# Agent Board

## Overview

A kanban board that several agent sessions can share safely.

**Core principle: `BOARD.md` is the only shared state, and `board.py` is the
only thing that writes to it.** Every mutation goes through a lockfile, so
concurrent sessions serialize instead of clobbering each other.

Two mechanisms do the real work:

- **File-disjointness on claim.** A card declares the files it will touch.
  Claiming is refused if any of them are already claimed by a card in Doing.
  Two workers can never be handed the same file.
- **A verify gate per card.** Each card carries a `verify:` command that must
  **fail before** the work and **pass after**. A gate that passes before the
  work has started is not a gate.

## Setup

```bash
python3 scripts/board.py init      # writes BOARD.md + ROLES.md if absent
```

That creates `./board/BOARD.md` and drops `ROLES.md` beside it, **in the
current project** — never inside this skill folder, which may be installed
somewhere shared, outside any one project.

`BOARD_DIR` overrides the location; otherwise an existing `./board/BOARD.md`
or `./BOARD.md` is found, and `./board/` is the default. `BOARD_PREFIX` sets
the card-id prefix (default `T`, giving `T-001`). Read `ROLES.md` next to the
board — it defines the columns, the gates between them, and the grooming
rules.

## Quick Reference

| Command | Does |
|---|---|
| `board.py list` | the whole board |
| `board.py show <id>` | one card in full |
| `board.py add --title … --files … --verify …` | create a card |
| `board.py claim <id> --owner <name>` | Ready → Doing, enforcing disjointness |
| `board.py move <id> <column>` | move between columns |
| `board.py comment <id> --author … --text …` | append a comment |
| `board.py release <id>` | abandon a claim, Doing → Ready |
| `board.py archive <id>` | Done card → ARCHIVE.md |
| `board.py check-disjoint` | verify Ready cards do not overlap |

Run `board.py <command> --help` for flags.

The live dashboard is `python3 scripts/serve.py --port 8766`, bound to
127.0.0.1. It mutates through the same lockfile as the CLI, so a browser
cannot make a move a worker could not.

## NEVER hand-edit BOARD.md to change state

Editing the markdown directly is easy, looks harmless, and **will eventually
lose somebody's write** — another session holds the file between your read and
your save, and the last writer wins silently. Nothing warns you.

Use `board.py` for every claim, move, comment, and status change.

The single exception: a card's **body prose** may be edited by hand, by the
orchestrator or designer. Never its column, owner, or fields.

| Rationalization | Reality |
|---|---|
| "It's a one-line change" | One line is exactly the size of a lost write. |
| "I'm the only session running" | You cannot see the others from here. Sessions start without telling you. |
| "The CLI doesn't support this field" | Then the field is not board state. Use `comment`, or add the command. |
| "I'll edit and then run the CLI to sync" | There is nothing to sync to. The file IS the state. |
| "It's faster than shelling out" | It is faster until it silently drops a card. |
| "The board is stuck, I'll fix the file" | See "Handling a stuck board" in ROLES.md. |

## Red Flags — stop

- Reaching for Edit/Write on `BOARD.md`
- Moving a card by rewriting a `## Column` heading
- Claiming a card without declaring its files
- Writing a `verify:` you have not watched fail
- `grep -q "phrase"` as a gate for removing that phrase — it passes when the
  phrase is *present*, so it is exactly backwards as a check that it is gone

## Common Mistakes

**A gate that never failed.** Run the `verify:` command before starting. If it
passes, the gate proves nothing about your work.

**Overlapping Ready cards.** Disjointness is enforced on *claim*, not on
create. Run `check-disjoint` after grooming, or workers collide at claim time.

**Disjointness is not isolation.** It protects writes, not gates: a worker
editing a module the test suite imports breaks *every* concurrent card's
verify command. Run such cards alone.

**A card too large to slice.** A card naming a 6,000-line file blocks every
other card touching it. Split along real seams before moving it to Ready.
