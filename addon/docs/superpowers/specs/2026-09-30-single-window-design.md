# Single window: Decks and Browse as tabs, Add as a right panel

Date: 2026-09-30. Status: design approved in conversation, spec awaiting review.

## Goal

Anki opens Add, Browse, and Edit Current as separate top-level windows.
Klaus makes the main window the only window for daily use:

- Two tabs in the main window: **Decks** (Anki's whole main screen: deck
  list, overview, review, unchanged) and **Browse** (Anki's real Browse
  window, embedded).
- One **right dock area** on the main window that persists across both
  tabs, holding **Add** (Anki's real Add window, embedded), **Edit
  Current** (embedded the same way while open), and Klaus's **Library**
  and **PDF** docks, which move here from the Browse window.
- Preferences, Statistics, Deck Options, Card Layout, the card previewer,
  and imports stay windows.

The two pains this removes: window juggling (Cmd-Tab, lost windows,
several things to close) and a sidebar that disappears when you switch
between the deck list and Browse.

## Why the real windows, embedded

Anki's Browse and Add screens are large, and other add-ons (AnKing,
AnkiHub, AMBOSS) attach menus, sidebar entries, and buttons to them
through `browser_will_show` and `add_cards_did_init`. A Klaus-built
Browse would leave those add-ons attaching to Anki's, giving two Browse
screens. Embedding the real instances keeps every add-on working.

Anki's own Add screen is a thin wrapper over three embeddable parts (the
editor, the deck chooser, the notetype chooser), which is why a Klaus-built
Add panel was considered; it was rejected for the same add-on reason and
because one embedding mechanism shared by Browse, Add, and Edit Current is
one thing to keep working across Anki updates, not two.

## The August attempt, and why this one constructs instead of moving

Klaus already shipped a single-window mode once (K-059..K-062, 2026-08-24)
and deleted it the next day (K-090..K-094, commit `a72726d`, "too buggy
to keep"). Its mechanism was the one a first design reaches for: build
Anki's Browse or Add window, suppress its `show()`, re-parent it into a
stack inside the main window. Every native widget rendered; **every
webview inside was black**. Five rounds tried to repair it: nudging
visibility, forcing Chromium page visibility, re-parenting the view
itself, re-binding every view one tick after embedding, and giving each
view its own native window. None worked on Qt 6.9 on macOS. K-094's
closing note named the one route not tried: "construct panes inside mw
from the start".

The cause, as the cards record it: a QtWebEngine view binds its
presentation path to the top-level window it is born under. Anki's
`Browser.__init__` makes the window top-level in its first line and
creates the editor webview a few lines later, so by the time any hook
fires the webview is already bound to a window that will never be shown.
Moving the view afterwards does not rebind it.

So this design never moves a window. It makes Anki construct each window
**as a child of the host from its first line**, so the editor webview is
born under the main window. Two shims do that, both verified offscreen on
2026-09-30 (a child created inside the window reports the main window as
its top-level at creation, the window is not a top-level, it still
accepts docks and survives `restoreGeometry`):

- **Add and Edit Current** call `super().__init__(None, Window)`. Klaus
  registers subclasses `EmbeddedAddCards(AddCards, _Shim)` and
  `EmbeddedEditCurrent(EditCurrent, _Shim)` with Anki's dialog registry.
  `_Shim` sits after the Anki class in the method resolution order, so
  that `super()` call lands in `_Shim.__init__`, which constructs the
  main window as a child of the target container, clears the window flag
  (`setWindowFlags(Widget)`, which Qt's own nested-main-window docs
  prescribe), and adds it to the container's layout. Instances are still
  instances of Anki's class, so every add-on's `isinstance` check and
  hook keeps working.
- **Browse** calls `QMainWindow.__init__(self, None, Window)` explicitly,
  which bypasses the method resolution order. Klaus registers a creator
  that swaps the name `QMainWindow` in Anki's `aqt.browser.browser` module
  for a shim during that one constructor call and restores it in a
  `finally`. Ruling: this is the one scoped module-namespace swap in the
  design, taken because Browse leaves no other seam; it is guarded and
  falls back to Anki's own class.

Registration uses `aqt.dialogs.register_dialog`, the public add-on API
whose docstring exists for this purpose. Anki's `dialogs.open("Browser")`,
the `b`/`a`/`e` shortcuts, and other add-ons' opens all reach the
embedded classes without knowing.

**Gate.** Because the August failure only showed in the live app (the
offscreen frame was perfect while the screen was black), the plan stops
after the shims and the host exist: Pouya restarts Anki, opens Add, and
confirms the editor renders. Nothing else in this design is built until
that is seen.

This reverses the CLAUDE.md rule "Embedding Anki's windows stays
deleted" (written after the August removal), on Pouya's request of
2026-09-30, with a different mechanism. The doc task updates that entry.

## What Anki assumes, and the touchpoints

Every mechanism in Anki's window code assumes the three are independent
top-level windows. These are the places the embedding must handle. Source
references are to Anki's `qt/aqt` (the `anki-main` checkout beside this
workspace).

| # | Assumption | Where | Effect if ignored |
|---|---|---|---|
| T0 | A webview presents through the top-level window it was born under | QtWebEngine on Qt 6.9/macOS; K-090..K-094 | Black editor panes; the August failure. Handled by construction-time hosting, never by re-parenting |
| T1 | "Am I the focused window?" via `current_window() == self` | `browser/browser.py` `on_operation_did_execute`, `on_focus_change` | Embedded Browse never redraws its table cells or refreshes its sidebar after a change |
| T2 | Geometry, dock state, splitter saved and restored per window | `browser.py` `restoreGeom/restoreState`, `addcards.py` `restoreGeom(self, "add")` | Harmless on a child widget (the layout overrides), but must not raise |
| T3 | Close flow: ignore close event, save the editor through JS, then `close()`, `markClosed`, `deleteLater` | `browser.py` `closeEvent/_closeWindow`, `addcards.py` `closeEvent/_close`, `editcurrent.py` | The tab or dock keeps a dangling reference after Anki deletes the instance |
| T4 | `activateWindow()` and `raise_()` on reopen | `__init__.py` `DialogManager.open` | No-ops on a child; the host must switch the tab or show the dock itself |
| T5 | Menu bar: Browse has Edit/View/Notes/Cards/Go; Add and Edit Current keep an Edit menu on macOS only | `browser.ui`, `addcards.py:58`, `editcurrent.py:24` | A child main window's menu bar renders as a strip inside the widget instead of the macOS menu bar |
| T6 | Escape closes Browse | `browser.py` `keyPressEvent` | An accidental Escape tears down the tab |
| T7 | Keyboard: the reviewer's single-key shortcuts are window-scoped shortcuts on the main window; Browse's actions are window-scoped on Browse | `main.py` `applyShortcuts`, `browser.ui` | Once both live in one window they overlap (flags, forget, set due, delete) and Qt fires neither of an ambiguous pair; space in an Add field could answer a card |
| T8 | Anki closes all three before sync, profile switch, and quit, then disables the main window | `main.py` `unloadCollection`, `DialogManager.closeAll` | Accepted: the tab and dock go blank and come back on next use |

Hook timing still matters for the post-construction fixes:
`browser_will_show(browser)` fires inside `Browser.__init__` before
`restoreGeom` and `show()`; `add_cards_did_init(addcards)` fires before
`show()`; `editor_did_init(editor)` fires inside `Editor.__init__`. Klaus
uses them to hide the child's menu bar, install the Escape and close
filters, and connect `destroyed`. The window is already a child by then.

## Architecture

### Host layout

`main.py` lays the main window out as a vertical stack: toolbar webview,
main webview, bottom webview, inside `form.centralwidget`. Klaus rebuilds
that stack once, at `main_window_did_init`:

```
centralwidget
└─ QVBoxLayout
   ├─ toolbarWeb                      (unchanged, the tab strip)
   └─ QStackedWidget  "host"
      ├─ page "decks": QVBoxLayout(mw.web, mw.bottomWeb)   (Anki's objects, only re-parented)
      └─ page "browse": QVBoxLayout(<placeholder | embedded Browser>)
```

`mw.web`, `mw.bottomWeb`, and `mw.toolbarWeb` keep their identities; only
their parent widget changes. The Decks page is Anki's whole state machine
and is never touched again. The Browse page holds a placeholder until
Browse is first opened.

The right dock area belongs to the main window itself (`mw.addDockWidget`),
with dock nesting on and Klaus's docks tabbed together: Add, Edit Current
(while open), Library, PDF.

### Construction-time hosting

`register(mw)` runs once at init and replaces three creators in Anki's
dialog registry:

- `"Browser"` → `make_browser(mw, card=None, search=None)`: preflight
  (the attributes the touchpoints rely on exist on the classes and on
  `mw`), then construct `aqt.browser.browser.Browser(mw, card, search)`
  with the module's `QMainWindow` name swapped for `_Shim` targeting the
  Browse page, restored in a `finally`. Anki's own `__init__` then runs
  unchanged and its `show()` shows a child.
- `"AddCards"` → `EmbeddedAddCards`, targeting the Add dock's content.
- `"EditCurrent"` → `EmbeddedEditCurrent`, targeting a fresh Edit dock,
  tabbed with Add and raised. When it closes (Close button, Ctrl+Return,
  or Anki's close-all), its dock is removed and Add is raised again.

The post-construction fixes ride the existing hooks: hide the child's
menu bar (T5), connect `destroyed` to the container's reset-to-placeholder
(T3), install the Escape filter on Browse (T6) and the close filter on
Edit Current.

If a shim raises, the creator constructs Anki's own class instead (a stock
window), and `disable(reason)` runs (see Fallback).

### Navigation

- Anki's toolbar links are the tabs. `dialog_manager_did_open_dialog(dm,
  name, instance)` fires on every `dialogs.open`, including from other
  add-ons and from `b`/`a`/`e`: for `"Browser"` switch to the Browse tab;
  for `"AddCards"` show the right dock and raise Add; for `"EditCurrent"`
  raise its dock. Anki's own `reopen` still runs the search or re-picks
  deck and notetype (T4).
- The Decks link (`d`, or the "decks" toolbar id) switches to the Decks
  tab and then runs Anki's handler.
- `b` on the Browse tab focuses the search box (Anki's `reopen` already
  does); `a` with the panel open focuses the first field (Anki's `reopen`
  already does). Nothing toggles.
- Active indicator: the toolbar page gets a `klaus-active` class on the
  `#decks` or `#browse` link, and `klaus-pressed` on `#add` while the dock
  is shown, via `top_toolbar_did_redraw` and a small eval on each switch.
- Right dock toggle: the Browse status bar's existing right-side toggle and
  a matching toggle in the Decks bottom row both show or hide the host's
  right dock area. (Assumption not grilled: the Decks bottom row gains one
  toggle next to the gear. Flagged for review.)
- Escape in the Browse tab does nothing: an event filter on the embedded
  Browse swallows Escape (T6).
- The Add panel's Close button hides the dock; the instance stays alive
  with its sticky fields and history. Implemented by reconnecting
  `addcards.closeButton.clicked` from `close` to the dock's hide. The dock
  title bar's own close does the same. Anki's `closeWithCallback` (used by
  close-all) still destroys it (T8).
- The user can close the Browse tab (a close control on the Browse page's
  bottom bar). That calls `browser.close()`, which runs Anki's
  save-then-close, then the page shows its placeholder.

### Menus (T5)

While the Browse tab is active, Browse's menus (Edit, View, Notes, Cards,
Go, and the consolidated Add-ons menu from `addons_menu.py`) are inserted
into the main window's menu bar before Help; on leaving the tab they are
removed again. This reuses the insert-before-Help logic from
`addons_menu.py`. Browse's own menu bar stays hidden. Add's and Edit
Current's macOS Edit menus stay hidden; the main window's Edit menu serves.

Removing the menus also deactivates their shortcuts: Qt only fires a menu
action's shortcut when the action reaches a visible menu bar. This is what
scopes Browse's keyboard to its tab.

### Keyboard (T7)

- Browse's actions fire only while its menus are in the host bar, i.e.
  only on the Browse tab (above).
- The reviewer's, overview's, and deck list's state shortcuts: Klaus
  records the list from `state_shortcuts_will_change(state, shortcuts)`.
  On leaving the Decks tab it calls `mw.clearStateShortcuts()`; on
  returning it calls `mw.setStateShortcuts(recorded)`. Both are public.
- While the Decks tab is active and focus is inside the right dock, an
  application-level event filter accepts `ShortcutOverride` for any key in
  the recorded state list, so the key is delivered to the editor as typing
  and never reaches the shortcut map. Space, Enter, digits, and letters
  therefore type into Add and Edit Current fields.
- Add's own Ctrl+Return and history shortcut are window-scoped on the Add
  widget and are active only while the dock is visible, as Qt already
  handles.

Open verification, not a decision: how Anki's editor webview itself
handles `ShortcutOverride` for space and single letters. The filter above
holds regardless; the test in the plan must cover a space keypress with
focus in the embedded editor while a review is showing.

### Refresh (T1)

Browse skips its own redraw because `current_window()` returns the main
window, never the embedded Browse. Klaus appends its own handlers after
Browse's (Browse registers in `setupHooks`, which runs before
`browser_will_show`):

- `operation_did_execute` → if the Browse tab is showing, call
  `browser.table.redraw_cells()` and `browser.sidebar.refresh_if_needed()`.
- `focus_did_change` → same, when focus lands inside the Browse page.

No monkeypatching of `current_window`. The main window's own focus check
now returns true while focus is in the Browse tab or the dock, so it
refreshes immediately instead of fading; that is acceptable and cheap.

### Lifecycle

- Browse is created lazily on first open and kept alive.
- Anki's close-all (sync, profile switch, quit) destroys Browse, Add, and
  Edit Current; `destroyed` resets the page or dock to its placeholder;
  the next open recreates and re-embeds (T8).
- Startup: Decks tab, right dock closed. Dock widths and tab order inside
  the dock area are saved with `mw.saveState` under a Klaus key on close
  and restored at init, then the dock area is hidden.
- Klaus's Library and PDF docks are created on the main window at init
  instead of on the Browse window (`__init__.py`, the `browser.addDockWidget`
  and `PdfDock` attach paths). Their existing placement config keys keep
  their meaning; "left" now means the host's left dock area.

### Fallback and notice

A config flag `single_window` (default `true`) turns the whole feature
off, returning stock Anki windows.

Every embedding step is wrapped. If the preflight or any step raises:

1. Undo: `widget.setParent(None, Qt.WindowType.Window)` and `widget.show()`
   so the instance is a normal window again.
2. Set a session flag that disables further embedding for this run.
3. Notice, once per session: a tooltip on the toolbar and a sticky error
   line in the task readout (`tasks.begin("single_window")` then
   `tasks.end("single_window", "Single window unavailable: <reason>",
   error=True)`), which stays until the next task, as failures already do.

Klaus never leaves a half-embedded instance: the undo runs even if the
failure happened after re-parenting.

## Components and files

- `klausmate/single_window.py` (new): host layout builder, the
  construction shims and registry creators, placeholders, navigation
  hooks, menu swap, dock area, lifecycle, fallback. The name matches the
  deleted August module on purpose; its CLAUDE.md entry is rewritten. Pure helpers above the divider (which links are active, which
  menus to move, preflight attribute list, key-set membership), aqt glue
  below, as in `bottom_row.py`.
- `klausmate/host_keys.py` (new): the state-shortcut recorder, the
  clear/restore on tab switch, the `ShortcutOverride` filter.
- `klausmate/__init__.py`: Library and PDF dock attach moves to the main
  window; `single_window.setup()` and `host_keys.setup()` guarded like the
  other setup blocks.
- `klausmate/addons_menu.py`: expose the insert-before-Help helper for
  reuse.
- `klausmate/bottom_row.py`, `klausmate/status_bar.py`: right-dock toggle
  and the Browse tab close control.
- `klausmate/top_bar.py`: active-link classes on the toolbar page.
- `klausmate/config.json`, `config.md`: `single_window`.
- Docs: `CLAUDE.md`, `AGENTS.md`, `README.md` bullets.

## Data flow

1. Init: rebuild the central stack; create the right dock area and
   Klaus's docks; register hooks.
2. User presses `b` or clicks Browse: Anki's `dialogs.open("Browser")` →
   Klaus's registered creator → `Browser.__init__` with the shim (child of
   the Browse page from line one; editor webview born under the main
   window) → `browser_will_show` (menu bar hidden, filters, `destroyed`)
   → Anki's `show()` → `dialog_manager_did_open_dialog` → switch tab, move
   menus in, state shortcuts off.
3. A change anywhere: `CollectionOp` → `operation_did_execute` → Browse's
   handler (skips redraw) → Klaus's handler (redraws if the tab shows).
4. Sync: `closeAll` → Browse `closeWithCallback` → save → `close` →
   `deleteLater` → `destroyed` → placeholder; menus removed; state
   shortcuts restored when the Decks tab is active again.

## Error handling

- Preflight failure or a shim exception → the creator falls back to
  Anki's own class, and `disable` runs.
- Black editor in the live app (the August symptom) → the plan's gate
  stops the work; the flag is turned off and the fallback is stock Anki.
- `destroyed` arriving while the tab is active → placeholder, menus
  removed, shortcuts restored.
- A hook receiving an instance that is already a child (an add-on calling
  `dialogs.open` twice, or reopen) → no-op.
- The feature never raises into Anki: every hook body is try/except with a
  `[klausmate]` print, as elsewhere in the add-on.

## Testing

Offscreen Qt tests with the existing `anki_stubs`, in the style of
`tests/test_addons_menu.py` and `tests/test_bottom_row.py`:

- Host layout: after rebuild, `mw.web` and `mw.bottomWeb` are the same
  objects, inside the Decks page; the toolbar is above the stack.
- Shims: a fake Anki class using `super().__init__(None, Window)` and a
  fake module whose class calls `QMainWindow.__init__(self, None, Window)`
  explicitly; through the shims, a child widget created in their
  `__init__` reports the host's main window as its top-level, the instance
  is not a window, is still an instance of the original class, accepts a
  dock, and survives `restoreGeometry`. The module's `QMainWindow` name is
  restored after construction, also when `__init__` raises.
- Preflight: a missing attribute makes the creator return Anki's own class
  (a top-level window), set the fallback flag, and record the sticky error
  task.
- Live gate (not automatable): the editor renders in Anki after a restart.
- Destroyed: deleting the embedded widget restores the placeholder.
- Menus: switching to Browse inserts its menus before Help and removes
  them on switching back; Browse's own menu bar stays hidden; an action
  shortcut fires on the Browse tab and not on the Decks tab.
- Keyboard: the recorded state list is cleared on leaving Decks and
  restored on return; with focus in a widget inside the right dock, a
  space `ShortcutOverride` is accepted and a state shortcut on the main
  window does not fire; with focus in the Decks page it does.
- Navigation: `dialog_manager_did_open_dialog("Browser")` switches the
  tab; `("AddCards")` shows the dock and raises Add; Escape in the Browse
  page is swallowed; the Add Close button hides the dock and the instance
  survives.
- Toolbar page (node DOM test, as `dashboard_js_dom_test.js`): active and
  pressed classes follow the switch.
- Bridge rule: every js-message handler that opens a window defers with
  `QTimer.singleShot(0, ...)`; the roster in
  `tests/test_bridge_reentrancy.py` grows by the new handlers.

Manual check in Anki after the plan lands: one AMBOSS, AnKing, and
AnkiHub menu each appears under Add-ons on the Browse tab; the Browse
sidebar still shows their entries; sync with the Browse tab open blanks
and restores it.

## Rulings during implementation

- Construction-time hosting replaces re-parenting; one scoped swap of the
  `QMainWindow` name in the class's module during the constructor call
  (see "The August attempt"), applied to every hosted class and inert
  where the class uses `super()`.
- The running Anki is 26.09.2 and registers five hosted names (`Browser`,
  `AddCards`, `NewAddCards`, `EditCurrent`, `NewEditCurrent`); classes are
  read from the registry at register time, never imported by module path.
  The new Add screen has no `closeButton`, so the Add preflight is
  `editor`, `close`, `form`.
- Add's Close is a close filter, not a button reconnect: a user-initiated
  Close event hides the dock; Anki's own teardown passes.
- The host layout is REUSED, never detached: AMBOSS and AnkiHub wrap
  `mw.web` in a splitter inside `mw.mainLayout` and locate it there, so
  `build_host` moves whatever items the layout holds and makes
  `mw.mainLayout` the Decks page's layout. (The first live run crashed on
  exactly this.)
- State shortcuts are suspended by disabling them, not by clearing and
  re-setting (re-setting re-fires the hook for every add-on).
- Browse's consolidated Add-ons menu is retitled "Browse Add-ons" while it
  sits in the host bar.
- Edit Current's dock is reaped only once the dialog registry shows it
  closed (its close saves the note asynchronously first).
- A third pane toggle ("Right Sidebar") joins Browse's status bar, and the
  Decks bottom row gets the same toggle after the gear; the editor-column
  toggle is untouched.
- The PDF dock's host is `host_for(editor.parentWindow)`: the main window
  for all three hosted screens, so one PDF dock is shared.
- Live gate passed 2026-09-30 on Anki 26.09.2 with AMBOSS and AnkiHub
  active: both editors render inside the main window.
- Final review (2026-09-30): a nested main window's NATIVE menu bar
  attaches to the main window's NSWindow on macOS and replaces Anki's
  whole menu bar; `menuBar().hide()` is a no-op for a native bar. So
  `AA_DontUseNativeMenuBar` is set for exactly the constructor call that
  creates the hosted window's bar, the bar is then made non-native and
  hidden, and no hide site ever calls `menuBar()` (which creates one).
- While the Browse tab shows, host-bar actions whose key Browse also uses
  (Cmd+Shift+P would switch profiles from inside Browse) or whose key is
  bare (F, /) are parked, and the main window's permanent bare-key
  shortcuts (`d s a b t y`, which fire from a table or tree) are
  disabled; all return on leaving the tab. The spec's keyboard section
  named only the state shortcuts.
- The shared PDF dock follows focus: it inserts into the editor of the
  hosted window that holds focus, not the last one initialised.
- A preflight miss no longer destroys the window it just built: the
  hosted instance is kept and only NEW windows fall back to stock.
- `disable` keeps live instances in Anki's dialog registry so close-all
  still sees them.
- The PDF dock keeps its own placement; it is tabbed with Add only when it
  sits in the right area.

## Out of scope

Preferences, Statistics, Deck Options, Card Layout, previewer, and import
dialogs stay windows. A single shared bottom bar across tabs is a later
refinement; each tab keeps its own. No changes to the review screen's
answer row.
