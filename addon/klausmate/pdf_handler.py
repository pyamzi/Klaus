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
import shutil
import sys
import time
import uuid
from collections import Counter
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


# ----------------------------- extraction --------------------------------


def extract_text(path: str) -> str:
    return "\n\n".join(extract_pages(path))


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
    os.makedirs(user_files_dir, exist_ok=True)
    base = _safe_basename(name)
    with open(_active_pdf_path(user_files_dir), "w", encoding="utf-8") as f:
        f.write(base)


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
    ctx_dir = os.path.join(user_files_dir, "contexts")
    newest_name = names[0]
    newest_mtime = 0.0
    for n in names:
        try:
            m = os.path.getmtime(os.path.join(ctx_dir, n))
        except OSError:
            m = 0.0
        if m >= newest_mtime:
            newest_mtime = m
            newest_name = n
    base = newest_name[:-4] if newest_name.endswith(".txt") else newest_name
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
        with open(
            os.path.join(user_files_dir, _OPEN_TABS_FILE),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(data, f)
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


def save_context(user_files_dir: str, name: str, text: str) -> str:
    ctx_dir = os.path.join(user_files_dir, "contexts")
    os.makedirs(ctx_dir, exist_ok=True)
    safe = _safe_basename(name) + ".txt"
    path = os.path.join(ctx_dir, safe)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _CACHE.clear()
    return path


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
    _CACHE.clear()
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


def pdf_path_for(user_files_dir: str, name: str) -> str | None:
    base = _safe_basename(name)
    path = os.path.join(user_files_dir, "pdfs", base + ".pdf")
    return path if os.path.isfile(path) else None


def objectives_path_for(user_files_dir: str, name: str) -> str:
    base = _safe_basename(name)
    return os.path.join(user_files_dir, "objectives", base + ".txt")


def load_objectives(user_files_dir: str, name: str) -> str:
    path = objectives_path_for(user_files_dir, name)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def save_objectives(user_files_dir: str, name: str, text: str) -> None:
    obj_dir = os.path.join(user_files_dir, "objectives")
    try:
        os.makedirs(obj_dir, exist_ok=True)
        with open(objectives_path_for(user_files_dir, name), "w", encoding="utf-8") as f:
            f.write(text or "")
    except OSError:
        pass


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
        working = os.path.join(user_files_dir, "pdfs", base + ".pdf")
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
        os.path.join(user_files_dir, "objectives", base + ".txt"),
        os.path.join(user_files_dir, "annotations", base + ".json"),
        os.path.join(user_files_dir, "pdf_originals", base + ".pdf"),
        os.path.join(user_files_dir, "contexts", name),
    ]
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
    if get_active_pdf(user_files_dir) == base:
        clear_active_pdf(user_files_dir)
    _CACHE.clear()


def load_all_contexts(user_files_dir: str) -> str:
    ctx_dir = os.path.join(user_files_dir, "contexts")
    if not os.path.isdir(ctx_dir):
        return ""
    chunks: list[str] = []
    for fname in sorted(os.listdir(ctx_dir)):
        if fname.endswith(".txt"):
            with open(os.path.join(ctx_dir, fname), encoding="utf-8") as f:
                chunks.append(f.read())
    return "\n\n---\n\n".join(chunks)


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


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "at", "by", "for", "with", "as", "is", "are", "was", "were", "be", "been",
    "being", "this", "that", "these", "those", "it", "its", "from", "into",
    "than", "so", "such", "not", "no", "nor", "do", "does", "did", "has",
    "have", "had", "can", "could", "should", "would", "may", "might", "will",
    "shall", "you", "your", "we", "our", "they", "their", "i", "my", "me",
}


def _tokenize(text: str) -> list[str]:
    return [
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if len(t) > 2 and t.lower() not in _STOPWORDS
    ]


_CACHE: dict = {}


def _index_signature(ctx_dir: str) -> tuple:
    if not os.path.isdir(ctx_dir):
        return ()
    sig = []
    for fname in sorted(os.listdir(ctx_dir)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(ctx_dir, fname)
        try:
            st = os.stat(path)
            sig.append((fname, int(st.st_mtime), int(st.st_size)))
        except OSError:
            sig.append((fname, 0, 0))
    return tuple(sig)


def _build_index(ctx_dir: str) -> tuple[list[dict], dict[str, float], float]:
    all_chunks: list[dict] = []
    for fname in sorted(os.listdir(ctx_dir)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(ctx_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        source = fname[:-4] if fname.endswith(".txt") else fname
        all_chunks.extend(_chunk_text(text, source))

    if not all_chunks:
        return [], {}, 0.0

    doc_freq: Counter[str] = Counter()
    doc_lens: list[int] = []
    chunk_tokens: list[list[str]] = []
    for ch in all_chunks:
        toks = _tokenize(ch["text"])
        chunk_tokens.append(toks)
        doc_lens.append(len(toks) or 1)
        doc_freq.update(set(toks))

    n_docs = len(all_chunks)
    avg_dl = sum(doc_lens) / n_docs if n_docs else 1.0
    idf: dict[str, float] = {}
    for term, df in doc_freq.items():
        idf[term] = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))

    for i, ch in enumerate(all_chunks):
        ch["_tokens"] = chunk_tokens[i]
        ch["_dl"] = doc_lens[i]

    return all_chunks, idf, avg_dl


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_len: int,
    avg_dl: float,
    idf: dict[str, float],
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    score = 0.0
    for term in query_tokens:
        if term not in tf:
            continue
        freq = tf[term]
        idf_val = idf.get(term, 0.0)
        denom = freq + k1 * (1 - b + b * doc_len / avg_dl)
        score += idf_val * (freq * (k1 + 1)) / denom
    return score


def retrieve_relevant_chunks(
    user_files_dir: str,
    query: str,
    top_k: int = 4,
) -> list[dict]:
    ctx_dir = os.path.join(user_files_dir, "contexts")
    if not os.path.isdir(ctx_dir):
        return []

    sig = _index_signature(ctx_dir)
    cache_key = (ctx_dir, sig)
    if cache_key not in _CACHE:
        _CACHE[cache_key] = _build_index(ctx_dir)

    all_chunks, idf, avg_dl = _CACHE[cache_key]
    if not all_chunks:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        head = all_chunks[:top_k]
        return [{**c, "score": 0.0} for c in head]

    scored: list[tuple[float, dict]] = []
    for ch in all_chunks:
        s = _bm25_score(
            query_tokens,
            ch.get("_tokens", []),
            ch.get("_dl", 1),
            avg_dl,
            idf,
        )
        if s > 0:
            scored.append((s, ch))

    scored.sort(reverse=True, key=lambda x: x[0])
    if not scored:
        head = all_chunks[:top_k]
        return [
            {"source": c["source"], "text": c["text"], "score": 0.0}
            for c in head
        ]

    out: list[dict] = []
    for s, ch in scored[:top_k]:
        out.append({"source": ch["source"], "text": ch["text"], "score": s})
    return out
