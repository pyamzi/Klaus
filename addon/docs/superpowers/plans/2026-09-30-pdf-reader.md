# PDF Reader Implementation Plan

> **Historical record: shipped, do not execute.** This plan was carried out and the work is in the code, which is the source of truth. It predates two changes: the package `klausmate/` is now `klaus_note/`, and the local board (`board/board.py`) is retired in favour of GitHub Issues (see `docs/agents/issue-tracker.md`). Unchecked boxes are not open work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One fast pdf.js reader, identical in every host, that stays in two-way sync with the Library folder.

**Architecture:** Two new aqt-free cores own saving (`annotation_save.py`) and disk watching (`doc_sync.py`). Both renderers call them until the native renderer is deleted in phase 5. A third core (`pdf_source.py`) serves byte ranges to pdf.js over Anki's bridge. The tab bar moves out of `PdfDock` into a reusable `reader_tabs.py` that every host embeds.

**Tech Stack:** Python 3.9-compatible add-on code (`from __future__ import annotations`), PyQt6 via `aqt.qt`, vendored pdf.js 3.11.174, vendored pypdf 6.11.0, node for the JS pure-function tests.

**Spec:** `docs/superpowers/specs/2026-09-30-pdf-reader-design.md` (read it first; this plan argues from it).

## Global Constraints

- Paths are relative to `Klaus Addon/`. Edit the main checkout only; the compile hook checks `klausmate/*.py` through the Anki symlink.
- Tests: headless, `sys.path.insert(0, ".claude/skills/klaus-test/scripts")`, `from anki_stubs import install, check, section, report`, temporary directories only. Never read or write `klausmate/user_files` or `meta.json`.
- Run a test file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/<file>.py` (exit 0 and "N passed, 0 failed").
- Full suite before each card moves to Review: `failed=0; for t in tests/test_*.py; do env QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 "$t" >/dev/null 2>&1 || { echo "FAIL $t"; failed=1; }; done; test "$failed" -eq 0`. Known pre-existing failures must be named in the card comment, not hidden.
- No app-modal `exec()`; dialogs use `open()`/`show()` (K-114). No hardcoded colours in UI code; use `theme` tokens.
- Save debounce: **500 ms**, defined once in `annotation_save.DEBOUNCE_MS`.
- Stable-file rule: size and `mtime_ns` unchanged across two checks **150 ms** apart (`doc_sync.STABLE_MS = 150`).
- Range loading: first chunk **256 KB** (`pdf_source.FIRST_CHUNK = 262144`), `rangeChunkSize: 262144`, max **1 MB** per bridge call (`pdf_source.MAX_RANGE = 1048576`).
- Render cache: keep up to **12** off-zone rendered pages (`KEEP_RENDERED = 12` in `web/pdfjs_pure.js`).
- User-facing copy (exact): `"<name> was removed from your Library folder."`, `"Updated from disk"`, `"Marks couldn't be saved into the file yet; they're kept and will retry."`.
- Fingerprint = `(st_ino, st_mtime_ns, st_size)`; one helper, `pdf_handler.file_stat(path) -> tuple | None`.
- Coordinate through `python3 board/board.py`; one card per phase; `check-disjoint` before `claim`. Commit per task only once Pouya has approved committing for this run; otherwise leave changes staged-by-task and say so on the card.
- Out of scope: K-079 notes pane, `pdf_map`, the 200 MB limit, upgrading pdf.js.

## Review Focus

1. **Library root unavailable** (drive unplugged, iCloud folder offline): no PDF may be flagged missing and no open tab may close; readers keep showing, and the flag logic resumes when the root returns. Test in Task 5.
2. **Same PDF open in two hosts** (editor dock and Lecture panel): one outside change reloads both, one own save is ignored by both, a Finder rename re-points both. Test in Task 4.
3. **Save churn from other apps** (Preview autosave, iCloud re-downloads writing several times within a second): exactly one reload per settled change, never a reload storm. Test in Task 4.
4. **File replaced by something unreadable** (truncated, encrypted, not a PDF) while open: the range read reports `stale`, the reload fails into a visible "couldn't open" state, marks JSON is untouched, no exception escapes. Test in Task 7.
5. **Awkward filenames** (spaces, `&`, non-ASCII, a case-only rename on case-insensitive APFS such as `Lecture.pdf` → `lecture.pdf`): re-point and save both land on the renamed file. Test in Task 5.

---

## Phase 1 (card "PDF reader 1/5: save pipeline and sync engine")

### Task 1: Per-PDF lock and late path resolution in `pdf_handler`

**Files:**
- Modify: `klausmate/pdf_handler.py` (`bake_annotations` ~1625, `move_mapped_file` ~852, `rename_mapped_file` ~883, `rename_mapped_folder` ~907, `delete_context` ~2644)
- Test: `tests/test_pdf_lock.py`

**Interfaces:**
- Produces: `pdf_handler.pdf_lock(safe: str) -> contextlib.AbstractContextManager` (re-entrant, one `threading.RLock` per safe name); `pdf_handler.file_stat(path: str) -> tuple | None`. `bake_annotations` resolves the working path under `pdf_lock(name)` immediately before `os.replace`, and puts `report["stat"] = file_stat(final_path)` and `report["path"] = final_path`. The four library actions hold `pdf_lock` for every PDF they touch (`rename_mapped_folder`: every safe name under the folder).

- [ ] **Step 1: Write the failing tests**

`check("rename during bake lands on new path", ...)`: build a two-page PDF with the vendored pypdf in a temp root, map it, save one highlight record, start `bake_annotations` in a thread whose pristine-capture step is slowed by monkeypatching `_capture_pristine_stripped` to wait on an Event; call `rename_mapped_file(..., display="Renamed")` from the main thread (it blocks on the lock), release the Event, join both. Assert: old path does not exist, new path exists and contains one `/Annot`, `report["path"]` equals the new path.
`check("file_stat is (ino, mtime_ns, size)")`, `check("file_stat of missing path is None")`, `check("pdf_lock is re-entrant")`.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_pdf_lock.py`
Expected: FAIL (AttributeError: `pdf_lock`).

- [ ] **Step 3: Implement `pdf_lock`, `file_stat`, and the late resolution** as in Interfaces. A module-level `dict[str, RLock]` guarded by one `threading.Lock`.

- [ ] **Step 4: Run to verify pass**, then run `tests/test_klausmate.py` (bake/mirror engine) and `tests/test_drive.py`: all pass.

- [ ] **Step 5: Commit** `tests/test_pdf_lock.py klausmate/pdf_handler.py` — "PDF reader 1/5: per-PDF lock; bake resolves its path just before replace".

### Task 2: `library_stats.json` sidecar

**Files:**
- Modify: `klausmate/pdf_handler.py` (new helpers beside `load_library_map`)
- Test: `tests/test_library_stats.py`

**Interfaces:**
- Produces: `load_library_stats(ufd: str) -> dict[str, list[int]]` (`{safe: [size, mtime_ns]}`, corrupt reads as `{}`; keys starting with `__` are reserved for Task 5 and skipped by every reader here); `record_stat(ufd: str, safe: str, stat: tuple | None) -> None` (atomic write, `None` removes the entry); `changed_since_recorded(ufd: str, root: str, mapping: dict) -> list[str]` (safe names whose current `[size, mtime_ns]` differ from the recorded one; unrecorded names are recorded and not reported; missing files are not reported).

- [ ] **Step 1: Failing tests**: round trip; corrupt file reads `{}`; first call records without reporting; touching a file (new mtime) reports it once; `record_stat` after a Klaus write suppresses the report; a missing file is not reported.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** using `_atomic_write_json`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — "PDF reader 1/5: library_stats sidecar for closed-file change detection".

### Task 3: `annotation_save.py`, one save pipeline

**Files:**
- Create: `klausmate/annotation_save.py` (aqt-free above a `# ---- Qt glue` divider)
- Modify: `klausmate/pdf_viewer.py` (`_schedule_bake`/`_on_bake_timer`/`_post` ~1871-1975 replaced by calls), `klausmate/pdfjs_viewer.py` (`_schedule_bake`/`_on_bake_timer` ~1393-1436 replaced)
- Test: `tests/test_annotation_save.py`

**Interfaces:**
- Consumes: `pdf_handler.bake_annotations(ufd, name, report=...)`, `remove_records`, `mark_native_baked`, `record_stat` (Task 2), `doc_sync.pin_own_write` (Task 4; inject as a callable so Task 3 lands first).
- Produces:
  - `class SavePipeline(ufd: str, run_on_main: Callable[[Callable], None], start_timer: Callable[[str, int, Callable], None], pin: Callable[[str, tuple | None], None])`
  - `.request(name: str) -> None`: restart the `DEBOUNCE_MS = 500` timer for `name`.
  - `.flush(name: str | None = None, timeout: float = 10.0) -> bool`: run pending bakes now and wait.
  - `.subscribe(cb: Callable[[str, str], None]) -> Callable[[], None]`: events `("saved", name)`, `("failed", name)`, `("records", name)`.
  - `.failed_names() -> set[str]`; `.retry(name) -> None`.
  - Qt glue: `pipeline() -> SavePipeline` (singleton bound to `mw.taskman.run_on_main` and `QTimer.singleShot`); `flush_all()` wired to `profile_will_close`.
  - Post-step on main thread, per successful bake: `pin(name, report["stat"])`, `record_stat(ufd, name, report["stat"])`, `remove_records` for `report["omitted"]`, `mark_native_baked`, then emit `"records"` and `"saved"`.

- [ ] **Step 1: Failing tests** with fake `run_on_main` (runs inline), fake timer (manual fire), and a fake `bake` injected by monkeypatching `pdf_handler.bake_annotations`:
  - three `request("A")` calls before the timer fires → one bake;
  - a bake running for A and a second `request("A")` → second bake starts only after the first returns (never concurrent; count overlap with a lock-held flag);
  - bakes for A and B may overlap;
  - fake bake returns False → `("failed","A")` emitted, `failed_names()=={"A"}`, JSON untouched; next `request("A")` retries and clears it;
  - `flush("A")` runs a pending bake immediately and returns True;
  - successful bake calls `pin("A", stat)` with the report's stat.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `SavePipeline`** (one `threading.Thread` per active name, a per-name "again" flag like today's `_bake_pending`).
- [ ] **Step 4: Rewire both viewers**: `_save_annotations` keeps its JSON write, then `annotation_save.pipeline().request(name)`; delete their private timers and `_post`; subscribe each viewer to `"records"` to call its existing reload-records path, and to `"failed"` to show the exact failure copy in its toast. Run `test_annotation_save.py`, `test_pdfjs_viewer.py`, `test_klausmate.py`, `test_current_page_load_failure.py`: PASS.
- [ ] **Step 5: Commit** — "PDF reader 1/5: one save pipeline for both renderers (K-085 bookkeeping now covers pdf.js)".

### Task 4: `doc_sync.py`, open-file watching

**Files:**
- Create: `klausmate/doc_sync.py` (aqt-free core above `# ---- Qt glue`)
- Test: `tests/test_doc_sync.py`

**Interfaces:**
- Consumes: `pdf_handler.file_stat`.
- Produces (core):
  - `open_doc(host: str, safe: str, path: str) -> None`, `close_doc(host: str, safe: str) -> None`, `open_paths() -> dict[str, str]`
  - `pin_own_write(safe: str, stat: tuple | None) -> None`
  - `classify(safe: str, stat: tuple | None) -> str` returning `"own"`, `"changed"` or `"missing"`
  - `stable(prev: tuple | None, cur: tuple | None) -> bool` (size and mtime equal)
  - `subscribe(cb: Callable[[str, str, str | None], None]) -> Callable[[], None]` with events `("changed", safe, None)`, `("moved", safe, new_path)`, `("missing", safe, None)`, `("back", safe, path)`
  - `repoint(safe: str, new_path: str) -> None` (emits `"moved"`), `mark_missing(safe)`, `mark_back(safe, path)`.
- Produces (Qt glue): `watcher()` owning one `QFileSystemWatcher`; `fileChanged` → wait `STABLE_MS = 150` twice via `QTimer.singleShot` → `classify` → emit; re-`addPath` once the path exists again.

- [ ] **Step 1: Failing tests** (real `QFileSystemWatcher`, offscreen `QApplication`, drive with `processEvents` plus short sleeps):
  - outside rewrite of an open file → exactly one `"changed"`;
  - `pin_own_write` with the new stat, then write → no event;
  - save-over via tmp + `os.replace` → one `"changed"` and the path is watched again (a second rewrite also fires);
  - five writes 50 ms apart → one `"changed"` after they stop (Review Focus 3);
  - same safe open in hosts `"editor"` and `"lecture"` → subscribers get one event per change; `close_doc` of one host keeps watching (Review Focus 2);
  - `repoint` emits `"moved"` and moves the watch to the new path.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.** Wire `SavePipeline`'s `pin` to `doc_sync.pin_own_write` in `annotation_save.pipeline()`, and subscribe the pipeline to `doc_sync` so a `"back"` event calls `retry(safe)` when `safe in failed_names()` (add that check to the Task 3 test file).
- [ ] **Step 5: Commit** — "PDF reader 1/5: doc_sync watches open files with a stable-file rule".

### Task 5: Folder scan: moves, deletes, reconnects, closed-file changes, off the main thread

**Files:**
- Modify: `klausmate/pdf_handler.py` (`prepare_rescan` ~1073, `rescan_root` ~1131), `klausmate/pdf_drive.py` (`_on_fs_tick` ~174, `start_library_rescan` ~242, `rescan_library_root` ~311), `klausmate/library_sidebar.py` (warning icon + menu)
- Test: `tests/test_rescan.py` (extend), `tests/test_doc_sync.py` (extend)

**Interfaces:**
- Consumes: `changed_since_recorded` (Task 2), `doc_sync.repoint/mark_missing/mark_back` (Task 4), `repair_garbled_pages`, `page_store.ensure_records`, `index_queue.request_pdf`.
- Produces:
  - `prepare_rescan` also returns `"disk"` (the walk), `"changed": {safe: pages}` (re-extracted and repaired text of closed-file content changes) and `"root_ok": bool`. `rescan_root(..., prepared=...)` uses `prepared["disk"]` instead of walking again.
  - `rescan_library_root` result gains `"missing": [safe]`, `"moved": {safe: new_abs_path}`, `"back": [safe]`. After applying the mapping, `finish` calls `doc_sync.repoint`/`mark_missing`/`mark_back` (the old immediate `poll_external_changes` call in `_on_fs_tick` is removed).
  - `pdf_handler.load_missing(ufd) -> set[str]` / `set_missing(ufd, safes)` persisted in `library_stats.json` under key `"__missing__"`.
  - `_on_fs_tick` pre-check: skip the rescan when every changed directory entry is a hidden name (starts with `.`) or a mapped file whose stat equals its recorded stat.
  - Library sidebar: rows in `load_missing` show the existing warning icon with tooltip `"Missing from your Library folder"`, and a context-menu action `"Remove from Library"` that calls the existing `pdf_drive.delete_pdf` path without trashing a file.
  - Changed closed files: `ensure_records` with the new pages; `index_queue.request_pdf(safe)` only when `page_store.text_hash` of any page changed.

- [ ] **Step 1: Failing tests:**
  - Finder-style rename of a mapped file → result `"moved"` has the new path; a `doc_sync` subscriber sees `"moved"` after, not before, the mapping update;
  - case-only rename `Lecture.pdf` → `lecture.pdf` and a name with spaces and `&` → `"moved"` resolves and a following bake writes to the new name (Review Focus 5);
  - deleted file → `"missing"` and `load_missing` contains it; the file reappears → `"back"` and it is cleared;
  - root directory absent → `root_ok` False, `missing` empty, `load_missing` unchanged (Review Focus 1);
  - closed file content changed outside → `"changed"` has its pages and `request_pdf` is called once (monkeypatched); a Klaus bake of the same file (stat recorded) → not reported;
  - `prepare_rescan` is the only `walk_root` caller in a full rescan (count calls via monkeypatch);
  - pre-check: a tick that only created `.x.pdf.uuid.tmp` does not start a rescan.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Before editing `library_sidebar.py`, run `git status -- klausmate/library_sidebar.py klausmate/library_viewer.py`; if dirty with another session's hunk, park it per CLAUDE.md (tagged stash, scratchpad patch, board comment).
- [ ] **Step 4: Run `test_rescan.py`, `test_doc_sync.py`, `test_drive.py`, `test_library_sidebar*.py`: PASS.**
- [ ] **Step 5: Commit** — "PDF reader 1/5: rescan re-points, flags and reconnects PDFs; closed-file edits re-index".

### Task 6: Readers follow `doc_sync`

**Files:**
- Modify: `klausmate/pdf_viewer.py` (`PdfSidebar.load_pdf` ~4386, `reload_if_externally_changed` ~4527, `_full_external_reload` ~4593, module functions `poll_external_changes`/`_refresh_stats_for`/`_reload_records_for`/`_stat_of` ~4193-4260, `cleanup` ~4638)
- Test: `tests/test_reader_sync.py`

**Interfaces:**
- Consumes: `doc_sync` (Task 4), `annotation_save` (Task 3).
- Produces: `PdfSidebar.host_key: str` (constructor keyword `host_key="editor"`; the Lecture dock passes `"lecture"`). `load_pdf` calls `doc_sync.open_doc(host_key, name, path)` and, when the annotations JSON is newer than the PDF, `annotation_save.pipeline().request(name)` (this replaces native's re-bake-on-load and gives pdf.js the same retry after a restart); `clear`/`cleanup` call `annotation_save.pipeline().flush(name)` and then `close_doc`. Handlers: `"changed"` → `flush(name)` first, wait for an open text box to commit, then reload in place keeping page and zoom and run the foreign mirror, then toast `"Updated from disk"`; `"moved"` → re-point without reload; `"missing"` → close the document with toast `"<name> was removed from your Library folder."`. The five old module functions and `reload_if_externally_changed`/`_full_external_reload` are deleted; `pdf_drive` no longer imports them.

- [ ] **Step 1: Failing tests** with a real `PdfSidebar(None, host_key="lecture")` offscreen (native renderer is fine here) and a fake `doc_sync` event: `"changed"` calls the reload path once and preserves `scroll_position()`; `"moved"` updates the path and does not reload; `"missing"` clears the document and emits the exact copy; `cleanup` flushes a pending save before `close_doc`; loading a PDF whose JSON mtime is newer than the file requests one save.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the new test and the full suite: PASS** (fix `grep -rn "poll_external_changes\|_refresh_stats_for" klausmate tests` to zero).
- [ ] **Step 5: Commit**; board: move card 1 to Review with evidence.

## Phase 2 (card "PDF reader 2/5: piece loader, speed, zoom")

Before coding: ask Pouya for baseline "time to first page" on the largest lecture and `Bootcamp.com Hematology & Oncology` with today's build (Task 8 adds the log line; record numbers on the card).

### Task 7: `pdf_source.py`, range reads

**Files:**
- Create: `klausmate/pdf_source.py`
- Test: `tests/test_pdf_source.py`

**Interfaces:**
- Produces: `FIRST_CHUNK = 262144`, `MAX_RANGE = 1048576`; `class DocSource(path: str)` with `.length: int`, `.stat: tuple`, `.read(begin: int, end: int) -> bytes` raising `StaleSource` on fingerprint mismatch or unreadable file; `range_reply(source: DocSource | None, gen: int, current_gen: int, begin: int, end: int) -> dict` returning `{"b64": str}`, `{"stale": True}` or `{"refused": True}`.

- [ ] **Step 1: Failing tests:** first chunk and a middle range match `open(...).read()` slices; `end` past length is clamped; a request wider than `MAX_RANGE` is clamped to it; after `os.replace` with other bytes → `stale`; truncated or deleted file → `stale` (Review Focus 4); old `gen` → `refused`; after `read`, `lsof`-free check: `os.replace` onto the path succeeds on this platform and no handle is kept (assert `source._fh` does not exist).
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement** (open, `fstat` compare, `seek`, `read`, close per call). **Step 4: PASS.** **Step 5: Commit.**

### Task 8: Piece loader in the pdf.js page

**Files:**
- Modify: `klausmate/pdfjs_viewer.py` (`load_path` ~1468, `_on_bridge` ~1006; delete `chunk_b64`, `CHUNK_CHARS`), `klausmate/web/pdfjs_viewer.html` (`klausPdfLoad` ~460-480, `teardown` ~617-632)
- Test: `tests/test_pdfjs_viewer.py` (extend)

**Interfaces:**
- Consumes: `pdf_source.DocSource`, `range_reply`.
- Produces: bridge command `klausmate_pdfjs:range:<gen>:<begin>:<end>` answered with `range_reply(...)` (the handler returns the dict; Anki JSON-encodes it to the JS callback). Page entry point `klausPdfOpen(gen, length, firstB64, name)` replacing `klausPdfLoad`; it builds a `PDFDataRangeTransport(length, firstBytes)` whose `requestDataRange(begin, end)` calls `pycmd(..., cb)` and on `stale` aborts and posts `stale:<gen>` (Python then asks `doc_sync` to treat it as `"changed"`). `getDocument({range, disableAutoFetch: true, disableStream: true, rangeChunkSize: 262144})`. `teardown()` calls `transport.abort()` and `await doc.destroy()`. The page posts `firstpage:<ms>` once page 1 is drawn; Python prints `[klausmate] pdfjs first page <name> <ms> ms`.

- [ ] **Step 1: Failing tests** (pure, no WebEngine): `parse_bridge("klausmate_pdfjs:range:3:0:262144")` routes to the range handler; the handler with a real temp PDF returns base64 decoding to the first 256 KB; `load_path` no longer reads the whole file (monkeypatch `open` to count bytes read ≤ `FIRST_CHUNK`); `chunk_b64` is gone.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS plus full suite. Step 5: Commit.**

### Task 9: Render cache, per-page mark redraw, incremental find

**Files:**
- Create: `klausmate/web/pdfjs_pure.js` (loaded by the page before its main script; also `module.exports` when run under node)
- Modify: `klausmate/web/pdfjs_viewer.html` (observer ~533-615, `klausSetAnnotations` ~658-666, find ~1912-1928), `klausmate/pdfjs_viewer.py` (`build_page_html` includes the new script)
- Test: `tests/pdfjs_pure_test.js`, run from `tests/test_pdfjs_pure.py` (honest SKIP when `node` is absent, as `test_dashboard.py` does)

**Interfaces:**
- Produces: `KEEP_RENDERED = 12`; `evictable(renderedLru: number[], inZone: Set<number>, keep: number) -> number[]` (pages to tear down, least recently visible first, never one in the zone); `changedPages(prev: Record[], next: Record[]) -> Set<number>` (1-based pages whose records differ by id, rect or content); `findOrder(visible: number[], count: number) -> number[]` (visible pages first, then the rest ascending).

- [ ] **Step 1: Failing JS tests** for the three functions, including: zone pages never evicted; nothing evicted at or under the cap; a moved highlight marks both its old and new page; `findOrder([5,6], 8)` equals `[5,6,1,2,3,4,7,8]`.
- [ ] **Step 2: FAIL. Step 3: Implement and use them in the page** (tear down only `evictable(...)`; redraw only `changedPages(...)`; find walks `findOrder(...)` in `requestIdleCallback` batches of 5 pages, appending results as found). **Step 4: PASS. Step 5: Commit.**

### Task 10: Zoom fix

**Files:**
- Modify: `klausmate/pdfjs_viewer.py` (`eventFilter` ~974), `klausmate/web/pdfjs_viewer.html` (zoom block ~1197-1420)
- Test: `tests/test_pdfjs_viewer.py` (extend)

**Interfaces:**
- Produces: `gesture_action(gesture_type, value: float) -> tuple | None` (pure): `Qt.NativeGestureType.ZoomNativeGesture` → `("pinch", math.exp(value))`, `SmartZoomNativeGesture` → `("smart",)`, anything else → `None`. `eventFilter` consumes `QEvent.Type.NativeGesture` on the view and its `focusProxy` and evals `klausPinch(factor, x, y)` or `klausSmartZoom()`. Page: `klausPinch` feeds the existing `zoomTo(...)` session; `klausSmartZoom` toggles fit-width; a `visualViewport` resize listener posts `vv-scale:<scale>` when `scale !== 1`, and Python reloads the page and re-feeds the current document at its page and zoom.

- [ ] **Step 1: Failing tests:** `gesture_action` mapping (value 0.1 → factor `exp(0.1)`); a synthetic `QNativeGestureEvent` sent to a stand-in `QWidget` with the filter installed is consumed and records one pinch; `_on_bridge("klausmate_pdfjs:vv-scale:1.4")` triggers the reload path once.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS plus full suite. Step 5: Commit**; board: card 2 to Review. Live check list for Pouya on the card: first-page times vs baseline, scrolling, pinch, two-finger double-tap, the gray-background bug.

## Phase 3 (card "PDF reader 3/5: one reader everywhere")

Before claiming: `git status -- klausmate/library_viewer.py klausmate/lecture_view.py klausmate/__init__.py`; park foreign hunks per CLAUDE.md.

### Task 11: `reader_tabs.py`, tabs inside the reader

**Files:**
- Create: `klausmate/reader_tabs.py`
- Modify: `klausmate/pdf_viewer.py` (`PdfSidebar` gains the tab strip), `klausmate/__init__.py` (`PdfDock` loses `_decorate_tab` … `_show_add_menu`, ~1233-1389; `_PanelBar` keeps placement, float, hide), `klausmate/pdf_handler.py` (`load_open_tabs`/`save_open_tabs` gain `host_key`)
- Test: `tests/test_reader_tabs.py`, `tests/test_pdf_dock.py` (update)

**Interfaces:**
- Produces: `class ReaderTabs(QWidget)` with signals `activated(str)`, `closed(str)`, `add_requested()`; methods `set_tabs(names: list[str], active: str | None)`, `open(name: str) -> None` (add or focus), `close(name: str)`, `names() -> list[str]`; page label `set_page(n: int, total: int)`. `pdf_handler.load_open_tabs(ufd, host_key="editor")` / `save_open_tabs(ufd, names, host_key="editor")`; stored under `pdf_tabs.json["tabs"][host_key]`, with the legacy top-level list migrated into `"editor"` on first read.

- [ ] **Step 1: Failing tests:** open/focus/close order; persistence round trip per host key; legacy file migrates into `"editor"` and `"lecture"` starts empty; `PdfSidebar(None, host_key="lecture")` shows a tab strip.
- [ ] **Step 2: FAIL. Step 3: Implement** (move, don't rewrite, the existing tab behaviour: decoration, close button, ＋ menu). **Step 4: PASS plus `test_pdf_dock.py`. Step 5: Commit.**

### Task 12: Lecture panel uses tabs; all hosts on pdf.js; lazy load

**Files:**
- Modify: `klausmate/lecture_view.py` (~415-470), `klausmate/pdf_viewer.py` (`PdfSidebar.__init__` renderer choice ~4314-4359), `klausmate/__init__.py` (`on_editor_did_init` ~1392-1490, `_migrate_config` ~136), `klausmate/manage_models.py` (renderer row ~885, ~2078, ~2129), `klausmate/config.json`, `klausmate/config.md`
- Test: `tests/test_lecture_view.py`, `tests/test_pdf_dock.py`, `tests/test_klausmate.py` (migration)

**Interfaces:**
- Produces: `PdfSidebar` always builds `PdfJsViewer` (native branch unreachable, kept until phase 5); `_migrate_config` pops `pdf_renderer`; Preferences has no renderer row; the Lecture dock calls `sidebar.tabs.open(safe)` instead of replacing the document and returns focus to `mw.web` after every jump; the editor dock loads its active tab on first `showEvent`, not at install.

- [ ] **Step 1: Failing tests:** a stored `pdf_renderer: "native"` is removed by `_migrate_config`; the Lecture dock opening lecture B while A is open yields tabs `[A, B]` with B active; a hidden dock has not called `load_pdf` until shown.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS plus full suite. Step 5: Commit.**

### Task 13: Viewer-mode sizing under `single_window`, and K-155

**Files:**
- Modify: `klausmate/library_viewer.py` (`_fill` 46-66, `leave` 131-135), `klausmate/__init__.py` (`_klausmate_active_pdf` writes)
- Test: `tests/test_library_viewer.py` (extend)

**Interfaces:**
- Produces: `library_viewer._dock_host(dock) -> QMainWindow` (the dock's `parentWidget()` main window); every `dockWidgetArea`/`resizeDocks` call goes through it. `_klausmate_active_pdf` no longer exists (`grep` returns nothing).

- [ ] **Step 1: Failing test:** with the dock parented to a separate main window standing in for `mw`, `enter` sizes via that window (spy on `resizeDocks`) and not via the browser.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS plus full suite. Step 5: Commit**; board: card 3 to Review; close K-095 and K-101 with a comment pointing at the spec. Live check list on the card: all four places, tabs in review, Preview round trip, Finder rename/move/delete.

## Phase 4 (card "PDF reader 4/5: trial")

No code. Pouya uses the build for a few days. Record issues as comments on this card; each fix is its own small card. Phase 5 starts only after Pouya says the trial is good.

## Phase 5 (card "PDF reader 5/5: delete the native renderer")

### Task 14: Delete `PdfViewer` and native-only code

**Files:**
- Modify: `klausmate/pdf_viewer.py` (delete `PdfViewer` and its helpers; keep `PdfSidebar`, then move it to `klausmate/reader_panel.py` and leave `pdf_viewer.py` importing nothing native), every importer found by `grep -rn "pdf_viewer\.\|from .pdf_viewer\|PdfViewer" klausmate tests`
- Delete: native-only tests (selection probes, QPdfView overlay, thumbnail strip), after listing them on the card
- Test: full suite

- [ ] **Step 1:** `grep` the importers and native-only tests; post the list on the card.
- [ ] **Step 2:** Delete and move; update imports.
- [ ] **Step 3:** `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/*.py` and the full suite: PASS.
- [ ] **Step 4: Commit** — "PDF reader 5/5: delete the native renderer".

### Task 15: Documentation

**Files:** `CLAUDE.md` (module map: pdf_viewer/pdfjs_viewer/reader_panel/doc_sync/annotation_save/pdf_source; the stale "1200ms"; the Hard-won gotchas that were QPdfView-only), `AGENTS.md` (layout list), `klausmate/config.md` (no `pdf_renderer`), `DESIGN.md` (reader surface).

- [ ] **Step 1:** Update each file; `grep -rn "QPdfView\|pdf_renderer\|1200ms" CLAUDE.md AGENTS.md klausmate/config.md DESIGN.md` shows only historical mentions.
- [ ] **Step 2: Commit**; board: card 5 to Review.
