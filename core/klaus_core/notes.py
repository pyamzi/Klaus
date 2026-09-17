"""Per-PDF notes and pasted-image assets, in KlausBook's own data dir.

Notes are one JSON document per PDF (keyed by the library's pdf id) with
per-page markdown. Assets are content-addressed image files. Nothing here
touches the klausmate library — that stays read-only. Ids and asset names
are regex-validated so a crafted id can never escape the data dir.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ASSET_RE = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")
_ASSET_EXTS = ("png", "jpg", "gif", "webp")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def data_dir() -> Path:
    override = os.environ.get("KLAUS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library/Application Support/Klausbook"


def _require_id(pdf_id: str) -> str:
    if not _ID_RE.match(pdf_id or ""):
        raise ValueError("bad pdf id: %r" % (pdf_id,))
    return pdf_id


def _notes_path(pdf_id: str) -> Path:
    return data_dir() / "notes" / (_require_id(pdf_id) + ".json")


def load_notes(pdf_id: str) -> dict:
    try:
        with open(_notes_path(pdf_id), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"version": 1, "pages": {}}


def save_notes(pdf_id: str, doc: dict) -> None:
    if not isinstance(doc, dict) or not isinstance(doc.get("pages"), dict):
        raise ValueError("notes doc must be a dict with a 'pages' dict")
    if doc.get("version") != 1:
        raise ValueError("notes doc version must be 1")
    for key, page in doc["pages"].items():
        if not (isinstance(key, str) and key.isdigit() and int(key) >= 1):
            raise ValueError("page keys must be 1-based numeric strings: %r" % (key,))
        if not isinstance(page, dict) or not isinstance(page.get("md"), str):
            raise ValueError("page %s must be {'md': <str>}" % key)
    if doc.get("highlights") is not None:
        _validate_highlights(doc["highlights"])
    path = _notes_path(pdf_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _validate_highlights(highlights) -> None:
    if not isinstance(highlights, dict):
        raise ValueError("highlights must be a dict keyed by page")
    for key, items in highlights.items():
        if not (isinstance(key, str) and key.isdigit() and int(key) >= 1):
            raise ValueError("highlight page keys must be 1-based numeric strings: %r" % (key,))
        if not isinstance(items, list):
            raise ValueError("highlights for page %s must be a list" % key)
        for h in items:
            if not isinstance(h, dict):
                raise ValueError("each highlight must be a dict")
            if not (isinstance(h.get("id"), str) and h["id"]):
                raise ValueError("highlight id must be a non-empty string")
            if not (isinstance(h.get("color"), str) and _HEX_RE.match(h["color"])):
                raise ValueError("highlight color must be #rrggbb")
            rects = h.get("rects")
            if not (isinstance(rects, list) and rects):
                raise ValueError("highlight rects must be a non-empty list")
            for r in rects:
                if not (isinstance(r, list) and len(r) == 4 and all(
                        isinstance(v, (int, float)) and not isinstance(v, bool) for v in r)):
                    raise ValueError("each rect must be [x, y, w, h] numbers")


def save_asset(pdf_id: str, data: bytes, ext: str) -> str:
    if ext not in _ASSET_EXTS:
        raise ValueError("bad asset extension: %r" % (ext,))
    name = hashlib.sha1(data).hexdigest()[:16] + "." + ext
    root = data_dir() / "assets" / _require_id(pdf_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if not path.exists():
        path.write_bytes(data)
    return name


def asset_path(pdf_id: str, name: str) -> Optional[Path]:
    if not _ASSET_RE.match(name or ""):
        return None
    path = data_dir() / "assets" / _require_id(pdf_id) / name
    return path if path.is_file() else None
