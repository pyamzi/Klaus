#!/usr/bin/env python3
"""A themed bar chart in HTML/SVG, standard library only.

Runnable reference for the pattern in SKILL.md:

    python3 example.py out.html && open out.html

Everything above the "Paint" divider is pure arithmetic — no imports beyond
the stdlib, nothing from a GUI toolkit or a host application — so it can be
unit-tested in an environment where the host itself cannot be imported.
"""

from __future__ import annotations

import sys

# ── Pure geometry (import-free, testable) ────────────────────────────────
#
# Authored on a fixed unit grid and scaled. One set of numbers serves every
# rendered size and every device pixel ratio.

GRID_W, GRID_H = 160.0, 90.0
PAD_L, PAD_B, PAD_T = 22.0, 14.0, 6.0
BAR_GAP = 2.0          # the surface gap that keeps adjacent fills distinct
BAR_RADIUS = 2.0       # rounded data-end, anchored to the baseline


def plot_box(w: float, h: float) -> tuple[float, float, float, float]:
    """(x, y, w, h) of the area the marks live in, inside the axes."""
    sx, sy = w / GRID_W, h / GRID_H
    return (
        PAD_L * sx,
        PAD_T * sy,
        w - PAD_L * sx,
        h - (PAD_T + PAD_B) * sy,
    )


def bar_rect(
    value: float, vmax: float, index: int, count: int, w: float, h: float
) -> tuple[float, float, float, float]:
    """(x, y, w, h) for one bar. Bars grow up from the baseline."""
    px, py, pw, ph = plot_box(w, h)
    gap = BAR_GAP * (w / GRID_W)
    slot = pw / max(1, count)
    bw = max(1.0, slot - gap)
    bh = 0.0 if vmax <= 0 else (max(0.0, value) / vmax) * ph
    return px + index * slot, py + (ph - bh), bw, bh


def ramp_alphas(steps: int, low: float, high: float, curve: float = 0.65) -> tuple:
    """`steps` alphas from low to high, front-loaded.

    Curve < 1.0 climbs fast then eases: a typical value keeps reading as
    solid ink while the top of the range stays available for outliers. A
    linear spread (curve=1.0) puts mid-range values in the muddy middle and
    washes the whole plot out.
    """
    if steps <= 1:
        return (high,)
    return tuple(
        round(low + (high - low) * (i / (steps - 1)) ** curve, 3)
        for i in range(steps)
    )


def level_for(value: float, vmax: float, steps: int) -> int:
    """Which ramp step a value falls in, 0-based."""
    if vmax <= 0 or value <= 0:
        return 0
    return min(steps - 1, int((value / vmax) * steps))


# ── Paint ────────────────────────────────────────────────────────────────


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def palette_css(accent_light: str, accent_dark: str, steps: int) -> str:
    """BOTH palettes, always. The host flips a class with JS and never
    re-runs whatever injected this, so emitting only the active one freezes
    the plot on whichever theme happened to be current."""
    # Floor 0.35, not the 0.15 a heatmap wants. The floor is set by what
    # "empty" has to look like: in a cell grid an unfilled day must read as
    # nothing, so the ramp starts near-invisible. Every BAR must be visible,
    # so the smallest one still needs real ink under it.
    alphas = ramp_alphas(steps, 0.35, 1.0)
    light = "".join(
        f" --p{i}: {_rgba(accent_light, a)};" for i, a in enumerate(alphas)
    )
    dark = "".join(
        f" --p{i}: {_rgba(accent_dark, a)};" for i, a in enumerate(alphas)
    )
    return (
        f":root {{{light} --ink: #1d1d1f; --grid: rgba(0,0,0,0.10); }}"
        f":root.night-mode {{{dark} --ink: #f5f5f7;"
        " --grid: rgba(255,255,255,0.14); }"
    )


def bars_svg(values, labels, w: float, h: float, steps: int) -> str:
    vmax = max(values) if values else 0
    px, py, pw, ph = plot_box(w, h)
    out = [f'<svg viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}">']
    # Recessive baseline. Grid and axes never compete with the marks.
    # Stops at the last bar rather than at the plot box: the box carries a
    # trailing gap, and an axis overshooting the data reads as an error.
    last = bar_rect(values[-1], vmax, len(values) - 1, len(values), w, h)
    out.append(
        f'<line x1="{px:.2f}" y1="{py + ph:.2f}" x2="{last[0] + last[2]:.2f}"'
        f' y2="{py + ph:.2f}" stroke="var(--grid)" stroke-width="1"/>'
    )
    for i, (v, lab) in enumerate(zip(values, labels)):
        x, y, bw, bh = bar_rect(v, vmax, i, len(values), w, h)
        step = level_for(v, vmax, steps)
        # rx rounds all four corners; the baseline end is covered by the
        # axis line, which is what gives the "rounded data-end" read.
        out.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}"'
            f' height="{bh:.2f}" rx="{BAR_RADIUS}" fill="var(--p{step})">'
            f"<title>{lab}: {v:g}</title></rect>"
        )
        # Label size is in PIXELS, not grid units. The grid scales the
        # marks; type does not scale with it, and a grid-unit number
        # dropped into a font-size renders 4px tall.
        out.append(
            f'<text x="{x + bw / 2:.2f}" y="{h - 3:.2f}" font-size="11"'
            f' text-anchor="middle" fill="var(--ink)">{lab}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def page(values, labels, accent_light="#007AFF", accent_dark="#4FACFE") -> str:
    steps = 5
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + palette_css(accent_light, accent_dark, steps)
        + " body { font: 14px -apple-system, sans-serif; color: var(--ink);"
        " background: #fff; margin: 0; padding: 24px; }"
        " :root.night-mode body { background: #191919; }"
        # Wide plots scroll in their own box and never widen the container.
        " .plot-scroll { overflow-x: auto; overflow-y: hidden; }"
        " .plot-wrap { width: fit-content; max-width: 100%; }"
        "</style></head><body>"
        "<div class='plot-scroll'><div class='plot-wrap'>"
        + bars_svg(values, labels, 640.0, 360.0, steps)
        + "</div></div></body></html>"
    )


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "out.html"
    vals = [12, 31, 47, 22, 58, 39, 8]
    labs = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page(vals, labs))
    print(f"wrote {out}")
