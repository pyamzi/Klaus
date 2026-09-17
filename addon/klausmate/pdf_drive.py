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

Bottom-left of that tree since K-143 sits the MAP box — Pouya's
"separate little box in the bottom left, sort of like how Obsidian does
it". The tree and the box share the pane through a vertical splitter
whose height AND collapsed state persist (``map_split``, guarded by
``_sane_map_sizes``), and the canvas itself is pdf_map's — reached
through ``pdf_map.map_canvas``, never re-implemented here, so the box
and the standalone Map window are literally the same renderer. The
box's graph is built on a QueryOp worker rather than inline: 16.9 s on
Pouya's collection, which inline would be 17 s of frozen Library on
every open. And ``PdfSidebar.on_loaded`` — the viewer's own existing
"a document went on screen" callback — points both maps at whatever
the viewer is showing.
"""

from __future__ import annotations

import os
import weakref
from typing import Any, Callable

import aqt
from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QFileSystemWatcher,
    QTimer,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
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

# No `curation` import since K-152: the only thing this window used it
# for was ensure_index, phase one of the chain that moved to index_queue.
from . import drive_store, pdf_handler, retention, tag_sync
from .slot_guard import guarded

# K-117: Retention History ships in parallel via K-118 — the menu entry
# appears once the module exists, and its absence must never break the
# Library. `except Exception`, not ImportError, on purpose: under a stub
# test environment a missing Qt name inside retention_history surfaces
# as a non-ImportError, and pdf_drive must still import.
try:
    from . import retention_history
except Exception:  # noqa: BLE001
    retention_history = None

# K-175: the Explorer delegate (icons, indent guides, the column-0
# band) and the glyph caption actions. Guarded the same way, for the
# same reason: tests/test_drive.py's fixed aqt.qt stub has no
# QToolButton or QStyledItemDelegate, and a missing module must cost
# the look, never the Library — the K-117 text buttons and plain
# cells are the fallback, built below wherever this is None.
try:
    from . import library_explorer
except Exception:  # noqa: BLE001
    library_explorer = None

DIALOG_NAME = "KlausDrive"
# K-254: the row context-menu entry that opens Browse on this PDF's
# pertinence-rejected cards (tag_sync.DOUBTFUL_TAG intersected with the
# PDF's own lecture tag). A module constant rather than an inline
# literal because Plan 2's other tasks (index_queue's Judge/Skip prompt)
# reference the same label.
DOUBTFUL_MENU_LABEL = "Doubtful cards…"
_ROLE_SAFE = Qt.ItemDataRole.UserRole
_ROLE_FOLDER = Qt.ItemDataRole.UserRole + 1
_ROLE_SORT = Qt.ItemDataRole.UserRole + 2
_UNKNOWN_SORT = -1.0

# The narrowest PDF-name column that still reads. A row nested under a
# folder starts its text 32px in (the 16px tree indent, twice), and a
# short real name — "Renal Phys.pdf" — measures 93px, so 160 leaves a
# depth-1 row ~128px of text. Long names ELIDE at this width, which is
# correct and always was; the bug this floor closes is names rendering
# as nothing at all. Paired with DriveWindow's setMinimumWidth below —
# the constant alone is inert.
_NAME_COL_FLOOR = 160

# The K-143 map box, bottom-left. Every number here is a DELIBERATE
# floor, not sizeHint fallout: pdf_map's canvas declares no size of its
# own precisely so its host decides, and "whatever the canvas asks for"
# was 480x360 — which in this pane would have shoved the left pane 60px
# wider than K-136's floor and made the box taller than half the window.
#
# _MAP_MIN_W is deliberately WELL BELOW the tree's own minimum (the live
# numeric columns + _NAME_COL_FLOOR, 420 today): the map must never be
# the widest thing in the pane, or it would silently become the binding
# constraint on the horizontal splitter and quietly move K-136's floor.
# _MAP_MIN_H is the height at which the box still reads as a map rather
# than a strip — measured offscreen against the real canvas.
_MAP_MIN_W = 240
_MAP_MIN_H = 150
_MAP_DEFAULT_H = 220


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
    on disk. A VISIBLE Library repaints via the full refresh path
    (``_refresh_rows`` rescans first, then rebuilds); otherwise a bare
    rescan keeps mapping/tree/tags in step while nothing is showing, and
    any hidden screen is marked to refresh on its next show."""
    if not _refresh_live_libraries("on watcher tick"):
        try:
            rescan_library_root()
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
    Columns 1/2/3 (Retention, Cards, Notes) carry a numeric key in
    ``_ROLE_SORT`` set by ``_apply_row`` — otherwise Qt would compare
    the display strings lexicographically ("100%" < "20%", and
    "1,000" < "900").

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
        if col in (1, 2, 3):
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


# K-132: the Library's empty state. ONE pair of strings for BOTH empty
# shapes — a wholly blank first-run Library and one that already holds
# folders but no PDFs read exactly the same.
#
# Judgement (a), deliberate: the pane's content is PDFs. A folder is
# scaffolding the user just made; it changes neither what to do next nor
# how to do it, so a second variant ("Nothing in these folders yet…")
# would be a second string to keep true and to translate for a state
# whose instruction is identical. The show condition is therefore "no
# PDFs" — never "no rows" — and the layout answers the folders case
# instead of the copy does: the block is positioned in the free space
# BELOW whatever rows exist (see _LibraryTree._reposition_empty), which
# is exactly the "vast dead area" this card was opened about.
#
# The second line names the two routes that actually EXIST today: the
# tree's own external .pdf drop (K-117 — "here" IS the tree the text is
# printed on) and the Browse… button on the drop square below. The
# card's phrasing said "or use the context menu" — there is no import
# action in either Library context menu (_build_folder_menu / the
# blank-space menu offer folder actions only), and copy must not teach
# a route the user cannot take. Length is load-bearing too: this hint
# measures 214px at 11px and has to sit on ONE clean line rather than
# wrapping and orphaning "Browse… below" onto its own (offscreen
# render, 2026-08-31). It was sized against the 300px pane of the day;
# K-135 opened the pane to 560 and _NAME_COL_FLOOR now stops it going
# back below ~432, so the block only ever has MORE room than the line
# needs — the constraint is a floor under the width, not a guess at
# it.
LIBRARY_EMPTY_TEXT = "No PDFs in your library yet"
LIBRARY_EMPTY_HINT = "Drag PDFs here, or use Browse… below"


class _LibraryEmptyState(QWidget):
    """Quiet guidance block shown over an empty Library tree.

    Judgement (b), deliberate: this is an OVERLAY parented to the
    tree's viewport, never a replacement for the tree, and
    ``WA_TransparentForMouseEvents`` is what makes that safe.
    ``QWidget::childAt()`` — the lookup Qt's drop-target search runs
    (``QWidgetWindow::findDnDTarget``) — SKIPS children carrying that
    attribute, so a drag over this block is delivered to the tree's
    viewport as if the block were not in the hierarchy at all. Dropping
    a PDF on the empty state therefore runs the unchanged
    ``_LibraryTree.dropEvent`` → ``_dest_folder_at(point)`` →
    ``DriveWindow._on_dropped_paths`` path and files the file exactly as
    a drop on the bare tree would (root over blank space, that folder
    over a folder row). Swapping the tree out for this widget — a
    QStackedWidget page, say — would have taken ``_dest_folder_at``,
    folder targeting and the whole K-117 drop path off screen and
    needed a second drop handler to drift from the first.

    The block is not inert, though: the TREE owns the affordance and
    calls :meth:`set_drag_active` from its own drag handlers, so the
    empty state lights up as a target under a .pdf drag without ever
    handling an event itself.

    Styling is ``theme.drop_zone_qss(..., idle_border=False)`` — the
    shared drop-square language, minus the idle dashed box (the pane
    already carries one of those below the tree, and the K-117
    vernacular is quiet). No colour literal appears here: if theme
    can't be imported the widget simply ships unstyled.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("klausmateLibraryEmpty")
        try:
            # WA_StyledBackground: a bare QWidget ignores stylesheet
            # background/border without it (_LibraryDropZone's note).
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
        except Exception as e:
            print(f"[klausmate] library empty-state attrs failed: {e}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(4)
        lay.addStretch(1)
        # 13px headline over an 11px hint: the Library's own body and
        # caption sizes (library_qss), both in text_muted — guidance,
        # not an announcement. No illustration, no button.
        self.title = QLabel(LIBRARY_EMPTY_TEXT, self)
        self.hint = QLabel(LIBRARY_EMPTY_HINT, self)
        for label, size in ((self.title, 13), (self.hint, 11)):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            try:
                from . import theme as _theme

                label.setStyleSheet(
                    _theme.muted_label_qss(_theme.night_mode(), size)
                )
            except Exception as e:
                print(f"[klausmate] library empty-state label theme failed: {e}")
            lay.addWidget(label)
        lay.addStretch(1)

        try:
            from . import theme as _theme

            self.setStyleSheet(
                _theme.drop_zone_qss(
                    _theme.night_mode(),
                    "klausmateLibraryEmpty",
                    idle_border=False,
                )
            )
        except Exception as e:
            print(f"[klausmate] library empty-state theme failed: {e}")

    def set_drag_active(self, active: bool) -> None:
        """Paint (or clear) the shared drag-over treatment. Driven by
        _LibraryTree, which is the widget that actually sees the drag."""
        try:
            self.setProperty("dragOver", "true" if active else "false")
            self.style().unpolish(self)
            self.style().polish(self)
        except Exception as e:
            print(f"[klausmate] library empty-state polish failed: {e}")


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
        # K-132's empty state, owned by the tree it covers: no seam to
        # the window (which tests substitute), and the drag handlers
        # below can light it up directly.
        self._empty = None
        try:
            self._empty = _LibraryEmptyState(self.viewport())
            self._empty.hide()
        except Exception as e:
            print(f"[klausmate] library empty-state setup failed: {e}")

    # ---------------------------------------------------------- K-132

    def set_empty_state(self, empty: bool) -> None:
        """Show the guidance block iff the Library holds no PDFs.
        Called from DriveWindow.rebuild_tree with ``not contexts``."""
        try:
            if self._empty is None:
                return
            self._empty.setVisible(bool(empty))
            if empty:
                self._empty.raise_()
                self._reposition_empty()
        except Exception as e:
            print(f"[klausmate] library empty-state toggle failed: {e}")

    def _rows_bottom(self) -> int:
        """Bottom edge (viewport y) of the last visible row, 0 for a
        tree with no rows at all. Walks the last top-level item's
        expanded last-child chain — O(depth), not O(rows)."""
        try:
            count = self.topLevelItemCount()
            if not count:
                return 0
            item = self.topLevelItem(count - 1)
            while item is not None and item.isExpanded() and item.childCount():
                item = item.child(item.childCount() - 1)
            if item is None:
                return 0
            return max(0, int(self.visualItemRect(item).bottom()) + 1)
        except Exception:
            return 0

    def _reposition_empty(self) -> None:
        """Park the block in the FREE area under the rows.

        With no rows the free area is the whole viewport and the block
        centres in it. With folder rows (the "folders but no PDFs"
        case) it starts below them, so quiet guidance text can never
        print over a row. The half-viewport clamp is what makes a
        scroll hook unnecessary: rows that FIT can't be scrolled, and
        rows that overflow push _rows_bottom past the half line at
        every scroll position, where the clamp pins the block anyway.
        """
        try:
            if self._empty is None:
                return
            vp = self.viewport()
            w, h = vp.width(), vp.height()
            top = min(self._rows_bottom(), max(0, h // 2))
            inset = 8
            self._empty.setGeometry(
                inset,
                top + inset,
                max(0, w - 2 * inset),
                max(0, h - top - 2 * inset),
            )
        except Exception as e:
            print(f"[klausmate] library empty-state layout failed: {e}")

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        # Unconditional: a child's isVisible() is False while its window
        # is still hidden, and DriveWindow builds the tree before show().
        super().resizeEvent(event)
        self._reposition_empty()

    def _set_empty_drag(self, active: bool) -> None:
        # isVisibleTo, not isVisible: a child reports invisible while its
        # window is merely not shown yet, and this must be true the
        # instant the block is up, not one show() later.
        try:
            if self._empty is not None and self._empty.isVisibleTo(
                self.viewport()
            ):
                self._empty.set_drag_active(active)
        except Exception as e:
            print(f"[klausmate] library empty-state drag paint failed: {e}")

    @staticmethod
    def _external_pdf_paths(md: Any) -> list[str]:
        """Local ``.pdf`` paths in a drag's mime data — non-empty exactly
        when the drag is an external file drop this tree should accept
        (K-117). Anything else (internal row drags carry no urls) comes
        back empty and falls through to Qt's InternalMove handling."""
        try:
            if md is None or not md.hasUrls():
                return []
            return [
                url.toLocalFile()
                for url in md.urls()
                if url.toLocalFile().lower().endswith(".pdf")
            ]
        except Exception:
            return []

    def _dest_folder_at(self, point: Any) -> str | None:
        """The folder a drop at *point* files into: a folder row is
        itself, a PDF row is its parent folder, empty space is the
        root. Shared by the internal row-move and the external
        file-drop paths so the two can never disagree on targeting."""
        target = self.itemAt(point)
        if target is None:
            return None
        if target.data(0, _ROLE_FOLDER):
            return target.data(0, _ROLE_FOLDER)
        if target.data(0, _ROLE_SAFE):
            parent = target.parent()
            return parent.data(0, _ROLE_FOLDER) if parent is not None else None
        return None

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        """Accept external .pdf drags (K-117) — InternalMove alone
        refuses foreign mime data, so without this override the tree
        never even lights up for a Finder drop. Everything else keeps
        Qt's internal-move handling untouched."""
        try:
            if event.source() is not self and self._external_pdf_paths(
                event.mimeData()
            ):
                # K-132: the same test that accepts the drag arms the
                # empty state's active look — one condition, so the
                # block can never advertise a drop the tree refuses.
                self._set_empty_drag(True)
                event.acceptProposedAction()
                return
        except Exception as e:
            print(f"[klausmate] library dragEnter failed: {e}")
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.source() is not self and self._external_pdf_paths(
                event.mimeData()
            ):
                event.acceptProposedAction()
                return
        except Exception as e:
            print(f"[klausmate] library dragMove failed: {e}")
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        # A drag that wanders back out must not leave the block lit
        # (K-132). Nothing else about leave behaviour changes.
        self._set_empty_drag(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Resolve what moved where and hand off to DriveWindow; the
        rebuild from drive.json IS the visual move. Every path finishes
        the drop as an accepted IgnoreAction and schedules a next-tick
        rebuild: QAbstractItemView's InternalMove cleanup deletes the
        dragged row itself after an accepted MoveAction (and macOS has
        been seen doing it even for drops we ignored), which is exactly
        how Library folders were "disappearing" until reopen (K-076).

        Two kinds of drop land here (K-117): an EXTERNAL file drag
        (Finder et al. — ``source()`` is not this tree) imports its
        .pdf payload into the folder under the cursor via the same
        ``_on_dropped_paths`` every other import surface uses; an
        internal row drag keeps its original move logic untouched."""
        try:
            try:
                external_paths = (
                    self._external_pdf_paths(event.mimeData())
                    if event.source() is not self
                    else []
                )
                if external_paths:
                    dest = self._dest_folder_at(event.position().toPoint())
                    self._window._on_dropped_paths(external_paths, dest)
                elif event.source() is self:
                    dragged = self.currentItem()
                    safe = dragged.data(0, _ROLE_SAFE) if dragged is not None else None
                    folder_path = (
                        dragged.data(0, _ROLE_FOLDER) if dragged is not None else None
                    )
                    dest = self._dest_folder_at(event.position().toPoint())

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
                # The drag is over however this ended (K-132).
                self._set_empty_drag(False)
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
    different hosts. pdf_drop._drop_square_html() renders one as HTML
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

    All three squares are now the same single-state invitation: K-151
    retired the deck square's armed/× half, which this one never had
    (arming was deck-screen semantics — the Library's job here is only
    "get the file into the store and show it in the tree").

    Style values (idle border/radius, font-size, Browse-button chrome)
    come from theme.drop_zone_qss — the shared drop-square language.
    pdf_drop._drop_square_html renders the same theme tokens as
    inline HTML for the deck screens, so the surfaces cannot drift.
    (This discharges the old "three duplicated copies" debt.)
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
        try:
            from . import theme as _theme

            self.setStyleSheet(
                _theme.drop_zone_qss(
                    _theme.night_mode(), "klausmateLibraryDropZone"
                )
            )
        except Exception:
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

        self._label = label = QLabel(self._IDLE_TEXT, self)
        label.setWordWrap(True)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        try:
            from . import theme as _theme

            label.setStyleSheet(_theme.muted_label_qss(_theme.night_mode(), 13))
        except Exception:
            label.setStyleSheet(
                "font-size: 13px; color: rgba(120, 120, 120, 0.95);"
            )
        lay.addWidget(label, 1)

        # Chrome comes from the drop-zone QSS on the parent (the shared
        # drop-square language in theme.drop_zone_qss) — no inline style.
        browse_btn = QPushButton("Browse…", self)
        browse_btn.setFlat(True)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._browse)
        lay.addWidget(browse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def apply_theme(self) -> None:
        """Re-run construction's two theme calls against the CURRENT
        theme. Only the refresh path uses this (see DriveWindow._apply_
        theme) — construction applies both itself, with its own
        exception-specific fallbacks, which this does not repeat."""
        from . import theme as _theme

        night = _theme.night_mode()
        self.setStyleSheet(_theme.drop_zone_qss(night, "klausmateLibraryDropZone"))
        self._label.setStyleSheet(_theme.muted_label_qss(night, 13))

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


# What the status line says when there is no viewer to open a PDF in. A
# LINE, not a modal: this is reached from a double-click slot, and
# aqt.utils.showWarning execs internally (K-114/K-125) — a modal opened
# from inside a slot re-enters the event loop under the click that
# triggered it.
NO_VIEWER_TEXT = "The PDF viewer could not start — see the log for why."


def _viewer_needs_rebuild(sidebar: Any) -> bool:
    """True when ``sidebar`` is a husk that can no longer show a PDF.

    Two ways that happens. The C++ side went away (any touch raises
    RuntimeError), or K-095 cleanup ran: ``pdf_viewer.cleanup_all_sidebars``
    sweeps EVERY live sidebar on profile switch and on quit, and the
    pdf.js renderer's cleanup drops its AnkiWebView (``_web = None``)
    because a webview must be unregistered from Anki's global hooks
    while its C++ object is still alive.

    The standalone window never noticed either case — it is destroyed and
    rebuilt around them. The EMBEDDED screen is not: ``library_tab`` keeps
    its tab in module state for the whole session and only hides it, so
    without this check the Library would come back from a profile switch
    unable to open anything, with no error to explain it. The native
    renderer has no cleanup at all (QPdfView holds nothing to release) and
    is never dead.
    """
    try:
        viewer = getattr(sidebar, "_viewer", None)
        if viewer is None:
            return False  # the no-viewer fallback label; nothing to revive
        if not hasattr(viewer, "cleanup"):
            return False  # QPdfView path
        return getattr(viewer, "_web", False) is None
    except RuntimeError:
        return True  # C++ side deleted
    except Exception:
        return False


# Every embedded Library alive in this session. A WeakSet because
# library_tab owns the tab's lifetime, not this module — see
# _release_embedded_viewers for what it is for. DriveWindow must stay
# HASHABLE by identity: an __eq__ without __hash__ makes WeakSet.add raise
# TypeError, and the guarded add in __init__ would swallow that into a log
# line, silently dropping the screen from refresh AND viewer release.
_embedded_windows: "weakref.WeakSet[DriveWindow]" = weakref.WeakSet()


class DriveWindow(QWidget):
    """Standalone library window. Managed by aqt.dialogs."""

    # Required by the dialog manager for profile-switch teardown.
    silentlyClose = True

    def __init__(self, embedded: bool = False) -> None:
        super().__init__()
        # Embedded = mounted as a screen inside Anki's main window rather
        # than opened as its own. Read during construction, so it is set
        # first.
        self.embedded = bool(embedded)
        self.setWindowTitle("Library — KlausMate")
        self.setMinimumSize(720 if not embedded else 320, 420)
        # VS Code Explorer language (K-117): window on bg, the tree a
        # flat full-bleed panel on surface with compact rows, an
        # uppercase section caption with quiet flat actions beside it.
        try:
            from . import theme as _theme

            self.setObjectName("KlausLibraryWindow")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(_theme.library_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] library theme failed: {exc}")

        # `seq` is the RETENTION-refresh staleness token only. The
        # indexing run's busy flag and cancel event left with the chain
        # in K-152 — a job outlives this window now, so a per-window
        # token could only ever describe half of it.
        self.seq = 0
        self.card_r: dict = {}
        # Beside card_r, and for the same reason (K-118): priority_rows
        # hands the nid -> [queue] map back so a threshold change can
        # re-aggregate the Cards/Notes counts with no collection access.
        # Match Sensitivity's OK is the one caller (PR #4 F5).
        self.card_queues: dict = {}
        self.matches: dict = {}
        self.rows: dict[str, dict] = {}
        # ---- the K-143 map dock's state, before anything builds it ----
        # The canvas exists only after its (slow) graph lands, so every
        # reader of it is written for None; _map_started makes the build
        # once-per-window; _map_collapsed is the tracked intent that
        # _ensure_map consults instead of trusting pre-layout geometry;
        # _map_last remembers what the viewer is showing so a canvas
        # arriving late still opens on the right node.
        self.map_canvas = None
        self.map_box = None
        self._map_started = False
        self._map_collapsed = False
        self._map_last: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        outer.addWidget(self.splitter, 1)

        # ---- left: section header + tree + status ----
        left = QWidget(self.splitter)
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # VS Code sidebar section header: uppercase caption left, the
        # section's quiet actions right (the old bottom button row moved
        # up here). Uppercase in the TEXT — Qt QSS has no text-transform.
        header_row = QHBoxLayout()
        header_row.setSpacing(2)
        section = QLabel("LIBRARY", left)
        section.setObjectName("LibrarySectionHeader")
        header_row.addWidget(section)
        header_row.addStretch(1)
        # K-175: VS Code's section actions are 16px glyphs in 22px hit
        # boxes with tooltips, not words. Each is a GlyphButton when the
        # Explorer module loaded and the K-117 text button when it did
        # not; both expose the same clicked/setEnabled/setToolTip.
        new_folder = self._glyph_action("new-folder", "New Folder…", left)
        if new_folder is None:
            new_folder = QPushButton("New Folder…", left)
        new_folder.clicked.connect(lambda: self._new_folder())
        header_row.addWidget(new_folder)
        refresh = self._glyph_action("refresh", "Refresh", left)
        if refresh is None:
            refresh = QPushButton("Refresh", left)
        refresh.clicked.connect(self._refresh_rows)
        header_row.addWidget(refresh)
        map_tip = (
            "Embedding map — every indexed note as a point, "
            "your PDFs where their matches cluster"
        )
        map_btn = self._glyph_action("map", map_tip, left)
        if map_btn is None:
            map_btn = QPushButton("Map", left)
            map_btn.setToolTip(map_tip)
        map_btn.clicked.connect(self._open_map)
        header_row.addWidget(map_btn)
        assistant_tip = "Klaus Assistant (Ctrl+Shift+K)"
        # No "assistant" entry in library_explorer.KINDS today (that module
        # belongs to another plan) — _glyph_action would only ever log a
        # failure and fall back, so the check below skips straight to the
        # K-117 text button rather than calling a path known to always
        # fail. Written as a live capability check, not a version note, so
        # this picks up a real glyph automatically the day one lands there.
        assistant_btn = None
        if library_explorer is not None and "assistant" in library_explorer.KINDS:
            assistant_btn = self._glyph_action("assistant", assistant_tip, left)
        if assistant_btn is None:
            assistant_btn = QPushButton("Assistant", left)
            assistant_btn.setToolTip(assistant_tip)
        assistant_btn.clicked.connect(self._open_assistant)
        header_row.addWidget(assistant_btn)
        lay.addLayout(header_row)

        self.tree = _LibraryTree(self, left)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["PDF", "Retention", "Cards", "Notes"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        try:
            head = self.tree.header()
            head.setStretchLastSection(False)
            # The PDF column stretches to swallow whatever width the
            # numeric columns leave (K-127): a fixed 240px ended the
            # table mid-pane, with the header hairline running on into
            # a dead right gutter. The numeric columns are Fixed so
            # that stretch is the only elastic part of the layout.
            head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for col in (1, 2, 3):
                head.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(1, 84)
            # 88, not a slimmer numeric width: the Cards cell doubles as
            # the status cell ("suspended" / "not embedded"), and 64px
            # elided those to "suspe…" (offscreen render, 2026-08-31).
            self.tree.setColumnWidth(2, 88)
            self.tree.setColumnWidth(3, 88)
            # Declare the width this tree actually needs. Left alone it
            # reports an 88px minimum while its own Fixed columns
            # consume 260 (both measured offscreen) — so QSplitter hands
            # it 288px in good faith and the Stretch name column
            # collapses to 28, rendering every row nameless. K-135
            # widened the DEFAULT, which moves that cliff edge but does
            # not remove it: _sane_splitter_sizes accepts any pane at or
            # above _MIN_PANE (120), so ONE narrow drag persists and the
            # Library opens nameless on every launch after, with nothing
            # on screen to suggest dragging wider is the cure. With a
            # real minimum declared, Qt clamps both a narrow drag and a
            # hostile restored value back up. Summed from the live
            # column widths, never a literal 260: K-127 and K-130 each
            # widened these columns, and a hardcoded total here would be
            # a second number to keep in step.
            self.tree.setMinimumWidth(
                sum(self.tree.columnWidth(c) for c in (1, 2, 3))
                + _NAME_COL_FLOOR
            )
            head.setSectionsClickable(True)
            # VS Code Explorer density: shallow indent, uniform 22px
            # rows (the QSS min-height; uniformity also speeds layout).
            self.tree.setIndentation(16)
            self.tree.setUniformRowHeights(True)
            # Numeric columns read right-aligned, header cells included
            # (per-item alignment happens in _apply_row).
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            header_item = self.tree.headerItem()
            for col in (1, 2, 3):
                header_item.setTextAlignment(col, align)
            self.tree.setSortingEnabled(True)
            # Worst-first by default: the Library's job (PRODUCT.md) is
            # ranking lecture material by how poorly it is retained —
            # that ranking must be the view you open, not one hiding
            # behind a header click. Column 1 = Retention, ascending =
            # lowest retention (study this first) on top.
            self.tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        except Exception:
            pass
        # K-175: the Explorer delegate — icons, indent guides and the
        # full-cell band in column 0; columns 1-3 stay the style's.
        # Folder-ness is injected because the role is this module's,
        # and library_explorer must not import its own importer. The
        # main sash takes VS Code's width here (the hairline itself is
        # in theme.library_qss); the map dock's keeps its 6px, which is
        # a tooltip target when the box is dragged shut.
        if library_explorer is not None:
            try:
                from . import theme as _theme

                library_explorer.install(
                    self.tree,
                    _theme.night_mode(),
                    lambda idx: bool(idx.data(_ROLE_FOLDER)),
                )
                self.splitter.setHandleWidth(library_explorer.SASH_W)
            except Exception as e:
                print(f"[klausmate] explorer delegate install failed: {e}")
        # The tree and the K-143 map box share the pane vertically, in
        # their own splitter — Obsidian's shape, which is what Pouya
        # asked for ("a separate little box in the bottom left").
        # Everything under it (status, Cancel, drop zone) is thin
        # chrome that stays put; only these two negotiate for height.
        self.left_split = QSplitter(Qt.Orientation.Vertical, left)
        self.left_split.addWidget(self.tree)
        self.map_box = self._build_map_box(self.left_split)
        self.left_split.addWidget(self.map_box)
        try:
            # The tree can never be collapsed away — it IS the Library.
            # The map can: collapsed is a state Obsidian offers and the
            # one _sane_map_sizes deliberately admits (a 0 that means
            # "shut", not a 0 that means "never laid out").
            self.left_split.setCollapsible(0, False)
            self.left_split.setCollapsible(1, True)
            self.left_split.setStretchFactor(0, 1)
            self.left_split.setStretchFactor(1, 0)
            # A collapsed box leaves ONLY this handle behind, so it has
            # to be a real target and say what it is (offscreen render:
            # at the stock width it is a hairline in the same token as
            # the chrome around it, and a box dragged shut looks gone
            # rather than closed). The standalone Map button is the
            # other way back, so nobody is ever stranded.
            self.left_split.setHandleWidth(6)
            handle = self.left_split.handle(1)
            if handle is not None:
                handle.setToolTip("Drag to resize the map — or shut it")
            # Dragging the box open is what starts its build, so the
            # collapsed box costs nothing until it is wanted.
            self.left_split.splitterMoved.connect(self._on_map_split_moved)
        except Exception as e:
            print(f"[klausmate] map splitter setup failed: {e}")
        lay.addWidget(self.left_split, 1)

        self.status = QLabel("", left)
        self.status.setWordWrap(True)
        try:
            from . import theme as _theme

            self.status.setStyleSheet(
                _theme.muted_label_qss(_theme.night_mode(), 11)
            )
        except Exception:
            self.status.setStyleSheet("font-size: 11px; opacity: 0.8;")
        lay.addWidget(self.status)

        self.cancel_btn = QPushButton("Cancel", left)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setVisible(False)
        lay.addWidget(self.cancel_btn)

        self.drop_zone = _LibraryDropZone(self._on_dropped_paths, left)
        lay.addWidget(self.drop_zone)

        # ---- right: the viewer ----
        # Built by _ensure_sidebar, which is the ONLY place one is
        # constructed and the only place this attribute is read. The
        # embedded screen does not build it here: see showEvent.
        self.sidebar = None
        self._sidebar_arming = 0
        # Set by _release_embedded_viewers on profile close: the tab is
        # never shut down (unmount only hides), so the next showEvent
        # must refresh or it shows the PREVIOUS collection's rows.
        self._refresh_pending = False
        self.splitter.addWidget(left)
        if not self.embedded:
            self._ensure_sidebar()

        self._restore_geometry()
        self.rebuild_tree()
        self._refresh_rows()

        # K-152: the Library is a VIEW of the shared index runner, not
        # its owner. Seed from the live snapshot immediately — a job
        # started from the deck screen may already be running, and a
        # window that opened blank while indexing was in flight would be
        # lying about the state of the very thing it manages.
        try:
            from . import index_queue

            index_queue.add_listener(self._on_index_state)
            self._on_index_state(index_queue.state())
        except Exception as e:
            print(f"[klausmate] index status wiring failed: {e}")

        if self.embedded:
            # NOT shown here. An embedded screen is built parentless and
            # only then added to mw.mainLayout by library_tab, which
            # shows it itself — self.show() would make this a real
            # top-level window for those few milliseconds (a visible
            # flash that also steals focus), and every widget in it
            # would then be reparented across a native-window boundary.
            # That crossing is exactly what turned single_window.py's
            # panes black (K-090: "a view reparented BEFORE first show
            # can miss its visibility transition and never attach a
            # surface"), and the viewer is the one widget here that
            # cannot survive it.
            try:
                _embedded_windows.add(self)
            except Exception as e:
                print(f"[klausmate] embedded registry failed: {e}")
        else:
            try:
                self.show()
                self.raise_()
                self.activateWindow()
            except Exception as e:
                print(f"[klausmate] drive show failed: {e}")

        # After show(), so the box's real height decides whether the
        # (expensive) graph build is worth starting at all.
        self._ensure_map()

    # --------------------------------------------------------- viewer

    # Ticks to wait for library_tab to finish mounting before giving up
    # and building the viewer wherever we are. Only reached if the mount
    # order ever changes (today: addWidget, then show).
    _ARM_RETRIES = 10

    def _ensure_sidebar(self):
        """Return this Library's live PDF viewer, building it if needed.

        THE choke point: the only place a ``PdfSidebar`` is constructed
        here, and the only place ``self.sidebar`` is read. Everything
        else takes what this returns — or the attribute plus an ``is
        None`` test — because the answer is legitimately None (a viewer
        that failed to import, or one not built yet).

        K-173: fc8591c gave the embedded screen ``self.sidebar = None``
        and guarded construction and teardown, but not the OPEN path, so
        every double-click raised AttributeError on None and the
        handler's except turned it into "Could not open that PDF."
        """
        self._sidebar_arming = 0
        sidebar = self.sidebar
        if sidebar is not None and not _viewer_needs_rebuild(sidebar):
            return sidebar
        if sidebar is not None:
            # A husk (see _viewer_needs_rebuild). Drop it before building
            # its replacement, or the splitter keeps a dead pane.
            self.sidebar = None
            try:
                sidebar.setParent(None)
                sidebar.deleteLater()
            except Exception as e:
                print(f"[klausmate] stale viewer drop failed: {e}")
        try:
            from .pdf_viewer import PdfSidebar

            sidebar = PdfSidebar(None, parent=self.splitter)
        except Exception as e:
            print(f"[klausmate] library viewer unavailable: {e}")
            return None
        self.sidebar = sidebar
        try:
            # THE follow-the-viewer seam (K-143/K-137). PdfSidebar
            # already owns one: on_loaded fires from _notify_loaded on
            # EVERY path that puts a document on screen, whichever call
            # site triggered it — which is exactly "the Library knows
            # which PDF is showing", and why no new signal was invented
            # for this. The slot is free here: the only other assignment
            # in the addon is PdfDock's, on its OWN sidebar.
            sidebar.on_loaded = self._on_viewer_loaded
            # After the tree, in both modes (Task 11 retired the third,
            # assistant pane) — the window's two-pane shape, which is
            # also what keeps ONE stored splitter layout meaningful for
            # both the standalone window and the embedded screen.
            self.splitter.insertWidget(1, sidebar)
            self.splitter.setStretchFactor(self.splitter.indexOf(sidebar), 1)
            self._apply_splitter_sizes()
        except Exception as e:
            print(f"[klausmate] library viewer host failed: {e}")
        return sidebar

    def showEvent(self, evt) -> None:  # noqa: N802 — Qt naming
        """Build the embedded screen's viewer once it is really on screen.

        A Qt event handler, so it may not raise: an unhandled exception
        crossing back into C++ is ``qFatal()`` in a bare interpreter (exit
        134) and Anki's modal error dialog under aqt's excepthook (K-183).

        WHY NOT IN ``__init__``: an embedded DriveWindow is constructed
        PARENTLESS and only then added to ``mw.mainLayout``. A viewer
        built in the constructor would therefore be created inside a
        throwaway top-level window and reparented into the main window
        before its first show — the precise shape that turned
        single_window.py's panes black (K-090) and outlived five rework
        rounds before that module was deleted. Built here instead, one
        tick after the screen is shown in its final home, the webview's
        ``window()`` is Anki's main window from birth and never changes.
        That — not "dock versus layout" — is the property lecture_view's
        shipped in-main-window PdfSidebar has too: its dock is parented
        to ``mw`` from construction.
        """
        try:
            super().showEvent(evt)
        except Exception as e:
            print(f"[klausmate] drive showEvent failed: {e}")
        # Every mount-time duty runs one tick later, in ONE slot, in a
        # stated order — see _on_shown. Three separate timers here once
        # made that order an accident of registration.
        try:
            QTimer.singleShot(0, self._on_shown)
        except Exception as e:
            print(f"[klausmate] settle scheduling failed: {e}")

    def _apply_theme(self) -> None:
        """Re-paint every widget this window styled once at construction,
        against whatever theme.night_mode() says NOW.

        Construction applies each of these itself, in the order it needs
        them built — this exists only for the refresh path (see module
        function _restyle_live_libraries): the embedded screen is built
        ONCE per session and then only shown/hidden, so a night-mode flip
        made while Anki runs never reached it before this existed, and
        the tab stayed on whichever theme was active at first mount.
        Separate try/except per widget: a torn-down child between the
        flip and this deferred tick must not cost the others theirs.
        """
        from . import theme as _theme

        night = _theme.night_mode()
        try:
            self.setStyleSheet(_theme.library_qss(night))
        except Exception as e:
            print(f"[klausmate] library theme refresh failed: {e}")
        try:
            self.status.setStyleSheet(_theme.muted_label_qss(night, 11))
        except Exception as e:
            print(f"[klausmate] library status theme refresh failed: {e}")
        try:
            self.map_status.setStyleSheet(_theme.muted_label_qss(night, 12))
        except Exception as e:
            print(f"[klausmate] map status theme refresh failed: {e}")
        try:
            self.drop_zone.apply_theme()
        except Exception as e:
            print(f"[klausmate] drop zone theme refresh failed: {e}")

    @guarded
    def _on_shown(self) -> None:
        """The screen has been shown and has settled in its final window.

        Order is the point of having one method: build the viewer (only
        the embedded screen, only once — the arm has its own 50ms retry
        ladder for a mount that has not landed yet), then refresh rows
        marked stale by a collection close, then the map, then FOCUS LAST
        so nothing built after it can take it. Every show: returning to
        the screen puts the arrow keys back on the list (K-179 — a
        setFocus() made before library_tab's reparent did not survive the
        move, and the first widget in the tab chain, an icon button, wore
        the ring instead).
        """
        if not self._alive() or not self.isVisible():
            return
        if self.embedded and self.sidebar is None and not self._sidebar_arming:
            self._sidebar_arming = 1
            self._arm_sidebar()
        if self._refresh_pending:
            self._refresh_pending = False
            self._refresh_rows()
        self._ensure_map()
        self.tree.setFocus()

    @guarded
    def _arm_sidebar(self) -> None:
        """Build the embedded screen's viewer once the mount has landed
        (called from _on_shown; reschedules itself while parentless)."""
        if not self._alive() or not self.embedded:
            return
        if (self.window() is self
                and self._sidebar_arming < self._ARM_RETRIES):
            # Still parentless: the mount has not landed yet. Wait
            # rather than build a webview in a window that is about
            # to be thrown away (see showEvent).
            self._sidebar_arming += 1
            QTimer.singleShot(50, self._arm_sidebar)
            return
        self._ensure_sidebar()

    def collection_will_close(self) -> None:
        """Everything this screen computed against the closing collection
        (profile switch, quit) — owned HERE, not enumerated by the hook.

        The viewer is released K-095-correctly. The retention rows and the
        map were built against a collection that is going away: ``seq`` is
        bumped so an in-flight priority_rows result cannot land on the new
        profile, ``_refresh_pending`` makes the next _on_shown refresh the
        rows, and the map canvas is dropped so _ensure_map rebuilds it
        (its layout digest changes with the collection). Lazy on purpose:
        a screen nobody looks at again pays nothing, and the map rebuild
        is a worker job of tens of seconds on a cold cache.
        """
        try:
            self.release_viewer()
        except Exception as e:
            print(f"[klausmate] embedded viewer release failed: {e}")
        self.seq += 1
        self._refresh_pending = True
        try:
            canvas, self.map_canvas = self.map_canvas, None
            self._map_started = False
            if canvas is not None:
                canvas.setParent(None)
                canvas.deleteLater()
            status = getattr(self, "map_status", None)
            if status is not None:
                status.setText("")
                status.setVisible(True)
        except Exception as e:
            print(f"[klausmate] map reset on collection close failed: {e}")

    def release_viewer(self) -> None:
        """Hand the viewer back, K-095-correctly, without tearing down
        the rest of the Library.

        The webview must be unregistered from Anki's global hooks while
        its C++ object is alive (see ``PdfSidebar.cleanup``) or the next
        theme change crashes inside Anki's own hook iteration on a
        dangling AnkiWebView. The standalone window does this in
        ``shutdown``; the embedded screen has no close to hang it on —
        ``library_tab.unmount`` only HIDES the tab and keeps it for the
        session — so ``_release_embedded_viewers`` calls this on profile
        switch and on quit instead, and ``_ensure_sidebar`` builds a
        fresh viewer the next time one is wanted.
        """
        sidebar = self.sidebar
        self.sidebar = None
        if sidebar is None:
            return
        try:
            sidebar.clear()
            sidebar.cleanup()
        except Exception as e:
            print(f"[klausmate] viewer release failed: {e}")
        try:
            sidebar.setParent(None)
            sidebar.deleteLater()
        except Exception as e:
            print(f"[klausmate] viewer disposal failed: {e}")

    # -------------------------------------------------------- geometry

    _MIN_PANE = 120

    def _sane_splitter_sizes(self, sizes: object) -> list[int] | None:
        """Reject degenerate splitter sizes (e.g. saved from a never-shown
        window, where sizes() returns something like [46, 46]).

        Accepts a pane count matching the splitter rather than a hardcoded
        two, so a stale layout saved while the (since-Task-11-retired)
        third, assistant pane existed is rejected as the wrong shape —
        exactly like any other degenerate value — rather than partially
        applied to a splitter that no longer has that pane; the default
        two-pane layout takes over instead of guessing.
        """
        want = self.splitter.count() or 2
        if not isinstance(sizes, list) or not sizes:
            return None
        try:
            ints = [int(s) for s in sizes]
        except (TypeError, ValueError):
            return None
        if len(ints) != want:
            return None
        for size in ints:
            if size < self._MIN_PANE:
                return None
        return ints

    def _sane_map_sizes(self, sizes: object) -> list[int] | None:
        """The same guard for the left pane's VERTICAL splitter (K-143).

        Mirrors ``_sane_splitter_sizes`` — a two-int list or nothing,
        the tree half held above the same 120px "that isn't a pane"
        floor — with ONE deliberate difference: the map half may be
        exactly 0. Zero here is a real state, the box collapsed shut,
        and it is the whole reason the collapsed state persists without
        a second config key. Any OTHER value below ``_MAP_MIN_H`` is
        the degenerate kind (a never-laid-out window's sizes()) and is
        rejected exactly as the horizontal guard rejects them, so a
        window that was built but never shown cannot poison the next
        restore.
        """
        if not isinstance(sizes, list) or len(sizes) != 2:
            return None
        try:
            ints = [int(s) for s in sizes]
        except (TypeError, ValueError):
            return None
        if ints[0] < self._MIN_PANE:
            return None
        if ints[1] != 0 and ints[1] < _MAP_MIN_H:
            return None
        return ints

    def _apply_splitter_sizes(self) -> None:
        """Size the horizontal splitter from the stored layout, for
        however many panes exist RIGHT NOW.

        Its own method because the viewer pane can arrive after the
        window is built (K-173: the embedded screen builds it on first
        show), and a pane inserted into an already-sized splitter takes
        whatever width Qt's redistribution gives it rather than the one
        the user chose.
        """
        try:
            state = drive_store.get_window_state(_user_files())
        except Exception as e:
            print(f"[klausmate] splitter state read failed: {e}")
            state = {}
        try:
            sane = self._sane_splitter_sizes(state.get("splitter"))
            # [560, 480], not [300, 740]: the numeric columns are Fixed
            # (K-127) at 84+88+88 = 260px and the tree indents 16, so a
            # 300px pane left 24px for the PDF NAME — every row opened
            # nameless, the header truncated to "PL" (offscreen render,
            # K-132). Fixed numerics do not yield; the pane has to be
            # wide enough to hold them plus a readable name. 560 leaves
            # 284. tests/test_drive.py pins that arithmetic so a future
            # width change cannot silently re-break it.
            default = [560, 480]
            self.splitter.setSizes(sane if sane is not None else default)
        except Exception as e:
            print(f"[klausmate] splitter sizing failed: {e}")

    def _restore_geometry(self) -> None:
        try:
            state = drive_store.get_window_state(_user_files())
            if self.embedded:
                # A screen has no geometry of its own — it fills whatever
                # mw.mainLayout gives it. Applying a stored WINDOW rect
                # here would move a child widget around inside the main
                # window for one layout pass and prove nothing.
                pass
            elif state.get("w") and state.get("h"):
                self.resize(int(state["w"]), int(state["h"]))
                if state.get("x") is not None and state.get("y") is not None:
                    self.move(int(state["x"]), int(state["y"]))
            else:
                self.resize(1040, 680)
            self._apply_splitter_sizes()
            # The map box's height + collapsed state, same shape and
            # same defensiveness. The default pair SUMS to roughly the
            # left pane's height at the default 1040x680 window (the
            # chrome under the splitter costs ~100px), because setSizes
            # distributes proportionally when the total doesn't match —
            # so a pair summing to 560 lands the box near its intended
            # _MAP_DEFAULT_H rather than somewhere arbitrary.
            sane_map = self._sane_map_sizes(state.get("map_split"))
            if sane_map is None:
                sane_map = [560 - _MAP_DEFAULT_H, _MAP_DEFAULT_H]
            self.left_split.setSizes(sane_map)
            # Tracked, not measured: _ensure_map runs before Qt has
            # necessarily laid the splitter out, and sizes() before the
            # first layout pass is exactly the bogus value the guards
            # above exist to reject. _on_map_split_moved re-reads the
            # real geometry once the user touches the handle.
            self._map_collapsed = sane_map[1] == 0
        except Exception as e:
            print(f"[klausmate] drive geometry restore failed: {e}")
            if not self.embedded:
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
            if self.embedded:
                # A screen's rect is the main window's, not a Library
                # window's — saving it would poison the standalone
                # window's next restore, and save_window_state REPLACES
                # the stored dict rather than merging, so what is
                # already there has to be carried through by hand.
                state = dict(drive_store.get_window_state(_user_files()))
            else:
                geo = self.geometry()
                state = {
                    "x": geo.x(),
                    "y": geo.y(),
                    "w": geo.width(),
                    "h": geo.height(),
                }
            if self._sane_splitter_sizes(sizes) is not None:
                state["splitter"] = sizes
            map_sizes = list(self.left_split.sizes())
            if self._sane_map_sizes(map_sizes) is not None:
                state["map_split"] = map_sizes
            drive_store.save_window_state(_user_files(), state)
        except Exception as e:
            print(f"[klausmate] drive geometry save failed: {e}")

    # ---------------------------------------------------- caption actions

    def _glyph_action(self, kind: str, tooltip: str, parent):
        """A K-175 glyph action for a section caption row, or None when
        the Explorer module is unavailable — the caller then builds the
        K-117 text button in its place. Never raises: a glyph that
        fails to construct costs an icon, not the Library."""
        if library_explorer is None:
            return None
        try:
            from . import theme as _theme

            return library_explorer.GlyphButton(
                kind, tooltip, _theme.night_mode(), parent
            )
        except Exception as e:
            print(f"[klausmate] glyph action {kind} failed: {e}")
            return None

    # --------------------------------------------------------- map dock

    def _build_map_box(self, parent):
        """The bottom-left map box: a MAP section over the canvas slot.

        Section header + one body, the same two-part shape as the
        LIBRARY section above it (uppercase caption left, quiet flat
        action right) — so the pane reads as two stacked VS Code
        sections, which is also exactly what Obsidian's sidebar is. The
        canvas is NOT built here: it costs a 17 s graph build (see
        _ensure_map), so the body starts as a muted line and the canvas
        is swapped in underneath it when the worker lands.
        """
        box = QWidget(parent)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(2)
        caption = QLabel("MAP", box)
        caption.setObjectName("LibrarySectionHeader")
        row.addWidget(caption)
        row.addStretch(1)
        fit_tip = "Fit — reset the map's zoom to show everything"
        self.map_fit_btn = self._glyph_action("fit", fit_tip, box)
        if self.map_fit_btn is None:
            self.map_fit_btn = QPushButton("Fit", box)
            self.map_fit_btn.setToolTip(fit_tip)
        self.map_fit_btn.setEnabled(False)
        self.map_fit_btn.clicked.connect(self._map_fit)
        row.addWidget(self.map_fit_btn)
        lay.addLayout(row)

        self.map_status = QLabel("", box)
        self.map_status.setWordWrap(True)
        try:
            from . import theme as _theme

            self.map_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.map_status.setStyleSheet(
                _theme.muted_label_qss(_theme.night_mode(), 12)
            )
        except Exception:
            pass
        lay.addWidget(self.map_status, 1)

        try:
            box.setMinimumHeight(_MAP_MIN_H)
        except Exception:
            pass
        return box

    def _map_fit(self) -> None:
        cv = self.map_canvas
        if cv is None:
            return
        try:
            cv.fit()
        except Exception as e:
            print(f"[klausmate] map fit failed: {e}")

    def _on_map_split_moved(self, *_args) -> None:
        """Handle drag: re-read the collapsed state from real geometry
        (unlike restore time, the splitter has been laid out by now) and
        start the build if the box was just dragged open."""
        try:
            self._map_collapsed = list(self.left_split.sizes())[1] <= 0
        except Exception:
            return
        self._ensure_map()

    def _ensure_map(self) -> None:
        """Build the dock's graph ONCE, off the main thread, and only
        for a box the user can actually see.

        ``pdf_map.graph_data`` is 16.9 s on Pouya's 28,668-note
        collection (measured K-143 — the PCA over the whole card index).
        Calling it inline would freeze the Library for that long on
        EVERY open, so it runs on a QueryOp worker: _refresh_rows'
        contract exactly, parented to mw rather than self (a QueryOp
        whose parent dies takes its callback with it) with _alive()
        guarding the callback instead. A collapsed box pays nothing at
        all, and dragging one open starts the build then.

        Once per window, whatever the outcome: a retry on every handle
        drag would be a 17 s CPU burn per twitch.
        """
        if self._map_started or self._map_collapsed:
            return
        if mw is None or mw.col is None:
            return
        try:
            from . import pdf_map
        except Exception as e:
            print(f"[klausmate] map unavailable: {e}")
            return
        self._map_started = True
        self.map_status.setText(pdf_map.BUILDING_TEXT)

        def done(graph: dict) -> None:
            if not self._alive():
                return
            self._install_map(graph)

        def fail(exc: Exception) -> None:
            if not self._alive():
                return
            print(f"[klausmate] map graph build failed: {exc}")
            self.map_status.setText(pdf_map.BUILD_FAIL_TEXT)

        op = QueryOp(parent=mw, op=lambda _col: pdf_map.graph_data(), success=done)
        op.failure(fail)
        op.run_in_background()

    def _install_map(self, graph: dict) -> None:
        """Put the finished graph on screen — main thread only.

        An empty graph gets pdf_map's own empty-state line rather than a
        blank card: same policy as the standalone window, decided in one
        place each so neither surface invents its own wording.
        """
        try:
            from . import pdf_map
        except Exception as e:
            print(f"[klausmate] map import failed: {e}")
            return
        try:
            if not (graph or {}).get("pdfs"):
                self.map_status.setText(pdf_map.EMPTY_TEXT)
                return
            canvas = pdf_map.map_canvas(self.map_box, graph)
            if canvas is None:
                self.map_status.setText(pdf_map.CANVAS_FAIL_TEXT)
                return
            # The canvas declares no size of its own (K-143) — this is
            # where the dock's deliberate floor is applied.
            canvas.setMinimumSize(_MAP_MIN_W, _MAP_MIN_H)
            self.map_box.layout().addWidget(canvas, 1)
            self.map_canvas = canvas
            self.map_status.setVisible(False)
            self.map_fit_btn.setEnabled(True)
            # The build takes seconds; the reader may well have opened a
            # PDF while it ran, and that load's on_loaded fired into a
            # canvas that did not exist yet.
            if self._map_last:
                self._on_viewer_loaded(self._map_last)
        except Exception as e:
            print(f"[klausmate] map install failed: {e}")

    def _on_viewer_loaded(self, safe) -> None:
        """The Library's viewer just put ``safe`` on screen (or cleared,
        for None) — point every open map at it.

        Wired to ``PdfSidebar.on_loaded``, which fires from the viewer's
        own _notify_loaded on every load path there is, so this covers
        the tree double-click and anything later that loads a PDF
        without going through it.

        Both maps follow: the dock's canvas directly, and the standalone
        window through pdf_map.select_pdf — the seam K-138 built and
        deliberately left unwired for this card. Its contract already
        covers everything awkward here (unknown or None CLEARS, no
        window is a silent no-op, an already-visible node is not chased)
        and canvas.select IS that contract, so nothing is re-derived.
        """
        self._map_last = str(safe) if safe else None
        cv = self.map_canvas
        if cv is not None:
            try:
                cv.select(safe)
            except Exception as e:
                print(f"[klausmate] map dock select failed: {e}")
        try:
            from . import pdf_map

            pdf_map.select_pdf(safe)
        except Exception as e:
            print(f"[klausmate] map select failed: {e}")

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
                    # No bold (K-117): VS Code folders are regular
                    # weight — the chevron twisty carries the affordance.
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
            # K-132: the empty state, on the PDF count and nothing else.
            # `not contexts`, never "no rows": a Library holding folders
            # but no PDFs is still empty of the thing this pane is for,
            # and it keeps the block (parked below those folder rows).
            # This REPLACES the old one-line status message — the status
            # label is also where _refresh_rows writes its retention
            # notes, so that message was overwritten seconds later by
            # every refresh; an empty state that survives its own pane
            # is the point of the card.
            self.tree.set_empty_state(not contexts)
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
        # Numeric columns are right-aligned (VS Code report language;
        # K-117). Runtime-only on purpose: the AlignmentFlag OR can't
        # run under the fixed test stubs at import time.
        try:
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            for col in (1, 2, 3):
                item.setTextAlignment(col, align)
        except Exception:
            pass
        # Tabular figures on the numeric cells (K-127): the "tnum"
        # OpenType feature gives every digit the same advance width, so
        # figures align down the column under the right-alignment above.
        # QFont.setFeature only exists on Qt 6.7+ — guarded so an older
        # or odd binding degrades to proportional digits, never a
        # broken row.
        try:
            from aqt.qt import QFont

            f = item.font(1)
            f.setFeature(QFont.Tag(b"tnum"), 1)
            for col in (1, 2, 3):
                item.setFont(col, f)
        except Exception:
            pass
        retention_val: float | None = None
        cards: int | None = None
        notes: int | None = None
        suspended = 0
        if not row:
            item.setText(1, "—")
            item.setText(2, "")
            item.setText(3, "")
        elif not row.get("indexed"):
            item.setText(1, "—")
            item.setText(2, "not embedded")
            item.setText(3, "")
            # Status strings can elide in a numeric-width column — the
            # tooltip carries the full sentence, in the menu's language.
            item.setToolTip(2, "Not embedded yet — run Add to Search Index.")
        elif row.get("stale"):
            item.setText(1, "—")
            item.setText(2, "re-embed needed")
            item.setText(3, "")
            item.setToolTip(2, "The index is stale — run Update Search Index.")
        else:
            retention_val = row.get("retention")
            item.setText(
                1, f"{round(retention_val * 100)}%" if retention_val is not None else "—"
            )
            # Separate Cards/Notes columns (K-117). card_count counts
            # only VIEWABLE cards (suspended excluded — "don't show the
            # cards that are not viewable") and note_count the matched
            # notes; both computed by retention.priority_rows (K-118
            # contract). Consumed via .get so this file stands alone:
            # until those keys exist the cells render an em-dash and
            # light up the moment K-118 lands.
            raw_cards = row.get("card_count")
            raw_notes = row.get("note_count")
            cards = int(raw_cards) if raw_cards is not None else None
            notes = int(raw_notes) if raw_notes is not None else None
            suspended = int(row.get("suspended_count") or 0)
            doubtful = int(row.get("doubtful_count") or 0)
            if cards == 0 and suspended > 0:
                # Every matched card is suspended: say so instead of a
                # bare 0, and dim the whole row below.
                item.setText(2, "suspended")
            else:
                item.setText(2, f"{cards:,}" if cards is not None else "—")
            if doubtful:
                # K-254: pertinence rejected some of this PDF's matches —
                # confirmed counts (above) already exclude them, this just
                # says so, appended to whichever text the Cards cell just
                # got ("12 · 3 doubtful", or "suspended · 3 doubtful").
                item.setText(2, f"{item.text(2)} · {doubtful} doubtful")
            item.setText(3, f"{notes:,}" if notes is not None else "—")
            # The old composite cell's detail survives as hover text.
            matched = int(row.get("matched_cards") or 0)
            new_pct = float(row.get("new_pct") or 0.0)
            bits = [f"{matched:,} matched cards"]
            if suspended:
                bits.append(f"{suspended:,} suspended")
            if doubtful:
                bits.append(f"{doubtful:,} doubtful")
            bits.append(f"{round(new_pct * 100)}% unseen")
            tip = " · ".join(bits)
            item.setToolTip(2, tip)
            item.setToolTip(3, tip)
        # Sort keys live in a role, not the display text, so the tree can
        # sort numerically instead of lexicographically ("100%" < "20%",
        # "1,000" < "900"). -1.0 is an out-of-range sentinel: no row/not
        # embedded/stale have no retention *or* counts to speak of, so
        # all three columns sink them to the bottom (see
        # _LibraryItem.__lt__). A PDF that IS embedded but matched
        # nothing is a real, known zero — it sorts with the numbers, not
        # with the unknowns. Absent count keys (K-118 not landed) sort
        # as unknowns too.
        item.setData(
            1, _ROLE_SORT, float(retention_val) if retention_val is not None else _UNKNOWN_SORT
        )
        item.setData(2, _ROLE_SORT, float(cards) if cards is not None else _UNKNOWN_SORT)
        item.setData(3, _ROLE_SORT, float(notes) if notes is not None else _UNKNOWN_SORT)
        self._set_retention_color(item, retention_val)
        # After the retention colour on purpose: a fully suspended row's
        # dim wash covers every column, that cell included.
        self._set_suspended_dim(item, cards == 0 and suspended > 0)

    def _set_suspended_dim(self, item: QTreeWidgetItem, dimmed: bool) -> None:
        """A fully suspended PDF (every matched card suspended) reads as
        dormant: the whole row drops to the faint text token (K-117).
        Un-dimming clears the ForegroundRole with None so the default
        foreground returns — except column 1, whose colour belongs to
        ``_set_retention_color`` and is repainted right before this."""
        try:
            if dimmed:
                from aqt.qt import QBrush, QColor

                from . import theme as _theme

                faint = QBrush(
                    QColor(_theme.palette(_theme.night_mode())["text_faint"])
                )
                for col in range(4):
                    item.setForeground(col, faint)
            else:
                for col in (0, 2, 3):
                    item.setData(col, Qt.ItemDataRole.ForegroundRole, None)
        except Exception as e:
            print(f"[klausmate] suspended dim failed: {e}")

    def _set_retention_color(self, item: QTreeWidgetItem, fraction: float | None) -> None:
        """Color the retention cell's text only — no row background,
        regular weight, never bold. Semantic levels, not a hue ramp
        (K-127): low wears the palette's ``red_text``, high its
        ``green``, and mid gets NO ink at all — "fine" needs no colour,
        and the product bar is "Anki with a little extra you barely
        notice." Mid and non-numeric states RESET the ForegroundRole
        rather than skip: ``_apply_row`` reuses items across refreshes,
        so a row moving low -> mid must shed its stale red here (the
        un-dim in ``_set_suspended_dim`` deliberately leaves column 1
        to this method).
        """
        try:
            level = (
                drive_store.retention_level(fraction)
                if fraction is not None
                else None
            )
            if level in ("low", "high"):
                from aqt.qt import QBrush, QColor

                from . import theme as _theme

                pal = _theme.palette(_theme.night_mode())
                # green_text, not "green": the vivid system green is fill
                # ink, neon as text on dark (offscreen render, 2026-08-31).
                key = "red_text" if level == "low" else "green_text"
                item.setForeground(1, QBrush(QColor(pal[key])))
            else:
                item.setData(1, Qt.ItemDataRole.ForegroundRole, None)
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

    def _on_index_state(self, snapshot) -> None:
        """Render the shared runner's snapshot into this window.

        The status line and the Cancel button used to be driven by
        ``_begin``/``_finish``/``_on_progress``, private plumbing around
        a chain this window owned. It owns neither now: ONE pure
        ``index_queue.status_line`` writes both this label and the
        bottom-of-main-window bar, so the two surfaces cannot describe
        the same job differently, and Cancel stops the whole queue
        rather than this window's private run.
        """
        if not self._alive():
            return
        from . import index_queue

        self.status.setText(index_queue.status_line(snapshot))
        self.cancel_btn.setVisible(bool(snapshot.active))
        if snapshot.finished:
            # A PDF's matches just landed — its retention, card counts
            # and freshness flag are all stale in this tree.
            self._refresh_rows()

    def _on_cancel(self) -> None:
        from . import index_queue

        index_queue.cancel_all()

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
            self.card_queues = out.get("card_queues") or {}
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
            # One status line, two writers, and the running job wins
            # (K-152). This callback lands asynchronously — on window
            # open, and again after every finished job — so without the
            # guard it would blank the progress of the job that is
            # running RIGHT NOW, which is the one thing on this line the
            # user might be waiting on. The notes are advisory and
            # reappear on the next refresh.
            from . import index_queue

            if not index_queue.state().active:
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
        """Ask the shared runner to index this PDF.

        **The four-phase chain that used to BE this method now lives in
        ``index_queue``** (K-152): ``curation.ensure_index`` (the CARD
        index — an embedding per note, and the reason K-146 could not
        just delete the curate button: nothing else refreshes it, so
        skipping it leaves every note written since the last pass
        invisible to matching and the PDF's !Library tag silently
        under-covering) → ``ensure_pdf_index`` → ``ensure_matches`` →
        ``tag_sync``, cancel token threaded through, each phase taking
        ``curation._busy`` in its own turn.

        It moved because a PDF added from the deck screen has no Library
        window and so could reach none of it. This window is now one
        CALLER of that runner among several, and there is exactly one
        copy of the sequence in the addon — a second would drift
        (K-143's two-renderer lesson).

        ``announce=False``: the runner's tooltip is for surfaces with
        nowhere to show state. This window has ``_on_index_state``.
        """
        from . import index_queue

        index_queue.request_pdf(safe, announce=False)

    def _on_threshold(self, safe: str) -> None:
        cfg = retention._cfg()
        current = retention.get_threshold(safe, cfg)
        dlg = QDialog(self)
        dlg.setWindowTitle("Match Sensitivity")
        try:
            from . import theme as _theme

            dlg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as _exc:
            print(f"[klausmate] sensitivity dialog theme failed: {_exc}")
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
        # K-254 review Important 1: read once, same as `matches` above —
        # never per keystroke — so the live preview and the OK path score
        # exactly what the Library row already excludes (confirmed =
        # matched - rejected). A read failure degrades to "nothing
        # rejected" rather than freezing the dialog.
        try:
            from . import pertinence

            _rejected = pertinence.rejected_nids(
                pertinence.load_judged(_user_files(), safe)
            )
        except Exception as exc:
            print(f"[klausmate] sensitivity dialog: doubtful set unavailable: {exc}")
            _rejected = set()

        def preview(value: int) -> None:
            threshold = value / 100.0
            if matches is None:
                label.setText(f"Threshold {threshold:.2f}")
                return
            agg = retention.pdf_retention(
                [(int(n), float(s)) for n, s in matches], threshold, self.card_r,
                rejected=_rejected,
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

        def apply() -> None:
            value = slider.value() / 100.0
            retention.set_threshold(safe, value)
            tag_sync.sync_after_threshold(mw, safe, matches, value)
            row = self.rows.get(safe)
            if row is not None and matches is not None:
                pairs = [(int(n), float(s)) for n, s in matches]
                agg = retention.pdf_retention(
                    pairs, value, self.card_r, rejected=_rejected,
                )
                # The COUNTS move with the threshold too (PR #4 F5) —
                # without this the Cards cell showed a score computed at
                # the new threshold beside a "· n doubtful" (and a card
                # count, and a note count) computed at the old one.
                notes, cards, susp, doubtful = retention.note_card_counts(
                    pairs, value, self.card_queues, rejected=_rejected,
                )
                row.update(threshold=value, note_count=notes, card_count=cards,
                           suspended_count=susp, doubtful_count=doubtful, **{
                    k: agg[k] for k in ("retention", "matched_cards", "new_pct", "priority")
                })
                for item in self._iter_pdf_items():
                    if item.data(0, _ROLE_SAFE) == safe:
                        self._apply_row(item, row)

        # K-114: window-modal open() + accepted callback, never
        # app-modal exec() — that path segfaulted seven times on
        # Qt 6.11 + macOS 26 (manage_models' precedent; the reject
        # path simply never fires apply).
        dlg.accepted.connect(apply)
        dlg.open()

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
        browser.search_for(tag_sync.tag_query(tag))

    def _on_doubtful(self, safe: str) -> None:
        """K-254: "Doubtful cards…" — this PDF's own lecture tag,
        intersected with the global Doubtful tag. No matches/threshold
        math needed here (unlike _on_browse): tag membership already IS
        the confirmed/rejected split, so this is a plain tag search.

        Both operands come from ``tag_sync.tag_query`` (PR #4 fourth
        review): a tag is user-derived and this is Anki's query
        language, where a quote ends the operand and ``*``/``_`` are
        wildcards.
        """
        tag = tag_sync.get_stored_tag(safe)
        if not tag:
            self.status.setText("Re-index this PDF to create its Library tag.")
            return
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(
            tag_sync.tag_query(tag_sync.DOUBTFUL_TAG)
            + " "
            + tag_sync.tag_query(tag)
        )

    def _set_suspended_cards(self, safe: str, suspend: bool) -> None:
        """Suspend or unsuspend every card of this PDF's matched notes
        (K-117 — "allow me to suspend and unsuspend specific PDFs on
        their own").

        Membership IS the per-PDF !Library tag (tag_sync's invariant):
        the stored tag when one exists — the exact string tag_sync last
        applied, same resolution as the Browse hop — falling back to
        the derived ``desired_tag`` for a PDF whose tag was never
        stored. The sched call runs as ONE CollectionOp so it lands as
        a single undoable step (curation.py's threading pattern; the
        sched API brings its own undo entry, so no custom entry is
        needed), and the rows refresh after so the Cards column and the
        dimmed row treatment follow immediately.
        """
        if mw is None or mw.col is None:
            return
        tag = tag_sync.get_stored_tag(safe)
        if not tag:
            folder, display = tag_sync._folder_and_display(safe)
            tag = tag_sync.desired_tag(folder, display)
        try:
            cids = list(mw.col.find_cards(tag_sync.tag_query(tag)))
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Could not find this PDF's cards: {e}")
            return
        if not cids:
            self.status.setText(
                "No cards carry this PDF's Library tag yet — index it first."
            )
            return

        def op(col):
            if suspend:
                return col.sched.suspend_cards(cids)
            return col.sched.unsuspend_cards(cids)

        verb = "Suspended" if suspend else "Unsuspended"

        def done(_changes) -> None:
            if not self._alive():
                return
            tooltip(f"{verb} {len(cids):,} cards (Ctrl+Z to undo)", parent=self)
            self._refresh_rows()

        # Parented to mw like the QueryOp above: the window may close
        # mid-run; _alive() guards the callback instead.
        CollectionOp(parent=mw, op=op).success(done).run_in_background()

    # ----------------------------------------------------------- actions

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        """Double-click a row: expand a folder, or show a PDF.

        A Qt SLOT, so the whole body is wrapped — ``item.data()``
        included. An unhandled exception here does not print and carry
        on: in a bare interpreter PyQt6 calls ``qFatal()`` (exit 134); in
        Anki, whose excepthook PyQt6 honours instead, it is the modal
        error dialog mid-review (K-183). Neither is a broken row.

        The viewer comes from ``_ensure_sidebar``, never off the
        attribute: fc8591c left this line calling ``self.sidebar
        .load_pdf`` on a None the embedded screen never builds, and the
        except below dressed the AttributeError up as a modal "Could not
        open that PDF" — the whole of K-173's reported symptom.
        """
        try:
            safe = item.data(0, _ROLE_SAFE)
            if not safe:
                item.setExpanded(not item.isExpanded())
                return
            try:
                sidebar = self._ensure_sidebar()
                if sidebar is None:
                    self.status.setText(NO_VIEWER_TEXT)
                    print("[klausmate] library: no viewer to open a PDF in")
                    return
                sidebar.load_pdf(safe)
                pdf_handler.touch_last_used(_user_files(), safe)
            except Exception as e:
                # A line, not a modal (see NO_VIEWER_TEXT).
                print(f"[klausmate] drive open failed for {safe}: {e}")
                self.status.setText(f"Could not open that PDF: {e}")
        except Exception as e:
            # The outer net: everything above, the status write included,
            # touches C++ objects that may be gone.
            print(f"[klausmate] drive activate failed: {e}")

    def _on_dropped_paths(
        self, paths: list[str], folder: str | None = None
    ) -> None:
        """Import PDFs dropped on, or picked via Browse… in, the drop
        zone — and, since K-117, dropped straight onto the folder tree.
        Reaches the same import_pdf_file() every other PDF entry
        point uses (its own docstring already names "drive window" as a
        caller) so a file lands in the store exactly like it would from
        the deck screen or the editor's PDF bar — the only difference is
        what happens after: a tree rebuild, so the new PDF shows up
        immediately in the window the user is already looking at.

        ``folder`` is the tree drop's target (None = root — what the
        bottom drop zone always passes): each imported PDF is FILED
        there through ``_move_pdf``, the one choke point that already
        moves the store entry, the on-disk file, and the !Library tag
        together.
        """
        from . import import_pdf_file

        imported: list[str] = []
        for path in paths:
            try:
                name = import_pdf_file(path)
            except Exception as e:
                print(f"[klausmate] library import failed for {path}: {e}")
                continue
            if name:
                imported.append(name)
        if folder:
            for name in imported:
                try:
                    self._move_pdf(name, folder)
                except Exception as e:  # noqa: BLE001
                    print(
                        f"[klausmate] library drop filing failed for {name!r}: {e}"
                    )
        if imported:
            self.rebuild_tree()

    def _new_folder(
        self, parent_path: str | None = None, on_done=None
    ) -> None:
        """Prompt for a folder name, window-modal (K-125).

        A QInputDialog INSTANCE via open() + textValueSelected — the
        getText static it replaces exec()s app-modal internally, the
        K-114 segfault class. ``on_done(path)`` fires only when the
        folder was actually created (the accepted-callback CPS shape);
        cancel, an emptied name, and an invalid name all end the flow
        exactly as the old blocking return-None paths did.
        """
        dlg = QInputDialog(self)
        dlg.setWindowTitle("New Folder")
        dlg.setLabelText("Folder name:")
        try:
            from . import theme as _theme

            dlg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as _exc:
            print(f"[klausmate] new-folder dialog theme failed: {_exc}")

        def _create(raw) -> None:
            name = str(raw or "").strip().strip("/")
            if not name:
                return
            path = f"{parent_path}/{name}" if parent_path else name
            if not drive_store.add_folder(_user_files(), path):
                showWarning("That folder name isn't valid.")
                return
            self.rebuild_tree()
            if on_done is not None:
                on_done(path)

        dlg.textValueSelected.connect(_create)
        dlg.finished.connect(lambda _r: dlg.deleteLater())
        dlg.open()

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        try:
            # K-117 menu clarity: the index action carries an
            # explanatory tooltip — invisible unless the menu opts in.
            menu.setToolTipsVisible(True)
        except Exception:
            pass
        if item is not None and item.data(0, _ROLE_SAFE):
            self._build_pdf_menu(menu, item)
        elif item is not None and item.data(0, _ROLE_FOLDER):
            self._build_folder_menu(menu, item.data(0, _ROLE_FOLDER))
        else:
            menu.addAction("New Folder…").triggered.connect(lambda: self._new_folder())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_pdf_menu(self, menu: QMenu, item: QTreeWidgetItem) -> None:
        safe = item.data(0, _ROLE_SAFE)
        row = self.rows.get(safe) or {}

        menu.addAction("Open").triggered.connect(
            lambda: self._on_item_activated(item)
        )
        menu.addAction("Rename…").triggered.connect(lambda: self._rename_pdf(safe))

        move = menu.addMenu("Move to Folder")
        move.addAction("(root)").triggered.connect(
            lambda: self._move_pdf(safe, None)
        )
        for path in drive_store.load(_user_files()).get("folders") or []:
            move.addAction(path).triggered.connect(
                lambda _c=False, p=path: self._move_pdf(safe, p)
            )
        move.addSeparator()
        move.addAction("New Folder…").triggered.connect(
            lambda: self._move_to_new_folder(safe)
        )

        menu.addSeparator()
        # K-117 menu clarity ("I don't understand what reindex and
        # curate deck difference is"): the index action says what it
        # indexes and carries a tooltip spelling out what it touches
        # (visible via setToolTipsVisible above). K-146 answered the
        # same confusion the other way — the curate action is GONE,
        # because it only ever tagged and opened Browse on the tag
        # indexing already writes, which "Show Matched Cards in Browse"
        # two lines below opens directly.
        embed_label = (
            "Update Search Index" if row.get("indexed") else "Add to Search Index"
        )
        embed_action = menu.addAction(embed_label)
        embed_action.setToolTip(
            "Re-reads the PDF and recomputes which cards match it. "
            "Does not touch your decks."
        )
        embed_action.triggered.connect(lambda: self._on_embed(safe))
        menu.addAction("Match Sensitivity…").triggered.connect(
            lambda: self._on_threshold(safe)
        )
        menu.addAction("Show Matched Cards in Browse").triggered.connect(
            lambda: self._on_browse(safe)
        )
        # K-254 review Important 4: always offered, exactly like the
        # neighbouring "Show Matched Cards in Browse" — DOUBTFUL_TAG is
        # the GLOBAL union across every PDF (spec D5), so gating on this
        # row's OWN doubtful_count would both hide the item on a PDF
        # whose search still returns results (another PDF rejected the
        # same note) and offer it on a PDF whose search can return notes
        # rejected only by OTHERS. Task 7 documents that divergence.
        menu.addAction(DOUBTFUL_MENU_LABEL).triggered.connect(
            lambda: self._on_doubtful(safe)
        )
        if retention_history is not None:
            # K-118's contract: open_history_dialog(parent, safe, label).
            menu.addAction("Retention History…").triggered.connect(
                lambda: retention_history.open_history_dialog(
                    self, safe, row.get("label") or safe
                )
            )
        menu.addSeparator()
        # Per-PDF suspend/unsuspend (K-117). Offer by current state when
        # the K-118 count keys are present; with counts unknown offer
        # both — the runtime path degrades to a status line when the
        # tag has no cards.
        cards = row.get("card_count")
        suspended = int(row.get("suspended_count") or 0)
        if cards is None or int(cards) > 0:
            suspend_action = menu.addAction("Suspend Cards")
            suspend_action.setToolTip(
                "Suspends every card of this PDF's matched notes — they "
                "stop coming up in reviews until unsuspended."
            )
            suspend_action.triggered.connect(
                lambda _c=False, s=safe: self._set_suspended_cards(s, True)
            )
        if cards is None or suspended > 0:
            unsuspend_action = menu.addAction("Unsuspend Cards")
            unsuspend_action.setToolTip(
                "Returns this PDF's suspended cards to review."
            )
            unsuspend_action.triggered.connect(
                lambda _c=False, s=safe: self._set_suspended_cards(s, False)
            )
        menu.addSeparator()
        menu.addAction("Delete…").triggered.connect(lambda: self._delete_pdf(safe))

    def _build_folder_menu(self, menu: QMenu, path: str) -> None:
        menu.addAction("New Subfolder…").triggered.connect(
            lambda: self._new_folder(path)
        )
        menu.addAction("Rename Folder…").triggered.connect(
            lambda: self._rename_folder(path)
        )
        menu.addAction("Remove Folder").triggered.connect(
            lambda: self._remove_folder(path)
        )

    def _rename_pdf(self, safe: str) -> None:
        # K-125: instance + open() + textValueSelected, never the
        # app-modal getText static. Cancel/empty keep their old
        # do-nothing meaning (the signal only fires on OK).
        current = drive_store.display_name(_user_files(), safe)
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename PDF")
        dlg.setLabelText("Display name:")
        dlg.setTextValue(current)
        try:
            from . import theme as _theme

            dlg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as _exc:
            print(f"[klausmate] rename dialog theme failed: {_exc}")

        def _apply(raw) -> None:
            name = str(raw or "").strip()
            if not name:
                return
            drive_store.rename_display(_user_files(), safe, name)
            # Disk rename follows the display rename (K-075).
            try:
                root = pdf_handler._live_library_root()
                if root and os.path.isdir(root):
                    pdf_handler.rename_mapped_file(
                        _user_files(), root, safe, name
                    )
            except Exception as e:  # noqa: BLE001
                print(f"[klausmate] disk rename failed for {safe!r}: {e}")
            self.rebuild_tree()
            tag_sync.sync_after_rename(mw, safe)

        dlg.textValueSelected.connect(_apply)
        dlg.finished.connect(lambda _r: dlg.deleteLater())
        dlg.open()

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
        # K-125 CPS: the move rides _new_folder's created-path callback.
        self._new_folder(on_done=lambda path: self._move_pdf(safe, path))

    def _rename_folder(self, path: str) -> None:
        # K-125: instance + open() + textValueSelected (see _rename_pdf).
        leaf = path.rsplit("/", 1)[-1]
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename folder")
        dlg.setLabelText("Folder name:")
        dlg.setTextValue(leaf)
        try:
            from . import theme as _theme

            dlg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as _exc:
            print(f"[klausmate] rename dialog theme failed: {_exc}")

        def _apply(raw) -> None:
            name = str(raw or "").strip().strip("/")
            if not name or name == leaf:
                return
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            # Same path as a drag-move (K-076): the store-only rename
            # this shipped as was reverted by the very next disk-truth
            # rescan.
            self._move_folder(path, f"{parent}/{name}" if parent else name)

        dlg.textValueSelected.connect(_apply)
        dlg.finished.connect(lambda _r: dlg.deleteLater())
        dlg.open()

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
        # K-125: instance + open() + finished/clickedButton, never the
        # question() static (its internal exec is app-modal, the K-114
        # segfault class). Yes/No with No default as before; Esc/close
        # land on No, exactly the static's reject path. The closure
        # keeps ``msg`` referenced; themed per K-112 with the delete
        # action wearing DangerButton.
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete PDF")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f"Delete “{display}”?\n\n"
            "This removes the PDF, its extracted text, your highlights and "
            "notes, and its retention index. Cards are not touched."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = msg.button(QMessageBox.StandardButton.Yes)
        if yes_btn is not None:
            yes_btn.setObjectName("DangerButton")
        no_btn = msg.button(QMessageBox.StandardButton.No)
        if no_btn is not None:
            no_btn.setObjectName("SecondaryButton")
        try:
            from . import theme as _theme

            msg.setStyleSheet(_theme.dialog_qss(_theme.night_mode()))
        except Exception as _exc:
            print(f"[klausmate] delete dialog theme failed: {_exc}")

        def _on_answered(_r: int) -> None:
            clicked = msg.clickedButton()
            confirmed = (
                clicked is not None
                and msg.standardButton(clicked)
                == QMessageBox.StandardButton.Yes
            )
            msg.deleteLater()
            if confirmed:
                self._delete_pdf_confirmed(safe, display)

        msg.finished.connect(_on_answered)
        msg.open()

    def _delete_pdf_confirmed(self, safe: str, display: str) -> None:
        """The destructive back half, run only from the confirm's Yes."""
        # The ATTRIBUTE, not _ensure_sidebar: deleting a PDF must never
        # build a viewer that was not wanted.
        sidebar = self.sidebar
        if sidebar is not None:
            try:
                if sidebar.is_loaded(safe):
                    sidebar.clear()
                    # clear() is the one load-path that does NOT fire
                    # on_loaded, so the map would keep a ring on the PDF
                    # the viewer just stopped showing (K-143).
                    self._on_viewer_loaded(None)
            except Exception as e:
                print(f"[klausmate] viewer clear on delete failed: {e}")
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
        # No disarm call here since K-151: the deck square no longer
        # names a PDF (arming went with the curate button it staged
        # for), so there is nothing left for a delete to clear. The
        # K-146 comment that stood here explained why the call survived
        # that card; the concept it guarded is now gone entirely.
        # Drop it from the index queue too (K-152). The runner re-checks
        # presence before it starts each job, so this is not what makes
        # a deleted PDF safe — it is what stops the bar advertising work
        # on a file the user just removed.
        try:
            from . import index_queue

            index_queue.forget(safe)
        except Exception as e:
            print(f"[klausmate] index queue forget failed: {e}")
        self.rows.pop(safe, None)
        self.matches.pop(safe, None)
        self.rebuild_tree()
        tooltip(f"Deleted “{display}”.")

    def _open_map(self) -> None:
        """The K-123 embedding map, guarded like every optional surface
        — a broken map import costs a log line, never the Library."""
        try:
            from . import pdf_map

            pdf_map.open_map_window(self)
        except Exception as exc:
            print(f"[klausmate] map open failed: {exc}")

    def _open_assistant(self) -> None:
        """Task 11: toggle the Claude Code assistant dock, same guarded-
        import shape as _open_map above — a broken/missing assistant
        module costs a log line, never the Library. The dock lives on
        mw, not here, so this never builds or owns a widget; it only
        asks assistant_dock to show or hide the one it manages."""
        try:
            from . import assistant_dock

            assistant_dock.toggle_assistant()
        except Exception as exc:
            print(f"[klausmate] assistant open failed: {exc}")

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

    def shutdown(self) -> None:
        """Teardown extracted from closeEvent (unsubscribe, persist
        geometry, clear the viewer, reset the singleton).

        **Closing this window no longer cancels indexing** (K-152). It
        used to call ``_on_cancel``, which was right while the run was
        this window's private property; now the run belongs to the
        addon, may have been started from the deck screen, and has its
        own always-visible bar with its own Stop button. Killing minutes
        of paid embedding because a window was tidied away would be the
        opposite of what this card is for. Bumping ``seq`` still drops
        any in-flight retention refresh, which is what it was ever for.
        """
        global _instance
        try:
            from . import index_queue

            index_queue.remove_listener(self._on_index_state)
        except Exception as e:
            print(f"[klausmate] index listener detach failed: {e}")
        try:
            self.seq += 1
            self._save_geometry()
        except Exception as e:
            print(f"[klausmate] drive close cleanup failed: {e}")
        # SEPARATE from the try above, deliberately: these two shared one
        # block, so a geometry-save failure skipped the cleanup and left
        # exactly the dangling AnkiWebView that cleanup exists to
        # prevent. Unregistering the renderer's webview from Anki's
        # global hooks while its C++ object is still alive (see
        # PdfSidebar.cleanup) is the part that must not be conditional
        # on anything.
        self.release_viewer()
        if _instance is self:
            _instance = None

    def closeEvent(self, evt) -> None:  # noqa: N802 — Qt naming
        try:
            self.shutdown()
        except Exception as e:
            print(f"[klausmate] drive shutdown failed: {e}")
        # Only the standalone window is a dialog-manager instance; an
        # embedded screen was never opened through aqt.dialogs, so
        # reporting it closed would mark a window that may still be open.
        if not self.embedded:
            try:
                aqt.dialogs.markClosed(DIALOG_NAME)
            except Exception:
                pass
        super().closeEvent(evt)


# ------------------------------------------------------------ module API


_instance: DriveWindow | None = None


def _live_libraries():
    """Every live Library, whichever shape it is wearing.

    Two rosters, disjoint by construction — ``_instance`` is written only
    by ``_create()`` (the standalone window), ``_embedded_windows`` only
    by an embedded ``__init__`` — so nothing here dedupes. Hidden windows
    are yielded on purpose: hidden is the embedded tab's RESTING state,
    and a consumer must MARK it (see _refresh_live_libraries), not skip
    it — skipping is how a settings save made elsewhere in Anki was lost.
    """
    for win in (_instance, *_embedded_windows):
        if win is not None and win._alive():
            yield win


def _refresh_live_libraries(why: str) -> int:
    """Refresh every VISIBLE live Library now; mark hidden ones pending.

    A hidden screen is refreshed exactly once, by _on_shown when it is
    next looked at — not once per event while nobody sees it. Measured
    (2026-09-01): one refresh holds the collection worker ~130ms (an 88MB
    index load, four match caches, retrievability over 35k cards), and
    save_threshold fires on every slider release, so five releases on the
    deck screen were five refreshes of an unseen screen for an identical
    end state. Per-window guard: one screen's exception must neither
    escape into the caller nor skip the others. Returns how many were
    refreshed NOW, so the watcher can fall back to a bare rescan.
    """
    refreshed = 0
    for win in _live_libraries():
        try:
            if not win.isVisible():
                win._refresh_pending = True
                continue
            win._refresh_rows()
            refreshed += 1
        except Exception as e:
            print(f"[klausmate] library refresh {why} failed: {e}")
    return refreshed


@guarded
def _restyle_live_libraries() -> None:
    """Every live Library re-paints itself against the current theme.

    Deferred one tick from ``_on_theme_change`` — Anki toggles its
    night-mode CSS classes via JS, same tick, same pattern top_bar.py and
    window_chrome.py both defer around; restyling immediately can race
    that flip and read the old state.
    """
    for win in _live_libraries():
        try:
            win._apply_theme()
        except Exception as e:
            print(f"[klausmate] library theme refresh {win} failed: {e}")


def _on_theme_change() -> None:
    try:
        QTimer.singleShot(0, _restyle_live_libraries)
    except Exception as e:
        print(f"[klausmate] library theme-change scheduling failed: {e}")


def refresh_open_library() -> None:
    """Re-aggregate every live Library — the screen and the window.

    Called from KlausMate Preferences when the DEFAULT sensitivity is
    saved (manage_models.save_threshold): every PDF without a per-PDF
    override reads that default through retention.get_threshold, so the
    retention/cards columns a Library is showing go stale the moment it
    changes. Without this hook the Library only caught up on reopen —
    which read as the setting not working at all (Pouya, K-052:
    'currently it does not update the library sensitivity like I had
    imagined'). No-op when none is open; per-PDF overrides are
    unaffected either way since they never read the default.
    """
    _refresh_live_libraries("after settings change")


def _create() -> DriveWindow:
    global _instance
    _instance = DriveWindow()
    return _instance


def open_library() -> None:
    """What the toolbar's Library link does now: a screen inside Anki's
    main window rather than a separate one (Pouya, 2026-09-01 — "it's
    really annoying having a separate window show up each time").

    Falls back to the standalone window if the mount fails for any reason,
    so a broken tab costs the tab and not the Library.
    """
    try:
        from . import library_tab

        if library_tab.mount():
            return
    except Exception as e:
        print(f"[klausmate] library tab unavailable, using the window: {e}")
    open_drive()


def open_drive() -> None:
    try:
        aqt.dialogs.open(DIALOG_NAME)
    except Exception as e:
        print(f"[klausmate] drive open failed: {e}")
        # Deferred: the toolbar Library link reaches here over the
        # webchannel, and showWarning is modal — the bridge-reentrancy
        # rule (tests/test_bridge_reentrancy.py) applies to this error
        # branch too. The message is frozen as a default because the
        # except-variable is unbound by the time the timer fires.
        QTimer.singleShot(
            0,
            lambda msg=f"Could not open the PDF drive.\n\n{e}": showWarning(msg),
        )


def _release_embedded_viewers() -> None:
    """K-095 for the Library SCREEN, which has no close to hang it on.

    ``library_tab`` keeps its tab in module state for the whole session
    and unmount only HIDES it, so the standalone window's closeEvent
    teardown never runs for it. Profile switch and quit are the two
    points where the viewer's webview must be handed back — a webview
    still registered in Anki's global hooks when its C++ object dies
    crashes the next theme change. ``pdf_viewer.cleanup_all_sidebars``
    is the blanket sweep behind this; this is the owner doing it for
    itself, and it also drops the husk so the next open builds a live
    viewer instead of finding a cleaned-up one.
    """
    for win in _live_libraries():
        if win.embedded:
            win.collection_will_close()


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
    """Insert the Library link so the bar reads
    Decks · Add · Library · Browse · Stats · Sync (K-088).

    Anki builds the list and other addons may add to it, so the slot is
    found by locating Browse rather than trusting a fixed index; with no
    Browse link (a future rename) it falls back to third place, which is
    that same slot in the stock layout.
    """
    try:
        link = toolbar.create_link(
            "klausDriveOpen",
            "Library",
            open_library,
            tip="Klaus PDF library",
            id="klaus-drive",
        )
        idx = next(
            (
                i
                for i, item in enumerate(links)
                if "browse" in str(item).lower()
            ),
            min(2, len(links)),
        )
        links.insert(idx, link)
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
        # K-117 built the Library's chrome once at construction; the
        # embedded screen then lives for the whole session (built once,
        # shown/hidden thereafter), so a later day/night flip never
        # reached it without this.
        gui_hooks.theme_did_change.append(_on_theme_change)
    except Exception as e:
        print(f"[klausmate] drive theme hook failed: {e}")
    try:
        gui_hooks.profile_will_close.append(_close_drive)
        gui_hooks.profile_will_close.append(_release_embedded_viewers)
    except Exception as e:
        print(f"[klausmate] drive profile hook failed: {e}")
    try:
        mw.app.aboutToQuit.connect(_close_drive)
        mw.app.aboutToQuit.connect(_release_embedded_viewers)
    except Exception as e:
        print(f"[klausmate] drive quit hook failed: {e}")
