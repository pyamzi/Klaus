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

import os
from typing import Any, Callable

import aqt
from aqt import gui_hooks, mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QFileSystemWatcher,
    QTimer,
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

from . import deck_curate, drive_store, pdf_handler, retention, tag_sync

DIALOG_NAME = "KlausDrive"
_ROLE_SAFE = Qt.ItemDataRole.UserRole
_ROLE_FOLDER = Qt.ItemDataRole.UserRole + 1
_ROLE_SORT = Qt.ItemDataRole.UserRole + 2
_UNKNOWN_SORT = -1.0


def _user_files() -> str:
    from . import USER_FILES

    return USER_FILES


def _dbg(msg: str) -> None:
    """K-075 TEMP DIAGNOSTICS — remove once folder sync is confirmed live.
    The profile-open rescan silently no-ops on Pouya's machine and stdout
    is invisible; this localizes where the chain dies."""
    try:
        import time as _time

        with open("/tmp/klausmate-debug.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{_time.strftime('%H:%M:%S')} drive: {msg}\n")
    except Exception:
        pass


def plan_folder_move(old: str, dest: str | None) -> str | None:
    """Destination path for dropping folder ``old`` into ``dest`` (None =
    root), or None when the drop is a no-op or illegal — a folder cannot
    move into itself or its own subtree. Pure: the drag handler and the
    tests share it (K-076)."""
    if not old:
        return None
    if dest is not None and (dest == old or dest.startswith(old + "/")):
        return None
    leaf = old.rsplit("/", 1)[-1]
    new = f"{dest}/{leaf}" if dest else leaf
    return None if new == old else new


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


# ------------------------------------------------------- live watcher
# Module-level, parented to mw, NOT to the Library window (K-076): the
# folder->Anki sync must stay live while the window is closed too, and a
# window-owned watcher died with its window.

_fs_watcher: Any = None
_fs_debounce: Any = None


def _on_fs_tick() -> None:
    """Debounced watcher target: something under the library root changed
    on disk. Window open -> the full refresh path repaints it (rescan +
    rebuild); closed -> a bare rescan still keeps mapping/tree/tags in
    step, so the sync is live all the time, not only while showing."""
    try:
        win = _instance
        if win is not None and win._alive() and win.isVisible():
            win._refresh_rows()
        else:
            rescan_library_root()
    except Exception as e:  # noqa: BLE001
        print(f"[klausmate] library watcher tick failed: {e}")


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
            _fs_debounce.setInterval(700)
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


def rescan_library_root() -> dict | None:
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
        _dbg("rescan: entered")
        root = pdf_handler._live_library_root()
        _dbg(f"rescan: root={root!r} isdir={bool(root and os.path.isdir(root))}")
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
        summary = pdf_handler.rescan_root(uf, root, folders)
        _dbg(f"rescan: summary={summary}")
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
        import traceback as _tb

        _dbg(f"rescan: FAILED {type(exc).__name__}: {exc}\n{_tb.format_exc()}")
        print(f"[klausmate] library rescan failed: {exc}")
        return None


class _LibraryItem(QTreeWidgetItem):
    """Tree item with numeric sort keys and folders pinned above PDFs.

    Column 0 (name) falls through to the base class's text comparison.
    Columns 1/2 (Retention, Cards) carry a numeric key in ``_ROLE_SORT``
    set by ``_apply_row`` — otherwise Qt would compare the display
    strings lexicographically ("100%" < "20%").

    Two invariants need to hold in EITHER sort direction: folders always
    sit above PDFs, and PDFs with no retention data (unembedded/stale/no
    row) always sink below ones that have it. Qt's descending sort does
    not just reverse the ascending list — its comparator swaps which
    item's ``__lt__`` gets called (``QTreeModel::itemGreaterThan`` calls
    ``right < left``) — so a plain "folder is less-than PDF" relation
    flips to the wrong side once the header is clicked to descending.
    Both branches below read the header's current sort order and invert
    the relation for that direction to cancel the flip out.
    """

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QTreeWidgetItem):
            return NotImplemented
        descending = self._descending()

        self_folder = bool(self.data(0, _ROLE_FOLDER))
        other_folder = bool(other.data(0, _ROLE_FOLDER))
        if self_folder != other_folder:
            return (not self_folder) if descending else self_folder

        col = self._sort_column()
        if col in (1, 2):
            self_key = self.data(col, _ROLE_SORT)
            other_key = other.data(col, _ROLE_SORT)
            if self_key is not None and other_key is not None:
                try:
                    self_val = float(self_key)
                    other_val = float(other_key)
                except (TypeError, ValueError):
                    return super().__lt__(other)
                self_known = self_val > _UNKNOWN_SORT
                other_known = other_val > _UNKNOWN_SORT
                if self_known != other_known:
                    return (not self_known) if descending else self_known
                return self_val < other_val
        return super().__lt__(other)

    def _descending(self) -> bool:
        try:
            tree = self.treeWidget()
            if tree is None:
                return False
            return tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        except Exception:
            return False

    def _sort_column(self) -> int:
        try:
            tree = self.treeWidget()
            return tree.sortColumn() if tree is not None else 0
        except Exception:
            return 0


class _LibraryTree(QTreeWidget):
    """QTreeWidget with drag-and-drop folder moves.

    ``drive.json`` is the single source of truth for folder placement —
    a drop never lets Qt perform the visual reparent itself. ``dropEvent``
    only resolves what moved where and hands off to the owning
    ``DriveWindow``, whose ``_move_pdf`` writes ``drive_store.set_folder``
    then calls ``rebuild_tree()``; the repaint from disk IS the move.
    """

    def __init__(self, window: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        try:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.setDropIndicatorShown(True)
        except Exception as e:
            print(f"[klausmate] library tree dnd setup failed: {e}")

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Resolve what moved where and hand off to DriveWindow; the
        rebuild from drive.json IS the visual move. Every path finishes
        the drop as an accepted IgnoreAction and schedules a next-tick
        rebuild: QAbstractItemView's InternalMove cleanup deletes the
        dragged row itself after an accepted MoveAction (and macOS has
        been seen doing it even for drops we ignored), which is exactly
        how Library folders were "disappearing" until reopen (K-076)."""
        try:
            try:
                if event.source() is self:
                    dragged = self.currentItem()
                    safe = dragged.data(0, _ROLE_SAFE) if dragged is not None else None
                    folder_path = (
                        dragged.data(0, _ROLE_FOLDER) if dragged is not None else None
                    )
                    target = self.itemAt(event.position().toPoint())
                    if target is None:
                        dest = None
                    elif target.data(0, _ROLE_FOLDER):
                        dest = target.data(0, _ROLE_FOLDER)
                    elif target.data(0, _ROLE_SAFE):
                        parent = target.parent()
                        dest = (
                            parent.data(0, _ROLE_FOLDER)
                            if parent is not None
                            else None
                        )
                    else:
                        dest = None

                    if safe:
                        current_parent = dragged.parent()
                        current_folder = (
                            current_parent.data(0, _ROLE_FOLDER)
                            if current_parent is not None
                            else None
                        )
                        if current_folder != dest:
                            self._window._move_pdf(safe, dest)
                    elif folder_path:
                        new = plan_folder_move(folder_path, dest)
                        if new:
                            self._window._move_folder(folder_path, new)
            finally:
                try:
                    event.setDropAction(Qt.DropAction.IgnoreAction)
                    event.accept()
                except Exception:
                    pass
                try:
                    QTimer.singleShot(0, self._window.rebuild_tree)
                except Exception:
                    pass
        except Exception as e:
            print(f"[klausmate] library drop failed: {e}")


class _LibraryDropZone(QWidget):
    """Drop-a-PDF square for the bottom of the Library's left pane.

    The Library is the one PDF surface with no way to add a PDF at all —
    its own empty state used to just point elsewhere. Every OTHER PDF
    entry point (deck browser, deck overview, editor's PDF bar) already
    has one of these; this closes the gap.

    Those three squares are two different implementations for two
    different hosts. deck_curate._drop_square_html() renders one as HTML
    with pycmd() onclick handlers for the deck browser/overview, which
    are webviews. This pane is a plain QTreeWidget + QVBoxLayout — no
    webview, no bridge — so that HTML has nothing to attach pycmd() to.
    __init__._PdfBar is the precedent for the native-Qt version:
    setAcceptDrops(True), a "dragOver" dynamic property toggled in
    dragEnter/dragLeave via style().unpolish/polish for hover feedback,
    and a dropEvent that hands matched .pdf paths to a plain Python
    callback. This class follows that exact shape rather than hosting a
    QWebEngineView for one box. One deliberate difference: _PdfBar bases
    itself on QFrame (+ setFrameShape(StyledPanel)) to get its stylesheet
    border painted; this class stays on QWidget and sets
    WA_StyledBackground instead, because tests/test_drive.py stubs
    aqt.qt with its own fixed, non-permissive name list (unlike the
    permissive stub anki_stubs.py provides elsewhere) and QFrame is not
    in it — adding it would mean editing a file outside this card's
    scope (klausmate/pdf_drive.py only). WA_StyledBackground on QWidget
    paints the same stylesheet border/background QFrame would.

    Unlike either existing square, this one never arms a PDF for
    curation (armed/× is deck-screen semantics — the Library's job here
    is only "get the file into the store and show it in the tree").

    Style values (idle border/radius, font-size, Browse-button chrome)
    are copied from deck_curate._drop_square_html() rather than shared,
    because this card's file scope is pdf_drive.py only and sharing them
    would mean also editing deck_curate.py. __init__._PdfBar already
    duplicates the same values for the same reason (see its docstring) —
    this makes three copies where until now there were two. Owed: pull
    idle-square border/radius/font-size/Browse-button styling into one
    module all three can import from. If you change these values here,
    update deck_curate._drop_square_html and __init__._PdfBar to match,
    and vice versa.
    """

    _IDLE_TEXT = "Drop a PDF to add"

    def __init__(
        self,
        on_paths: Callable[[list[str]], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_paths = on_paths
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("klausmateLibraryDropZone")
        self.setStyleSheet(
            "#klausmateLibraryDropZone {"
            " border: 1px dashed rgba(128, 128, 128, 0.55);"
            " border-radius: 10px;"
            " background: transparent;"
            "}"
            "#klausmateLibraryDropZone[dragOver=\"true\"] {"
            " border: 1px solid rgba(58, 130, 247, 0.85);"
            "}"
        )
        # One row: label takes the free space, Browse… sits hard right —
        # same shape as the deck square's flex row and _PdfBar's QHBoxLayout,
        # so all three drop surfaces read as the same component.
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        label = QLabel(self._IDLE_TEXT, self)
        label.setWordWrap(True)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        label.setStyleSheet(
            "font-size: 13px; color: rgba(120, 120, 120, 0.95);"
        )
        lay.addWidget(label, 1)

        browse_btn = QPushButton("Browse…", self)
        browse_btn.setFlat(True)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setStyleSheet(
            "QPushButton {"
            " border: 1px solid rgba(128, 128, 128, 0.55);"
            " border-radius: 6px;"
            " font-size: 12px;"
            " padding: 3px 10px;"
            " background: transparent;"
            "}"
            "QPushButton:hover {"
            " border-color: rgba(58, 130, 247, 0.55);"
            "}"
        )
        browse_btn.clicked.connect(self._browse)
        lay.addWidget(browse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _browse(self) -> None:
        from aqt.qt import QFileDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import PDF", "", "PDF files (*.pdf)"
        )
        if paths:
            self._on_paths(list(paths))

    def dragEnterEvent(self, e) -> None:  # type: ignore[override]
        md = e.mimeData()
        if md and md.hasUrls():
            for url in md.urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    self.setProperty("dragOver", "true")
                    self.style().unpolish(self)
                    self.style().polish(self)
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dragLeaveEvent(self, e) -> None:  # type: ignore[override]
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, e) -> None:  # type: ignore[override]
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        md = e.mimeData()
        if not md:
            return
        paths = [
            url.toLocalFile()
            for url in md.urls()
            if url.toLocalFile().lower().endswith(".pdf")
        ]
        if paths:
            self._on_paths(paths)
        e.acceptProposedAction()


class DriveWindow(QWidget):
    """Standalone library window. Managed by aqt.dialogs."""

    # Required by the dialog manager for profile-switch teardown.
    silentlyClose = True

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Klaus — Library")
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

        self.tree = _LibraryTree(self, left)
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
            self.tree.header().setSectionsClickable(True)
            self.tree.setSortingEnabled(True)
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

        self.drop_zone = _LibraryDropZone(self._on_dropped_paths, left)
        lay.addWidget(self.drop_zone)

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
        """Repaint the tree from disk, preserving selection, folder
        expansion, and scroll position where possible — it runs on every
        refresh now (K-076 live repaint), so it must be visually calm."""
        try:
            selected = self._selected_safe()
            expanded: dict[str, bool] = {}
            scroll = None
            try:
                stack = [
                    self.tree.topLevelItem(i)
                    for i in range(self.tree.topLevelItemCount())
                ]
                while stack:
                    it = stack.pop()
                    if it is None:
                        continue
                    path = it.data(0, _ROLE_FOLDER)
                    if path:
                        expanded[path] = it.isExpanded()
                    stack.extend(it.child(j) for j in range(it.childCount()))
                scroll = self.tree.verticalScrollBar().value()
            except Exception:
                pass
            user_files = _user_files()
            contexts = pdf_handler.list_contexts(user_files)
            data = drive_store.load(user_files)
            tree = drive_store.build_tree(contexts, data)
            # QTreeWidget re-sorts on every insertion while sorting is
            # enabled, which both wastes work and — worse — can land rows
            # in the wrong spot mid-repopulation (children inserted before
            # their sort keys are set). Disable for the rebuild, restore
            # whatever the user had after.
            was_sorting = self.tree.isSortingEnabled()
            self.tree.setSortingEnabled(False)
            try:
                self.tree.clear()

                folder_items: dict[str, QTreeWidgetItem] = {}

                def folder_item(path: str) -> QTreeWidgetItem:
                    if path in folder_items:
                        return folder_items[path]
                    parent_path, _, leaf = path.rpartition("/")
                    parent = folder_item(parent_path) if parent_path else None
                    item = (
                        _LibraryItem(parent, [leaf])
                        if parent is not None
                        else _LibraryItem(self.tree, [leaf])
                    )
                    item.setData(0, _ROLE_FOLDER, path)
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                    item.setExpanded(expanded.get(path, True))
                    folder_items[path] = item
                    return item

                for path, pdfs in tree["folders"].items():
                    parent = folder_item(path)
                    for pdf in pdfs:
                        self._add_pdf_item(parent, pdf)
                for pdf in tree["root"]:
                    self._add_pdf_item(None, pdf)
            finally:
                self.tree.setSortingEnabled(was_sorting)

            if selected:
                self._select_safe(selected)
            if scroll is not None:
                try:
                    self.tree.verticalScrollBar().setValue(scroll)
                except Exception:
                    pass
            if not contexts:
                self.status.setText(
                    "No PDFs yet — drop one on the deck list or the editor's "
                    "PDF bar to add it here."
                )
        except Exception as e:
            print(f"[klausmate] drive tree rebuild failed: {e}")

    def _add_pdf_item(self, parent, pdf: dict) -> QTreeWidgetItem:
        item = (
            _LibraryItem(parent, [pdf["display"]])
            if parent is not None
            else _LibraryItem(self.tree, [pdf["display"]])
        )
        item.setData(0, _ROLE_SAFE, pdf["safe"])
        # A PDF must never LOOK like a drop target (K-075): the model
        # already resolved such drops to the PDF's parent folder, but the
        # indicator invited "moving a PDF into a PDF". Folders keep the
        # default drop-enabled flag.
        try:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        except Exception:
            pass
        item.setToolTip(0, pdf["safe"])
        self._apply_row(item, self.rows.get(pdf["safe"]))
        return item

    def _apply_row(self, item: QTreeWidgetItem, row: dict | None) -> None:
        retention_val: float | None = None
        cards: int | None = None
        if not row:
            item.setText(1, "—")
            item.setText(2, "")
        elif not row.get("indexed"):
            item.setText(1, "—")
            item.setText(2, "not embedded")
        elif row.get("stale"):
            item.setText(1, "—")
            item.setText(2, "re-embed needed")
        else:
            retention_val = row.get("retention")
            item.setText(
                1, f"{round(retention_val * 100)}%" if retention_val is not None else "—"
            )
            cards = int(row.get("matched_cards") or 0)
            new_pct = float(row.get("new_pct") or 0.0)
            item.setText(
                2,
                f"{cards:,} cards · {round(new_pct * 100)}% unseen"
                if cards
                else "no matches",
            )
        # Sort keys live in a role, not the display text, so the tree can
        # sort numerically instead of lexicographically ("100%" < "20%").
        # -1.0 is an out-of-range sentinel: no row/not embedded/stale have
        # no retention *or* card count to speak of, so both columns sink
        # them to the bottom (see _LibraryItem.__lt__). A PDF that IS
        # embedded but matched nothing is a real, known zero — it sorts
        # with the numbers, not with the unknowns.
        item.setData(
            1, _ROLE_SORT, float(retention_val) if retention_val is not None else _UNKNOWN_SORT
        )
        item.setData(2, _ROLE_SORT, float(cards) if cards is not None else _UNKNOWN_SORT)
        self._set_retention_color(item, retention_val)

    def _set_retention_color(self, item: QTreeWidgetItem, fraction: float | None) -> None:
        """Color the retention cell's text only — no row background, no
        bold. Non-numeric states get no color override (default
        foreground): the product bar is "Anki with a little extra you
        barely notice."
        """
        try:
            if fraction is None:
                item.setData(1, Qt.ItemDataRole.ForegroundRole, None)
                return
            from aqt.qt import QBrush, QColor

            night = False
            try:
                from aqt.theme import theme_manager

                night = bool(theme_manager.night_mode)
            except Exception:
                night = False
            rgb = drive_store.retention_color(fraction, night)
            item.setForeground(1, QBrush(QColor(*rgb)))
        except Exception as e:
            print(f"[klausmate] drive retention color failed: {e}")

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
        # K-054: pick up any tag renamed in Anki's own sidebar since the
        # last refresh, before recomputing rows off (possibly now stale)
        # drive_store display/folder data. Never raises — see
        # tag_sync.reconcile_from_tags's own try/except.
        # reconcile_from_tags' own docstring puts the None-check on its
        # callers. It happens to short-circuit before touching col while
        # no PDF has a stored tag yet, but once they do, a closing profile
        # would log a spurious failure here every refresh.
        # Disk first, tags second: the folder is the source of truth for
        # structure, the tree follows it, and the tag reconcile below
        # then works against the freshly-synced tree (K-073).
        rescan_library_root()
        if mw.col is not None:
            tag_sync.reconcile_from_tags(mw.col)
        # THE live-update fix (K-076): everything above only moved DATA
        # (drive.json, mapping, tags) — without this repaint the open
        # window kept showing the old tree until it was reopened.
        # rebuild_tree preserves expansion/selection/scroll, so frequent
        # watcher-driven rebuilds are visually stable.
        self.rebuild_tree()
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
            op=lambda col: retention.priority_rows(col, retention._cfg()),
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

        def after_matches(matches) -> None:
            if not self._finish(seq):
                return
            tag_sync.sync_after_matches(mw, safe, matches)
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
        cfg = retention._cfg()
        current = retention.get_threshold(safe, cfg)
        dlg = QDialog(self)
        dlg.setWindowTitle("Match sensitivity")
        lay = QVBoxLayout(dlg)
        label = QLabel("", dlg)
        lay.addWidget(
            QLabel("How closely must a card relate to this PDF to count?", dlg)
        )
        slider = QSlider(Qt.Orientation.Horizontal, dlg)
        slider.setMinimum(20)
        slider.setMaximum(80)
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
        tag_sync.sync_after_threshold(mw, safe, matches, value)
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
        threshold = retention.get_threshold(safe, retention._cfg())
        nids = [int(n) for n, s in matches if float(s) >= threshold]
        if not nids:
            self.status.setText(
                "No cards above the current sensitivity — lower it in Match sensitivity…"
            )
            return
        tag = tag_sync.get_stored_tag(safe)
        if not tag:
            self.status.setText("Re-index this PDF to create its Library tag.")
            return
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(f'tag:"{tag}"')

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

    def _on_dropped_paths(self, paths: list[str]) -> None:
        """Import PDFs dropped on, or picked via Browse… in, the drop
        zone. Reaches the same import_pdf_file() every other PDF entry
        point uses (its own docstring already names "drive window" as a
        caller) so a file lands in the store exactly like it would from
        the deck screen or the editor's PDF bar — the only difference is
        what happens after: no arm(), just a tree rebuild so the new PDF
        shows up immediately. Arming is deck-screen semantics; the
        Library's job here stops at "get it into the store and visible."
        """
        from . import import_pdf_file

        imported = 0
        for path in paths:
            try:
                name = import_pdf_file(path)
            except Exception as e:
                print(f"[klausmate] library import failed for {path}: {e}")
                continue
            if name:
                imported += 1
        if imported:
            self.rebuild_tree()

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
        embed_label = "Re-index" if row.get("indexed") else "Add to index"
        menu.addAction(embed_label).triggered.connect(lambda: self._on_embed(safe))
        menu.addAction("Match sensitivity…").triggered.connect(
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
            # Disk rename follows the display rename (K-075).
            try:
                root = pdf_handler._live_library_root()
                if root and os.path.isdir(root):
                    pdf_handler.rename_mapped_file(
                        _user_files(), root, safe, name.strip()
                    )
            except Exception as e:  # noqa: BLE001
                print(f"[klausmate] disk rename failed for {safe!r}: {e}")
            self.rebuild_tree()
            tag_sync.sync_after_rename(mw, safe)

    def _move_pdf(self, safe: str, folder: str | None) -> None:
        drive_store.set_folder(_user_files(), safe, folder)
        # Anki -> disk half (K-075): the FILE follows the tree move, so
        # the disk-truth rescan agrees with it instead of snapping the
        # tree back on the next pass — which read as "my move just
        # disappeared" live.
        try:
            root = pdf_handler._live_library_root()
            if root and os.path.isdir(root):
                pdf_handler.move_mapped_file(_user_files(), root, safe, folder)
        except Exception as e:  # noqa: BLE001
            print(f"[klausmate] disk move failed for {safe!r}: {e}")
        self.rebuild_tree()
        tag_sync.sync_after_rename(mw, safe)

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
        if not ok or not name or name == leaf:
            return
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        # Same path as a drag-move (K-076): the store-only rename this
        # shipped as was reverted by the very next disk-truth rescan.
        self._move_folder(path, f"{parent}/{name}" if parent else name)

    def _move_folder(self, old: str, new: str) -> None:
        """Folder rename/reparent, disk directory included; the shared
        back half of the context-menu rename and a tree drag (K-076)."""
        root = None
        try:
            root = pdf_handler._live_library_root()
        except Exception:  # noqa: BLE001
            pass
        ok, why = apply_folder_change(_user_files(), root, old, new)
        if not ok:
            if why == "exists":
                showWarning("A folder with that name already exists there.")
            elif why == "disk":
                showWarning("Could not move the folder inside the library root.")
            else:
                showWarning("That folder name isn't valid.")
            return
        # Every PDF now under new (direct children and nested
        # descendants alike) just changed its path — collect them AFTER
        # the change so their tags follow in one batched undo entry.
        affected = [
            safe
            for safe, entry in drive_store.load(_user_files()).get("pdfs", {}).items()
            if entry.get("folder") == new
            or (entry.get("folder") or "").startswith(new + "/")
        ]
        self.rebuild_tree()
        tag_sync.sync_after_folder_rename(mw, affected)

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
        # Must run BEFORE delete_context: that call chains into
        # retention.forget_prefs, which wipes this PDF's whole prefs.json
        # entry (including the stored tag name) — after that, there is no
        # way left to know what tag to remove.
        tag_sync.sync_after_delete(mw, safe, display)
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


def refresh_open_library() -> None:
    """Re-aggregate the open Library window, if there is one.

    Called from Klausmate Preferences when the DEFAULT sensitivity is
    saved (manage_models.save_threshold): every PDF without a per-PDF
    override reads that default through retention.get_threshold, so the
    retention/cards columns an open Library is showing go stale the
    moment it changes. Without this hook the window only caught up on
    reopen — which read as the setting not working at all (Pouya, K-052:
    'currently it does not update the library sensitivity like I had
    imagined'). No-op when the Library is closed; per-PDF overrides are
    unaffected either way since they never read the default.
    """
    try:
        win = _instance
        if win is not None and win._alive() and win.isVisible():
            win._refresh_rows()
    except Exception as e:
        print(f"[klausmate] library refresh after settings change failed: {e}")


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
                "Library",
                open_drive,
                tip="Klaus PDF library",
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
