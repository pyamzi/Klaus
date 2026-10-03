# Session handoff — UI/design arc (2026-08-25 → 2026-08-26)

Anchored summary for a session that has already been compacted once.
Written to survive the next compaction: identifiers verbatim, decisions
with their *reasons*, and the debts that are invisible from the code.

**Scope of this document.** It covers one arc: the visual-system build
and the two crashes that came out of it. `CLAUDE.md` remains the
architecture authority, `PRODUCT.md` the product truth, `DESIGN.md` the
visual authority, `board/BOARD.md` the work-in-flight authority. This
file only holds what those four do not: session decisions, rejected
paths, and outstanding obligations.

## Session intent

Bring Klaus Note's UI up to a deliberate, documented standard, using
SynapsePro (`scripts/SynapsePro-main`) as the reference: a central token
system, a settings shell, accent theming, seamless window chrome — then
audit and revise the whole addon against it. Two live segfaults surfaced
mid-arc and were fixed.

## Current state (verified, not recalled)

- 23 commits this arc plus a post-arc `/simplify` cleanup pass.
- Test suite: **1129 checks across 15 files, all green**.
- Addon compiles through the addons21 symlink.
- Board: 31 Done, 0 in flight, **2 open in Backlog** (K-100, K-101).

## Files created this arc

- `klaus_note/browse_highlight.py` — Browse search-term highlighting
  (K-113), adapted from `References/highlight-search-results-main`.
- `klaus_note/md3_switch.py` — MD3 track-and-thumb switch.
- `klaus_note/background.py` — custom background + frosted-bar CSS.
- `klaus_note/top_bar.py` — restyles Anki's top toolbar in place.
- `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`,
  `.impeccable/critique/2026-08-26T06-04-26Z__klaus_note.md`.
- Tests: `test_bridge_reentrancy.py`, `test_md3_switch.py`,
  `test_browse_highlight.py`, `test_setup_crop_theme.py`,
  `test_background.py`, `test_top_bar.py`, `test_theme.py`.

## Files substantially modified

- `klaus_note/theme.py` — the design system's single source of truth:
  `palette(night)`, `COLOR_THEMES` (13 accents + `custom` via
  `custom_overrides`/`set_custom_colour`), the test-enforced radius/font
  scale, `toolbar_css()`/`bottombar_css()` and the shared
  `_chip_base_rules`/`_chip_hover_rules`/`_chip_active_rules`.
- `klaus_note/manage_models.py` — Preferences: `SettingsNav` list shell,
  `_page()`/`_row()`, accent swatches, deferred-save machinery.
- `klaus_note/pdfjs_viewer.py`, `klaus_note/pdf_viewer.py`,
  `klaus_note/web/pdfjs_viewer.html` — viewer parity, zoom affordances.
- `klaus_note/pdf_drive.py` — worst-first retention sort, themed dialogs.
- `klaus_note/deck_curate.py`, `klaus_note/setup_flow.py`,
  `klaus_note/crop_dialog.py`, `klaus_note/browse_toggles.py` — theming
  and bridge-deferral fixes.
- `klaus_note/__init__.py` — `_apply_color_theme` on `profile_did_open`,
  `browse_highlight.setup()`, widened `setWebExports`.

## Decisions that must not be re-litigated

These cost real work to reach. Reversing one needs a reason, not a
fresh instinct.

1. **Anki's shell is never replaced.** The "Klaus Workspace" and
   single-window attempts were both built and both deleted (user:
   "garbage"). Klaus *restyles* Anki in place. `_migrate_config` scrubs
   `workspace_enabled` and `single_window_mode`.
2. **The nav is ONE `QListWidget`, never per-item buttons.** Three
   rounds of pill-spacing fixes (QSS margin → layout spacing → fixed
   heights) all failed because QSS-derived size hints land on re-polish,
   so first paint differed from later restyles. A single list view has
   no per-button hints to get wrong.
3. **Chrome-bar state feedback is a translucent veil, never an opaque
   fill** — so highlights tint whatever is behind them (flat colour,
   photo frost) instead of pasting a grey chip.
4. **Top and bottom toolbars emit the same chip declaration blocks
   verbatim.** Pinned byte-identical; the bars cannot drift.
5. **Accent themes override blue-family tokens only.** Backgrounds and
   text never fork per theme — that is why all 13 presets work in both
   light and dark.
6. **Preferences are deferred-save.** Widgets only `mark_dirty()`;
   `save_all()` is the single writer. A forgotten signal costs a missing
   dirty mark, not a silently unsaved setting (how `pdf_renderer`
   originally shipped broken).
7. **Never show a dialog application-modal via `exec()` on this stack
   (Qt 6.11 + macOS 26)** — use window-modal `dlg.open()` with
   callback-driven close paths. Suite-enforced for Preferences. The
   older "never open a modal from a webchannel handler" deferral rule
   stays as hygiene but was falsified as the crash's cause — see the
   crash section below.

## The crash saga (SEVEN crashes — root cause CORRECTED 2026-08-26 pm)

Signature every time: `EXC_BAD_ACCESS` in
`QPaintDevice::devicePixelRatio` inside `QBackingStore::flush`, during
a Python `QDialog`'s `exec()` (the Preferences dialog), on
**Qt 6.11.0 + macOS 26.5.1 (Tahoe)**.

**The original diagnosis was wrong.** `20997c6`/`a2374e2` blamed
webchannel reentrancy and deferred every bridge-dispatched modal via
`QTimer.singleShot(0, ...)`. The machine's DiagnosticReports then
falsified that: crashes at 01:29/01:34 were webchannel-dispatched, but
01:35 came from a **Tools-menu QAction** (no webchannel anywhere), and
12:10/12:18/14:07/14:08 came from the **deferred timer slot itself** —
the fix's own clean dispatch path. Three dispatch shapes, one crash.

**Second theory ALSO wrong (2026-08-26 pm):** blamed application-modal
`exec()`, switched Preferences to window-modal `dlg.open()`. An eighth
crash (14:44) then bottomed out at `QCoreApplication::exec()` — the
MAIN loop, not `QDialog::exec()` — proving `open()` loaded and the
dialog still crashed the same way from a normal posted-paint. Modality
is NOT the cause. `open()` is kept anyway (more correct than app-modal
for a settings window) but is NOT the fix.

**ACTUAL ROOT CAUSE (found 2026-08-26 by staged live bisection, then
confirmed exactly by a traceback):** `Md3Switch.paintEvent` raised a
`TypeError` on **every** paint, and the escaping exception left a live
`QPainter` on the widget, which corrupts the window's backing store so
Qt segfaults on the next flush.

The `TypeError`: PyQt6's only float-coordinate `drawRoundedRect`
overload takes a `QRectF`; the positional `x, y, w, h` form is
**int-only**. This widget passed floats positionally from the day it
shipped (`d837bde`), so **the MD3 switches never once rendered** — and
`_logo`-style live verification had never been done (it sat unchecked
in this file's own live-verify list). `drawEllipse` had the same trap.

Chain: float args → `TypeError` → exception escapes `paintEvent` with
the painter still active → backing store corrupted → SIGSEGV in
`QPaintDevice::devicePixelRatio` inside `QBackingStore::flush`.

Nine crashes, one widget, two lines of geometry.

How it was found — a staged probe behind `_BARE_DIALOG_PROBE` in
`manage_models.py`, one new variable per restart:

| stage | contents | result |
|---|---|---|
| 1 | bare `QDialog(mw)` | fine |
| 2 | + `theme.dialog_qss` on the top level | fine |
| 3 | + ONE `Md3Switch` (`setChecked(True)`) | **crash** |

**Fix (`md3_switch.py`):** the real one is the geometry — every pill
stroke now goes through ONE `_pill()` helper that builds a `QRectF`,
and the thumb uses `drawEllipse(QPointF, rx, ry)`. Around it, three
layers of containment so this class of bug can never again reach the
backing store: `paintEvent` catches drawing exceptions and logs them,
closes the painter in a `finally`, and refuses a zero-size widget.
(The `_animate_to` visibility guard shipped in the same pass and is
sound behaviour — a control should not animate into its initial state —
but it was **not** what fixed the segfault; the `finally` was.)

**Audit done:** every other `draw*` call in the addon passes a real
`QRect`/`QRectF`/`QPolygonF` or genuine ints, so no other float-overload
`TypeError`s lurk. But `crop_dialog.paintEvent` and
`pdf_viewer.paintEvent` still call `.end()` outside a `finally` — the
same latent leaked-painter hazard, filed as **K-115**.

Ruled out along the way (do not re-suspect): webchannel reentrancy;
modality (`exec` vs `open`); translucent/frameless window attributes;
`dialog_qss` contents. The probe is left in place, switched off — flip
`_BARE_DIALOG_PROBE` True to bisect a future paint crash the same way.

**Lesson, stated plainly:** three theories were shipped as fixes before
the bisect (webchannel reentrancy, app-modal `exec`, animation timing).
Each pattern-matched the stack trace; none was tested against a
discriminating case first. What actually worked: change one variable
per run and let the failure speak. A traceback beats a stack trace,
and a stack trace beats a hypothesis.

The deferral rule is KEPT as hygiene (Qt documents the hazard), with
its enforcement machinery: two auto-discovered rosters (js-message
handlers + pdfjs `_bridge_*` table), per-site pins, the untokenize
comment-stripper with a non-vacuity self-check, and the
`pdf_drive.open_drive` straggler closed.

**Process lessons:** (1) a fix scoped to one file when the bug looks
cross-module leaves violators live — but (2) a plausible mechanism that
pattern-matches the stack is not the root cause until a discriminating
sample confirms it; the falsifying QAction crash sat unread in
`~/Library/Logs/DiagnosticReports` the whole time. Check ALL the crash
reports, not just the ones the user pastes.

Remaining app-modal exec sites (same risk class, on the board):
`deck_curate.choose_deck_scope`, `__init__` crop dialog,
`pdf_drive:1087`, `setup_flow`'s five `msg.exec()` QMessageBoxes,
pdfjs's two static `QInputDialog` helpers.

## Open work

- **K-100** (Backlog) — pdf.js parity: page-image insert into the
  editor's focused field, exact-phrase find highlighting. These gaps are
  now *disclosed* in the Preferences checkbox copy but not built.
- **K-101** (Backlog, `needs-human`) — flip the default renderer to
  pdf.js after a live soak, then retire the QPdfView path.
- **AGPL licensing decision** (from `PRODUCT.md`, blocks public
  release): `browse_highlight.py` is adapted from Glutanimate's
  AGPLv3 addon with header-retention terms. A public AnkiWeb release
  must be AGPL-compatible or drop that module. Also unresolved: an
  "inspired by vs. copied" attribution audit of the SynapsePro-derived
  theme conventions.
- **Critique backlog** (`.impeccable/critique/…__klaus_note.md`, scored
  27/40): Help & Documentation 1/4 and Recognition-over-Recall were the
  weakest dimensions. Deferred items include provider/model jargon on
  the first-run screen, no on-demand concept help, and no severity
  colour cue on the Library's retention numbers.

## Live-verify debts (Qt cannot be tested headlessly)

Everything below is source-verified and compiles, but has **never been
seen rendering**. Anki must be fully restarted to load changes.

1. Preferences opens from the star without crashing (`a2374e2`).
2. Curate Deck opens from the deck list without crashing (`a2374e2`).
3. pdf.js: right-click a highlight → "Add Note…", and "Go to Page"
   (`20997c6`).
4. MD3 switches render and animate in Preferences → General (`d837bde`).
5. Sidebar spacing is correct on the *very first* open (`76fed5b`).
6. Accent switching recolours every surface live (pick Orchid → Save).
7. Bottom toolbar matches the top bar in all three background modes.

## Environment constraints (easy to forget, expensive to rediscover)

- Edit **only** `/Users/pyamzi/Documents/Github/Klaus/klaus-note/addon/klaus_note/`
  — Anki loads it through a symlink; worktree edits compile nothing.
- System `python3` is 3.9.6 and **cannot import aqt**. Headless tests
  stub `aqt`/`anki` via `.claude/skills/klaus-test/scripts/anki_stubs.py`;
  Qt widgets are never constructed in tests.
- Never stage `klaus_note/user_files/` or `meta.json*` (API keys).
- Board state changes only through `python3 board/board.py`.
