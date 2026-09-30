"""One record per (PDF, page): the slide's text.

The page is the seam every API-first capability keys on (spec D2): the
index embeds combined_text per page, the pertinence phase judges a card
against one page, the assistant reads one page. (Lecture transcripts
lived here too until K-314 moved recording to the Klaus app.) Records live at
user_files/pages/<pdf_safe>/<digest>/<page:04d>.json. <digest> is resolved
through a pointer file, pages/<pdf_safe>/current, and settled by
document_identity: normally text_digest(pages), a hash of the document's
own TEXT, so a bake (pdf_handler.bake_annotations rewrites the file with
os.replace) or a move inside the Library — neither changes what the page
says — cannot orphan the records; for a TEXT-LESS document (a scan with
no text layer, which has no text to be identified by) the bytes of its
pristine original instead. A legacy digest12(path) directory found with
no pointer yet (a profile indexed before this scheme existed) is adopted
in place rather than abandoned. Only a genuinely different document —
another PDF re-imported under the same safe name — repoints at a fresh
directory (see ensure_records); the old one is left on disk until
delete_context removes it.

aqt-free above the divider; render_page_png (QtPdf) sits below it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

VERSION = 1
SUBDIR = "pages"
LONG_EDGE = 1400

def digest12(path: str, stat=os.stat) -> str:
    """Legacy identity: path+size+mtime. A bake or a move changes all
    three, which is exactly why record_dir no longer resolves on this —
    kept only to recognize and adopt a directory seeded before the
    pointer scheme existed."""
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _has_path(path) -> bool:
    return bool(str(path or "").strip())


def _require_path(pdf_safe: str, path) -> None:
    """Refuse a path that cannot name anything (K-238).

    ``path`` is not this store's identity — the pointer file and
    ``document_identity`` are — but where there is no pointer yet the
    directory name IS ``digest12(path)``, and ``path == ""`` makes that
    one constant directory, the same for every caller that has lost
    track of its file. The empty path is reachable, not theoretical:
    ``pdf_handler.pdf_path_for`` answers ``""`` for a PDF whose file does
    not resolve yet. Records written to that shared bucket vanish from view the
    moment the real file resolves and the identity moves on, so the store
    refuses here rather than trusting its callers.

    Only where the path is what would be CONSULTED: a call the store can
    still answer from the document itself (a pointer already on disk, or
    ``ensure_records`` keying on the page text) is well defined without
    one and is answered.
    """
    if path == "" or not _has_path(path):
        raise ValueError(
            f"page_store: {pdf_safe!r} has no page-record directory without a PDF path"
        )


def _norm(text) -> str:
    return " ".join(str(text or "").split())


def text_digest(pages: list[str]) -> str:
    """A text-BEARING document's identity: a hash of what the pages
    actually SAY, not the file carrying them — stable across a bake's
    os.replace or a move, since neither touches the text layer.
    Whitespace is collapsed per page before hashing so re-extracting the
    same text with different line-wrapping still resolves to the same
    directory.

    Not the whole story: a text-less document (a scanned deck with no
    text layer) would hash purely on its PAGE COUNT here, since every
    page normalizes to "", so two different scans of the same length
    would collide. Those are identified by their pristine original's
    bytes instead — document_identity is the one place that decides
    which of the two a document gets, and the ONLY caller ensure_records
    asks."""
    normalized = "\x1f".join(_norm(p) for p in pages)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _textless(pages: list[str]) -> bool:
    """True when nothing in this document has any text at all — a scan
    with no text layer, and so nothing text_digest can tell apart."""
    return not any(_norm(p) for p in pages)


def _file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:12]


def document_identity(user_files: str, pdf_safe: str, path: str, pages: list[str]) -> str:
    """The directory name this document's page records live under.

    text_digest(pages) for anything with text on a page. A TEXT-LESS
    document says nothing, so it is identified by the BYTES of its
    pristine original (pdf_originals/<base>.pdf) — captured here, by the
    same stripped capture the first bake does rather than a second copy,
    when no bake has captured one yet. That file is what a bake
    regenerates FROM and never writes, and pdf_handler.save_pdf drops
    it when the PDF is re-ingested under the same safe name, so the
    digest survives every bake and move and still differs between two
    different scans of the same length.

    One edge, accepted (K-268 review): a text-less legacy directory
    (pre-pointer scheme) is recognised as this file's by the legacy
    path digest, which a bake changes — so a text-less deck that got
    records before any index run AND was baked before its first
    ensure_records starts a fresh directory; the old one stays on disk
    for delete_context, nothing is deleted.

    Nothing here may raise: a missing or unreadable file, an
    unavailable pypdf, a failed capture all fall back to text_digest
    with one log line. A page-count identity is worse than a byte one;
    an import that dies on a torn file is worse than both.
    """
    if not _textless(pages):
        return text_digest(pages)
    try:
        # Lazy: pdf_handler reaches back into this module (delete_context).
        from . import pdf_handler
        pristine = os.path.join(
            pdf_handler._originals_dir(user_files),
            pdf_handler._safe_basename(pdf_safe) + ".pdf",
        )
        if not os.path.isfile(pristine):
            pdf_handler._capture_pristine_stripped(user_files, pdf_safe, path)
        return _file_digest(pristine)
    except Exception as exc:
        print(f"[klausmate] text-less identity fell back to page count for {pdf_safe}: {exc}")
        return text_digest(pages)


def _pointer_path(user_files: str, pdf_safe: str) -> str:
    return os.path.join(user_files, SUBDIR, pdf_safe, "current")


def _read_pointer(user_files: str, pdf_safe: str) -> str | None:
    try:
        with open(_pointer_path(user_files, pdf_safe), encoding="utf-8") as f:
            digest = f.read().strip()
        return digest or None
    except OSError:
        return None


def _write_pointer(user_files: str, pdf_safe: str, digest: str) -> None:
    p = _pointer_path(user_files, pdf_safe)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(digest)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def record_dir(user_files: str, pdf_safe: str, path: str) -> str:
    """Where this PDF's page records live. The pointer file decides it
    when one exists; otherwise an on-disk legacy (path-digest) directory
    is adopted — written into the pointer so it doesn't have to be
    rediscovered next time — and failing that this is a never-seeded
    PDF, so the (not yet existing) legacy path is returned exactly as
    before.

    That last step is the only one that reads ``path``, and it is where
    an empty one is refused (``_require_path``): ``digest12("")`` is a
    constant, not a directory this document owns."""
    base = os.path.join(user_files, SUBDIR, pdf_safe)
    pointer = _read_pointer(user_files, pdf_safe)
    if pointer:
        return os.path.join(base, pointer)
    _require_path(pdf_safe, path)
    legacy = digest12(path)
    legacy_dir = os.path.join(base, legacy)
    if os.path.isdir(legacy_dir):
        try:
            _write_pointer(user_files, pdf_safe, legacy)
        except OSError as exc:
            print(f"[klausmate] page pointer adopt failed for {pdf_safe}: {exc}")
    return legacy_dir


def record_path(user_files: str, pdf_safe: str, path: str, page_index: int) -> str:
    return os.path.join(record_dir(user_files, pdf_safe, path), f"{int(page_index):04d}.json")


def _empty() -> dict:
    return {"version": VERSION, "slide_text": "", "updated_at": 0.0}


def load_record(user_files: str, pdf_safe: str, path: str, page_index: int) -> dict:
    try:
        p = record_path(user_files, pdf_safe, path, page_index)
    except ValueError as exc:
        # A reader, and its contract already answers the empty record for
        # data it cannot find (below). A raise would break every reader
        # that survives an unresolvable PDF today — the assistant's page
        # context, anki_tools' PDF search, the pertinence judge — for
        # no gain: there is nothing to read.
        print(f"[klausmate] no page record without a path: {exc}")
        return _empty()
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        if not isinstance(rec, dict):
            raise ValueError("not a page record")
        rec.pop("segments", None)  # transcripts, retired in K-314
        rec.setdefault("slide_text", "")
        rec.setdefault("version", VERSION)
        return rec
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as exc:
        print(f"[klausmate] page record unreadable, treating as empty: {p}: {exc}")
        return _empty()


def _atomic_json(p: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _same_text(rec_dir: str, pages: list[str], same_file: bool = False) -> bool:
    """True when the records already in *rec_dir* are compatible with
    what *pages* say — the same document under another directory name.

    A TEXT-LESS document is the exception, and it is why *same_file*
    exists (K-268): it has no text to be compatible WITH, so every
    record below is skipped and an all-empty directory belonging to a
    DIFFERENT scan of the same length would be adopted. For one of those, sameness has to be proved outside the
    text — *same_file*, which ensure_records sets only for the LEGACY
    (path-digest) directory, a directory reachable only through
    digest12 of the live file and so minted for this document's own
    bytes, never for a name that merely matches.

    A page with no record file yet (FileNotFoundError, or any other
    unreadable/corrupt record — same tolerance load_record gives them),
    or a record whose stored slide_text is "", has nothing to disagree
    with and is skipped rather than counted as a mismatch: a directory
    whose records are all empty or missing has nothing to disprove
    sameness with, so it is treated as the same document rather than
    orphaned. Only a stored NON-EMPTY slide_text that disagrees
    with the new text proves a different document.
    """
    if _textless(pages) and not same_file:
        return False
    for i, text in enumerate(pages):
        try:
            with open(os.path.join(rec_dir, f"{int(i):04d}.json"), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        stored = _norm((rec or {}).get("slide_text"))
        if not stored:
            continue
        if stored != _norm(text):
            return False
    return True


def ensure_records(user_files: str, pdf_safe: str, path: str, pages: list[str]) -> int:
    """Write slide_text for every page. Idempotent.

    Settles the identity pointer before seeding: adopt an on-disk legacy
    (path-digest) directory the first time one is found — a profile that
    already indexed under Plan 1 keeps its records — otherwise key on
    document_identity(pages). A pointer that already names a DIFFERENT
    identity means the PDF itself was replaced (a different document
    re-imported under the same safe name): records move to a fresh
    directory, and the old one is left on disk until delete_context
    removes it.
    """
    if not pages:
        # Nothing to seed, and the identity of "no pages" is the SAME hash a
        # path-less call would produce (text_digest([]) == digest12("")), so
        # seeding here would mint the one shared bucket every other entry
        # point now refuses (K-238 review). A PDF whose text has not been
        # extracted yet is seeded on the next pass that actually has pages.
        return 0
    td = document_identity(user_files, pdf_safe, path, pages)
    base = os.path.join(user_files, SUBDIR, pdf_safe)
    # No path, no legacy directory to adopt: digest12("") names a shared
    # bucket, never this document's own records (K-238). The identity
    # itself needs no path, so seeding still works for a caller whose PDF
    # does not resolve yet — it just keys on the text, as it always does.
    legacy = digest12(path) if _has_path(path) else None
    pointer = _read_pointer(user_files, pdf_safe)
    if pointer is None:
        pointer = legacy if legacy and os.path.isdir(os.path.join(base, legacy)) else td
        _write_pointer(user_files, pdf_safe, pointer)
    if pointer != td:
        # The pointer names a directory that is not this text's own. Two
        # cases, told apart by CONTENT, never by name: a legacy
        # (path-digest) directory holding this same document is renamed
        # onto the identity and kept; a
        # directory whose slide text differs is a replaced document and is
        # left behind for delete_context. A text-less document has no
        # slide text to tell those apart with, so for one of those only
        # the legacy directory — the one digest12 of the live file names
        # — counts as the same document (K-268).
        old_dir = os.path.join(base, pointer)
        td_dir = os.path.join(base, td)
        if os.path.isdir(old_dir) and _same_text(old_dir, pages, pointer == legacy):
            if os.path.isdir(td_dir):
                # td already has its own directory on disk, and old_dir's
                # content matches too — it is a valid home as-is (M-15).
                # os.replace onto an existing non-empty directory raises;
                # repointing anyway (the old bug) moved the pointer onto
                # td regardless, orphaning old_dir's records. Simplest
                # correct move: touch neither directory nor the pointer.
                pass
            else:
                try:
                    os.replace(old_dir, td_dir)
                except OSError as exc:
                    print(f"[klausmate] page records migrate failed for {pdf_safe}: {exc}")
                else:
                    _write_pointer(user_files, pdf_safe, td)
        else:
            _write_pointer(user_files, pdf_safe, td)
    n = 0
    for i, text in enumerate(pages):
        rec = load_record(user_files, pdf_safe, path, i)
        new_text = str(text or "")
        if rec["slide_text"] == new_text and os.path.exists(record_path(user_files, pdf_safe, path, i)):
            continue
        rec["slide_text"] = new_text
        rec["updated_at"] = time.time()
        _atomic_json(record_path(user_files, pdf_safe, path, i), rec)
        n += 1
    return n


def combined_text(rec: dict) -> str:
    """The text a page is embedded and judged by: its slide text."""
    return str(rec.get("slide_text") or "").strip()


def text_hash(rec: dict) -> str:
    return hashlib.blake2b(combined_text(rec).encode("utf-8"), digest_size=8).hexdigest()


def page_texts(user_files: str, pdf_safe: str, path: str, page_count: int) -> list[tuple[int, str, str]]:
    out = []
    for i in range(int(page_count)):
        rec = load_record(user_files, pdf_safe, path, i)
        out.append((i + 1, text_hash(rec), combined_text(rec)))
    return out


def _png_path(user_files: str, pdf_safe: str, path: str, page_index: int) -> str:
    """Where this page's rendered PNG is cached — a sibling of its JSON
    record, same directory, same stem (K-230). Moves and expires with the
    record for free: a replaced file gets a fresh record_dir and so a
    fresh cache, while a changed slide_text never
    invalidates it — only the rendered IMAGE depends on the file's own
    bytes, not on what a record stores about it, so this cache's
    invalidation is simpler than the text_hash-driven re-embed elsewhere
    in this module and must not be coupled to it."""
    return os.path.join(record_dir(user_files, pdf_safe, path), f"{int(page_index):04d}.png")


def cached_page_png(user_files: str, pdf_safe: str, path: str, page_index: int) -> bytes | None:
    """The cached render, or None on any miss — no cache yet, no record
    directory to resolve (an unresolvable path), a removed file, an
    unreadable one. Mirrors load_record's contract: a reader answers
    empty (None, here) for data it cannot find, and never raises."""
    try:
        with open(_png_path(user_files, pdf_safe, path, page_index), "rb") as f:
            return f.read()
    except Exception:
        return None


def store_page_png(user_files: str, pdf_safe: str, path: str, page_index: int, png: bytes) -> None:
    """Cache *png* beside the page's JSON record, atomically (tmp +
    os.replace, matching every other writer here). Never raises into the
    caller: the caller already has this turn's PNG from the render that
    just succeeded, so a failed cache write must not break it — log and
    move on."""
    try:
        p = _png_path(user_files, pdf_safe, path, page_index)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(png)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception as exc:
        print(f"[klausmate] page png cache write failed: {exc}")


# ---- QtPdf glue -------------------------------------------------------------

def render_page_png(path: str, page_index: int, long_edge: int = LONG_EDGE) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice, QSize
    from PyQt6.QtPdf import QPdfDocument
    doc = QPdfDocument(None)
    doc.load(path)
    if doc.status() != QPdfDocument.Status.Ready or page_index < 0 or page_index >= doc.pageCount():
        raise RuntimeError(f"cannot render page {page_index + 1} of {path}")
    pts = doc.pagePointSize(page_index)
    w, h = max(1.0, pts.width()), max(1.0, pts.height())
    scale = float(long_edge) / max(w, h)
    img = doc.render(page_index, QSize(int(round(w * scale)), int(round(h * scale))))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())
