"""Read-only view over the klausmate PDF library.

Milestone 1 points at the existing klausmate user_files and NEVER writes
there. klausmate keeps a pristine copy of every PDF in pdf_originals/ and a
baked copy (annotations written into the file) in pdfs/; when a base name
exists in both, the baked copy is the one the user expects to see. Ids are
derived from the filename so they stay stable across restarts without any
state on disk.
"""

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_USER_FILES = Path.home() / "Documents/Github/KlausMate-Context/klausmate/user_files"


def _roots() -> List[Path]:
    override = os.environ.get("KLAUS_LIBRARY_DIR")
    if override:
        return [Path(override).expanduser()]
    base = DEFAULT_USER_FILES
    # Order matters: baked pdfs/ shadows pristine pdf_originals/.
    return [base / "pdfs", base / "pdf_originals"]


def _pdf_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]


def _scan(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.iterdir()
        if p.suffix.lower() == ".pdf" and not p.name.startswith(".")
    )


def list_pdfs() -> List[Dict]:
    seen: Dict[str, Path] = {}
    for root in _roots():
        for path in _scan(root):
            seen.setdefault(path.name, path)
    items = []
    for name in sorted(seen):
        path = seen[name]
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "id": _pdf_id(name),
                "name": name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return items


def library_dirs() -> List[str]:
    return [str(root) for root in _roots()]


def pdf_path(pdf_id: str) -> Optional[Path]:
    for root in _roots():
        for path in _scan(root):
            if _pdf_id(path.name) == pdf_id:
                return path
    return None
