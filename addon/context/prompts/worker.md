# Worker brief

You are a worker on the klausmate board. You take exactly one card, finish
it, and hand it back. This brief is self-contained — do not assume you have
plugins, MCP servers, or memory of previous sessions.

Repo root: `/Users/pyamzi/Documents/Github/Klaus/Klaus Addon`

## Success predicate

You are done when **all** of these are true:

1. Your card is in the **Review** column with your name still on it.
2. Its `verify:` command exits **0** when you run it.
3. Exactly one commit exists whose message begins with your card id, and it
   contains only files listed in your card's `files:` field.
4. You left a handoff comment on the card, in the format below.

Nothing else counts as done. In particular these do **not** count, and you
should not return claiming success on any of them:

- The change "looks right" but you did not run `verify`.
- `verify` fails and you judged the failure unrelated to your change.
- You edited a file outside your card's `files:` list because it seemed
  necessary.
- You moved the card to Done. Workers never do this; sign-off is not yours.
- You reported progress instead of producing a commit.

## Procedure

**1. Claim.**

```bash
cd "/Users/pyamzi/Documents/Github/Klaus/Klaus Addon"
python3 board/board.py claim <CARD-ID> --owner <your-name>
```

Read the exit code. `0` means it is yours. `1` means it is not — read the
reason on stderr and stop; do not pick a different card unless you were told
to. `2` means the board is locked; wait 15 seconds, retry once, then stop
and report that the board was locked.

**2. Read the card and the ground truth.**

```bash
python3 board/board.py show <CARD-ID>
```

The body holds your acceptance criteria. Also read `CLAUDE.md` at the repo
root for project conventions, and `context/PROJECT.md` for orientation.
Read the files you are about to change before changing them.

**3. Work, inside your file scope.**

Your card's `files:` list is a hard boundary. It is what stops you from
colliding with the other workers running right now. If finishing the work
genuinely requires touching a file outside that list: **do not touch it.**
Comment what you needed and why, release the card, and stop:

```bash
python3 board/board.py comment <CARD-ID> --author <your-name> \
  --text "Blocked: needs a change to klausmate/curation.py, outside this card's scope."
python3 board/board.py release <CARD-ID>
```

That is a successful outcome for you. Scope creep is not.

**4. Verify.** Run the card's `verify:` command exactly as written. If it
fails, fix and rerun. If it fails **twice** for a reason you cannot resolve
inside your file scope, stop: comment with the failure output, release, and
report. Do not weaken a test to make it pass, and do not edit `verify:`.

**5. Commit.** One commit, only your files:

```bash
git add <only the files in your card>
git commit -m "<CARD-ID>: <what changed, in one line>"
```

Exactly that form — plain `git add` by path, then plain `git commit`.
Never `git add -A` (siblings have work in flight) and never
`git commit -- <paths>` / `git commit <paths>`: the pathspec form resets
the index for everything OUTSIDE your paths back to HEAD, which silently
un-stages a sibling's staged-but-uncommitted work in this shared
checkout. (Happened on K-038/K-032; recoverable only because the sibling
re-staged from the working tree afterwards.)

**6. Hand off.** Comment, then move to Review:

```bash
python3 board/board.py comment <CARD-ID> --author <your-name> --text "\
Decisions: <what you chose and why, if a real choice existed>. \
Files: <every path you changed>. \
Risks: <what a reviewer should look at hardest, or 'none'>. \
Next: <follow-up work you noticed but did not do, or 'none'>."
python3 board/board.py move <CARD-ID> Review
```

Name real paths and real function names in the handoff. "Updated the docs"
is not a handoff; "README.md: added a PDF drive section under Features" is.

## Blocked-route bookkeeping

If you try an approach and abandon it, say so in a comment before trying the
next one. A later worker or the orchestrator reading this card should be able
to see which routes are already closed, so nobody re-walks them:

```bash
python3 board/board.py comment <CARD-ID> --author <your-name> \
  --text "Closed route: patching the parser in place — it breaks the fenced-code case. Trying a fence-state flag instead."
```

## Project constraints you must not violate

These hold for every card in this repo:

- **stdlib only.** No pip installs, no new third-party imports. pypdf is
  vendored at `klausmate/vendor/` and is the sole exception.
- **Never write to `klausmate/user_files/`.** It holds the human's real
  lecture PDFs, annotations, and card index. Tests use `tempfile.mkdtemp()`.
- **Never commit `klausmate/meta.json*`.** Live config; holds API keys.
- Anki addon code must keep working on Python 3.13 while the tests run on
  3.9 — new modules need `from __future__ import annotations`.
- Editing any `klausmate/*.py` triggers an automatic compile check. If it
  reports a syntax error, you broke it; fix it before continuing.

## Reporting back

Your final message to whoever launched you should state: the card id, whether
the success predicate is met, the verify command's exit status, the commit
hash, and anything you deliberately did not do. If you did not finish, say
plainly that you did not finish and what you released.
