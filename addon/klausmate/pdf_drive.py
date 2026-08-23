"""The Klaus PDF drive — an Obsidian-style library window.

Left: a tree of every imported PDF, organised into VIRTUAL folders (no
file ever moves; the folder map lives in drive_store). Right: the existing
``PdfSidebar``, which works standalone — its ``editor`` argument is only
ever setattr'd behind an ``is None`` early-return.

Each row carries its retention score: the share of that PDF's matched
cards you'd currently recall, computed by retention.priority_rows from
cached artifacts only. Embedding, threshold tuning and the Browse hop all
run here — this window replaced the Klaus panel's Priorities tab.

Threading contract is lifted from chat_dock: long work runs on QueryOp
workers, a seq token discards callbacks from a cancelled or replaced run,
and the retrievability/match maps are cached so threshold changes
re-aggregate instantly without touching the collection.
"""

from __future__ import annotations

from typing import Any

import aqt
from aqt import gui_hooks, mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    Qt,
    QSlider,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showWarning, tooltip

from . import curation, deck_curate, drive_store, pdf_handler, retention

DIALOG_NAME = "KlausDrive"
_ROLE_SAFE = Qt.ItemDataRole.UserRole
_ROLE_FOLDER = Qt.ItemDataRole.UserRole + 1


def _user_files() -> str:
    from . import USER_FILES

    return USER_FILES


class DriveWindow(QWidget):
    """Standalone library window. Managed by aqt.dialogs."""

    # Required by the dialog manager for profile-switch teardown.
    silentlyClose = True

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Klaus — PDFs")
        self.setMinimumSize(720, 420)

        self.busy = False
        self.seq = 0
        self.cancel_event = None
        self.card_r: dict = {}
        self.matches: dict = {}
        self.rows: dict[str, dict] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(self.splitter, 1)

        # ---- left: tree + status ----
        left = QWidget(self.splitter)
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.tree = QTreeWidget(left)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["PDF", "Retention", "Cards"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        try:
            self.tree.setColumnWidth(0, 240)
            self.tree.header().setStretchLastSection(False)
            self.tree.setColumnWidth(1, 80)
        except Exception:
            pass
        lay.addWidget(self.tree, 1)

        btn_row = QHBoxLayout()
        new_folder = QPushButton("New folder", left)
        new_folder.clicked.connect(lambda: self._new_folder())
        btn_row.addWidget(new_folder)
        refresh = QPushButton("Refresh", left)
        refresh.clicked.connect(self._refresh_rows)
        btn_row.addWidget(refresh)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.status = QLabel("", left)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 11px; opacity: 0.8;")
        lay.addWidget(self.status)

        self.cancel_btn = QPushButton("Cancel", left)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setVisible(False)
        lay.addWidget(self.cancel_btn)

        # ---- right: the existing viewer ----
        from .pdf_viewer import PdfSidebar

        self.sidebar = PdfSidebar(None, parent=self.splitter)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.sidebar)
        self.splitter.setStretchFactor(1, 1)

        self._restore_geometry()
        self.rebuild_tree()
        self._refresh_rows()

        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            print(f"[klausmate] drive show failed: {e}")

    # -------------------------------------------------------- geometry

    _MIN_PANE = 120

    def _sane_splitter_sizes(self, sizes: object) -> list[int] | None:
        """Reject degenerate splitter sizes (e.g. saved from a never-shown
        window, where sizes() returns something like [46, 46])."""
        if not isinstance(sizes, list) or len(sizes) != 2:
            return None
        try:
            ints = [int(s) for s in sizes]
        except (TypeError, ValueError):
            return None
        if any(s < self._MIN_PANE for s in ints):
            return None
        return ints

    def _restore_geometry(self) -> None:
        try:
            state = drive_store.get_window_state(_user_files())
            if state.get("w") and state.get("h"):
                self.resize(int(state["w"]), int(state["h"]))
                if state.get("x") is not None and state.get("y") is not None:
                    self.move(int(state["x"]), int(state["y"]))
            else:
                self.resize(1040, 680)
            sane = self._sane_splitter_sizes(state.get("splitter"))
            self.splitter.setSizes(sane if sane is not None else [300, 740])
        except Exception as e:
            print(f"[klausmate] drive geometry restore failed: {e}")
            self.resize(1040, 680)

    def _save_geometry(self) -> None:
        try:
            if not self.isVisible():
                # A window that was constructed but never shown has bogus
                # geometry/splitter sizes (e.g. splitter.sizes() == [46, 46]
                # before any layout pass) — persisting it would poison the
                # next restore. Nothing to save in that case.
                return
            sizes = list(self.splitter.sizes())
            geo = self.geometry()
            state = {
                "x": geo.x(),
                "y": geo.y(),
                "w": geo.width(),
                "h": geo.height(),
            }
            if self._sane_splitter_sizes(sizes) is not None:
                state["splitter"] = sizes
            drive_store.save_window_state(_user_files(), state)
        except Exception as e:
            print(f"[klausmate] drive geometry save failed: {e}")

    # ------------------------------------------------------------ tree

    def rebuild_tree(self) -> None:
        """Repaint the tree from disk, preserving selection where possible."""
        try:
            selected = self._selected_safe()
            user_files = _user_files()
            contexts = pdf_handler.list_contexts(user_files)
            data = drive_store.load(user_files)
            tree = drive_store.build_tree(contexts, data)
            self.tree.clear()

            folder_items: dict[str, QTreeWidgetItem] = {}

            def folder_item(path: str) -> QTreeWidgetItem:
                if path in folder_items:
                    return folder_items[path]
                parent_path, _, leaf = path.rpartition("/")
                parent = folder_item(parent_path) if parent_path else None
                item = (
                    QTreeWidgetItem(parent, [leaf])
                    if parent is not None
                    else QTreeWidgetItem(self.tree, [leaf])
                )
                item.setData(0, _ROLE_FOLDER, path)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                item.setExpanded(True)
                folder_items[path] = item
                return item

            for path, pdfs in tree["folders"].items():
                parent = folder_item(path)
                for pdf in pdfs:
                    self._add_pdf_item(parent, pdf)
            for pdf in tree["root"]:
                self._add_pdf_item(None, pdf)

            if selected:
                self._select_safe(selected)
            if not contexts:
                self.status.setText(
                    "No PDFs yet — drop one on the deck list or the editor's "
                    "PDF bar to add it here."
                )
        except Exception as e:
            print(f"[klausmate] drive tree rebuild failed: {e}")

    def _add_pdf_item(self, parent, pdf: dict) -> QTreeWidgetItem:
        item = (
            QTreeWidgetItem(parent, [pdf["display"]])
            if parent is not None
            else QTreeWidgetItem(self.tree, [pdf["display"]])
        )
        item.setData(0, _ROLE_SAFE, pdf["safe"])
        item.setToolTip(0, pdf["safe"])
        self._apply_row(item, self.rows.get(pdf["safe"]))
        return item

    def _apply_row(self, item: QTreeWidgetItem, row: dict | None) -> None:
        if not row:
            item.setText(1, "—")
            item.setText(2, "")
            return
        if not row.get("indexed"):
            item.setText(1, "—")
            item.setText(2, "not embedded")
            return
        if row.get("stale"):
            item.setText(1, "—")
            item.setText(2, "re-embed needed")
            return
        retention_val = row.get("retention")
        item.setText(
            1, f"{round(retention_val * 100)}%" if retention_val is not None else "—"
        )
        cards = int(row.get("matched_cards") or 0)
        new_pct = float(row.get("new_pct") or 0.0)
        item.setText(
            2,
            f"{cards:,} cards · {round(new_pct * 100)}% unseen" if cards else "no matches",
        )

    def _iter_pdf_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            for i in range(item.childCount()):
                stack.append(item.child(i))
            if item.data(0, _ROLE_SAFE):
                yield item

    def _selected_safe(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, _ROLE_SAFE) if item is not None else None

    def _select_safe(self, safe: str) -> None:
        for item in self._iter_pdf_items():
            if item.data(0, _ROLE_SAFE) == safe:
                self.tree.setCurrentItem(item)
                return

    # ------------------------------------------------------- run plumbing

    def _begin(self):
        if self.busy:
            tooltip("Klaus is already working — wait for it to finish.")
            return None
        import threading

        self.busy = True
        self.seq += 1
        self.cancel_event = threading.Event()
        self.cancel_btn.setVisible(True)
        return self.seq, self.cancel_event

    def _finish(self, seq: int) -> bool:
        if seq != self.seq:
            return False
        self.busy = False
        self.cancel_btn.setVisible(False)
        return True

    def _on_progress(self, seq: int, label: str, done: int, total: int) -> None:
        if seq != self.seq:
            return
        pct = f" {round(done * 100 / total)}%" if total else ""
        self.status.setText(f"{label}{pct}")

    def _on_cancel(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
        self.seq += 1
        self.busy = False
        self.cancel_btn.setVisible(False)
        self.status.setText("Cancelled.")

    # -------------------------------------------------------- retention

    def _refresh_rows(self) -> None:
        if mw is None or mw.col is None:
            return
        seq = self.seq

        def done(out: dict) -> None:
            if seq != self.seq or not self._alive():
                return
            self.card_r = out.get("card_r") or {}
            self.matches = out.get("matches") or {}
            self.rows = {r["name"]: r for r in out.get("rows") or []}
            for item in self._iter_pdf_items():
                self._apply_row(item, self.rows.get(item.data(0, _ROLE_SAFE)))
            notes = []
            if not out.get("card_index_ok"):
                notes.append(
                    "Cards aren't indexed for the current embedding settings — "
                    "run a search from the Klaus panel first."
                )
            if out.get("approx"):
                notes.append("Retention is approximate — enable FSRS for exact numbers.")
            self.status.setText("  ".join(notes))

        def fail(exc: Exception) -> None:
            if self._alive():
                self.status.setText(f"Could not load retention: {exc}")

        # Parented to mw, not self: the window may be closed mid-run, and a
        # QueryOp whose parent is destroyed takes the callback down with it.
        # Staleness is handled by the seq token and _alive() instead.
        op = QueryOp(
            parent=mw,
            op=lambda col: retention.priority_rows(col, curation._cfg()),
            success=done,
        )
        op.failure(fail)
        op.run_in_background()

    def _alive(self) -> bool:
        try:
            self.isVisible()
            return True
        except RuntimeError:  # C++ side deleted
            return False

    def _on_embed(self, safe: str) -> None:
        handle = self._begin()
        if handle is None:
            return
        seq, cancel = handle

        def on_error(exc: Exception) -> None:
            if not self._finish(seq):
                return
            from . import embeddings

            msg = (
                exc.user_message()
                if isinstance(exc, embeddings.EmbeddingError)
                else str(exc)
            )
            self.status.setText(msg)

        def after_matches(_matches) -> None:
            if not self._finish(seq):
                return
            self.status.setText("Embedded — refreshing retention…")
            self._refresh_rows()

        def after_index(idx) -> None:
            if seq != self.seq:
                return
            if not idx.is_complete():
                if self._finish(seq):
                    self.status.setText(
                        "Embedding cancelled — it resumes where it stopped."
                    )
                return
            retention.ensure_matches(
                mw,
                safe,
                on_progress=lambda l, d, t: self._on_progress(seq, l, d, t),
                on_done=after_matches,
                on_error=on_error,
                cancel=cancel,
            )

        retention.ensure_pdf_index(
            mw,
            safe,
            on_progress=lambda l, d, t: self._on_progress(seq, l, d, t),
            on_done=after_index,
            on_error=on_error,
            cancel=cancel,
        )

    def _on_threshold(self, safe: str) -> None:
        cfg = curation._cfg()
        current = retention.get_threshold(safe, cfg)
        dlg = QDialog(self)
        dlg.setWindowTitle("Match strictness")
        lay = QVBoxLayout(dlg)
        label = QLabel("", dlg)
        lay.addWidget(
            QLabel("How closely must a card relate to this PDF to count?", dlg)
        )
        slider = QSlider(Qt.Orientation.Horizontal, dlg)
        slider.setMinimum(20)
        slider.setMaximum(60)
        slider.setValue(int(round(current * 100)))
        lay.addWidget(slider)
        lay.addWidget(label)
        matches = self.matches.get(safe)

        def preview(value: int) -> None:
            threshold = value / 100.0
            if matches is None:
                label.setText(f"Threshold {threshold:.2f}")
                return
            agg = retention.pdf_retention(
                [(int(n), float(s)) for n, s in matches], threshold, self.card_r
            )
            ret = agg["retention"]
            ret_txt = f"{round(ret * 100)}%" if ret is not None else "—"
            label.setText(
                f"Threshold {threshold:.2f} · {agg['matched_cards']:,} cards · "
                f"retention {ret_txt}"
            )

        slider.valueChanged.connect(preview)
        preview(slider.value())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value = slider.value() / 100.0
        retention.set_threshold(safe, value)
        row = self.rows.get(safe)
        if row is not None and matches is not None:
            agg = retention.pdf_retention(
                [(int(n), float(s)) for n, s in matches], value, self.card_r
            )
            row.update(threshold=value, **{
                k: agg[k] for k in ("retention", "matched_cards", "new_pct", "priority")
            })
            for item in self._iter_pdf_items():
                if item.data(0, _ROLE_SAFE) == safe:
                    self._apply_row(item, row)

    def _on_browse(self, safe: str) -> None:
        matches = self.matches.get(safe)
        if not matches:
            self.status.setText("Embed this PDF first to see its matched cards.")
            return
        threshold = retention.get_threshold(safe, curation._cfg())
        nids = [int(n) for n, s in matches if float(s) >= threshold]
        if not nids:
            self.status.setText(
                "No cards above the current strictness — lower it in Threshold…"
            )
            return
        retention.preview_matches(mw, nids)

    # ----------------------------------------------------------- actions

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        safe = item.data(0, _ROLE_SAFE)
        if not safe:
            item.setExpanded(not item.isExpanded())
            return
        try:
            self.sidebar.load_pdf(safe)
            pdf_handler.touch_last_used(_user_files(), safe)
        except Exception as e:
            print(f"[klausmate] drive open failed for {safe}: {e}")
            showWarning(f"Could not open that PDF.\n\n{e}")

    def _new_folder(self, parent_path: str | None = None) -> str | None:
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        name = (name or "").strip().strip("/")
        if not ok or not name:
            return None
        path = f"{parent_path}/{name}" if parent_path else name
        if not drive_store.add_folder(_user_files(), path):
            showWarning("That folder name isn't valid.")
            return None
        self.rebuild_tree()
        return path

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is not None and item.data(0, _ROLE_SAFE):
            self._build_pdf_menu(menu, item)
        elif item is not None and item.data(0, _ROLE_FOLDER):
            self._build_folder_menu(menu, item.data(0, _ROLE_FOLDER))
        else:
            menu.addAction("New folder…").triggered.connect(lambda: self._new_folder())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_pdf_menu(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        safe = item.data(0, _ROLE_SAFE)
        row = self.rows.get(safe) or {}

        menu.addAction("Open").triggered.connect(
            lambda: self._on_item_activated(item)
        )
        menu.addAction("Rename…").triggered.connect(lambda: self._rename_pdf(safe))

        move = menu.addMenu("Move to folder")
        move.addAction("(root)").triggered.connect(
            lambda: self._move_pdf(safe, None)
        )
        for path in drive_store.load(_user_files()).get("folders") or []:
            move.addAction(path).triggered.connect(
                lambda _c=False, p=path: self._move_pdf(safe, p)
            )
        move.addSeparator()
        move.addAction("New folder…").triggered.connect(
            lambda: self._move_to_new_folder(safe)
        )

        menu.addSeparator()
        embed_label = "Re-embed for retention" if row.get("indexed") else "Embed for retention"
        menu.addAction(embed_label).triggered.connect(lambda: self._on_embed(safe))
        menu.addAction("Match strictness…").triggered.connect(
            lambda: self._on_threshold(safe)
        )
        menu.addAction("Show matched cards in Browse").triggered.connect(
            lambda: self._on_browse(safe)
        )
        menu.addAction("Curate deck from this PDF…").triggered.connect(
            lambda: self._curate(safe)
        )
        menu.addSeparator()
        menu.addAction("Delete…").triggered.connect(lambda: self._delete_pdf(safe))

    def _build_folder_menu(self, menu: QMenu, path: str) -> None:
        menu.addAction("New subfolder…").triggered.connect(
            lambda: self._new_folder(path)
        )
        menu.addAction("Rename folder…").triggered.connect(
            lambda: self._rename_folder(path)
        )
        menu.addAction("Remove folder").triggered.connect(
            lambda: self._remove_folder(path)
        )

    def _rename_pdf(self, safe: str) -> None:
        current = drive_store.display_name(_user_files(), safe)
        name, ok = QInputDialog.getText(
            self, "Rename PDF", "Display name:", text=current
        )
        if ok and (name or "").strip():
            drive_store.rename_display(_user_files(), safe, name.strip())
            self.rebuild_tree()

    def _move_pdf(self, safe: str, folder: str | None) -> None:
        drive_store.set_folder(_user_files(), safe, folder)
        self.rebuild_tree()

    def _move_to_new_folder(self, safe: str) -> None:
        path = self._new_folder()
        if path:
            self._move_pdf(safe, path)

    def _rename_folder(self, path: str) -> None:
        leaf = path.rsplit("/", 1)[-1]
        name, ok = QInputDialog.getText(
            self, "Rename folder", "Folder name:", text=leaf
        )
        name = (name or "").strip().strip("/")
        if not ok or not name:
            return
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        new_path = f"{parent}/{name}" if parent else name
        if drive_store.rename_folder(_user_files(), path, new_path):
            self.rebuild_tree()
        else:
            showWarning("That folder name isn't valid.")

    def _remove_folder(self, path: str) -> None:
        drive_store.remove_folder(_user_files(), path)
        self.rebuild_tree()

    def _delete_pdf(self, safe: str) -> None:
        display = drive_store.display_name(_user_files(), safe)
        answer = QMessageBox.question(
            self,
            "Delete PDF",
            f"Delete “{display}”?\n\n"
            "This removes the PDF, its extracted text, your highlights and "
            "notes, and its retention index. Cards are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.sidebar.is_loaded(safe):
                self.sidebar.clear()
        except Exception:
            pass
        try:
            pdf_handler.delete_context(_user_files(), safe)
        except Exception as e:
            showWarning(f"Could not delete that PDF.\n\n{e}")
            return
        try:
            deck_curate.disarm_if(safe)
        except Exception:
            pass
        self.rows.pop(safe, None)
        self.matches.pop(safe, None)
        self.rebuild_tree()
        tooltip(f"Deleted “{display}”.")

    def _curate(self, safe: str) -> None:
        if mw is None or mw.col is None:
            return
        accepted, deck = deck_curate.choose_deck_scope(self)
        if accepted:
            deck_curate.run_curation_flow(safe, deck, parent=mw)

    # --------------------------------------------------------- lifecycle

    def reopen(self, *args, **kwargs) -> None:
        self.rebuild_tree()
        self._refresh_rows()
        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            print(f"[klausmate] drive reopen show failed: {e}")

    def closeEvent(self, evt) -> None:  # noqa: N802 — Qt naming
        global _instance
        try:
            self._on_cancel()
            self._save_geometry()
            self.sidebar.clear()
        except Exception as e:
            print(f"[klausmate] drive close cleanup failed: {e}")
        if _instance is self:
            _instance = None
        try:
            aqt.dialogs.markClosed(DIALOG_NAME)
        except Exception:
            pass
        super().closeEvent(evt)


# ------------------------------------------------------------ module API


_instance: DriveWindow | None = None


def _create() -> DriveWindow:
    global _instance
    _instance = DriveWindow()
    return _instance


def open_drive() -> None:
    try:
        aqt.dialogs.open(DIALOG_NAME)
    except Exception as e:
        print(f"[klausmate] drive open failed: {e}")
        showWarning(f"Could not open the PDF drive.\n\n{e}")


def _close_drive() -> None:
    """Close the window if open — geometry is persisted by closeEvent."""
    global _instance
    window, _instance = _instance, None
    if window is None:
        return
    try:
        window.close()
    except RuntimeError:
        pass  # already destroyed on the C++ side
    except Exception as e:
        print(f"[klausmate] drive teardown failed: {e}")


def _on_toolbar_links(links: list, toolbar: Any) -> None:
    """Prepend the drive link so it sits left of Decks…Sync."""
    try:
        links.insert(
            0,
            toolbar.create_link(
                "klausDriveOpen",
                "PDFs",
                open_drive,
                tip="Klaus PDF drive",
                id="klaus-drive",
            ),
        )
    except Exception as e:
        print(f"[klausmate] drive toolbar link failed: {e}")


def setup() -> None:
    try:
        aqt.dialogs.register_dialog(DIALOG_NAME, lambda *a, **k: _create())
    except Exception as e:
        print(f"[klausmate] drive dialog registration failed: {e}")
        return
    try:
        gui_hooks.top_toolbar_did_init_links.append(_on_toolbar_links)
    except Exception as e:
        print(f"[klausmate] drive toolbar hook failed: {e}")
    try:
        gui_hooks.profile_will_close.append(_close_drive)
    except Exception as e:
        print(f"[klausmate] drive profile hook failed: {e}")
    try:
        mw.app.aboutToQuit.connect(_close_drive)
    except Exception as e:
        print(f"[klausmate] drive quit hook failed: {e}")
