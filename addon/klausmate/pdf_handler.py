"""PDF text extraction + lightweight retrieval.

Tries to use ``pypdf`` if it's been vendored into ``klausmate/vendor/``.
If not available, the PDF feature is disabled but the rest of the add-on
continues to work.

Retrieval (BM25): chunks of saved context files are scored against the
user's current field text, and the top-K most relevant chunks are returned.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any
import shutil
import sys
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).parent
_VENDOR = _HERE / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

try:
    import pypdf  # type: ignore

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Guarded separately from the plain ``pypdf`` import above: baking real
# PDF annotations needs the writer + annotation builders. If only these
# are missing, extraction still works and baking degrades to a no-op.
try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    from pypdf.annotations import (  # type: ignore
        FreeText as _BakeFreeText,
        Highlight as _BakeHighlight,
        Text as _BakeText,
    )
    from pypdf.generic import (  # type: ignore
        ArrayObject as _BakeArray,
        FloatObject as _BakeFloat,
        NameObject as _BakeName,
        TextStringObject as _BakeString,
    )

    BAKE_AVAILABLE = True
except Exception:
    BAKE_AVAILABLE = False

# Every annotation Klaus bakes carries this /NM (annotation name) prefix
# (K-077). It is how the foreign-annotation scan tells outside markup
# (Preview text boxes, highlights) from Klaus's own regenerated bakes.
_KLAUS_NM = "klausmate:"

_ACTIVE_PDF_FILE = "active_pdf.txt"


# ------------------------------- atomic writes ----------------------------
#
# Shared by every store below that can be written from more than one call
# site (pdf_tabs.json has four: open tabs, last_used, thumbs, panel
# placement) or that a background thread might touch concurrently with a
# read. A tmp file lives in the SAME directory as the target so
# ``os.replace`` is a same-filesystem rename: atomic, and safe even while
# something else still holds the old inode open (mirrors
# ``_atomic_replace_from`` below, which does the analogous thing for whole
# PDF files during bake/un-bake).
#
# Both helpers RAISE on failure rather than swallowing — callers decide
# whether a failed write should be silent (``_save_tabs_file`` keeps its
# long-standing best-effort contract) or surfaced (retention's
# save_matches/set_threshold let it propagate to the caller's QueryOp
# failure handler, same as before this helper existed).


def _atomic_write(path: str, write_fn) -> None:
    """Write to ``path`` atomically: ``write_fn(f)`` writes into an open
    tmp file in ``path``'s directory, which is then ``os.replace``'d onto
    ``path``. The tmp file is always cleaned up, success or failure."""
    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(
        dest_dir, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            write_fn(f)
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _atomic_write_json(path: str, obj, **json_kwargs) -> None:
    """Write ``obj`` as JSON to ``path`` atomically (tmp file + rename).

    ``**json_kwargs`` forwards to ``json.dump`` (e.g. ``separators=(",",
    ":")`` for a compact cache file).
    """
    _atomic_write(path, lambda f: json.dump(obj, f, **json_kwargs))


# ----------------------------- extraction --------------------------------


def extract_pages(path: str) -> list[str]:
    if not PDF_AVAILABLE:
        return []
    reader = pypdf.PdfReader(path)
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _safe_basename(name: str) -> str:
    base = name[:-4] if name.endswith(".txt") else name
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in base)


def _active_pdf_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, _ACTIVE_PDF_FILE)


def get_active_pdf(user_files_dir: str) -> str | None:
    """Return the canonical basename of the single active PDF, or None."""
    path = _active_pdf_path(user_files_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    if not name:
        return None
    base = _safe_basename(name)
    txt = os.path.join(user_files_dir, "contexts", base + ".txt")
    return base if os.path.isfile(txt) else None


def set_active_pdf(user_files_dir: str, name: str) -> None:
    base = _safe_basename(name)
    # Plain text (a bare basename), not JSON — routed through the same
    # tmp+replace primitive as _atomic_write_json rather than that helper
    # itself, so the on-disk format of this live user file doesn't change.
    _atomic_write(_active_pdf_path(user_files_dir), lambda f: f.write(base))


def clear_active_pdf(user_files_dir: str) -> None:
    path = _active_pdf_path(user_files_dir)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def ensure_active_pdf(user_files_dir: str) -> str | None:
    """Make sure the active-PDF pointer references a stored context.

    Multi-PDF model: several contexts coexist and nothing is ever deleted
    here (this replaced the old ``migrate_to_single_pdf``, which pruned
    the store down to one file). If the pointer is missing or stale,
    repoint it at the newest stored context.
    """
    names = list_contexts(user_files_dir)
    if not names:
        clear_active_pdf(user_files_dir)
        return None
    active = get_active_pdf(user_files_dir)
    if active and active + ".txt" in names:
        return active
    # Repair from the same recency ranking the ＋ menu uses (last_used,
    # falling back to ingest time) rather than an independent mtime scan —
    # otherwise the repointed pointer could disagree with what the menu
    # calls "most recent".
    ranked = list_by_recency(user_files_dir)
    if ranked:
        base = ranked[0]
    else:
        base = names[0][:-4] if names[0].endswith(".txt") else names[0]
    set_active_pdf(user_files_dir, base)
    return base


_OPEN_TABS_FILE = "pdf_tabs.json"


def _load_tabs_file(user_files_dir: str) -> dict:
    try:
        with open(
            os.path.join(user_files_dir, _OPEN_TABS_FILE), encoding="utf-8"
        ) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tabs_file(user_files_dir: str, updates: dict) -> None:
    data = _load_tabs_file(user_files_dir)
    data.update(updates)
    try:
        _atomic_write_json(
            os.path.join(user_files_dir, _OPEN_TABS_FILE), data
        )
    except Exception:
        pass


def load_open_tabs(user_files_dir: str) -> list[str]:
    """Names of PDFs that were open as viewer tabs last session, filtered
    to contexts that still exist in the store."""
    names = [
        n
        for n in _load_tabs_file(user_files_dir).get("open", [])
        if isinstance(n, str)
    ]
    stored = {
        n[:-4] if n.endswith(".txt") else n
        for n in list_contexts(user_files_dir)
    }
    return [n for n in names if n in stored]


def save_open_tabs(user_files_dir: str, names: list[str]) -> None:
    _save_tabs_file(user_files_dir, {"open": list(names)})


def load_last_used(user_files_dir: str) -> dict:
    """{pdf name: unix timestamp of last activation} — recency ordering
    for the ＋ menu. Invalid entries are dropped."""
    data = _load_tabs_file(user_files_dir).get("last_used")
    if not isinstance(data, dict):
        return {}
    return {
        k: float(v)
        for k, v in data.items()
        if isinstance(k, str)
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(v)
    }


def touch_last_used(user_files_dir: str, name: str) -> None:
    """Record that ``name`` was just activated (tab switched/loaded)."""
    lu = load_last_used(user_files_dir)
    lu[name] = time.time()
    if len(lu) > 50:  # bound the map — keep the 50 most recent
        lu = dict(
            sorted(lu.items(), key=lambda kv: kv[1], reverse=True)[:50]
        )
    _save_tabs_file(user_files_dir, {"last_used": lu})


def list_by_recency(
    user_files_dir: str, limit: int | None = None
) -> list[str]:
    """Safe basenames of every stored PDF, most-recently-used first.

    Ranked by ``last_used`` (set by ``touch_last_used`` on import or tab
    activation) when present. A PDF that was imported but never
    activated falls back to its ``contexts/<safe>.txt`` mtime, which is
    written FRESH at import — this means "ingest time", unlike
    ``pdfs/<safe>.pdf``'s mtime, which ``shutil.copy2`` PRESERVES from
    the source file (a lecture authored in 2019 and imported today would
    sort as if it were from 2019). Both call sites that need a recency
    order (this ＋ menu / deck_curate's menu) should read this, not
    re-derive their own mtime fallback.
    """
    ctx_dir = os.path.join(user_files_dir, "contexts")
    names = [
        f[:-4] if f.endswith(".txt") else f
        for f in list_contexts(user_files_dir)
    ]
    recency = load_last_used(user_files_dir)

    def sort_key(safe: str) -> float:
        ts = recency.get(safe)
        if ts:
            return -float(ts)
        try:
            return -os.path.getmtime(os.path.join(ctx_dir, safe + ".txt"))
        except OSError:
            return 0.0

    names.sort(key=sort_key)
    return names[:limit] if limit is not None else names


def load_thumbs_state(user_files_dir: str) -> dict:
    """Thumbnails-strip state from last session (plan B).

    Returns {"thumbs_visible": bool, "thumbs_width": int} — either key
    may be absent when never saved or invalid. Width is only accepted
    inside the sane 80–400px band.
    """
    data = _load_tabs_file(user_files_dir)
    out: dict = {}
    vis = data.get("thumbs_visible")
    if isinstance(vis, bool):
        out["thumbs_visible"] = vis
    width = data.get("thumbs_width")
    if isinstance(width, int) and not isinstance(width, bool) and 80 <= width <= 400:
        out["thumbs_width"] = width
    return out


def save_thumbs_state(
    user_files_dir: str,
    visible: bool | None = None,
    width: int | None = None,
) -> None:
    """Persist thumbnails-strip visibility/width into pdf_tabs.json."""
    updates: dict = {}
    if visible is not None:
        updates["thumbs_visible"] = bool(visible)
    if width is not None:
        try:
            updates["thumbs_width"] = max(80, min(400, int(width)))
        except (TypeError, ValueError):
            pass
    if updates:
        _save_tabs_file(user_files_dir, updates)


#: The values ``save_panel_state`` writes for ``placement`` since
#: 2026-09-05 (the PDF panel is a QDockWidget: three areas plus floating).
PANEL_PLACEMENTS = ("left", "right", "bottom", "float")

_LEGACY_PLACEMENTS = {
    # The 2026-08 placement engine anchored the panel on a pane, above or
    # below the editor and beside the note list; the dock has window edges.
    "above": "bottom",
    "below": "bottom",
    "left": "left",
    "notes-left": "left",
    "right": "right",
    "notes-right": "right",
    "float": "float",
    "bottom": "bottom",
}


def migrate_placement(value: object) -> str:
    """Map a stored ``placement`` — any build's — to one of
    ``PANEL_PLACEMENTS``. Unknown, missing or non-string values land on
    ``"right"``, the editor-side default; a corrupt file must cost a
    default, never the panel."""
    if isinstance(value, str):
        return _LEGACY_PLACEMENTS.get(value.strip().lower(), "right")
    return "right"


def load_panel_state(user_files_dir: str) -> dict:
    """Viewer placement from last session: {"placement": "above"|"below"|
    "left"|"right"|"float", "geom": [x, y, w, h]} — either key may be
    absent."""
    data = _load_tabs_file(user_files_dir)
    out: dict = {}
    placement = data.get("placement")
    if placement in ("above", "below", "left", "right", "float"):
        out["placement"] = placement
    geom = data.get("geom")
    if (
        isinstance(geom, list)
        and len(geom) == 4
        and all(isinstance(v, int) for v in geom)
    ):
        out["geom"] = geom
    return out


def save_panel_state(
    user_files_dir: str,
    placement: str | None = None,
    geom: list[int] | None = None,
) -> None:
    updates: dict = {}
    if placement is not None:
        updates["placement"] = placement
    if geom is not None:
        updates["geom"] = geom
    if updates:
        _save_tabs_file(user_files_dir, updates)


def save_pdf(
    user_files_dir: str, name: str, raw_path: str, root: str | None = None
) -> dict:
    """Ingest a PDF: per-page text, BM25 .txt, page JSON, raw .pdf copy.

    ``root`` (K-073, single-copy invariant): with a Library root
    configured, the ONE copy of the PDF goes straight into the root —
    original filename preserved, mapping recorded — and nothing is
    written to the legacy ``pdfs/`` store. A RE-import of an
    already-mapped name overwrites its existing root file in place
    (same relative path) so no second copy ever appears, mirroring how
    the legacy store always overwrote ``pdfs/<safe>.pdf``. When the
    root directory is missing (unplugged drive, deleted folder) the
    import falls back to the legacy store with a printed note rather
    than failing — the next migration sweep relocates it.
    """
    pages = extract_pages(raw_path)
    safe = _safe_basename(name)
    ctx_dir = os.path.join(user_files_dir, "contexts")
    pdf_dir = os.path.join(user_files_dir, "pdfs")
    os.makedirs(ctx_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)

    full_text = "\n\n".join(pages)
    txt_path = os.path.join(ctx_dir, safe + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    json_path = os.path.join(ctx_dir, safe + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "page_count": len(pages)}, f)

    if root and os.path.isdir(root):
        mapping = load_library_map(user_files_dir)
        prior = mapping.get(safe)
        if prior and os.path.isfile(os.path.join(root, prior)):
            # Re-import: replace the existing library copy in place.
            pdf_dest = os.path.join(root, prior)
            shutil.copy2(raw_path, pdf_dest)
        else:
            filename = _library_filename(os.path.basename(raw_path), safe)
            pdf_dest = _unique_path(root, filename)
            shutil.copy2(raw_path, pdf_dest)
            mapping[safe] = os.path.relpath(pdf_dest, root)
            save_library_map(user_files_dir, mapping)
    else:
        if root:
            print(
                f"[klausmate] Library root {root!r} is unavailable — "
                f"importing {safe!r} into the legacy store instead."
            )
        pdf_dest = os.path.join(pdf_dir, safe + ".pdf")
        shutil.copy2(raw_path, pdf_dest)

    # Re-ingest under the same name: the base file changed, so any
    # captured pristine original is stale — drop it (the next bake
    # re-captures from the fresh copy).
    stale_orig = os.path.join(_originals_dir(user_files_dir), safe + ".pdf")
    if os.path.isfile(stale_orig):
        try:
            os.remove(stale_orig)
            print(f"[klausmate] dropped stale pristine original: {safe}.pdf")
        except OSError as exc:
            print(f"[klausmate] could not drop stale original: {exc}")

    set_active_pdf(user_files_dir, safe)
    # A re-import under the same basename must sort as freshly ingested,
    # not at its old recency slot (or worse, by the copied file's SOURCE
    # mtime — see list_by_recency).
    touch_last_used(user_files_dir, safe)
    return {"name": safe, "page_count": len(pages), "txt_path": txt_path}


def load_pages(user_files_dir: str, name: str) -> list[str] | None:
    base = _safe_basename(name)
    json_path = os.path.join(user_files_dir, "contexts", base + ".json")
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        pages = data.get("pages")
        if isinstance(pages, list):
            return [str(p) for p in pages]
    except (OSError, ValueError):
        pass
    return None


_LIBRARY_MAP_FILE = "library_map.json"


def _library_map_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, _LIBRARY_MAP_FILE)


def load_library_map(user_files_dir: str) -> dict:
    """{safe basename: path relative to library_root} for every PDF that
    ``migrate_to_root`` has moved out of the legacy ``pdfs/`` store.
    Missing file, malformed JSON, or non-string entries all degrade to
    ``{}`` (nothing mapped -> everything falls back to the legacy path)."""
    path = _library_map_path(user_files_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v) for k, v in data.items() if isinstance(v, str) and v
    }


def save_library_map(user_files_dir: str, mapping: dict) -> None:
    _atomic_write_json(_library_map_path(user_files_dir), dict(mapping))


def get_library_root(cfg: dict | None) -> str | None:
    """The user-chosen Library storage folder (absolute path) from the
    addon config, or None if never set. Takes ``cfg`` explicitly (rather
    than reading it itself) so this stays aqt-free and testable, mirroring
    ``embeddings.provider_name``'s cfg-in style."""
    if not isinstance(cfg, dict):
        return None
    root = cfg.get("library_root")
    return root if isinstance(root, str) and root.strip() else None


def _live_library_root() -> str | None:
    """Best-effort read of the configured Library folder via aqt's live
    addon config.

    ``pdf_path_for``'s two production call sites (pdf_viewer.py,
    __init__.py) only ever pass ``(user_files_dir, name)`` — this is the
    one spot in this otherwise aqt-free module that reaches for the
    config, and only as a fallback when no ``root`` was passed in
    explicitly. Guarded so the module keeps importing cleanly with no aqt
    present (the headless test harness) — tests instead pass ``root=``
    directly and never hit this path.
    """
    try:
        from aqt import mw

        if mw is None or mw.addonManager is None:
            return None
        cfg = mw.addonManager.getConfig(__package__) or {}
    except Exception:
        return None
    return get_library_root(cfg)


def _working_pdf_path(
    user_files_dir: str, name: str, root: str | None = None
) -> str:
    """Where ``name``'s stored PDF file lives — the mapped Library
    location once migrated, else the legacy ``pdfs/<safe>.pdf`` slot.

    Unlike ``pdf_path_for`` this is returned even when nothing exists
    there yet: ``bake_annotations`` needs the intended path to create the
    file, not just to check for one.
    """
    base = _safe_basename(name)
    rel = load_library_map(user_files_dir).get(base)
    if rel:
        if root is None:
            root = _live_library_root()
        if root:
            return os.path.join(root, rel)
    return os.path.join(user_files_dir, "pdfs", base + ".pdf")


def pdf_path_for(
    user_files_dir: str, name: str, root: str | None = None
) -> str | None:
    """Single resolution choke point for every PDF-file consumer.

    ``root`` lets tests (and any future explicit caller) bypass the aqt
    config lookup in ``_live_library_root`` — production call sites pass
    only ``(user_files_dir, name)``.
    """
    path = _working_pdf_path(user_files_dir, name, root)
    return path if os.path.isfile(path) else None


def _library_filename(display: str, fallback: str) -> str:
    """A filesystem-safe ``.pdf`` filename for a Library ``display`` name.

    ``display`` is free-form (drive_store's ``rename_display`` only
    checks non-empty) — this guards against a stray path separator or
    leading dots turning a rename into a path escape or hidden file.
    """
    name = (display or "").strip() or fallback
    name = name.replace("/", "-").replace("\\", "-")
    name = name.lstrip(".") or fallback
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _unique_path(dest_dir: str, filename: str) -> str:
    """``filename`` under ``dest_dir``, suffixed " (1)", " (2)", ... on a
    collision. Never returns a path that already exists on disk."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    n = 1
    while os.path.isfile(candidate):
        candidate = os.path.join(dest_dir, f"{stem} ({n}){ext}")
        n += 1
    return candidate


def migrate_to_root(
    user_files_dir: str,
    root: str,
    folders: dict | None = None,
    old_root: str | None = None,
) -> dict:
    """Move every stored PDF's baked copy out of the legacy ``pdfs/``
    store into ``root``, laid out to match the Library tree.

    ``old_root`` names the root this Library is moving AWAY from, for
    the Preferences "Change..." flow. Without it this function only ever
    finds LEGACY ``pdfs/<safe>.pdf`` sources, so a second root change
    reported every already-migrated PDF as "skipped", left the file in
    the old root, and pointed its mapping at a path that does not exist
    under the new one — ``pdf_path_for`` then returned None and the PDF
    was unopenable (review finding, reproduced 2026-08-24). With it, a
    PDF whose mapped file is missing under ``root`` but present under
    ``old_root`` is moved across with the identical discipline below.
    The first-time flow (legacy store -> first root) passes None.

    ``folders`` mirrors ``drive_store.load(user_files_dir)["pdfs"]`` —
    ``{safe: {"folder": "Anatomy/Week 3" | None, "display": "name.pdf"}}``
    — passed in by the caller rather than read from disk here, so this
    stays a pure function a headless test can call with a hand-built
    dict, and no module-global path is read inside the move loop.

    Per-file guarded and RESUMABLE:
      * a PDF whose mapping already points at an existing destination
        file is left alone — a leftover legacy copy is tidied up but
        nothing is re-copied (idempotent re-run).
      * a PDF with no ``pdfs/<safe>.pdf`` left to move (never stored, or
        already relocated by a prior run) is skipped.
      * the destination is never overwritten — a filename collision gets
        a " (1)", " (2)", ... suffix.
      * the ``library_map.json`` entry is written only after the copy is
        verified byte-for-byte (size match); the legacy source is removed
        only AFTER that write succeeds — a crash mid-move leaves either
        the untouched source or a fully-mapped destination, never a state
        in between.
      * one file's OSError is caught and recorded; the rest of the batch
        keeps going.

    ``contexts/``, ``pdf_originals/`` and ``annotations/`` are untouched —
    only the baked ``pdfs/`` copy relocates.

    Returns ``{"moved": [safe, ...], "skipped": [safe, ...], "failed":
    {safe: "reason"}}``.
    """
    folders = folders or {}
    result: dict = {"moved": [], "skipped": [], "failed": {}}
    library_map = load_library_map(user_files_dir)
    pdf_dir = os.path.join(user_files_dir, "pdfs")

    for fname in list_contexts(user_files_dir):
        safe = fname[:-4] if fname.endswith(".txt") else fname
        source = os.path.join(pdf_dir, safe + ".pdf")

        mapped_rel = library_map.get(safe)
        if mapped_rel and os.path.isfile(os.path.join(root, mapped_rel)):
            # Already migrated, possibly by an earlier interrupted run —
            # just tidy up a leftover legacy copy, if any.
            if os.path.isfile(source):
                try:
                    os.remove(source)
                except OSError:
                    pass
            result["skipped"].append(safe)
            continue

        if not os.path.isfile(source) and mapped_rel and old_root:
            # Root CHANGE: the file already left the legacy store on an
            # earlier run and now lives under the previous root. Treat
            # that as the source; everything below (destination layout,
            # collision suffixing, size verify, map-then-delete order)
            # is identical whichever root the bytes come from.
            previous = os.path.join(old_root, mapped_rel)
            if os.path.isfile(previous):
                source = previous

        if not os.path.isfile(source):
            result["skipped"].append(safe)  # nothing stored to move
            continue

        entry = folders.get(safe) or {}
        folder = entry.get("folder")
        display = entry.get("display") or safe
        dest_dir = root
        if isinstance(folder, str) and folder.strip():
            for part in folder.split("/"):
                part = part.strip()
                if part and part != "..":
                    dest_dir = os.path.join(dest_dir, part)
        filename = _library_filename(display, safe)

        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as exc:
            result["failed"][safe] = str(exc)
            continue

        dest_path = _unique_path(dest_dir, filename)
        try:
            src_size = os.path.getsize(source)
            shutil.copy2(source, dest_path)
            if os.path.getsize(dest_path) != src_size:
                raise OSError(f"size mismatch copying {safe} to {dest_path}")
        except OSError as exc:
            if os.path.isfile(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            result["failed"][safe] = str(exc)
            continue

        rel = os.path.relpath(dest_path, root)
        library_map[safe] = rel
        try:
            save_library_map(user_files_dir, library_map)
        except OSError as exc:
            library_map.pop(safe, None)
            try:
                os.remove(dest_path)
            except OSError:
                pass
            result["failed"][safe] = str(exc)
            continue

        try:
            os.remove(source)
        except OSError as exc:
            print(
                f"[klausmate] migration: moved {safe} but could not remove "
                f"the old copy: {exc}"
            )
        result["moved"].append(safe)

    return result


# ------------------------------------------------- Anki -> disk moves


def move_mapped_file(
    user_files_dir: str, root: str, safe: str, folder: str | None
) -> str | None:
    """Anki -> disk half of the two-way sync (K-075): a Library-tree move
    moves the FILE, so the disk-truth rescan agrees with the user's move
    instead of reverting it on the next pass. Returns the new rel, the
    unchanged rel when already in place, or None when nothing is mapped
    or the file is missing (legacy store, unplugged root — no-op)."""
    mapping = load_library_map(user_files_dir)
    rel = mapping.get(safe)
    if not rel:
        return None
    src = os.path.join(root, rel)
    if not os.path.isfile(src):
        return None
    dest_dir = root
    if isinstance(folder, str) and folder.strip():
        for part in folder.split("/"):
            part = part.strip()
            if part and part != "..":
                dest_dir = os.path.join(dest_dir, part)
    if os.path.realpath(dest_dir) == os.path.realpath(os.path.dirname(src)):
        return rel
    os.makedirs(dest_dir, exist_ok=True)
    dest = _unique_path(dest_dir, os.path.basename(rel))
    shutil.move(src, dest)
    mapping[safe] = os.path.relpath(dest, root)
    save_library_map(user_files_dir, mapping)
    return mapping[safe]


def rename_mapped_file(
    user_files_dir: str, root: str, safe: str, display: str
) -> str | None:
    """Library rename -> disk rename (K-075), same contract as
    ``move_mapped_file``. The filename follows ``_library_filename`` —
    the same normalizer the rescan uses to decide a display still
    corresponds to its file, so rename and rescan can never disagree."""
    mapping = load_library_map(user_files_dir)
    rel = mapping.get(safe)
    if not rel:
        return None
    src = os.path.join(root, rel)
    if not os.path.isfile(src):
        return None
    filename = _library_filename(display, safe)
    if os.path.basename(rel) == filename:
        return rel
    dest = _unique_path(os.path.dirname(src), filename)
    shutil.move(src, dest)
    mapping[safe] = os.path.relpath(dest, root)
    save_library_map(user_files_dir, mapping)
    return mapping[safe]


def rename_mapped_folder(
    user_files_dir: str, root: str, old: str, new: str
) -> bool:
    """Library folder rename -> disk directory rename (K-075). Refuses a
    merge into an existing destination (returns False, tree-only rename
    stands and the next rescan re-derives from disk). Rewrites every
    mapping rel under the old prefix."""
    src = os.path.join(root, *[p for p in old.split("/") if p])
    dst = os.path.join(root, *[p for p in new.split("/") if p])
    if not os.path.isdir(src) or os.path.exists(dst):
        return False
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    os.rename(src, dst)
    mapping = load_library_map(user_files_dir)
    old_prefix = old.rstrip("/") + "/"
    changed = False
    for safe, rel in list(mapping.items()):
        rel_fwd = rel.replace(os.sep, "/")
        if rel_fwd.startswith(old_prefix):
            tail = rel_fwd[len(old_prefix):]
            mapping[safe] = os.path.join(*[p for p in (new + "/" + tail).split("/") if p])
            changed = True
    if changed:
        save_library_map(user_files_dir, mapping)
    return True


# ------------------------------------------------- folder -> Anki sync


def walk_root(root: str) -> list[str]:
    """Every ``*.pdf`` under ``root`` as sorted root-relative paths.

    Hidden files and hidden directories (dot-prefixed) are skipped —
    macOS drops ``.DS_Store`` siblings everywhere, and editors leave
    dot-backups; none of those are library content.
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or not fn.lower().endswith(".pdf"):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def plan_rescan(mapping: dict, disk_rels: list[str]) -> dict:
    """PURE folder->Anki diff (K-073, the reverse half of K-057).

    The disk is the source of truth for structure, but matching a
    missing mapped file to a newly-appeared one is INFERENCE, so it
    follows tag_sync.plan_reconcile's confidence philosophy exactly:

      1. a missing file whose basename appears exactly once among the
         new files — and no OTHER missing file shares that basename —
         was MOVED (Finder moves keep the name);
      2. after that, exactly-one-missing and exactly-one-new pair up as
         a RENAME;
      3. anything else is ambiguous: report and do nothing. In
         particular, new files are only ``ingestable`` when NO missing
         files remain unmatched — ingesting while a rename is unresolved
         would duplicate the renamed PDF under a second identity.

    Returns ``{"moves": {safe: new_rel}, "missing": [safe],
    "new": [rel], "ingestable": [rel], "ambiguous": bool}``.
    ``missing`` are mapped PDFs gone from disk with no candidate — the
    caller reports them; Klaus never deletes its own data over them.
    """
    disk = set(disk_rels)
    claimed = set(mapping.values())
    missing = sorted(s for s, rel in mapping.items() if rel not in disk)
    new = sorted(r for r in disk if r not in claimed)
    moves: dict = {}

    if missing and new:
        new_by_base: dict = {}
        for r in new:
            new_by_base.setdefault(os.path.basename(r), []).append(r)
        missing_base_counts: dict = {}
        for s in missing:
            b = os.path.basename(mapping[s])
            missing_base_counts[b] = missing_base_counts.get(b, 0) + 1
        still = []
        for s in missing:
            b = os.path.basename(mapping[s])
            cands = new_by_base.get(b) or []
            if len(cands) == 1 and missing_base_counts[b] == 1:
                moves[s] = cands[0]
                new.remove(cands[0])
                new_by_base[b] = []
            else:
                still.append(s)
        missing = still

    if len(missing) == 1 and len(new) == 1:
        moves[missing[0]] = new[0]
        missing, new = [], []

    ambiguous = bool(missing and new)
    return {
        "moves": moves,
        "missing": missing,
        "new": new,
        "ingestable": [] if ambiguous else list(new),
        "ambiguous": ambiguous,
    }


def _rel_folder(rel: str) -> str | None:
    """drive_store folder path ("A/B", forward slashes) for a root-relative
    file path, or None for the root itself."""
    d = os.path.dirname(rel)
    parts = [p for p in d.replace(os.sep, "/").split("/") if p]
    return "/".join(parts) or None


def _unique_safe(user_files_dir: str, mapping: dict, stem: str) -> str:
    """A safe name not already used by a mapping entry or a context."""
    base = _safe_basename(stem)
    ctx = os.path.join(user_files_dir, "contexts")

    def taken(s: str) -> bool:
        return s in mapping or os.path.isfile(os.path.join(ctx, s + ".txt"))

    if not taken(base):
        return base
    n = 2
    while taken(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def rescan_root(user_files_dir: str, root: str, folders: dict | None = None) -> dict:
    """Apply the folder->Anki half of the two-way sync (K-073).

    Moves/renames confirmed by ``plan_rescan`` update the mapping AND the
    Library tree (drive_store folder + display follow the file). The
    mapping is saved FIRST: path resolution correctness beats a
    cosmetic tree mismatch if a write fails halfway (documented
    trade-off — a failed drive write leaves the folder column stale
    until the entry next moves, but every PDF still opens).

    New unmatched PDFs are ingested IN PLACE — context extracted, drive
    entry recorded, mapping pointed at the file where it already lives.
    No copy is made anywhere: the file in the root folder IS the
    library copy (single-copy invariant). A file that will not parse is
    skipped with a printed reason and retried on the next rescan.

    A display only changes when the on-disk basename no longer
    corresponds to it under ``_library_filename`` — a plain move keeps
    the user's display text untouched.
    """
    from . import drive_store  # aqt-free; local import keeps deps one-way

    folders = folders or {}
    mapping = load_library_map(user_files_dir)
    plan = plan_rescan(mapping, walk_root(root))

    moved: list[str] = []
    for safe, rel in sorted(plan["moves"].items()):
        mapping[safe] = rel
        moved.append(safe)

    ingested: list[str] = []
    ingest_failed: list[str] = []
    for rel in plan["ingestable"]:
        full = os.path.join(root, rel)
        try:
            pages = extract_pages(full)
        except Exception as exc:  # noqa: BLE001 - one bad file never stops a rescan
            print(f"[klausmate] rescan: could not ingest {rel!r}: {exc}")
            ingest_failed.append(rel)
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        safe = _unique_safe(user_files_dir, mapping, stem)
        ctx_dir = os.path.join(user_files_dir, "contexts")
        os.makedirs(ctx_dir, exist_ok=True)
        with open(os.path.join(ctx_dir, safe + ".txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(pages))
        with open(os.path.join(ctx_dir, safe + ".json"), "w", encoding="utf-8") as f:
            json.dump({"pages": pages, "page_count": len(pages)}, f)
        mapping[safe] = rel
        ingested.append(safe)

    if moved or ingested:
        save_library_map(user_files_dir, mapping)

    # The tree follows the MAPPING for EVERY entry whose file exists,
    # not just this pass's moves. The tree is derived state and drifts
    # independently of the mapping: the initial migration syncs the
    # mapping without ever updating the tree, and the K-054 tag
    # reconcile can pull the tree toward STALE !Library tags. Seen live
    # 2026-08-24: migration synced the mapping at 17:42, the old tags
    # then rewrote the tree to the pre-move layout at 18:08, and a
    # moves-only loop could never repair it — the mapping never changed
    # again, so the rescan no-opped forever while tree and disk
    # disagreed. Reconciling unconditionally makes the rescan
    # self-healing regardless of which side drifted.
    tree_changed: list[str] = []
    for safe in sorted(mapping):
        rel = mapping[safe]
        if not os.path.isfile(os.path.join(root, rel)):
            continue  # missing on disk — reported below, never rewritten
        entry = folders.get(safe) or {}
        changed = False
        try:
            folder = _rel_folder(rel)
            if (entry.get("folder") or None) != folder:
                drive_store.set_folder(user_files_dir, safe, folder)
                changed = True
            cur_display = entry.get("display") or safe
            basename = os.path.basename(rel)
            if _library_filename(cur_display, safe) != basename:
                drive_store.rename_display(user_files_dir, safe, basename)
                changed = True
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] rescan: tree update failed for {safe!r}: {exc}")
        if changed:
            tree_changed.append(safe)

    for safe in ingested:
        rel = mapping[safe]
        try:
            drive_store.record_import(user_files_dir, safe, os.path.basename(rel))
            folder = _rel_folder(rel)
            if folder:
                drive_store.set_folder(user_files_dir, safe, folder)
            touch_last_used(user_files_dir, safe)
        except Exception as exc:  # noqa: BLE001
            print(f"[klausmate] rescan: bookkeeping failed for {safe!r}: {exc}")

    if plan["missing"]:
        print(
            "[klausmate] rescan: missing from the Library folder "
            f"(nothing deleted on the Klaus side): {plan['missing']}"
        )
    if plan["ambiguous"]:
        print(
            "[klausmate] rescan: ambiguous folder changes — "
            f"missing {plan['missing']} vs new {plan['new']}; "
            "no action taken. Undo the simultaneous rename+move batch or "
            "resolve one file at a time."
        )

    return {
        "moved": moved,
        "tree_changed": tree_changed,
        "ingested": ingested,
        "ingest_failed": ingest_failed,
        "missing": plan["missing"],
        "ambiguous_new": plan["new"] if plan["ambiguous"] else [],
        "ambiguous": plan["ambiguous"],
    }


def annotations_path_for(user_files_dir: str, name: str) -> str:
    base = _safe_basename(name)
    return os.path.join(user_files_dir, "annotations", base + ".json")


_HIGHLIGHT_COLOR_DEFAULT = "#fadc50"


def _validate_highlight(entry) -> dict | None:
    """Normalize one stored highlight record; None if malformed.

    Schema (version 1): {"id": uuid hex, "page": int,
    "rects": [[x, y, w, h] in page points], "color": "#fadc50",
    "note": str}. ``note`` is the optional sticky-note text (N1) —
    missing or malformed normalizes to "".
    """
    if not isinstance(entry, dict):
        return None
    hl_id = entry.get("id")
    page = entry.get("page")
    rects = entry.get("rects")
    color = entry.get("color", _HIGHLIGHT_COLOR_DEFAULT)
    if not isinstance(hl_id, str) or not hl_id:
        return None
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        return None
    if not isinstance(rects, list) or not rects:
        return None
    clean_rects: list[list[float]] = []
    for r in rects:
        # json.load happily parses NaN/Infinity — reject non-finite
        # values here, otherwise int(round(...)) blows up on every
        # overlay refresh downstream. Width/height must be >= 0 too.
        if (
            isinstance(r, (list, tuple))
            and len(r) == 4
            and all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in r
            )
            and float(r[2]) >= 0.0
            and float(r[3]) >= 0.0
        ):
            clean_rects.append([float(v) for v in r])
        else:
            return None
    if not isinstance(color, str) or not color:
        color = _HIGHLIGHT_COLOR_DEFAULT
    note = entry.get("note", "")
    if not isinstance(note, str):
        note = ""
    out = {
        "id": hl_id,
        "page": page,
        "rects": clean_rects,
        "color": color,
        "note": note,
    }
    # K-077 extensions — adopted outside markup. kind "text" is a
    # FreeText record (rects[0] is its box, ``text`` its contents);
    # anything else normalizes to the classic highlight shape, keeping
    # pre-K-077 records byte-identical through save/load.
    if entry.get("kind") == "text":
        text = entry.get("text", "")
        out["kind"] = "text"
        out["text"] = text if isinstance(text, str) else ""
        size = entry.get("size")
        if (
            isinstance(size, (int, float))
            and not isinstance(size, bool)
            and math.isfinite(size)
            and size > 0
        ):
            out["size"] = float(size)
    origin = entry.get("origin")
    if isinstance(origin, str) and origin:
        out["origin"] = origin
    return out


def load_annotations(user_files_dir: str, name: str) -> list[dict]:
    """Persisted highlights for ``name`` (plan B).

    Validates every entry and skips malformed ones with a log line, so
    one corrupted record never takes down the whole file.
    """
    path = annotations_path_for(user_files_dir, name)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print(f"[klausmate] annotations unreadable: {path}")
        return []
    if not isinstance(data, dict):
        print(f"[klausmate] annotations malformed (not a dict): {path}")
        return []
    raw = data.get("highlights")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        hl = _validate_highlight(entry)
        if hl is None:
            print(
                "[klausmate] skipping malformed highlight in "
                f"{os.path.basename(path)}"
            )
            continue
        out.append(hl)
    return out


def _load_annotation_doc(user_files_dir: str, name: str) -> dict:
    """The whole annotations json as a dict (K-081) — highlights plus
    any other top-level keys (suppressed_external tombstones)."""
    path = annotations_path_for(user_files_dir, name)
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            return doc
    except (OSError, ValueError):
        pass
    return {"version": 1, "highlights": []}


def save_annotations(
    user_files_dir: str, name: str, highlights: list[dict]
) -> None:
    """Write highlights for ``name`` — SYNCHRONOUS by design (plan B).

    Saves are rare and tiny; a debounce would risk cross-tab loss when
    ``load_pdf`` swaps the shared QPdfDocument before the flush fires.
    Top-level keys other than ``highlights`` are preserved (K-081: the
    suppressed_external tombstones used to be dropped on every save).
    """
    path = annotations_path_for(user_files_dir, name)
    try:
        doc = _load_annotation_doc(user_files_dir, name)
        doc["version"] = 1
        doc["highlights"] = list(highlights or [])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
    except (OSError, TypeError, ValueError) as exc:
        print(f"[klausmate] failed to save annotations {path}: {exc}")


def load_suppressed(user_files_dir: str, name: str) -> list[dict]:
    """Tombstones of deleted external records (K-081): a Remove on an
    adopted mark must survive the unmarked original reappearing (bake
    still pending, or Preview re-saving its stale model)."""
    doc = _load_annotation_doc(user_files_dir, name)
    raw = doc.get("suppressed_external")
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def _update_doc_keys(user_files_dir: str, name: str, updates: dict) -> None:
    """Read-modify-write of top-level annotation-doc keys. Main-thread
    only, like every other json write here."""
    doc = _load_annotation_doc(user_files_dir, name)
    doc.update(updates)
    path = annotations_path_for(user_files_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)


def add_suppressed(user_files_dir: str, name: str, record: dict) -> None:
    """Tombstone one external record (called on delete, K-081). Stores
    the full geometry + text so matching can be PRECISE (K-084): a
    tombstone blocks the resurrection of the specific deleted mark,
    never the location."""
    try:
        rects = [list(r) for r in record.get("rects") or []]
        if not rects:
            return
        entry = {
            "page": record.get("page"),
            "kind": "text" if record.get("kind") == "text" else "highlight",
            "rects": rects,
            "text": str(record.get("text") or ""),
            "ts": time.time(),
        }
        sup = load_suppressed(user_files_dir, name)
        sup.append(entry)
        _update_doc_keys(user_files_dir, name, {"suppressed_external": sup})
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] tombstone write failed for {name}: {exc}")


def remove_records(user_files_dir: str, name: str, ids) -> int:
    """Drop records by id (K-085: the viewer's post-bake callback
    removes marks the bake omitted as externally deleted). Returns the
    number removed; preserves every other doc key."""
    drop = {str(i) for i in ids if i}
    if not drop:
        return 0
    records = load_annotations(user_files_dir, name)
    kept = [r for r in records if str(r.get("id")) not in drop]
    removed = len(records) - len(kept)
    if removed:
        save_annotations(user_files_dir, name, kept)
    return removed


def load_removed_native(user_files_dir: str, name: str) -> list[dict]:
    """Recovery bucket (K-087): native records the mirror removed
    because their marks were deleted in an outside app. There is no
    content difference between "the user deleted them" and "an app
    saved a stale model that never had them", so deletions are trusted
    (the user's priority) and the removed records are kept here —
    capped and aged out — rather than lost outright."""
    raw = _load_annotation_doc(user_files_dir, name).get("removed_native")
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def load_baked_native(user_files_dir: str, name: str) -> set:
    """Ids of the native records present as marks in the file as of the
    last successful bake (K-084) — replaced wholesale per bake."""
    raw = _load_annotation_doc(user_files_dir, name).get("baked_native_ids")
    return {str(x) for x in raw} if isinstance(raw, list) else set()


def mark_native_baked(user_files_dir: str, name: str, ids) -> None:
    """Main-thread bookkeeping after a successful bake (K-084): exactly
    these native records exist as marks in the file. One of them later
    missing from the file — while other Klaus marks survived — was
    deleted in the outside app, and the mirror drops its record."""
    try:
        _update_doc_keys(
            user_files_dir,
            name,
            {"baked_native_ids": sorted({str(i) for i in ids if i})},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[klausmate] baked-ids record failed for {name}: {exc}")


def _originals_dir(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, "pdf_originals")


def _atomic_replace_from(src_path: str, dest_path: str) -> None:
    """Copy ``src_path`` over ``dest_path`` atomically (tmp + os.replace).

    The tmp file lives in the destination directory so ``os.replace`` is
    a same-filesystem rename — safe even while a QPdfDocument still holds
    the old inode open.
    """
    dest_dir = os.path.dirname(dest_path)
    tmp = os.path.join(
        dest_dir, f".{os.path.basename(dest_path)}.{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(src_path, tmp)
        os.replace(tmp, dest_path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _mark_klaus(anno, record: dict, suffix: str = "") -> None:
    """Stamp a pypdf annotation object with the Klaus /NM marker
    (K-077) — ``klausmate:<record id>``, plus a suffix for satellite
    annotations (a highlight's sticky note)."""
    try:
        anno[_BakeName("/NM")] = _BakeString(
            _KLAUS_NM + str(record.get("id") or uuid.uuid4().hex) + suffix
        )
    except Exception:
        pass


def _bake_color(value, fallback: str) -> str:
    """Record color ("#rrggbb" or "rrggbb") -> the bare hex pypdf's
    annotation builders take; ``fallback`` for anything malformed."""
    if isinstance(value, str):
        v = value.lstrip("#").lower()
        if len(v) == 6 and all(c in "0123456789abcdef" for c in v):
            return v
    return fallback


# The base-14 font name every reader resolves without a resource
# dictionary. Spelled once so the /DA string and any future /DR entry
# can never name different fonts.
_DA_FONT = "Helv"

# The size a text record falls back to when its own is missing or junk
# — one constant behind both the /DS string pypdf builds and the /DA
# string we build, so the two halves of one annotation's appearance can
# never disagree.
TEXT_SIZE_FALLBACK = 12


def _num(value: float) -> str:
    """A PDF numeric token: ``12`` not ``12.0``, ``0.9804`` not
    ``0.9803921568627451`` — a content-stream operand, not a repr."""
    return f"{round(float(value), 4):g}"


def free_text_da(color, size, fallback_color: str = "000000") -> str:
    """The FreeText default-appearance string, ``/Helv 24 Tf 1 0 0 rg``.

    WHY WE BUILD THIS OURSELVES (K-159, and it is the whole bug):
    vendored pypdf's ``FreeText`` writes ``/DA`` only inside
    ``if border_color:`` — and it writes only the colour there, never a
    font. We pass ``border_color=None`` deliberately (K-150: Preview
    frames a text box only while it is selected, so a permanent border
    would be wrong), so every baked text box shipped ``/DA ()``. Size
    and colour went into ``/DS`` alone, the rich-text CSS string, which
    Preview and most readers ignore — so they fell back to a default
    appearance and every note rendered small and black. MEASURED, not
    assumed: PDFKit (the framework Preview itself draws with) reported
    ``font=Helvetica size=12.0 color=white 0`` for a 24pt red record,
    and reported ``size=24.0 color=RGB 1 0 0`` once this string was
    present. The border stays off: the border and the appearance string
    are separate concerns, and conflating them is what produced the bug.

    ``/DR`` is deliberately NOT written. ``/Helv`` is one of the base-14
    names readers resolve implicitly, and PDFKit was measured rendering
    both the size and the colour correctly with no resource dictionary
    and no ``/AcroForm`` anywhere in the file — inventing an empty form
    dictionary in a user's lecture PDF to restate a font every reader
    already knows would be a bigger change than the fix.

    Round-trips: ``_freetext_style`` parses exactly this shape back
    (``/Helv <n> Tf`` and ``r g b rg``), so a Klaus box re-read from the
    file carries the style it was baked with instead of black/None.
    """
    hexv = _bake_color(color, fallback_color)
    r, g, b = (int(hexv[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (
        f"/{_DA_FONT} {_num(text_point_size(size))} Tf "
        f"{_num(r)} {_num(g)} {_num(b)} rg"
    )


def text_point_size(size) -> float:
    """A text record's font size in points, ``TEXT_SIZE_FALLBACK`` for
    anything missing, non-numeric, non-positive or non-finite.

    The bake's ``hl.get('size') or 12`` used to say this inline, in one
    place. It now has two readers — pypdf's ``/DS`` and our own ``/DA``
    — and a note whose two appearance strings disagreed about its size
    would be worse than the bug K-159 fixes.
    """
    try:
        pt = float(size)
    except (TypeError, ValueError):
        return float(TEXT_SIZE_FALLBACK)
    if not math.isfinite(pt) or pt <= 0:
        return float(TEXT_SIZE_FALLBACK)
    return pt


def bake_annotations(
    user_files_dir: str,
    name: str,
    report: dict | None = None,
) -> bool:
    """Bake stored highlights/notes into ``pdfs/<base>.pdf`` as REAL PDF
    annotations (visible in Preview/Acrobat). Returns False on failure.

    The pristine (never-annotated) original lives in
    ``pdf_originals/<base>.pdf`` — captured on first bake. Every bake
    regenerates the working file FROM that pristine copy plus the FULL
    annotations json, never incrementally, so removing a highlight is
    just a re-bake and corruption cannot accumulate. An empty
    annotations list restores the pristine original (un-bake).

    Coordinates: stored rects are Qt page points (origin top-left, y
    down); PDF user space is origin bottom-left, y up. Each page's own
    mediabox height drives the flip: ``y_pdf = height - (y_qt + h)``.

    Writes are atomic (tmp file + ``os.replace`` in the pdfs dir) and
    this never raises — safe to call from a background thread.
    """
    try:
        if not PDF_AVAILABLE or not BAKE_AVAILABLE:
            print("[klausmate] bake skipped: pypdf writer/annotations unavailable")
            return False
        base = _safe_basename(name)
        # The MAPPED location once migrated (K-070) — same choke point as
        # pdf_path_for, so a bake after moving the library folder writes
        # to where the file actually lives, not the old pdfs/ slot.
        working = _working_pdf_path(user_files_dir, name)
        pristine = os.path.join(_originals_dir(user_files_dir), base + ".pdf")
        highlights = load_annotations(user_files_dir, name)

        if not os.path.isfile(pristine):
            if not highlights:
                # Never baked and nothing to bake — working IS pristine.
                return True
            if not os.path.isfile(working):
                print(f"[klausmate] bake failed: no stored PDF for {base}")
                return False
            # STRIPPED capture (K-082): a plain copy would smuggle the
            # outside marks into the baseline, and the carry below would
            # then double them on every bake.
            if not _capture_pristine_stripped(user_files_dir, name, working):
                print(f"[klausmate] bake failed: pristine capture ({base})")
                return False

        # Outside marks are CARRIED verbatim from the current working
        # file (K-082) — the file is their source of truth, and baking
        # must never rewrite or delete Preview's own objects. Klaus
        # regenerates only its NATIVE marks. Tombstoned outside marks
        # (deleted in Klaus) are dropped from the carry, and legacy
        # K-077 adopted copies (marked, id belongs to an external
        # record) ride along verbatim.
        native = [h for h in highlights if h.get("origin") != "external"]
        ext_ids = {
            str(h.get("id"))
            for h in highlights
            if h.get("origin") == "external" and h.get("id")
        }
        suppressed = load_suppressed(user_files_dir, name)
        carried: list[tuple[int, Any]] = []
        present_primary: set[str] = set()
        if os.path.isfile(working):
            try:
                wreader = PdfReader(working)
                for pi, wpg in enumerate(wreader.pages):
                    phf, oxf, oyf = _page_frame(wpg)
                    for ref in _annots_of(wpg):
                        try:
                            o = ref.get_object()
                            sub = str(o.get("/Subtype"))
                            if sub not in ("/Highlight", "/FreeText"):
                                continue
                            nm = str(o.get("/NM") or "")
                            if nm.startswith(_KLAUS_NM):
                                tail = nm[len(_KLAUS_NM):]
                                rid = tail.split(":", 1)[0]
                                if ":" not in tail:
                                    present_primary.add(rid)
                                if rid not in ext_ids:
                                    # Klaus-native: regenerated below.
                                    continue
                            if suppressed:
                                if sub == "/Highlight":
                                    rects = _quads_to_qt_rects(
                                        o, phf, oxf, oyf
                                    )
                                else:
                                    r = _rect_to_qt(
                                        o.get("/Rect"), phf, oxf, oyf
                                    )
                                    rects = [r] if r else []
                                pseudo = {
                                    "page": pi,
                                    "kind": (
                                        "text"
                                        if sub == "/FreeText"
                                        else "highlight"
                                    ),
                                    "rects": rects,
                                    # Precision tombstones compare text
                                    # for text marks (K-084).
                                    "text": (
                                        _freetext_text(o, wreader)
                                        if sub == "/FreeText"
                                        else ""
                                    ),
                                }
                                if _matches_tombstone(pseudo, suppressed):
                                    # Deleted in Klaus: drop for real.
                                    continue
                            carried.append((pi, o))
                        except Exception:
                            continue
            except Exception as exc:
                print(
                    f"[klausmate] bake: carry scan failed ({base}): {exc}"
                )
                carried = []

        # Resurrection guard (K-085): a record whose mark the LAST bake
        # put in the file, now absent while other Klaus marks survived,
        # was deleted in the outside app after our records last synced —
        # regenerating it would resurrect a deliberate deletion (the
        # race: Preview deletes, a pending bake fires before the mirror
        # ran). Omit it and report; the caller drops the record.
        # Zero surviving marks = stale-model clobber, same rule as the
        # mirror: bake everything, never mass-omit.
        ledger = load_baked_native(user_files_dir, name)
        omitted: list[str] = []
        native_to_bake: list[dict] = []
        for hl in native:
            rid = str(hl.get("id"))
            if rid in ledger and rid not in present_primary:
                # Ledger says this mark was in the file; it is not there
                # now — deleted in an outside app, so regenerating it
                # would resurrect a deliberate deletion. (K-087 dropped
                # the "some Klaus mark must survive" precondition: it
                # made deleting the last highlight impossible.)
                omitted.append(rid)
                continue
            native_to_bake.append(hl)
        if report is not None:
            report["omitted_native"] = omitted

        if not native_to_bake and not carried:
            # Un-bake: nothing of anyone's to keep — pristine back.
            _atomic_replace_from(pristine, working)
            if report is not None:
                report["native_ids"] = []
                try:
                    st = os.stat(working)
                    report["stat"] = (
                        st.st_ino, st.st_mtime_ns, st.st_size
                    )
                except OSError:
                    pass
            print(f"[klausmate] un-baked (restored pristine): {base}.pdf")
            return True

        reader = PdfReader(pristine)
        writer = PdfWriter(clone_from=reader)
        n_pages = len(writer.pages)
        for pi, o in carried:
            if not (0 <= pi < n_pages):
                continue
            try:
                cl = o.clone(writer)
                try:
                    del cl[_BakeName("/P")]
                except Exception:
                    pass
                refc = writer._add_object(cl)
                pgw = writer.pages[pi]
                arr = pgw.get("/Annots")
                if arr is None:
                    pgw[_BakeName("/Annots")] = _BakeArray([refc])
                else:
                    arr.get_object().append(refc)
            except Exception as exc:
                print(
                    f"[klausmate] bake: carry failed on p{pi} "
                    f"({base}): {exc}"
                )
        baked = 0
        baked_ids_now: list[str] = []
        for hl in native_to_bake:
            page = hl.get("page")
            if not isinstance(page, int) or not (0 <= page < n_pages):
                print(
                    f"[klausmate] bake: skipping highlight on out-of-range "
                    f"page {page!r} ({base}, {n_pages} pages)"
                )
                continue
            mb = writer.pages[page].mediabox
            ph = float(mb.height)
            # Account for a non-zero mediabox origin (rare, but a PDF
            # whose mediabox doesn't start at (0,0) would otherwise get
            # shifted annotations). Known limitation: CropBox≠MediaBox
            # documents may still be offset — lecture PDFs are origin-0.
            try:
                ox = float(mb.left)
                oy = float(mb.bottom)
            except Exception:
                ox = oy = 0.0
            if hl.get("kind") == "text":
                # Adopted outside text (K-077): one FreeText per record,
                # rects[0] is its box in Qt page points.
                rects = hl.get("rects") or []
                if not rects:
                    continue
                x, y, w, h = (float(v) for v in rects[0])
                pt = text_point_size(hl.get("size"))
                free = _BakeFreeText(
                    text=str(hl.get("text") or ""),
                    rect=(
                        ox + x,
                        oy + ph - (y + h),
                        ox + x + w,
                        oy + ph - y,
                    ),
                    font_size=f"{pt}pt",
                    font_color=_bake_color(hl.get("color"), "000000"),
                    border_color=None,
                    background_color=None,
                )
                # /DA, which pypdf leaves EMPTY for a borderless box —
                # see free_text_da. Without it Preview renders every
                # note at its own default size in black, whatever /DS
                # says (measured in PDFKit, K-159).
                free[_BakeName("/DA")] = _BakeString(
                    free_text_da(hl.get("color"), pt)
                )
                _mark_klaus(free, hl)
                writer.add_annotation(page, free)
                baked += 1
                if hl.get("id"):
                    baked_ids_now.append(str(hl["id"]))
                continue
            # One Highlight annotation per record: quad_points cover ALL
            # its rects, rect is their union. 8 floats per quad:
            # x0,y_top, x1,y_top, x0,y_bot, x1,y_bot.
            quads: list[float] = []
            ux0 = uy0 = ux1 = uy1 = None
            for r in hl.get("rects", []):
                x, y, w, h = (float(v) for v in r)
                x0 = ox + x
                x1 = ox + x + w
                y_bot = oy + ph - (y + h)
                y_top = oy + ph - y
                quads.extend(
                    [x0, y_top, x1, y_top, x0, y_bot, x1, y_bot]
                )
                ux0 = x0 if ux0 is None else min(ux0, x0)
                ux1 = x1 if ux1 is None else max(ux1, x1)
                uy0 = y_bot if uy0 is None else min(uy0, y_bot)
                uy1 = y_top if uy1 is None else max(uy1, y_top)
            if not quads or ux0 is None:
                continue
            anno = _BakeHighlight(
                rect=(ux0, uy0, ux1, uy1),
                quad_points=_BakeArray(_BakeFloat(v) for v in quads),
                highlight_color=_bake_color(hl.get("color"), "fadc50"),
                printing=True,
            )
            _mark_klaus(anno, hl)
            writer.add_annotation(page, anno)
            baked += 1
            if hl.get("id"):
                baked_ids_now.append(str(hl["id"]))
            note = hl.get("note")
            note = note.strip() if isinstance(note, str) else ""
            if note:
                # Sticky note: 18x18 icon anchored at the union's
                # top-right corner.
                sticky = _BakeText(
                    rect=(ux1, uy1 - 18, ux1 + 18, uy1),
                    text=note,
                    open=False,
                )
                _mark_klaus(sticky, hl, suffix=":note")
                writer.add_annotation(page, sticky)

        tmp = os.path.join(
            os.path.dirname(working),
            f".{base}.pdf.{uuid.uuid4().hex}.tmp",
        )
        try:
            with open(tmp, "wb") as f:
                writer.write(f)
            os.replace(tmp, working)
        finally:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if report is not None:
            report["native_ids"] = baked_ids_now
            try:
                st = os.stat(working)
                report["stat"] = (st.st_ino, st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        print(
            f"[klausmate] baked {baked} annotation record(s) into "
            f"{base}.pdf ({len(carried)} outside mark(s) carried)"
        )
        return True
    except Exception as exc:
        print(f"[klausmate] bake failed for {name}: {exc}")
        return False


# ------------------------------- foreign annotations (K-077) -------------
#
# Outside markup (macOS Preview text boxes and highlights) is ADOPTED into
# Klaus's own records rather than rendered from the file: after the next
# bake it is Klaus-owned — marked, regenerated from pristine, deletable in
# Klaus. One-way valve by design: further edits belong in Klaus; an outside
# re-edit of an adopted item is either reverted by the next bake (marker
# kept) or re-imported as a second copy (marker dropped).


def _annots_of(pg) -> list:
    raw = pg.get("/Annots")
    if raw is None:
        return []
    try:
        return list(raw.get_object())
    except Exception:
        return []


def _page_frame(pg) -> tuple[float, float, float]:
    try:
        mb = pg.mediabox
        return float(mb.height), float(mb.left), float(mb.bottom)
    except Exception:
        return 792.0, 0.0, 0.0


def _rect_to_qt(rect, ph: float, ox: float, oy: float) -> list[float] | None:
    try:
        a, b, c, d = (float(v) for v in rect)
    except Exception:
        return None
    x0, x1 = min(a, c), max(a, c)
    yb, yt = min(b, d), max(b, d)
    return [x0 - ox, oy + ph - yt, x1 - x0, yt - yb]


def _quads_to_qt_rects(o, ph: float, ox: float, oy: float) -> list[list[float]]:
    rects: list[list[float]] = []
    try:
        qp = o.get("/QuadPoints")
        if qp:
            vals = [float(v) for v in qp.get_object()]
            for i in range(0, len(vals) - 7, 8):
                xs = vals[i:i + 8:2]
                ys = vals[i + 1:i + 8:2]
                x0, x1 = min(xs), max(xs)
                yb, yt = min(ys), max(ys)
                rects.append([x0 - ox, oy + ph - yt, x1 - x0, yt - yb])
    except Exception:
        rects = []
    if not rects:
        r = _rect_to_qt(o.get("/Rect"), ph, ox, oy)
        if r is not None:
            rects = [r]
    return rects


def _annot_color(o) -> str | None:
    """/C array (1=gray, 3=rgb, 4=cmyk components) -> "#rrggbb"."""
    try:
        c = o.get("/C")
        if not c:
            return None
        vals = [max(0.0, min(1.0, float(v))) for v in c.get_object()]
        if len(vals) == 1:
            r = g = b = vals[0]
        elif len(vals) == 3:
            r, g, b = vals
        elif len(vals) == 4:
            cc, mm, yy, kk = vals
            r, g, b = (1 - cc) * (1 - kk), (1 - mm) * (1 - kk), (1 - yy) * (1 - kk)
        else:
            return None
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
    except Exception:
        return None


def _ap_text(o, reader) -> str:
    """Text-showing operators of an annotation's /AP normal appearance
    (K-080): Tj / ' / \" / TJ strings collected in order, with Td/TD/T*
    between runs treated as line breaks. macOS Preview writes FreeText
    annotations whose text lives ONLY here — /Contents is absent."""
    try:
        from pypdf.generic import ContentStream  # vendored

        ap = o.get("/AP")
        if ap is None:
            return ""
        n = ap.get_object().get("/N")
        if n is None:
            return ""
        n = n.get_object()
        if not hasattr(n, "get_data"):
            # Appearance-state subdictionary: take the first stream.
            streams = [
                v.get_object()
                for v in n.values()
                if hasattr(v.get_object(), "get_data")
            ]
            if not streams:
                return ""
            n = streams[0]

        def _s(x) -> str:
            if isinstance(x, bytes):
                try:
                    if x.startswith(b"\xfe\xff"):
                        return x.decode("utf-16-be", "ignore")
                    return x.decode("latin-1", "ignore")
                except Exception:
                    return ""
            return x if isinstance(x, str) else ""

        pieces: list[str] = []
        newline = False
        for operands, op in ContentStream(n, reader).operations:
            if op in (b"Td", b"TD", b"T*"):
                newline = True
                continue
            if op in (b"Tj", b"'", b'"'):
                s = _s(operands[-1]) if operands else ""
            elif op == b"TJ" and operands:
                s = "".join(_s(x) for x in operands[0])
            else:
                continue
            if not s:
                continue
            if newline and pieces:
                pieces.append("\n")
            pieces.append(s)
            newline = False
        return "".join(pieces).strip()
    except Exception:
        return ""


def _freetext_text(o, reader) -> str:
    """A FreeText annotation's text, Preview quirks included (K-080):
    /Contents when present, else /RC with its markup stripped, else the
    /AP appearance stream's text runs."""
    try:
        c = o.get("/Contents")
        if c is not None and str(c).strip():
            return str(c)
        rc = o.get("/RC")
        if rc is not None:
            txt = re.sub(r"<[^>]+>", " ", str(rc))
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            if txt:
                return txt
        return _ap_text(o, reader)
    except Exception:
        return ""


def _freetext_style(o) -> tuple[str, float | None]:
    """Best-effort text color + font size from a FreeText /DA string
    (e.g. "0 0 1 rg /Helv 12 Tf"); black / None when unparseable."""
    color: str = "#000000"
    size: float | None = None
    try:
        toks = str(o.get("/DA") or "").split()
        for i, t in enumerate(toks):
            if t == "rg" and i >= 3:
                r, g, b = (float(x) for x in toks[i - 3:i])
                color = "#%02x%02x%02x" % (
                    round(r * 255), round(g * 255), round(b * 255)
                )
            elif t == "g" and i >= 1:
                v = round(float(toks[i - 1]) * 255)
                color = "#%02x%02x%02x" % (v, v, v)
            elif t == "Tf" and i >= 1:
                s = float(toks[i - 1])
                if s > 0:
                    size = s
    except Exception:
        pass
    return color, size


def scan_foreign_annotations(user_files_dir: str, name: str) -> list[dict]:
    """Compatibility wrapper over ``scan_working_annotations``: just the
    foreign records, [] on failure."""
    res = scan_working_annotations(user_files_dir, name)
    return list(res.get("foreign") or []) if isinstance(res, dict) else []


def scan_working_annotations(user_files_dir: str, name: str) -> dict | None:
    """Everything the mirror needs from ``name``'s working PDF (K-082):

    ``{"foreign": [...], "marked_ids": set, "page_count": int}`` —
    foreign is /Highlight + /FreeText entries whose /NM lacks the
    klausmate: marker, as records in Klaus page-point space (origin
    top-left); marked_ids are the record ids of Klaus-marked annotations
    present (legacy K-077 adopted copies live in the file marked).

    Returns None when the file is missing or unreadable — callers must
    NOT treat that as "clean": a failed scan must never mass-remove
    mirrored records. Never raises."""
    out: list[dict] = []
    marked_ids: set[str] = set()
    try:
        if not BAKE_AVAILABLE:
            return None
        working = _working_pdf_path(user_files_dir, name)
        if not os.path.isfile(working):
            return None
        # Fingerprint of the file THIS scan reads (K-086): scans run on
        # threads and can complete out of order; the mirror discards a
        # result whose fingerprint no longer matches the file.
        st = os.stat(working)
        stat = (st.st_ino, st.st_mtime_ns, st.st_size)
        reader = PdfReader(working)
        for pageno, pg in enumerate(reader.pages):
            ph, ox, oy = _page_frame(pg)
            for ref in _annots_of(pg):
                try:
                    o = ref.get_object()
                    sub = str(o.get("/Subtype"))
                    if sub not in ("/Highlight", "/FreeText"):
                        continue
                    nm = str(o.get("/NM") or "")
                    if nm.startswith(_KLAUS_NM):
                        tail = nm[len(_KLAUS_NM):]
                        # Only PRIMARY marks count as present (K-085):
                        # a suffixed satellite (the ":note" sticky) left
                        # behind after Preview deleted the highlight
                        # must not mask that deletion.
                        if ":" not in tail:
                            marked_ids.add(tail)
                        continue
                    contents = o.get("/Contents")
                    contents = str(contents) if contents else ""
                    if sub == "/Highlight":
                        rects = _quads_to_qt_rects(o, ph, ox, oy)
                        if not rects:
                            continue
                        out.append({
                            "kind": "highlight",
                            "page": pageno,
                            "rects": rects,
                            "note": contents,
                            "color": _annot_color(o) or _HIGHLIGHT_COLOR_DEFAULT,
                        })
                    else:
                        rect = _rect_to_qt(o.get("/Rect"), ph, ox, oy)
                        # NOT the raw /Contents: Preview omits it and
                        # keeps the text in /AP only (K-080).
                        text = _freetext_text(o, reader)
                        if rect is None or not text.strip():
                            continue
                        color, size = _freetext_style(o)
                        rec: dict = {
                            "kind": "text",
                            "page": pageno,
                            "rects": [rect],
                            "text": text,
                            "note": "",
                            "color": color,
                        }
                        if size:
                            rec["size"] = size
                        out.append(rec)
                except Exception:
                    continue
    except Exception as exc:
        print(f"[klausmate] foreign annotation scan failed for {name}: {exc}")
        return None
    return {
        "foreign": out,
        "marked_ids": marked_ids,
        "page_count": len(reader.pages),
        "stat": stat,
    }


def _capture_pristine_stripped(
    user_files_dir: str, name: str, working: str
) -> bool:
    """First-adoption pristine capture: the baseline must NOT contain
    the foreign annotations being adopted, or every regenerating bake
    would double them (pristine copy + marked Klaus copy). A pristine
    that already exists predates the foreign markup and stands."""
    try:
        base = _safe_basename(name)
        pristine = os.path.join(_originals_dir(user_files_dir), base + ".pdf")
        if os.path.isfile(pristine):
            return True
        reader = PdfReader(working)
        writer = PdfWriter(clone_from=reader)
        for pg in writer.pages:
            annots = _annots_of(pg)
            if not annots:
                continue
            kept = []
            for ref in annots:
                try:
                    o = ref.get_object()
                    sub = str(o.get("/Subtype"))
                    if sub in ("/Highlight", "/FreeText") and not str(
                        o.get("/NM") or ""
                    ).startswith(_KLAUS_NM):
                        continue
                except Exception:
                    pass
                kept.append(ref)
            if len(kept) == len(annots):
                continue
            if kept:
                pg[_BakeName("/Annots")] = _BakeArray(kept)
            else:
                del pg[_BakeName("/Annots")]
        os.makedirs(_originals_dir(user_files_dir), exist_ok=True)
        tmp = pristine + f".{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "wb") as f:
                writer.write(f)
            os.replace(tmp, pristine)
        finally:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        print(f"[klausmate] captured pristine (foreign-stripped): {base}.pdf")
        return True
    except Exception as exc:
        print(f"[klausmate] stripped pristine capture failed for {name}: {exc}")
        return False


def _bbox_of(rec: dict) -> list[float] | None:
    """Union bounding box of a record's rects in page points."""
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for r in rec.get("rects") or []:
        try:
            x, y, w, h = (float(v) for v in r)
        except Exception:
            continue
        xs0.append(x)
        ys0.append(y)
        xs1.append(x + w)
        ys1.append(y + h)
    if not xs0:
        return None
    return [min(xs0), min(ys0), max(xs1) - min(xs0), max(ys1) - min(ys0)]


def _overlaps(a: list[float], b: list[float]) -> bool:
    """True when boxes overlap meaningfully (intersection >= 30% of the
    smaller area). Tolerant enough to recognize an outside annotation
    whose box drifted between Preview autosaves (K-081), strict enough
    to keep genuinely separate side-by-side notes apart."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    if inter <= 0.0:
        return False
    smaller = min(max(aw, 0.0) * max(ah, 0.0), max(bw, 0.0) * max(bh, 0.0))
    if smaller <= 0.0:
        return True
    return inter >= 0.3 * smaller


def _same_annotation(a: dict, b: dict) -> bool:
    """Same page, same kind, overlapping boxes — two sightings of ONE
    outside annotation (possibly edited in between)."""
    if a.get("page") != b.get("page"):
        return False
    ka = "text" if a.get("kind") == "text" else "highlight"
    kb = "text" if b.get("kind") == "text" else "highlight"
    if ka != kb:
        return False
    ba = _bbox_of(a)
    bb = _bbox_of(b)
    if ba is None or bb is None:
        return False
    return _overlaps(ba, bb)


def _record_signature(rec: dict) -> tuple:
    return (
        rec.get("page"),
        "text" if rec.get("kind") == "text" else "highlight",
        tuple(
            tuple(round(float(v), 1) for v in r)
            for r in rec.get("rects") or []
        ),
        (rec.get("text") or "") if rec.get("kind") == "text" else "",
    )


def _tombstone_hits(s: dict, rec: dict) -> bool:
    """PRECISE tombstone match (K-084): same page and kind, equal text
    for text marks, and bounding box within 3pt per coordinate — i.e.
    the specific deleted mark resurfacing, NOT a new mark the user drew
    near the same spot (the old 30%-overlap match blocked those:
    'sometimes my highlight doesn't appear')."""
    ts = s.get("ts")
    if (
        not isinstance(ts, (int, float))
        or time.time() - float(ts) > 600.0
    ):
        # TTL (K-086): a tombstone guards against a stale open model
        # resurrecting the deleted mark — a session-scoped risk. Past
        # ten minutes, an identical mark is a deliberate re-add
        # (re-highlighting the same selection yields identical quads)
        # and must import. Legacy ts-less entries count as aged.
        return False
    if s.get("page") != rec.get("page"):
        return False
    kind = "text" if rec.get("kind") == "text" else "highlight"
    if ("text" if s.get("kind") == "text" else "highlight") != kind:
        return False
    if kind == "text" and (
        str(s.get("text") or "").strip()
        != str(rec.get("text") or "").strip()
    ):
        return False
    fb = _bbox_of(rec)
    if fb is None:
        return False
    if isinstance(s.get("rects"), list) and s["rects"]:
        sb = _bbox_of({"rects": s["rects"]})
    elif isinstance(s.get("rect"), list) and len(s["rect"]) == 4:
        sb = [float(v) for v in s["rect"]]  # legacy K-081 entries
    else:
        sb = None
    if sb is None:
        return False
    return all(abs(float(a) - float(b)) <= 3.0 for a, b in zip(sb, fb))


def _matches_tombstone(rec: dict, suppressed: list[dict]) -> bool:
    return any(_tombstone_hits(s, rec) for s in suppressed)


def _mirror_core(
    user_files_dir: str,
    name: str,
    foreign: list[dict],
    marked_ids: set[str] | None,
    remove_missing: bool,
) -> int:
    """Shared add/update(/remove) pass keeping records in step with the
    file's outside marks. Overlap = same annotation (K-081: Preview
    autosaves while typing; every snapshot differs slightly). With
    ``remove_missing``, external records with no counterpart in the file
    are dropped (Preview-side deletes propagate, K-082) — unless their
    id is in ``marked_ids`` (legacy K-077 adopted copies live in the
    file Klaus-marked)."""
    records = load_annotations(user_files_dir, name)
    changes = 0
    # Self-heal (K-081): overlapping EXTERNAL records of the same kind
    # on the same page are generations of one outside annotation —
    # keep the newest. Native Klaus records are never touched.
    kept: list[dict] = []
    for rec in records:
        if rec.get("origin") == "external":
            for i, prev in enumerate(kept):
                if (
                    prev.get("origin") == "external"
                    and _same_annotation(prev, rec)
                ):
                    kept[i] = rec
                    changes += 1
                    break
            else:
                kept.append(rec)
        else:
            kept.append(rec)
    records = kept
    suppressed = load_suppressed(user_files_dir, name)
    sig_map = {_record_signature(r): r for r in records}
    matched: set[str] = set()
    for f in foreign:
        hit = sig_map.get(_record_signature(f))
        if hit is not None:
            if hit.get("origin") == "external":
                matched.add(str(hit.get("id")))
            continue
        if _matches_tombstone(f, suppressed):
            continue
        target = next(
            (
                r
                for r in records
                if r.get("origin") == "external" and _same_annotation(r, f)
            ),
            None,
        )
        if target is not None:
            # Same spot -> the outside annotation was EDITED (Preview
            # autosaves mid-typing): update in place, never append.
            matched.add(str(target.get("id")))
            updated = False
            for key in ("rects", "text", "color", "size", "note"):
                if key in f and f.get(key) != target.get(key):
                    target[key] = f[key]
                    updated = True
            if updated:
                changes += 1
            sig_map[_record_signature(target)] = target
            continue
        rec = dict(f)
        rec["id"] = uuid.uuid4().hex
        rec["origin"] = "external"
        records.append(rec)
        sig_map[_record_signature(rec)] = rec
        matched.add(rec["id"])
        changes += 1
    if remove_missing:
        marked = {str(x) for x in (marked_ids or set())}
        doc = _load_annotation_doc(user_files_dir, name)
        baked = {str(x) for x in (doc.get("baked_native_ids") or [])}
        # Legacy reconciliation (K-087): a json predating the ledger
        # can never satisfy "was baked", so pre-ledger highlights were
        # undeletable from outside apps. Trust the file ONCE — but only
        # when it is NEWER than the records, so a bake still pending
        # (records newer) can never be mistaken for an outside delete.
        if "baked_native_ids" not in doc:
            try:
                pdf_mtime = os.path.getmtime(
                    _working_pdf_path(user_files_dir, name)
                )
                json_mtime = os.path.getmtime(
                    annotations_path_for(user_files_dir, name)
                )
            except OSError:
                pdf_mtime = json_mtime = 0.0
            if pdf_mtime > json_mtime:
                baked |= {
                    str(r.get("id"))
                    for r in records
                    if r.get("origin") != "external"
                }
        # Self-seed (K-087): a mark observed in the file IS baked, so
        # the ledger heals itself for records baked before it existed.
        baked |= {str(r.get("id")) for r in records if str(r.get("id")) in marked}
        survivors: list[dict] = []
        removed_native: list[dict] = []
        for r in records:
            rid = str(r.get("id"))
            if (
                r.get("origin") == "external"
                and rid not in matched
                and rid not in marked
            ):
                # Its original left the file — deleted outside.
                changes += 1
                continue
            if (
                r.get("origin") != "external"
                and rid in baked
                and rid not in marked
            ):
                # Its mark was in the file and is gone from this FRESH
                # scan: deleted in the outside app (K-087 — the old
                # "at least one Klaus mark must survive" guard made
                # deleting the last/only highlight impossible, and no
                # content signal can separate that from a stale-model
                # save, so the removal is trusted and the record is
                # kept in the recovery bucket instead).
                removed_native.append({"ts": time.time(), "record": r})
                changes += 1
                continue
            survivors.append(r)
        records = survivors
        live_ids = {str(r.get("id")) for r in records}
        updates: dict = {"baked_native_ids": sorted(baked & live_ids)}
        if removed_native:
            cutoff = time.time() - 86400.0
            bucket = [
                e
                for e in load_removed_native(user_files_dir, name)
                if float(e.get("ts") or 0) >= cutoff
            ]
            bucket.extend(removed_native)
            updates["removed_native"] = bucket[-50:]
            print(
                f"[klausmate] {len(removed_native)} highlight(s) deleted "
                f"outside — removed from {name} (recoverable for 24h)"
            )
        _update_doc_keys(user_files_dir, name, updates)
        if suppressed:
            # Tombstone expiry (K-084): the stale copy it guards
            # against is no longer in the file — job done. If it were
            # still being resurrected by an open stale model, this very
            # scan would contain it.
            still = [
                s
                for s in suppressed
                if any(_tombstone_hits(s, f) for f in foreign)
            ]
            if len(still) != len(suppressed):
                try:
                    _update_doc_keys(
                        user_files_dir,
                        name,
                        {"suppressed_external": still},
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[klausmate] tombstone expiry failed: {exc}")
    if changes:
        save_annotations(user_files_dir, name, records)
        print(
            f"[klausmate] synced {changes} outside annotation "
            f"change(s) for {name}"
        )
    return changes


def adopt_foreign_annotations(
    user_files_dir: str, name: str, scanned: list[dict] | None = None
) -> int:
    """Add/update pass only (no removals) — kept for callers and tests
    that feed a bare foreign list. The live viewer path uses
    ``mirror_foreign_annotations``. Never raises."""
    try:
        foreign = (
            scanned
            if scanned is not None
            else scan_foreign_annotations(user_files_dir, name)
        )
        if foreign:
            working = _working_pdf_path(user_files_dir, name)
            if not _capture_pristine_stripped(user_files_dir, name, working):
                foreign = []
        return _mirror_core(
            user_files_dir, name, foreign, None, remove_missing=False
        )
    except Exception as exc:
        print(f"[klausmate] foreign annotation adopt failed for {name}: {exc}")
        return 0


def mirror_foreign_annotations(
    user_files_dir: str, name: str, scan_result: dict | None
) -> int:
    """K-082: the FILE is the source of truth for outside marks; records
    mirror it — adds, in-place updates, and removals when the original
    left the file. ``scan_result`` comes from scan_working_annotations;
    None (failed scan) is a guarded no-op so a read hiccup can never
    mass-delete mirrored records. Never raises."""
    try:
        if not isinstance(scan_result, dict):
            return 0
        scanned_stat = scan_result.get("stat")
        if scanned_stat is not None:
            # Stale-apply guard (K-086): scans run on threads and can
            # land out of order — applying an older scan after a newer
            # one re-imports marks already gone ("ghost highlights").
            # The file changed since this scan read it? Discard; the
            # tick machinery always follows a change with a fresh pass.
            try:
                working = _working_pdf_path(user_files_dir, name)
                st = os.stat(working)
                if (st.st_ino, st.st_mtime_ns, st.st_size) != tuple(
                    scanned_stat
                ):
                    print(
                        f"[klausmate] stale mirror scan discarded "
                        f"for {name}"
                    )
                    return 0
            except OSError:
                return 0
        foreign = list(scan_result.get("foreign") or [])
        marked = {str(x) for x in scan_result.get("marked_ids") or []}
        if foreign:
            working = _working_pdf_path(user_files_dir, name)
            if not _capture_pristine_stripped(user_files_dir, name, working):
                return 0
        return _mirror_core(
            user_files_dir, name, foreign, marked, remove_missing=True
        )
    except Exception as exc:
        print(f"[klausmate] mirror failed for {name}: {exc}")
        return 0


def list_contexts(user_files_dir: str) -> list[str]:
    """All stored context files — one ``.txt`` per PDF (multi-PDF model).

    This used to return ONLY the active PDF's context (a single-PDF-era
    fossil). Once an active pointer was set, that emptied the ＋ menu
    (the active PDF is always an open tab, which the menu filters out)
    and made session restore drop every non-active tab.
    """
    ctx_dir = os.path.join(user_files_dir, "contexts")
    if not os.path.isdir(ctx_dir):
        return []
    return sorted(f for f in os.listdir(ctx_dir) if f.endswith(".txt"))


def delete_context(user_files_dir: str, name: str) -> None:
    base = _safe_basename(name)
    candidates = [
        os.path.join(user_files_dir, "contexts", base + ".txt"),
        os.path.join(user_files_dir, "contexts", base + ".json"),
        os.path.join(user_files_dir, "pdfs", base + ".pdf"),
        os.path.join(user_files_dir, "annotations", base + ".json"),
        os.path.join(user_files_dir, "pdf_originals", base + ".pdf"),
        os.path.join(user_files_dir, "contexts", name),
    ]
    # A migrated PDF's real file lives outside user_files_dir entirely
    # (see migrate_to_root) — the candidates above can never reach it, so
    # without this a delete would only clear the Klaus-private siblings
    # and leave the actual PDF orphaned in the Library folder.
    library_map = load_library_map(user_files_dir)
    mapped_rel = library_map.pop(base, None)
    if mapped_rel:
        root = _live_library_root()
        if root:
            candidates.append(os.path.join(root, mapped_rel))
        try:
            save_library_map(user_files_dir, library_map)
        except OSError as exc:
            print(f"[klausmate] library_map cleanup failed for {base}: {exc}")
    for path in candidates:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    # Lazy import: pdf_index imports our _chunk_text at module level.
    try:
        from . import pdf_index

        pdf_index.delete(user_files_dir, base)
    except Exception as exc:
        print(f"[klausmate] pdf_index cleanup failed for {base}: {exc}")
    try:
        from . import drive_store

        drive_store.remove_pdf(user_files_dir, base)
    except Exception as exc:
        print(f"[klausmate] drive cleanup failed for {base}: {exc}")
    # prefs.json (sensitivity threshold, etc.) is a SIBLING of contexts/
    # pdfs/annotations — the candidates list above can never reach it, so
    # without this a re-import under the same safe basename would
    # silently inherit a stale entry forever.
    try:
        from . import retention

        retention.forget_prefs(base)
    except Exception as exc:
        print(f"[klausmate] prefs cleanup failed for {base}: {exc}")
    # retention_history.json is a sibling too, with the same blind spot:
    # a re-import under this safe basename would otherwise inherit the
    # deleted PDF's whole retention curve.
    try:
        from . import retention_history

        retention_history.forget_history(user_files_dir, base)
    except Exception as exc:
        print(f"[klausmate] retention history cleanup failed for {base}: {exc}")
    if get_active_pdf(user_files_dir) == base:
        clear_active_pdf(user_files_dir)


# ----------------------------- chunking ----------------------------------

_CHUNK_SIZE = 400
_CHUNK_OVERLAP = 50


def _chunk_text(text: str, source: str) -> list[dict]:
    chunks: list[dict] = []
    text = text.strip()
    if not text:
        return chunks
    i = 0
    n = len(text)
    while i < n:
        end = min(i + _CHUNK_SIZE, n)
        if end < n:
            window = text[i:end]
            for sep in ("\n\n", ". ", "\n"):
                idx = window.rfind(sep)
                if idx >= _CHUNK_SIZE // 2:
                    end = i + idx + len(sep)
                    break
        chunk_text = text[i:end].strip()
        if chunk_text:
            # "start" = offset into the (stripped) input text; pdf_index uses
            # it for stable chunk identity. BM25/curation ignore it.
            chunks.append({"source": source, "text": chunk_text, "start": i})
        if end >= n:
            break
        i = max(end - _CHUNK_OVERLAP, i + 1)
    return chunks

