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


def _user_files() -> str:
    from . import USER_FILES

    return USER_FILES


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
    uf = _user_files()
    display = drive_store.display_name(uf, safe)
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
    uf = _user_files()
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


def _on_fs_tick() -> None:
    """Debounced watcher target: something under the library root changed
    on disk. A VISIBLE Library repaints via the full refresh path
    (``_refresh_rows`` rescans first, then rebuilds); otherwise a bare
    rescan keeps mapping/tree/tags in step while nothing is showing, and
    any hidden screen is marked to refresh on its next show."""
    try:
        start_library_rescan()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library watcher rescan failed: {e}")
    # After the rescan settled the mapping: any open viewer showing a
    # file that changed on disk reloads it (K-078 — Preview saves swap
    # the inode, so the open QPdfDocument goes stale otherwise).
    try:
        from . import pdf_viewer

        pdf_viewer.poll_external_changes()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] viewer external-change poll failed: {e}")


def _rearm_watcher(root: str | None) -> None:
    """Point the watcher at the root and every current subdirectory.
    Called after every rescan — moved or newly created directories fall
    off a QFileSystemWatcher silently. Idempotent and cheap."""
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
                lambda _p: _fs_debounce.start()
            )
        old = list(_fs_watcher.directories())
        if old:
            _fs_watcher.removePaths(old)
        if not root or not os.path.isdir(root):
            return
        paths = [root]
        for dirpath, dirnames, _files in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            paths.extend(os.path.join(dirpath, d) for d in dirnames)
        _fs_watcher.addPaths(paths)
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
    uf = _user_files()
    _rescan["running"] = True

    def finish(prepared: dict | None, error: str = "") -> None:
        _rescan["running"] = False
        if error:  # the scan itself is silent; only a failure reaches the bar
            _task(lambda t: (t.begin("rescan", error), t.end("rescan", error, error=True)))
        summary = rescan_library_root(prepared)
        if summary and summary.get("ingested"):
            _after_ingest(summary["ingested"])
        if summary and (summary.get("moved") or summary.get("ingested") or summary.get("tree_changed")):
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
        parent=mw, op=lambda _col: pdf_handler.prepare_rescan(uf, root), success=finish
    ).failure(failed).without_collection().run_in_background()


def _after_ingest(safes: list[str]) -> None:
    """A PDF the folder scan imported gets what every other import
    surface gives it (``__init__.import_pdf_file``): page records for the
    transcript strip and current_page, a tag so it shows in Browse's
    sidebar, and auto-indexing when that is on."""
    uf = _user_files()
    for safe in safes:
        try:
            from . import page_store

            page_store.ensure_records(
                uf, safe, pdf_handler.pdf_path_for(uf, safe) or "", pdf_handler.load_pages(uf, safe) or []
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] page records for {safe!r} failed: {exc}")
        try:
            from . import index_queue

            index_queue.on_pdf_imported(safe)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] auto-index for {safe!r} failed: {exc}")
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
        uf = _user_files()
        folders = drive_store.load(uf).get("pdfs", {})
        try:
            # Single-copy sweep: anything still in the legacy pdfs/
            # store belongs in the root; migrate_to_root is idempotent.
            pdf_handler.migrate_to_root(uf, root, folders)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] rescan: straggler sweep failed: {exc}")
        summary = pdf_handler.rescan_root(uf, root, folders, prepared)
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
        # Every rescan re-arms the live watcher: directories that moved
        # or appeared since the last pass must fire the next one.
        _rearm_watcher(root)
        return summary
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library rescan failed: {exc}")
        return None


def _library_changed() -> None:
    """Browse's sidebar redraws the Library: names, warning icons, %."""
    try:
        from . import library_sidebar

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
        from . import pdf_viewer

        for sidebar in list(pdf_viewer._open_sidebars):
            if sidebar.is_loaded(safe):
                sidebar.clear()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] viewer clear on delete failed: {e}")
