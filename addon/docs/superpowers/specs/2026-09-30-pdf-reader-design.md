# PDF reader: one fast reader, two-way sync with the Library folder

Date: 2026-09-30. Status: design approved in conversation, awaiting spec review.
Supersedes the open pdf.js cutover cards K-095 (umbrella) and K-101 (cutover).

## Goal

Pouya wants the PDF reader to be **fast, simple, and in two-way sync with the
local Library folder**, and **the same in every place it appears**.

## Decisions (Pouya, 2026-09-30)

1. **Two-way sync means all of A, B and C:**
   - A. Marks made in Klaus are written into the real PDF in the Library folder.
   - B. Outside edits (Preview, a replaced file) show up live in an open reader.
   - C. The folder is the source of truth: adds, renames, moves and deletes in
     Finder show up in Klaus, and Klaus's own renames, moves and deletes change
     the real files.
2. **Fast** means time to first page when opening a PDF, and scrolling and
   zooming. Pouya uses the default (native) renderer today.
3. **Keep all twelve features**: tabs, thumbnails, find, highlights in several
   inks, text boxes on the page, notes on highlights, zoom, go to page, copy
   slide as image, drag a region out as an image, copy page text, panel
   placement (left, right, bottom, float).
4. **Identical everywhere**: the full reader with every feature in all four
   places, including the review Lecture panel.
5. **Approach 1**: one reader on pdf.js with a rebuilt loader and one sync engine.
6. **Delete the native renderer** after a few-day trial, not keep it as a fallback.
7. **Separate tab sets** for the review Lecture panel and the Browse/Add/Edit dock.
8. **A PDF deleted in Finder is flagged, not removed automatically.**

Assumptions (stated, not contradicted): the Library folder stays the only home of
the PDF files; existing annotations carry over unchanged.

## Current state (read 2026-09-30)

- Every reader is one class, `PdfSidebar` (`pdf_viewer.py`). It picks the native
  `PdfViewer` (QPdfView) or `PdfJsViewer` once at construction from
  `pdf_renderer`. Hosts: the shared editor `PdfDock` (Browse, Add, Edit Current
  under `single_window`), the review `LectureDock` (`lecture_view.py`), and Browse
  viewer mode (`library_viewer.py`, which reuses the editor dock).
- Only the editor dock has tabs; the tab bar is `_PanelBar` in `__init__.py`.
- Native lacks text boxes and multiple inks. It flickers because QPdfView delivers
  pages late.
- pdf.js opens slowly: Python reads the whole file on the main thread, base64-encodes
  it, pushes 6 MB `eval` slices, and the page copies it back byte by byte before
  `getDocument({data})`. Its `teardown()` never calls `destroy()`. Every mark push
  rebuilds the annotation layers of every rendered page. The first find extracts
  text from every page.
- No watcher on open files; only directories are watched (`pdf_drive._rearm_watcher`,
  350 ms debounce). An outside edit that keeps the page count mirrors marks but
  leaves stale pixels. Readers are polled *before* the background rescan updates the
  mapping, so a Finder rename or move leaves the reader stale; a Finder delete leaves
  the stale document on screen.
- Saves: the K-085 fixes (own-write stat pin, removal of omitted records, baked
  ledger) exist only in native. pdf.js bakes without them, so each of its saves looks
  like an outside edit. Every bake fires a full folder rescan. A bake resolves its
  path at the start, so a rename during a bake can recreate the file at the old path.
- The folder scan fingerprints only new and missing files; content changes to a
  mapped, closed PDF are never noticed.
- No tests cover `reload_if_externally_changed`, `poll_external_changes`,
  `_refresh_stats_for`, `_full_external_reload`, `_on_fs_tick` or `_rearm_watcher`.

## Design

### 1. Loading and speed

**Piece loading.** The page gives pdf.js a `PDFDataRangeTransport` (present in the
vendored 3.11.174) with the file's length and the first 256 KB, and calls
`getDocument({range, disableAutoFetch: true, disableStream: true,
rangeChunkSize: 262144})`. When pdf.js asks for a range, the page calls
`pycmd("klausmate_pdfjs:range:<gen>:<begin>:<end>", cb)`. Anki's bridge returns the
handler's value JSON-encoded to `cb` (verified in `aqt/webview.py`'s `pycmd` shim).

**Range reads** live in a new aqt-free module, `pdf_source.py`:
- `DocSource(path)` captures the fingerprint `(inode, mtime_ns, size)` at load.
- `read(begin, end)` opens the file, checks the fingerprint, reads the range and
  closes it. The file is never held open, so neither Klaus's own save nor another
  app's save-over is blocked (Windows refuses `os.replace` onto a path with an open
  handle).
- A fingerprint mismatch returns `{"stale": true}`. The page aborts the transport
  and the tab hands over to section 3's reload.
- Every request carries the document generation `gen`; a request from an older
  generation is refused, so a tab switch never mixes bytes from two files.
- Ranges are bounded to the file size and capped at 1 MB per call.

**Memory.** `teardown()` calls `doc.destroy()` and aborts any open transport.

**Scrolling and zooming.**
- Pages that leave the render zone stay rendered, up to 12 pages outside the render
  zone, instead of being torn down immediately. The least recently visible are evicted
  first. The cap is one constant, adjusted only if the live measurement calls for it.
- Zoom keeps K-116's instant preview and settle, then re-renders visible pages first.
- `klausSetAnnotations` redraws only the pages whose records changed.
- The first find searches visible pages first, then the rest in idle batches, and
  shows results as they arrive.

**Zoom bug (reported 2026-09-30).** Pinch sometimes zooms the whole page, gray
background included. The page already cancels every ctrl-wheel, so the leak must be
a path the page cannot catch. Probable causes, not yet reproduced: a pinch that lands
before the page script attaches its listener (Chromium's visual-viewport zoom then
sticks), and the macOS two-finger double-tap ("smart zoom").
- **Fix.** The existing event filter on the webview and its `focusProxy` also
  intercepts `QEvent.NativeGesture`. `ZoomNativeGesture` is forwarded to the page as
  `klausPinch(factor, x, y)`; `SmartZoomNativeGesture` toggles fit-width. Neither
  reaches Chromium. This needs live confirmation.
- **Recovery.** `setZoomFactor(1.0)` does not undo visual-viewport zoom. The page
  watches `visualViewport.scale`; if it ever leaves 1, it posts `vv-scale` and
  Python reloads the page and re-feeds the document, which piece loading makes cheap.

**Unchanged:** the pdf.js version, the annotations JSON schema, and the 200 MB limit.

### 2. One reader everywhere

- pdf.js is the only reader. The Preferences renderer row is removed, and
  `_migrate_config` scrubs `pdf_renderer`.
- The native `PdfViewer` is deleted in the last phase, after Pouya's trial.
- **One reader panel.** The tab bar (tabs, ＋ picker, page n/m) moves from
  `__init__._PanelBar` into the reader panel itself (a new `reader_panel.py` holding
  `PdfSidebar`'s host-neutral part). Every host then shows the same bar. A host adds
  only its own window controls: dock placement, float and hide.
- **Editor dock** (Browse, Add, Edit): unchanged, except that the PDF loads the first
  time the dock is shown, not at install while hidden.
- **Lecture panel:** a card matched to a different lecture opens that PDF as a tab,
  or switches to it if already open. Focus returns to the reviewer after every jump,
  so answer keys keep working. Reader shortcuts apply only while the reader has focus.
- **Viewer mode:** keeps reusing the editor dock. Its sizing calls
  (`browser.dockWidgetArea`, `browser.resizeDocks`) assume a dock owned by the Browse
  window; under `single_window` the dock belongs to `mw`, so they are corrected.
- **Tabs:** each host keeps its own tab set, persisted in `pdf_tabs.json` under a
  per-host key.
- The dead `_klausmate_active_pdf` seam (K-155) is removed.

### 3. Disk → reader sync

A new module, `doc_sync.py`, is aqt-free above a Qt glue divider. It keeps a registry
of open documents: safe name, path, load fingerprint, and the last own-write
fingerprint.

**Watching.**
- Each open file is added to a `QFileSystemWatcher` (`fileChanged`). The directory
  watcher stays.
- A save-over removes the watched path, so after each change the path is re-added
  once it exists again.

**Stable-file rule.** After a change, Klaus waits until size and `mtime_ns` are
unchanged across two checks 150 ms apart before reading the file.

**Decision** for a changed open file:
- Fingerprint equals the last own write: ignore.
- Otherwise: reload the pages in place, keeping the page and zoom, even when the page
  count is unchanged. Mirror outside marks as today (`mirror_foreign_annotations`,
  stale-scan discard kept) and show a transient "Updated from disk" note.

**Rename or move in Finder.** Readers are notified *after* the background rescan
(`finish` in `pdf_drive.start_library_rescan`) applies the mapping, not before. A
tab whose safe name now maps to a new path re-points its `DocSource` and title with
no reload.

**Delete in Finder.**
- The rescan reports the safe name as missing. Open tabs of it close with the notice
  "*name* was removed from your Library folder."
- The Library sidebar row shows a missing warning icon (the existing warning-icon
  mechanism) and a right-click "Remove from Library". The tag, annotations and matches
  are kept.
- When a file reappears (moved back, drive plugged in, iCloud restores it), the
  content-matched rescan reconnects it and clears the flag.

**Closed PDFs changed outside.**
- A sidecar, `user_files/library_stats.json`, stores `{safe: [size, mtime_ns]}` for
  every mapped file. A sidecar is used instead of changing `library_map.json`, whose
  values are bare relative paths.
- The background prepare step compares stats. A changed file whose stats are not
  Klaus's own last write is re-extracted (with `repair_garbled_pages`) and its page
  records re-seeded.
- If the text actually changed (`page_store.text_hash`), the PDF is queued for
  re-index through `index_queue`.

**Main thread.** The two `walk_root` passes and the watcher re-arm that currently run
in `finish` move into the background prepare step. Only applying the result stays on
the main thread.

**Tick pre-check.** A directory tick whose only changes are hidden temporary files
or a pinned own write does not start a rescan.

### 4. Reader → disk saves

One save pipeline in a new module, `annotation_save.py`, replaces the two bake paths
in `pdf_viewer.py` and `pdfjs_viewer.py`:

1. The reader shows the mark immediately. The record is written to the annotations
   JSON (atomic, as today).
2. After a **500 ms** debounce from the last change (the only save debounce; CLAUDE.md's
   "1200ms" is stale), one background worker per PDF runs `bake_annotations`.
3. A main-thread post-step, now used for every save:
   - pins the written fingerprint in `doc_sync` and `library_stats.json`;
   - removes omitted records;
   - marks native records baked;
   - pushes records to the open readers.

**Per-PDF lock.**
- `bake_annotations` and `pdf_handler`'s rename, move and delete (`rename_mapped_file`,
  `move_mapped_file`, `rename_mapped_folder`, `delete_context`) share one lock per
  safe name.
- A bake resolves the working path *under the lock, immediately before* its
  `os.replace`.
- A Library action waits for an in-flight bake.
- This closes the rename-during-bake race.

**Temporary files.** They stay hidden (`.<base>.pdf.<uuid>.tmp`) next to the target on
the same filesystem, so the swap is atomic. The directory watcher and the rescan ignore
them.

**Failures.** A read-only file, a lock held by another app, or a missing drive leaves
the JSON as the safe copy. The tab shows "Marks couldn't be saved into the file yet;
they're kept and will retry." The save retries on the next change, when `doc_sync`
sees the file return, and on the next profile open. Nothing is dropped silently.

**Flush.** Closing a tab or the profile runs any pending bake to completion first.

**What other apps see (unchanged):** real highlight and FreeText annotations with
`/DA`; a pristine original in `pdf_originals/`; removing every mark restores it.

### 5. Testing and rollout

**Automated tests** (headless, temporary directories, real PDFs made with the vendored
pypdf, real `QFileSystemWatcher` under offscreen Qt driven by `processEvents`; never the
real `user_files`):
- `pdf_source`: range bounds, 1 MB cap, a stale fingerprint returns `stale`, an old
  generation is refused, no handle stays open after a read.
- `doc_sync`:
  - an outside write reloads and an own write is ignored;
  - a half-written file waits for the stable-file rule;
  - a Finder rename re-points after the rescan, not before;
  - a delete flags and closes the tab, and reappearance reconnects;
  - a closed PDF changed outside is re-extracted, while an own write is not;
  - hidden tmp files never start a rescan.
- `annotation_save`:
  - one worker per PDF;
  - a rename during a bake writes to the new path;
  - a failed write keeps the JSON and retries;
  - flush on close;
  - the post-step pins the fingerprint.
- Zoom: the event filter forwards `ZoomNativeGesture` and swallows
  `SmartZoomNativeGesture`, tested with synthetic `QNativeGestureEvent`s on a stand-in
  widget.
- The disk → reader path gets coverage for the first time.

**Live checks with Pouya** (WebEngine cannot be imported under system python3):
- time to first page on the largest lecture and on `Bootcamp.com Hematology & Oncology`,
  measured before and after;
- scrolling and zooming, including the gray-background bug and two-finger double-tap;
- a Preview edit round trip on an open PDF;
- Finder rename, move and delete of open and closed PDFs;
- all four places.

**Rollout.** Each phase is one board card, committed separately with its tests passing:
1. Save pipeline and sync engine (sections 3 and 4).
2. Piece loader, render cache, per-page mark redraw, incremental find, zoom fix
   (section 1).
3. Reader panel with tabs in every host; all hosts on pdf.js; Preferences row removed;
   lazy dock load; viewer-mode sizing fix (section 2).
4. Pouya's few-day trial.
5. Delete `PdfViewer`, its native-only helpers and tests; update CLAUDE.md, config.md
   and DESIGN.md.

**Coordination.**
- Before claiming phase 3, run `git status` on `library_viewer.py` and `library_sidebar.py`.
  K-313 and K-317 are in Review and K-313 may be uncommitted. Park any foreign hunk with
  CLAUDE.md's stash, patch and board-comment rule.
- K-095 and K-101 are closed by a board comment pointing here, not deleted.

## Out of scope

- The per-PDF notes pane, K-079.
- The embedding map (`pdf_map`, no entry point today).
- Raising the 200 MB limit.
- Upgrading the vendored pdf.js.

## Risks

- **Zoom fix unconfirmed.** It is inferred from the code, and native gesture delivery
  inside QtWebEngine can only be confirmed live.
- **Piece loading may not pay off on every file.** On PDFs whose cross-reference data
  sits at the end or is fragmented, pdf.js may request many ranges before the first
  page. The before-and-after measurement decides whether `rangeChunkSize` needs tuning
  or small files should skip piece loading.
- **Unsaved-edit loss on outside change.** A reload after an outside change would
  discard a text box still being typed. The reload waits until an open text box
  commits (blur or Escape), and its record is saved before the new file is read.
