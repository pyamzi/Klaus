"""Library actions without a Library window (K-307).

What the Library window's right-click menu did, callable with just a
PDF's safe name or a folder path plus a parent widget, so Browse's
sidebar menu can offer it. Every dialog is an instance opened with
``open()`` (K-114/K-125), never an exec.
"""
from __future__ import annotations

import os
import shutil
from typing import Callable

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSlider,
    Qt,
    QVBoxLayout,
)
from aqt.utils import showWarning, tooltip

from . import drive_store, pdf_handler, tag_sync


def _uf() -> str:
    from . import pdf_drive

    return pdf_drive._user_files()


def _style(dialog) -> None:
    try:
        from . import theme

        dialog.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] dialog theme failed: {exc}")


def _refresh() -> None:
    from . import pdf_drive

    pdf_drive._library_changed()


def _live_root() -> str | None:
    root = pdf_handler._live_library_root()
    return root if root and os.path.isdir(root) else None


def pdfs_under(folder: str) -> list[str]:
    tree = drive_store.build_tree(pdf_handler.list_contexts(_uf()), drive_store.load(_uf()))
    return sorted(
        p["safe"]
        for f, items in tree["folders"].items()
        if f == folder or f.startswith(folder + "/")
        for p in items
    )


# ------------------------------------------------------------ viewing


def show_in_finder(safe: str) -> None:
    path = pdf_handler.pdf_path_for(_uf(), safe)
    if not path or not os.path.exists(path):
        tooltip("This PDF's file could not be found.")
        return
    from aqt.utils import show_in_folder

    show_in_folder(path)


def history(parent, safe: str) -> None:
    from . import retention_history

    retention_history.open_history_dialog(
        parent, safe, tag_sync.strip_pdf_ext(drive_store.display_name(_uf(), safe))
    )


# ------------------------------------------------------------ indexing


def reembed(safes: list[str]) -> None:
    from . import index_queue

    index_queue.request([(index_queue.JOB_PDF, s) for s in safes], announce=True)


def set_suspended(safe: str, suspend: bool) -> None:
    """Suspend or unsuspend every card carrying this PDF's tag, as one
    undoable op (the sched call brings its own undo entry)."""
    if mw is None or mw.col is None:
        return
    tag = tag_sync.get_stored_tag(safe) or tag_sync.desired_tag(*tag_sync._folder_and_display(safe))
    cids = list(mw.col.find_cards(tag_sync.tag_query(tag)))
    if not cids:
        tooltip("No cards carry this PDF's tag yet. Index it first.")
        return

    def op(col):
        return col.sched.suspend_cards(cids) if suspend else col.sched.unsuspend_cards(cids)

    verb = "Suspended" if suspend else "Unsuspended"
    CollectionOp(parent=mw, op=op).success(
        lambda _c: tooltip(f"{verb} {len(cids):,} cards (Ctrl+Z to undo)")
    ).run_in_background()


def sensitivity(parent, safe: str) -> None:
    """Match Sensitivity without a Library window: the matches and card
    recall it previews are loaded off the main thread first."""
    from . import retention

    cfg = retention._cfg()

    def load(col):
        matches = tag_sync._cached_matches_many([safe], cfg)[safe]
        card_r = retention.card_retrievability(col, {int(n) for n, _ in matches or []})
        return matches, card_r

    QueryOp(
        parent=mw, op=load, success=lambda res: sensitivity_dialog(parent, safe, *res)
    ).failure(lambda exc: tooltip(f"Could not load this PDF's matches: {exc}")).run_in_background()


def sensitivity_dialog(parent, safe: str, matches, card_r, on_applied: Callable | None = None) -> QDialog:
    from . import retention

    current = retention.get_threshold(safe, retention._cfg())
    dlg = QDialog(parent)
    dlg.setWindowTitle("Match Sensitivity")
    _style(dlg)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("How closely must a card relate to this PDF to count?", dlg))
    slider = QSlider(Qt.Orientation.Horizontal, dlg)
    slider.setMinimum(20)
    slider.setMaximum(80)
    slider.setValue(int(round(current * 100)))
    lay.addWidget(slider)
    label = QLabel("", dlg)
    lay.addWidget(label)

    def preview(value: int) -> None:
        threshold = value / 100.0
        if matches is None:
            label.setText(f"Threshold {threshold:.2f} · not indexed yet")
            return
        agg = retention.pdf_retention([(int(n), float(s)) for n, s in matches], threshold, card_r)
        ret = agg["retention"]
        ret_txt = f"{round(ret * 100)}%" if ret is not None else "—"
        label.setText(f"Threshold {threshold:.2f} · {agg['matched_cards']:,} cards · retention {ret_txt}")

    slider.valueChanged.connect(preview)
    preview(slider.value())
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)

    def apply() -> None:
        value = slider.value() / 100.0
        retention.set_threshold(safe, value)
        tag_sync.sync_after_threshold(mw, safe, matches, value)
        if on_applied is not None:
            on_applied(value)

    dlg.accepted.connect(apply)
    dlg.finished.connect(dlg.deleteLater)
    dlg.open()
    return dlg


# ------------------------------------------------------------ names and folders


def _ask_text(parent, title: str, label: str, value: str, on_text: Callable[[str], None]) -> QInputDialog:
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(value)
    _style(dlg)
    dlg.textValueSelected.connect(lambda raw: on_text(str(raw or "").strip()))
    dlg.finished.connect(lambda _r: dlg.deleteLater())
    dlg.open()
    return dlg


def rename_pdf(parent, safe: str) -> None:
    """For a PDF with no matched cards: Anki refuses to rename an empty
    tag, so the sidebar's own rename cannot reach it."""

    def apply(name: str) -> None:
        if not name:
            return
        drive_store.rename_display(_uf(), safe, name)
        root = _live_root()
        if root:
            pdf_handler.rename_mapped_file(_uf(), root, safe, name)
        _refresh()
        tag_sync.sync_after_rename(mw, safe)
        tag_sync._schedule_reconcile()  # an empty tag has no op to follow

    _ask_text(parent, "Rename PDF", "Name:", drive_store.display_name(_uf(), safe), apply)


def new_folder(parent, parent_path: str | None = None) -> None:
    def apply(name: str) -> None:
        name = name.strip("/")
        if not name:
            return
        path = f"{parent_path}/{name}" if parent_path else name
        if not drive_store.add_folder(_uf(), path):
            showWarning("That folder name isn't valid.", parent=parent)
            return
        root = _live_root()
        if root:
            os.makedirs(os.path.join(root, *path.split("/")), exist_ok=True)
        _refresh()
        tag_sync._schedule_reconcile()  # registers the new folder's tag

    _ask_text(parent, "New Folder", "Folder name:", "", apply)


def rename_folder(parent, path: str) -> None:
    """For an empty folder, which Anki's own rename refuses."""
    from . import pdf_drive

    leaf = path.rsplit("/", 1)[-1]

    def apply(name: str) -> None:
        name = name.strip("/")
        if not name or name == leaf:
            return
        up = path.rsplit("/", 1)[0] if "/" in path else ""
        new = f"{up}/{name}" if up else name
        ok, why = pdf_drive.apply_folder_change(_uf(), _live_root(), path, new)
        if not ok:
            showWarning(
                "A folder with that name already exists there." if why == "exists"
                else "That folder name isn't valid.",
                parent=parent,
            )
            return
        _refresh()
        tag_sync.sync_after_folder_rename(mw, pdfs_under(new))
        tag_sync._schedule_reconcile()

    _ask_text(parent, "Rename Folder", "Folder name:", leaf, apply)


def remove_empty_folder(path: str) -> None:
    """Only offered for a folder with no PDFs: a populated folder is
    deleted by deleting its tag, which asks first."""
    from . import pdf_drive

    pdf_drive.delete_folder(path)
    _refresh()
    tag = tag_sync.folder_tag(path)
    tag_sync._run_sync_op(mw, f"Klaus: remove folder “{path}”", lambda col: {"removed": tag_sync.apply_removal(col, tag)})


def confirm_delete_pdf(parent, safe: str) -> QMessageBox:
    from . import pdf_drive

    display = drive_store.display_name(_uf(), safe)
    box = QMessageBox(parent)
    box.setWindowTitle("Delete PDF")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(
        f"Delete “{display}”?\n\nThe PDF goes to the Trash. Its extracted text, "
        "your highlights and notes, and its retention index are removed. "
        "Cards are not touched."
    )
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setObjectName("DangerButton")
    box.button(QMessageBox.StandardButton.No).setObjectName("SecondaryButton")
    _style(box)

    def answered(_r: int) -> None:
        yes = box.standardButton(box.clickedButton()) == QMessageBox.StandardButton.Yes
        box.deleteLater()
        if yes and pdf_drive.delete_pdf(safe):
            tooltip(f"Deleted “{display}”.")

    box.finished.connect(answered)
    box.open()
    return box


# ------------------------------------------------------------ import


def import_files(paths: list[str], folder: str | None = None) -> int:
    """Import dropped or picked PDFs. With a library root they are
    COPIED into it (into ``folder``) and the background folder scan
    reads, imports and indexes them — nothing slow on the main thread.
    Without one, the old one-by-one import runs. Returns how many."""
    paths = [p for p in paths if p.lower().endswith(".pdf") and os.path.isfile(p)]
    if not paths:
        return 0
    root = _live_root()
    if root is None:
        from . import import_pdf_file

        for path in paths:
            safe = import_pdf_file(path)
            if safe and folder:
                drive_store.set_folder(_uf(), safe, folder)
        _refresh()
        return len(paths)
    dest = os.path.join(root, *[p for p in (folder or "").split("/") if p])
    os.makedirs(dest, exist_ok=True)
    for path in paths:
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(dest):
            continue  # already there; the scan will find it
        shutil.copy2(path, pdf_handler._unique_path(dest, os.path.basename(path)))
    from . import pdf_drive

    pdf_drive.start_library_rescan()
    tooltip(f"Importing {len(paths)} PDF{'s' if len(paths) != 1 else ''}…")
    return len(paths)


def pick_and_import(parent, folder: str | None = None) -> QFileDialog:
    """A file picker INSTANCE (the getOpenFileNames static execs)."""
    dlg = QFileDialog(parent, "Import PDFs")
    dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dlg.setNameFilter("PDF files (*.pdf)")
    dlg.filesSelected.connect(lambda files: import_files(list(files), folder))
    dlg.finished.connect(lambda _r: dlg.deleteLater())
    dlg.open()
    return dlg
