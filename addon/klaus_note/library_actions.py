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
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QMessageBox,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QSlider,
    Qt,
    QTimer,
    QVBoxLayout,
)
from aqt.utils import show_warning, tooltip  # show_warning opens (window-modal), never execs

from . import drive_store, pdf_handler, tag_sync
from . import settings


def _style(dialog) -> None:
    try:
        from . import theme

        dialog.setStyleSheet(theme.dialog_qss(theme.night_mode()))
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] dialog theme failed: {exc}")


def _refresh() -> None:
    from . import pdf_drive

    pdf_drive._library_changed()


def _live_root() -> str | None:
    root = pdf_handler._live_library_root()
    return root if root and os.path.isdir(root) else None


def exclude_confirm_text(name: str, kind: str, n_indexed: int) -> str:
    if kind == "pdf":
        return (f"Exclude “{name}” from the index? Its search index is deleted. "
                "Its cards keep their Library tag.")
    count = f"{n_indexed} PDF" + ("" if n_indexed == 1 else "s")
    return (f"Exclude “{name}” from the index? The search index of {count} in it is deleted. "
            "Their cards keep their Library tags.")


def _ask_exclude(parent, text: str, on_yes: Callable[[], None]) -> None:
    """Window-modal (K-114), Cancel the default: this deletes files."""
    box = QMessageBox(parent or mw)
    box.setWindowTitle("Exclude from Index")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    yes = box.addButton("Exclude", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    yes.setObjectName("DangerButton")
    cancel.setObjectName("SecondaryButton")
    _style(box)

    def answered(_result: int) -> None:
        chosen = box.clickedButton() is yes
        box.deleteLater()
        if chosen:
            on_yes()

    box.finished.connect(answered)
    box.open()


def _repaint_library() -> None:
    from . import library_sidebar

    library_sidebar.refresh_status()
    library_sidebar.refresh_trees()


def exclude(parent, kind: str, key: str, name: str) -> None:
    """Exclude a PDF (``key`` = safe name) or folder (``key`` = path) from
    indexing. Its index data is deleted, after a confirm when there is
    any; card tags are untouched (manual indexing spec, Rulings)."""
    from . import index_queue, pdf_index

    uf = settings.user_files()
    covered = [key] if kind == "pdf" else pdfs_under(key)
    indexed = [s for s in covered if os.path.isdir(pdf_index.index_dir(uf, s))]

    def do() -> None:
        if not drive_store.set_excluded(uf, kind, key, True):
            tooltip("Couldn't save the exclusion.", parent=parent)
            return
        for safe in covered:
            index_queue.forget(safe)
        for safe in indexed:
            pdf_index.delete(uf, safe)
        _repaint_library()

    if not indexed:
        do()
    else:
        _ask_exclude(parent, exclude_confirm_text(name, kind, len(indexed)), do)


def include(kind: str, key: str) -> None:
    """Undo an exclusion. Queues nothing: the row shows its warning
    icon until ⟳."""
    drive_store.set_excluded(settings.user_files(), kind, key, False)
    _repaint_library()


def pdfs_under(folder: str) -> list[str]:
    tree = drive_store.build_tree(pdf_handler.list_contexts(settings.user_files()), drive_store.load(settings.user_files()))
    return sorted(
        p["safe"]
        for f, items in tree["folders"].items()
        if f == folder or f.startswith(folder + "/")
        for p in items
    )


# ------------------------------------------------------------ viewing


def show_in_finder(safe: str) -> None:
    path = pdf_handler.pdf_path_for(settings.user_files(), safe)
    if not path or not os.path.exists(path):
        tooltip("This PDF's file could not be found.")
        return
    from aqt.utils import show_in_folder

    show_in_folder(path)


def history(parent, safe: str) -> None:
    from . import retention_history

    retention_history.open_history_dialog(
        parent, safe, tag_sync.strip_pdf_ext(drive_store.display_name(settings.user_files(), safe))
    )


# ------------------------------------------------------------ sensitivity


def sensitivity(parent, safe: str) -> None:
    """Match Sensitivity without a Library window: the matches and card
    recall it previews are loaded off the main thread first."""
    from . import retention

    cfg = settings.read()

    def load(col):
        matches = tag_sync._cached_matches_many([safe], cfg)[safe]
        card_r = retention.card_retrievability(col, {int(n) for n, _ in matches or []})
        return matches, card_r

    QueryOp(
        parent=mw, op=load, success=lambda res: sensitivity_dialog(parent, safe, *res)
    ).failure(lambda exc: tooltip(f"Could not load this PDF's matches: {exc}")).run_in_background()


def sensitivity_dialog(parent, safe: str, matches, card_r, on_applied: Callable | None = None) -> QDialog:
    from . import retention

    current = retention.get_threshold(safe, settings.read())
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


def _name_clash(parent_path: str | None, name: str, **kw) -> str | None:
    """#14: the PDF or folder ``name`` would share a tag with, as the
    message to show; None when the name is free."""
    pdfs, folders = tag_sync.library_layout()
    return tag_sync.name_clash(pdfs, folders, parent_path, name, **kw)


def new_folder(parent, parent_path: str | None = None) -> None:
    def apply(name: str) -> None:
        name = name.strip("/")
        if not name:
            return
        why = _name_clash(parent_path, name, is_folder=True)
        if why:
            show_warning(why, parent=parent)
            return
        path = f"{parent_path}/{name}" if parent_path else name
        if not drive_store.add_folder(settings.user_files(), path):
            show_warning("That folder name isn't valid.", parent=parent)
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
        clash = _name_clash(up or None, name, is_folder=True, skip=path)
        if clash:
            show_warning(clash, parent=parent)
            return
        ok, why = pdf_drive.apply_folder_change(settings.user_files(), _live_root(), path, new)
        if not ok:
            show_warning(
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
    if any(t.casefold() == tag.casefold() for t in tag_sync._stored_tags().values()):
        return  # #14: an old clash — a PDF stores this tag, so it stays that PDF's
    tag_sync._run_sync_op(mw, f"Klaus: remove folder “{path}”", lambda col: {"removed": tag_sync.apply_removal(col, tag)})


# ------------------------------------------------------------ import


def import_files(paths: list[str], folder: str | None = None) -> int:
    """Import dropped or picked PDFs. With a library root they are
    COPIED into it (into ``folder``) and the background folder scan
    reads, imports and indexes them — nothing slow on the main thread.
    Without one, the old one-by-one import runs. Returns how many."""
    paths = [p for p in paths if p.lower().endswith(".pdf") and os.path.isfile(p)]
    paths = _refuse_clashes(paths, folder)
    if not paths:
        return 0
    root = _live_root()
    if root is None:
        from . import import_pdf_file

        for path in paths:
            safe = import_pdf_file(path)
            if safe and folder:
                drive_store.set_folder(settings.user_files(), safe, folder)
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


def _refuse_clashes(paths: list[str], folder: str | None) -> list[str]:
    """#14: drop files whose name would share a tag with a folder or
    another PDF in ``folder``, in one warning naming each clash. A file
    named exactly like a PDF already there is a re-import, not a clash."""
    pdfs, folders = tag_sync.library_layout()
    same = {d.casefold() for f, d in pdfs.values() if (f or None) == (folder or None)}
    keep, refused = [], []
    for path in paths:
        name = os.path.basename(path)
        why = None if name.casefold() in same else tag_sync.name_clash(pdfs, folders, folder, name)
        if why:
            refused.append(why)
            continue
        keep.append(path)
        same.add(name.casefold())
        pdfs[f"\0import{len(keep)}"] = (folder or None, name)  # a batch can clash with itself
    if refused:
        # A tick later: this runs inside a Finder drop's event filter, and
        # a dialog there is the K-114 nested-loop crash class.
        text = "\n\n".join(refused)
        QTimer.singleShot(0, lambda: show_warning(text, parent=mw))
    return keep


def pick_and_import(parent, folder: str | None = None) -> QFileDialog:
    """A file picker INSTANCE (the getOpenFileNames static execs)."""
    dlg = QFileDialog(parent, "Import PDFs")
    dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dlg.setNameFilter("PDF files (*.pdf)")
    dlg.filesSelected.connect(lambda files: import_files(list(files), folder))
    dlg.finished.connect(lambda _r: dlg.deleteLater())
    dlg.open()
    return dlg
