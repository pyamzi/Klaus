"""Byte-range source for the pdf.js reader (PDF reader 2/5).

The page asks for ranges of the open PDF on demand. The file is opened per
call and closed again: Windows refuses ``os.replace`` onto a path with an
open handle, and the add-on bakes annotations that way. A fingerprint
``(inode, mtime_ns, size)`` is captured at load; a read of a file that no
longer matches it raises ``StaleSource`` so the page can reload.

With a ``snapshot_dir`` the source hard-links the file there at load and
reads the link (ruling R20): Klaus's own bakes ``os.replace`` the library
file onto a new inode and leave the snapshot untouched, while an outside
in-place rewrite changes the shared inode and still reads stale. Where a
hard link is impossible the live path is read, as without a snapshot.
"""
from __future__ import annotations

import base64
import os
import uuid

from . import pdf_handler

FIRST_CHUNK = 262144
MAX_RANGE = 1048576


def user_files_dir() -> str:
    """The add-on's user-files folder (Ruling R25, amended): the settings
    seam's ``settings.user_files()`` where that module exists (tests point
    it at scratch), else the package's ``USER_FILES``."""
    try:
        from . import settings

        return settings.user_files()
    except ImportError:
        from . import USER_FILES

        return USER_FILES


class StaleSource(Exception):
    """The file was replaced, truncated, deleted or is unreadable."""


class DocSource:
    def __init__(self, path: str, snapshot_dir: str | None = None):
        self.path = path
        self.read_path = path
        self._link: str | None = None
        if snapshot_dir is not None:
            try:
                os.makedirs(snapshot_dir, exist_ok=True)
                link = os.path.join(snapshot_dir, uuid.uuid4().hex + ".pdf")
                os.link(path, link)
                self._link = self.read_path = link
            except OSError:
                pass  # other volume, no hard links, permission: read live
        stat = pdf_handler.file_stat(self.read_path)
        if stat is None:
            self.close()
            raise StaleSource(path)
        self.stat = stat
        self.length = stat[2]

    def read(self, begin: int, end: int) -> bytes:
        begin = max(0, min(begin, self.length))
        end = max(begin, min(end, self.length, begin + MAX_RANGE))
        try:
            with open(self.read_path, "rb") as f:
                st = os.fstat(f.fileno())
                if (st.st_ino, st.st_mtime_ns, st.st_size) != self.stat:
                    raise StaleSource(self.path)
                f.seek(begin)
                return f.read(end - begin)
        except OSError as e:
            raise StaleSource(str(e)) from e

    def close(self) -> None:
        """Remove the snapshot link, if one was made. Idempotent."""
        link, self._link = self._link, None
        if link is not None:
            try:
                os.remove(link)
            except OSError:
                pass


def sweep_snapshots(snapshot_dir: str, keep: set[str] = frozenset()) -> None:
    """Remove leftover ``*.pdf`` snapshot links whose path is not in *keep*."""
    try:
        names = os.listdir(snapshot_dir)
    except OSError:
        return
    for n in names:
        p = os.path.join(snapshot_dir, n)
        if n.endswith(".pdf") and p not in keep:
            try:
                os.remove(p)
            except OSError:
                pass


def range_reply(source, gen: int, current_gen: int, begin: int, end: int) -> dict:
    """JSON-serialisable answer for one bridge range request."""
    if gen != current_gen:
        return {"refused": True}
    if source is None:
        return {"stale": True}
    try:
        data = source.read(begin, end)
    except StaleSource:
        return {"stale": True}
    return {"b64": base64.b64encode(data).decode("ascii")}
