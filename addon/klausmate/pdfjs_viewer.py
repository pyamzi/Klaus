"""pdf.js-backed PDF viewer (K-095/K-096; parity K-097..K-099) — the
flicker fix.

QPdfView flickers structurally: pdfium delivers page bitmaps async (blank
flash on scroll/zoom) and the Python-side selection overlay repaints in a
separate pass from the viewport. This module hosts ``web/pdfjs_viewer.html``
(vendored pdf.js 3.11.174 in ``web/pdfjs/``) in an AnkiWebView instead:
canvases are GPU-composited by Chromium, scrolling translates
already-rendered layers, and the text layer gives native browser selection.

Selected by config key ``pdf_renderer`` (``"native"`` default until the
K-101 cutover). ``PdfSidebar`` branches on :func:`renderer_from_config`.

Division of labour (K-097..K-099): the page owns rendering and gestures;
THIS MODULE OWNS THE ANNOTATIONS JSON. JS sends mutations over the bridge
(``hl-add``/``hl-remove``/``note-edit``/``text-add``/``text-update``),
Python mutates ``_highlights``,
persists via ``pdf_handler.save_annotations`` + the same debounced bake
the native viewer uses, then pushes the canonical records back through
``window.klausSetAnnotations``. Record schema is identical to the native
viewer's (0-based ``page``, ``rects`` in top-left-origin page points), so
the bake pipeline and K-081 external-delete tombstones are shared, not
forked.

Feed pattern (SynapsePro's): read the file in Python, base64, push into
window globals in chunks, then trigger the load. Pure helpers
(:func:`renderer_from_config`, :func:`chunk_b64`, :func:`build_page_html`,
:func:`parse_bridge`, :func:`decode_b64_json`,
:func:`records_from_rect_map`) stay aqt-free for the headless tests.
"""

from __future__ import annotations

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


# ~6 MB of base64 per eval call: large enough that a lecture PDF loads in
# a handful of calls, small enough that no single eval string is huge.
CHUNK_CHARS = 6 * 1024 * 1024

# Refuse beyond this — base64 inflates 4/3 and the whole document lives
# in webview memory.
MAX_PDF_MB = 200

_BRIDGE_PREFIX = "klausmate_pdfjs:"

HIGHLIGHT_COLOR = "#fadc50"  # native viewer's default highlight yellow

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

# WCAG AA for body text. Text ink is OPAQUE glyphs on white paper, so
# legibility is a hard floor, not a preference — see :func:`ink_for_text`.
TEXT_INK_MIN_CONTRAST = 4.5

# The PDF spec caps a page dimension at 14,400 pt (200 in) — any
# coordinate beyond that is garbage whatever the document says.
MAX_PAGE_PT = 14400.0


def renderer_from_config(cfg: Any) -> str:
    """``"pdfjs"`` or ``"native"`` from the addon config dict.

    Unknown values and malformed configs degrade to ``"native"`` — the
    proven path stays the default until the K-101 cutover.
    """
    if not isinstance(cfg, dict):
        return "native"
    val = cfg.get("pdf_renderer")
    return "pdfjs" if val == "pdfjs" else "native"


def chunk_b64(data: bytes, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """Base64-encode *data* and split into eval-sized string chunks."""
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    b64 = base64.b64encode(data).decode("ascii")
    return [b64[i : i + chunk_chars] for i in range(0, len(b64), chunk_chars)]


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
        except (TypeError, ValueError):
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
    ``{page0: [[x, y, w, h] page points, ...]}`` — same shape the native
    viewer's ``_add_highlight_from_selection`` mints (uuid id, 0-based
    int page, float rects, default yellow). Malformed pages/rects are
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
    3. what survives is unioned into a same-ink record it touches, or
       appended as a new record.

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
        host_at = -1
        for i, cur in enumerate(out):
            if not _is_plain_highlight(cur, page):
                continue
            if validate_hex_color(cur.get("color")) != ink:
                continue
            if _rects_touch(cur.get("rects") or [], rects):
                host_at = i
                break
        if host_at >= 0:
            host = out[host_at]
            out[host_at] = dict(
                host,
                rects=merge_rects(list(host.get("rects") or []) + rects),
            )
        else:
            out.append(dict(rec, color=ink, rects=rects))
    return out


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
        v = data.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        f = float(v)
        if not math.isfinite(f):
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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    size = float(value)
    if not math.isfinite(size):
        return default
    return min(max(size, TEXT_SIZE_MIN), TEXT_SIZE_MAX)


def _validate_rows(value: Any) -> int:
    """A trusted rendered-row count, or 0 for "not measured"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    rows = float(value)
    if not math.isfinite(rows) or rows < 1:
        return 0
    return int(min(rows, MAX_TEXT_ROWS))


def text_box_size(
    text: str, size: float = TEXT_SIZE_DEFAULT, rows: int = 0
) -> tuple[float, float]:
    """A FreeText box sized for freshly typed *text*, in page points.

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
    w = min(max(longest * size * 0.6 + 8.0, 60.0), 480.0)
    per_row = max(w - 8.0, size * 0.6)
    wrapped = 0
    for line in lines:
        wrapped += max(1, math.ceil(len(line) * size * 0.6 / per_row))
    wrapped = max(wrapped, _validate_rows(rows))
    h = min(max(wrapped * size * 1.35 + 6.0, size * 1.5), 720.0)
    return w, h


def make_text_record(
    page: int,
    x: float,
    y: float,
    text: str,
    color: str = TEXT_COLOR_DEFAULT,
    size: float = TEXT_SIZE_DEFAULT,
    rows: int = 0,
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
    w, h = text_box_size(text, size, rows)
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
    except (TypeError, ValueError, IndexError):
        x = y = 0.0
    for key, cur in (("x", x), ("y", y)):
        v = data.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        f = float(v)
        if not math.isfinite(f):
            continue
        if key == "x":
            x = min(max(f, 0.0), MAX_PAGE_PT)
        else:
            y = min(max(f, 0.0), MAX_PAGE_PT)
    w, h = text_box_size(body, size, _validate_rows(data.get("rows")))
    updated = dict(
        old,
        text=body,
        color=color,
        size=size,
        rects=[[x, y, w, h]],
    )
    if updated == old:
        return out, False
    out[index] = updated
    return out, True


class PdfJsViewer(QWidget):  # type: ignore[misc]
    """Drop-in for ``PdfViewer`` behind the ``pdf_renderer`` flag.

    Matches the surface PdfSidebar and the tab container actually use:
    ``load_path`` (the pdf.js entry — the sidebar calls it instead of
    ``set_document``), ``set_page_texts``, ``load_annotations``,
    ``clear_document``, ``go_to_page``, ``scroll_position`` /
    ``restore_scroll_position``, ``toggle_thumbnails``, ``_page_label``.
    """

    def __init__(
        self,
        on_page_changed: Callable[[int], None],
        parent: Optional[QWidget] = None,  # type: ignore[valid-type]
    ) -> None:
        super().__init__(parent)
        self._on_page_changed = on_page_changed
        self._name: str | None = None
        self._annotations_name: str | None = None
        self._highlights: list[dict] = []
        self._page_count = 0
        self._scroll_pos = 0
        self.on_count: Optional[Callable[[int], None]] = None
        # No Add Text prompt lives here any more (K-150): text is typed
        # in the page, so there is no dialog to keep a singleton of.
        self._note_dialog: Any = None  # live Highlight Note prompt (singleton)
        self._goto_dlg: Any = None  # live Go to Page prompt (singleton)

        # Debounced bake, same shape as the native viewer's: pending
        # jobs are a SET so annotating PDF A then PDF B inside one
        # debounce window bakes both.
        self._bake_timer: Any = None
        self._bake_pending: dict[tuple[str, str], bool] = {}
        self._bake_lock = threading.Lock()
        self._bake_running = False

        # Same adoption contract as the native viewer: the tab container
        # re-parents this label into the panel header bar. Clicking it
        # opens Go to Page (native parity).
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
            fallback = QLabel(
                "pdf.js viewer could not start — switch off the pdf.js "
                "viewer in KlausMate Preferences.",
                self,
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            lay.addWidget(fallback, 1)
        self._page_loaded = False

    # Keys the PAGE owns. Without claiming these via ShortcutOverride
    # (the same gotcha the native viewer documents), Anki's window-level
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
                handler(payload)
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

    def _bridge_ready(self, _payload: str) -> None:
        # openDocument's teardown() wiped page state — (re)push whatever
        # records we hold so annotations survive load order races.
        self._push_annotations()
        if self._scroll_pos:
            self._eval(f"window.klausScrollTo && window.klausScrollTo({int(self._scroll_pos)});")

    def _bridge_log(self, payload: str) -> None:
        print(f"[klausmate] pdfjs: {payload}")

    def _bridge_scroll(self, payload: str) -> None:
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
        data = decode_b64_json(payload) or {}
        # The page sends the swatch row's chosen ink; anything that is
        # not a hex colour falls back to the native yellow rather than
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
        if tooltip is not None:
            tooltip("Klaus: highlight added")

    def _bridge_hl_remove(self, payload: str) -> None:
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
        # resurrect them. Same rule as the native viewer's
        # _remove_highlight.
        try:
            rec = removed[0]
            if rec.get("origin") == "external" and self._annotations_name:
                from . import USER_FILES  # type: ignore
                from . import pdf_handler

                pdf_handler.add_suppressed(
                    USER_FILES, self._annotations_name, rec
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
        data = decode_b64_json(payload) or {}
        hit = clamp_text_add(data, self._page_count)
        if hit is None:
            return
        page, x, y = hit
        body = sanitize_text(data.get("text"))
        if not body:
            return  # an empty box mints nothing (dialog-era rule, kept)
        self._highlights.append(
            make_text_record(
                page,
                x,
                y,
                body,
                color=validate_hex_color(
                    data.get("color"), TEXT_COLOR_DEFAULT
                ),
                size=validate_text_size(data.get("size")),
                rows=_validate_rows(data.get("rows")),
            )
        )
        self._save_annotations()
        self._push_annotations()
        if tooltip is not None:
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
                    # Menu-driven page capture — parity with the native
                    # viewer's confirmation (critique H1 finding).
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
        """Duck-typed by shared sidebar code (_reload_records_for's
        post-bake refresh sets ``v._highlights`` then calls this) — for
        this renderer, refreshing the overlay means pushing the records
        to the page."""
        self._push_annotations()

    def _save_annotations(self) -> None:
        """Synchronous write-through + debounced bake (native parity)."""
        if self._annotations_name is None:
            return
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            pdf_handler.save_annotations(
                USER_FILES, self._annotations_name, self._highlights
            )
            self._schedule_bake(USER_FILES, self._annotations_name)
        except Exception as exc:
            print(f"[klausmate] pdfjs save annotations failed: {exc}")

    def _schedule_bake(self, user_files_dir: str, name: str) -> None:
        self._bake_pending[(user_files_dir, name)] = True
        try:
            if self._bake_timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(500)
                timer.timeout.connect(self._on_bake_timer)
                self._bake_timer = timer
            self._bake_timer.start()
        except Exception as exc:
            print(f"[klausmate] pdfjs bake schedule failed: {exc}")

    def _on_bake_timer(self) -> None:
        jobs = list(self._bake_pending.keys())
        self._bake_pending.clear()
        if not jobs:
            return
        with self._bake_lock:
            if self._bake_running:
                # Re-arm; the running bake predates this batch's saves.
                for j in jobs:
                    self._bake_pending[j] = True
                try:
                    self._bake_timer.start()
                except Exception:
                    pass
                return
            self._bake_running = True

        def work() -> None:
            try:
                from . import pdf_handler

                for user_files_dir, name in jobs:
                    try:
                        pdf_handler.bake_annotations(user_files_dir, name)
                    except Exception as exc:
                        print(f"[klausmate] pdfjs bake failed for {name}: {exc}")
            finally:
                with self._bake_lock:
                    self._bake_running = False

        threading.Thread(target=work, daemon=True).start()

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

    def load_path(self, path: str, name: str) -> None:
        """Read the stored PDF and feed it to pdf.js (chunked base64)."""
        if self._web is None:
            return
        self._ensure_page()
        self._claim_shortcuts()  # focusProxy may only exist by now
        try:
            self._web.setZoomFactor(1.0)
        except Exception:
            pass
        self._name = name
        self._scroll_pos = 0
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > MAX_PDF_MB:
                self._eval(
                    "window.klausPdfError && window.klausPdfError("
                    + json.dumps(
                        f"This PDF is {size_mb:.0f} MB — too large for the "
                        "pdf.js viewer."
                    )
                    + ");"
                )
                return
            with open(path, "rb") as f:
                data = f.read()
        except Exception as exc:
            print(f"[klausmate] pdfjs read failed: {exc}")
            return
        for part in chunk_b64(data):
            self._web.eval(
                "window.klausPdfChunk && window.klausPdfChunk("
                + json.dumps(part)
                + ");"
            )
        self._web.eval("window.klausPdfLoad && window.klausPdfLoad();")

    # ---- PdfViewer-surface parity ---------------------------------------

    def set_page_texts(self, pages: list[str]) -> None:
        # pdf.js extracts its own text layer; retained so the sidebar's
        # call sites stay identical across renderers.
        if self._page_count == 0:
            self._page_count = len(pages)

    def load_annotations(self, name: str) -> None:
        """Load the shared annotations JSON and push it to the page."""
        self._annotations_name = name
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            self._highlights = pdf_handler.load_annotations(USER_FILES, name)
        except Exception as exc:
            print(f"[klausmate] pdfjs annotations load failed: {exc}")
            self._highlights = []
        self._push_annotations()
        self._start_foreign_mirror(name)

    # ---- outside-annotation mirror (K-082) -------------------------------
    # PdfSidebar's external-change poller duck-types the viewer: it calls
    # v._apply_mirror(name, res) on whichever renderer is active (this
    # crashed live as AttributeError until PdfJsViewer grew the method).
    # The scan/merge machinery is pdf_handler's and fully shared; only
    # the last hop — putting refreshed records on screen — differs, and
    # here that is a push through klausSetAnnotations.

    def _apply_mirror(self, name: str, res: dict) -> None:
        """Main-thread half of the mirror: records follow the file for
        outside marks. Schedules NO bake — the file already holds those
        marks, and baking here would re-feed the watcher loop."""
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            changed = pdf_handler.mirror_foreign_annotations(
                USER_FILES, name, res
            )
            if not changed:
                return
            if self._annotations_name == name:
                self._highlights = pdf_handler.load_annotations(
                    USER_FILES, name
                )
                self._push_annotations()
                if tooltip is not None:
                    tooltip(f"Klaus: synced {changed} outside change(s)")
        except Exception as exc:
            print(f"[klausmate] pdfjs mirror apply failed: {exc}")

    def _start_foreign_mirror(self, name: str) -> None:
        """Scan the working PDF for outside text/highlights on a daemon
        thread (multi-MB pypdf parse must never block the UI); the
        merge/save hops back to the main thread so it cannot race the
        synchronous _save_annotations writes. Same shape as the native
        viewer's method."""
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler
        except Exception:
            return
        if not getattr(pdf_handler, "BAKE_AVAILABLE", False):
            return

        def _worker() -> None:
            try:
                res = pdf_handler.scan_working_annotations(USER_FILES, name)
                if res is None:
                    return
                if res.get("foreign"):
                    working = pdf_handler._working_pdf_path(USER_FILES, name)
                    if not pdf_handler._capture_pristine_stripped(
                        USER_FILES, name, working
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

    def set_document(self, *_a: Any) -> None:
        pass  # native-renderer concept; load_path is the pdfjs entry

    def clear_document(self) -> None:
        self._name = None
        self._annotations_name = None
        self._highlights = []
        self._page_count = 0
        self._scroll_pos = 0
        self._eval(
            "(function(){var p=document.getElementById('pages');"
            "if(p)p.textContent='';})();"
        )

    def go_to_page(self, page: int) -> None:
        self._eval(
            f"window.klausGoToPage && window.klausGoToPage({int(page) + 1});"
        )

    def scroll_position(self) -> int:
        return self._scroll_pos

    def restore_scroll_position(self, pos: Any) -> None:
        try:
            y = int(pos)
        except (TypeError, ValueError):
            return
        self._scroll_pos = y
        self._eval(f"window.klausScrollTo && window.klausScrollTo({y});")

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
        web, self._web = self._web, None
        self._page_loaded = False
        if web is None:
            return
        try:
            web.cleanup()
        except Exception as exc:
            print(f"[klausmate] pdfjs webview cleanup failed: {exc}")
