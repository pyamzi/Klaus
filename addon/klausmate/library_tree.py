"""The Add tab's Library tree: Klaus's own view over the index
``library_sidebar`` builds (spec
docs/superpowers/specs/2026-10-01-add-tab-design.md, "The Library tree").

Same rows as Browse's Library section — the ``!Library`` root, folders,
PDFs, with the same icons, painted names, retention % and warning icons
(``library_sidebar.LibraryNameDelegate`` through ``TreeDelegate``), the
same right-click items (``library_sidebar.menu_entries``), the same
import footer and Finder drops — plus a filter box. It is NOT an Anki
``SidebarTreeView``: Anki's needs a Browse instance for every click.

A single click on a PDF row emits ``pdf_clicked(safe)``; the host opens
it in the reader. Folder rows toggle. PDF rename, delete and drag-to-move
stay in Browse's sidebar (Anki's tag operations) or in Finder.

Pure above the divider.
"""
from __future__ import annotations

from . import library_sidebar as ls

SEP = "::"


def tree_from_index(index: dict) -> dict:
    """Nested nodes from ``library_index()``: ``{"key", "label", "kind"
    ("root" | "folder" | "pdf"), "safe", "folder", "children"}``, rooted at
    the Library; folders before PDFs, each level by label (casefolded).
    A PDF whose tag path names a folder the index does not list still
    lands by its tag path."""
    labels, safes, folders = index.get("labels", {}), index.get("safes", {}), index.get("folders", {})
    root_key = ls.ROOT_TAG.casefold()
    nodes: dict[str, dict] = {}

    def node(key: str) -> dict:
        if key not in nodes:
            kind = "root" if key == root_key else "pdf" if key in safes else "folder"
            nodes[key] = {"key": key, "label": labels.get(key) or key.rsplit(SEP, 1)[-1], "kind": kind,
                          "safe": safes.get(key), "folder": folders.get(key), "children": []}
            if key != root_key:
                parent_key = key.rsplit(SEP, 1)[0] if SEP in key else root_key
                node(parent_key)["children"].append(nodes[key])
        return nodes[key]

    node(root_key)
    for key in list(labels) + list(safes) + list(folders):
        if key == root_key or key.startswith(root_key + SEP):
            node(key)
    for n in nodes.values():
        n["children"].sort(key=lambda c: (c["kind"] == "pdf", c["label"].casefold()))
    return nodes[root_key]


def visible_keys(node: dict, needle: str) -> set[str]:
    """Keys whose label contains ``needle`` (casefolded) plus every
    ancestor of a match; an empty needle means every key."""
    needle = (needle or "").strip().casefold()
    out: set[str] = set()

    def walk(n: dict) -> bool:
        hit = not needle or needle in n["label"].casefold()
        for child in n["children"]:
            hit = walk(child) or hit
        if hit:
            out.add(n["key"])
        return hit

    walk(node)
    return out


# ── aqt glue ─────────────────────────────────────────────────────────────

from aqt.qt import (  # noqa: E402
    QIcon,
    QLineEdit,
    QMenu,
    QStandardItem,
    QStandardItemModel,
    Qt,
    QTreeView,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

TAG_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_ROLE = Qt.ItemDataRole.UserRole + 2
SAFE_ROLE = Qt.ItemDataRole.UserRole + 3
_ICONS = {"root": ls.ROOT_ICON, "folder": ls.FOLDER_ICON, "pdf": ls.PDF_ICON}


class TreeDelegate(ls.LibraryNameDelegate):
    def tag_of(self, index) -> str | None:
        return index.data(TAG_ROLE)


class LibraryTree(QWidget):
    pdf_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("klausmate_library_tree")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter")
        self.filter.setClearButtonEnabled(True)
        self.view = QTreeView(self)
        self.view.setHeaderHidden(True)
        self.view.setUniformRowHeights(True)
        self.view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.view.setItemDelegate(TreeDelegate(self.view))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model = QStandardItemModel(self)
        self.view.setModel(self.model)
        self.footer = ls.Footer(self)
        lay.addWidget(self.filter)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.footer)
        self._items: dict[str, QStandardItem] = {}
        self._expanded: set[str] = set()
        self._built = False
        self._drops = ls.PdfDropFilter(self)
        self.view.viewport().setAcceptDrops(True)
        self.view.viewport().installEventFilter(self._drops)
        self.footer.setAcceptDrops(True)
        self.footer.installEventFilter(self._drops)
        self.view.clicked.connect(self._on_clicked)
        self.view.expanded.connect(lambda idx: self._expanded.add(idx.data(TAG_ROLE)))
        self.view.collapsed.connect(lambda idx: self._expanded.discard(idx.data(TAG_ROLE)))
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self.filter.textChanged.connect(lambda _t: self._apply_filter())
        ls._trees.add(self)
        self.refresh()

    # ── rows ──
    def index_for(self, key: str):
        item = self._items.get(key)
        return item.index() if item is not None else self.model.index(-1, -1)

    def refresh(self) -> None:
        """Rebuild from the index, keeping expansion and the filter; a
        failed read leaves the previous rows."""
        try:
            root = tree_from_index(ls.library_index())
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] library tree: index read failed: {exc}")
            return
        if not self._built:
            self._expanded = {root["key"]}
            self._built = True
        self.model.clear()
        self._items = {}
        self.model.invisibleRootItem().appendRow(self._item(root))
        for key in list(self._expanded):
            idx = self.index_for(key)
            if idx.isValid():
                self.view.setExpanded(idx, True)
        self._apply_filter()

    def _item(self, node: dict) -> QStandardItem:
        item = QStandardItem(node["label"])
        item.setEditable(False)
        item.setData(node["key"], TAG_ROLE)
        item.setData(node["kind"], KIND_ROLE)
        item.setData(node["safe"], SAFE_ROLE)
        item.setIcon(QIcon(_ICONS[node["kind"]]))
        self._items[node["key"]] = item
        for child in node["children"]:
            item.appendRow(self._item(child))
        return item

    def _apply_filter(self) -> None:
        text = self.filter.text()
        keep = visible_keys(tree_from_index(ls.library_index()), text) if text.strip() else None
        for key, item in self._items.items():
            idx = item.index()
            hide = keep is not None and key not in keep
            self.view.setRowHidden(idx.row(), idx.parent(), hide)
            if keep is not None and not hide and item.hasChildren():
                self.view.setExpanded(idx, True)

    # ── clicks ──
    def _on_clicked(self, index) -> None:
        kind = index.data(KIND_ROLE)
        if kind == "pdf":
            safe = index.data(SAFE_ROLE)
            if safe:
                self.pdf_clicked.emit(safe)
        else:
            self.view.setExpanded(index, not self.view.isExpanded(index))

    def popup_menu(self, menu, pos) -> None:
        menu.popup(self.view.viewport().mapToGlobal(pos))  # never exec (K-114)

    def _on_context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        key = index.data(TAG_ROLE) if index.isValid() else None
        if not key:
            return
        menu = QMenu(self)
        for entry in ls.menu_entries(self, key):
            if entry is None:
                if menu.actions():
                    menu.addSeparator()
            else:
                ls._add(menu, *entry)
        if menu.actions():
            self.popup_menu(menu, pos)
