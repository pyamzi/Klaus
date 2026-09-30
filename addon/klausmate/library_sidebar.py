"""The Library in Browse's sidebar (K-307; spec
docs/superpowers/specs/2026-09-28-library-in-browse-design.md, Part 2).

Real names: a tag cannot hold a space, so ``Intro_to_CBC``
is the tag's real name. The sidebar row now PAINTS the PDF's own name
("04-L-Intro to CBC"), a folder's own name ("Week 1") and "Library" for
the ``!Library`` root. Only the drawn text changes (``initStyleOption``):
the rename editor still opens on the tag name (EditRole), and search,
drag and delete still act on the tag.

Retention: every tag row, not only the Library's, ends in a dimmed
grey %: the mean FSRS recall of the tag's cards right now, a parent
counting its children's cards, suspended ones included, new cards left
out ("—"
when nothing is studied). Computed in a background op over the whole
collection and repainted when it lands.

aqt-free above the "aqt glue" divider.
"""
from __future__ import annotations

import os
from typing import Callable

from . import tag_sync

ROOT_TAG = "!Library"
ROOT_LABEL = "Library"

_cache: dict = {"key": None, "index": None}


def build_index(drive: dict, prefs: dict) -> dict:
    """Pure. ``labels``: tag casefolded -> the name to show, for the
    root, every folder and every PDF that owns a tag. ``safes``: PDF tag
    -> safe name. ``folders``: folder tag -> folder path."""
    labels = {ROOT_TAG.casefold(): ROOT_LABEL}
    safes: dict[str, str] = {}
    folder_tags: dict[str, str] = {}
    pdfs = drive.get("pdfs") or {}
    folders = list(drive.get("folders") or []) + [
        e.get("folder") for e in pdfs.values() if e.get("folder")
    ]
    for folder in tag_sync._with_parents(folders):
        key = tag_sync.folder_tag(folder).casefold()
        labels[key] = folder.rsplit("/", 1)[-1]
        folder_tags[key] = folder
    for safe, entry in prefs.items():
        if isinstance(entry, dict) and entry.get("tag"):
            key = entry["tag"].casefold()
            display = (pdfs.get(safe) or {}).get("display") or safe
            labels[key] = tag_sync.strip_pdf_ext(display).strip() or safe
            safes[key] = safe
    return {"labels": labels, "safes": safes, "folders": folder_tags}


def build_labels(drive: dict, prefs: dict) -> dict[str, str]:
    return build_index(drive, prefs)["labels"]


def library_index() -> dict:
    """``build_index`` from disk, re-read only when drive.json or the
    prefs (stored tags) changed — this is called once per painted row."""
    from . import curation, drive_store, retention

    paths = (drive_store._drive_path(curation.USER_FILES), retention._prefs_path())
    key = tuple(os.stat(p).st_mtime_ns if os.path.exists(p) else 0 for p in paths)
    if key != _cache["key"]:
        _cache["index"] = build_index(drive_store.load(curation.USER_FILES), retention._load_prefs())
        _cache["key"] = key
    return _cache["index"]


def library_labels() -> dict[str, str]:
    return library_index()["labels"]


def tag_means(note_tags: dict, card_r: dict) -> dict[str, float]:
    """``{tag casefolded: mean recall}``. A note's studied cards count
    once toward each of its tags AND each of their parents (a note
    tagged A::B and A::C counts once in A). Pure."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for nid, tags in note_tags.items():
        rs = [r for r, is_new in card_r.get(nid, ()) if not is_new]
        if not rs:
            continue
        keys = set()
        for tag in (tags or "").split():
            parts = tag.split("::")
            for i in range(1, len(parts) + 1):
                keys.add("::".join(parts[:i]).casefold())
        total = sum(rs)
        for key in keys:
            sums[key] = sums.get(key, 0.0) + total
            counts[key] = counts.get(key, 0) + len(rs)
    return {k: sums[k] / counts[k] for k in sums}


def compute_means(col) -> dict[str, float]:
    """The collection-wide pass behind every row's %. Runs in a QueryOp."""
    from . import retention

    note_tags = {int(nid): tags for nid, tags in col.db.all("select id, tags from notes")}
    return tag_means(note_tags, retention.card_retrievability(col, set(note_tags)))


def percent_text(means: dict | None, tag: str) -> str | None:
    """What the row shows; None while nothing is computed yet."""
    if means is None:
        return None
    mean = means.get(tag.casefold())
    return "—" if mean is None else f"{round(mean * 100)}%"


_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
# Black outline SVGs, the same kind Anki's own sidebar icons are: Anki
# inverts a plain-path icon in night mode, so one file serves both.
ROOT_ICON = os.path.join(_WEB, "library-root.svg")
FOLDER_ICON = os.path.join(_WEB, "library-folder.svg")
PDF_ICON = os.path.join(_WEB, "library-pdf.svg")


def _kind(item) -> str:
    return getattr(getattr(item, "item_type", None), "name", "")


def split_library_section(root, safes: dict, folders: dict | None = None) -> object | None:
    """Move the ``!Library`` tag branch out of Anki's Tags section into a
    section of its own at the top of the sidebar, with library, folder
    and PDF icons. Its rows stay Anki TAG items, so Anki's own rename,
    drag, delete and search keep working on them. Pure over the item
    objects (``children``, ``_parent_item``, ``full_name``, ``icon``);
    returns the Library item, or None when there is no Library yet."""
    folders = folders or {}
    tags_root = next((c for c in reversed(root.children) if _kind(c) == "TAG_ROOT"), None)
    if tags_root is None:
        return None
    lib = next((c for c in tags_root.children if c.full_name.casefold() == ROOT_TAG.casefold()), None)
    if lib is None:
        return None
    tags_root.children.remove(lib)
    lib._parent_item = root
    root.children.insert(0, lib)
    lib.icon = ROOT_ICON

    def mark(item) -> None:
        for child in item.children:
            key = child.full_name.casefold()
            # A row with nothing under it is a PDF unless it is a known
            # (empty) folder; a PDF's link to its tag can lag a rename.
            is_folder = key not in safes and (key in folders or bool(child.children))
            child.icon = FOLDER_ICON if is_folder else PDF_ICON
            mark(child)

    mark(lib)
    return lib


def wrap_sidebar(sidebar) -> None:
    """Two per-instance wraps on Anki's SidebarTreeView (once each):

    - ``_root_tree``: after EVERY stage has been built — Anki's own tags
      and any add-on's (AnkiHub builds the Tags section itself and does
      not check whether someone already did, so building it here too
      showed two Tags sections) — lift the Library into its own section.
    - ``remove_tags``: tell tag_sync which tags the USER is deleting, the
      one signal that may turn a vanished tag into "delete the PDF too?".

    Private names: if Anki renames them the wrap is skipped and the
    Library simply stays inside Tags, and no delete prompt ever shows."""
    if getattr(sidebar, "_klausmate_wrapped", False):
        return
    sidebar._klausmate_wrapped = True
    build = getattr(sidebar, "_root_tree", None)
    if build is not None:
        def root_tree():
            root = build()
            try:
                lib = library_index()
                split_library_section(root, lib["safes"], lib["folders"])
            except Exception as exc:  # noqa: BLE001 - the tree is built; only the move failed
                print(f"[klausmate] library section: split failed: {exc}")
            return root

        sidebar._root_tree = root_tree
    remove = getattr(sidebar, "remove_tags", None)
    if remove is not None:
        def remove_tags(item):
            try:
                tag_sync.note_user_deleted(sidebar._selected_tags())
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] library: could not note a tag delete: {exc}")
            return remove(item)

        sidebar.remove_tags = remove_tags


NOT_EMBEDDED = "Not in the search index yet. Right-click › Re-embed."
STALE = "Needs re-embedding: the embedding model or the file changed. Right-click › Re-embed."
INDEXING = "Indexing…"


def pdf_status(safes, pending: set, index_status: Callable) -> dict[str, str]:
    """``{safe: reason}`` for PDFs that need attention. Pure: the caller
    passes ``index_status(safe) -> (indexed, stale)``. A failed index
    run is not here: the runner reports failures without a PDF name."""
    out: dict[str, str] = {}
    for safe in safes:
        if safe in pending:
            out[safe] = INDEXING
            continue
        indexed, stale = index_status(safe)
        if not indexed:
            out[safe] = NOT_EMBEDDED
        elif stale:
            out[safe] = STALE
    return out


def label_for(tag: str | None) -> str | None:
    if not tag or not tag.casefold().startswith(ROOT_TAG.casefold()):
        return None
    try:
        return library_labels().get(tag.casefold())
    except Exception as exc:  # noqa: BLE001 - a label is never worth a broken sidebar
        print(f"[klausmate] library sidebar labels failed: {exc}")
        return None


# ------------------------------------------------------------ aqt glue

import weakref  # noqa: E402

from aqt import gui_hooks, mw  # noqa: E402
from aqt.operations import QueryOp  # noqa: E402
from aqt.qt import (  # noqa: E402
    QColor,
    QEvent,
    QObject,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    Qt,
    QTimer,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

PCT_GAP = 8  # px between the name and the %, and after the %

_state: dict = {"means": None, "busy": False, "again": False, "timer": None, "status": {}}
_sidebars: "weakref.WeakSet" = weakref.WeakSet()


def _is_tag(item) -> bool:
    return getattr(getattr(item, "item_type", None), "name", "") == "TAG"


class LibraryNameDelegate(QStyledItemDelegate):
    """Anki's sidebar has no delegate of its own, so this replaces the
    default one. It changes two things: a Library row's drawn name, and
    a right-aligned retention % on every tag row."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt override
        super().initStyleOption(option, index)
        try:
            name = getattr(index.internalPointer(), "full_name", None)
            label = label_for(name)
            if label:
                option.text = label
                reason = status_for(name)
                if reason and option.widget is not None:
                    icon = (
                        QStyle.StandardPixmap.SP_BrowserReload if reason == INDEXING
                        else QStyle.StandardPixmap.SP_MessageBoxWarning
                    )
                    option.icon = option.widget.style().standardIcon(icon)
                    option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] library sidebar paint failed: {exc}")

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802 - Qt override
        try:
            name = getattr(index.internalPointer(), "full_name", None)
            reason = status_for(name)
            if event.type() == QEvent.Type.ToolTip and reason:
                QToolTip.showText(event.globalPos(), f"{label_for(name)}\n{reason}", view)
                return True
        except Exception:  # noqa: BLE001
            pass
        return super().helpEvent(event, view, option, index)

    def paint(self, painter, option, index) -> None:
        try:
            item = index.internalPointer()
            text = percent_text(_state["means"], item.full_name) if _is_tag(item) else None
        except Exception:  # noqa: BLE001
            text = None
        if not text:
            super().paint(painter, option, index)
            return
        width = option.fontMetrics.horizontalAdvance(text) + 2 * PCT_GAP
        # The selection/hover band spans the whole row; only the NAME
        # gives up room, so a long name elides before it reaches the %.
        full = QStyleOptionViewItem(option)
        self.initStyleOption(full, index)
        full.text = ""
        full.icon = type(full.icon)()
        style = option.widget.style() if option.widget is not None else None
        if style is not None:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, full, painter, option.widget)
        narrow = QStyleOptionViewItem(option)
        narrow.rect = option.rect.adjusted(0, 0, -width, 0)
        super().paint(painter, narrow, index)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            # Muted grey on the selection band is unreadable: the band's
            # own text colour, slightly dimmed, stays secondary. With
            # Klaus's sidebar sheet the band is a light tint and the text
            # the theme's; without it, Qt's blue band and its white text.
            styled = option.widget is not None and bool(option.widget.styleSheet())
            try:
                from . import theme

                color = QColor(theme.palette(theme.night_mode())["text"]) if styled else QColor(
                    option.palette.highlightedText().color()
                )
            except Exception:  # noqa: BLE001
                color = QColor(option.palette.highlightedText().color())
            color.setAlphaF(0.75)
        else:
            try:
                from . import theme

                color = QColor(theme.palette(theme.night_mode())["text_muted"])
            except Exception:  # noqa: BLE001
                color = QColor(option.palette.text().color())
                color.setAlphaF(0.5)
        painter.setPen(color)
        painter.drawText(
            option.rect.adjusted(0, 0, -PCT_GAP, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.restore()


def _repaint() -> None:
    for sidebar in list(_sidebars):
        try:
            sidebar.viewport().update()
        except Exception:  # noqa: BLE001 - a closed Browse is not an error
            pass


def refresh_retention() -> None:
    """Recompute every tag's % in the background; a request made while
    one runs is folded into one more pass afterwards."""
    if _state["busy"]:
        _state["again"] = True
        return
    if not _sidebars or mw is None or getattr(mw, "col", None) is None:
        _state["means"] = None  # stale by the next open; recomputed then
        return
    _state["busy"] = True

    def done(means: dict) -> None:
        _state["busy"] = False
        _state["means"] = means
        _repaint()
        if _state["again"]:
            _state["again"] = False
            refresh_retention()

    def failed(exc: Exception) -> None:
        _state["busy"] = False
        print(f"[klausmate] tag retention failed: {exc}")

    QueryOp(parent=mw, op=compute_means, success=done).failure(failed).run_in_background()


def _schedule_refresh() -> None:
    """Debounced: reviewing or editing fires many ops."""
    try:
        if _state["timer"] is None:
            timer = QTimer(mw)
            timer.setSingleShot(True)
            timer.setInterval(1500)
            timer.timeout.connect(refresh_retention)
            _state["timer"] = timer
        _state["timer"].start()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tag retention schedule failed: {exc}")


def status_for(tag: str | None) -> str | None:
    if not tag:
        return None
    safe = library_index()["safes"].get(tag.casefold())
    return _state["status"].get(safe) if safe else None


def refresh_status() -> None:
    """Which PDFs get a warning icon. Reads index manifests only (no card
    index), on the main thread: a few dozen small JSON files."""
    if not _sidebars:
        return  # recomputed when Browse opens
    try:
        from . import embeddings, index_queue, retention

        sig = embeddings.index_signature(retention._cfg())
        _state["status"] = pdf_status(
            set(library_index()["safes"].values()),
            index_queue.pending_names(),
            lambda safe: retention.index_status(safe, sig),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library status failed: {exc}")
    _repaint()


# ------------------------------------------------------------ menus


def _add(menu, text: str, fn: Callable) -> None:
    menu.addAction(text).triggered.connect(lambda *_a: fn())


def on_context_menu(sidebar, menu, item, index) -> None:
    """``browser_sidebar_will_show_context_menu``: Klaus's section below
    Anki's own tag items."""
    if not _is_tag(item):
        return
    from . import library_actions as act

    key = item.full_name.casefold()
    lib = library_index()
    parent = getattr(sidebar, "browser", None) or sidebar
    if key == ROOT_TAG.casefold():
        menu.addSeparator()
        _add(menu, "Import PDFs…", lambda: act.pick_and_import(parent))
        _add(menu, "New Folder…", lambda: act.new_folder(parent))
    elif key in lib["safes"]:
        safe = lib["safes"][key]
        # K-316: opening is a double-click, rename and delete are Anki's
        # own items above (tag_sync follows them), and PDFs embed
        # themselves — only what nothing else does is left here.
        menu.addSeparator()
        _add(menu, "Match Sensitivity…", lambda: act.sensitivity(parent, safe))
        _add(menu, "Retention History…", lambda: act.history(parent, safe))
        _add(menu, "Show in Finder", lambda: act.show_in_finder(safe))
    elif key in lib["folders"]:
        folder = lib["folders"][key]
        menu.addSeparator()
        _add(menu, "New Folder…", lambda: act.new_folder(parent, folder))
        _add(menu, "Import PDFs Here…", lambda: act.pick_and_import(parent, folder))
        if not act.pdfs_under(folder):  # Anki's own rename and delete skip a tag with no cards
            _add(menu, "Rename Folder…", lambda: act.rename_folder(parent, folder))
            _add(menu, "Remove Folder", lambda: act.remove_empty_folder(folder))


# ------------------------------------------------------------ click, drop, footer


def _on_clicked(browser, index) -> None:
    """One click: Anki's own search fills the table with the row's cards
    (a PDF's matched cards), and viewer mode, if on, steps aside."""
    try:
        from . import library_viewer

        library_viewer.on_sidebar_click(browser)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library click failed: {exc}")


def _on_double_clicked(browser, index) -> None:
    """Two clicks on a PDF: the PDF viewer takes the cards' place."""
    try:
        safe = library_index()["safes"].get(index.internalPointer().full_name.casefold())
        if safe:
            from . import library_viewer

            library_viewer.enter(browser, safe)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library double-click failed: {exc}")


def pdf_paths(mime) -> list[str]:
    try:
        if mime is None or not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]
    except Exception:  # noqa: BLE001
        return []


class PdfDropFilter(QObject):
    """PDF files dropped anywhere on the sidebar are imported into the
    Library root. Every other drag (Anki's own tag and deck moves) is
    left alone."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        kind = event.type()
        if kind not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        paths = pdf_paths(event.mimeData())
        if not paths:
            return False
        event.acceptProposedAction()
        if kind == QEvent.Type.Drop:
            from . import library_actions

            library_actions.import_files(paths)
        return True


class Footer(QWidget):
    """Under the sidebar tree: the Import PDFs… button. Indexing progress
    shows in the status bar (``status_bar``), not here."""

    def __init__(self, browser) -> None:
        super().__init__()
        self.setObjectName("klausmateLibraryFooter")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 8, 6)
        self.button = QPushButton("Import PDFs…", self)
        lay.addWidget(self.button)
        from . import library_actions

        self.button.clicked.connect(lambda *_a: library_actions.pick_and_import(browser))


def _on_index_state(state) -> None:
    """A PDF finished indexing (or the runner went idle): its warning
    icon may be stale."""
    if state.finished or not state.active:
        refresh_status()


def _install_footer(browser, sidebar) -> None:
    if getattr(browser, "_klausmate_library_footer", None) is not None:
        return
    grid = browser.sidebarDockWidget.widget().layout()
    footer = Footer(browser)
    grid.addWidget(footer, grid.rowCount(), 0, 1, 2)
    browser._klausmate_library_footer = footer
    drops = PdfDropFilter(sidebar)
    sidebar.viewport().installEventFilter(drops)
    footer.setAcceptDrops(True)
    footer.installEventFilter(drops)
    sidebar._klausmate_drops = drops


def on_operation_did_execute(changes, handler) -> None:
    if not _sidebars:
        return  # no Browse open: recompute when one opens
    if any(getattr(changes, k, False) for k in ("card", "note", "tag", "study_queues")):
        _schedule_refresh()


def on_browser_will_show(browser) -> None:
    try:
        sidebar = browser.sidebar
        if not isinstance(sidebar.itemDelegate(), LibraryNameDelegate):
            sidebar.setItemDelegate(LibraryNameDelegate(sidebar))
        wrap_sidebar(sidebar)
        if not getattr(sidebar, "_klausmate_clicks", False):
            sidebar.clicked.connect(lambda index: _on_clicked(browser, index))
            sidebar.doubleClicked.connect(lambda index: _on_double_clicked(browser, index))
            sidebar._klausmate_clicks = True
        _sidebars.add(sidebar)
        refresh_status()
        refresh_retention()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library sidebar install failed: {exc}")
    try:
        _install_footer(browser, browser.sidebar)
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library sidebar footer failed: {exc}")


def on_profile_will_close() -> None:
    _state["means"] = None  # the next profile's collection is another one


def setup() -> None:
    from . import index_queue

    index_queue.add_listener(_on_index_state)
    gui_hooks.browser_will_show.append(on_browser_will_show)
    gui_hooks.operation_did_execute.append(on_operation_did_execute)
    gui_hooks.profile_will_close.append(on_profile_will_close)
    gui_hooks.browser_sidebar_will_show_context_menu.append(on_context_menu)
