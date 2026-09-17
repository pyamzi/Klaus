"""Virtual folder layer + display names for the PDF drive.

Pure stdlib, no aqt/Qt — headlessly testable. All state in one file,
``user_files/drive.json``. Folders are VIRTUAL: nothing on disk moves, the
flat safe-basename storage stays exactly as it is; this module is a pure
presentation join over ``pdf_handler.list_contexts`` output.

Also the home of the drive window's saved geometry — deliberately NOT in
``pdf_tabs.json``, whose ``placement``/``geom`` keys belong to the editor's
PDF panel.

Schema (version 1)::

    {
      "version": 1,
      "folders": ["Anatomy", "Anatomy/Week 3"],
      "pdfs": {"<safe>": {"folder": "Anatomy/Week 3",
                           "display": "Renal Physiology (Dr. K).pdf"}},
      "window": {"x": 120, "y": 80, "w": 1100, "h": 720,
                  "splitter": [280, 800]}
    }

Orphan rules: a stored PDF with no ``pdfs`` entry shows at the root under
its safe name; a ``pdfs`` entry whose files are gone is skipped by
``build_tree`` and pruned lazily on the next save; a folder referenced by a
pdf but missing from ``folders`` is implicitly part of the tree.
"""

from __future__ import annotations

import json
import os

DRIVE_FILE = "drive.json"
DRIVE_VERSION = 1


def _drive_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, DRIVE_FILE)


def _default() -> dict:
    return {"version": DRIVE_VERSION, "folders": [], "pdfs": {}, "window": {}}


def load(user_files_dir: str) -> dict:
    """The drive state, default-shaped on any error or version mismatch."""
    try:
        with open(_drive_path(user_files_dir), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != DRIVE_VERSION:
            return _default()
        out = _default()
        folders = data.get("folders")
        if isinstance(folders, list):
            out["folders"] = [str(p) for p in folders if _valid_folder(str(p))]
        pdfs = data.get("pdfs")
        if isinstance(pdfs, dict):
            for safe, entry in pdfs.items():
                if not isinstance(entry, dict):
                    continue
                folder = entry.get("folder")
                out["pdfs"][str(safe)] = {
                    "folder": str(folder) if folder else None,
                    "display": str(entry.get("display") or safe),
                }
        window = data.get("window")
        if isinstance(window, dict):
            out["window"] = window
        return out
    except (OSError, ValueError, json.JSONDecodeError):
        return _default()


def _save(user_files_dir: str, data: dict) -> None:
    """Atomic write (tmp + os.replace)."""
    path = _drive_path(user_files_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def _valid_folder(path: str) -> bool:
    if not path or path != path.strip():
        return False
    parts = path.split("/")
    return all(p.strip() and p == p.strip() for p in parts)


# ------------------------------------------------------------- mutations


def record_import(user_files_dir: str, safe: str, display: str) -> None:
    """Remember the original filename at import; keep any existing folder."""
    data = load(user_files_dir)
    entry = data["pdfs"].get(safe) or {"folder": None, "display": safe}
    entry["display"] = display or safe
    data["pdfs"][safe] = entry
    _save(user_files_dir, data)


def set_folder(user_files_dir: str, safe: str, folder: str | None) -> None:
    data = load(user_files_dir)
    entry = data["pdfs"].get(safe) or {"folder": None, "display": safe}
    entry["folder"] = folder if folder and _valid_folder(folder) else None
    data["pdfs"][safe] = entry
    if entry["folder"] and entry["folder"] not in data["folders"]:
        data["folders"].append(entry["folder"])
    _save(user_files_dir, data)


def rename_display(user_files_dir: str, safe: str, display: str) -> None:
    display = (display or "").strip()
    if not display:
        return
    data = load(user_files_dir)
    entry = data["pdfs"].get(safe) or {"folder": None, "display": safe}
    entry["display"] = display
    data["pdfs"][safe] = entry
    _save(user_files_dir, data)


def add_folder(user_files_dir: str, path: str) -> bool:
    path = (path or "").strip().strip("/")
    if not _valid_folder(path):
        return False
    data = load(user_files_dir)
    if path in data["folders"]:
        return True
    data["folders"].append(path)
    data["folders"].sort()
    _save(user_files_dir, data)
    return True


def rename_folder(user_files_dir: str, old: str, new: str) -> bool:
    """Rename a folder path, rewriting the prefix on subfolders and pdfs."""
    new = (new or "").strip().strip("/")
    if not _valid_folder(new) or not old:
        return False
    data = load(user_files_dir)

    def swap(p: str) -> str:
        if p == old:
            return new
        if p.startswith(old + "/"):
            return new + p[len(old):]
        return p

    data["folders"] = sorted({swap(p) for p in data["folders"]} | {new})
    for entry in data["pdfs"].values():
        if entry.get("folder"):
            entry["folder"] = swap(entry["folder"])
    _save(user_files_dir, data)
    return True


def remove_folder(user_files_dir: str, path: str) -> None:
    """Drop a folder; its PDFs and subfolders reparent to the parent."""
    data = load(user_files_dir)
    parent = path.rsplit("/", 1)[0] if "/" in path else None

    def reparent(p: str | None) -> str | None:
        if p is None:
            return None
        if p == path:
            return parent
        if p.startswith(path + "/"):
            rest = p[len(path) + 1:]
            return f"{parent}/{rest}" if parent else rest
        return p

    data["folders"] = sorted(
        {q for q in (reparent(p) for p in data["folders"]) if q}
    )
    for entry in data["pdfs"].values():
        entry["folder"] = reparent(entry.get("folder"))
    _save(user_files_dir, data)


def remove_pdf(user_files_dir: str, safe: str) -> None:
    data = load(user_files_dir)
    if safe in data["pdfs"]:
        del data["pdfs"][safe]
        _save(user_files_dir, data)


# --------------------------------------------------------------- window


def get_window_state(user_files_dir: str) -> dict:
    return load(user_files_dir).get("window") or {}


def save_window_state(user_files_dir: str, geom: dict) -> None:
    data = load(user_files_dir)
    data["window"] = dict(geom or {})
    _save(user_files_dir, data)


# ----------------------------------------------------------------- tree


def display_name(user_files_dir: str, safe: str) -> str:
    entry = load(user_files_dir)["pdfs"].get(safe)
    return entry["display"] if entry else safe


def build_tree(context_names: list[str], data: dict) -> dict:
    """Pure join of stored PDFs and the folder map.

    ``context_names`` come from ``pdf_handler.list_contexts`` (``<safe>.txt``
    filenames). Returns ``{"folders": {path: [pdf, ...]}, "root": [pdf,
    ...]}`` where each pdf is ``{"safe", "display", "folder"}``, folders
    sorted, pdfs sorted by display name. Every folder known to ``data`` or
    referenced by a pdf appears, even when empty.
    """
    pdfs_meta = data.get("pdfs") or {}
    folders: dict[str, list[dict]] = {
        p: [] for p in (data.get("folders") or []) if _valid_folder(p)
    }
    root: list[dict] = []
    for fname in context_names:
        safe = fname[:-4] if fname.endswith(".txt") else fname
        entry = pdfs_meta.get(safe) or {}
        folder = entry.get("folder")
        if folder and not _valid_folder(folder):
            folder = None
        pdf = {
            "safe": safe,
            "display": entry.get("display") or safe,
            "folder": folder,
        }
        if folder:
            folders.setdefault(folder, []).append(pdf)
        else:
            root.append(pdf)
    for items in folders.values():
        items.sort(key=lambda p: p["display"].lower())
    root.sort(key=lambda p: p["display"].lower())
    return {"folders": dict(sorted(folders.items())), "root": root}


def retention_level(fraction: float) -> str:
    """Bucket a retention fraction: ``"low"`` < 0.70 <= ``"mid"`` < 0.85
    <= ``"high"``.

    Replaces the K-117 HSV hue ramp (K-127): a continuous red->green
    sweep gave every row its own arbitrary tertiary hue — 59% rendered
    chartreuse — with no meaning attached to any of them. Three semantic
    levels instead: FSRS desired retention sits around 0.9, so >= 0.85
    reads "at target" (high), < 0.70 is genuinely poor (low), and the
    wide middle band is simply fine — the caller gives it no ink at all.

    Deliberately returns a level name, never a colour, so this stays
    aqt-free/Qt-free and headlessly testable; the theme-token mapping
    lives with the one consumer (pdf_drive._set_retention_color).
    Out-of-range values clamp into [0, 1] exactly like the old ramp;
    non-numeric input raises like ``float()`` does, into that caller's
    guard.
    """
    frac = max(0.0, min(1.0, float(fraction)))
    if frac < 0.70:
        return "low"
    if frac < 0.85:
        return "mid"
    return "high"
