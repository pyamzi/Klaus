# Handoff: local-model reversion (in progress)

**Written:** 2026-09-19, mid-execution, for a fresh LLM session with no
access to the conversation that produced this. Read this whole file
before touching anything — it explains context the ledger alone won't
give you.

## What this project is

The user (Pouya) asked to remove Klaus's API-first stack (OpenAI/
Anthropic keys, the Klaus Plus subscription service, the Claude
pertinence judge, the embedded Claude-Code-CLI assistant dock) and go
back to local models — but NOT a straight revert. Four rounds of
clarifying questions settled a materially different end state than
"undo the API-first turn":

1. **Embeddings** → local Ollama, **full runtime management** restored
   (not just a thin client — Klaus detects/installs/starts/stops Ollama
   itself, same as it did before 2026-09-15).
2. **Card-duplicate judging** → drops to plain cosine thresholds. No
   local stand-in for the Claude judge is being built.
3. **The embedded assistant dock is deleted outright**, not ported to a
   local model. In its place: Klaus's existing internal MCP server
   (`anki_endpoint.py`) becomes reachable from an **external** client —
   Claude Desktop — via a new stdio↔HTTP bridge script. ChatGPT is
   explicitly out of scope (its connector model wants a public HTTPS
   endpoint, not a localhost socket).
4. **Lecture transcription** survives, moved off OpenAI Whisper onto a
   locally-installed whisper.cpp binary (discovered the same way Klaus
   discovers the `claude` CLI) — but this is genuinely new work, not a
   revert (there's no local-transcription code anywhere in this repo's
   history), and is explicitly scoped as **spike first, then build**.

Full rationale, verified facts (Claude Desktop's stdio-only MCP config,
this machine having neither Ollama nor whisper.cpp installed), and every
decision is written up in the design spec — **read it before writing
any more plans**:

`docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`

That spec is APPROVED by the user and complete. Do not re-litigate its
decisions (D1–D6) without a real reason; if you find a factual error in
it, fix it in place and note why, the way earlier work in this project
did (see its own edit history via `git log --follow` on that file).

## Where things physically are

**The repo moved during this project.** It is now at:

```
/Users/pyamzi/Documents/Github/Klaus/KlausMate-Context
```

NOT the old `/Users/pyamzi/Documents/Github/KlausMate-Context` (that
path no longer exists). `/Users/pyamzi/Documents/Github/Klaus/` itself
is **not a git repo** — it's a plain folder holding three independent
repos side by side (`KlausBook-Code`, `KlausBook-Context`,
`KlausMate-Context` — see `Klaus/CLAUDE.md` for how they relate). Always
`cd` into `KlausMate-Context` specifically.

**The Anki addon symlink** (`~/Library/Application Support/Anki2/
addons21/klausmate`) went dangling when the repo moved (it still pointed
at the old path) and was relinked mid-session to point at the new one.
If you see compile-through-symlink failures, `ls -l` that symlink before
assuming the code is broken — it may just be stale again after another
move. `KlausMate-Context/CLAUDE.md`'s own "Hard-won gotchas" section
covers this exact failure mode.

**Branch:** `claude/repo-root-casing` — an existing feature branch, not
main/master. Nothing in this project has been pushed to origin; the
branch is local-only, ahead of origin by many commits. Do not push
without asking the user first.

## Documents that exist

- **Spec** (approved, complete): `docs/superpowers/specs/2026-09-18-local-model-reversion-design.md`
- **Demolition plan** (D1+D2+D3, **currently being executed**):
  `docs/superpowers/plans/2026-09-18-local-model-reversion-demolition.md`
  — 20 sequential tasks, explicitly NOT parallelizable (see its own
  Global Constraints: `plus.py` had 8 importers, `pertinence.py` has 5;
  deleting either breaks every concurrent card's verify at once). This
  plan has already been amended TWICE mid-execution (see "Rulings"
  below) — the amendments are written into the plan file itself, not
  just the ledger, so reading the plan now gives you the corrected
  version.
- **D4 (Ollama restoration), D5 (MCP bridge), D6 (local transcription)
  plans do NOT exist yet.** They're separate, independent plans per the
  spec's own "Execution shape" section — demolition must finish first
  (its clean tree is their prerequisite), but they don't depend on each
  other and can be written/executed in any order once demolition lands.
  Write them with the `writing-plans` skill when you get there. The
  research needed to write them precisely (verbatim old `ollama_client.py`/
  `ollama_runtime.py`/`ollama_setup.py` content, current `manage_models.py`
  page-building patterns, `anki_endpoint.py`'s full structure, etc.) was
  gathered once already via parallel research agents but **was not
  persisted anywhere** — it lived only in the conversation that produced
  this handoff. It's cheap to re-gather: the spec's D4/D5/D6 sections
  name the exact git commits to pull from (`git show 1b6fccd^:klausmate/
  ollama_client.py` etc.) and the exact files to read — just re-run
  equivalent research passes rather than assuming the old output is
  recoverable.
- **This handoff file** — delete it once the whole project (demolition +
  D4/D5/D6 + doc inversion) is done and merged; it's a point-in-time
  note, not a permanent doc.

## Execution state — READ THE LEDGER FIRST

This project is being executed with the `subagent-driven-development`
skill (fresh implementer subagent per task, task-scoped review after
each, fix loops on findings). Its ledger is the authoritative record of
what's actually done — **read it before doing anything else**:

`.superpowers/sdd/2026-09-18-local-model-reversion-demolition/progress.md`

(This path is git-ignored scratch, per the skill's convention — it
won't show up in `git log`, only on disk.)

As of this handoff, the ledger shows:

- **Tasks 1–5: complete, reviewed clean.** (Task 5 has one deferred
  Minor finding — a stale comment at `manage_models.py:1755-1756`
  naming a deleted function, zero functional impact — parked for the
  final whole-branch review, not worth a fix round.)
- **Task 6: implementation DONE and committed, task review NOT YET
  dispatched.** This is the messiest part of this handoff — read
  carefully:

  Task 6 as originally written ("delete `plus.py`, its test, and
  `service/`") was a **plan defect**, caught by an implementer that
  correctly refused to proceed rather than delete something two files
  still legitimately depend on (`anthropic_client.py`'s `plus.active(cfg)`
  call, survives until Task 14; `openai_client.py`'s `plus.Endpoint`
  type hints — that file isn't deleted by THIS plan at all, only by a
  future D4/D6 plan). The ruling: Task 6 was rescoped in place (in both
  the ledger AND the plan document itself) to only delete `service/`
  and strip `openai_client.py`'s now-dead Plus-endpoint parameters;
  the actual `plus.py`/`tests/test_plus.py` deletion moved into Task 14
  (which already deletes `anthropic_client.py`, `plus.py`'s last real
  caller). **The plan file at its current path already reflects this —
  you don't need to re-derive it, just read Task 6 and Task 14 as
  currently written.**

  A redirected implementer executed the corrected scope and reported
  **DONE**, committed as **`790aac0`**: "Delete the never-shipped Klaus
  Plus service; drop openai_client's now-dead Plus-endpoint params" —
  `service/` deleted (37 files, 4475 lines), `openai_client.py`'s
  `plus` import and both functions' `endpoint` parameters removed
  cleanly. Its self-reported full-suite run (44 files, no early break):
  43 pass, 1 skip (`test_live_api.py`, needs `KLAUS_LIVE_API=1`), and 7
  fail — `test_openai_client.py` (**new**, expected: it has tests that
  pass `endpoint=` explicitly, cleaned up only in a future D4/D6 plan,
  not this one) plus the 6 already-known pre-existing ones
  (`test_dialog_logic.py`, `test_index_queue.py`, `test_klausmate.py`,
  `test_lecture_recorder.py`, `test_manage_models_assistant.py`,
  `test_setup_crop_theme.py`).

  **What's NOT done yet**: no report file exists at
  `.superpowers/sdd/.../task-6-report.md` (the implementer's final
  message came back as a structured summary, not a written report —
  worth asking it to write one retroactively if you want the artifact,
  though not blocking), and — most importantly — **the task review step
  was never dispatched**. Per the `subagent-driven-development` skill,
  a task isn't "complete" until it's been through
  `review-package` + a task-reviewer subagent, and the ledger does not
  yet have a `Task 6: complete` line. **Do this next**: run
  `review-package PLAN_FILE c54f487 790aac0` (BASE is Task 5's commit,
  HEAD is Task 6's), dispatch a task reviewer against Task 6's
  (amended) brief and this report, and only then write `Task 6:
  complete (commit 790aac0, review ...)` to the ledger before starting
  Task 7.

  Also uncommitted as of this handoff: this handoff file itself, and
  the plan document's own Task 6/Task 14 amendments (`git status` shows
  `docs/superpowers/plans/2026-09-18-local-model-reversion-demolition.md`
  as modified, not yet committed — the amendment text is already in the
  file on disk, just not committed). Commit the plan amendment as its
  own small commit (it predates and is independent of Task 6's actual
  work commit, which already landed without it).

- **Tasks 7–20: not started.**

## Rulings already made (do not silently re-litigate)

All three below are written in full in the ledger
(`.superpowers/sdd/.../progress.md`) with their reasoning and cost-if-
wrong — this is a compressed pointer, go read the ledger for the actual
text before deciding anything that touches these:

1. **Task 4** (setup_flow.py): the code change was correct. The gap was
   verification — an early `|| break` in the test-suite run hid a real,
   newly-caused failure in `tests/test_setup_crop_theme.py` (3
   assertions that assumed Klaus Plus still existed). Fixed by re-
   running the suite properly and reporting honestly; no code changed.
   **Consequence for later work**: Task 8 (not yet run) must ALSO cover
   `tests/test_setup_crop_theme.py`'s 3 Klaus-Plus assertions — this
   file was missing from the plan's original Task 8 file list (a gap in
   the research pass that fed the plan). Make sure whoever dispatches
   Task 8 includes it explicitly in that task's brief, since the
   auto-generated brief (from the plan text) won't mention it — the
   ledger note is the only record.

2. **Task 5** (manage_models.py): similarly surfaced `tests/
   test_lecture_recorder.py` as a pre-existing-failure file not on the
   plan's original list either — verified via git-stash-and-compare
   against base to be pre-existing rather than caused by Task 5. This is
   probably already covered by Task 8's broad "fix every Klaus-Plus-
   aware test" sweep, but flag it explicitly to Task 8's dispatch too,
   for the same reason as #1.

3. **Task 6**: see the long writeup above — `plus.py` deletion moved
   from Task 6 to Task 14; the plan document itself was amended in
   place to reflect this, so reading the current plan file is enough,
   you don't need to re-derive the ruling.

## Established conventions — keep following these

- **Never run the test suite with an early break** (`|| break`). Always:
  `for t in tests/test_*.py; do echo "— $t"; python3 "$t"; done` — no
  `|| break`. This bit Task 4 once already (see ruling #1 above); every
  dispatch since has explicitly told implementers not to repeat it.
- **Work directly in the main checkout, never a worktree.** CLAUDE.md
  requires this — Anki's addon symlink points only at this exact path,
  so a worktree edit would compile/test successfully without ever being
  the code Anki actually loads.
- **Commit messages**: short, descriptive, no K-numbers/ticket refs —
  this plan isn't board-tracked (the `agent-board` skill/kanban workflow
  in this repo is a separate, unrelated mechanism for a different kind
  of multi-session work; this project uses `subagent-driven-development`
  instead, chosen because the plan is explicitly sequential).
- **Model tiers used so far**: `haiku` for pure single-file mechanical
  edits with complete before/after code given in the brief; `sonnet` for
  anything touching multiple sites, requiring judgment about what a
  stale brief snippet actually maps to in the live file, or reviewing
  non-trivial diffs.
- **Grep-confirm before deleting.** Every deletion task in this plan
  starts with a grep to confirm zero remaining importers/references, and
  implementers have been told explicitly: if the grep isn't clean,
  report BLOCKED and stop — don't guess, don't delete anyway. This
  caught the Task 6 plan defect; trust it, don't skip it to save time.

## After the Demolition plan finishes (Tasks 1–20 all complete)

1. Run the final whole-branch review per the `subagent-driven-development`
   skill: dispatch on the most capable available model, package the diff
   with `review-package PLAN_FILE MERGE_BASE HEAD` (figure out
   `MERGE_BASE` — likely `a1d56fd`, the commit right before Task 1
   started, but confirm against where this branch actually diverged from
   whatever it should merge into). Point the final reviewer at the two
   deferred Minor findings already in the ledger (ruling #1's file and
   Task 5's stale-comment finding) so it can triage whether either
   blocks merge.
2. Use `superpowers:finishing-a-development-branch` once that's clean.
3. Write and execute the **D4 (Ollama restoration)**, **D5 (MCP
   bridge)**, and **D6 (local transcription — spike first)** plans, each
   as its own `writing-plans` → `subagent-driven-development` cycle, per
   the spec's "Execution shape" section (these three can run in any
   order relative to each other, but all need D1–D3's clean tree first).
4. Do the **"Doc inversion" pass** the spec calls for in its own section
   of that name: `CLAUDE.md`, `AGENTS.md`, `PRODUCT.md`, `config.md`, and
   one-line "superseded by" headers on the three specs this reversal
   makes obsolete (`2026-09-15-api-first-klaus-design.md`,
   `2026-09-16-klaus-plus-subscription-design.md`,
   `2026-09-01-klaus-assistant-claude-code-design.md`). **Not started at
   all yet** — don't let it fall through the cracks; a future session
   reading `CLAUDE.md` mid-D4/D5/D6 will otherwise be actively misled by
   documentation describing the very systems this whole project deletes.
