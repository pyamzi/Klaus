"""Label masks from an Excalidraw scene. Klaus addition (not part of IOE); pure, no aqt.

Every live, non-blank text element becomes one occlusion rectangle in image
pixels. The mask SVG is IOE's omask format, which ngen.py reads unchanged.
remap_masks carries masks over when a drawing is used again (re-edit).
"""
from __future__ import annotations

import math
from xml.dom import minidom
from xml.sax.saxutils import quoteattr

# An old mask whose box overlaps an old label's this much is that label's mask.
LABEL_IOU = 0.8
# IOE's default mask colours, for a new label when no old mask has a style to copy.
DEFAULT_FILL, DEFAULT_STROKE = "#FFEBA2", "#2D2D2D"
# A new label's mask id. ngen's edit path reads every mask's id, and one that
# doesn't start with the notes' uniq_id (hex) is a new card there.
NEW_ID = "klaus-new-%d"


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


def _f(node, name: str) -> float:
    try:
        return float(node.getAttribute(name) or 0)
    except ValueError:
        return math.nan


def _box(node):
    """(x, y, w, h) of an untransformed rect, ellipse or circle; else None."""
    if node.getAttribute("transform"):
        return None
    if node.nodeName == "rect":
        return tuple(_f(node, k) for k in ("x", "y", "width", "height"))
    if node.nodeName in ("ellipse", "circle"):
        rx = _f(node, "rx" if node.nodeName == "ellipse" else "r")
        ry = _f(node, "ry" if node.nodeName == "ellipse" else "r")
        return _f(node, "cx") - rx, _f(node, "cy") - ry, 2 * rx, 2 * ry
    return None


def _iou(a, b) -> float:
    iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    if not (iw > 0 and ih > 0):
        return 0.0
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def _shapes(layer):
    return [n for n in layer.childNodes if n.nodeType == n.ELEMENT_NODE and n.nodeName != "title"]


def _moved(node, dx: float, dy: float, width: int, height: int) -> bool:
    """Shift node by (dx, dy); False when it now lies wholly outside the image."""
    box = _box(node)
    if box is None:
        # ponytail: paths, polygons, groups and transformed shapes move by a
        # transform and are always kept; bound them if one strays off-image.
        if dx or dy:
            node.setAttribute("transform", ("translate(%s %s) %s" % (
                _num(dx), _num(dy), node.getAttribute("transform"))).strip())
        return True
    kx, ky = ("x", "y") if node.nodeName == "rect" else ("cx", "cy")
    node.setAttribute(kx, _num(_f(node, kx) + dx))
    node.setAttribute(ky, _num(_f(node, ky) + dy))
    x, y, w, h = box[0] + dx, box[1] + dy, box[2], box[3]
    return x < width and x + w > 0 and y < height and y + h > 0


def remap_masks(old_svg: str, old_scene: dict, old_meta: dict, new_scene: dict,
                new_meta: dict, new_w: int, new_h: int) -> str:
    """old_svg's masks carried over to a new export of the drawing.

    1. An old mask is a label's when its rect has IoU >= LABEL_IOU with that
       label's old box (label_rects of old_scene at old_meta's origin), the
       best one per label; every other mask is the user's own ("hand").
    2. Each new label gets the old mask of the same element (its id and
       style kept, so the note updates in place) on its new box. A label new
       to the scene gets a new rect in the old masks' style, id NEW_ID. A
       label the old scene had but no mask matched keeps what the user left
       (Ruling R22): a mask resized or moved off it stays a hand mask, a
       deleted one stays deleted.
    3. Hand masks, and svg-edit's Labels layer, move by the origin change
       ((old.originX - new.originX) * scale, likewise y), so they stay on the
       same spot of the drawing; one now wholly outside new_w x new_h goes.
    4. IOE's omask format: old_svg's layers, the canvas resized to new_w x new_h.
    """
    doc = minidom.parseString(old_svg.encode("utf-8"))
    svg = doc.documentElement
    layers = [n for n in svg.childNodes if n.nodeType == n.ELEMENT_NODE and n.nodeName == "g"]
    masks = layers[-1]  # IOE: the topmost layer is the masks layer

    def labels(scene, meta):
        return label_rects(scene, float(meta["originX"]), float(meta["originY"]),
                           float(meta.get("padding", 20)), float(meta.get("scale", 2)))

    old_labels = labels(old_scene, old_meta)
    scale = float(new_meta.get("scale", 2))
    dx = (float(old_meta["originX"]) - float(new_meta["originX"])) * scale
    dy = (float(old_meta["originY"]) - float(new_meta["originY"])) * scale

    taken = {n.getAttribute("id") for n in doc.getElementsByTagName("*")}
    best, hand = {}, []  # best: element id -> (IoU, its mask)
    for node in _shapes(masks):
        masks.removeChild(node)
        box = _box(node) if node.nodeName == "rect" else None
        score, eid = max(((_iou(box, r[1:]), r[0]) for r in old_labels),
                         default=(0.0, None)) if box else (0.0, None)
        if score < LABEL_IOU:
            hand.append(node)
        elif eid in best and best[eid][0] >= score:
            hand.append(node)  # a second mask over the label is the user's
        else:
            if eid in best:
                hand.append(best[eid][1])
            best[eid] = (score, node)
    matched = {eid: node for eid, (_score, node) in best.items()}
    old_ids = {r[0] for r in old_labels}
    style = next(iter(matched.values()), None) or next(
        (n for n in hand if n.nodeName == "rect" and _box(n) is not None), None)
    for eid, x, y, w, h in labels(new_scene, new_meta):
        node = matched.get(eid)
        if node is None and eid in old_ids:
            continue  # R22: the user resized, moved or deleted its mask
        if node is None:
            if style is not None:
                node = style.cloneNode(False)
            else:
                node = doc.createElement("rect")
                node.setAttribute("fill", DEFAULT_FILL)
                node.setAttribute("stroke", DEFAULT_STROKE)
            n = 1
            while NEW_ID % n in taken:
                n += 1
            taken.add(NEW_ID % n)
            node.setAttribute("id", NEW_ID % n)
        for k, v in zip(("x", "y", "width", "height"), (x, y, w, h)):
            node.setAttribute(k, _num(v))
        masks.appendChild(node)
    for node in hand:
        if _moved(node, dx, dy, new_w, new_h):
            masks.appendChild(node)
    for layer in layers[:-1]:
        for node in _shapes(layer):
            if not _moved(node, dx, dy, new_w, new_h):
                layer.removeChild(node)

    svg.setAttribute("width", str(int(new_w)))
    svg.setAttribute("height", str(int(new_h)))
    return svg.toxml()
