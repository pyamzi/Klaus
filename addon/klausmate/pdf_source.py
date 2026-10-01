"""Byte-range source for the pdf.js reader (PDF reader 2/5).

The page asks for ranges of the open PDF on demand. The file is opened per
call and closed again: Windows refuses ``os.replace`` onto a path with an
open handle, and the add-on bakes annotations that way. A fingerprint
``(inode, mtime_ns, size)`` is captured at load; a read of a file that no
longer matches it raises ``StaleSource`` so the page can reload.
"""
from __future__ import annotations

import base64
import os

from . import pdf_handler

FIRST_CHUNK = 262144
MAX_RANGE = 1048576


class StaleSource(Exception):
    """The file was replaced, truncated, deleted or is unreadable."""


class DocSource:
    def __init__(self, path: str):
        stat = pdf_handler.file_stat(path)
        if stat is None:
            raise StaleSource(path)
        self.path = path
        self.stat = stat
        self.length = stat[2]

    def read(self, begin: int, end: int) -> bytes:
        begin = max(0, min(begin, self.length))
        end = max(begin, min(end, self.length, begin + MAX_RANGE))
        try:
            with open(self.path, "rb") as f:
                st = os.fstat(f.fileno())
                if (st.st_ino, st.st_mtime_ns, st.st_size) != self.stat:
                    raise StaleSource(self.path)
                f.seek(begin)
                return f.read(end - begin)
        except OSError as e:
            raise StaleSource(str(e)) from e


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
