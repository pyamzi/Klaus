---
name: plotting-without-dependencies
description: Use when a chart must be drawn somewhere charting libraries cannot go - an embedded runtime, a plugin host, a bundled Python with no numpy or matplotlib, a sandboxed webview with no CDN - or when a plot has to follow a host application's live theme and light/dark switch.
---

# Plotting Without Dependencies

## Overview

Drawing charts as hand-built HTML/CSS/SVG, with the standard library and
nothing else.

**REQUIRED BACKGROUND:** Use the `dataviz` skill for what makes a chart
*correct* — choosing the form, the four colour jobs, mark specs, the
accessibility pass. This skill is only about building one where you cannot
install anything, and where the surrounding app owns the theme.

**Core principle: separate the geometry from the paint.** Geometry is pure
functions over numbers — no imports from the GUI toolkit, the host app, or the
DOM. Paint is a thin layer that turns those numbers into markup. That split is
what makes the chart testable at all, because the host is usually the thing you
cannot run.

## The shape

```python
# ── Pure geometry (no host imports) ──────────────────────────────────
GRID = 16.0                        # author on a fixed unit grid, then scale

def bar_rect(value, vmax, index, size):
    """(x, y, w, h) for one bar, in a `size`-wide box."""
    s = size / GRID
    ...

# ── Paint ────────────────────────────────────────────────────────────
def bar_svg(values, size, colours):
    return "".join(
        f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}"'
        f' fill="{colours[i]}"/>'
        for i, (x, y, w, h) in enumerate(...)
    )
```

Author every dimension on one unit grid and scale it. One set of numbers then
serves every rendered size and every device pixel ratio, and a size change can
never leave one element behind.

See `example.py` in this directory — runnable, produces a themed chart.

## Colour

**Take colours from the host's tokens. Never invent a hex.** A plot inside
another application that picks its own blue looks like a foreign object the
first time the user changes theme.

Where the host exposes one accent rather than a palette, build a sequential
ramp as **that accent at rising alpha**. It then re-colours with every theme
for free, including user-chosen ones.

**Space the alpha steps on a curve, not evenly.** Alpha over a surface is not
the same as a lightness ramp: spread N steps linearly and the middle of the
range goes muddy, so the whole plot washes out. Front-load it:

```python
alpha = low + (high - low) * (i / (steps - 1)) ** 0.65
```

The exponent is the knob. Below 1.0 the ramp climbs fast and eases off near
the top, which keeps a *typical* value reading as solid ink while leaving
headroom above it for the outliers. A linear spread put a typical day at 0.56
and flattened a real heatmap; 0.65 put it at 0.69 and fixed it.

**Ship both palettes, keyed on the host's own class.** Hosts flip themes by
toggling a class with JavaScript and do not re-run whatever hook injected your
CSS. A palette baked at injection time freezes on whichever theme was active
then:

```css
:root            { --c1: <light>; }
:root.night-mode { --c1: <dark>;  }
```

Emit both blocks always. Never read the current theme and emit one.

## Layout

**Align by construction, not measurement.** Put the axis labels and the marks
in the *same* CSS grid with the same column and row sizes. They then line up
because they cannot do anything else — no measuring, no magic offsets, nothing
to drift when the font changes.

**Never let a plot widen its container.** Wide plots scroll inside their own
box:

```css
.plot-scroll { overflow-x: auto; overflow-y: hidden; }
.plot-wrap   { width: fit-content; max-width: 100%; }
```

Both halves of that wrapper rule are load-bearing. A plain block stays
full-width; bare `fit-content` cannot go below its widest child, so a wide grid
still overflows. And never `width: 100%` — with `box-sizing: content-box` in
force, width plus padding overflows.

## Verifying

| What | How |
|---|---|
| Geometry | Unit-test the pure functions. Bounds, monotonicity, mirror symmetry, linear scaling across sizes. |
| Data | Test the aggregation separately from the drawing. |
| **Appearance** | **Render it and look at it.** |

**Appearance is not unit-testable, and pretending otherwise is how bad plots
ship.** A washed-out ramp passed every one of a hundred geometry assertions —
the numbers were all correct, and the chart was unreadable. Write the output to
a file and open it. If the target is a webview, open the same markup in any
browser; it is the same engine.

## Common Mistakes

**Baking one theme.** Emitting only the palette that was active when your CSS
was generated. The host flips a class later and your plot stays wrong.

**A colour string the target cannot parse.** Check what your *render target*
accepts, not what CSS accepts. Qt's `QColor` takes `#RRGGBB` and named colours
but silently yields invalid — opaque black — for a CSS `rgba(...)` string.

**Floats through an integer-only API.** Some drawing APIs accept ints only in
their positional overloads and raise on floats; pass the float-typed object
instead.

**Bucketing timestamps in the wrong zone.** Convert to integer day numbers in
the query, in local time, or a DST shift smears one day across two.

**Rank-coloured series.** Colour follows the entity, never its position — see
`dataviz`.
