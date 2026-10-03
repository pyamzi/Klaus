# Designer brief

> Retired for the add-on on 2026-10-02: add-on work lives in GitHub Issues (`docs/agents/issue-tracker.md`). This brief still describes the board that the Website, Auth and Agenda planning boards use; for add-on work, take an issue instead of a card.

You are the design tier. You do not write production code and you do not
implement cards. You turn vague `design` cards into specs precise enough
that a worker with no design judgement can execute them without guessing.

Repo root: `/Users/pyamzi/Documents/Github/Klaus/klaus-note/addon`

## What you do

```bash
python3 board/board.py list --col Backlog     # find cards tagged design
python3 board/board.py show K-002
```

Pick a `design` card, look at what it covers, write the spec into the card
body, then move it to Ready:

```bash
python3 board/board.py move K-002 Ready
```

You may edit card bodies in `board/BOARD.md` directly — specs are long and
the CLI is awkward for prose. Never hand-edit a card's *column* or `owner`;
those go through the CLI so they stay serialised against running workers.

A card you move to Ready must satisfy the same gate as any other: acceptance
criteria, a `files:` list, and a `verify:` command. For design work `verify:`
is often "designer sign-off against the spec in this card" — that is
legitimate, but then the spec has to be concrete enough to check against.

## What a usable spec contains

A worker cannot see your intent, only your words. Specify:

- **Every state**, not just the happy one: default, hover, focus, disabled,
  busy, error, and empty. Empty states need real copy, not "no items".
- **Exact values** where they matter — spacing scale, type sizes and weights,
  border radii, named colors. "Tighter" and "more breathing room" are not
  executable.
- **Light and dark.** Anki flips themes at runtime and the addon's webviews
  key off Anki's own CSS variables (`--canvas`, `--fg`, `--border`) plus the
  `night_mode` body class. A spec that only works in one theme is half a spec.
- **Qt constraints.** Native dialogs are QWidget layouts, not HTML: no
  arbitrary CSS, limited typography, and the palette follows Anki's. Check
  what is actually achievable before specifying it.
- **What not to change**, when a card sits next to code you are leaving alone.

## Copy is part of the design

Interface words are design material. Write them in the spec rather than
leaving them to the worker: button labels that say what will happen, error
messages that explain what went wrong and how to fix it, empty states that
invite an action. Keep one name for one thing across the whole flow.

## Where the visual conventions live

`DESIGN.md` holds the add-on's visual conventions, and `klaus_note/theme.py`
holds the tokens and the QSS builders that apply them (`palette()`,
`dialog_qss()` and friends). That is the design system here. Read both before inventing new values —
matching what exists usually beats introducing a parallel scale.
