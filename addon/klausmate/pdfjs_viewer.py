"""The PDF reader: pdf.js in an AnkiWebView (K-095/K-096; parity
K-097..K-099).

This module hosts ``web/pdfjs_viewer.html`` (vendored pdf.js 3.11.174 in
``web/pdfjs/``): canvases are GPU-composited by Chromium, scrolling
translates already-rendered layers, and the text layer gives native
browser selection. It replaced the QPdfView renderer, which flickered
because pdfium delivered page bitmaps late.

It is the only reader: the native ``PdfViewer`` was deleted in PDF
reader 5/5, so without QtWebEngine (``PDFJS_AVAILABLE``) ``PdfSidebar``
shows an "unavailable" label instead.

Division of labour (K-097..K-099): the page owns rendering and gestures;
THIS MODULE OWNS THE ANNOTATIONS JSON. JS sends mutations over the bridge
(``hl-add``/``hl-remove``/``note-edit``/``text-add``/``text-update``),
Python mutates ``_highlights``,
persists via ``pdf_handler.save_annotations``, requests the bake from
``annotation_save``'s pipeline (500 ms debounce), then pushes the canonical
records back through ``window.klausSetAnnotations``. Records keep the
schema the bake reads (0-based ``page``, ``rects`` in top-left-origin page
points), shared with K-081's external-delete tombstones.

Feed (PDF reader 2/5): Python hands the page the file length and the
first ``pdf_source.FIRST_CHUNK`` bytes; pdf.js asks for further byte
ranges over the bridge (``range``) as it needs them. Pure helpers
(:func:`first_chunk`, :func:`handle_range`, :func:`build_page_html`,
:func:`parse_bridge`, :func:`decode_b64_json`, :func:`records_from_rect_map`)
stay aqt-free for the headless tests.
"""

from __future__ import annotations

from . import settings

import base64
import colorsys
import json
import math
import threading
import uuid
from typing import Any, Callable, Optional

import os

# Guarded Qt imports — headless tests import this module with stub aqt.
try:
    from aqt import mw
    from aqt.qt import (
        QApplication,
        QImage,
        QInputDialog,
        QLabel,
        QSizePolicy,
        QTimer,
        QVBoxLayout,
        QWidget,
        Qt,
    )
    from aqt.utils import tooltip
    from aqt.webview import AnkiWebView

    PDFJS_AVAILABLE = True
except Exception:  # pragma: no cover — only in stripped test stubs
    mw = None  # type: ignore[assignment]
    QApplication = QImage = QInputDialog = None  # type: ignore
    QLabel = QSizePolicy = QTimer = QVBoxLayout = QWidget = Qt = None  # type: ignore
    tooltip = None  # type: ignore[assignment]
    AnkiWebView = None  # type: ignore[assignment]
    PDFJS_AVAILABLE = False


# ``class PdfJsViewer(None)`` is a hard TypeError AT IMPORT TIME —
# "NoneType takes no arguments" — so a partial Qt surface would not cost
# the viewer, it would cost the WHOLE MODULE: every aqt-free helper below
# (handle_range, build_page_html, parse_bridge, decode_b64_json,
# records_from_rect_map) and PDFJS_AVAILABLE itself,
# which never got to be False because the module never finished importing
# to set it. The handler above says "only in stripped test stubs", which
# is precisely where the fallback is load-bearing and precisely where it
# did not work. The None fallback is the house convention and is right for
# names used as VALUES; it is a trap for names used as BASE CLASSES. Only
# the widget needs Qt, so only the widget degrades: the base falls back to
# ``object`` and PDFJS_AVAILABLE keeps the real gate — at PdfSidebar's
# viewer branch (reader_panel.py), which is the only place one is built,
# and again in __init__ below for any caller that skips it. Same shape as
# ``index_queue._DockBase`` (K-152) and ``lecture_view._DockBase``
# (K-161); this is the third and last instance (K-164).
_WidgetBase: Any = QWidget if QWidget is not None else object


# Refuse beyond this — pdf.js keeps every fetched range in webview memory.
MAX_PDF_MB = 200

_BRIDGE_PREFIX = "klausmate_pdfjs:"

HIGHLIGHT_COLOR = "#fadc50"  # default highlight yellow (the deleted native viewer's)

# Outside-text defaults, matching what the bake assumes when a record
# omits them (12pt, black) — but written EXPLICITLY into new records:
# pdf_handler._validate_highlight backfills a missing/empty ``color``
# with the highlight YELLOW, which would repaint the text on reload.
TEXT_COLOR_DEFAULT = "#000000"
TEXT_SIZE_DEFAULT = 12.0

# Typed text is bounded before it becomes a record (K-150: the body now
# arrives over the bridge instead of out of a Qt dialog, so it is
# untrusted input like every other payload field).
MAX_TEXT_CHARS = 4000
TEXT_SIZE_MIN = 6.0
TEXT_SIZE_MAX = 96.0
# A measured row count the page may send with a commit; see
# :func:`text_box_size`.
MAX_TEXT_ROWS = 400
# Caps on a text box, in page points: the page measures inside them and
# :func:`validate_text_box` clamps whatever arrives to them.
TEXT_BOX_MAX_W = 480.0
TEXT_BOX_MAX_H = 720.0

# WCAG AA for body text. Text ink is OPAQUE glyphs on white paper, so
# legibility is a hard floor, not a preference — see :func:`ink_for_text`.
TEXT_INK_MIN_CONTRAST = 4.5

# The PDF spec caps a page dimension at 14,400 pt (200 in) — any
# coordinate beyond that is garbage whatever the document says.
MAX_PAGE_PT = 14400.0


def first_chunk(source: Any) -> tuple[int, str]:
    """Length and base64 of the first ``FIRST_CHUNK`` bytes of a
    ``pdf_source.DocSource`` — all the main thread reads at load, through
    the same source every later range comes from."""
    from .pdf_source import FIRST_CHUNK

    head = source.read(0, FIRST_CHUNK)
    return source.length, base64.b64encode(head).decode("ascii")


def _reading_dir() -> str:
    """``<user files>/reading``: where open PDFs are hard-link snapshotted."""
    from . import pdf_source

    return os.path.join(pdf_source.user_files_dir(), "reading")


_SWEPT = False  # leftover snapshots are swept once per process


def handle_range(payload: Any, source: Any, current_gen: int) -> dict:
    """Answer a ``range:<gen>:<begin>:<end>`` bridge payload.

    JS is never trusted: anything but three plain non-negative decimal
    ints is ``{"refused": True}``. Never raises."""
    if not isinstance(payload, str):
        return {"refused": True}
    try:
        parts = payload.split(":")
        if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
            return {"refused": True}
        gen, begin, end = (int(p) for p in parts)
        from .pdf_source import range_reply

        return range_reply(source, gen, current_gen, begin, end)
    except Exception as exc:
        print(f"[klausmate] pdfjs range failed: {exc}")
        return {"refused": True}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _contrast_on_white(rgb: tuple[int, int, int]) -> float:
    """WCAG contrast ratio of *rgb* against white paper."""

    def channel(c: int) -> float:
        f = c / 255.0
        return f / 12.92 if f <= 0.03928 else ((f + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 1.05 / (lum + 0.05)


def ink_for_text(hex_color: str) -> str:
    """One HIGHLIGHT ink, re-mixed as OPAQUE text ink of the same hue.

    K-149's five inks are tuned to be read THROUGH — 43% alpha over
    white paper — so at full strength they are pastel wash: yellow
    #FADC50 measures 1.36:1 against white, which as glyphs is
    unreadable. Text is the opposite problem: opaque marks on the same
    paper, where legibility is the whole job. So the two rows share
    their NAMES and their hues and nothing else, and the text value is
    DERIVED rather than hand-picked: keep the hue, floor the saturation
    (a darkened pastel goes muddy otherwise), then walk the lightness
    down until the colour clears :data:`TEXT_INK_MIN_CONTRAST` on white.

    Derivation, not a second table, so the two rows can never drift:
    edit ``theme.HIGHLIGHT_INKS`` and the text row follows, still
    legible by construction. Independent of night mode for exactly
    K-149's reason — the value bakes into the PDF's ``/C`` and that
    file opens in Preview, where night mode does not exist.
    """
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, IndexError):
        return TEXT_COLOR_DEFAULT
    h, lightness, sat = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    sat = max(sat, 0.75)
    steps = int(lightness / 0.01) + 1
    out = (0, 0, 0)
    for i in range(steps + 1):
        lit = max(lightness - i * 0.01, 0.05)
        fr, fg, fb = colorsys.hls_to_rgb(h, lit, sat)
        out = (round(fr * 255), round(fg * 255), round(fb * 255))
        if _contrast_on_white(out) >= TEXT_INK_MIN_CONTRAST:
            break
    return "#%02x%02x%02x" % out


def text_inks() -> tuple[tuple[str, str], ...]:
    """The Add Text swatch row: ``(name, #rrggbb)``, black first.

    Black leads for K-149's yellow-first reason — it IS
    :data:`TEXT_COLOR_DEFAULT`, the colour every outside-text record
    already on disk carries, so the default swatch mints a record
    byte-identical to one minted before the row existed. The rest are
    :data:`theme.HIGHLIGHT_INKS` through :func:`ink_for_text`.
    """
    from . import theme

    out = [("black", TEXT_COLOR_DEFAULT)]
    for name, value in theme.HIGHLIGHT_INKS:
        out.append((name, ink_for_text(value)))
    return tuple(out)


def text_ink_vars() -> str:
    """``--tink-*`` custom properties for the page's text swatches.

    theme.css_vars owns ``--ink-*`` (the highlight row); this is its
    text-side sibling, appended to the same substitution so the page
    still spells no hex of its own. It lives HERE rather than in
    theme.py because it is derived from a theme table rather than being
    one — theme.py stays the source of the hues.
    """
    return "".join(f" --tink-{name}: {value};" for name, value in text_inks())


def build_page_html(addon_name: str, night: bool) -> str:
    """The viewer page with ``__ADDON__``/``__THEME_VARS__`` filled in.

    These two placeholder names are spelled HERE and nowhere in the
    template: both replacements are global, so a comment in the HTML
    that mentions one gets the replacement text — the whole palette,
    for the theme vars — spliced into it. Harmless inside a comment,
    but it bloats every rendered page and it is a trap for anything
    that greps the rendered output. Keep the template's prose
    describing the placeholders rather than naming them.
    """
    from . import theme

    path = os.path.join(os.path.dirname(__file__), "web", "pdfjs_viewer.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ADDON__", addon_name)
    html = html.replace(
        "__THEME_VARS__", theme.css_vars(night) + text_ink_vars()
    )
    return html


def parse_bridge(cmd: str) -> tuple[str, str] | None:
    """Split a ``klausmate_pdfjs:<action>[:<payload>]`` bridge string.

    Returns ``(action, payload)`` (payload ``""`` when absent) or None
    for commands that are not ours. Splits on the FIRST colon after the
    prefix only — payloads (base64, data URLs) may contain colons.
    """
    if not cmd.startswith(_BRIDGE_PREFIX):
        return None
    msg = cmd[len(_BRIDGE_PREFIX):]
    if ":" in msg:
        action, payload = msg.split(":", 1)
    else:
        action, payload = msg, ""
    return action, payload


def decode_b64_json(payload: str) -> Any:
    """UTF-8 JSON out of a base64 bridge payload (None on any failure)."""
    try:
        return json.loads(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        return None


def gesture_action(gesture_type: Any, value: float) -> tuple | None:
    """What a native trackpad gesture means for the page, or None to let
    it through to Chromium.

    ``value`` of a ``ZoomNativeGesture`` is an INCREMENTAL scale delta per
    event, not a running total: Qt documents it as a scale-factor delta,
    Cocoa feeds it ``[NSEvent magnification]`` per event, and QtWebEngine
    itself applies it as a pinch step of ``1 + value``. ``exp(value)``
    agrees with that to second order and stays symmetric (out by v then
    in by v nets exactly 1.0), the same exponential response the page
    gives ctrl-wheel (``PINCH_K``). Matched by enum NAME so this stays
    pure: no Qt import, and headless stubs need no real enum.
    """
    name = getattr(gesture_type, "name", "")
    if name == "ZoomNativeGesture":
        return ("pinch", math.exp(value))
    if name == "SmartZoomNativeGesture":  # macOS two-finger double-tap
        return ("smart",)
    return None


# A vv-scale report this soon after the last vv-scale reload is not
# reloaded again: if a reload ever kept the scale, that would loop.
VV_RELOAD_GAP_S = 10.0
# How long a reload from disk waits for the page to commit an open text box
# before it goes ahead anyway.
EDIT_COMMIT_WAIT_MS = 1000


def validate_hex_color(value: Any, default: str = HIGHLIGHT_COLOR) -> str:
    """A trusted ``#rrggbb`` out of an untrusted bridge value.

    JS is never trusted (house rule) and ``records_from_rect_map``'s
    ``color`` lands in the annotations JSON verbatim, from where the
    bake resolves it into the PDF's ``/C`` — so the page's chosen ink
    has to be shape-checked before it becomes a record. Accepts
    ``#rgb`` and ``#rrggbb`` in either case (with or without the hash),
    normalizes to LOWERCASE ``#rrggbb``: that is exactly the form of
    :data:`HIGHLIGHT_COLOR` and of every pre-K-149 record on disk, so a
    yellow minted through the swatch row is byte-identical to a yellow
    minted before it existed. Anything else returns *default*.
    """
    if not isinstance(value, str):
        return default
    v = value.strip().lstrip("#").lower()
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6 or any(ch not in "0123456789abcdef" for ch in v):
        return default
    return "#" + v


def _same_line(a: list[float], b: list[float]) -> bool:
    """True when two rects sit on the same text line.

    Vertical overlap of more than half the SHORTER rect — the border
    box and the text quad of one span differ in height (see
    :func:`merge_rects`), so equality of y/h is far too strict, while a
    bare "overlaps at all" would fuse the descenders of one line into
    the ascenders of the next.
    """
    top = max(a[1], b[1])
    bottom = min(a[1] + a[3], b[1] + b[3])
    shorter = min(a[3], b[3])
    return shorter > 0 and (bottom - top) > shorter * 0.5


def merge_rects(rects: Any, gap: float = 0.75) -> list[list[float]]:
    """Selection rects folded into one rect per run of text (K-149).

    THE BUG THIS FIXES, measured in Blink: ``Range.getClientRects()``
    returns, for a text-layer span the range covers COMPLETELY, both
    the span's border box AND its text node's quad. pdf.js's text layer
    is one shrink-wrapped absolutely-positioned span per text item, so
    an ordinary three-line drag yields six rects, not three — same x,
    same width, the border box nested inside the taller quad (measured:
    ``[21, 21, 110.28, 16]`` inside ``[21, 19.5, 110.28, 18.5]``). Each
    became its own ``.hl`` div, and two layers of the 43%-alpha paint
    composite to 67.5% — which is precisely the "double- and
    triple-highlighted" look, from ONE drag with no user error.

    So: rects that share a line and overlap horizontally (or sit within
    *gap* points of each other, which stitches the per-span pieces of a
    line into one box) are unioned. Exact duplicates and containment
    fall out of the same rule. The union is deliberately the OUTER box
    — the taller text quad wins, covering the glyphs rather than
    clipping their descenders.

    Pure and order-independent by construction (sorted, then run to a
    fixpoint), and it also hands the bake clean quad_points: one quad
    per line instead of two stacked ones.
    """
    clean: list[list[float]] = []
    for r in rects or []:
        try:
            x, y, w, h = (float(v) for v in r)
        except (TypeError, ValueError, OverflowError):  # 10**400 is JSON
            continue
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            continue
        if w <= 0 or h <= 0:
            continue
        clean.append([x, y, w, h])
    merged = True
    while merged:
        merged = False
        clean.sort(key=lambda r: (r[1], r[0]))
        out: list[list[float]] = []
        for r in clean:
            host = None
            for cand in out:
                if not _same_line(cand, r):
                    continue
                # Horizontal overlap, or a hairline gap between the
                # pieces of one line. A real column gutter is far wider
                # than *gap*, so two columns never fuse.
                if (
                    r[0] <= cand[0] + cand[2] + gap
                    and cand[0] <= r[0] + r[2] + gap
                ):
                    host = cand
                    break
            if host is None:
                out.append(r)
                continue
            x0 = min(host[0], r[0])
            y0 = min(host[1], r[1])
            x1 = max(host[0] + host[2], r[0] + r[2])
            y1 = max(host[1] + host[3], r[1] + r[3])
            host[:] = [x0, y0, x1 - x0, y1 - y0]
            merged = True
        clean = out
    clean.sort(key=lambda r: (r[1], r[0]))
    return clean


def records_from_rect_map(
    pages: Any, color: str = HIGHLIGHT_COLOR
) -> list[dict]:
    """New highlight records from the JS selection map
    ``{page0: [[x, y, w, h] page points, ...]}`` — the shape the deleted
    native viewer minted too (uuid id, 0-based int page, float rects,
    default yellow). Malformed pages/rects are
    skipped, never raised on.

    Every page's rects go through :func:`merge_rects` first. The page
    dedupes too, but this is the mint choke point and JS is never
    trusted — a stale webview, a future caller, or a hand-crafted
    payload must not be able to stack two coincident rects into one
    record and paint it twice.
    """
    out: list[dict] = []
    if not isinstance(pages, dict):
        return out
    keyed: list[tuple[int, Any]] = []
    for page_key in pages:
        try:
            keyed.append((int(page_key), page_key))
        except (TypeError, ValueError):
            continue
    for page, page_key in sorted(keyed):
        rects = merge_rects(pages[page_key])
        if rects:
            out.append(
                {
                    "id": uuid.uuid4().hex,
                    "page": page,
                    "rects": rects,
                    "color": color,
                }
            )
    return out


def _is_plain_highlight(rec: Any, page: Any) -> bool:
    """A NATIVE highlight record of ours on *page* — the only kind
    :func:`merge_highlight_records` is allowed to rewrite.

    Excluded on purpose: ``kind`` records (outside text boxes are not
    highlights) and ``origin`` records (K-081 — an adopted external
    mark may only leave the list through ``_bridge_hl_remove``, which
    tombstones it; dropping one here would resurrect it on the next
    foreign scan).
    """
    return (
        isinstance(rec, dict)
        and rec.get("page") == page
        and not rec.get("kind")
        and not rec.get("origin")
    )


def _rect_covers(outer: Any, inner: Any, tol: float = 0.5) -> bool:
    """True when *inner* lies inside *outer* (page points, *tol* slack)."""
    try:
        ox, oy, ow, oh = (float(v) for v in outer)
        ix, iy, iw, ih = (float(v) for v in inner)
    except (TypeError, ValueError):
        return False
    return (
        ix >= ox - tol
        and iy >= oy - tol
        and ix + iw <= ox + ow + tol
        and iy + ih <= oy + oh + tol
    )


def _subtract_x(rect: Any, cutter: Any) -> list[list[float]]:
    """*rect* with *cutter*'s horizontal span cut out of it (0–2 pieces).

    Only rects on the SAME LINE cut each other — a mark two lines down
    shares no ink with this one however its x range lines up. Slivers
    thinner than half a point are dropped rather than kept as hairlines.
    Anything malformed comes back untouched: this trims records, and a
    parse failure must never silently delete one.
    """
    try:
        x, y, w, h = (float(v) for v in rect)
        cx0 = float(cutter[0])
        cx1 = cx0 + float(cutter[2])
    except (TypeError, ValueError, IndexError):
        return [list(rect)]
    if not _same_line(rect, cutter):
        return [[x, y, w, h]]
    out: list[list[float]] = []
    if cx0 - x > 0.5:
        out.append([x, y, min(cx0, x + w) - x, h])
    if (x + w) - cx1 > 0.5:
        left = max(cx1, x)
        out.append([left, y, x + w - left, h])
    return out


def _rects_touch(a: Any, b: Any) -> bool:
    """True when any rect of *a* overlaps any rect of *b*."""
    for r1 in a or []:
        for r2 in b or []:
            try:
                x1, y1, w1, h1 = (float(v) for v in r1)
                x2, y2, w2, h2 = (float(v) for v in r2)
            except (TypeError, ValueError):
                continue
            if (
                x1 < x2 + w2
                and x2 < x1 + w1
                and y1 < y2 + h2
                and y2 < y1 + h1
            ):
                return True
    return False


def merge_highlight_records(
    existing: list[dict], records: list[dict]
) -> list[dict]:
    """Fold freshly minted highlight *records* into *existing*.

    :func:`merge_rects` stops ONE drag painting itself twice; this
    stops TWO drags doing it. Re-highlighting a sentence used to
    blind-append a second record over the first, and two 43% layers
    composite to 67.5% — the same visible darkening, reached the other
    way. Per incoming record, against native highlights on its page:

    1. rects an existing SAME-ink highlight already covers are dropped
       (that text is already highlighted in that colour — there is
       nothing to add);
    2. a DIFFERENT-ink highlight has the new mark's span CUT out of it
       (:func:`_subtract_x`), and a record left with nothing goes: the
       new ink wins on exactly the area it covers, so re-marking two
       words inside a yellow sentence in green leaves yellow either
       side and green between, never green over yellow;
    3. what survives is unioned into EVERY same-ink record it touches
       — all of them collapsing into one — or appended as a new record.

    Step 3 folded into only the FIRST touching record until K-159, and
    that left a same-ink overlap the property walk found: mark two
    separated spans of a line in one ink, then drag across the gap
    between them, and the bridging mark unioned into the left record
    while the right one stayed put, overlapping it. Two 43% layers on
    that sliver — the "double-highlighted" look K-149 set out to kill,
    reached by a third route it did not model. NOT a stickiness bug
    (nothing here can see the tool state; the same three drags produced
    the same records when Highlight was one-shot), but a sticky tool is
    how a user reaches three overlapping drags without noticing.

    Deliberately at MINT time, never in pdf_handler: storage collapses
    duplicates only for ``origin == "external"`` records (Preview
    autosaves the same box repeatedly), and overlapping NATIVE
    highlights staying distinct there is a pinned K-081 invariant.
    """
    out: list[dict] = list(existing or [])
    for rec in records or []:
        page = rec.get("page")
        ink = validate_hex_color(rec.get("color"))
        rects = merge_rects(rec.get("rects"))
        for cur in out:
            if not rects:
                break
            if not _is_plain_highlight(cur, page):
                continue
            if validate_hex_color(cur.get("color")) != ink:
                continue
            covered = cur.get("rects") or []
            rects = [
                r for r in rects
                if not any(_rect_covers(o, r) for o in covered)
            ]
        if not rects:
            continue
        kept: list[dict] = []
        for cur in out:
            if (
                _is_plain_highlight(cur, page)
                and validate_hex_color(cur.get("color")) != ink
            ):
                left: list[list[float]] = []
                changed = False
                for o in cur.get("rects") or []:
                    pieces = [o]
                    for r in rects:
                        cut: list[list[float]] = []
                        for p in pieces:
                            cut.extend(_subtract_x(p, r))
                        pieces = cut
                    if pieces != [o]:
                        changed = True
                    left.extend(pieces)
                if changed:
                    left = merge_rects(left)
                    if not left:
                        continue  # fully recoloured by the new mark
                    cur = dict(cur, rects=left)
            kept.append(cur)
        out = kept
        # EVERY same-ink record the new mark touches, not just the
        # first — a mark bridging two of them has to collapse both, or
        # the two survivors overlap each other (K-159).
        touched = [
            i for i, cur in enumerate(out)
            if _is_plain_highlight(cur, page)
            and validate_hex_color(cur.get("color")) == ink
            and _rects_touch(cur.get("rects") or [], rects)
        ]
        if touched:
            host_at = touched[0]
            host = out[host_at]
            pooled = list(rects)
            # The host keeps its id, and its note if it has one; a note
            # on an absorbed record is carried over rather than
            # silently dropped with it (first non-empty wins — two
            # notes on marks a single drag bridges is not a case worth
            # inventing a join for).
            note = host.get("note")
            note = note if isinstance(note, str) and note.strip() else ""
            for i in touched:
                pooled = list(out[i].get("rects") or []) + pooled
                if not note:
                    other = out[i].get("note")
                    if isinstance(other, str) and other.strip():
                        note = other
            merged_rec = dict(host, rects=merge_rects(pooled))
            if note:
                merged_rec["note"] = note
            drop = set(touched[1:])
            out = [
                merged_rec if i == host_at else cur
                for i, cur in enumerate(out)
                if i not in drop
            ]
        else:
            out.append(dict(rec, color=ink, rects=rects))
    return out


def _finite(value: Any) -> float | None:
    """A real, finite float out of an untrusted bridge number, or None.

    Bools are rejected (they are ints in Python). So is an int too big
    for a float: JSON puts no limit on integers, ``10**400`` parses as a
    Python int, and ``float()`` of it raises OverflowError — which,
    raised inside a bridge slot, aborts Anki (PyQt6 aborts on an
    unhandled slot exception). Every number the text-box bridge reads
    goes through here.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def clamp_text_add(
    data: Any, page_count: int = 0
) -> tuple[int, float, float] | None:
    """Validated ``(page, x, y)`` out of a ``text-add`` bridge payload.

    JS is never trusted (house rule): ``page`` must be a real 0-based
    int (bools rejected) inside ``page_count`` when the count is known;
    ``x``/``y`` must be finite numbers and are clamped into
    ``[0, MAX_PAGE_PT]``. None for anything else — a malformed payload
    places nothing rather than something somewhere surprising.
    """
    if not isinstance(data, dict):
        return None
    page = data.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        return None
    if page_count > 0 and page >= page_count:
        return None
    coords: list[float] = []
    for key in ("x", "y"):
        f = _finite(data.get(key))
        if f is None:
            return None
        coords.append(min(max(f, 0.0), MAX_PAGE_PT))
    return page, coords[0], coords[1]


def sanitize_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """A trusted body out of an untrusted ``text`` payload field.

    Since K-150 the typed text arrives over the bridge (the editor is
    in the page), where before it came out of a Qt dialog — so it gets
    the same treatment as every other bridge value. Newlines
    normalize to ``\\n`` and survive (an outside-text box is
    multi-line); tabs become one space, because the box geometry is
    measured per character and a tab is one character that draws eight
    wide; every other control character is dropped; the result is
    capped and stripped. Non-strings are "".
    """
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    kept = [
        ch for ch in text if ch == "\n" or (ch >= " " and ch != "\x7f")
    ]
    return "".join(kept)[:limit].strip()


def validate_text_size(
    value: Any, default: float = TEXT_SIZE_DEFAULT
) -> float:
    """A trusted font size in points out of a bridge value.

    Junk (and bools, which are ints in Python) falls back to *default*;
    a real number is clamped into [:data:`TEXT_SIZE_MIN`,
    :data:`TEXT_SIZE_MAX`] rather than rejected, so a size the page
    offers that this side has since tightened still places text.
    """
    size = _finite(value)
    if size is None:
        return default
    return min(max(size, TEXT_SIZE_MIN), TEXT_SIZE_MAX)


def _validate_rows(value: Any) -> int:
    """A trusted rendered-row count, or 0 for "not measured"."""
    rows = _finite(value)
    if rows is None or rows < 1:
        return 0
    return int(min(rows, MAX_TEXT_ROWS))


def validate_text_box(
    w: Any, h: Any, size: float = TEXT_SIZE_DEFAULT
) -> tuple[float, float] | None:
    """The page's MEASURED box ``(w, h)`` in points, or None.

    The page lays the text out in the browser, in the font it draws in,
    and sends the size it got. That beats any estimate, but it is still
    bridge input: both values must be real and finite (:func:`_finite`),
    else None and the caller falls back to :func:`text_box_size`.

    A box smaller than ONE LINE of *size* is refused too: narrower than
    0.2 em (Helvetica's narrowest glyph, "i", is 0.22 em, and the page
    adds 1 pt) or shorter than 1.1 em (a line is 1.15 em, rounded UP to
    whole points). Nothing the page measures is smaller, so a sliver is
    a bad payload, not a tiny box. A good value is capped at
    :data:`TEXT_BOX_MAX_W` x :data:`TEXT_BOX_MAX_H`.
    """
    fw, fh = _finite(w), _finite(h)
    if fw is None or fh is None or fw < size * 0.2 or fh < size * 1.1:
        return None
    return min(fw, TEXT_BOX_MAX_W), min(fh, TEXT_BOX_MAX_H)


def text_box_size(
    text: str, size: float = TEXT_SIZE_DEFAULT, rows: int = 0
) -> tuple[float, float]:
    """An ESTIMATED FreeText box for *text*, in page points.

    Only the fallback since 2026-09-30: the page measures the box it
    typed in and sends it (:func:`validate_text_box`). This estimate is
    for a payload without one. Records already on disk keep the box
    they were stored with; nothing re-sizes them.

    Width fits the longest line at ~0.6 em/char (a Helvetica-ish
    average; the renderers clip/shrink gracefully either side), height
    fits every line at 1.35 leading — both clamped to sane page-scale
    bounds so pathological input cannot mint an absurd box.

    Lines that exceed the width cap WRAP, and the height counts the
    wrapped rows (K-150). It used to count source lines only, so one
    long paragraph got a one-line box — and ``.hltext`` and the baked
    FreeText both clip to their box, which silently ate most of the
    text. That was invisible while the only way in was a modal dialog
    you could not see the page behind; with the box now edited in
    place, the box you type in has to be the box you get.

    *rows*, when the page sends its MEASURED row count with a commit,
    raises the estimate (never lowers it): the browser knows its own
    font metrics and this formula only approximates them, so the box
    is sized by whichever of the two is more generous. 0 means "not
    measured" — the formula alone, which is also what an untrusted or
    absurd value degrades to.
    """
    lines = (text or "").splitlines() or [""]
    longest = max(len(line) for line in lines)
    w = min(max(longest * size * 0.6 + 8.0, 60.0), TEXT_BOX_MAX_W)
    per_row = max(w - 8.0, size * 0.6)
    wrapped = 0
    for line in lines:
        wrapped += max(1, math.ceil(len(line) * size * 0.6 / per_row))
    wrapped = max(wrapped, _validate_rows(rows))
    h = min(max(wrapped * size * 1.35 + 6.0, size * 1.5), TEXT_BOX_MAX_H)
    return w, h


def make_text_record(
    page: int,
    x: float,
    y: float,
    text: str,
    color: str = TEXT_COLOR_DEFAULT,
    size: float = TEXT_SIZE_DEFAULT,
    rows: int = 0,
    box: tuple[float, float] | None = None,
) -> dict:
    """A Klaus-native outside-text record at (*x*, *y*) page points.

    EXACTLY the K-077/K-083 ``kind: "text"`` shape the whole pipeline
    already speaks — pdf_handler._validate_highlight round-trips it
    unchanged, the page's ``hltext`` branch renders it, and the bake
    regenerates it as a Klaus-marked FreeText. Deliberately NO
    ``origin`` key: this is native markup, so K-081 tombstones and the
    K-082 foreign mirror ignore it.

    The KEY SET is closed on purpose and K-150 did not widen it: the
    editor's frame, grip and focus ring are EDITING chrome, not record
    state — Preview draws a frame around a text annotation only while
    it is selected, and a committed one is bare glyphs. So the bake
    keeps passing ``border_color=None``/``background_color=None`` and
    the on-screen twin keeps matching the baked PDF exactly, with no
    border flag to keep in step between them.
    """
    w, h = box or text_box_size(text, size, rows)
    return {
        "id": uuid.uuid4().hex,
        "kind": "text",
        "page": int(page),
        "rects": [[float(x), float(y), w, h]],
        "text": str(text),
        "note": "",
        "color": str(color),
        "size": float(size),
    }


def apply_text_update(records: Any, data: Any) -> tuple[list[dict], bool]:
    """One outside-text record re-committed from the page's editor.

    Returns ``(records, changed)`` — a NEW list when something moved,
    the input list untouched when nothing did, so the caller can skip
    the save/push round trip on a no-op commit (clicking away from a
    box you did not edit).

    Every field is re-validated here, not trusted: the id must name an
    existing ``kind: "text"`` record, the body goes through
    :func:`sanitize_text`, the colour through :func:`validate_hex_color`
    and the size through :func:`validate_text_size`. ``x``/``y`` are
    optional and, when valid, move the box (the editor's drag); the
    record's own anchor stands otherwise. The box is re-measured from
    the new text and size, and every OTHER key — ``origin`` above all,
    which decides K-081 tombstoning — is carried through unchanged.

    The box is the page's measured ``w``/``h`` when valid, else the
    :func:`text_box_size` estimate — but only when the text or size
    CHANGED. Same text, same size keeps the stored box: an old record
    (estimated, or adopted from Preview) is never re-sized by a
    click-away or a move.

    An empty body is NOT a delete here: the page routes that to
    ``hl-remove``, which already owns tombstoning an adopted record.
    """
    out = list(records or [])
    if not isinstance(data, dict):
        return out, False
    rec_id = data.get("id")
    if not isinstance(rec_id, str) or not rec_id:
        return out, False
    index = -1
    for i, rec in enumerate(out):
        if isinstance(rec, dict) and rec.get("id") == rec_id \
                and rec.get("kind") == "text":
            index = i
            break
    if index < 0:
        return out, False
    body = sanitize_text(data.get("text"))
    if not body:
        return out, False
    old = out[index]
    color = validate_hex_color(data.get("color"), TEXT_COLOR_DEFAULT)
    size = validate_text_size(data.get("size"))
    rects = old.get("rects") or [[0.0, 0.0, 0.0, 0.0]]
    try:
        x, y = float(rects[0][0]), float(rects[0][1])
    except (TypeError, ValueError, IndexError, OverflowError):
        x = y = 0.0
    for key in ("x", "y"):
        f = _finite(data.get(key))
        if f is None:
            continue
        if key == "x":
            x = min(max(f, 0.0), MAX_PAGE_PT)
        else:
            y = min(max(f, 0.0), MAX_PAGE_PT)
    try:
        w, h = float(rects[0][2]), float(rects[0][3])
    except (TypeError, ValueError, IndexError, OverflowError):
        w = h = 0.0
    # A record with no stored size (one adopted from Preview) is drawn,
    # opened and baked at the default; the page sends that, so the same
    # number here is "unchanged" and the record stays size-less.
    old_size = validate_text_size(old.get("size"))
    if body != old.get("text") or size != old_size or w <= 0 or h <= 0:
        w, h = validate_text_box(
            data.get("w"), data.get("h"), size
        ) or text_box_size(body, size, _validate_rows(data.get("rows")))
    updated = dict(old, text=body, color=color, rects=[[x, y, w, h]])
    if "size" in old or size != old_size:
        updated["size"] = size
    if updated == old:
        return out, False
    out[index] = updated
    return out, True


class PdfJsViewer(_WidgetBase):  # type: ignore[misc]
    """Every reader's viewer (PDF reader 3/5; the only one since 5/5).

    The surface PdfSidebar and its hosts use: ``load_path``,
    ``set_page_texts``, ``load_annotations``, ``clear_document``,
    ``go_to_page``, ``toggle_thumbnails``, ``_page_label``.
    """

    def __init__(
        self,
        on_page_changed: Callable[[int], None],
        parent: Optional[QWidget] = None,  # type: ignore[valid-type]
    ) -> None:
        if not PDFJS_AVAILABLE:
            # _WidgetBase fell back to ``object``, so this is a husk, not
            # a widget. The gate is PdfSidebar's renderer branch — it can
            # only choose "pdfjs" when PDFJS_AVAILABLE — and this is the
            # backstop for a caller that skips it: a named refusal beats
            # ``object.__init__() takes exactly one argument`` raised four
            # frames down (K-164). lecture_view._ensure_dock returns None
            # for the same reason; a constructor cannot, so it raises.
            raise RuntimeError(
                "pdf.js viewer unavailable: Qt imports failed at load"
            )
        super().__init__(parent)
        self._on_page_changed = on_page_changed
        self._name: str | None = None
        # Piece loader (PDF reader 2/5): each load_path is a new
        # generation; range requests from an older page are refused.
        self._path: str | None = None
        self._gen = 0
        self._source: Any = None  # pdf_source.DocSource of the open file
        # True while a stale reload waits for "ready": the teardown's
        # scroll-to-top report must not overwrite the position to restore.
        self._hold_scroll = False
        # Called when the page reports the open file changed under it.
        # PdfSidebar points it at its doc_sync reload.
        self.on_stale: Callable[[], None] = self._reload_current
        self._annotations_name: str | None = None
        self._highlights: list[dict] = []
        self._page_count = 0
        self._scroll_pos = 0
        self.on_count: Optional[Callable[[int], None]] = None
        # Task 10 (K-196): set by PdfSidebar, same shape as on_count —
        # fired from _bridge_sel whenever the page's own debounced
        # selectionchange listener posts the live selection text.
        self.on_selection: Optional[Callable[[str], None]] = None
        # No Add Text prompt lives here any more (K-150): text is typed
        # in the page, so there is no dialog to keep a singleton of.
        self._note_dialog: Any = None  # live Highlight Note prompt (singleton)
        self._goto_dlg: Any = None  # live Go to Page prompt (singleton)

        # Bakes run in annotation_save's one pipeline (PDF reader 1/5),
        # shared by every reader: this one only hears the events for its
        # own document.
        self._unsub_save: Optional[Callable[[], None]] = None
        try:
            from . import annotation_save

            self._unsub_save = annotation_save.pipeline().subscribe(
                self._on_save_event
            )
        except Exception as exc:
            print(f"[klausmate] pdfjs save pipeline subscribe failed: {exc}")

        # The reader's tab strip (ReaderTabs) re-parents this label into
        # its row. Clicking it opens Go to Page.
        self._page_label = QLabel("", self)
        try:
            from . import theme

            self._page_label.setStyleSheet(
                theme.muted_label_qss(theme.night_mode(), 10)
            )
        except Exception:
            pass
        self._page_label.setVisible(False)
        try:
            self._page_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self._page_label.setToolTip("Go to page (Cmd+Option+G)")
        except Exception:
            pass
        self._page_label.installEventFilter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._web: Any = None
        try:
            self._web = AnkiWebView(parent=self)
            self._web.set_bridge_command(self._on_bridge, self)
            lay.addWidget(self._web, 1)
        except Exception as exc:
            print(f"[klausmate] pdfjs webview failed: {exc}")
            fallback = QLabel("The PDF viewer could not start.", self)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            lay.addWidget(fallback, 1)
        self._page_loaded = False

    # Keys the PAGE owns. Without claiming these via ShortcutOverride
    # (CLAUDE.md's host-window shortcut gotcha), Anki's window-level
    # QActions fire first: Cmd+/- zooms the WHOLE webview frame (page,
    # sidebar and all) instead of the PDF, and Cmd+F opens the host
    # window's find. Accepting the override delivers the key to the
    # focused webview instead, where the page's JS keydown handler is
    # the single owner of the behaviour.
    _CLAIMED_KEYS: Any = None  # built lazily; Qt enums need aqt present

    def _claimed(self, event: Any) -> bool:
        try:
            if PdfJsViewer._CLAIMED_KEYS is None:
                K, M = Qt.Key, Qt.KeyboardModifier
                ctrl, shift, alt = M.ControlModifier, M.ShiftModifier, M.AltModifier
                PdfJsViewer._CLAIMED_KEYS = {
                    (K.Key_Plus, ctrl), (K.Key_Equal, ctrl),
                    (K.Key_Minus, ctrl), (K.Key_0, ctrl),
                    (K.Key_F, ctrl),
                    (K.Key_G, ctrl), (K.Key_G, ctrl | shift),
                    (K.Key_G, ctrl | alt),
                    (K.Key_H, ctrl | shift), (K.Key_A, ctrl | shift),
                }
            mods = event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.AltModifier
            )
            return (event.key(), mods) in PdfJsViewer._CLAIMED_KEYS
        except Exception:
            return False

    def eventFilter(self, obj: Any, event: Any) -> bool:
        try:
            if obj is self._page_label and event.type() == event.Type.MouseButtonRelease:
                self._goto_dialog()
                return True
            if event.type() == event.Type.ShortcutOverride and self._claimed(event):
                event.accept()
                return True
            # Trackpad pinch / smart zoom, taken BEFORE Chromium sees it:
            # Chromium pinch-zooms the visual viewport (the whole page,
            # gray background too) for any gesture the page cannot cancel
            # as a ctrl-wheel — one landing before the page script runs,
            # or the two-finger double-tap. Consumed even while the page
            # is still loading (_eval then drops it): that IS the fix.
            # (Not the page label: the header owns it, outside the view.)
            if event.type() == event.Type.NativeGesture and obj is not self._page_label:
                act = gesture_action(event.gestureType(), event.value())
                if act is not None:
                    if act[0] == "smart":
                        self._eval("window.klausSmartZoom && window.klausSmartZoom();")
                    else:
                        # Global -> view: right whichever widget got it.
                        # Frame zoom is pinned to 1.0: view px == CSS px.
                        pos = self._web.mapFromGlobal(event.globalPosition())
                        self._eval(
                            "window.klausPinch && window.klausPinch("
                            f"{act[1]!r}, {pos.x()!r}, {pos.y()!r});"
                        )
                    # Accepted, or Qt re-sends it to the parent view, whose
                    # filter (this one) would zoom a second time.
                    event.accept()
                    return True
        except Exception:
            pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def _claim_shortcuts(self) -> None:
        """Filter the webview AND its focusProxy — QWebEngineView routes
        key events through the proxy child, which only exists once the
        page is up, so this is (re)run per load; installEventFilter is
        idempotent."""
        if self._web is None:
            return
        try:
            self._web.installEventFilter(self)
            proxy = self._web.focusProxy()
            if proxy is not None:
                proxy.installEventFilter(self)
        except Exception:
            pass

    # ---- bridge ---------------------------------------------------------

    def _on_bridge(self, cmd: str) -> Any:
        parsed = parse_bridge(cmd)
        if parsed is None:
            return None
        action, payload = parsed
        try:
            handler = getattr(self, f"_bridge_{action.replace('-', '_')}", None)
            if handler is not None:
                result = handler(payload)
                if result is not None:
                    return result  # Anki JSON-encodes it to the pycmd callback
            # "boot" needs no action.
        except Exception as exc:
            print(f"[klausmate] pdfjs bridge {action} error: {exc}")
        return (True, None)

    def _bridge_page(self, payload: str) -> None:
        num, total = payload.split(":", 1)
        try:
            self._page_label.setText(f"{int(num)} / {int(total) or self._page_count}")
        except Exception:
            pass
        self._on_page_changed(int(num) - 1)

    def _bridge_count(self, payload: str) -> None:
        self._page_count = int(payload)
        if self.on_count is not None:
            self.on_count(self._page_count)

    def _bridge_sel(self, payload: str) -> None:
        """Task 10 (K-196): the page's debounced ``selectionchange``
        listener posts ``{"text": ...}`` — forward it to whatever
        PdfSidebar wired up (viewer_context.report_selection). No-op
        with nothing wired, same guard as _bridge_count's on_count."""
        if self.on_selection is None:
            return
        data = decode_b64_json(payload) or {}
        self.on_selection(str(data.get("text") or ""))

    def _bridge_ready(self, _payload: str) -> None:
        self._hold_scroll = False
        # The page is up, so the live focusProxy exists: filter it too
        # (idempotent) — the pinch/smart-zoom interception rides on it.
        self._claim_shortcuts()
        # openDocument's teardown() wiped page state — (re)push whatever
        # records we hold so annotations survive load order races.
        self._push_annotations()
        if self._scroll_pos:
            self._eval(f"window.klausScrollTo && window.klausScrollTo({int(self._scroll_pos)});")

    def _bridge_range(self, payload: str) -> dict:
        return handle_range(payload, self._source, self._gen)

    def _bridge_stale(self, payload: str) -> None:
        if payload != str(self._gen):
            return
        gen = self._gen
        # Deferred: a reload evals into the page this bridge call came from.
        QTimer.singleShot(0, lambda: gen == self._gen and self.on_stale())

    def _reload_current(self) -> None:
        if self._path is not None and self._name is not None:
            self.load_path(self._path, self._name, keep_view=True)

    _edit_seq = 0
    _after_edit: Optional[Callable[[], None]] = None

    def commit_open_edit(self, then: Callable[[], None]) -> None:
        """Commit the page's open text box, then call ``then`` once. The
        page answers on the bridge after the commit's own message, so its
        mark is saved first; with no page, or no answer in time, ``then``
        runs anyway."""
        if self._web is None or not self._page_loaded:
            then()
            return
        self._edit_seq += 1
        seq, self._after_edit = self._edit_seq, then
        self._eval(f"window.klausCommitEdit && window.klausCommitEdit({seq});")
        QTimer.singleShot(EDIT_COMMIT_WAIT_MS, lambda: self._edit_done(seq))

    def _bridge_edit_done(self, payload: str) -> None:
        try:
            seq = int(payload)
        except ValueError:
            return
        # Deferred: the reload evals into the page this bridge call came from.
        QTimer.singleShot(0, lambda: self._edit_done(seq))

    def _edit_done(self, seq: int) -> None:
        if seq != self._edit_seq or self._after_edit is None:
            return
        then, self._after_edit = self._after_edit, None
        then()

    def repoint(self, path: str) -> None:
        """The open file moved (same file, new path): later reloads use the
        new path, and a source reading the live file follows it."""
        self._path = path
        src = self._source
        if src is not None and src.read_path == src.path:
            src.path = src.read_path = path

    # Class defaults, so __new__-built test stand-ins carry them too.
    _user_zoom = 0.0  # the page's committed user zoom; 0 = fit width
    _vv_reload_at = float("-inf")
    _vv_retry_pending = False  # the ONE end-of-gap retry is scheduled

    def _bridge_zoom(self, payload: str) -> None:
        try:
            z = float(payload)
        except ValueError:
            return
        self._user_zoom = z if math.isfinite(z) and z > 0 else 0.0

    def _bridge_vv_scale(self, payload: str) -> None:
        """Chromium zoomed the visual viewport — the WHOLE page — on a
        gesture nothing caught. Nothing in the page can undo that; only a
        new page resets it, so reload the HTML and re-open the document
        at the same scroll and zoom. Malformed or unzoomed reports are
        ignored."""
        try:
            scale = float(payload)
        except ValueError:
            return
        if not (math.isfinite(scale) and scale > 0 and abs(scale - 1) > 0.01):
            return
        if self._path is None or self._name is None:
            return
        import time

        now = time.monotonic()
        wait = VV_RELOAD_GAP_S - (now - self._vv_reload_at)
        if wait > 0:
            # At most one reload per gap — but never drop the report for
            # good: retry once when the gap ends.
            if not self._vv_retry_pending:
                self._vv_retry_pending = True
                QTimer.singleShot(int(wait * 1000) + 1, self._vv_retry)
            print(f"[klausmate] pdfjs page still zoomed to {scale:.2f}; retrying in {wait:.0f} s")
            return
        self._vv_reload_at = now
        print(f"[klausmate] pdfjs page zoomed to {scale:.2f}; reloading the page")
        # Deferred: the reload replaces the page this bridge call came from.
        QTimer.singleShot(0, self._reload_page)

    def _vv_retry(self) -> None:
        """End of the gap: the page re-checks its scale and reports again
        (into a fresh gap, so it reloads) only if it is still zoomed."""
        self._vv_retry_pending = False
        if self._path is not None:
            self._eval("window.klausVvRearm && window.klausVvRearm();")

    def _reload_page(self) -> None:
        if self._web is None or self._path is None or self._name is None:
            return
        self._page_loaded = False
        self._ensure_page()
        if self._user_zoom:  # the new page starts at fit; keepView keeps this
            self._eval(f"window.klausKeepZoom && window.klausKeepZoom({self._user_zoom!r});")
        self._reload_current()

    def _close_source(self) -> None:
        src, self._source = getattr(self, "_source", None), None
        if src is not None:
            src.close()

    def _bridge_firstpage(self, payload: str) -> None:
        # Untrusted page text: a malformed or huge number is ignored, never
        # raised inside this slot (an unhandled slot exception aborts Anki).
        try:
            ms = _finite(int(payload))
        except (TypeError, ValueError):
            ms = None
        if ms is not None:
            print(f"[klausmate] pdfjs first page {self._name} {int(ms)} ms")

    def _bridge_log(self, payload: str) -> None:
        print(f"[klausmate] pdfjs: {payload}")

    def _bridge_scroll(self, payload: str) -> None:
        if self._hold_scroll:
            return
        try:
            self._scroll_pos = int(payload)
        except ValueError:
            pass

    def _bridge_toast(self, payload: str) -> None:
        try:
            text = base64.b64decode(payload).decode("utf-8")
        except Exception:
            return
        if tooltip is not None:
            tooltip(text)

    def _bridge_hl_add(self, payload: str) -> None:
        self._sync_marks()
        data = decode_b64_json(payload) or {}
        # The page sends the swatch row's chosen ink; anything that is
        # not a hex colour falls back to the default yellow rather than
        # landing in the JSON verbatim (JS is never trusted).
        color = validate_hex_color(data.get("color"))
        records = records_from_rect_map(data.get("pages"), color=color)
        if not records:
            return
        merged = merge_highlight_records(self._highlights, records)
        if merged == self._highlights:
            # Every rect was already highlighted in this ink — say
            # nothing rather than toast a highlight that did not happen.
            return
        self._highlights = merged
        self._save_annotations()
        self._push_annotations()
        if tooltip is not None and not self._save_failed:  # see text-add
            tooltip("Klaus: highlight added")

    def _bridge_hl_remove(self, payload: str) -> None:
        self._sync_marks()
        data = decode_b64_json(payload) or {}
        hl_id = data.get("id")
        removed = [h for h in self._highlights if h.get("id") == hl_id]
        if not removed:
            return
        self._highlights = [
            h for h in self._highlights if h.get("id") != hl_id
        ]
        # A deleted ADOPTED mark must stay deleted (K-081) — tombstone
        # external records so the next foreign-annotation scan doesn't
        # resurrect them (the rule the deleted native viewer's
        # _remove_highlight followed).
        try:
            rec = removed[0]
            if rec.get("origin") == "external" and self._annotations_name:
                from . import settings
                from . import pdf_handler

                pdf_handler.add_suppressed(
                    settings.user_files(), self._annotations_name, rec
                )
        except Exception as exc:
            print(f"[klausmate] pdfjs tombstone failed: {exc}")
        self._save_annotations()
        self._push_annotations()

    def _bridge_text_add(self, payload: str) -> None:
        """A finished text box, committed by the page's own editor.

        NO DIALOG (K-150). The box is typed in place in the page — an
        ``.editLayer`` over the PDF, Preview's shape — so this handler
        receives a complete record's worth of payload and mints from
        it, synchronously, on exactly the path ``_bridge_hl_add`` has
        used since K-097.

        That deletes the K-114 crash class from this action rather
        than defending against it: the segfault needed a dialog on the
        webchannel stack, and there is no longer a dialog anywhere in
        the flow, so neither the deferral rule nor the never-exec rule
        has anything to bind to here. What it costs is that the TEXT
        is now untrusted input like the coordinates always were —
        hence sanitize_text/validate_hex_color/validate_text_size
        below, all before anything reaches the JSON.
        """
        self._sync_marks()
        data = decode_b64_json(payload) or {}
        hit = clamp_text_add(data, self._page_count)
        if hit is None:
            return
        page, x, y = hit
        body = sanitize_text(data.get("text"))
        if not body:
            return  # an empty box mints nothing (dialog-era rule, kept)
        size = validate_text_size(data.get("size"))
        self._highlights.append(
            make_text_record(
                page,
                x,
                y,
                body,
                color=validate_hex_color(
                    data.get("color"), TEXT_COLOR_DEFAULT
                ),
                size=size,
                rows=_validate_rows(data.get("rows")),
                box=validate_text_box(data.get("w"), data.get("h"), size),
            )
        )
        self._save_annotations()
        self._push_annotations()
        # A failed write already toasted SAVE_FAILED_COPY; a second
        # "added" toast would contradict it.
        if tooltip is not None and not self._save_failed:
            tooltip("Klaus: text added")

    def _bridge_text_update(self, payload: str) -> None:
        """An existing text box re-committed after an in-place edit.

        Same no-dialog path as ``text-add``; :func:`apply_text_update`
        does every check and reports whether anything actually moved,
        so clicking away from an untouched box costs no save, no bake
        and no push. Emptying a box is NOT routed here — the page
        posts ``hl-remove`` for that, which already tombstones an
        adopted record (K-081).
        """
        self._sync_marks()
        data = decode_b64_json(payload) or {}
        updated, changed = apply_text_update(self._highlights, data)
        if changed:
            self._highlights = updated
            self._save_annotations()
        # The push is UNCONDITIONAL, and that is load-bearing: the page
        # dropped this record's static twin while its editor was open
        # and is waiting for canonical records to draw it again. Only
        # the save (and the bake it debounces) is skipped when nothing
        # actually moved.
        self._push_annotations()

    def _bridge_note_edit(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        hl_id = data.get("id")
        if hl_id is None:
            return
        # Deferred to the next event-loop tick (live crash: SIGSEGV in
        # QPaintDevice::devicePixelRatio during QBackingStore::flush).
        # Anki's bridge (set_bridge_command above) rides QWebChannel, so
        # this handler runs INSIDE the same re-entrant Chromium/Qt call
        # stack a pending paint can land on. Opening a modal
        # QInputDialog synchronously from there — a nested .exec() —
        # corrupted a backing-store flush and crashed. QTimer.singleShot
        # (0, ...) unwinds back to a clean top-level event-loop
        # iteration first, same defer top_bar._push_chrome_colour uses
        # for the analogous "can't safely act from inside this
        # callback" situation. Re-look-up by id rather than capturing
        # ``record`` directly, in case annotations reload in between.
        QTimer.singleShot(0, lambda: self._do_note_edit(hl_id))

    def _do_note_edit(self, hl_id: str) -> None:
        """Window-modal note prompt for an existing highlight (K-114).

        A QInputDialog INSTANCE wired to signal callbacks and shown with
        open() — the sanctioned non-nested path (the Add Text prompt
        that used to share it retired with K-150, which moved text
        editing into the page); the
        getMultiLineText/getText statics this replaces ran an app-modal
        nested loop under the hood, the exact crash class K-114 bans
        (test_bridge_reentrancy pins the why). The guarded multiline
        option degrades to a single-line box exactly like the old
        hasattr fallback did.
        """
        record = next(
            (h for h in self._highlights if h.get("id") == hl_id), None
        )
        if record is None or QInputDialog is None:
            return
        if self._note_dialog is not None:
            # One note prompt at a time: front the open one instead of
            # stacking a second.
            try:
                self._note_dialog.raise_()
                self._note_dialog.activateWindow()
            except Exception:
                pass
            return
        existing = str(record.get("note") or "")
        try:
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Highlight Note")
            dlg.setLabelText("Note:")
            try:
                dlg.setOption(
                    QInputDialog.InputDialogOption
                    .UsePlainTextEditForTextInput,
                    True,
                )
            except Exception:
                pass
            dlg.setTextValue(existing)
            try:
                from . import theme

                dlg.setStyleSheet(theme.dialog_qss(theme.night_mode()))
            except Exception:
                pass
            dlg.textValueSelected.connect(
                lambda text: self._on_note_edited(hl_id, text)
            )
            dlg.finished.connect(lambda _r: self._on_note_dialog_closed())
            self._note_dialog = dlg
            dlg.open()
        except Exception as exc:
            self._note_dialog = None
            print(f"[klausmate] pdfjs note dialog failed: {exc}")

    def _on_note_dialog_closed(self) -> None:
        dlg, self._note_dialog = self._note_dialog, None
        if dlg is not None:
            try:
                dlg.deleteLater()
            except Exception:
                pass

    def _on_note_edited(self, hl_id: str, text: Any) -> None:
        # Re-look-up by id: annotations may have reloaded (bake refresh)
        # while the prompt was open. An emptied box clears the note —
        # same as OK-on-empty did under the old static.
        self._sync_marks()
        record = next(
            (h for h in self._highlights if h.get("id") == hl_id), None
        )
        if record is None:
            return
        record["note"] = str(text).strip()
        self._save_annotations()
        self._push_annotations()

    def _bridge_copy_text(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        text = str(data.get("text") or "").strip()
        if text and QApplication is not None:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(text)  # selection copy: silent, Preview-style
                if data.get("toast"):
                    # Menu-driven page capture confirms with a toast
                    # (critique H1 finding).
                    try:
                        from aqt.utils import tooltip

                        tooltip("Klaus: page text copied")
                    except Exception:
                        pass

    def _bridge_copy_image(self, payload: str) -> None:
        if QImage is None or QApplication is None:
            return
        try:
            raw = base64.b64decode(payload)
        except Exception:
            return
        img = QImage()
        if img.loadFromData(raw, "PNG") and not img.isNull():
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setImage(img)
                if tooltip is not None:
                    tooltip("Klaus: copied as image")

    def _bridge_goto_request(self, _payload: str) -> None:
        # Deferred for the same reason _bridge_note_edit is — see its
        # comment (live crash: modal QInputDialog opened synchronously
        # inside a QWebChannel-dispatched bridge call). The eventFilter
        # caller of _goto_dialog below stays synchronous on purpose:
        # that one fires from a normal Qt mouse event on a native
        # QLabel, never from inside the webchannel's call stack.
        QTimer.singleShot(0, self._goto_dialog)

    def _goto_dialog(self) -> None:
        """Window-modal page prompt (K-114): a QInputDialog INSTANCE via
        open() + intValueSelected, never the app-modal getInt static."""
        if QInputDialog is None or self._page_count <= 0:
            return
        if self._goto_dlg is not None:
            # One prompt at a time: front the open one.
            try:
                self._goto_dlg.raise_()
                self._goto_dlg.activateWindow()
            except Exception:
                pass
            return
        try:
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Go to Page")
            dlg.setLabelText(f"Page (1–{self._page_count}):")
            dlg.setInputMode(QInputDialog.InputMode.IntInput)
            dlg.setIntRange(1, self._page_count)
            dlg.setIntValue(1)
            try:
                from . import theme

                dlg.setStyleSheet(theme.dialog_qss(theme.night_mode()))
            except Exception:
                pass
            dlg.intValueSelected.connect(
                lambda page: self.go_to_page(page - 1)
            )
            dlg.finished.connect(lambda _r: self._on_goto_dialog_closed())
            self._goto_dlg = dlg
            dlg.open()
        except Exception as exc:
            self._goto_dlg = None
            print(f"[klausmate] pdfjs goto dialog failed: {exc}")

    def _on_goto_dialog_closed(self) -> None:
        dlg, self._goto_dlg = self._goto_dlg, None
        if dlg is not None:
            try:
                dlg.deleteLater()
            except Exception:
                pass

    # ---- annotations persistence ----------------------------------------

    def _push_annotations(self) -> None:
        self._eval(
            "window.klausSetAnnotations && window.klausSetAnnotations("
            + json.dumps(self._highlights)
            + ");"
        )

    def _refresh_highlight_overlay(self) -> None:
        """Duck-typed by shared sidebar code (a records reload sets
        ``_highlights`` then calls this) — for
        this renderer, refreshing the overlay means pushing the records
        to the page."""
        self._push_annotations()

    # True while the last JSON write failed: memory holds marks the JSON
    # lacks, so _sync_marks must not replace them (the next save retries).
    _save_failed = False
    # True while the marks file has been unreadable since this document
    # opened: memory holds only the marks made since, so nothing is
    # written until the file reads again, and then the two are merged.
    _unreadable = False

    def _sync_marks(self) -> None:
        """Before a mutation: take the marks JSON as it is now, so a mark
        another reader of this PDF saved since is kept, not overwritten
        by this viewer's older list. A file that was unreadable at open
        and reads again is merged with the marks made meanwhile."""
        if self._annotations_name is None or (self._save_failed and not self._unreadable):
            return
        try:
            from . import pdf_handler, settings

            fresh = pdf_handler.load_annotations_strict(
                settings.user_files(), self._annotations_name
            )
            if fresh is None:  # unreadable is not "no marks": keep ours
                return
            if self._unreadable:
                have = {str(h.get("id")) for h in fresh}
                fresh = fresh + [h for h in self._highlights if str(h.get("id")) not in have]
                self._unreadable = False
            self._highlights = fresh
        except Exception as exc:
            print(f"[klausmate] pdfjs marks re-read failed: {exc}")

    def _save_annotations(self) -> None:
        """Synchronous write-through, then the shared save pipeline. A
        failed write keeps the marks in memory and requests no bake. An
        unreadable marks file is never written over (said once, at open)."""
        if self._annotations_name is None:
            return
        if self._unreadable:
            self._sync_marks()
            if self._unreadable:
                return
        try:
            from . import settings
            from . import pdf_handler

            ok = pdf_handler.save_annotations(
                settings.user_files(), self._annotations_name, self._highlights
            )
            self._save_failed = not ok
            if not ok:
                if tooltip is not None:
                    from . import annotation_save

                    tooltip(annotation_save.SAVE_FAILED_COPY)
                return
            # Hold what the JSON holds (normalized), so a pipeline event
            # compares like with like and pushes only real differences.
            fresh = pdf_handler.load_annotations_strict(
                settings.user_files(), self._annotations_name
            )
            if fresh is not None:
                self._highlights = fresh
            self._schedule_bake(settings.user_files(), self._annotations_name)
        except Exception as exc:
            print(f"[klausmate] pdfjs save annotations failed: {exc}")

    def _schedule_bake(self, _user_files_dir: str, name: str) -> None:
        """Hand the bake to the shared pipeline. Only a forwarder: its
        call site carries another session's uncommitted edit."""
        from . import annotation_save

        annotation_save.pipeline().request(name)

    def _on_save_event(self, event: str, name: str) -> None:
        """Pipeline event for THIS viewer's document: "saved" and "records"
        re-read the marks JSON and push it when it differs from what this
        viewer holds (another reader of the same PDF saved, or the bake
        dropped marks) — so this viewer's next save writes them back
        instead of erasing them; the page keeps an open text box. "failed"
        toasts that the marks are kept."""
        if name != self._annotations_name:
            return
        if event in ("saved", "records") and not self._save_failed:
            from . import pdf_handler, pdf_source

            fresh = pdf_handler.load_annotations_strict(pdf_source.user_files_dir(), name)
            if fresh is not None and fresh != self._highlights:
                self._highlights = fresh
                self._refresh_highlight_overlay()
        elif event == "failed" and tooltip is not None:
            from . import annotation_save

            tooltip(annotation_save.SAVE_FAILED_COPY)

    # ---- loading --------------------------------------------------------

    def _eval(self, js: str) -> None:
        if self._web is not None and self._page_loaded:
            try:
                self._web.eval(js)
            except Exception:
                pass

    def _ensure_page(self) -> None:
        if self._page_loaded or self._web is None:
            return
        try:
            from . import theme

            addon = mw.addonManager.addonFromModule(__name__)
            html = build_page_html(addon, theme.night_mode())
            self._web.stdHtml(html, context=self)
            self._page_loaded = True
        except Exception as exc:
            print(f"[klausmate] pdfjs page load failed: {exc}")
            return
        # Frame zoom must stay 1.0 — PDF zoom is the page's own
        # re-render (klausSetZoom), not Chromium magnification.
        try:
            self._web.setZoomFactor(1.0)
        except Exception:
            pass
        self._claim_shortcuts()

    def load_path(self, path: str, name: str, keep_view: bool = False) -> None:
        """Open the stored PDF in pdf.js by byte range: only its length and
        first chunk are read here; the page asks for the rest.

        ``keep_view`` (a stale reload of the same document) keeps the
        scroll position and any user zoom."""
        if self._web is None:
            return
        self._ensure_page()
        self._claim_shortcuts()  # focusProxy may only exist by now
        try:
            self._web.setZoomFactor(1.0)
        except Exception:
            pass
        self._name = name
        self._path = path
        if not keep_view:
            self._scroll_pos = 0
            self._user_zoom = 0.0
        self._hold_scroll = keep_view
        self._gen += 1
        self._close_source()
        source = None
        try:
            from .pdf_source import DocSource, sweep_snapshots

            source = DocSource(path, _reading_dir())
            global _SWEPT
            if not _SWEPT:
                _SWEPT = True
                sweep_snapshots(_reading_dir(), keep={source.read_path})
            size_mb = source.length / (1024 * 1024)
            if size_mb > MAX_PDF_MB:
                source.close()
                self._page_close(
                    f"This PDF is {size_mb:.0f} MB — too large for the "
                    "pdf.js viewer."
                )
                return
            length, first_b64 = first_chunk(source)
        except Exception as exc:
            if source is not None:
                source.close()
            print(f"[klausmate] pdfjs read failed: {exc}")
            self._page_close("Could not open this PDF.")
            return
        self._source = source
        args = ", ".join(
            json.dumps(v) for v in (self._gen, length, first_b64, name, keep_view)
        )
        self._web.eval(f"window.klausPdfOpen && window.klausPdfOpen({args});")

    # ---- the surface PdfSidebar uses -------------------------------------

    def set_page_texts(self, pages: list[str]) -> None:
        # pdf.js extracts its own text layer; the stored page texts only
        # seed the page count until the document reports its own.
        if self._page_count == 0:
            self._page_count = len(pages)

    def load_annotations(self, name: str) -> None:
        """Load the shared annotations JSON and push it to the page."""
        self._annotations_name = name
        self._save_failed = self._unreadable = False
        try:
            from . import settings
            from . import pdf_handler

            recs = pdf_handler.load_annotations_strict(settings.user_files(), name)
            if recs is None:
                # Unreadable (a sync client mid-write, a corrupt file): open
                # with nothing shown, write nothing over it, say so once.
                self._highlights = []
                self._unreadable = self._save_failed = True
                if tooltip is not None:
                    from . import annotation_save

                    tooltip(annotation_save.UNREADABLE_MARKS_COPY)
            else:
                self._highlights = recs
        except Exception as exc:
            print(f"[klausmate] pdfjs annotations load failed: {exc}")
            self._highlights = []
        self._push_annotations()
        self._start_foreign_mirror(name)

    # ---- outside-annotation mirror (K-082) -------------------------------
    # load_annotations starts the mirror on every load and every reload
    # from disk.
    # The scan/merge machinery is pdf_handler's and fully shared; only
    # the last hop — putting refreshed records on screen — differs, and
    # here that is a push through klausSetAnnotations.

    def _apply_mirror(self, name: str, res: dict) -> None:
        """Main-thread half of the mirror: records follow the file for
        outside marks. Schedules NO bake — the file already holds those
        marks, and baking here would re-feed the watcher loop."""
        try:
            from . import settings
            from . import pdf_handler

            changed = pdf_handler.mirror_foreign_annotations(
                settings.user_files(), name, res
            )
            if not changed:
                return
            if self._annotations_name == name:
                self._sync_marks()  # strict: unsaved or unreadable marks stay
                self._push_annotations()
                if tooltip is not None:
                    tooltip(f"Klaus: synced {changed} outside change(s)")
        except Exception as exc:
            print(f"[klausmate] pdfjs mirror apply failed: {exc}")

    def _start_foreign_mirror(self, name: str) -> None:
        """Scan the working PDF for outside text/highlights on a daemon
        thread (multi-MB pypdf parse must never block the UI); the
        merge/save hops back to the main thread so it cannot race the
        synchronous _save_annotations writes."""
        try:
            from . import settings
            from . import pdf_handler
        except Exception:
            return
        if not getattr(pdf_handler, "BAKE_AVAILABLE", False):
            return

        def _worker() -> None:
            try:
                res = pdf_handler.scan_working_annotations(settings.user_files(), name)
                if res is None:
                    return
                if res.get("foreign"):
                    working = pdf_handler._working_pdf_path(settings.user_files(), name)
                    if not pdf_handler._capture_pristine_stripped(
                        settings.user_files(), name, working
                    ):
                        return
                if mw is not None:
                    mw.taskman.run_on_main(
                        lambda: self._apply_mirror(name, res)
                    )
            except Exception as exc:
                print(f"[klausmate] pdfjs mirror scan failed: {exc}")

        threading.Thread(
            target=_worker, name="klausmate-pdfjs-extmirror", daemon=True
        ).start()

    def _page_close(self, error: Optional[str] = None) -> None:
        """Tear the page's document down for the current generation and,
        given *error*, show it where the pages were."""
        args = ", ".join(json.dumps(v) for v in (self._gen, error) if v is not None)
        self._eval(f"window.klausPdfClose && window.klausPdfClose({args});")

    def clear_document(self) -> None:
        self._name = None
        self._annotations_name = None
        self._highlights = []
        self._page_count = 0
        self._scroll_pos = 0
        self._gen += 1
        self._close_source()
        self._page_close()

    def go_to_page(self, page: int) -> None:
        self._eval(
            f"window.klausGoToPage && window.klausGoToPage({int(page) + 1});"
        )

    def toggle_thumbnails(self) -> None:
        self._eval("window.klausToggleThumbs && window.klausToggleThumbs();")

    def cleanup(self) -> None:
        """Unregister the webview from Anki's global hooks BEFORE its
        C++ object dies.

        ``AnkiWebView.__init__`` appends ``on_theme_did_change`` to
        ``gui_hooks.theme_did_change`` (and other global hooks) and only
        ``AnkiWebView.cleanup()`` removes them — Anki even logs
        "destroyed without a cleanup() call" for the ones it catches.
        A webview destroyed without it leaves a dead bound method in
        that hook, so the user's NEXT theme change crashes inside
        Anki's own iteration with "wrapped C/C++ object of type
        AnkiWebView has been deleted" (live traceback 2026-08-25:
        Library window closed, then the theme was switched). Idempotent
        and safe to call twice.
        """
        self._after_edit = None  # a late commit reply must not reload a dead page
        unsub, self._unsub_save = self._unsub_save, None
        if unsub is not None:
            unsub()
        self._close_source()
        web, self._web = self._web, None
        self._page_loaded = False
        if web is None:
            return
        try:
            web.cleanup()
        except Exception as exc:
            print(f"[klausmate] pdfjs webview cleanup failed: {exc}")
