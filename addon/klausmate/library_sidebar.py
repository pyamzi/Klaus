"""The Library in Browse's sidebar (K-307; spec
docs/superpowers/specs/2026-09-28-library-in-browse-design.md, Part 2).

First slice: real names. A tag cannot hold a space, so ``Intro_to_CBC``
is the tag's real name. The sidebar row now PAINTS the PDF's own name
("04-L-Intro to CBC"), a folder's own name ("Week 1") and "Library" for
the ``!Library`` root. Only the drawn text changes (``initStyleOption``):
the rename editor still opens on the tag name (EditRole), and search,
drag and delete still act on the tag.

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


def label_for(tag: str | None) -> str | None:
    if not tag or not tag.startswith(ROOT_TAG):
        return None
    try:
        return library_labels().get(tag.casefold())
    except Exception as exc:  # noqa: BLE001 - a label is never worth a broken sidebar
        print(f"[klausmate] library sidebar labels failed: {exc}")
        return None


# ------------------------------------------------------------ aqt glue

from aqt import gui_hooks  # noqa: E402
from aqt.qt import QStyledItemDelegate  # noqa: E402


class LibraryNameDelegate(QStyledItemDelegate):
    """Anki's sidebar has no delegate of its own, so this replaces the
    default one and differs only in the text it draws for Library rows."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt override
        super().initStyleOption(option, index)
        try:
            label = label_for(getattr(index.internalPointer(), "full_name", None))
            if label:
                option.text = label
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] library sidebar paint failed: {exc}")


def on_browser_will_show(browser) -> None:
    try:
        sidebar = browser.sidebar
        if not isinstance(sidebar.itemDelegate(), LibraryNameDelegate):
            sidebar.setItemDelegate(LibraryNameDelegate(sidebar))
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] library sidebar install failed: {exc}")


def setup() -> None:
    gui_hooks.browser_will_show.append(on_browser_will_show)
