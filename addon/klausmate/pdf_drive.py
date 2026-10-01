"""The Library's files: the folder scan, its watcher, and deleting PDFs.

The Library itself is the ``!Library`` tag branch in Browse's sidebar
(K-306..K-308; spec docs/superpowers/specs/2026-09-28-library-in-browse-
design.md): ``library_sidebar`` draws it, ``library_actions`` holds its
right-click actions, ``tag_sync`` keeps tags and PDFs in step. This
module keeps the disk half (K-073/K-075/K-309): the library root is
mirrored into the Library, renames on disk are matched by content, and
new files are imported off the main thread.

The Library window and the embedded Library screen that used to live
here were removed in K-308, and with them the top-bar Library link and
the map button (pdf_map/pdf_graph stay for a later home).
"""

from __future__ import annotations

import os
from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QFileSystemWatcher, QTimer
from aqt.utils import showWarning

from . import drive_store, pdf_handler, tag_sync
from . import settings


def apply_folder_change(
    user_files_dir: str, root: str | None, old: str, new: str
) -> tuple[bool, str]:
    """Move/rename a Library folder in BOTH stores — the directory on
    disk (when the live root has one) and drive_store — so the
    disk-truth rescan agrees with the change instead of reverting it on
    the next pass (K-076: the context-menu rename shipped store-only and
    snapped back live). Refuses merges: an occupied destination leaves
    everything untouched. Returns (ok, reason); reason is "exists" for
    an occupied destination, "invalid" for a bad name, "disk" when the
    directory move itself failed."""
    new = (new or "").strip().strip("/")
    if not new or not drive_store._valid_folder(new):
        return False, "invalid"
    if new == old:
        return True, ""
    data = drive_store.load(user_files_dir)
    occupied = new in data.get("folders", []) or any(
        (e.get("folder") or "") == new
        or (e.get("folder") or "").startswith(new + "/")
        for e in data.get("pdfs", {}).values()
    )
    src_dir = None
    if root and os.path.isdir(root):
        src_dir = os.path.join(root, *[p for p in old.split("/") if p])
        dst_dir = os.path.join(root, *[p for p in new.split("/") if p])
        occupied = occupied or os.path.exists(dst_dir)
    if occupied:
        return False, "exists"
    if src_dir is not None and os.path.isdir(src_dir):
        try:
            if not pdf_handler.rename_mapped_folder(user_files_dir, root, old, new):
                return False, "disk"
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] folder disk move failed {old!r}->{new!r}: {exc}")
            return False, "disk"
    if not drive_store.rename_folder(user_files_dir, old, new):
        return False, "invalid"
    return True, ""


def _move_to_trash(path: str) -> bool:
    """The Trash, not a permanent delete (K-306): a deleted tag is one
    click, so its PDF must be recoverable. Where there is no Trash a FILE
    stays where it is and this answers False for the caller to report —
    the confirmation promised the Trash, and a rescan re-importing the
    file loses nothing. A directory is only ever removed when empty,
    never rmtree'd."""
    ok = False
    try:
        from aqt.qt import QFile

        result = QFile.moveToTrash(path)
        ok = bool(result[0] if isinstance(result, tuple) else result)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] move to Trash failed for {path!r}: {exc}")
    if ok or not os.path.exists(path):
        return True
    if os.path.isdir(path):
        try:
            os.rmdir(path)  # raises unless empty: whatever is inside stays
            return True
        except OSError as exc:
            print(f"[klausmate] left {path!r} in place: {exc}")
            return False
    print(f"[klausmate] left {path!r} in place: no Trash")
    return False


def delete_pdf(safe: str) -> bool:
    """Delete one PDF from the Library, whichever surface asked: the
    Library's own Delete…, or a confirmed sidebar tag delete (K-306)."""
    uf = settings.user_files()
    display = drive_store.display_name(uf, safe)
    # Its marks go with it: no pending save may bake (or fail and toast)
    # once the readers showing it let go — clear() flushes.
    try:
        from . import annotation_save

        annotation_save.pipeline().forget(safe)
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] save pipeline forget failed: {e}")
    _close_in_panels(safe)
    # Must run BEFORE delete_context: that call chains into
    # retention.forget_prefs, which wipes this PDF's whole prefs.json
    # entry (including the stored tag name) — after that, there is no
    # way left to know what tag to remove.
    tag_sync.sync_after_delete(mw, safe, display)
    kept = []

    def _trash(path):
        if _move_to_trash(path) is False:
            kept.append(path)

    try:
        pdf_handler.delete_context(uf, safe, remove_file=_trash)
    except Exception as e:  # noqa: BLE001
        showWarning(f"Could not delete that PDF.\n\n{e}")
        return False
    if kept:
        showWarning("Could not move this to the Trash, so it was left in place:\n\n"
                    + "\n".join(kept))
    # Drop it from the index queue too (K-152). The runner re-checks
    # presence before it starts each job, so this is not what makes
    # a deleted PDF safe — it is what stops the bar advertising work
    # on a file the user just removed.
    try:
        from . import index_queue

        index_queue.forget(safe)
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] index queue forget failed: {e}")
    _library_changed()
    return True


def delete_folder(folder: str) -> None:
    """Drop a folder and its subfolders after their PDFs were deleted,
    and send the emptied directory to the Trash so a rescan cannot
    bring the folder back."""
    uf = settings.user_files()
    data = drive_store.load(uf)
    data["folders"] = [
        f for f in data.get("folders", []) if not (f == folder or f.startswith(folder + "/"))
    ]
    drive_store._save(uf, data)
    root = pdf_handler._live_library_root()
    if root and os.path.isdir(root):
        path = os.path.join(root, *[p for p in folder.split("/") if p])
        # Only an EMPTY directory goes: a folder of lectures often holds
        # the user's own notes (.md) beside the PDFs, and those are not
        # the Library's to delete. A leftover directory with no PDFs in
        # it is harmless — the rescan follows the mapping, not the dirs.
        leftovers = [n for n in os.listdir(path) if n != ".DS_Store"] if os.path.isdir(path) else None
        if leftovers == []:
            _move_to_trash(path)


# ------------------------------------------------------- live watcher
# Module-level, parented to mw, NOT to the Library window (K-076): the
# folder->Anki sync must stay live while the window is closed too, and a
# window-owned watcher died with its window.

_fs_watcher: Any = None
_fs_debounce: Any = None
_fs_changed: set = set()  # directories that fired since the last tick
_dir_names: dict = {}  # directory -> its visible entry names at the last re-arm


def _visible(names) -> set:
    return {n for n in names if not n.startswith(".")}


def _dir_snapshot(root: str) -> dict:
    """Directory -> visible entry names, for the root and every visible
    subdirectory: the pre-check's baseline. Taken BEFORE a scan walks, so
    anything that changes after the walk differs from it and rescans,
    whenever Qt gets round to delivering its event."""
    names = {}
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        names[dirpath] = _visible(dirnames + files)
    return names


def _tick_needs_rescan(dirs) -> bool:
    """The watcher's pre-check: False only when every changed entry is
    hidden (a bake's ``.x.pdf.<uuid>.tmp``) or a mapped PDF whose stat is
    the one recorded (Klaus's own bake). A directory whose visible names
    differ from the last re-arm, an unmapped or edited PDF, or anything
    unreadable rescans."""
    try:
        from . import pdf_source

        root = pdf_handler._live_library_root()
        if not dirs or not root:
            return True
        uf = pdf_source.user_files_dir()
        by_path = {os.path.join(root, rel): safe for safe, rel in pdf_handler.load_library_map(uf).items()}
        recorded = pdf_handler.load_library_stats(uf)
        for d in dirs:
            names = _visible(os.listdir(d))
            if names != _dir_names.get(d):
                return True
            for name in names:
                path = os.path.join(d, name)
                if not name.lower().endswith(".pdf") or not os.path.isfile(path):
                    continue
                safe, st = by_path.get(path), pdf_handler.file_stat(path)
                if safe is None or st is None or recorded.get(safe) != pdf_handler._stat_entry(st):
                    return True
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library watcher pre-check failed, rescanning: {e}")
        return True


def _on_fs_tick() -> None:
    """Debounced watcher target: something under the library root changed
    on disk. A VISIBLE Library repaints via the full refresh path
    (``_refresh_rows`` rescans first, then rebuilds); otherwise a bare
    rescan keeps mapping/tree/tags in step while nothing is showing, and
    any hidden screen is marked to refresh on its next show. A tick that
    saw only Klaus's own writes skips the rescan (``_tick_needs_rescan``).
    Open readers follow their files through doc_sync, not this tick."""
    dirs = set(_fs_changed)
    _fs_changed.clear()
    try:
        if _tick_needs_rescan(dirs):
            start_library_rescan()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library watcher rescan failed: {e}")


def _rearm_watcher(root: str | None, names: dict | None = None) -> None:
    """Point the watcher at the root and every current subdirectory.
    Called after every rescan — moved or newly created directories fall
    off a QFileSystemWatcher silently. Idempotent and cheap. ``names`` is
    the pre-check's new baseline (``_dir_snapshot`` from before the scan's
    walk) and also the directories to watch, so this never walks the tree
    on the main thread; None keeps the old baseline and walks."""
    global _fs_watcher, _fs_debounce
    if mw is None:
        return
    try:
        if _fs_watcher is None:
            _fs_watcher = QFileSystemWatcher(mw)
            _fs_debounce = QTimer(mw)
            _fs_debounce.setSingleShot(True)
            # 350ms (K-085): a Preview save should land in Klaus in
            # well under a second; still long enough to coalesce the
            # multi-event bursts Finder emits per move.
            _fs_debounce.setInterval(350)
            _fs_debounce.timeout.connect(_on_fs_tick)
            _fs_watcher.directoryChanged.connect(
                lambda p: (_fs_changed.add(p), _fs_debounce.start())
            )
        old = list(_fs_watcher.directories())
        if old:
            _fs_watcher.removePaths(old)
        if not root or not os.path.isdir(root):
            return
        if names is not None:  # the scan's own snapshot: no walk on the main thread
            paths = list(names)
        else:
            paths = [root]
            for dirpath, dirnames, _files in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                paths.extend(os.path.join(dirpath, d) for d in dirnames)
        _fs_watcher.addPaths(paths)
        if names is not None:
            _dir_names.clear()
            _dir_names.update(names)
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library watcher re-arm failed: {e}")


_rescan = {"running": False, "again": False}


def _task(report: Callable) -> None:
    """Report to the status bar; a report never breaks the scan."""
    try:
        from . import tasks

        report(tasks)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] rescan status report failed: {exc}")


def start_library_rescan(on_done: Callable[[dict | None], None] | None = None) -> None:
    """Rescan the library root without freezing Anki (K-309): reading
    and OCR-ing new PDFs runs in a background op that never touches the
    collection; applying the result — the mapping, the tree, the tags —
    happens back on the main thread. A rescan asked for while one runs
    is folded into one more pass afterwards."""
    if _rescan["running"]:
        _rescan["again"] = True
        return
    root = pdf_handler._live_library_root()
    if mw is None or not root or not os.path.isdir(root):
        summary = rescan_library_root()
        if on_done:
            on_done(summary)
        return
    uf = settings.user_files()
    _rescan["running"] = True

    def finish(prepared: dict | None, error: str = "") -> None:
        _rescan["running"] = False
        if error:  # the scan itself is silent; only a failure reaches the bar
            _task(lambda t: (t.begin("rescan", error), t.end("rescan", error, error=True)))
        summary = rescan_library_root(prepared)
        if summary and summary.get("ingested"):
            _after_ingest(summary["ingested"])
        if summary and any(summary.get(k) for k in ("moved", "ingested", "tree_changed", "newly_missing", "back")):
            _library_changed()
        if on_done:
            on_done(summary)
        if _rescan["again"]:
            _rescan["again"] = False
            start_library_rescan()

    def failed(exc: Exception) -> None:
        print(f"[klausmate] library rescan (background) failed: {exc}")
        finish(None, f"Folder scan failed: {exc}")

    QueryOp(
        parent=mw, op=lambda _col: _prepare(uf, root), success=finish
    ).failure(failed).without_collection().run_in_background()


_tmp_swept = False  # the session's first scan sweeps stranded bake tmps


def _prepare(uf: str, root: str) -> dict:
    """The background half: the watcher's baseline first, then the scan's
    own walk and reads (``prepare_rescan``). The session's first scan
    also clears bake tmp files a crash left in the root."""
    global _tmp_swept
    if not _tmp_swept:
        _tmp_swept = True
        pdf_handler.sweep_stranded_tmps(root)
    names = _dir_snapshot(root)
    prepared = pdf_handler.prepare_rescan(uf, root)
    prepared["names"] = names
    return prepared


def _after_ingest(safes: list[str]) -> None:
    """A PDF the folder scan imported gets what every other import
    surface gives it (``__init__.import_pdf_file``): page records for the
    transcript strip and current_page, and a tag so it shows in Browse's
    sidebar. Indexing waits for the Library's ⟳ (manual indexing)."""
    uf = settings.user_files()
    for safe in safes:
        try:
            from . import page_store

            page_store.ensure_records(
                uf, safe, pdf_handler.pdf_path_for(uf, safe) or "", pdf_handler.load_pages(uf, safe) or []
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] page records for {safe!r} failed: {exc}")
    # Registers the new PDFs' tags. Scheduled, not run inline: the
    # rescan just queued tag renames, and reading the collection before
    # they land mistook them for deletions (2026-09-30).
    tag_sync._schedule_reconcile()


def rescan_library_root(prepared: dict | None = None) -> dict | None:
    """Folder -> Anki half of the two-way Library sync (K-073).

    Walks the configured root, applies confirmed moves/renames to the
    mapping and the tree (pdf_handler.rescan_root), sweeps any legacy
    pdfs/ stragglers first via the idempotent migration, and hands the
    moved PDFs to tag_sync so their !Library tags follow the new
    folder/name. Returns the rescan summary, or None when no root is
    configured (or on any failure — this runs on profile open and on
    every Library refresh and must never break either).
    """
    try:
        root = pdf_handler._live_library_root()
        if not root or not os.path.isdir(root):
            _rearm_watcher(None)  # root unplugged/unset -> stop watching
            return None
        uf = settings.user_files()
        folders = drive_store.load(uf).get("pdfs", {})
        try:
            # Single-copy sweep: anything still in the legacy pdfs/
            # store belongs in the root; migrate_to_root is idempotent.
            pdf_handler.migrate_to_root(uf, root, folders)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] rescan: straggler sweep failed: {exc}")
        missing_before = pdf_handler.load_missing(uf)
        names = (prepared or {}).get("names")
        if names is None:
            names = _dir_snapshot(root)  # before rescan_root walks
        summary = pdf_handler.rescan_root(uf, root, folders, prepared)
        # A file that stays gone is reported every pass; readers and the
        # sidebar hear it once, when it goes.
        summary["newly_missing"] = [s for s in summary.get("missing") or [] if s not in missing_before]
        # tree_changed, not moved: the tags follow folder+display, and
        # those can change for entries the mapping already knew about
        # (drift repair — see rescan_root's tree loop).
        touched = list(summary.get("tree_changed") or []) + list(
            summary.get("ingested") or []
        )
        if touched and mw is not None and mw.col is not None:
            # Tags follow the tree (K-053 invariant). Ingested PDFs with
            # no match cache yet are skipped inside tag_sync (cold-cache
            # rule) and pick their tag up on first indexing.
            tag_sync.sync_after_folder_rename(mw, touched)
        _tell_readers(uf, root, summary)
        # Every rescan re-arms the live watcher: directories that moved
        # or appeared since the last pass must fire the next one.
        _rearm_watcher(root, names)
        return summary
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library rescan failed: {exc}")
        return None


def _tell_readers(uf: str, root: str, summary: dict) -> None:
    """After the mapping is applied, never before: open readers follow a
    move (the scan's, or Klaus's own rename/move, which the scan cannot
    see), hear a delete or a return (doc_sync), the watches are re-synced,
    and a PDF whose text changed waits for the Library's ⟳ (its row
    shows as stale; manual indexing)."""
    try:
        from . import doc_sync

        for safe, path in (summary.get("moved") or {}).items():
            doc_sync.repoint(safe, path)
        for safe in summary.get("newly_missing") or []:
            doc_sync.mark_missing(safe)
        mapping = pdf_handler.load_library_map(uf) if summary.get("back") else {}
        for safe in summary.get("back") or []:
            if safe in mapping:
                doc_sync.mark_back(safe, os.path.join(root, mapping[safe]))
        # Klaus's own rename/move already updated the map, so the scan
        # saw no move: an open reader still holds the old path.
        held = doc_sync.open_paths()
        mapping = pdf_handler.load_library_map(uf) if held else {}
        for safe, path in held.items():
            mapped = os.path.join(root, mapping[safe]) if safe in mapping else None
            if mapped and os.path.normpath(mapped) != os.path.normpath(path) and os.path.isfile(mapped):
                doc_sync.repoint(safe, mapped)
        doc_sync.resync()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] rescan: telling readers failed: {exc}")


def _library_changed() -> None:
    """Browse's sidebar and the Add tab's tree redraw the Library: names,
    warning icons, %."""
    try:
        from . import library_sidebar

        library_sidebar.refresh_trees()
        library_sidebar.refresh_status()
        library_sidebar.refresh_retention()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library sidebar refresh failed: {e}")


def refresh_open_library() -> None:
    """Preferences saved a new default sensitivity: every PDF without its
    own override reads it, so the sidebar's numbers follow."""
    _library_changed()


def _close_in_panels(safe: str) -> None:
    """A deleted PDF leaves every Browse PDF panel showing it."""
    try:
        from . import reader_panel

        for sidebar in list(reader_panel._open_sidebars):
            if sidebar.is_loaded(safe):
                sidebar.clear()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] viewer clear on delete failed: {e}")
