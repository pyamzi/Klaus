"""Per-PDF retention history — snapshots over time + the line-chart dialog.

Pouya's ask (K-118): "allow me to view how retention has changed for PDF
over time." The Library's priorities pass (retention.priority_rows) already
computes a retention score per PDF on every refresh; this module gives each
score a memory: ``record_rows`` appends one dated snapshot per PDF to
``<user_files>/retention_history.json`` (same-day refreshes replace the
day's value instead of stacking), and ``open_history_dialog`` draws the
stored series as a hand-painted line chart.

Storage shape — ``{safe_name: [["YYYY-MM-DD", retention], ...]}``, dates in
LOCAL time, each list chronological, capped at ``MAX_ENTRIES`` (two years of
daily snapshots) with the oldest dropped first. Corrupt or missing files
read as empty; writes are atomic (tmp + ``os.replace``) because recording
runs on the Library's background collection-held thread and a torn write
would poison every later read. Only two writers exist: the priority_rows
pass (``record_rows``) and the PDF delete path (``forget_history``, reached
from pdf_handler.delete_context).

Everything above the "aqt glue" divider is aqt-free and pure — storage,
recording, and all chart math (point mapping, axis ticks, date thinning) —
for tests/test_retention_history.py. The glue below imports aqt lazily
inside the one entry point (browse_highlight's pattern), so importing this
module never needs Qt.

Chart colours come ONLY from theme.palette tokens (the accent at reduced
alpha for the area fill — heatmap's borrow rule: styling is borrowed, never
invented). The dialog is parent-owned, WA_DeleteOnClose, and shown with
``show()`` — NEVER ``exec()``: app-modal exec's nested event loop is the
proven macOS 26 segfault class (K-114), pinned by test.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import date as _date

HISTORY_FILE = "retention_history.json"
MAX_ENTRIES = 730  # two years of daily snapshots per PDF

# Chart geometry: (left, top, right, bottom) padding around the plot area.
# Left is widest (y-axis "100%" labels), bottom holds the date labels.
CHART_PAD = (44.0, 16.0, 16.0, 26.0)
# Per-point dots stop being drawn past this many snapshots — on a dense
# series they'd fuse into a rope thicker than the line itself.
DOT_LIMIT = 60
MAX_DATE_LABELS = 5

EMPTY_MESSAGE = (
    "History starts today — a snapshot is recorded whenever the "
    "Library refreshes."
)

# Locale-free month names: QLocale isn't reachable above the glue divider,
# and %b follows the process locale, which tests can't control.
MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


# ------------------------------------------------------------ storage


def _history_path(user_files_dir: str) -> str:
    return os.path.join(user_files_dir, HISTORY_FILE)


def _atomic_write_json(path: str, obj: dict) -> None:
    """Atomic write, self-contained (pdf_handler has the same primitive,
    but importing pdf_handler would drag aqt into this module's top)."""
    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(
        dest_dir, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_history(user_files_dir: str) -> dict[str, list[list]]:
    """The whole history file as {safe_name: [[date, value], ...]}.

    Corrupt, missing, or wrongly-shaped content reads as empty — a bad
    file must never take the Library refresh (or the dialog) down with
    it. Individual malformed entries are dropped, not fatal, so one
    hand-edited line can't erase a PDF's whole series.
    """
    try:
        with open(_history_path(user_files_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[list]] = {}
    for name, series in data.items():
        if not isinstance(series, list):
            continue
        entries: list[list] = []
        for e in series:
            try:
                if isinstance(e, (list, tuple)) and len(e) == 2:
                    entries.append([str(e[0]), float(e[1])])
            except (TypeError, ValueError):
                continue
        out[str(name)] = entries
    return out


def record_rows(
    user_files_dir: str, rows: list[dict], today: str | None = None
) -> None:
    """Append today's retention snapshot for every row that has one.

    Called by retention.priority_rows right before it returns, i.e. on
    every Library refresh, from the background collection-held thread —
    the single writer of this file. Per PDF (``row["name"]``, the safe
    basename): rows whose ``retention`` is None (unindexed / no matches)
    record nothing; otherwise TODAY's entry is appended, or replaced in
    place when the same day already has one (a second refresh is a
    correction, not a second data point). Series are capped at
    MAX_ENTRIES, oldest dropped. ``today`` exists for tests only.

    Skips the write entirely when nothing changed, so an idle Library
    being reopened all day doesn't rewrite an identical file each time.
    """
    day = str(today) if today else _date.today().isoformat()
    hist = load_history(user_files_dir)
    changed = False
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        r = row.get("retention")
        if r is None:
            continue
        try:
            val = round(clamp01(float(r)), 4)
        except (TypeError, ValueError):
            continue
        safe = str(row.get("name") or "").strip()
        if not safe:
            continue
        entries = hist.setdefault(safe, [])
        hit = None
        for e in reversed(entries):
            if e[0] == day:
                hit = e
                break
        if hit is not None:
            if hit[1] != val:
                hit[1] = val
                changed = True
        else:
            entries.append([day, val])
            changed = True
        if len(entries) > MAX_ENTRIES:
            del entries[: len(entries) - MAX_ENTRIES]
            changed = True
    if changed:
        _atomic_write_json(_history_path(user_files_dir), hist)


def forget_history(user_files_dir: str, safe: str) -> None:
    """Drop one PDF's whole series — called when that PDF is deleted.

    retention_history.json is a SIBLING of the per-PDF ``contexts``/
    ``pdfs``/``annotations`` files, so nothing ``pdf_handler.delete_context``
    unlinks can reach it (``retention.forget_prefs`` exists for exactly the
    same blind spot). Without this, re-importing a PDF under the same safe
    basename silently inherits the deleted one's curve — a chart of two
    unrelated documents stitched together.

    Every miss is a quiet no-op: a blank key, a key that isn't there, an
    absent file, and an unparseable one all return without writing. A
    corrupt file is deliberately LEFT ALONE rather than truncated here —
    record_rows recovers it on the next Library refresh, and a delete must
    never be the operation that destroys a readable-tomorrow file.
    """
    key = str(safe or "").strip()
    if not key:
        return
    hist = load_history(user_files_dir)
    if key not in hist:
        return
    del hist[key]
    _atomic_write_json(_history_path(user_files_dir), hist)


# ------------------------------------------------------------ chart math


def clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def sorted_entries(raw) -> list[tuple[str, float]]:
    """Sanitized, chronologically sorted [(iso_date, retention)] pairs.

    The chart's contract: every entry here has a parseable date and a
    clamped 0..1 value, so chart_points stays index-aligned with what the
    paint code labels. ISO dates sort lexicographically = chronologically.
    """
    out: list[tuple[str, float]] = []
    for e in raw or []:
        try:
            day = str(e[0])
            _date.fromisoformat(day[:10])  # parseability gate
            out.append((day, clamp01(float(e[1]))))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda t: t[0])
    return out


def chart_points(
    entries, w: float, h: float, pad: tuple = CHART_PAD
) -> list[tuple[float, float]]:
    """Map sorted_entries output to pixel coords inside a w×h widget.

    X is TIME-proportional (date ordinals), not index-even: a gap in
    recording shows as a gap, which is the honest shape for "how has this
    changed over time". Y maps retention 1.0 → top pad, 0.0 → bottom of
    the plot. A single entry (or all entries on one day) centres on X.
    Entries must be chronological (sorted_entries) — output is 1:1 with
    input, minus any row whose date will not parse.
    """
    pad_l, pad_t, pad_r, pad_b = pad
    inner_w = float(w) - pad_l - pad_r
    inner_h = float(h) - pad_t - pad_b
    if inner_w <= 0 or inner_h <= 0:
        return []
    days: list[tuple[int, float]] = []
    for e in entries or []:
        try:
            day = _date.fromisoformat(str(e[0])[:10]).toordinal()
            days.append((day, clamp01(float(e[1]))))
        except (TypeError, ValueError, IndexError):
            continue
    if not days:
        return []
    lo = days[0][0]
    hi = days[-1][0]
    span = hi - lo
    pts: list[tuple[float, float]] = []
    for day, r in days:
        if span > 0:
            x = pad_l + (day - lo) / span * inner_w
        else:
            x = pad_l + inner_w / 2.0
        y = pad_t + (1.0 - r) * inner_h
        pts.append((x, y))
    return pts


def nice_ticks(lo: float, hi: float, max_ticks: int = 5) -> list[float]:
    """Axis tick values covering [lo, hi] on a 1/2/5×10^k step (the
    classic Graphics Gems "nice numbers" loop)."""
    if hi <= lo:
        return [lo]
    step = _nice_num((hi - lo) / max(1, max_ticks - 1), True)
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    ticks: list[float] = []
    v = start
    while v <= end + step * 0.5:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _nice_num(x: float, do_round: bool) -> float:
    exp = math.floor(math.log10(x))
    f = x / (10.0 ** exp)
    if do_round:
        nf = 1.0 if f < 1.5 else 2.0 if f < 3.0 else 5.0 if f < 7.0 else 10.0
    else:
        nf = 1.0 if f <= 1.0 else 2.0 if f <= 2.0 else 5.0 if f <= 5.0 else 10.0
    return nf * (10.0 ** exp)


def thin_dates(n: int, max_labels: int = MAX_DATE_LABELS) -> list[int]:
    """Indices (into n chronological entries) to label on the x-axis:
    evenly spread, always including the first and last entry."""
    if n <= 0 or max_labels <= 0:
        return []
    count = min(n, max_labels)
    if count == 1:
        return [0]
    return sorted({int(round(k * (n - 1) / (count - 1))) for k in range(count)})


def short_date(iso: str, with_year: bool = False) -> str:
    """"2026-08-31" → "Aug 31" (or "Aug 31, 2026" when the series spans
    calendar years). Unparseable input echoes back rather than raising —
    a label, never a crash."""
    try:
        d = _date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso)
    label = f"{MONTHS[d.month - 1]} {d.day}"
    return f"{label}, {d.year}" if with_year else label


def subtitle_text(entries) -> str:
    """The dialog's muted caption for a sanitized, sorted series."""
    n = len(entries)
    if not n:
        return "No snapshots yet"
    pct = int(round(clamp01(float(entries[-1][1])) * 100))
    noun = "snapshot" if n == 1 else "snapshots"
    return f"Latest {pct}% · {n} {noun} since {short_date(entries[0][0], True)}"


# ─────────────────────────────────────────────────────────────────────
# aqt glue — imported lazily inside the one entry point below
# ─────────────────────────────────────────────────────────────────────


def open_history_dialog(parent, safe_name: str, display_name: str):
    """Show the retention-history chart for one PDF. Returns the dialog
    (or None when Qt/history is unavailable).

    The (parent, safe_name, display_name) signature is a CONTRACT — the
    Library's "Retention History…" context-menu item calls exactly this,
    and tests/test_retention_history.py pins it. ``safe_name`` is the
    storage key (pdf_handler._safe_basename); ``display_name`` is what
    the human sees.

    Non-modal by construction: ``show()``, never ``exec()`` (K-114 — an
    app-modal nested event loop is the proven macOS 26 segfault class),
    parent-owned so profile close tears it down, WA_DeleteOnClose so a
    dismissed chart doesn't linger as a hidden widget.
    """
    try:
        from aqt.qt import (
            QBrush,
            QColor,
            QDialog,
            QLabel,
            QLinearGradient,
            QPainter,
            QPainterPath,
            QPen,
            QPointF,
            QRectF,
            Qt,
            QVBoxLayout,
            QWidget,
        )

        from . import retention, theme
    except Exception as exc:
        print(f"[klausmate] retention history dialog unavailable: {exc}")
        return None

    try:
        entries = sorted_entries(
            load_history(retention.USER_FILES).get(str(safe_name), [])
        )
    except Exception as exc:
        print(f"[klausmate] retention history load failed: {exc}")
        entries = []

    class _HistoryChart(QWidget):
        """Retention % over time, painted by hand — QPainter is the whole
        renderer (no QtCharts in Anki's bundle). Every colour is a
        theme.palette token; the area fill is the accent at low alpha."""

        def __init__(self, chart_entries, parent=None):
            super().__init__(parent)
            self._entries = chart_entries
            try:
                self.setMinimumSize(420, 240)
            except Exception:
                pass

        def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override
            # No surface yet = nothing safe to paint on (md3_switch's
            # lesson: Qt's flush must never see an unusable device).
            if self.width() <= 0 or self.height() <= 0:
                return
            painter = QPainter(self)
            try:
                self._paint(painter)
            except Exception as exc:
                # A drawing bug degrades to "the chart didn't draw",
                # never to an exception escaping mid-paint.
                print(f"[klausmate] retention history paint failed: {exc}")
            finally:
                # ALWAYS close the painter (K-115): a QPainter left live
                # on an exception corrupts the backing store and
                # segfaults Qt's next flush.
                painter.end()

        def _paint(self, painter) -> None:
            """The drawing, split out so paintEvent's try/finally can
            guarantee the painter closes no matter how this returns."""
            c = theme.palette(theme.night_mode())
            w = float(self.width())
            h = float(self.height())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # The house dialog card: surface fill, hairline border, 12px
            # radius (dialog_qss's QGroupBox language). QRectF overload
            # only — the positional float form raises on every paint.
            painter.setPen(QPen(QColor(c["grey_light"]), 1.0))
            painter.setBrush(QColor(c["surface"]))
            painter.drawRoundedRect(
                QRectF(0.5, 0.5, w - 1.0, h - 1.0), 12.0, 12.0
            )

            pad_l, pad_t, pad_r, pad_b = CHART_PAD
            inner_w = w - pad_l - pad_r
            inner_h = h - pad_t - pad_b
            if inner_w <= 1.0 or inner_h <= 1.0:
                return

            entries = self._entries
            small = painter.font()
            small.setPixelSize(10)

            pts: list[tuple[float, float]] = []
            if entries:
                # Y gridlines + % labels on the fixed 0–100 axis.
                painter.setFont(small)
                align_r = int(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )
                for tick in nice_ticks(0.0, 100.0, 5):
                    if tick < 0.0 or tick > 100.0:
                        continue
                    y = pad_t + (1.0 - tick / 100.0) * inner_h
                    painter.setPen(QPen(QColor(c["grey_light"]), 1.0))
                    painter.drawLine(
                        QPointF(pad_l, y), QPointF(w - pad_r, y)
                    )
                    painter.setPen(QColor(c["text_muted"]))
                    painter.drawText(
                        QRectF(0.0, y - 8.0, pad_l - 8.0, 16.0),
                        align_r,
                        f"{tick:g}%",
                    )

                pts = chart_points(entries, w, h, CHART_PAD)

            if len(pts) >= 2:
                floor_y = pad_t + inner_h
                # Soft area fill: the accent fading to nothing downward.
                area = QPainterPath()
                area.moveTo(QPointF(pts[0][0], floor_y))
                for x, y in pts:
                    area.lineTo(QPointF(x, y))
                area.lineTo(QPointF(pts[-1][0], floor_y))
                area.closeSubpath()
                top = QColor(c["blue_accent"])
                top.setAlphaF(0.20)
                bottom = QColor(c["blue_accent"])
                bottom.setAlphaF(0.02)
                grad = QLinearGradient(0.0, pad_t, 0.0, floor_y)
                grad.setColorAt(0.0, top)
                grad.setColorAt(1.0, bottom)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(grad))
                painter.drawPath(area)

                line = QPainterPath()
                line.moveTo(QPointF(pts[0][0], pts[0][1]))
                for x, y in pts[1:]:
                    line.lineTo(QPointF(x, y))
                pen = QPen(QColor(c["blue_accent"]), 2.0)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(line)

            if pts:
                # Dots on sparse series only; the latest point always.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(c["blue_accent"]))
                if len(pts) <= DOT_LIMIT:
                    for x, y in pts:
                        painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
                painter.drawEllipse(
                    QPointF(pts[-1][0], pts[-1][1]), 3.5, 3.5
                )

                # Thinned date labels under the plot.
                painter.setFont(small)
                painter.setPen(QColor(c["text_muted"]))
                with_year = (
                    len(entries) > 1
                    and str(entries[0][0])[:4] != str(entries[-1][0])[:4]
                )
                align_c = int(
                    Qt.AlignmentFlag.AlignHCenter
                    | Qt.AlignmentFlag.AlignVCenter
                )
                for i in thin_dates(len(entries)):
                    if i >= len(pts):
                        continue
                    painter.drawText(
                        QRectF(pts[i][0] - 46.0, h - pad_b + 5.0, 92.0, 15.0),
                        align_c,
                        short_date(str(entries[i][0]), with_year),
                    )

            if len(entries) < 2:
                # Empty and single-point states share the friendly note;
                # a lone dot (if any) stays visible behind it.
                body = painter.font()
                body.setPixelSize(12)
                painter.setFont(body)
                painter.setPen(QColor(c["text_muted"]))
                flags = int(Qt.AlignmentFlag.AlignCenter) | int(
                    Qt.TextFlag.TextWordWrap
                )
                painter.drawText(
                    QRectF(pad_l, pad_t, inner_w, inner_h),
                    flags,
                    EMPTY_MESSAGE,
                )

    try:
        night = theme.night_mode()
        c = theme.palette(night)
        dlg = QDialog(parent)
        dlg.setWindowTitle("Retention History")
        try:
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        except Exception:
            pass
        try:
            dlg.setStyleSheet(theme.dialog_qss(night))
        except Exception:
            pass
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(6)
        title = QLabel(str(display_name), dlg)
        # 14px = the design scale's section-heading size.
        title.setStyleSheet(
            f"color: {c['text']}; font-size: 14px; font-weight: 600;"
        )
        lay.addWidget(title)
        caption = QLabel(subtitle_text(entries), dlg)
        caption.setStyleSheet(theme.muted_label_qss(night))
        lay.addWidget(caption)
        chart = _HistoryChart(entries, dlg)
        lay.addWidget(chart, 1)
        dlg.resize(600, 400)
        dlg.show()  # NEVER exec() — K-114
        return dlg
    except Exception as exc:
        print(f"[klausmate] retention history dialog failed: {exc}")
        return None
