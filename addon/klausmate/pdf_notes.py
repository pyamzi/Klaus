"""Per-PDF notes — the markdown sidecar plus the appended "Notes" page.

Pouya's ask (K-079): each PDF should be "a space where you can take notes
on the side", "embedded into the PDFs in some way that's viewable in other
files but doesn't overwrite the PDF". This module is slice A (K-134): the
storage and all the page math, self-contained so the remaining K-079 work
is one call site in ``pdf_handler.bake_annotations`` plus the viewer pane.

Three layers, deliberately separate:

1. SIDECAR STORAGE — ``user_files/annotations/<safe>.notes.md``, plain
   markdown, the source of truth (a sibling of ``<safe>.json``, the
   highlights). ``load_notes`` tolerates anything; ``save_notes`` is
   atomic (tmp + ``os.replace``, retention_history.py's primitive) and
   DELETES the sidecar for empty text, so "no notes" round-trips to
   un-baked rather than leaving a stale file behind.

2. PURE LAYOUT — ``wrap_lines`` measures with the Helvetica AFM widths
   (base-14, no font file, no embedding) over WinAnsi bytes, and
   ``paginate`` cuts the wrapped lines into pages. Both are plain
   arithmetic over strings: no pypdf, no aqt, no I/O.

3. SYNTHESIS — ``notes_page_stream`` turns one page of lines into raw
   PDF content-stream bytes (``Tj``/``T*`` ops). It is still pure: it
   builds bytes, it does not build a PDF. Only ``append_notes_pages``,
   below the pypdf-glue divider, touches pypdf, and it imports lazily
   inside the function so this module imports on stdlib alone.

THE REGENERATIVE-BAKE CONTRACT. Every bake regenerates the working PDF
from the pristine original plus the FULL annotations state, never
incrementally — so appending the notes page is safe by construction: it
can never accumulate or duplicate across repeated bakes, because each
bake starts from a document that has no notes page in it. The other half
of that contract is ``notes_pages("")`` returning ZERO pages: empty notes
must append nothing at all, or an un-bake would leave a blank appendix
where the pristine original should be. That emptiness check is
load-bearing, not hygiene, and is pinned by test.

Content pages are never touched — the notes ride on appended pages only —
which is what makes this "doesn't overwrite the PDF", and they are REAL
pages rather than an embedded-file attachment, which is what makes them
"viewable in other files" (macOS Preview ignores attachments; that
alternative was rejected on the card).

Limitation v1, flagged on K-079: plain text in the WinAnsi charset. Text
outside it degrades to "?" — the same trade the base-14 fonts impose, and
the price of not embedding a font. Headings/bold/lists in the markdown are
rendered as their literal source characters; this is a notes appendix, not
a markdown renderer.
"""

from __future__ import annotations

import os
import uuid

# ---------------------------------------------------------------- storage

NOTES_SUFFIX = ".notes.md"
NOTES_SUBDIR = "annotations"

# ------------------------------------------------------------- page setup
# PDF user space: 1 unit = 1/72 inch, origin bottom-left, y up.
PAGE_WIDTH = 612.0          # US Letter — the base-14 default page
PAGE_HEIGHT = 792.0
MARGIN = 72.0               # one inch on every side
FONT_SIZE = 11.0
LEADING = 13.75             # 1.25 × font size, written out so the emitted
                            # bytes stay byte-stable under test
TITLE_FONT_SIZE = 14.0      # the design scale's section-heading size
# Vertical space the first page gives up to the "Notes — <name>" heading:
# heading baseline sits at the top margin, the first body baseline this
# far below it. paginate() charges it to page ONE only, because only page
# one carries the heading.
TITLE_RESERVE = 30.0
RULE_GAP = 8.0              # hairline under the heading, below its baseline
RULE_WIDTH = 0.6
RULE_GREY = 0.75
# The resource name the page's /Font dict binds to Helvetica. One font for
# the whole page — the heading is the same face a size up, so there is one
# width table to be right about instead of two.
FONT_RES = "F1"
# Below this a "page" is too small to lay text out on sanely (a stray or
# corrupt mediabox); fall back to Letter rather than emit hundreds of
# one-line pages.
MIN_PAGE_SIDE = 144.0

TITLE_PREFIX = "Notes — "   # em dash, per K-079's wording


def notes_path(user_files_dir: str, safe: str) -> str:
    """Where one PDF's notes sidecar lives.

    ``safe`` is the storage key — ``pdf_handler._safe_basename(name)``,
    the same key the highlights json and the retention history use, NOT
    the display name.
    """
    return os.path.join(
        user_files_dir, NOTES_SUBDIR, str(safe) + NOTES_SUFFIX
    )


def load_notes(user_files_dir: str, safe: str) -> str:
    """This PDF's notes, or "" when there are none.

    Absent, unreadable, or a directory — every miss is "". Decoding uses
    ``errors="replace"`` rather than failing: a single mangled byte must
    cost one character, never the whole note.
    """
    path = notes_path(user_files_dir, safe)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def has_notes(user_files_dir: str, safe: str) -> bool:
    """True when this PDF has non-empty notes — the cheap check a bake
    or a toolbar badge can ask without reading the text."""
    return bool(load_notes(user_files_dir, safe).strip())


def save_notes(user_files_dir: str, safe: str, text: str) -> bool:
    """Write (or delete) the notes sidecar. True on success.

    EMPTY TEXT DELETES THE FILE. Whitespace-only counts as empty. That
    is the round-trip half of the regenerative bake: clearing the pane
    must leave no sidecar, so the next bake finds no notes, appends no
    page, and restores the pristine original exactly.

    The write is atomic — a temp file in the destination directory then
    ``os.replace`` — because the notes pane autosaves on a debounce while
    the bake thread may be reading, and a torn write would hand the bake
    half a note.
    """
    path = notes_path(user_files_dir, safe)
    body = str(text or "")
    if not body.strip():
        try:
            if os.path.isfile(path):
                os.remove(path)
            return True
        except OSError as exc:
            print(f"[klausmate] notes delete failed: {path}: {exc}")
            return False
    dest_dir = os.path.dirname(path) or "."
    tmp = ""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        tmp = os.path.join(
            dest_dir, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp"
        )
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"[klausmate] notes save failed: {path}: {exc}")
        return False
    finally:
        if tmp and os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ------------------------------------------------------- Helvetica metrics
# Adobe's Helvetica AFM widths, in 1/1000 em. Codes 32..126 in order — the
# printable ASCII run, which is what the vast majority of a note is.
_ASCII_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333,   # 32  space..)
    389, 584, 278, 333, 278, 278, 556, 556, 556, 556,   # 42  *..3
    556, 556, 556, 556, 556, 556, 278, 278, 584, 584,   # 52  4..=
    584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,  # 62  >..G
    722, 278, 500, 667, 556, 833, 722, 778, 667, 778,   # 72  H..Q
    722, 667, 611, 722, 667, 944, 667, 667, 611, 278,   # 82  R..[
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556,   # 92  \..e
    278, 556, 556, 222, 222, 500, 222, 833, 556, 556,   # 102 f..o
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500,   # 112 p..y
    500, 334, 260, 334, 584,                            # 122 z..~
)

# The WinAnsi upper half (128..255). Slots cp1252 cannot produce (0x81,
# 0x8D, 0x8F, 0x90, 0x9D) are simply absent and fall to the default.
_HIGH_WIDTHS = {
    128: 556, 130: 222, 131: 556, 132: 333, 133: 1000, 134: 556,
    135: 556, 136: 333, 137: 1000, 138: 667, 139: 333, 140: 1000,
    142: 611, 145: 222, 146: 222, 147: 333, 148: 333, 149: 350,
    150: 556, 151: 1000, 152: 333, 153: 1000, 154: 500, 155: 333,
    156: 944, 158: 500, 159: 667,
    160: 278, 161: 333, 162: 556, 163: 556, 164: 556, 165: 556,
    166: 260, 167: 556, 168: 333, 169: 737, 170: 370, 171: 556,
    172: 584, 173: 333, 174: 737, 175: 333, 176: 400, 177: 584,
    178: 333, 179: 333, 180: 333, 181: 556, 182: 537, 183: 278,
    184: 333, 185: 333, 186: 365, 187: 556, 188: 834, 189: 834,
    190: 834, 191: 611,
    192: 667, 193: 667, 194: 667, 195: 667, 196: 667, 197: 667,
    198: 1000, 199: 722,
    200: 667, 201: 667, 202: 667, 203: 667,
    204: 278, 205: 278, 206: 278, 207: 278,
    208: 722, 209: 722,
    210: 778, 211: 778, 212: 778, 213: 778, 214: 778, 215: 584,
    216: 778,
    217: 722, 218: 722, 219: 722, 220: 722, 221: 667, 222: 667,
    223: 611,
    224: 556, 225: 556, 226: 556, 227: 556, 228: 556, 229: 556,
    230: 889, 231: 500,
    232: 556, 233: 556, 234: 556, 235: 556,
    236: 278, 237: 278, 238: 278, 239: 278,
    240: 556, 241: 556,
    242: 556, 243: 556, 244: 556, 245: 556, 246: 556, 247: 584,
    248: 611,
    249: 556, 250: 556, 251: 556, 252: 556, 253: 500, 254: 556,
    255: 500,
}

# Control codes and the undefined WinAnsi slots. Unreachable in practice
# (line splitting eats the newlines, ``split()`` eats the tabs) but the
# table must be total so a stray byte cannot raise mid-measure.
_DEFAULT_WIDTH = 556

HELVETICA_WIDTHS = tuple(
    _ASCII_WIDTHS[i - 32] if 32 <= i <= 126
    else _HIGH_WIDTHS.get(i, _DEFAULT_WIDTH)
    for i in range(256)
)


def encode_winansi(text) -> bytes:
    """Text as WinAnsi (cp1252) bytes, unmappable characters as "?".

    THE single place text becomes bytes, so measurement and emission can
    never disagree: ``text_width`` measures these bytes and
    ``notes_page_stream`` writes these bytes. A width computed off the
    original str would silently over-measure every character that
    degrades to a one-byte "?".
    """
    try:
        return str(text).encode("cp1252", "replace")
    except Exception:
        # Astonishingly hard to reach (cp1252 + "replace" cannot raise on
        # a str), but measurement must not be a crash site.
        return b"?" * len(str(text))


def text_width(text, font_size: float = FONT_SIZE) -> float:
    """Rendered width of ``text`` in points at ``font_size``."""
    total = 0
    for byte in encode_winansi(text):
        total += HELVETICA_WIDTHS[byte]
    try:
        return total / 1000.0 * float(font_size)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------- layout


def _split_token(token: str, avail: float, font_size: float) -> list:
    """One unbreakable token as pieces that each fit in ``avail``.

    A pasted URL is the case this exists for: greedy word wrap alone
    would set it as one line running off the right margin. Every piece
    keeps at least one character, so a token wider than the whole column
    still terminates instead of looping.
    """
    if text_width(token, font_size) <= avail:
        return [token]
    pieces = []
    cur = ""
    for ch in token:
        if cur and text_width(cur + ch, font_size) > avail:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        pieces.append(cur)
    return pieces


def _wrap_one(line: str, width: float, font_size: float) -> list:
    """Greedy word wrap of one non-empty, already-rstripped line."""
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)].expandtabs(4)
    # A deep indent would leave no usable column; drop it rather than
    # wrap two characters per line.
    if text_width(indent, font_size) > width * 0.5:
        indent = ""
    avail = width - text_width(indent, font_size)
    if avail <= 0:
        indent = ""
        avail = width
    out = []
    cur = ""
    for word in stripped.split():
        for piece in _split_token(word, avail, font_size):
            cand = piece if not cur else cur + " " + piece
            if text_width(cand, font_size) <= avail:
                cur = cand
            elif cur:
                out.append(indent + cur)
                cur = piece
            else:
                # The very first token is already wider than the column —
                # flushing here would emit a spurious blank line ahead of
                # it. Take it anyway; _split_token has already made it as
                # narrow as one character can be.
                cur = piece
    if cur or not out:
        out.append(indent + cur)
    return out


def wrap_lines(
    text, width_pt: float = PAGE_WIDTH - 2 * MARGIN,
    font_size: float = FONT_SIZE,
) -> list:
    """Note text wrapped to ``width_pt``, as a flat list of output lines.

    Blank lines are PRESERVED — a markdown note's paragraph breaks are
    its structure, and collapsing them would reflow the note into a wall.
    Trailing whitespace is trimmed off every line (invisible on the page,
    but it would push a wrap point). Leading indent is preserved and
    re-applied to continuation lines, so a wrapped bullet stays visually
    a bullet. Empty text yields no lines at all.
    """
    out: list = []
    if not text:
        return out
    try:
        width = float(width_pt)
        size = float(font_size)
    except (TypeError, ValueError):
        return out
    if width <= 0 or size <= 0:
        return out
    for raw in str(text).splitlines():
        line = raw.rstrip()
        if not line:
            out.append("")
            continue
        out.extend(_wrap_one(line, width, size))
    return out


def lines_per_page(
    page_height_pt: float = PAGE_HEIGHT,
    top_margin: float = MARGIN,
    bottom_margin: float = MARGIN,
    leading: float = LEADING,
    reserve: float = 0.0,
) -> int:
    """How many baselines fit in one page's text column.

    The first baseline sits at ``height - top - reserve``; each later one
    is ``leading`` lower; the last may not fall below the bottom margin.
    Always at least 1, so a degenerate geometry paginates badly rather
    than dropping the note on the floor.
    """
    try:
        span = (
            float(page_height_pt) - float(top_margin)
            - float(bottom_margin) - float(reserve)
        )
        lead = float(leading)
    except (TypeError, ValueError):
        return 1
    if lead <= 0:
        return 1
    return max(1, int(span // lead) + 1)


def paginate(
    lines,
    page_height_pt: float = PAGE_HEIGHT,
    top_margin: float = MARGIN,
    bottom_margin: float = MARGIN,
    leading: float = LEADING,
    first_page_reserve: float = TITLE_RESERVE,
) -> list:
    """Wrapped lines cut into pages: a list of per-page line lists.

    Page one is short by ``first_page_reserve`` because it carries the
    "Notes — <name>" heading; every later page uses the full column. No
    input lines means NO pages — never one empty page (see the module
    docstring: an empty appendix would break the un-bake).
    """
    items = list(lines or [])
    if not items:
        return []
    first_cap = lines_per_page(
        page_height_pt, top_margin, bottom_margin, leading, first_page_reserve
    )
    rest_cap = lines_per_page(
        page_height_pt, top_margin, bottom_margin, leading, 0.0
    )
    pages = []
    idx = 0
    while idx < len(items):
        cap = first_cap if not pages else rest_cap
        pages.append(items[idx: idx + cap])
        idx += cap
    return pages


def notes_pages(
    text,
    page_width_pt: float = PAGE_WIDTH,
    page_height_pt: float = PAGE_HEIGHT,
    margin_pt: float = MARGIN,
    font_size: float = FONT_SIZE,
    leading: float = LEADING,
    title_reserve: float = TITLE_RESERVE,
) -> list:
    """Note text → the pages to append: ``[[line, ...], ...]``.

    The one composed entry point the bake calls: wrap, drop trailing
    blank lines (a note ending in newlines must not buy a page of
    nothing), then paginate. Empty or whitespace-only text returns [] —
    the emptiness gate the un-bake depends on.
    """
    if not str(text or "").strip():
        return []
    try:
        width = float(page_width_pt) - 2 * float(margin_pt)
    except (TypeError, ValueError):
        return []
    lines = wrap_lines(text, width, font_size)
    while lines and not lines[-1]:
        lines.pop()
    return paginate(
        lines, page_height_pt, margin_pt, margin_pt, leading, title_reserve
    )


# -------------------------------------------------------------- synthesis


def _num(value) -> bytes:
    """A PDF real, shortest stable form — "72", "13.75", "0".

    Deterministic on purpose: the emitted content stream is asserted on
    byte-for-byte by test, because pypdf is the one dependency those
    tests cannot rely on having.
    """
    try:
        s = f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        s = "0"
    if not s or s == "-0":
        s = "0"
    return s.encode("ascii")


def pdf_literal(text) -> bytes:
    """Text as a PDF literal string, parentheses and all.

    Bytes outside printable ASCII go out as ``\\ooo`` octal escapes, so
    the whole stream stays 7-bit — a stream a human (or a failing test)
    can read is worth the three bytes.
    """
    out = bytearray(b"(")
    for byte in encode_winansi(text):
        if byte in (0x28, 0x29, 0x5C):      # ( ) \
            out += b"\\" + bytes([byte])
        elif 32 <= byte <= 126:
            out.append(byte)
        else:
            out += ("\\%03o" % byte).encode("ascii")
    out += b")"
    return bytes(out)


def notes_page_stream(
    lines,
    title=None,
    page_width_pt: float = PAGE_WIDTH,
    page_height_pt: float = PAGE_HEIGHT,
    margin_pt: float = MARGIN,
    font_size: float = FONT_SIZE,
    leading: float = LEADING,
    title_font_size: float = TITLE_FONT_SIZE,
    title_reserve: float = TITLE_RESERVE,
    font_res: str = FONT_RES,
) -> bytes:
    """One page of lines as raw PDF content-stream bytes.

    Pure: bytes in, bytes out, no pypdf — which is what lets the test
    suite assert on the exact stream under a Python that cannot import
    the vendored pypdf at all.

    ``title`` is passed for page ONE only; it draws the heading plus its
    hairline and pushes the body down by ``title_reserve`` (exactly the
    reserve ``paginate`` charged page one). Blank lines emit a bare
    ``T*``: the line advance IS the blank line, with no empty string to
    show for it. Everything sits inside ``q``/``Q`` so the page's
    graphics state is left as it was found.
    """
    parts = [b"q"]
    body_top = float(page_height_pt) - float(margin_pt)
    if title is not None:
        parts.append(b"BT")
        parts.append(b"0 g")
        parts.append(
            b"/" + str(font_res).encode("ascii") + b" "
            + _num(title_font_size) + b" Tf"
        )
        parts.append(
            b"1 0 0 1 " + _num(margin_pt) + b" " + _num(body_top) + b" Tm"
        )
        parts.append(pdf_literal(title) + b" Tj")
        parts.append(b"ET")
        rule_y = body_top - RULE_GAP
        parts.append(_num(RULE_WIDTH) + b" w")
        grey = _num(RULE_GREY)
        parts.append(grey + b" " + grey + b" " + grey + b" RG")
        parts.append(
            _num(margin_pt) + b" " + _num(rule_y) + b" m "
            + _num(float(page_width_pt) - float(margin_pt)) + b" "
            + _num(rule_y) + b" l S"
        )
        body_top -= float(title_reserve)
    rows = list(lines or [])
    if rows:
        parts.append(b"BT")
        parts.append(b"0 g")
        parts.append(
            b"/" + str(font_res).encode("ascii") + b" "
            + _num(font_size) + b" Tf"
        )
        parts.append(_num(leading) + b" TL")
        parts.append(
            b"1 0 0 1 " + _num(margin_pt) + b" " + _num(body_top) + b" Tm"
        )
        for i, line in enumerate(rows):
            if i:
                parts.append(b"T*")
            if line:
                parts.append(pdf_literal(line) + b" Tj")
        parts.append(b"ET")
    parts.append(b"Q")
    return b"\n".join(parts) + b"\n"


def notes_title(display_name) -> str:
    """The heading K-079 specified: "Notes — <display name>"."""
    return TITLE_PREFIX + str(display_name or "").strip()


# ─────────────────────────────────────────────────────────────────────
# pypdf glue — this module's equivalent of the house "aqt glue" divider.
# Nothing ABOVE it imports anything but the stdlib: no aqt (there is no
# Qt in a notes page) and no pypdf, which cannot be imported by this
# machine's python3 at all. The one function below imports pypdf lazily,
# inside itself, and degrades to "appended nothing" when it is missing.
# ─────────────────────────────────────────────────────────────────────


def append_notes_pages(writer, text, display_name) -> int:
    """Append the rendered notes page(s) to an open pypdf writer.

    Returns how many pages were appended — 0 for empty notes, and 0 (with
    a log line) when pypdf is unavailable, because a bake that cannot
    write a notes page must still bake the highlights.

    Called ONCE per bake, on a writer freshly cloned from the pristine
    original. That is the whole reason repeated bakes cannot stack notes
    pages: there were never any in the document being appended to.

    Page geometry copies the document's last page when that is a sane
    size, so the appendix looks native behind 16:9 slides instead of
    dropping a Letter sheet at the end of the deck.
    """
    try:
        body = str(text or "")
        if not body.strip():
            return 0
        import sys
        from pathlib import Path

        vendor = Path(__file__).parent / "vendor"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from pypdf.generic import (  # type: ignore
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
        )
    except Exception as exc:
        print(f"[klausmate] notes page skipped (pypdf unavailable): {exc}")
        return 0

    try:
        width, height = PAGE_WIDTH, PAGE_HEIGHT
        try:
            box = writer.pages[-1].mediabox
            w, h = float(box.width), float(box.height)
            if w >= MIN_PAGE_SIDE and h >= MIN_PAGE_SIDE:
                width, height = w, h
        except Exception:
            pass

        pages = notes_pages(body, width, height)
        if not pages:
            return 0
        title = notes_title(display_name)
        added = 0
        for i, rows in enumerate(pages):
            page = writer.add_blank_page(width=width, height=height)
            data = notes_page_stream(
                rows,
                title=title if i == 0 else None,
                page_width_pt=width,
                page_height_pt=height,
            )
            stream = DecodedStreamObject()
            stream.set_data(data)
            page[NameObject("/Contents")] = writer._add_object(stream)

            font = DictionaryObject()
            font[NameObject("/Type")] = NameObject("/Font")
            font[NameObject("/Subtype")] = NameObject("/Type1")
            font[NameObject("/BaseFont")] = NameObject("/Helvetica")
            font[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
            fonts = DictionaryObject()
            fonts[NameObject("/" + FONT_RES)] = writer._add_object(font)
            resources = DictionaryObject()
            resources[NameObject("/Font")] = fonts
            page[NameObject("/Resources")] = resources
            added += 1
        return added
    except Exception as exc:
        print(f"[klausmate] notes page append failed: {exc}")
        return 0
