# Status bar — design

Agreed with Pouya on 2026-09-30.

## Goal

A thin bar along the bottom of Anki's windows, like VS Code's status bar:
one place for layout toggles, settings, and every process Klaus or Anki
is running. Why: work that takes minutes (embedding, syncing, a folder
scan) should be visible and stoppable wherever you are, and the controls
scattered across Browse's search row, the Library footer and a
main-window-only indexing dock belong in one predictable spot.

## Scope

- **Windows:** the main window and Browse. Add Cards and Edit Current
  are not included.
- **In the bar:** Browse's left-sidebar and card-editor toggles (Browse
  only), a progress readout of running tasks, and one gear with a menu
  holding KlausMate Settings and Anki Settings.
- **Out of scope** (separate cards):
  - moving OCR repair off the main thread; it joins the bar afterwards;
  - a new job for the top-bar Klaus star, which stays;
  - Anki's own modal "Processing…" popups, which are left alone and not
    mirrored in the bar;
  - VS Code's bottom-panel and customize-layout icons.

## Approach

Each window uses Qt's own status bar: `QMainWindow.statusBar()`, which
creates one (Anki's main.ui has none — the hidden `form.statusbar` is the
profile manager's), and a `QStatusBar` added to Browse. Qt keeps it
at the bottom through resizes and dock changes, and nothing of Anki's is
patched. One shared task tracker feeds both bars. An HTML bar in
`mw.bottomWeb` was rejected: it exists only in the main window and hides
during review. So was a custom widget spliced into Browse's layout: that
layout re-splits when docks change (see K-317).

## Units

### `tasks.py`: the task tracker (aqt-free)

The one list of running processes.

- `begin(key, label, cancel=None) -> None`: start or replace a task.
  `cancel` is a zero-argument callable, or None when the task can't be
  cancelled.
- `update(key, done=None, total=None, label=None) -> None`: report
  progress. `total` None or 0 means unknown (an animated bar).
- `end(key, message="") -> None`: finish. A non-empty `message` stays
  visible for 4 s as the task's last line ("Anemia indexed",
  "Cancelled", "Ollama is not reachable"), then disappears.
- `snapshot() -> list[Task]`: the tasks, newest first. `Task` is a
  NamedTuple: `key`, `label`, `done`, `total`, `cancellable`, `message`,
  `started`.
- `cancel(key) -> None`: run the task's cancel callable.
- `add_listener(fn)` / `remove_listener(fn)`: `fn(snapshot)` after every
  change.
- `clear()`: called on `profile_will_close`.

Thread rule: `begin`, `update` and `end` may be called from any thread.
They only record the change and hand the listener notification to the
main thread, through an injected `run_on_main` (in production
`mw.taskman.run_on_main`; in tests, a direct call). A listener that
raises is logged and skipped, and never breaks the reporter.

### Sources: who reports

| Process | Where | Key | Progress | Cancel |
|---|---|---|---|---|
| Indexing (PDF embed, matching, card index) | `index_queue`'s own listener turns `RunnerState` into one task | `index` | `done`/`total`; the label comes from `status_line`, and "+N queued" shows in the list | `index_queue.cancel_all` |
| Library folder scan (failures only — the user asked for the running scan to stay out of the bar) | `pdf_drive.start_library_rescan` | `rescan` | — | — |
| Retention % refresh | `library_sidebar.refresh_retention` | `retention` | unknown | — |
| Collection sync | `gui_hooks.sync_will_start` / `sync_did_finish` | `sync` | unknown | — |
| Media sync | `gui_hooks.media_sync_did_start_or_stop` / `media_sync_did_progress` | `media` | counts when Anki reports them, otherwise unknown | — |
| Ollama runtime install, model pull | `manage_models`' runtime ops (their existing progress callbacks) | `ollama` | percent | — |

Every source wraps its report in try/except, so a failing report can't
break the work it describes. A task whose job crashes is ended from that
job's failure path, with the error as its message and `error=True`: a
failure stays in the bar, in red, until the next task begins (a plain
end message lingers 4 s). A task younger than `SHOW_DELAY_S` (0.5 s) is
not drawn, so quick sync/retry blips never flash the bar.

### `status_bar.py`: the bar widget

`StatusBar(QWidget)`, one class, installed as a permanent widget in the
window's `QStatusBar`. It is 28pt tall, the macOS title bar's height (the user asked for a match), and always visible.

Order, as the user asked after the first build: gear at the left, then
the readout, the toggles at the far right. Every icon is painted at
16 px in a 22 px button (no chip at rest or when on; Tab focus only, so
a click leaves no ring).

- **Far right, main window (added on request):** the deck list's and
  deck overview's bottom-row buttons, moved out of `mw.bottomWeb` (which
  is hidden on those screens). Labels, tooltips and commands are parsed
  from Anki's own HTML, so add-on additions come along; a click goes
  through `webview_did_receive_js_message` then the installed link
  handler, exactly like Anki's button. Review keeps its answer buttons
  in Anki's row. A button that isn't a plain `pycmd` keeps Anki's row.
- **Far right, Browse only:** two checkable icon buttons.
  - ◧ shows and hides Anki's sidebar dock (`browser.sidebarDockWidget`).
  - ◨ shows and hides the card editor column.
  - The logic moves here from `browse_toggles._install_browser_sidebar_toggle`
    and `_PaneToggle`. That includes staying in step with visibility
    changes made elsewhere: ⌘⇧F, the View menu, and Anki hiding the
    editor for a multi-card selection.
  - The icons are new theme-aware SVGs in VS Code's layout style.
- **Left, after the gear, the task readout:**
  - a small `QProgressBar` (about 120 px): determinate when `total` > 0,
    indeterminate otherwise;
  - the newest task's label, then "+N more" when several run;
  - when idle, only a lingering end message, or nothing.
- **Clicking the readout** opens a popup (a `Qt.Popup` frame, never a
  modal dialog) anchored above the bar. It lists every task with its
  label, its own bar and a ✕ when it can be cancelled, and closes on an
  outside click.
- **Far left, one gear** (painted, no menu arrow): it opens a menu with
  - **KlausMate Settings…** (`manage_models_dialog`, the Tools-menu
    entry's target);
  - **Anki Settings…** (`mw.onPrefs`).
- **Theme:** new `theme.status_bar_qss(night)`, tokens only: the chrome
  background with a `grey_light` hairline on top, muted 11–12 px text,
  and the progress chunk in the accent colour. It re-applies on
  `theme_did_change`.

**Install:**
- `profile_did_open`: show `mw.statusBar()`, add a `StatusBar`.
- `browser_will_show`: `browser.setStatusBar(QStatusBar())`, add a
  `StatusBar` with toggles.
- Each bar subscribes to the tracker and unsubscribes when its widget is
  destroyed. Install failures log one line and leave the window as it
  was.

## Removed

- `index_queue._StatusDock` and its dock plumbing (`_ensure_dock`,
  `_render_dock`, `_hide_dock`, `_on_dock_button`, `dock_button_label`).
  The main window's bar replaces it. `status_line` stays, as the index
  task's label.
- The Library sidebar footer's status line and ✕. The footer keeps only
  "Import PDFs…".
- The two toggle buttons `browse_toggles` puts beside Browse's search
  box. `_reset_browse_layout_to_defaults` stays.

## Testing

Real PyQt6, offscreen:

- **`tasks`:** begin, update and end; replace by key; newest-first order;
  the message lingers and then expires (injected clock); listeners
  called on main (an injected `run_on_main` records the calls); a
  raising listener is isolated; `clear`; `cancel` calls the callable.
- **Bar:**
  - In a Browse-shaped `QMainWindow`: the toggles flip the sidebar and
    editor and follow outside visibility changes; the gear menu has both
    actions and they call their targets (stubbed).
  - Determinate versus indeterminate bar; "+N more"; the popup lists
    tasks and ✕ calls `tasks.cancel`.
  - Theme QSS carries no literal hex.
- **Sources:**
  - a `RunnerState` sequence produces one `index` task that ends with the
    runner's message;
  - the sync and media-sync hook handlers begin and end their tasks;
  - `start_library_rescan` reports nothing while it runs, and a
    failure as a sticky `rescan` error.
- **Removals:** `_StatusDock` is gone; the footer has no status label;
  `browse_toggles` installs no search-row toggles; no app-modal `exec()`
  in the new files.
