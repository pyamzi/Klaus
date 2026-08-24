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
        Highlight as _BakeHighlight,
        Text as _BakeText,
    )
    from pypdf.generic import (  # type: ignore
        ArrayObject as _BakeArray,
        FloatObject as _BakeFloat,
    )

    BAKE_AVAILABLE = True
except Exception:
    BAKE_AVAILABLE = False

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


def save_pdf(user_files_dir: str, name: str, raw_path: str) -> dict:
    """Ingest a PDF: per-page text, BM25 .txt, page JSON, raw .pdf copy."""
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
    user_files_dir: str, root: str, folders: dict | None = None
) -> dict:
    """Move every stored PDF's baked copy out of the legacy ``pdfs/``
    store into ``root``, laid out to match the Library tree.

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
    return {
        "id": hl_id,
        "page": page,
        "rects": clean_rects,
        "color": color,
        "note": note,
    }


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


def save_annotations(
    user_files_dir: str, name: str, highlights: list[dict]
) -> None:
    """Write highlights for ``name`` — SYNCHRONOUS by design (plan B).

    Saves are rare and tiny; a debounce would risk cross-tab loss when
    ``load_pdf`` swaps the shared QPdfDocument before the flush fires.
    """
    path = annotations_path_for(user_files_dir, name)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "highlights": list(highlights or [])}, f
            )
    except (OSError, TypeError, ValueError) as exc:
        print(f"[klausmate] failed to save annotations {path}: {exc}")


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


def bake_annotations(user_files_dir: str, name: str) -> bool:
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
            os.makedirs(_originals_dir(user_files_dir), exist_ok=True)
            shutil.copy2(working, pristine)
            print(f"[klausmate] captured pristine original: {base}.pdf")

        if not highlights:
            # Un-bake: put the pristine original back, atomically.
            _atomic_replace_from(pristine, working)
            print(f"[klausmate] un-baked (restored pristine): {base}.pdf")
            return True

        reader = PdfReader(pristine)
        writer = PdfWriter(clone_from=reader)
        n_pages = len(writer.pages)
        baked = 0
        for hl in highlights:
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
            writer.add_annotation(
                page,
                _BakeHighlight(
                    rect=(ux0, uy0, ux1, uy1),
                    quad_points=_BakeArray(_BakeFloat(v) for v in quads),
                    highlight_color="fadc50",
                    printing=True,
                ),
            )
            baked += 1
            note = hl.get("note")
            note = note.strip() if isinstance(note, str) else ""
            if note:
                # Sticky note: 18x18 icon anchored at the union's
                # top-right corner.
                writer.add_annotation(
                    page,
                    _BakeText(
                        rect=(ux1, uy1 - 18, ux1 + 18, uy1),
                        text=note,
                        open=False,
                    ),
                )

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
        print(
            f"[klausmate] baked {baked} annotation record(s) into {base}.pdf"
        )
        return True
    except Exception as exc:
        print(f"[klausmate] bake failed for {name}: {exc}")
        return False


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

