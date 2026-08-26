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

Bring KlausMate's UI up to a deliberate, documented standard, using
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

- `klausmate/browse_highlight.py` — Browse search-term highlighting
  (K-113), adapted from `References/highlight-search-results-main`.
- `klausmate/md3_switch.py` — MD3 track-and-thumb switch.
- `klausmate/background.py` — custom background + frosted-bar CSS.
- `klausmate/top_bar.py` — restyles Anki's top toolbar in place.
- `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`,
  `.impeccable/critique/2026-08-26T06-04-26Z__klausmate.md`.
- Tests: `test_bridge_reentrancy.py`, `test_md3_switch.py`,
  `test_browse_highlight.py`, `test_setup_crop_theme.py`,
  `test_background.py`, `test_top_bar.py`, `test_theme.py`.

## Files substantially modified

- `klausmate/theme.py` — the design system's single source of truth:
  `palette(night)`, `COLOR_THEMES` (13 accents + `custom` via
  `custom_overrides`/`set_custom_colour`), the test-enforced radius/font
  scale, `toolbar_css()`/`bottombar_css()` and the shared
  `_chip_base_rules`/`_chip_hover_rules`/`_chip_active_rules`.
- `klausmate/manage_models.py` — Preferences: `SettingsNav` list shell,
  `_page()`/`_row()`, accent swatches, deferred-save machinery.
- `klausmate/pdfjs_viewer.py`, `klausmate/pdf_viewer.py`,
  `klausmate/web/pdfjs_viewer.html` — viewer parity, zoom affordances.
- `klausmate/pdf_drive.py` — worst-first retention sort, themed dialogs.
- `klausmate/deck_curate.py`, `klausmate/setup_flow.py`,
  `klausmate/crop_dialog.py`, `klausmate/browse_toggles.py` — theming
  and bridge-deferral fixes.
- `klausmate/__init__.py` — `_apply_color_theme` on `profile_did_open`,
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

**Where it actually stands:** the crash is Qt flushing THIS dialog's
Cocoa backing store and finding a null paint device, independent of how
the dialog is shown. Ruled out by inspection: webchannel reentrancy;
modality; translucent/frameless window attributes (none on our
dialog); alpha/border-radius/gradient on the top-level in
`theme.dialog_qss` (none — opaque bg, radius only on child group
boxes). Dialogs WE create crash; Anki's own don't. Very likely a Qt
6.11 + macOS 26.5 platform bug tied to the Tahoe window-appear
animation (`QApplicationPrivate::enabledAnimations` in the crash
registers; `NSAnimation _runBlocking` on a background queue in earlier
reports). **Current state: a bare-dialog probe is wired in
(`manage_models._BARE_DIALOG_PROBE = True`)** — Preferences opens a
plain unstyled `QDialog(mw)` to decide whether ANY dialog we open
crashes (⇒ upstream, report to Anki/Qt) or only our styled/complex one
(⇒ bisect styling → widgets). Set the flag False to restore the real
dialog once the fault is localized.

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
- **Critique backlog** (`.impeccable/critique/…__klausmate.md`, scored
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

- Edit **only** `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`
  — Anki loads it through a symlink; worktree edits compile nothing.
- System `python3` is 3.9.6 and **cannot import aqt**. Headless tests
  stub `aqt`/`anki` via `.claude/skills/klaus-test/scripts/anki_stubs.py`;
  Qt widgets are never constructed in tests.
- Never stage `klausmate/user_files/` or `meta.json*` (API keys).
- Board state changes only through `python3 board/board.py`.
