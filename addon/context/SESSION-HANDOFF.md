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
7. **Never open a modal from a webchannel-dispatched handler** — see
   the crash section below. This is now a suite-enforced rule.

## The two crashes (same root cause, different sites)

Signature both times: `EXC_BAD_ACCESS` in
`QPaintDevice::devicePixelRatio` inside `QBackingStore::flush`, with
`QMetaObjectPublisher::invokeMethod` → a Python slot → `QDialog::exec()`
on the stack. A modal spins a nested event loop inside the re-entrant
Chromium/Qt bridge dispatch, and a posted paint lands against a backing
store that is not in a valid state.

- `20997c6` fixed `pdfjs_viewer._bridge_note_edit` and
  `_bridge_goto_request`.
- `a2374e2` fixed `top_bar._on_js_message` (the star → Preferences path)
  and `deck_curate._on_curate_clicked`.

**Process lesson worth keeping:** the first fix was scoped to one file
when the bug was a cross-module rule, so it left the other violators
live and the user hit the very next one. `tests/test_bridge_reentrancy.py`
now enforces the rule across modules and **auto-discovers two rosters**
— the registered js-message handlers AND pdfjs_viewer's `_bridge_*`
dispatch table — so a new handler either fails the roster pin or lands
in the modal scan automatically. Verified self-falsifying.

The one known straggler (`pdf_drive.open_drive`'s except-branch
`showWarning`, modal on the toolbar-link bridge path) was closed in
the post-arc cleanup pass and is pinned in the same test. That pass
also fixed the test's comment-stripper: its space-joined token output
could never match any `_MODAL` spelling, so the final scan had been
silently vacuous — it now preserves layout via `untokenize` and
self-tests its own matchability.

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
