# Status Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a VS Code-style bottom status bar to Anki's main window and Browse. It carries the Browse layout toggles, one settings gear, and a progress readout of every running process.

**Architecture:**
- An aqt-free task tracker (`klausmate/tasks.py`) is the single list of running processes.
- One `StatusBar` widget (`klausmate/status_bar.py`) draws it inside each window's native `QStatusBar`.
- Sources report through three calls: `begin`, `update` and `end`.
- The old surfaces are deleted: the indexing dock, the footer status line and the search-row toggles.

**Tech Stack:** Python 3.9-compatible source (`from __future__ import annotations`), PyQt6 via `aqt.qt`, Anki `gui_hooks`. The tests run on real PyQt6 offscreen with the `klaus-test` harness.

**Spec:** `docs/superpowers/specs/2026-09-30-status-bar-design.md`

## Global Constraints

- **Dialogs:** no app-modal `exec()`. Dialogs and popups are `open()`/`show()`/`popup()`. `QMenu.exec` is allowed; a `Qt.Popup` frame is not a dialog.
- **Colours:** UI files never hardcode colours. Every colour comes from `theme` tokens, and new QSS lives in `theme.py`.
- **Module layout:** `tasks.py` is aqt-free. `status_bar.py` keeps pure helpers above an `# ── aqt glue ──` divider. Qt is imported from `aqt.qt`.
- **Error handling:** wrap every Qt call and every source report in `try/except` and log `print(f"[klausmate] …")`. A failing report must never break the work it describes.
- **Tests:** never touch the real `user_files`. Run each file with `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/<file>.py` from the repo root.
- **Commits:** another session has uncommitted edits in `klausmate/manage_models.py`, `klausmate/top_bar.py`, `tests/test_top_bar.py` and `board/`. Stage your own files by name only. For `manage_models.py`, stage only your hunk by building a patch against HEAD and running `git apply --cached`.
- **Timing and size:** a finished task's message lingers 4 s (`tasks.LINGER_S = 4.0`). The bar is 22–24 px tall and its progress bar about 120 px wide.
- **Toggle icons:** reuse `browse_toggles._PaneToggle`. It already paints a theme-token, VS Code-style layout glyph (a panel outline with the side column filled when on), so it stands in for the spec's "new theme-aware SVGs".
- **Scope:** Main window and Browse only. There are no bottom-panel or customize-layout icons, and Anki's own "Processing…" popups are not mirrored.

## Review Focus

1. **Browse closed while a task runs:** the destroyed bar's listener is gone. The next `tasks.begin/update/end` raises nothing and updates the main window's bar. (Task 2 test.)
2. **A very long task label** (a PDF named with 200 characters): the readout elides it in the middle and the bar never grows past the window. (Task 2 test.)
3. **Updates from a worker thread** (media-sync progress, indexing progress): listeners run only through `run_on_main`, never inline on the reporting thread. (Task 1 test.)
4. **A task without a cancel callable:** its popup row has no ✕, and `tasks.cancel(key)` on it is a silent no-op. (Tasks 1 and 2.)
5. **Profile closed mid-sync or mid-index:** `tasks.clear()` empties the list. The next profile's bars start idle and no stale "Syncing…" is left behind. (Task 1 test, plus the Task 3 hook registration.)

---

### Task 1: The task tracker

**Files:**
- Create: `klausmate/tasks.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces:
  - `Task(NamedTuple)`: `key: str`, `label: str`, `done: int`, `total: int`, `cancellable: bool`, `message: str`, `started: float`. A running task has `message == ""`; an ended one carries its message.
  - `begin(key: str, label: str, cancel: Callable[[], None] | None = None) -> None`
  - `update(key: str, done: int | None = None, total: int | None = None, label: str | None = None) -> None`. A key that isn't running is ignored.
  - `end(key: str, message: str = "") -> None`
  - `snapshot() -> list[Task]`: newest `started` first, with ended tasks older than `LINGER_S` dropped.
  - `cancel(key: str) -> None`
  - `add_listener(fn: Callable[[list[Task]], None]) -> None` and `remove_listener(fn)`
  - `clear() -> None`
  - Module seams: `LINGER_S = 4.0`, `clock: Callable[[], float] = time.monotonic`, and `run_on_main: Callable[[Callable[[], None]], None]`, which defaults to calling the callable directly.

- [ ] **Step 1: Write the failing tests.** Use `tests/test_tasks.py` with `sys.path.insert(0, ".claude/skills/klaus-test/scripts")`, `from anki_stubs import check, install, report, section`, `install()`, then `tasks = importlib.import_module("klausmate.tasks")`. Set `tasks.clock` to a mutable fake clock (`now = [100.0]; tasks.clock = lambda: now[0]`).
  - **Begin, update, end:** `begin("a","A")`, then `update("a", done=3, total=10)`. Expect `snapshot()[0] == Task("a","A",3,10,False,"",100.0)`.
  - **Replace by key:** a second `begin("a","A2")` leaves exactly one task, labelled `"A2"`.
  - **Newest first:** tasks begun at 100 and then 101 come back in the order `[101-task, 100-task]`.
  - **Linger:** `end("a","Done")`. Expect `snapshot()[0].message == "Done"`. After `now[0] += 4.1`, the task is gone.
  - **Silent end:** `end("b")` with no message removes it immediately.
  - **Update of an unknown key:** `update("zz", done=1)` changes nothing and raises nothing.
  - **Cancel:**
    - `begin("c","C", cancel=lambda: hits.append(1))`, then `cancel("c")`. Expect `hits == [1]` and `snapshot()[0].cancellable is True`.
    - `cancel("a")` on a task without a callable is a no-op.
  - **Listeners go through `run_on_main` (Review Focus 3):** set `queued=[]` and `tasks.run_on_main = queued.append`, add a listener that records calls, then `begin("d","D")`. The listener has not been called yet and `len(queued) == 1`. After `queued[0]()`, the listener was called once with a list whose head has key `"d"`.
  - **Raising listener isolated:** a listener that raises doesn't stop a second listener, and `begin` doesn't raise.
  - **`clear()` (Review Focus 5):** `snapshot() == []`, and listeners are notified once with `[]`.

- [ ] **Step 2: Run it and watch it fail.**
  Run: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_tasks.py`
  Expected: `ModuleNotFoundError: klausmate.tasks`.

- [ ] **Step 3: Implement `klausmate/tasks.py`.** Hold a module dict `key -> Task` plus `key -> cancel callable`, guarded by a `threading.Lock`. Every mutator updates under the lock, takes `snapshot()`, and then calls `run_on_main(lambda: _notify(snap))`. `_notify` calls each listener in `try/except` and logs `[klausmate] task listener failed: …`. Add a module docstring stating the thread rule.

- [ ] **Step 4: Run it and watch it pass.** Same command. Expected: `N passed, 0 failed`.

- [ ] **Step 5: Commit.** `git add klausmate/tasks.py tests/test_tasks.py && git commit -m "Status bar 1/6: task tracker"`

---

### Task 2: The bar widget

**Files:**
- Create: `klausmate/status_bar.py`
- Modify: `klausmate/theme.py`, adding `status_bar_qss` beside `muted_label_qss`
- Test: `tests/test_status_bar.py`

**Interfaces:**
- Consumes:
  - from Task 1: `tasks.snapshot`, `add_listener`, `remove_listener`, `cancel`, `Task`, `LINGER_S`;
  - `browse_toggles._PaneToggle(side: str, pane: str, checked: bool)` and `browse_toggles._VisibilityWatcher(widget, callback)`, both as they are today.
- Produces:
  - `theme.status_bar_qss(night: bool) -> str`: styles `QWidget#KlausStatusBar` on the `chrome` token, with `border-top: 1px solid {grey_light}`, `QLabel` text in `text_muted` at 11px, and a `QProgressBar::chunk` in `blue` (the accent).
  - `readout_text(tasks: list[Task]) -> str`: pure, above the divider.
    - Empty: `""`.
    - One running task: its label.
    - Several: `f"{newest.label}  +{n-1} more"`, where n counts running tasks.
    - Only lingering tasks: the newest message.
  - `class StatusBar(QWidget)` with `__init__(self, window, browser=None)`, where `browser` is a Browse window or None. Methods: `refresh(tasks: list[Task]) -> None` and `apply_theme() -> None`. Attributes:
    - `sidebar_btn` and `editor_btn`: `_PaneToggle`, or None outside Browse or when the pane isn't found;
    - `progress: QProgressBar`
    - `label: QLabel`
    - `gear: QToolButton`, with its menu actions in `gear.menu().actions()` titled exactly `"KlausMate Settings…"` and `"Anki Settings…"`;
    - `popup`: the task-list frame, or None.
  - `open_task_list() -> None`: builds a `Qt.WindowType.Popup` `QFrame`. Each row has the task label, a small `QProgressBar`, and a `QToolButton` titled `"✕"` only when `task.cancellable`, wired to `tasks.cancel(task.key)`. It opens with `move(...)` above the bar and `show()`.

- [ ] **Step 1: Write the failing tests.** Use real PyQt6 with the `aqt.qt` shim from `tests/test_library_viewer.py` (copy its `shim`/`_ga` block). Stub these before the import: `sys.modules["klausmate"].manage_models_dialog = lambda: calls.append("klaus")`, and a stand-in `mw` with `onPrefs = lambda: calls.append("anki")` (set through the `aqt` stub's `mw`).
  - **`readout_text`:**
    - `[]` gives `""`.
    - One running task gives its label.
    - Three running give `"Newest  +2 more"`.
    - Only an ended one with message `"Anemia indexed"` gives `"Anemia indexed"`.
  - **Browse-shaped window:** a `QMainWindow` with a left `QDockWidget` as `sidebarDockWidget`, and `form = SimpleNamespace(splitter=…, fieldsArea=…)` built as a `QSplitter` holding a table widget and an editor-column widget that contains `fieldsArea`. `bar = StatusBar(win, browser=win)` adds it with `win.statusBar().addPermanentWidget(bar, 1)`, then `win.show()`.
    - `bar.sidebar_btn.click()` hides the dock; clicking again shows it.
    - `win.sidebarDockWidget.hide()` from outside leaves `bar.sidebar_btn.isChecked() is False`.
    - `bar.editor_btn.click()` hides the editor column.
  - **Main-window bar:** `StatusBar(QMainWindow())` has `sidebar_btn is None and editor_btn is None`.
  - **Gear:** the menu titles are `["KlausMate Settings…", "Anki Settings…"]`. Triggering each gives `calls == ["klaus", "anki"]`.
  - **Progress:**
    - `refresh([Task("i","Anemia — Embedding",3,10,True,"",1.0)])`: `progress.maximum() == 10`, `value() == 3`, label text `"Anemia — Embedding"`, progress visible.
    - A task with `total 0`: `progress.maximum() == 0` (indeterminate).
    - `refresh([])`: progress hidden, label `""`.
  - **Long label elided (Review Focus 2):** a 200-character label leaves `bar.sizeHint().width() <= 600`, and `"…" in bar.label.text()`.
  - **Popup:** after `refresh` with two tasks (one cancellable), `open_task_list()` shows exactly one `"✕"` button (Review Focus 4). Clicking it calls `tasks.cancel` with the cancellable key: monkeypatch `tasks.cancel` to record.
  - **Listener life (Review Focus 1):** create a bar, `bar.deleteLater()`, send posted `DeferredDelete` events, then `tasks.begin("x","X")`. Nothing raises, and `tasks._listeners` no longer holds the deleted bar's callback.
  - **Theme:** `status_bar_qss(False)` and `status_bar_qss(True)` contain `QWidget#KlausStatusBar`, and every `#rrggbb` in them belongs to that palette's values (copy the check from `tests/test_theme.py`).

- [ ] **Step 2: Run it and watch it fail.**
  Run: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_status_bar.py`
  Expected: `ModuleNotFoundError: klausmate.status_bar`.

- [ ] **Step 3: Implement.**
  - **`status_bar_qss` in `theme.py`:** tokens only.
  - **`status_bar.py`:**
    - `readout_text` above the divider.
    - Below it, `StatusBar` with objectName `KlausStatusBar`, `WA_StyledBackground`, fixed height 22, and a horizontal layout, left to right: `[sidebar_btn][editor_btn]`, a stretch, then `[progress 120px][label][gear]`. VS Code keeps its layout toggles together, so both sit at the far left.
    - **Label:** eliding happens in `refresh` via `QFontMetrics.elidedText(text, Qt.TextElideMode.ElideMiddle, 320)`. Clicking the label or the progress bar opens `open_task_list` (an event filter on both for `MouseButtonRelease`).
    - **Gear:** `setPopupMode(InstantPopup)` with a `QMenu`. Its actions call `sys.modules[__package__].manage_models_dialog()` and `mw.onPrefs()`, deferred imports inside `try/except`.
    - **Toggles:** take the discovery code from `browse_toggles._install_browser_sidebar_toggle` (the dock and the editor-column walk up to `form.splitter`), wiring `clicked → setVisible`, `dock.visibilityChanged → setChecked`, and `_VisibilityWatcher(col, editor_btn.setChecked)`.
    - **Subscription:** `tasks.add_listener(self._on_tasks)`, and `self.destroyed.connect(lambda *_: tasks.remove_listener(cb))` where `cb` is a module-level-safe closure that doesn't touch `self`.
    - **Lingering messages:** after a refresh that shows a lingering message, schedule `QTimer.singleShot(int(tasks.LINGER_S*1000)+50, lambda: self.refresh(tasks.snapshot()))`, guarded by `sip.isdeleted`-style `try/except RuntimeError`.

- [ ] **Step 4: Run it and watch it pass.** Same command. Expected: `N passed, 0 failed`.

- [ ] **Step 5: Commit.** `git add klausmate/status_bar.py klausmate/theme.py tests/test_status_bar.py && git commit -m "Status bar 2/6: the bar widget"`

---

### Task 3: Install in the main window and Browse; retire the search-row toggles

**Files:**
- Modify: `klausmate/status_bar.py`, adding the `install_main`, `install_browser` and `setup` glue plus the sync hook handlers
- Modify: `klausmate/browse_toggles.py`. `on_browser_will_show._deferred` stops calling `_install_browser_sidebar_toggle`, and that function is deleted. `_PaneToggle`, `_VisibilityWatcher` and the layout-repair call stay.
- Modify: `klausmate/__init__.py`, adding one guarded `status_bar.setup()` call beside `library_sidebar.setup()`
- Test: `tests/test_status_bar.py` (extend), `tests/test_browse_toggles.py` (update)

**Interfaces:**
- Consumes: `StatusBar` from Task 2, `tasks` from Task 1.
- Produces:
  - `status_bar.install_main(mw) -> StatusBar | None`: `mw.form.statusbar.setVisible(True)`, `setSizeGripEnabled(False)`, `addPermanentWidget(bar, 1)`. Idempotent through `mw._klausmate_status_bar`.
  - `status_bar.install_browser(browser) -> StatusBar | None`: `browser.setStatusBar(QStatusBar(browser))` only when `browser.statusBar()` has no `KlausStatusBar` yet, then `addPermanentWidget(StatusBar(browser, browser=browser), 1)`. Idempotent through `browser._klausmate_status_bar`.
  - `status_bar.on_sync_will_start()`: `tasks.begin("sync", "Syncing…")`.
  - `status_bar.on_sync_did_finish()`: `tasks.end("sync")`.
  - `status_bar.on_media_sync_did_start_or_stop(running: bool)`: `begin("media", "Syncing media…")` or `end("media")`.
  - `status_bar.on_media_sync_did_progress(entry: str)`: `tasks.update("media", label=f"Media: {entry}")`.
  - `status_bar.setup()` registers:
    - `profile_did_open → install_main(mw)` and set `tasks.run_on_main = mw.taskman.run_on_main`;
    - `profile_will_close → tasks.clear`;
    - `browser_will_show → QTimer.singleShot(0, install_browser)`;
    - `theme_did_change → apply_theme` on every live bar;
    - the four sync hooks, each only `if hasattr(gui_hooks, name)`.

- [ ] **Step 1: Write the failing tests.**
  - **`install_browser`** on the Browse-shaped window from Task 2: `win.statusBar().findChild(QWidget, "KlausStatusBar")` isn't None. A second call adds no second bar.
  - **`install_main`** on a `QMainWindow` with `form = SimpleNamespace(statusbar=QStatusBar())` set as its status bar and hidden: after the call, `statusbar.isVisible()`, with one `KlausStatusBar` in it.
  - **Sync handlers:**
    - `on_sync_will_start()` gives `tasks.snapshot()[0].key == "sync"`; `on_sync_did_finish()` removes it.
    - `on_media_sync_did_start_or_stop(True)`, then `on_media_sync_did_progress("12 of 40")`, gives label `"Media: 12 of 40"`. `on_media_sync_did_start_or_stop(False)` removes it.
  - **Search-row toggles gone:** in `tests/test_browse_toggles.py`, replace the assertions about the installed search-row buttons with a check that `browse_toggles` has no `_install_browser_sidebar_toggle` attribute, and that after `on_browser_will_show(win)` plus `app.processEvents()` the window has no `_klausmate_sidebar_toggle_btn`. Keep every `_PaneToggle` paint and state test as it is.

- [ ] **Step 2: Run both files and watch them fail.**
  Run: `for t in test_status_bar test_browse_toggles; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/$t.py; done`
  Expected: `AttributeError: … install_browser` and the new toggle assertions FAIL.

- [ ] **Step 3: Implement** the glue and the handlers above. Delete `_install_browser_sidebar_toggle`, the `_klausmate_sidebar_toggle_btn`/`_klausmate_editor_toggle_btn` attributes, and the grid-repacking comment block. Register `status_bar.setup()` in `__init__.py` with the file's usual `try/except` + print pattern.

- [ ] **Step 4: Run both files and watch them pass.** Same command. Expected: both report `0 failed`.

- [ ] **Step 5: Commit.** `git add klausmate/status_bar.py klausmate/browse_toggles.py klausmate/__init__.py tests/test_status_bar.py tests/test_browse_toggles.py && git commit -m "Status bar 3/6: main window + Browse, toggles move into the bar"`

  **Warning:** `klausmate/__init__.py` also holds the uncommitted K-320 diagnostic hunk and may hold K-319 edits. Stage only the `status_bar.setup()` hunk, by building a patch against HEAD and running `git apply --cached`.

---

### Task 4: Indexing reports to the tracker; the dock and the footer status go

**Files:**
- Modify: `klausmate/index_queue.py`:
  - delete `_StatusDock`, `_DockBase`, `_dock`, `_hide_gen`, `IDLE_HIDE_MS`, `_ensure_dock`, `_render_dock`, `_hide_dock_later`, `_hide_dock`, `_on_dock_button` and `dock_button_label`;
  - `_publish` calls `_report_task(new)` instead of `_render_dock`;
  - the `_on_profile_close` dock teardown lines go;
  - fix the module docstring paragraph that describes the dock.
- Modify: `klausmate/library_sidebar.py`. `Footer` keeps only `self.button` ("Import PDFs…"). Delete `status_row`, `status`, `cancel`, `on_state` and its `index_queue` listener.
- Test: `tests/test_index_queue.py`, `tests/test_library_sidebar.py`, `tests/test_drive.py` (update the pins)

**Interfaces:**
- Consumes: `tasks.begin/update/end`, and `index_queue.status_line`, which is unchanged.
- Produces: `index_queue._report_task(state: RunnerState) -> None`.
  - `state.active`: `tasks.begin("index", status_line(state), cancel=cancel_all)` if `"index"` isn't running yet, otherwise `tasks.update("index", done=state.done, total=state.total, label=status_line(state))`.
  - `not state.active`: `tasks.end("index", state.message)`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_index_queue.py`:
  - Feed `_publish` the sequence `RunnerState(active=True, name="Anemia", label="Embedding PDF…", done=3, total=10)`, then `RunnerState(message="Anemia indexed")`.
    - After the first: `tasks.snapshot()[0]` has `key == "index"`, `done == 3`, `total == 10`, `cancellable is True`.
    - After the second: its `message == "Anemia indexed"`.
  - `tasks.cancel("index")` calls `cancel_all`: monkeypatch it to record.
  - A source-text check that `_StatusDock`, `dock_button_label` and `_render_dock` are absent from `klausmate/index_queue.py`.
  - In `tests/test_library_sidebar.py`: `Footer(browser)` has no attribute `status`, and its only `QPushButton` reads `"Import PDFs…"`.
  - Delete or update any existing checks that construct `_StatusDock` or assert `index_queue.cancel_all()` in the sidebar source. `grep -n "_StatusDock\|dock_button_label\|status_row\|cancel_all()" tests/*.py` lists them. The K-316 check in `test_index_queue.py` that looks for `"index_queue.cancel_all()" in _sidebar_src` becomes a check that `"index_queue.cancel_all" in index_queue source` inside `_report_task`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `for t in test_index_queue test_library_sidebar test_drive; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/$t.py; done`
  Expected: the new checks FAIL (there's no `index` task, and the footer still has `status`).

- [ ] **Step 3: Implement** the deletions and `_report_task`, with `tasks` imported lazily inside it and wrapped in `try/except`.

- [ ] **Step 4: Run them and watch them pass.** Same command. Expected: every file reports `0 failed`.

- [ ] **Step 5: Commit.** `git add klausmate/index_queue.py klausmate/library_sidebar.py tests/test_index_queue.py tests/test_library_sidebar.py tests/test_drive.py && git commit -m "Status bar 4/6: indexing reports to the bar; dock and footer status removed"`

---

### Task 5: Folder scan and retention report

**Files:**
- Modify: `klausmate/pdf_drive.py` (`start_library_rescan`)
- Modify: `klausmate/library_sidebar.py` (`refresh_retention`)
- Test: `tests/test_rescan.py`, `tests/test_library_sidebar.py`

**Interfaces:**
- Consumes: `tasks.begin/end`.
- Produces: task keys `"rescan"` (label `"Scanning the Library folder…"`) and `"retention"` (label `"Updating retention…"`). Neither is cancellable. Each ends in its success path and its failure path. The folded-in "again" pass reuses the same key.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_rescan.py`, extending its `FakeQueryOp` section:
    - A `FakeQueryOp` that captures `op`/`success` without running: `start_library_rescan()` leaves `tasks.snapshot()[0].key == "rescan"`. Running the success callback removes it.
    - A second fake whose `failure` handler is invoked with `RuntimeError("disk")` also removes it.
  - `tests/test_library_sidebar.py`: with `_sidebars` non-empty and a capturing QueryOp stub, `refresh_retention()` leaves a `"retention"` task that is gone after `done({})`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `for t in test_rescan test_library_sidebar; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/$t.py; done`
  Expected: the new checks FAIL.

- [ ] **Step 3: Implement.** Call `begin` where each function sets its `running`/`busy` flag, and `end` in `finish`/`done` and in the op's `.failure(...)`. Add a `.failure` to `refresh_retention`'s QueryOp if it has none, which also resets `_state["busy"]`.

- [ ] **Step 4: Run them and watch them pass.** Same command. Expected: `0 failed`.

- [ ] **Step 5: Commit.** `git add klausmate/pdf_drive.py klausmate/library_sidebar.py tests/test_rescan.py tests/test_library_sidebar.py && git commit -m "Status bar 5/6: folder scan and retention report to the bar"`

---

### Task 6: Ollama install and model pull report; docs

**Files:**
- Modify: `klausmate/manage_models.py`, in `run_local` (`:~2417`), `local_progress` (`:~2401`), and the `done`/`failed` callbacks of that op.
- Modify: `CLAUDE.md`, `AGENTS.md` (module map), `klausmate/config.md` if it mentions the indexing dock, and the spec's Library-footer line.
- Test: `tests/test_local_model_settings.py`

**Interfaces:**
- Consumes: `tasks.begin/update/end`.
- Produces: task key `"ollama"`.
  - `run_local` begins it with the label `f"Ollama: {action}"` (plus `f" {model}"` when there is one).
  - `local_progress` updates it with `done=completed` and `total=total` from the event (the label comes from `event["status"]`).
  - `done` ends it silently, and `failed` ends it with `f"{action} failed: {exc}"`.
  - Not cancellable from the bar: Preferences' own Cancel stays.

- [ ] **Step 1: Write the failing test.** `tests/test_local_model_settings.py` already drives `run_local` with a stubbed runtime. After a `Pull` of `"nomic-embed-text"` whose stub emits `{"status": "pulling", "completed": 5, "total": 10}`, the `"ollama"` task has `total == 10` before completion and is gone after `done`. A failing stub leaves the message `"Pull failed: …"`.

- [ ] **Step 2: Run it and watch it fail.**
  Run: `env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_local_model_settings.py`
  Expected: the new check FAILs.

- [ ] **Step 3: Implement** the four calls, each in `try/except`. Update the docs:
  - CLAUDE.md's `index_queue` bullet: the dock is gone, and the bar is fed through `tasks`.
  - The `library_sidebar` bullet: the footer is Import only.
  - Add new `tasks.py` and `status_bar.py` bullets, plus the `browse_toggles` line (toggles now live in the status bar).
  - AGENTS.md's hook list and module tree.

- [ ] **Step 4: Run it and watch it pass, then run the full suite.**
  Run: `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" >/dev/null 2>&1 || { echo "FAIL $t"; failed=1; }; done`
  Expected: the only line is `FAIL tests/test_top_bar.py`, the other session's known logo failure.

- [ ] **Step 5: Commit.** Stage `manage_models.py` through a patch against HEAD plus `git apply --cached`, because the other session's hunks stay unstaged. Then `git add CLAUDE.md AGENTS.md tests/test_local_model_settings.py docs/superpowers/specs/2026-09-30-status-bar-design.md && git commit -m "Status bar 6/6: Ollama operations report to the bar; docs"`
