"""Label masks from an Excalidraw scene. Klaus addition (not part of IOE); pure, no aqt.

Every live, non-blank text element becomes one occlusion rectangle in image
pixels. The mask SVG is IOE's omask format, which ngen.py reads unchanged.
"""
from __future__ import annotations

import math
from xml.sax.saxutils import quoteattr


def label_rects(scene: dict, origin_x: float, origin_y: float, padding: float = 20,
                scale: float = 2, margin: float = 4) -> list[tuple[str, float, float, float, float]]:
    """(element_id, x, y, w, h) in image px per text label, in scene element order.

    Image px = (scene - origin + padding) * scale; margin is in image px. A
    rotated label gets the axis-aligned box of its rotated rectangle. Bound
    text uses its own box, not its container's.
    """
    out = []
    for el in scene.get("elements") or []:
        if el.get("type") != "text" or el.get("isDeleted") or not (el.get("text") or "").strip():
            continue
        w, h, a = el["width"], el["height"], el.get("angle") or 0
        bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
        bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        cx, cy = el["x"] + w / 2, el["y"] + h / 2
        out.append((el["id"],
                    (cx - bw / 2 - origin_x + padding) * scale - margin,
                    (cy - bh / 2 - origin_y + padding) * scale - margin,
                    bw * scale + 2 * margin,
                    bh * scale + 2 * margin))
    return out


def _num(v: float) -> str:
    s = ("%.5f" % v).rstrip("0").rstrip(".")  # IOE/svg-edit: up to 5 decimals, integers bare
    return "0" if s in ("-0", "") else s


def masks_svg(width: int, height: int, rects: list[tuple[str, float, float, float, float]],
              fill: str, stroke: str) -> str:
    """IOE omask SVG: an empty Labels group, then a Masks group with one id-less rect each."""
    body = "".join(
        "<rect fill=%s height=\"%s\" stroke=%s width=\"%s\" x=\"%s\" y=\"%s\"/>"
        % (quoteattr(fill), _num(h), quoteattr(stroke), _num(w), _num(x), _num(y))
        for _id, x, y, w, h in rects)
    return ('<svg width="%d" height="%d" xmlns="http://www.w3.org/2000/svg" '
            'xmlns:svg="http://www.w3.org/2000/svg">'
            "<g><title>Labels</title></g><g><title>Masks</title>%s</g></svg>" % (width, height, body))
