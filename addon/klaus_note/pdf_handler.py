"""PDF text extraction + lightweight retrieval.

Tries to use ``pypdf`` if it's been vendored into ``klaus_note/vendor/``.
If not available, the PDF feature is disabled but the rest of the add-on
continues to work.

Retrieval (BM25): chunks of saved context files are scored against the
user's current field text, and the top-K most relevant chunks are returned.
"""

from __future__ import annotations

from . import settings

import base64
import json
import math
import os
import re
from typing import Any, Callable
import shutil
import sys
import threading
import time
import uuid
from contextlib import ExitStack
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
_KLAUS_NM = "klaus_note:"

_ACTIVE_PDF_FILE = "active_pdf.txt"


# ------------------------------- atomic writes ----------------------------
#
# Shared by every store below that can be written from more than one call
# site (pdf_tabs.json has three: open tabs per host, last_used, the
# Lecture dock's state) or that a background thread might touch
# concurrently with a read. A tmp file lives in the SAME directory as the
# target so ``os.replace`` is a same-filesystem rename: atomic, and safe
# even while something else still holds the old inode open (the bake's
# ``_commit_bake`` does the analogous thing for whole PDF files).
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


# A font whose ToUnicode CMap maps nothing (Bootcamp Heme/Onc ch. 8: Type0
# Identity-H TrueType subsets with an empty CMap and no cmap/post table)
# makes pypdf emit raw glyph IDs — "%RRWFDPS" for "Bootcamp", space as
# \x03. Small glyph IDs land in C0 controls, which a real text layer
# almost never holds (tab/newline/CR aside). Measured over 639 stored
# pages: the 11 garbled ones sit at 0.12-0.24, the worst clean one 0.011.
# ponytail: misses garbling that maps into printable characters only; add
# a word-shape signal when a PDF like that turns up.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_GARBLED_SHARE = 0.05

OCR_MODEL = "glm-ocr"
OCR_TIMEOUT_S = 120.0
OCR_PROMPT = "Text Recognition:"


def looks_garbled(text: str) -> bool:
    """True when a page's text layer is unmapped glyph IDs, not text."""
    visible = re.sub(r"[ \t\n\r]", "", text or "")
    controls = len(_CONTROL_CHARS.findall(visible))
    return controls >= 3 and controls / len(visible) > _GARBLED_SHARE


def _live_endpoint() -> str:
    try:
        from . import settings

        cfg = settings.read()
        return str(cfg.get("endpoint") or "http://127.0.0.1:11434")
    except Exception:
        return "http://127.0.0.1:11434"


def _ocr_model(client) -> str | None:
    try:
        return next(
            (m for m in client.list_models() if m.split(":")[0] == OCR_MODEL), None
        )
    except Exception:
        return None


def repair_garbled_pages(
    path: str, pages: list[str], client=None, render=None
) -> list[str]:
    """Garbled pages get OCR through local Ollama (``glm-ocr``); without
    the runtime or the model they become "" — an empty page embeds as
    nothing, a garbled one as noise that never matches a card. Ingest
    only (save_pdf, rescan_root): request-time readers keep the raw layer.

    ponytail: OCR runs synchronously on import and on a rescan of new
    files, which the Library's folder watcher triggers too (~5 s a page
    warm, measured); move it to a worker if a whole garbled deck freezes
    Anki for too long. Blanking is logged, never shown to the user."""
    flagged = [i for i, text in enumerate(pages) if looks_garbled(text)]
    if not flagged:
        return pages
    if client is None:
        from .ollama_client import OllamaClient

        client = OllamaClient(_live_endpoint(), timeout=OCR_TIMEOUT_S)
    if render is None:
        from .page_store import render_page_png as render
    model = _ocr_model(client)
    if model is None:
        print(
            f"[klaus_note] {len(flagged)} garbled page(s) in {os.path.basename(path)}; "
            f"no {OCR_MODEL} model in Ollama, leaving them blank"
        )
    pages = list(pages)
    for i in flagged:
        text = ""
        if model is not None:
            try:
                png = base64.b64encode(render(path, i)).decode("ascii")
                text = client.generate(model, OCR_PROMPT, [png]).strip()
            except Exception as exc:  # noqa: BLE001 - one failed page never stops an import
                print(f"[klaus_note] OCR failed on page {i + 1}: {exc}")
        pages[i] = text
    return pages


# One re-entrant lock per PDF (by safe basename). Library actions that
# move, rename or delete a file hold it, and a bake takes it only around
# its final path resolution + os.replace, so the two can never interleave.
# ponytail: the dict only grows (a few bytes per PDF name); prune if that matters.
_PDF_LOCKS: dict[str, threading.RLock] = {}
_PDF_LOCKS_GUARD = threading.Lock()


def pdf_lock(safe: str):
    """The re-entrant lock (a context manager) for one PDF's safe name."""
    with _PDF_LOCKS_GUARD:
        return _PDF_LOCKS.setdefault(safe, threading.RLock())


def file_stat(path: str) -> tuple | None:
    """The file fingerprint ``(st_ino, st_mtime_ns, st_size)``, or None
    when the path cannot be stat'ed."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


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
        if not isinstance(data, dict):
            return {}
        # The dock's placement memory went with the dock (Add tab,
        # 2026-10-01): an older file's keys are ignored on read and gone
        # on the next save.
        return {k: v for k, v in data.items() if k not in ("placement", "geom")}
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


def _tab_sets(data: dict) -> dict:
    """``{host_key: [names]}`` from pdf_tabs.json's ``"tabs"``. The legacy
    top-level ``"open"`` list (one tab set, before each reader had its own)
    is the editor's until the editor has a set of its own."""
    sets = data.get("tabs")
    sets = dict(sets) if isinstance(sets, dict) else {}
    legacy = data.get("open")
    if "editor" not in sets and isinstance(legacy, list):
        sets["editor"] = legacy
    return sets


def load_open_tabs(user_files_dir: str, host_key: str = "editor") -> list[str]:
    """Names of PDFs that were open as tabs in ``host_key``'s reader last
    session, filtered to contexts that still exist in the store."""
    names = _tab_sets(_load_tabs_file(user_files_dir)).get(host_key)
    names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
    stored = {
        n[:-4] if n.endswith(".txt") else n
        for n in list_contexts(user_files_dir)
    }
    return [n for n in names if n in stored]


def save_open_tabs(
    user_files_dir: str, names: list[str], host_key: str = "editor"
) -> None:
    """Store ``host_key``'s tab set beside the other hosts' sets; the first
    save moves a legacy ``"open"`` list under ``"editor"`` and drops it."""
    data = _load_tabs_file(user_files_dir)
    sets = _tab_sets(data)
    sets[host_key] = list(names)
    data.pop("open", None)
    data["tabs"] = sets
    try:
        _atomic_write_json(os.path.join(user_files_dir, _OPEN_TABS_FILE), data)
    except Exception:
        pass


def load_last_used(user_files_dir: str) -> dict:
    """{pdf name: unix timestamp of last activation} — recency ordering
    for the ＋ menu. Invalid entries are dropped."""
    data = _load_tabs_file(user_files_dir).get("last_used")
    if not isinstance(data, dict):
        return {}
    return {
        k: float(v)
        for k, v in data.items()
        if isinstance(k, str) and _finite_number(v)
    }


def _finite_number(v) -> bool:
    """A real, finite int or float from stored JSON (bools rejected). A
    hand-edited int too big for a float (``10**400``) is not one:
    ``math.isfinite`` raises OverflowError on it, which used to fail the
    whole load instead of the one value."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


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


class ReplaceRefused(OSError):
    """A Replace import whose old file could not go to the Trash (#10):
    nothing was changed, and the message says so in plain words."""


def name_in_library(user_files_dir: str, name: str) -> str | None:
    """The safe name an import of ``name`` would clash with (#10): one
    already mapped or ingested, including names that sanitize alike
    ("Lecture 1" and "Lecture_1") and names that differ only in case, as
    Anki compares tags. Returns the existing safe name in its stored
    spelling, so callers act on that entry. None when the name is free."""
    safe = _safe_basename(name)
    taken = _taken_safe_names(user_files_dir, load_library_map(user_files_dir))
    if safe in taken:
        return safe
    key = safe.casefold()
    return next((s for s in sorted(taken) if s.casefold() == key), None)


def replace_blocker(user_files_dir: str, name: str, root: str | None) -> str | None:
    """Why a Replace import of ``name`` must be refused, or None (#10).
    A mapped file that can't be reached (Library folder unavailable, or
    the file gone from it): Replace would trash nothing and still wipe
    its marks. Callers ask before closing readers; ``save_pdf`` asks too."""
    safe = name_in_library(user_files_dir, name)
    mapped = load_library_map(user_files_dir).get(safe) if safe else None
    if not mapped:
        return None
    if not (root and os.path.isdir(root)):
        where = "its Library folder isn't available"
    elif not os.path.isfile(os.path.join(root, mapped)):
        where = "its file isn't in your Library folder"
    else:
        return None
    return f"Can't replace “{os.path.basename(mapped)}”: {where}."


def save_pdf(
    user_files_dir: str,
    name: str,
    raw_path: str,
    root: str | None = None,
    replace: Callable[[str], bool] | None = None,
) -> dict:
    """Ingest a PDF: per-page text, BM25 .txt, page JSON, raw .pdf copy.

    ``root`` (K-073, single-copy invariant): with a Library root
    configured, the ONE copy of the PDF goes straight into the root —
    original filename preserved, mapping recorded — and nothing is
    written to the legacy ``pdfs/`` store. When the root directory is
    missing (unplugged drive, deleted folder) the import falls back to
    the legacy store with a printed note rather than failing — the next
    migration sweep relocates it.

    A name already in the Library (:func:`name_in_library`, #10) never
    overwrites it. By default the import is kept BESIDE it, under a
    unique file (``_unique_path``) and safe name (``_unique_safe``), the
    way the rescan ingest names new files (never a path another entry
    maps, even one missing on disk). ``replace``, the caller's
    move-to-Trash, replaces it instead. In order, under ``pdf_lock``:
    copy to a temp file beside the destination, old file to the Trash,
    temp file into place, then the old document's marks and derived
    state go (pristine copy, annotations JSON with its baked-id ledger,
    page index, page records; its prefs entry, !Library tag and
    retention history stay). Any failure before the swap changes nothing;
    :class:`ReplaceRefused` when the old file can't be reached or
    trashed.

    Returns ``name`` (the safe name used), ``page_count``, ``txt_path``
    and ``filename``, the stored file's name for the Library display.
    """
    pages = repair_garbled_pages(raw_path, extract_pages(raw_path))
    pdf_dir = os.path.join(user_files_dir, "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    in_root = bool(root and os.path.isdir(root))
    if root and not in_root:
        print(
            f"[klaus_note] Library root {root!r} is unavailable — "
            f"importing {name!r} into the legacy store instead."
        )
    mapping = load_library_map(user_files_dir)
    safe = _safe_basename(name)
    clash = name_in_library(user_files_dir, name)
    filename = _library_filename(os.path.basename(raw_path), safe)
    if clash:
        safe = clash  # the existing entry's key, case-only matches included
    mapped = mapping.get(safe) if clash else None
    prior = os.path.join(root, mapped) if in_root and mapped else None
    if replace is not None:
        blocked = replace_blocker(user_files_dir, name, root)
        if blocked:
            raise ReplaceRefused(blocked)
    taken = set(mapping.values())  # mapped files may be missing on disk
    replacing = bool(clash and replace is not None)
    old = (prior or os.path.join(pdf_dir, safe + ".pdf")) if replacing else None
    with pdf_lock(safe):
        if prior and replacing:
            pdf_dest = prior
        elif in_root:
            # Beside the clashing file, suffix off ITS name: a name that
            # only sanitizes alike ("Lecture_1" by "Lecture 1") would
            # otherwise share its tag (#14).
            start = mapped if mapped and not os.path.dirname(mapped) else filename
            pdf_dest = _unique_path(root, start, taken)
        else:
            pdf_dest = None
        if clash and replace is None:
            safe = _unique_safe(user_files_dir, mapping, safe)
        pdf_dest = pdf_dest or os.path.join(pdf_dir, safe + ".pdf")
        # Copy beside the destination first: a failed copy (disk full)
        # leaves the old file, its marks and the mapping as they were.
        tmp = os.path.join(
            os.path.dirname(pdf_dest),
            f".{os.path.basename(pdf_dest)}.{uuid.uuid4().hex}.tmp",
        )
        backup = None
        try:
            shutil.copy2(raw_path, tmp)
            if old and os.path.isfile(old):
                # A local second name for the old file: if the swap below
                # fails after the Trash move, it goes back where it was.
                backup = os.path.join(os.path.dirname(old), f".{os.path.basename(old)}.{uuid.uuid4().hex}.bak")
                try:
                    os.link(old, backup)
                except OSError:
                    shutil.copy2(old, backup)
                if replace(old) is False:
                    raise ReplaceRefused(
                        f"“{os.path.basename(old)}” couldn't be moved to "
                        "the Trash, so nothing was replaced."
                    )
            try:
                os.replace(tmp, pdf_dest)
            except OSError:
                if backup and not os.path.exists(old):
                    os.replace(backup, old)
                    backup = None
                raise
        finally:
            for leftover in (tmp, backup):
                if leftover and os.path.exists(leftover):
                    os.remove(leftover)
        if replacing:
            # The new file starts with no marks: nothing of the old one
            # may later read as "deleted outside" or rank against it.
            _drop_stale_original(user_files_dir, safe)
            marks = annotations_path_for(user_files_dir, safe)
            if os.path.isfile(marks):
                os.remove(marks)
            _drop_document_state(user_files_dir, safe)
        if in_root:
            rel = os.path.relpath(pdf_dest, root)
            if mapping.get(safe) != rel:
                mapping[safe] = rel
                save_library_map(user_files_dir, mapping)
            filename = os.path.basename(pdf_dest)

    ctx_dir = os.path.join(user_files_dir, "contexts")
    os.makedirs(ctx_dir, exist_ok=True)
    txt_path = os.path.join(ctx_dir, safe + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(pages))
    with open(os.path.join(ctx_dir, safe + ".json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages, "page_count": len(pages)}, f)

    # A fresh file under this name: any captured pristine is stale (the
    # next bake re-captures from the fresh copy).
    _drop_stale_original(user_files_dir, safe)

    set_active_pdf(user_files_dir, safe)
    # A re-import under the same basename must sort as freshly ingested,
    # not at its old recency slot (or worse, by the copied file's SOURCE
    # mtime — see list_by_recency).
    touch_last_used(user_files_dir, safe)
    return {
        "name": safe,
        "page_count": len(pages),
        "txt_path": txt_path,
        "filename": filename,
    }


# The bake's hidden tmp in the Library root (``_commit_bake``).
_BAKE_TMP = re.compile(r"^\..+\.pdf\.[0-9a-f]{32}\.tmp$")


def sweep_stranded_tmps(root: str, max_age_s: float = 3600.0) -> int:
    """Remove bake tmp files (``.<base>.pdf.<uuid>.tmp``) a crash left in
    the Library root once they are over ``max_age_s`` old (a younger one
    may belong to a bake still running). Returns how many went; never
    raises."""
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for n in names:
        path = os.path.join(root, n)
        try:
            if _BAKE_TMP.match(n) and os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        print(f"[klaus_note] swept {removed} stranded bake tmp file(s) from the Library root")
    return removed


def _drop_stale_original(user_files_dir: str, safe: str) -> None:
    """Remove ``pdf_originals/<safe>.pdf`` (the base file changed), under
    ``pdf_lock`` so no bake commits between; never raises."""
    stale_orig = os.path.join(_originals_dir(user_files_dir), safe + ".pdf")
    with pdf_lock(safe):
        if os.path.isfile(stale_orig):
            try:
                os.remove(stale_orig)
                print(f"[klaus_note] dropped stale pristine original: {safe}.pdf")
            except OSError as exc:
                print(f"[klaus_note] could not drop stale original: {exc}")


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


_LIBRARY_STATS_FILE = "library_stats.json"
_STATS_LOCK = threading.Lock()


def _stats_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, _LIBRARY_STATS_FILE)


def _read_stats_raw(user_files_dir: str) -> dict:
    """The whole sidecar including reserved ``__`` keys; {} when absent or
    corrupt."""
    try:
        with open(_stats_path(user_files_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stat_entry(stat: tuple) -> list[int]:
    """``file_stat``'s ``(ino, mtime_ns, size)`` as the sidecar's
    ``[size, mtime_ns]`` (the inode changes on every atomic replace)."""
    return [stat[2], stat[1]]


def load_library_stats(user_files_dir: str) -> dict[str, list[int]]:
    """{safe: [size, mtime_ns]} last seen for each PDF (what Klaus wrote
    or observed), so a CLOSED file changed outside Klaus is noticed.
    Corrupt or missing reads as ``{}``; keys starting ``__`` are reserved
    and skipped."""
    out: dict[str, list[int]] = {}
    for k, v in _read_stats_raw(user_files_dir).items():
        if (
            not str(k).startswith("__")
            and isinstance(v, list)
            and len(v) == 2
            and all(isinstance(n, int) for n in v)
        ):
            out[str(k)] = v
    return out


def _edit_stats(user_files_dir: str, edit) -> None:
    """Run ``edit(data)`` on the whole sidecar under the lock and write it
    back in ONE atomic write when it changed."""
    try:
        with _STATS_LOCK:
            data = _read_stats_raw(user_files_dir)
            before = dict(data)
            edit(data)
            if data != before:
                _atomic_write_json(_stats_path(user_files_dir), data)
    except OSError as e:
        print(f"[klaus_note] library_stats write failed: {e}")


def _apply_stats(user_files_dir: str, updates: dict) -> None:
    """Merge ``{safe: stat | None}`` into the sidecar (``None`` removes),
    preserving reserved ``__`` keys."""

    def edit(data: dict) -> None:
        for safe, stat in updates.items():
            if stat is None:
                data.pop(safe, None)
            else:
                data[safe] = _stat_entry(stat)

    _edit_stats(user_files_dir, edit)


_MISSING_KEY = "__missing__"


def load_missing(user_files_dir: str) -> set[str]:
    """Mapped PDFs the last rescan could not find in the Library folder."""
    v = _read_stats_raw(user_files_dir).get(_MISSING_KEY)
    return {str(s) for s in v} if isinstance(v, list) else set()


def set_missing(user_files_dir: str, safes) -> None:
    """Persist the missing set (empty drops the key)."""
    want = sorted(set(safes))

    def edit(data: dict) -> None:
        if want:
            data[_MISSING_KEY] = want
        else:
            data.pop(_MISSING_KEY, None)

    _edit_stats(user_files_dir, edit)


def record_stat(user_files_dir: str, safe: str, stat: tuple | None) -> None:
    """Record ``safe``'s fingerprint after a Klaus write (``stat`` is
    ``file_stat``'s tuple); ``None`` removes the entry."""
    _apply_stats(user_files_dir, {safe: stat})


def changed_since_recorded(
    user_files_dir: str, root: str, mapping: dict, record_changed: bool = True
) -> list[str]:
    """Safe names in ``mapping`` ({safe: path relative to ``root``}) whose
    current ``[size, mtime_ns]`` differs from the recorded one. A changed
    file is reported once (its new value is recorded); an unrecorded name
    is recorded, not reported; a missing file is neither.
    ``record_changed=False`` leaves a changed file's entry alone, so it is
    reported again until the caller records it (the rescan does, once
    its new text is stored)."""
    recorded = load_library_stats(user_files_dir)
    changed: list[str] = []
    updates: dict[str, tuple] = {}
    for safe, rel in mapping.items():
        if str(safe).startswith("__"):
            continue
        st = file_stat(os.path.join(root, rel))
        if st is None or recorded.get(safe) == _stat_entry(st):
            continue
        if safe in recorded:
            changed.append(safe)
            if not record_changed:
                continue
        updates[safe] = st
    if updates:
        _apply_stats(user_files_dir, updates)
    return changed


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

    ``pdf_path_for``'s two production call sites (reader_panel.py,
    __init__.py) only ever pass ``(user_files_dir, name)`` — this is the
    one spot in this otherwise aqt-free module that reaches for the
    config, and only as a fallback when no ``root`` was passed in
    explicitly. Guarded so the module keeps importing cleanly with no aqt
    present (the headless test harness) — tests instead pass ``root=``
    directly and never hit this path.
    """
    try:
        from . import settings

        cfg = settings.read()
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


def _unique_path(dest_dir: str, filename: str, taken=()) -> str:
    """``filename`` under ``dest_dir``, suffixed " (1)", " (2)", ... on a
    collision. Never returns a path that already exists on disk, nor one
    whose path relative to ``dest_dir`` is in ``taken``."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    n = 1
    while os.path.isfile(candidate) or os.path.relpath(candidate, dest_dir) in taken:
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
                f"[klaus_note] migration: moved {safe} but could not remove "
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
    with pdf_lock(safe):
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
    with pdf_lock(safe):
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
    old_prefix = old.rstrip("/") + "/"
    # Every PDF under the folder, locked in name order so two folder
    # actions can never wait on each other.
    under = sorted(
        safe
        for safe, rel in load_library_map(user_files_dir).items()
        if rel.replace(os.sep, "/").startswith(old_prefix)
    )
    with ExitStack() as held:
        for safe in under:
            held.enter_context(pdf_lock(safe))
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        os.rename(src, dst)
        mapping = load_library_map(user_files_dir)
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


def page_fingerprint(pages: list[str] | None):
    """What survives a Finder rename: the page count plus the first
    three non-empty pages, whitespace- and case-normalised. None for a
    document with no text layer (nothing to compare)."""
    if not pages:
        return None
    texts = [t for t in (" ".join((p or "").split()).lower()[:400] for p in pages) if t]
    if not texts:
        return None
    return (len(pages), frozenset(texts[:3]))


def _same_document(a, b) -> bool:
    # Same page count and at least one shared page: a page that OCR
    # repaired at import can differ from the raw layer, the others not.
    return a is not None and b is not None and a[0] == b[0] and bool(a[1] & b[1])


def plan_rescan(mapping: dict, disk_rels: list[str], fingerprints: dict | None = None) -> dict:
    """PURE folder->Anki diff (K-073, the reverse half of K-057).

    The disk is the source of truth for structure, but matching a
    missing mapped file to a newly-appeared one is INFERENCE, so it
    follows tag_sync.plan_library_sync's confidence philosophy exactly:

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

    if missing and new and fingerprints:
        # K-309: a bulk rename in Finder (every file gets a new prefix)
        # leaves no basename to match, so the text decides. A pair must
        # be unique both ways, or neither side is guessed.
        fp_missing = fingerprints.get("missing") or {}
        fp_new = fingerprints.get("new") or {}
        cands = {s: [r for r in new if _same_document(fp_missing.get(s), fp_new.get(r))] for s in missing}
        claims: dict = {}
        for s, rs in cands.items():
            for r in rs:
                claims[r] = claims.get(r, 0) + 1
        still = []
        for s in missing:
            rs = cands[s]
            if len(rs) == 1 and claims[rs[0]] == 1:
                moves[s] = rs[0]
                new.remove(rs[0])
            else:
                still.append(s)
        missing = still

    if len(missing) == 1 and len(new) == 1:
        a = (fingerprints or {}).get("missing", {}).get(missing[0])
        b = (fingerprints or {}).get("new", {}).get(new[0])
        if a is None or b is None:  # text cannot tell; the lone pair is the rename
            moves[missing[0]] = new[0]
            missing, new = [], []

    if fingerprints and missing and new:
        # Every new file was compared with every missing one and matched
        # none: it is genuinely new, and a missing PDF is reported, not
        # guessed. Only a file whose text could not be read stays held.
        readable = [r for r in new if (fingerprints.get("new") or {}).get(r) is not None]
        return {
            "moves": moves,
            "missing": missing,
            "new": new,
            "ingestable": readable,
            "ambiguous": len(readable) < len(new),
        }

    ambiguous = bool(missing and new)
    return {
        "moves": moves,
        "missing": missing,
        "new": new,
        "ingestable": [] if ambiguous else list(new),
        "ambiguous": ambiguous,
    }


def _root_ok(root: str) -> bool:
    """The Library root exists and can be listed (os.walk swallows errors)."""
    try:
        os.listdir(root)
    except OSError:
        return False
    return os.path.isdir(root)


def prepare_rescan(user_files_dir: str, root: str) -> dict:
    """The slow half of a rescan, safe off the main thread (no Qt, no
    collection): walk the root ONCE (``"disk"``), read the text of every
    new file once, fingerprint it against the stored text of every
    missing PDF, OCR-repair the files that will be ingested, and
    re-extract (``"changed"``: {safe: {"pages", "stat"}}, the stat read
    around the extraction) mapped files that changed while closed and not
    by Klaus's own recorded write; ``"stats"`` is {rel: stat} of the new
    files as they were read.
    ``rescan_root(..., prepared=...)`` then applies the result without
    walking or touching a PDF again. ``{"root_ok": False}`` alone when
    the root is absent or unreadable."""
    if not _root_ok(root):
        return {"root_ok": False}
    mapping = load_library_map(user_files_dir)
    disk = walk_root(root)
    from . import doc_sync  # open files are their reader's job

    open_safes = doc_sync.open_paths()
    closed = {s: rel for s, rel in mapping.items() if s not in open_safes}
    changed: dict = {}
    for safe in changed_since_recorded(user_files_dir, root, closed, record_changed=False):
        # Unrecorded until apply has stored the new text: any failure on
        # the way (or a file still being written) is retried next pass.
        path = os.path.join(root, mapping[safe])
        st = file_stat(path)
        try:
            pages = repair_garbled_pages(path, extract_pages(path))
        except Exception as exc:  # noqa: BLE001 - one bad file never stops a rescan
            print(f"[klaus_note] rescan: could not re-read {safe!r}: {exc}")
            continue
        if st is not None and file_stat(path) == st:
            changed[safe] = {"pages": pages, "stat": st}
    out = {"root_ok": True, "disk": disk, "changed": changed, "fingerprints": None, "pages": {}}
    first = plan_rescan(mapping, disk)
    if not first["new"]:
        return out
    raw: dict = {}
    stats: dict = {}
    for rel in first["new"]:
        stats[rel] = file_stat(os.path.join(root, rel))
        try:
            raw[rel] = extract_pages(os.path.join(root, rel))
        except Exception as exc:  # noqa: BLE001 - an unreadable file is simply unmatched
            print(f"[klaus_note] rescan: could not read {rel!r}: {exc}")
    fingerprints = {
        "missing": {s: page_fingerprint(load_pages(user_files_dir, s)) for s in first["missing"]},
        "new": {rel: page_fingerprint(pages) for rel, pages in raw.items()},
    }
    plan = plan_rescan(mapping, disk, fingerprints if first["missing"] else None)
    pages: dict = {}
    for rel in plan["ingestable"]:
        if rel in raw:
            try:
                pages[rel] = repair_garbled_pages(os.path.join(root, rel), raw[rel])
            except Exception as exc:  # noqa: BLE001
                print(f"[klaus_note] rescan: could not repair {rel!r}: {exc}")
                pages[rel] = raw[rel]
    out.update(fingerprints=fingerprints if first["missing"] else None, pages=pages, stats=stats)
    return out


def _rel_folder(rel: str) -> str | None:
    """drive_store folder path ("A/B", forward slashes) for a root-relative
    file path, or None for the root itself."""
    d = os.path.dirname(rel)
    parts = [p for p in d.replace(os.sep, "/").split("/") if p]
    return "/".join(parts) or None


def _taken_safe_names(user_files_dir: str, mapping: dict) -> set[str]:
    """Every safe name in use: mapping entries and ingested contexts."""
    names = set(mapping)
    try:
        names.update(f[:-4] for f in os.listdir(os.path.join(user_files_dir, "contexts")) if f.endswith(".txt"))
    except OSError:
        pass
    return names


def _unique_safe(user_files_dir: str, mapping: dict, stem: str) -> str:
    """A safe name not already used by a mapping entry or a context,
    compared casefolded (a case-only twin would share a tag)."""
    base = _safe_basename(stem)
    used = {s.casefold() for s in _taken_safe_names(user_files_dir, mapping)}

    def taken(s: str) -> bool:
        return s.casefold() in used

    if not taken(base):
        return base
    n = 2
    while taken(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def _write_context(user_files_dir: str, safe: str, pages: list[str]) -> None:
    """``contexts/<safe>.txt`` and ``.json`` from ``pages``, as ingest writes them."""
    ctx_dir = os.path.join(user_files_dir, "contexts")
    _atomic_write(os.path.join(ctx_dir, safe + ".txt"), lambda f: f.write("\n\n".join(pages)))
    _atomic_write_json(os.path.join(ctx_dir, safe + ".json"), {"pages": pages, "page_count": len(pages)})


def _exists_exact(root: str, rel: str) -> bool:
    """``rel`` exists with exactly this spelling. ``os.path.isfile`` would
    say yes to ``Lecture.pdf`` after a case-only rename to ``lecture.pdf``
    on case-insensitive APFS."""
    d, base = os.path.split(os.path.join(root, rel))
    try:
        return base in os.listdir(d)
    except OSError:
        return False


def rescan_root(
    user_files_dir: str, root: str, folders: dict | None = None, prepared: dict | None = None
) -> dict:
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

    Also reports ``"moved"`` ({safe: new absolute path}), ``"missing"``
    (persisted with ``set_missing``), ``"back"`` (was missing, found
    again) and ``"changed_text"`` (closed files from ``prepared["changed"]``
    whose page text really changed). With the root unavailable nothing
    is reported or changed. ``prepared`` may be ``{}`` or None (walks).
    """
    from . import drive_store  # aqt-free; local import keeps deps one-way

    folders = folders or {}
    prepared = prepared or {}
    result: dict = {"moved": {}, "tree_changed": [], "ingested": [], "ingest_failed": [],
                    "missing": [], "ambiguous_new": [], "ambiguous": False, "back": [], "changed_text": []}
    if not prepared.get("root_ok", True) or not _root_ok(root):
        return result
    mapping = load_library_map(user_files_dir)
    disk = prepared.get("disk")
    if disk is None:
        disk = walk_root(root)
    else:
        # Mapped since the walk (the straggler sweep runs between prepare
        # and apply): present, not missing.
        seen = set(disk)
        disk = list(disk) + [rel for rel in mapping.values() if rel not in seen and _exists_exact(root, rel)]
    plan = plan_rescan(mapping, disk, prepared.get("fingerprints"))

    moved: dict = {}
    for safe, rel in sorted(plan["moves"].items()):
        mapping[safe] = rel
        moved[safe] = os.path.join(root, rel)

    ingested: list[str] = []
    ingest_failed: list[str] = []
    for rel in plan["ingestable"]:
        full = os.path.join(root, rel)
        try:
            pages = (prepared.get("pages") or {}).get(rel)
            st = (prepared.get("stats") or {}).get(rel)
            if pages is None:
                st = file_stat(full)
                pages = repair_garbled_pages(full, extract_pages(full))
        except Exception as exc:  # noqa: BLE001 - one bad file never stops a rescan
            print(f"[klaus_note] rescan: could not ingest {rel!r}: {exc}")
            ingest_failed.append(rel)
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        safe = _unique_safe(user_files_dir, mapping, stem)
        _write_context(user_files_dir, safe, pages)
        record_stat(user_files_dir, safe, st)
        mapping[safe] = rel
        ingested.append(safe)

    if moved or ingested:
        save_library_map(user_files_dir, mapping)

    changed_text: list[str] = []
    if prepared.get("changed"):
        from . import page_store

        for safe, got in sorted(prepared["changed"].items()):
            if safe not in mapping or safe in plan["missing"]:
                continue
            pages = got["pages"]
            path = os.path.join(root, mapping[safe])
            old = load_pages(user_files_dir, safe)
            try:  # the context last: a retry still sees the old text and counts the change
                _drop_stale_original(user_files_dir, safe)  # the next bake re-captures the edited file
                page_store.ensure_records(user_files_dir, safe, path, pages)
                _write_context(user_files_dir, safe, pages)
            except Exception as exc:  # noqa: BLE001 - unrecorded, so retried next pass
                print(f"[klaus_note] rescan: could not refresh {safe!r}: {exc}")
                continue
            record_stat(user_files_dir, safe, got["stat"])  # what was read, not what is there now
            if old is None or [page_store._norm(p) for p in old] != [page_store._norm(p) for p in pages]:
                changed_text.append(safe)

    was_missing = load_missing(user_files_dir)
    now_missing = set(plan["missing"])
    set_missing(user_files_dir, now_missing)

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
            print(f"[klaus_note] rescan: tree update failed for {safe!r}: {exc}")
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
            print(f"[klaus_note] rescan: bookkeeping failed for {safe!r}: {exc}")

    if plan["missing"]:
        print(
            "[klaus_note] rescan: missing from the Library folder "
            f"(nothing deleted on the Klaus side): {plan['missing']}"
        )
    if plan["ambiguous"]:
        print(
            "[klaus_note] rescan: ambiguous folder changes — "
            f"missing {plan['missing']} vs new {plan['new']}; "
            "no action taken. Undo the simultaneous rename+move batch or "
            "resolve one file at a time."
        )

    result.update(
        moved=moved,
        tree_changed=tree_changed,
        ingested=ingested,
        ingest_failed=ingest_failed,
        missing=plan["missing"],
        ambiguous_new=plan["new"] if plan["ambiguous"] else [],
        ambiguous=plan["ambiguous"],
        back=sorted((was_missing & set(mapping)) - now_missing),
        changed_text=changed_text,
    )
    return result


def annotations_path_for(user_files_dir: str, name: str) -> str:
    base = _safe_basename(name)
    return os.path.join(user_files_dir, "annotations", base + ".json")


_HIGHLIGHT_COLOR_DEFAULT = "#fadc50"


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def record_kind(rec) -> str:
    """"text" (a text box), "note" (a free-standing sticky note) or
    "highlight" (everything else, the classic shape)."""
    kind = rec.get("kind") if isinstance(rec, dict) else None
    return kind if kind in ("text", "note") else "highlight"


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
            and all(_finite_number(v) for v in r)
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
    kind = record_kind(entry)
    if kind in ("text", "note"):
        text = entry.get("text", "")
        out["kind"] = kind
        out["text"] = text if isinstance(text, str) else ""
        size = entry.get("size")
        if _finite_number(size) and size > 0:
            out["size"] = float(size)
    if kind == "note":
        # A sticky note (hand-drawn reader): never empty, and its ink is
        # one of the highlight hexes the page sends.
        if not out["text"].strip():
            return None
        if not _HEX_COLOR.match(out["color"]):
            out["color"] = _HIGHLIGHT_COLOR_DEFAULT
    card = entry.get("card")
    if (
        kind == "highlight"
        and isinstance(card, (list, tuple))
        and len(card) == 2
        and all(_finite_number(v) for v in card)
    ):
        # Where this highlight's note card sits: [dx, dy] page points
        # from the highlight's union top-right (pdfjs_pure.cardSpot).
        out["card"] = [float(card[0]), float(card[1])]
    origin = entry.get("origin")
    if isinstance(origin, str) and origin:
        out["origin"] = origin
    return out


def load_annotations(user_files_dir: str, name: str) -> list[dict]:
    """Persisted highlights for ``name`` (plan B).

    Validates every entry and skips malformed ones with a log line, so
    one corrupted record never takes down the whole file. An unreadable
    file reads as ``[]``; a caller that would write that back over the
    marks uses ``load_annotations_strict``.
    """
    out = load_annotations_strict(user_files_dir, name)
    return [] if out is None else out


def load_annotations_strict(user_files_dir: str, name: str) -> list[dict] | None:
    """``load_annotations``, but None when the file exists and cannot be
    read or parsed (a locked, half-synced or corrupt file is not "no
    marks"). A missing file is ``[]``."""
    path = annotations_path_for(user_files_dir, name)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print(f"[klaus_note] annotations unreadable: {path}")
        return None
    if not isinstance(data, dict):
        print(f"[klaus_note] annotations malformed (not a dict): {path}")
        return None
    raw = data.get("highlights")
    if not isinstance(raw, list):
        return None
    out: list[dict] = []
    for entry in raw:
        hl = _validate_highlight(entry)
        if hl is None:
            print(
                "[klaus_note] skipping malformed highlight in "
                f"{os.path.basename(path)}"
            )
            continue
        out.append(hl)
    return out


def _load_annotation_doc(user_files_dir: str, name: str) -> dict:
    """The whole annotations json as a dict (K-081) — highlights plus
    any other top-level keys (suppressed_external tombstones). For
    reads; an unreadable file reads as an empty doc."""
    doc = _load_annotation_doc_strict(user_files_dir, name)
    return {"version": 1, "highlights": []} if doc is None else doc


def _load_annotation_doc_strict(user_files_dir: str, name: str) -> dict | None:
    """The annotations doc for a read-modify-write: a fresh doc when the
    file is missing, None when it exists but cannot be read or is not a
    dict — every writer then leaves it alone rather than replace the
    marks it holds with an empty or partial set."""
    path = annotations_path_for(user_files_dir, name)
    if not os.path.isfile(path):
        return {"version": 1, "highlights": []}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def save_annotations(
    user_files_dir: str, name: str, highlights: list[dict], claim: bool = True
) -> bool:
    """Write highlights for ``name`` — SYNCHRONOUS by design (plan B).

    Saves are rare and tiny; a debounce would risk cross-tab loss when
    ``load_pdf`` moves the shared viewer to another document before the
    flush fires.
    Top-level keys other than ``highlights`` are preserved (K-081: the
    suppressed_external tombstones used to be dropped on every save).
    True when the file was written.

    ``claim`` (#11): an adopted outside record that differs from its
    stored copy was edited in Klaus, so it becomes Klaus's (see
    :func:`_claim_edited_external`). Only the outside-mark mirror, which
    writes the FILE's version of those records, passes False.
    """
    path = annotations_path_for(user_files_dir, name)
    try:
        doc = _load_annotation_doc_strict(user_files_dir, name)
        if doc is None:
            print(f"[klaus_note] annotations unreadable, not written over: {path}")
            return False
        highlights = list(highlights or [])
        if claim:
            highlights = _claim_edited_external(doc, highlights)
        doc["version"] = 1
        doc["highlights"] = highlights
        _atomic_write_json(path, doc)  # a failed write never truncates the marks
        return True
    except (OSError, TypeError, ValueError) as exc:
        print(f"[klaus_note] failed to save annotations {path}: {exc}")
        return False


def _claim_edited_external(doc: dict, highlights: list) -> list:
    """#11: Klaus owns an adopted outside mark from its first Klaus edit.

    Since K-082 the bake regenerates only native records and carries an
    outside mark's original object verbatim, so an edited external
    record never reached the file and the next mirror wrote the
    original back over it. Here, every external record that differs from
    its stored copy loses ``origin`` (the bake regenerates it, Klaus
    /NM and all) and its stored copy is tombstoned in the same write, so
    the carry drops the original from the file and the mirror never
    re-adopts it.
    """
    before: dict = {}
    for raw in doc.get("highlights") or []:
        old = _validate_highlight(raw)
        if old is not None and old.get("origin") == "external":
            before[old["id"]] = old
    if not before:
        return highlights
    out: list = []
    tombs: list[dict] = []
    for rec in highlights:
        new = _validate_highlight(rec)
        old = before.get(new["id"]) if new is not None else None
        if old is not None and new.get("origin") == "external" and new != old:
            # A claim tombstone lives until the original leaves the file
            # (the mirror sweeps it then), however late the first bake.
            tombs.append(dict(_tombstone_entry(old), claim=True))
            rec = {k: v for k, v in rec.items() if k != "origin"}
        out.append(rec)
    if tombs:
        sup = doc.get("suppressed_external")
        sup = [x for x in sup if isinstance(x, dict)] if isinstance(sup, list) else []
        doc["suppressed_external"] = sup + tombs
    return out


def _tombstone_entry(record: dict) -> dict:
    """The precise tombstone of one outside mark (K-084)."""
    return {
        "page": record.get("page"),
        "kind": record_kind(record),
        "rects": [list(r) for r in record.get("rects") or []],
        "text": str(record.get("text") or ""),
        "ts": time.time(),
    }


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
    only, like every other json write here. An unreadable doc is left
    alone; the write is atomic."""
    doc = _load_annotation_doc_strict(user_files_dir, name)
    path = annotations_path_for(user_files_dir, name)
    if doc is None:
        print(f"[klaus_note] annotations unreadable, keys not written: {path}")
        return
    doc.update(updates)
    _atomic_write_json(path, doc)


def add_suppressed(user_files_dir: str, name: str, record: dict) -> None:
    """Tombstone one external record (called on delete, K-081). Stores
    the full geometry + text so matching can be PRECISE (K-084): a
    tombstone blocks the resurrection of the specific deleted mark,
    never the location."""
    try:
        if not record.get("rects"):
            return
        sup = load_suppressed(user_files_dir, name)
        sup.append(_tombstone_entry(record))
        _update_doc_keys(user_files_dir, name, {"suppressed_external": sup})
    except Exception as exc:  # noqa: BLE001
        print(f"[klaus_note] tombstone write failed for {name}: {exc}")


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
        print(f"[klaus_note] baked-ids record failed for {name}: {exc}")


def _originals_dir(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, "pdf_originals")


class _MovedIn(Exception):
    """The file at the path the bake writes is not the one its carry scan
    read: it arrived there later (a rename the map caught up with
    mid-bake) or was saved outside Klaus meanwhile. The bake runs once
    more from it."""


def _commit_bake(
    user_files_dir: str,
    name: str,
    working: str,
    had_working: bool,
    carry_missed: bool,
    write_tmp,
    report: dict | None,
    scan_stat: tuple | None = None,
) -> bool:
    """The ONE commit tail of ``bake_annotations`` (bake and un-bake).

    ``write_tmp(tmp)`` fills a hidden tmp file; then, under ``pdf_lock``,
    the working path is resolved again and the tmp replaces it, so a
    Library rename/move that landed mid-bake is followed instead of
    forked. The tmp sits in the Library ROOT (same filesystem as every
    subfolder), not beside the file: a folder rename mid-bake would
    otherwise carry it away or remove its directory. Returns False —
    writing nothing — when the file vanished meanwhile, when a mapped file
    is missing (mid Finder rename: writing would recreate it at the old
    path; R35), or when the carry scan could not read it (its outside
    marks would be silently lost). The annotations JSON is intact; the
    pipeline retries when the file comes back. A file whose stat is no
    longer ``scan_stat`` (saved outside Klaus after the carry scan) raises
    ``_MovedIn`` instead, so the one re-bake reads that save.
    """
    base = _safe_basename(name)
    root = _live_library_root()
    root = os.path.normpath(root) if root else None
    tmp_dir = (
        root
        if root and working.startswith(root + os.sep)
        else os.path.dirname(working)
    )
    tmp = os.path.join(tmp_dir, f".{base}.pdf.{uuid.uuid4().hex}.tmp")
    try:
        write_tmp(tmp)
        with pdf_lock(base):
            final = _working_pdf_path(user_files_dir, name)
            if had_working and (carry_missed or not os.path.isfile(final)):
                # Deleted, or moved under the carry scan, while baking:
                # writing now would resurrect it or drop outside marks.
                print(f"[klaus_note] bake dropped: {base} changed under it")
                return False
            if not os.path.isfile(final) and base in load_library_map(user_files_dir):
                print(f"[klaus_note] bake dropped: {base} is missing from the Library folder")
                return False
            if not had_working and os.path.isfile(final):
                # The carry scan read no file, but replacing this one would
                # drop its outside marks: bake again from its real path.
                raise _MovedIn(final)
            if scan_stat is not None and file_stat(final) != scan_stat:
                # Saved outside Klaus after the carry scan read it:
                # replacing it now would drop that save.
                raise _MovedIn(final)
            os.replace(tmp, final)
            if report is not None:
                report["path"] = final
                report["stat"] = file_stat(final)
        return True
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _mark_klaus(anno, record: dict, suffix: str = "") -> None:
    """Stamp a pypdf annotation object with the Klaus /NM marker
    (K-077) — ``klaus_note:<record id>``, plus a suffix for satellite
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

# PDFKit (Preview) lays FreeText out this far inside its /Rect on every
# side; the reader draws a text box's glyphs AT the box edge. The bake
# outsets a text record's box by it, so the text lands where the reader
# shows it and a box measured to fit its text is not wrapped or clipped
# by the inset (rendered through PDFKit, 2026-09-30).
FREETEXT_INSET_PT = 2.0


def _num(value: float) -> str:
    """A PDF numeric token: ``12`` not ``12.0``, ``0.9804`` not
    ``0.9803921568627451`` — a content-stream operand, not a repr."""
    return f"{round(float(value), 4):g}"


NOTE_CARD_MAX_W, NOTE_CARD_MAX_H = 480.0, 720.0  # pdfjs_viewer.TEXT_BOX_MAX_W/H
_NOTE_PAD_PT = 6.0


def card_box(rec: dict, page_w: float, page_h: float, w: float, h: float) -> tuple[float, float]:
    """Top-left of a highlight's note card in page points (top-left
    origin): ``card`` [dx, dy] from the highlight's union top-right,
    else 8 pt right of it; kept inside the page. The same arithmetic as
    pdfjs_pure.cardSpot, so the file puts the card where Klaus draws it."""
    right, top = 0.0, None
    for r in rec.get("rects") or []:
        try:
            x, y, rw = float(r[0]), float(r[1]), float(r[2])
        except (TypeError, ValueError, IndexError):
            continue
        right = max(right, x + rw)
        top = y if top is None else min(top, y)
    card = rec.get("card")
    dx, dy = (float(card[0]), float(card[1])) if isinstance(card, (list, tuple)) and len(card) == 2 else (8.0, 0.0)

    def clamp(v: float, hi: float) -> float:
        return max(0.0, min(v, max(0.0, hi)))

    return clamp(right + dx, page_w - w), clamp((top or 0.0) + dy, page_h - h)


def note_card_size(text: str, size: float) -> tuple[float, float]:
    """A highlight note card's size in the file. The record stores only
    where the card sits, so this estimates it from the text: Helvetica
    at about 0.55 em per character, wrapped at 30 em, 1.15 line height,
    plus padding; capped like a text box."""
    pt = text_point_size(size)
    wrap_chars = 30.0 / 0.55
    lines = 0
    widest = 0
    for raw in str(text or "").split("\n") or [""]:
        n = len(raw)
        lines += max(1, -(-n // int(wrap_chars)))
        widest = max(widest, min(n, int(wrap_chars)))
    w = min(max(widest * 0.55 * pt + 2 * _NOTE_PAD_PT, 60.0), NOTE_CARD_MAX_W)
    h = min(lines * 1.15 * pt + 2 * _NOTE_PAD_PT, NOTE_CARD_MAX_H)
    return w, h


def _freetext(text: str, box: tuple, ox: float, oy: float, ph: float, color, size, fill=None):
    """One Helvetica /FreeText at ``box`` (x, y, w, h page points,
    top-left origin) — a text box when ``fill`` is None, a note card
    filled with that ink otherwise. Never a border (K-150)."""
    x, y, w, h = box
    inset = FREETEXT_INSET_PT
    x, y, w, h = x - inset, y - inset, w + 2 * inset, h + 2 * inset
    pt = text_point_size(size)
    free = _BakeFreeText(
        text=str(text or ""),
        rect=(ox + x, oy + ph - (y + h), ox + x + w, oy + ph - y),
        font_size=f"{pt}pt",
        font_color=_bake_color(color, "000000"),
        border_color=None,
        background_color=_bake_color(fill, "fadc50") if fill else None,
    )
    # /DA, which pypdf leaves EMPTY for a borderless box — see
    # free_text_da (K-159).
    free[_BakeName("/DA")] = _BakeString(free_text_da(color, pt))
    return free


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
    except (TypeError, ValueError, OverflowError):  # 10**400 is valid JSON
        return float(TEXT_SIZE_FALLBACK)
    if not math.isfinite(pt) or pt <= 0:
        return float(TEXT_SIZE_FALLBACK)
    return pt


def bake_annotations(
    user_files_dir: str,
    name: str,
    report: dict | None = None,
    _again: bool = True,
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
            print("[klaus_note] bake skipped: pypdf writer/annotations unavailable")
            return False
        base = _safe_basename(name)
        # The MAPPED location once migrated (K-070) — same choke point as
        # pdf_path_for, so a bake after moving the library folder writes
        # to where the file actually lives, not the old pdfs/ slot. This
        # early path only feeds the reads; the WRITE re-resolves it under
        # pdf_lock just before os.replace (a Library action may have moved
        # the file while this bake ran).
        working = _working_pdf_path(user_files_dir, name)
        had_working = os.path.isfile(working)
        pristine = os.path.join(_originals_dir(user_files_dir), base + ".pdf")
        highlights = load_annotations_strict(user_files_dir, name)
        if highlights is None:
            # Unreadable marks are not "no marks": an un-bake now would
            # strip every Klaus mark from the file. Leave it; retried.
            print(f"[klaus_note] bake skipped: {base}'s marks file is unreadable")
            return False

        # An outside save doc_sync has not reported yet, or one that landed
        # mid-bake (the _MovedIn pass): the working file is neither what
        # Klaus last wrote nor what the rescan last read, so the pristine
        # predates it and rebuilding from it would revert that save.
        # Nothing recorded: trust the pristine.
        recorded = load_library_stats(user_files_dir).get(base)
        now = file_stat(working)
        if recorded is not None and now is not None and recorded != _stat_entry(now):
            _drop_stale_original(user_files_dir, base)

        if not os.path.isfile(pristine):
            if not highlights:
                # Nothing to bake and no Klaus mark in the file — working
                # IS pristine. (A pristine dropped after an outside edit
                # leaves Klaus marks behind: those still need removing.)
                scan = scan_working_annotations(user_files_dir, name)
                if not (scan and scan.get("marked_ids")):
                    return True
            if not os.path.isfile(working):
                print(f"[klaus_note] bake failed: no stored PDF for {base}")
                return False
            # STRIPPED capture (K-082): a plain copy would smuggle the
            # outside marks into the baseline, and the carry below would
            # then double them on every bake.
            if not _capture_pristine_stripped(user_files_dir, name, working):
                print(f"[klaus_note] bake failed: pristine capture ({base})")
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
        # The file was there at the start but is not at the carry scan:
        # a Library action moved it, so its outside marks are unknown.
        carry_missed = had_working and not os.path.isfile(working)
        # The stat the pristine check above trusted: an outside save any
        # time after it (during the capture, or before the carry scan)
        # makes the commit re-bake from the new file instead of reverting
        # it — the re-bake's own check then drops the stale pristine.
        scan_stat = now
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
                    f"[klaus_note] bake: carry scan failed ({base}): {exc}"
                )
                carried = []
                # Outside marks unknown (e.g. a rename landed between the
                # isfile check and the open): drop the bake, keep the JSON.
                carry_missed = had_working

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
            if not _commit_bake(
                user_files_dir, name, working, had_working, carry_missed,
                lambda tmp: shutil.copy2(pristine, tmp), report, scan_stat,
            ):
                return False
            if report is not None:
                report["native_ids"] = []
            print(f"[klaus_note] un-baked (restored pristine): {base}.pdf")
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
                    f"[klaus_note] bake: carry failed on p{pi} "
                    f"({base}): {exc}"
                )
        baked = 0
        baked_ids_now: list[str] = []
        for hl in native_to_bake:
            page = hl.get("page")
            if not isinstance(page, int) or not (0 <= page < n_pages):
                print(
                    f"[klaus_note] bake: skipping highlight on out-of-range "
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
            kind = record_kind(hl)
            if kind in ("text", "note"):
                # A text box (K-077) or a sticky note (hand-drawn
                # reader): one Helvetica FreeText per record, rects[0]
                # its box in Qt page points; a note is filled with its
                # ink and its text is black.
                rects = hl.get("rects") or []
                if not rects:
                    continue
                box = tuple(float(v) for v in rects[0])
                if kind == "note":
                    free = _freetext(hl.get("text"), box, ox, oy, ph, "#000000",
                                     hl.get("size"), fill=hl.get("color"))
                else:
                    free = _freetext(hl.get("text"), box, ox, oy, ph,
                                     hl.get("color"), hl.get("size"))
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
            note = hl.get("note")
            note = note.strip() if isinstance(note, str) else ""
            if note:
                # The note rides in the highlight's own popup text.
                anno[_BakeName("/Contents")] = _BakeString(note)
            _mark_klaus(anno, hl)
            writer.add_annotation(page, anno)
            baked += 1
            if hl.get("id"):
                baked_ids_now.append(str(hl["id"]))
            if note:
                # ...and shows as a plain Helvetica card where Klaus
                # draws it (hand-drawn reader), in the highlight's ink.
                cw, ch = note_card_size(note, None)
                cx, cy = card_box(hl, float(mb.width), ph, cw, ch)
                card = _freetext(note, (cx, cy, cw, ch), ox, oy, ph, "#000000",
                                 None, fill=hl.get("color"))
                _mark_klaus(card, hl, suffix=":note")
                writer.add_annotation(page, card)

        def write_tmp(tmp: str) -> None:
            with open(tmp, "wb") as f:
                writer.write(f)

        if not _commit_bake(
            user_files_dir, name, working, had_working, carry_missed,
            write_tmp, report, scan_stat,
        ):
            return False
        if report is not None:
            report["native_ids"] = baked_ids_now
        print(
            f"[klaus_note] baked {baked} annotation record(s) into "
            f"{base}.pdf ({len(carried)} outside mark(s) carried)"
        )
        return True
    except _MovedIn as moved:
        if _again:  # once: the second pass reads the file it replaces
            return bake_annotations(user_files_dir, name, report, _again=False)
        print(f"[klaus_note] bake dropped: {name} kept moving ({moved})")
        return False
    except Exception as exc:
        print(f"[klaus_note] bake failed for {name}: {exc}")
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


def scan_working_annotations(user_files_dir: str, name: str) -> dict | None:
    """Everything the mirror needs from ``name``'s working PDF (K-082):

    ``{"foreign": [...], "marked_ids": set, "page_count": int}`` —
    foreign is /Highlight + /FreeText entries whose /NM lacks the
    klaus_note: marker, as records in Klaus page-point space (origin
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
        stat = file_stat(working)
        if stat is None:
            return None
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
        print(f"[klaus_note] foreign annotation scan failed for {name}: {exc}")
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
    """Pristine capture from the working file: the baseline must contain
    neither the outside highlights/text the bake carries nor ANY Klaus
    mark (``/NM`` ``klaus_note:…``, whatever its subtype, ``:note``
    stickies included) — the bake regenerates those, so a baseline
    holding them doubles every Klaus mark and makes it undeletable (a
    pristine dropped after an outside edit is re-captured from a baked
    file). A pristine that already exists stands."""
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
                    if str(o.get("/NM") or "").startswith(_KLAUS_NM) or str(
                        o.get("/Subtype")
                    ) in ("/Highlight", "/FreeText"):
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
        print(f"[klaus_note] captured pristine (foreign-stripped): {base}.pdf")
        return True
    except Exception as exc:
        print(f"[klaus_note] stripped pristine capture failed for {name}: {exc}")
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
    if record_kind(a) != record_kind(b):
        return False
    ba = _bbox_of(a)
    bb = _bbox_of(b)
    if ba is None or bb is None:
        return False
    return _overlaps(ba, bb)


def _record_signature(rec: dict) -> tuple:
    return (
        rec.get("page"),
        record_kind(rec),
        tuple(
            tuple(round(float(v), 1) for v in r)
            for r in rec.get("rects") or []
        ),
        (rec.get("text") or "") if record_kind(rec) != "highlight" else "",
    )


def _tombstone_hits(s: dict, rec: dict) -> bool:
    """PRECISE tombstone match (K-084): same page and kind, equal text
    for text marks, and bounding box within 3pt per coordinate — i.e.
    the specific deleted mark resurfacing, NOT a new mark the user drew
    near the same spot (the old 30%-overlap match blocked those:
    'sometimes my highlight doesn't appear')."""
    ts = s.get("ts")
    if not s.get("claim") and (
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
    kind = record_kind(rec)
    if record_kind(s) != kind:
        return False
    if kind != "highlight" and (
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
    records = load_annotations_strict(user_files_dir, name)
    if records is None:  # unreadable: never write the outside marks over it
        return 0
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
                f"[klaus_note] {len(removed_native)} highlight(s) deleted "
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
                    print(f"[klaus_note] tombstone expiry failed: {exc}")
    if changes:
        # The FILE's version of outside marks: never a Klaus edit (#11).
        save_annotations(user_files_dir, name, records, claim=False)
        print(
            f"[klaus_note] synced {changes} outside annotation "
            f"change(s) for {name}"
        )
    return changes


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
                if file_stat(working) != tuple(scanned_stat):
                    print(
                        f"[klaus_note] stale mirror scan discarded "
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
        print(f"[klaus_note] mirror failed for {name}: {exc}")
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


def _drop_document_state(user_files_dir: str, base: str) -> None:
    """What Klaus derived from one document's CONTENT: its page index
    (and match cache) and page records. Shared by a delete and a Replace
    import (#10). Not here: the prefs entry (it holds the PDF's !Library
    tag) and the retention history (it follows the tag's cards and can't
    be rebuilt), both of which a Replace keeps. Lazy imports avoid
    module cycles; each step is best-effort."""
    try:
        from . import pdf_index

        pdf_index.delete(user_files_dir, base)
    except Exception as exc:
        print(f"[klaus_note] pdf_index cleanup failed for {base}: {exc}")
    # user_files/pages/<safe>/ (page_store.py): a re-import under this
    # safe basename would otherwise inherit a stranger's slide text.
    try:
        from . import page_store

        shutil.rmtree(os.path.join(user_files_dir, page_store.SUBDIR, base), ignore_errors=True)
    except Exception as exc:
        print(f"[klaus_note] page record cleanup failed for {base}: {exc}")


def delete_context(user_files_dir: str, name: str, remove_file=os.remove) -> None:
    """Delete one PDF and everything Klaus derived from it. The PDF
    itself (library-root copy or legacy ``pdfs/`` copy) goes through
    ``remove_file`` — the caller passes a move-to-Trash (K-306); the
    derived files are rebuilt from it and are removed outright."""
    with pdf_lock(_safe_basename(name)):
        base = _safe_basename(name)
        source = {
            os.path.join(user_files_dir, "pdfs", base + ".pdf"),
            # The pristine pre-bake copy: once highlights are baked into the
            # library file, this is the only copy without them.
            os.path.join(user_files_dir, "pdf_originals", base + ".pdf"),
        }
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
                source.add(os.path.join(root, mapped_rel))
            try:
                save_library_map(user_files_dir, library_map)
            except OSError as exc:
                print(f"[klaus_note] library_map cleanup failed for {base}: {exc}")
        for path in candidates:
            if os.path.isfile(path):
                try:
                    (remove_file if path in source else os.remove)(path)
                except OSError:
                    pass
        # Lazy import: avoids a module cycle (pdf_index imports pdf_handler at
        # module level, for _safe_basename).
        _drop_document_state(user_files_dir, base)
        try:
            from . import drive_store

            drive_store.remove_pdf(user_files_dir, base)
        except Exception as exc:
            print(f"[klaus_note] drive cleanup failed for {base}: {exc}")
        # prefs.json (sensitivity threshold, etc.) is a SIBLING of contexts/
        # pdfs/annotations — the candidates list above can never reach it, so
        # without this a re-import under the same safe basename would
        # silently inherit a stale entry forever.
        try:
            from . import retention

            retention.forget_prefs(base)
        except Exception as exc:
            print(f"[klaus_note] prefs cleanup failed for {base}: {exc}")
        # retention_history.json is a sibling too, with the same blind spot:
        # a re-import under this safe basename would otherwise inherit the
        # deleted PDF's whole retention curve.
        try:
            from . import retention_history

            retention_history.forget_history(user_files_dir, base)
        except Exception as exc:
            print(f"[klaus_note] retention history cleanup failed for {base}: {exc}")
        if get_active_pdf(user_files_dir) == base:
            clear_active_pdf(user_files_dir)

