# The PDF panel as a native dock — design

**Date:** 2026-09-05. **Asked by Pouya:** "a better system for the PDF
viewer window management." Answers gathered the same day: today's drag
and tear-off feel flaky, six placements over two anchors are too many to
reason about, every window should use one mechanism, and a floating
panel should stay attached to its Anki window rather than be a separate
window. Approach chosen: **A, a native `QDockWidget` per host window.**

## Decisions

- **D1 — one class, `PdfDock(QDockWidget)`, one instance per host
  `QMainWindow`**: Browse and Add Cards (both are `QMainWindow`s; the
  PDF panel today hangs off their editors). Its contents are the
  existing panel body unchanged: the tab bar `[tabs ✕] [page n/m] [＋]`,
  the one shared `PdfSidebar`, per-tab reading positions, the ＋ menu
  of stored PDFs. The bar becomes the dock's **title-bar widget**
  (`setTitleBarWidget`), so dragging the bar moves and re-docks the
  panel and double-clicking it floats — by Qt.
- **D2 — three areas and float.** Allowed areas: left, right, bottom.
  Floating is Qt's own: an attached tool window that stays above its
  host, moves and hides with it, and drags back into an area. No top
  area, no placement menu, no drop bands of ours: drag the bar, or
  press the float/dock button on it.
- **D3 — delete the placement engine and the drag machine.** Gone from
  `_PdfTabContainer`: `_wrap_pane`, `_ensure_vsplit`,
  `_ensure_notes_split`, `_browse_note_pane`, `_dock_into`, `_embed`,
  `_make_floating`, `_remember_float_geom`, the drag state machine
  (`_start_panel_drag`, `_arm_drag_machinery`, `_install_app_filter`,
  `_displaced_enough`, `moveEvent`, `_drag_tick`, `_reset_drag`,
  `_defer_placement`, `_finalize_drag`, `_tear_off`, `_drag_ghost_to`,
  `_destroy_ghost`, `_update_zone`, `_show_zone_overlay`, `_hide_zone`),
  `NOTES_PLACEMENTS`, `_BROWSE_PLACEMENT_KEY`,
  `_load_browse_placement`/`_save_browse_placement`, and the zone
  captions. Roughly 1,000 of the container's 1,570 lines. Nothing
  outside `__init__.py` calls any of them (checked 2026-09-05:
  `library_tab.py`, `pdf_drive.py`, `pdf_viewer.py` only name the
  container in prose; `tests/test_bridge_reentrancy.py` pins
  `NOTES_PLACEMENTS` and `_defer_placement` and is re-baselined).
- **D4 — persistence is Klaus's own, two keys.** `pdf_tabs.json`'s
  `placement` key keeps its name and takes the new values `left`,
  `right`, `bottom`, `float`; `geom` keeps the floating geometry. Old
  values migrate once on read: `above` and `below` → `bottom`; `left`
  and `notes-left` → `left`; `right` and `notes-right` → `right`;
  `float` → `float`; anything else → `right`. The Browse-only
  `browse_placement` key is ignored and removed on the next save.
  Anki's `QMainWindow.saveState()`/`restoreState()` for Browse is left
  alone: the dock is created after Anki's restore, and Klaus applies its
  own remembered area, size and float state on first show, so a stale
  Anki-saved layout can never overrule the user's last move
  (`restoreDockWidget` is deliberately not used).
- **D5 — Browse keeps its sidebar heal.** `setDockNestingEnabled(True)`
  on Browse so the panel can sit left of the note list beside Anki's
  own sidebar dock. `_reset_browse_layout_to_defaults` touches only
  `sidebarDockWidget` and stays as is.
- **D6 — the host owns the dock's lifetime.** A dock is a child of its
  window, so the parentless-window teardown in `_on_host_closing`
  reduces to persisting state and `sidebar.cleanup()` (the webview must
  still be released before its C++ object dies). The floating panel no
  longer appears in Mission Control or minimises to the Dock; that is
  the trade Pouya chose.

## What the user sees

- Browse and Add Cards: the panel opens where it was last left, docked
  left, right or bottom of the window, or floating over it, sized to
  45% of the host on first use (`resizeDocks`).
- Dragging the bar's empty space moves the panel; dropping it on an
  edge docks it there, anywhere else leaves it floating. Dragging a tab
  still reorders tabs, as today.
- Two small buttons join the bar's right end: **float/dock** (toggles
  `setFloating`) and **hide** (`dock.hide()`, what the red traffic light
  did). ✕ on a tab and ＋ are unchanged.
- The chip and the shortcut that toggle the panel today call
  `panel_show`/`panel_hide`; those become `dock.show()`/`dock.hide()`
  with the same names kept, so `editor._klausmate_pdf_tabs` stays the
  attribute other code reads.

## Title-bar contract

The bar widget handles only the presses it needs (tab reorder inside the
tab bar, its buttons) and calls `event.ignore()` for the rest, which is
what lets `QDockWidget` move, dock and float from a custom title bar.
With a custom title bar Qt draws no float or close button of its own,
hence the two buttons above. The bar keeps `theme` tokens only.

## Behaviour lost on purpose

- "Above the editor pane" and "beside the note list inside the editor
  splitter" as anchors. Bottom of the window and left of the note list
  (beside the sidebar) are the nearest dock areas.
- The parentless floating window with its own traffic lights.

## Testing (offscreen PyQt6, `tests/test_klausmate.py`'s real-Qt section)

1. A fake Browse `QMainWindow` gets a `PdfDock`; `dockWidgetArea()`
   round-trips for left, right and bottom, and `isFloating()` after
   `setFloating(True)`.
2. Each old `placement` value migrates to the documented new one; an
   unknown value lands on `right`.
3. A press on the bar's empty space is ignored by the bar widget (the
   event reaches the dock); a press on a tab is not.
4. Nesting is enabled on Browse and the sidebar heal still finds and
   re-anchors `sidebarDockWidget`.
5. Host close persists state and calls `sidebar.cleanup()` exactly once.
6. `test_bridge_reentrancy.py`: the `NOTES_PLACEMENTS`/`_defer_placement`
   pins are replaced by one pin that the deleted names are absent from
   `__init__.py`.
7. The full loop stays green; `scripts/mutation_audit.py` unaffected.

## Docs

CLAUDE.md's `__init__.py` entry (the `_PdfTabContainer` paragraph) and
AGENTS.md's window-management paragraph are rewritten to this design;
the K-169 note-anchor prose in `browse_toolkit.browse_note_column`'s
docstring is updated to name the dock.

## Out of scope, for a later plan

- Unlocking the Lecture and assistant docks on the main window (today
  `NoDockWidgetFeatures` with empty title bars) to the same bar
  contract, so all three panels tab and stack together.
- The embedded Library screen's route to open a PDF (K-173's note in
  `library_tab.py`): the dock is the shape that fix should take.
