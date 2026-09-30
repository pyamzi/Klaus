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
counting its children's cards, new and suspended cards left out ("—"
when nothing is studied). Computed in a background op over the whole
collection and repainted when it lands.

aqt-free above the "aqt glue" divider.
"""
from __future__ import annotations

import os

from . import tag_sync

ROOT_TAG = "!Library"
ROOT_LABEL = "Library"

_cache: dict = {"key": None, "labels": {}}


def build_labels(drive: dict, prefs: dict) -> dict[str, str]:
    """``{tag casefolded: the name to show}`` for the Library root,
    every folder, and every PDF that owns a tag. Pure."""
    labels = {ROOT_TAG.casefold(): ROOT_LABEL}
    pdfs = drive.get("pdfs") or {}
    folders = list(drive.get("folders") or []) + [
        e.get("folder") for e in pdfs.values() if e.get("folder")
    ]
    for folder in tag_sync._with_parents(folders):
        labels[tag_sync.folder_tag(folder).casefold()] = folder.rsplit("/", 1)[-1]
    for safe, entry in prefs.items():
        if isinstance(entry, dict) and entry.get("tag"):
            display = (pdfs.get(safe) or {}).get("display") or safe
            labels[entry["tag"].casefold()] = tag_sync.strip_pdf_ext(display).strip() or safe
    return labels


def library_labels() -> dict[str, str]:
    """``build_labels`` from disk, re-read only when drive.json or the
    prefs (stored tags) changed — this is called once per painted row."""
    from . import curation, drive_store, retention

    paths = (drive_store._drive_path(curation.USER_FILES), retention._prefs_path())
    key = tuple(os.stat(p).st_mtime_ns if os.path.exists(p) else 0 for p in paths)
    if key != _cache["key"]:
        _cache["labels"] = build_labels(drive_store.load(curation.USER_FILES), retention._load_prefs())
        _cache["key"] = key
    return _cache["labels"]


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
    return tag_means(note_tags, retention.card_retrievability(col, set(note_tags), skip_suspended=True))


def percent_text(means: dict | None, tag: str) -> str | None:
    """What the row shows; None while nothing is computed yet."""
    if means is None:
        return None
    mean = means.get(tag.casefold())
    return "—" if mean is None else f"{round(mean * 100)}%"


def label_for(tag: str | None) -> str | None:
    if not tag or not tag.startswith(ROOT_TAG):
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    Qt,
    QTimer,
)

PCT_GAP = 8  # px between the name and the %, and after the %

_state: dict = {"means": None, "busy": False, "again": False, "timer": None}
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
            label = label_for(getattr(index.internalPointer(), "full_name", None))
            if label:
                option.text = label
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] library sidebar paint failed: {exc}")

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
            # own text colour, slightly dimmed, stays secondary.
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
    if mw is None or getattr(mw, "col", None) is None:
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
        _sidebars.add(sidebar)
        refresh_retention()
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library sidebar install failed: {exc}")


def on_profile_will_close() -> None:
    _state["means"] = None  # the next profile's collection is another one


def setup() -> None:
    gui_hooks.browser_will_show.append(on_browser_will_show)
    gui_hooks.operation_did_execute.append(on_operation_did_execute)
    gui_hooks.profile_will_close.append(on_profile_will_close)
