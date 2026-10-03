# Roles and the card lifecycle

Three tiers work this repo through one shared board. The tiers exist to
isolate context, not to divide labour by job title: each tier sees only what
its decisions need, so no session carries the whole project in its window.

| Tier | Who | Writes |
|---|---|---|
| **Orchestrator** | an Opus session | Anything. Grooms cards, slices large work, reviews, signs off. |
| **Designer** | a second Opus session | Card *bodies* of `design` cards; moves those cards via the CLI. No production code. |
| **Worker** | a Sonnet subagent or terminal session | Only the files its claimed card declares. Board state only through the CLI. |

The human supervisor sits above all three, watches the dashboard, and owns
`needs-human` cards.

## The board is the only shared state

`board/BOARD.md` is the source of truth. Everything else — this file, the
prompts, PROJECT.md — is static context that rarely changes.

**All state changes go through `board/board.py`.** It serialises every write
behind a lockfile, so parallel workers cannot corrupt the file or both claim
the same card. Editing BOARD.md by hand to move a card will eventually lose
a write. Editing a card's *body* prose by hand is fine and expected for the
orchestrator and designer, because those sessions are few and deliberate.

```bash
python3 board.py list                  # what is happening
python3 board.py show T-004            # one card in full
python3 board.py check-disjoint        # would any claimable work collide?
python3 board/serve.py                       # dashboard on 127.0.0.1:8765
```

Exit codes are a contract: `0` success, `1` refused (reason on stderr),
`2` the board was locked and stayed locked.

## Columns and the gates between them

```
Backlog ──groom──▶ Ready ──claim──▶ Doing ──verify──▶ Review ──sign-off──▶ Done
                     ▲                 │                  │
                     └─────release─────┘                  └──rework──▶ Doing
```

**Backlog → Ready** is the orchestrator's grooming gate. A card may not enter
Ready without all three of:

- **acceptance criteria** in the body — what must be true for this to count
  as finished, stated so an adversarial reader cannot satisfy the letter
  while missing the intent;
- **`files:`** — every path the work will touch;
- **`verify:`** — one command whose exit status decides the outcome.

A card without these is not ready, no matter how clear it looks in prose.

**Ready → Doing** happens only via `claim`, never `move`. Claiming enforces
**file disjointness**: if any path on the card overlaps a path held by a card
already in Doing, the claim is refused. This is what makes an unattended
swarm safe — two workers can never be editing the same file. Keeping Ready
cards disjoint is therefore the orchestrator's job, not a worker's problem.

**Doing → Review** requires the `verify` command to exit 0 and one commit
whose message starts with the card id.

**Review → Done** is human or orchestrator sign-off. Workers never move their
own card to Done — a generator that grades its own output grades leniently.

## Grooming rules for the orchestrator

- **A `verify:` command must fail before the work and pass after.** Run it
  against the current tree while grooming. If it already exits 0, it gates
  nothing and the card can be "finished" without a single edit. This is easy
  to get wrong: `grep -c 'stale phrase' FILE` exits 0 when the phrase is
  *present*, so as a check that the phrase is gone it is exactly backwards.
  (A card once shipped with that bug. The worker's judgement saved it;
  the gate did not.) Prefer `! grep -q ...`, a test command, or a compile check.
- **Keep Ready file-disjoint.** Run `check-disjoint` after every grooming
  pass. Overlapping Ready cards are not a bug in the board, they are a
  scheduling mistake.
- **File-disjointness protects writes, not verify gates.** Every card's gate
  runs the test suite, and the suite imports your project's entry module. So
  a worker editing that one file leaves *every* concurrently-running card's
  gate failing on an error that has nothing to do with its own work. This
  has happened: a worker polled until the tree recovered rather than
  releasing finished work — the right call, but it burned its time on
  someone else's half-saved file. When a card rewrites a module the suite
  imports at collection time, either run it alone or tell the parallel
  workers in their brief that a transient failure in a file outside their
  scope means "wait and re-run", not "my change broke it".
- **Slice large work before releasing it.** A card naming a 6,000-line file
  blocks every other card touching that file. Split it along real seams
  first; leave it in Backlog until you have.
- **Tag honestly.** `cheap-model-safe` means a worker with no design
  judgement, and no access to the running application, can finish it.
  `design` means it needs a spec first. `needs-human` means no agent can do
  it at all.
- **Sweep stale claims.** A card sitting in Doing with an old `claimed:` date
  and no recent comment is an abandoned claim. `release` it.

## Handling a stuck board

A crashed worker leaves two kinds of mess. Its **lockfile** clears itself
once it is older than 120s and its process is gone. Its **claim** does not —
the card sits in Doing forever. Release it:

```bash
python3 board.py release T-004
python3 board.py comment T-004 --author orchestrator --text "worker vanished; released"
```
