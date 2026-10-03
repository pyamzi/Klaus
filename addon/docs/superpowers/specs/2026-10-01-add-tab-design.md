# Add tab: Library | PDF reader | Add editor

Date: 2026-10-01. Status: design approved in conversation (grilled, Q1–Q14),
spec awaiting review. Builds on the [single window](2026-09-30-single-window-design.md)
(live gate passed 2026-09-30) and the peer's [PDF reader](2026-09-30-pdf-reader-design.md)
(phase 3 landed, latest 2222af8; phase 4 is Pouya's live trial).

## Goal

Make cards from the Library faster. Add stops being a right dock on the
main window and becomes a third tab beside Decks and Browse, laid out
like Browse with a different middle:

```
┌ toolbar: Decks  Add  Browse  Stats  Sync ───────────────────────────┐
│ Library tree      │ PDF reader (tab strip + page) │ Add editor      │
│ (folders, PDFs,   │                               │ (Anki's Add,    │
│  retention %)     │                               │  embedded)      │
│ [filter box]      │                               │                 │
│ [Import PDFs…]    │                               │                 │
├ status bar: ⚙  readout ……………………………………………………  ◧ tree  ◨ editor ┤
```

The PDF reader has exactly two homes: this middle pane, and Browse's
viewer mode (double-click a Library PDF, the cards step aside). The PDF
dock and the editor-toolbar "Library…" button go everywhere.

## Decisions (Pouya, 2026-10-01)

| Q | Decision |
|---|---|
| 1 | Add is a tab exactly like Browse; the dock-hosted Add is deleted. |
| 2 | The left pane is the Library branch only (folders, PDFs, icons, retention %, right-click actions, import footer). No decks, tags or searches. |
| 3 | One shared reader, moved between the Add tab's middle and Browse's viewer mode. Not two readers. |
| 4 | Edit Current stays a right dock on the main window. |
| 5 | `a` and the toolbar Add link switch to the tab and focus the first field. Close and Escape return to the previous tab with the instance alive and its sticky fields kept. Anki's close-all destroys it; the tab shows "Press A to add a note." until the next open. |
| 6 | The Add tab gets Browse's status bar: gear, task readout, ◧ tree and ◨ editor toggles. |
| 7 | The "Library…" editor-toolbar button is removed from Add, Browse and Edit Current. |
| 8 | Single click on a PDF row opens it in the middle. The reader's empty state shows until then. |
| 9 | No PDF dock anywhere. Edit Current has no PDF. The dock placement feature (left, right, bottom, float) retires. |
| 10 | Switching tabs never ends viewer mode: Browse gets the reader back on return, same page. |
| 11 | A filter box above the Library tree, like Anki's sidebar search box. |
| 12 | The "Right Sidebar" dock toggles on Browse's status bar and the Decks bottom row are removed. |
| 13 | Reader chrome is the open-PDF tab strip only; the float ⧉ and hide ✕ buttons go. |
| 14 | With the single window off or disabled, Anki's stock windows run; the PDF is reachable only through Browse's viewer mode. |

Consequence stated and accepted: the review screen's Lecture panel (its own
reader, `host_key="lecture"`) is untouched.

## Current state (read 2026-10-01, HEAD 2222af8 + working tree)

- `single_window.py`: `build_host` makes a two-page `QStackedWidget`
  (Decks, Browse) under `mw.toolbarWeb`; `_dock(mw, "add", "Add")` is a
  `QDockWidget` in `mw`'s right area holding the embedded Add; Edit Current
  gets a second dock tabified with it; `register_dock` tabs Klaus's PDF dock
  with Add. `show_dock/hide_dock/toggle_dock/dock_shown/focus_in_dock` serve
  the docks; `_on_dialog_opened` routes `ADD_NAMES` to `show_dock("add")`;
  `_CloseFilter("add")` turns a user Close into `hide_dock()`;
  `active_link_js` presses `#add` while a dock shows; `_retarget_pdf` moves
  the shared dock's editor binding on `focus_did_change`; `restore_dock_state`
  hides every dock at start.
- The docks run the full window height beside the central stack, outside
  the toolbar and Browse's status bar (Pouya's report, 2026-09-30). This
  design removes the Add and PDF docks; the Edit dock keeps the defect.
- `__init__.py`: `on_editor_did_init` builds one `PdfSidebar` + `PdfDock`
  per host window (`host_for(editor.parentWindow)` = `mw` under the single
  window, so one dock is shared by Browse, Add, Edit Current) and binds
  `editor._klausmate_pdf_tabs` / `editor._klausmate_sidebar`;
  `_on_library_button` and `_ensure_sidebar_pdf` serve the editor-toolbar
  "library" action; `PdfDock` persists placement and float geometry through
  `pdf_handler.load_panel_state` / `migrate_placement` / `PANEL_AREAS`;
  `_PanelBar` is its title bar and, since 2222af8, also carries the
  reader's tab strip (`reader_tabs.ReaderTabs`) so the dock has one row.
- `library_viewer.py`: `enter(browser, safe)` hides Browse's central widget
  and `resizeDocks` the PDF dock to fill the gap; `leave` restores. Nothing
  is re-parented today.
- `library_sidebar.py`: paints the Library rows into Anki's `SidebarTreeView`
  through `LibraryNameDelegate` and `wrap_sidebar`; keeps `_sidebars`
  (weak set of Anki trees), `_state["means"]` (retention), the missing and
  unindexed sets; refreshes on `operation_did_execute`, the index runner's
  listener and `pdf_drive._library_changed`; `on_context_menu` offers the
  Klaus items; `Footer` is the Import PDFs… button; `PdfDropFilter` takes
  Finder drops. `library_actions` take a parent widget and a safe name or
  folder path, never the Browse instance.
- `status_bar.py`: `StatusBar(parent, browser=browser)`; `_add_toggles`
  binds ◧ to `browser.sidebarDockWidget`, ◨ to `_editor_column(browser)`
  and adds the single window's dock toggle; `install_browser` adds the ✕
  "Close Browse" control. `bottom_row.py` adds the Decks row's dock toggle
  (`DOCK_CMD`, `row_html(dock_toggle=)`, `_dock_toggle`).
- `host_keys.py`: `setup(mw, focus_in_dock)`; the override filter lets
  typing keys through to the editor only while `focus_in_dock()` and the
  reviewer's state shortcuts are not suspended.

## Architecture

### Host: three pages

`build_host` makes three pages: `decks`, `add`, `browse`. `Host` remembers
`previous` (the tab shown before the current one; `decks` at start).
`active_link_js(tab)` marks `#decks`, `#add` or `#browse` active;
`klaus-pressed` is gone.

The Add page is one `QSplitter` (horizontal) with three children:

1. **Library pane** (`library_tree.py`, new): a `QWidget` with a filter
   `QLineEdit`, a `QTreeView` on Klaus's own model, and the existing
   `library_sidebar.Footer`.
2. **Reader slot** (`reader_host.py`, new): an empty `QWidget` with a
   zero-margin `QVBoxLayout`; the one `PdfSidebar` is its child whenever
   Browse is not borrowing it.
3. **Editor slot**: the container the embedded Add is constructed into
   (`_target("add")`), holding the placeholder "Press A to add a note."
   until then.

Below the splitter, Klaus's status bar (see Status bar). Splitter sizes
are saved and restored per profile with `aqt.utils.saveSplitter` /
`restoreSplitter` under the key `klausmate_add_tab`; first use is
24 % / 46 % / 30 %.

### Construction-time hosting (unchanged mechanism)

`"AddCards"`/`"NewAddCards"` still map to `EmbeddedAddCards`; `_target("add")`
now returns the Add page's editor slot. `_on_add_cards_did_init` drops the
placeholder, hides the child's menu bar, installs the close filter and
`destroyed` handler as today. `_on_add_destroyed` restores the placeholder.

### Navigation

- `_on_dialog_opened` for `ADD_NAMES` → `host.switch("add")`; Anki's
  `reopen` then focuses the first field as it does now. A switch to the
  Add tab with no live Add instance calls `mw.onAddCard()` one tick later
  (the logic `show_dock("add")` holds today moves into the switch).
- The toolbar Add link and `a` go through Anki's `dialogs.open`, so the
  route above covers them; nothing toggles.
- `_CloseFilter("add")`: a user Close (Cmd+W, a Close control, Escape via
  the filter below) ignores the event and calls `host.switch(host.previous)`.
  Anki's own teardown (`_close_event_has_cleaned_up`) passes.
- Escape on the Add tab: an `_EscapeFilter` variant on the Add instance
  that calls the same switch instead of swallowing. (Browse's Escape still
  does nothing.)
- Leaving the Add tab does nothing to the instance; its fields persist.
- `_on_state_did_change` still switches to Decks when the reviewer or deck
  list state changes.

### Keyboard (T7, extended)

The Add tab is treated exactly as the Browse tab is today:

- The reviewer's state shortcuts are suspended (`recorder.suspend(mw)`)
  while `add` or `browse` shows and resumed on Decks.
- `mw`'s permanent bare-key shortcuts (`d s a b t y …`) and the host-bar
  actions with bare keys are parked on the Add tab as on Browse, because
  the Library tree is a `QTreeView` they would fire from. `TAB_KEYS`
  (`d`, `b`, `a`) stay live.
- `host_keys` keeps its override filter, now gated on "focus inside the
  Add page's editor slot or the Edit dock" (`focus_in_editor()` replaces
  `focus_in_dock()`).
- Browse's menus still come and go with the Browse tab only; Add has no
  menus.

### The reader: one widget, two homes

`reader_host.py` owns the one editor-host `PdfSidebar`:

```python
def set_home(slot) -> None             # the Add page's reader slot (None in fallback mode)
def reader(parent=None) -> PdfSidebar  # built on first call under the home (or parent); None with nowhere to go
def lend(container: QWidget) -> None   # re-parent into Browse's central area (viewer mode)
def give_back() -> None                # re-parent into the Add page's reader slot; no-op without a home
def borrowed() -> bool
def release() -> None                  # cleanup() and forget (fallback: Browse closed)
```

- **Ownership.** With the single window active the reader's permanent
  parent is the Add page's reader slot; it is built lazily on the first
  Add tab show or the first viewer-mode entry, whichever comes first,
  with `host_key="editor"` so the tab set persists as today.
  In fallback mode (single window off or `disable()`d) there is no Add
  page: the reader is built under the Browse window on the first
  viewer-mode entry and never leaves it. The reader is never re-parented
  across top-level windows.
- **Viewer mode** (`library_viewer`): `enter` hides Browse's central widget
  and calls `lend(browse_central_area)`; the reader fills the central
  area beside Anki's sidebar. `leave` calls `give_back()` and shows the
  central widget. The dock resize code (`_fill`, `_dock_host`,
  `_pin_sidebar`'s dock half) is deleted; the sidebar width pin stays.
- **Tab switches** do not move the reader (Q10): the Add page simply shows
  an empty slot while Browse holds it, and the Add tab's empty state
  reads "Open in Browse: <name>"; switching to Browse shows it where it
  was. Leaving viewer mode from any tab gives it back.
- **Insert target.** None needed: the reader's inserts are a `QDrag` and
  the clipboard, and nothing reads the reader's editor (the only readers of
  `sidebar._editor` were the dock's own). `PdfSidebar` is built with
  `editor=None`; `editor._klausmate_pdf_tabs` / `_klausmate_sidebar` /
  `mw._klausmate_pdf_container` are deleted and every reader of them with
  the dock. (Planning ruling, 2026-10-01.)
- **Lifetime.** Browse's teardown (close-all, the ✕ control) runs
  `give_back()` before Anki's `deleteLater` reaches the Browse window:
  `_forget_browser_now` and the viewer-mode close path call it, and a
  `destroyed` connection on the Browse window is the backstop. Profile
  close runs `PdfSidebar.cleanup` through the existing
  `cleanup_all_sidebars`.
- **Chrome.** No `PdfDock`, no `_PanelBar`: the `ReaderTabs` strip goes
  back above the page inside the reader's own layout (where PDF reader
  3/5 first put it). Placement state is dropped from
  `pdf_tabs.json` on read (`load_panel_state`, `migrate_placement`,
  `PANEL_AREAS` and the dock's `placement`/`geom` keys are deleted; a
  settings migration strips the two keys once).

### The Library tree (`library_tree.py`)

A Klaus `QTreeView` over a `QStandardItemModel` built from
`library_sidebar.library_index()`: the `!Library` root, folders, PDFs,
with the same icons (`web/library-*.svg`), the same painted names, the
same dimmed retention % and warning icons. It is NOT an Anki
`SidebarTreeView`.

- **Data and refresh.** One module-level `LibraryTree` registry in
  `library_sidebar` beside `_sidebars`: `refresh_status`,
  `refresh_retention` and `_schedule_refresh` repaint both kinds on the
  same signals as today (`operation_did_execute` with card/note/tag
  changes, the index runner's listener, `pdf_drive._library_changed`).
  The retention means are computed once and shared.
- **Clicks.** Single click on a PDF row → `reader().load_pdf(safe)` (and
  `pdf_handler.touch_last_used`). Click on a folder toggles it. Double
  click does nothing extra.
- **Filter.** The `QLineEdit` filters rows by painted name, case-folded,
  keeping matching rows' ancestors; empty shows all. Folder expansion
  state is per session.
- **Right-click.** The Klaus items `on_context_menu` offers today, reused
  through `library_actions`: root → Import PDFs…, New Folder…; PDF →
  Match Sensitivity…, Retention History…, Show in Finder, Remove from
  Library (only while its file is missing); folder → New Folder…,
  Import PDFs Here…, Rename Folder… and Remove Folder (empty folders
  only). **Not offered:** rename and delete of a PDF, drag-to-move
  between folders. Those are Anki's own tag operations in Browse's
  sidebar (`tag_sync` follows them) and stay there, or happen in Finder.
- **Drops.** The pane accepts Finder drops through `PdfDropFilter`.
- **Footer.** `library_sidebar.Footer` takes a parent widget instead of
  a browser (its one use is `pick_and_import(parent)`).

### Status bar

`StatusBar` gains a second constructor path, `StatusBar(parent,
panes=(left_widget, right_widget))`: ◧ toggles the Library pane's
visibility, ◨ the editor slot's, with `_VisibilityWatcher` on both.
`install_add_tab(page, left, right)` builds it under the splitter. The
dock toggle leaves `_add_toggles`; `install_browser` keeps the ✕ "Close
Browse" control; the Add tab has no ✕ (Close and Escape switch tabs).
`bottom_row` loses `DOCK_CMD`, the `dock_toggle` parameter and
`_dock_toggle`.

### What is removed

| Removed | Where |
|---|---|
| Add dock, `make_add_dock`, `_ensure_add_dock`, `DOCK_PLACEHOLDERS["add"]`, `show_dock("add")`, `toggle_dock`, `dock_shown`'s multi-dock meaning, `register_dock`, `_retarget_pdf`, `klaus-pressed` | `single_window.py` |
| `PdfDock`, `_PanelBar`, `_on_library_button`, `_ensure_sidebar_pdf`, the "library" editor-toolbar action and its button, the per-editor dock install in `on_editor_did_init`, `PANEL_AREAS` | `__init__.py` |
| `load_panel_state`, `migrate_placement`, placement/geom keys | `pdf_handler.py`, `pdf_tabs.json` |
| `_fill`, `_dock_host`, the dock half of `enter`/`leave` | `library_viewer.py` |
| The dock toggle in `_add_toggles`; `DOCK_CMD`, `row_html(dock_toggle)`, `_dock_toggle` | `status_bar.py`, `bottom_row.py` |

The Edit dock stays: `_dock(mw, "edit", …)`, `_new_edit_dock`,
`_reap_edit`, `show_dock("edit")`, `hide_dock`, `save/restore_dock_state`.
`dock_shown` and `focus_in_dock` now mean the Edit dock only.

## Components and files

| File | Change |
|---|---|
| `klausmate/single_window.py` | three pages, `Host.previous`, Add page build (splitter + status bar), `_target("add")`, the open/close/Escape routing, keyboard parking on the Add tab, removals above |
| `klausmate/reader_host.py` (new) | `set_home()`, `reader()`, `lend()`, `give_back()`, `borrowed()`, `release()`; fallback-mode construction under Browse |
| `klausmate/library_tree.py` (new) | `LibraryTree(parent)`: model build from `library_index()`, filter, clicks, context menu, drops; `refresh()` |
| `klausmate/library_sidebar.py` | registry for `LibraryTree` instances beside `_sidebars`; `Footer(parent)`; context-menu item builder shared with the tree |
| `klausmate/library_viewer.py` | `enter`/`leave` lend and give back the reader |
| `klausmate/__init__.py` | removals above; `on_editor_did_init` and its hook go |
| `klausmate/reader_panel.py` (peer's phase 5 home of `PdfSidebar`) | untouched; built with `editor=None` |
| `klausmate/pdf_handler.py` | placement state deleted; migration strips `placement`/`geom` |
| `klausmate/status_bar.py`, `bottom_row.py`, `host_keys.py` | as above |
| `klausmate/web/copilot.js` | the DOM-mounted "Library..." toolbar button (K-056/K-063 block, ~line 140) and its `klausmate:library` pycmd go; `__init__`'s `action == "library"` branch with them |
| `CLAUDE.md`, `AGENTS.md`, `README.md`, `CONTEXT.md` | Add tab, reader host, removals; the "PDF dock" glossary entry becomes "Reader host" |

## Data flow

1. `a` → `dialogs.open("AddCards")` → registered creator builds
   `EmbeddedAddCards` inside the Add page's editor slot →
   `dialog_manager_did_open_dialog` → `host.switch("add")` → keys parked,
   state shortcuts suspended, status bar toggles painted.
2. Click a PDF row → `reader().load_pdf(safe)` → the reader (already a child
   of the reader slot) loads it; its tab strip adds the tab; `last_used`
   touched; `doc_sync` registration as today.
3. Drag a region out of the reader → a `QDrag` lands in whichever editor
   field it is dropped on (Add's, or Browse's while borrowed).
4. Double-click a PDF in Browse's sidebar → `library_viewer.enter` →
   `lend(central_area)`; Esc or a sidebar click → `leave` → `give_back()`.
5. Close on the Add tab → `_CloseFilter` → `host.switch(previous)`.
6. Close-all → Anki destroys Add → `_on_add_destroyed` → placeholder; the
   reader is untouched (it is the page's child, not Add's).

## Error handling

- Every re-parent (`lend`, `give_back`) is wrapped; on failure the reader
  stays where it is and a `print` names the step. A reader whose C++
  object is gone (`RuntimeError`) is rebuilt on the next `reader()` call.
- A `switch("add")` before the host exists or while disabled falls
  through to Anki's stock Add window (the creator's existing fallback).
- `LibraryTree.refresh` runs inside a try; a failed index read leaves the
  previous rows.
- `disable(reason)` additionally gives the reader back if borrowed and
  leaves it under whichever window it is in.

## Testing

Offscreen (`tests/test_add_tab.py`, new, plus existing files):

- `build_host` has three pages; `active_link_js` marks each tab and never
  emits `klaus-pressed`; `Host.previous` tracks the last tab.
- Opening `AddCards` through the registry lands the instance in the Add
  page's editor slot and switches the tab; a user Close switches to
  `previous` and keeps the instance; Escape does the same; Anki's own
  close passes; `_on_add_destroyed` restores the placeholder.
- State shortcuts are suspended on the Add tab and resumed on Decks; a
  bare key pressed with focus in the Library tree does not fire `mw`'s
  shortcut; `d`/`b`/`a` stay live.
- `reader()` builds once, under the reader slot; `lend` moves it into a
  given container; `give_back` restores it; Browse's close triggers
  `give_back`; a `RuntimeError` reader is rebuilt.
- `LibraryTree`: rows mirror `build_index` (root, folders, PDFs, labels,
  retention text); the filter keeps ancestors; a single click on a PDF
  row calls `reader().load_pdf`; the context menu offers exactly the items
  listed above per row kind; the drop filter accepts PDFs.
- `StatusBar(panes=…)`: ◧ and ◨ toggle the given widgets and follow their
  visibility; no dock toggle anywhere; `bottom_row` emits no dock button;
  the bridge-roster pin in `test_bridge_reentrancy` goes back to two
  deferred opens.
- `library_viewer`: `enter` lends, `leave` gives back, tab switches in
  between do not end viewer mode.
- Removal pins: no `PdfDock`, `_PanelBar`, `_on_library_button`, `library`
  editor action, `load_panel_state`, `toggle_dock`, `_retarget_pdf`,
  `_klausmate_pdf_tabs` in the package.
- Migration: `pdf_tabs.json` with `placement`/`geom` loses both on read.
- Files to update: `test_single_window.py` (98), `test_host_keys.py`,
  `test_status_bar.py`, `test_bottom_row.py`, `test_library_sidebar.py`,
  `test_library_viewer.py`, `test_pdf_dock.py` (deleted with the dock),
  `test_reader_tabs.py`, `test_bridge_reentrancy.py`, and any
  `test_dialog_logic.py` / `test_local_model_settings.py` pin naming the
  Library button.

Live checklist (Pouya, after the plan runs; nothing here shows offscreen):

1. The Add tab renders the editor and the reader; typing in a field and
   space do not answer a card.
2. Open a PDF from the tree, drag a region into a field, make a card.
3. Double-click a PDF in Browse: the SAME document appears in Browse's
   central area; `a`, `b`: still there, same page; Esc: cards back and the
   Add tab shows the reader again.
4. Close Browse with ✕ while in viewer mode: no crash, the reader is back
   on the Add tab.
5. Sync (close-all): Add shows its placeholder, the reader keeps its tabs.
6. Switch profile and back: tree, reader and editor return.

## Rulings

- The reader's parent is a page of the host, never the Add instance, so
  Anki's close-all cannot take the webview with it.
- The Add tab does not move the reader on tab switch (Q10 asks for the
  same page on return; moving twice per switch would be the costlier way
  to the same result).
- The Library tree is Klaus's own view, not a second `SidebarTreeView`:
  Anki's tree needs a Browse instance for every click.
- PDF rename/delete and drag-to-move stay Browse-only: they are tag
  operations with Anki's own dialogs and undo.
- Splitter sizes through `saveSplitter`/`restoreSplitter`, Anki's own
  per-profile mechanism, one key.
- The reader stays ONE `PdfSidebar` instance for its whole life, keeping
  `host_key="editor"` and its per-instance `doc_sync` registration
  (`_sync_key`): re-parenting never rebuilds it, so sync and the tab set
  never split (peer's request, 2026-10-01). The rebuild-on-`RuntimeError`
  path is for a dead C++ object only.
- Timing, agreed with the peer session (2026-10-01): Pouya signed off
  the reader's phase 4 trial and the peer is running phase 5 now (delete
  the native renderer; `PdfSidebar` moves from `pdf_viewer.py` to a new
  `klausmate/reader_panel.py` with no re-export). This plan starts only
  after the peer pings that phase 5 is committed, and imports
  `PdfSidebar` from `reader_panel` and `ReaderTabs` from `reader_tabs`.

## Rulings during implementation

- The reader is built on the first Add-tab show (`_on_tab_switch`), so
  last session's tab set is visible before any click; the "Open in
  Browse: <name>" note is a label `reader_host` keeps in the home slot
  (`borrowed_note()`), shown on `lend`, hidden on `give_back`/`release`.
- `open_add()` was dead and is deleted: Anki's `dialogs.open` → the
  registered creator → `dialog_manager_did_open_dialog` is the one route
  into the tab (the toolbar link and `a` both take it).
- A Browse that still holds the reader on Close releases it, home or not
  (fallback mode, and a stock Browse after a mid-session disable); the
  close path reads `reader_host.current()`, which never builds.
- Profile close calls `reader_host.release()`: the profile's readers are
  cleaned up by `cleanup_all_sidebars`, and a cleaned `PdfSidebar` can
  never be reused (its webview is gone for good).
- `PdfSidebar._editor` keeps meaning "the editor this reader belongs to"
  (the peer's Image Occlusion work reads it): the live Add editor at home
  (`set_home_editor`), Browse's editor while lent (`lend(box, editor)`).
- `_inside` / `_hosted_in` walk with `QObject.parent(w)`: Image Occlusion
  Enhanced's `ImgOccEdit` sets `self.parent = <window>`, which shadowed
  the method and crashed `_on_focus_did_change` live.
- The dock toggles, `DOCK_CMD` and the "dock" pane name went in Task 5
  with `toggle_dock`; the bottom row's gear keeps its own hover rule.
- The test fixture for viewer mode nests Browse under the same top-level
  as the home, as the shim does in production.

## Out of scope

- The Edit dock's full-height placement (Pouya's 2026-09-30 report); it
  outlives this design and gets its own fix.
- Deck, tag or notetype picking from the Add tab's sidebar (Q2 option b).
- A second reader (Q3 option a), kept as the contingency below.
- The Lecture panel, the save pipeline, `doc_sync`, the loader.
- Anki's stock windows in fallback mode gain nothing.

## Risks

- **Re-parenting a live pdf.js webview between two containers under
  `mw`.** New: today viewer mode resizes a dock, nothing moves. For it:
  the dock's float/re-dock path re-parents the same webview across
  top-levels and ships; both homes here are under one top-level window,
  which is the condition the August failure violated. Against it: the
  August cards, and no offscreen test can show a black pane. Live
  checklist item 3 is the gate. Contingency if it fails: Q3 option (a),
  two readers, each born in its home (the Add slot, Browse's central
  area) and never moved.
- **Peer overlap.** `__init__.py` (K-320 hold) and `library_viewer.py`
  (peer's Task 13 sizing code, which they agreed goes with the dock). The
  peer has nothing uncommitted there; staging stays by hunk, by name.
- **Keys.** Parking bare keys on a third tab doubles the surface of the
  I2/I3 logic; the tests above pin it per tab.
