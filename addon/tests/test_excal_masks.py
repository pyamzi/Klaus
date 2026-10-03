"""Image Occlusion 3/3: label masks from an Excalidraw scene (pure, aqt-free).

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_excal_masks.py
"""
import importlib
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import install, check, section, report  # noqa: E402

install()
em = importlib.import_module("klaus_note.image_occlusion.excal_masks")

with open(os.path.join(ROOT, "tests/fixtures/io/flowchart.excalidraw"), encoding="utf-8") as f:
    scene = json.load(f)


def rects(sc=scene, **kw):
    return em.label_rects(sc, 0, 0, **kw)


def by_id(rs):
    return {r[0]: r[1:] for r in rs}


def close(a, b):
    return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))


section("label_rects")
rs = rects()
d = by_id(rs)
check("free text maps to (236, 136, 168, 58)", d.get("free") == (236, 136, 168, 58), str(d.get("free")))
check("bound text uses its own box, not the container's",
      d.get("txtA") == ((340 + 20) * 2 - 4, (317.5 + 20) * 2 - 4, 60 * 2 + 8, 25 * 2 + 8), str(d.get("txtA")))
check("both bound labels present", "txtA" in d and "txtB" in d)
check("deleted text skipped", "gone" not in d)
check("whitespace-only text skipped", "blank" not in d)
check("shapes and arrows give no rect", not {"rectA", "rectB", "arrow"} & set(d))
check("two-line text gives exactly one rect", [r[0] for r in rs].count("multi") == 1)
check("two-line rect covers the whole element", d["multi"] == ((600 + 20) * 2 - 4, (100 + 20) * 2 - 4, 188, 108))
check("non-ASCII text gives one rect", [r[0] for r in rs].count("greek") == 1)
check("scene element order kept", [r[0] for r in rs] == ["txtA", "txtB", "free", "multi", "tilt", "greek"],
      str([r[0] for r in rs]))

section("rotation")
w, h, a = 100, 20, 0.5
cx, cy = 600 + w / 2, 300 + h / 2
bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
want = (((cx - bw / 2) + 20) * 2 - 4, ((cy - bh / 2) + 20) * 2 - 4, bw * 2 + 8, bh * 2 + 8)
check("angle=0.5 gives the axis-aligned bounding box", close(d["tilt"], want), "%s vs %s" % (d["tilt"], want))
check("rotation changes the box (taller than the unrotated 20px label)", d["tilt"][3] > 20 * 2 + 8)

section("origin, padding, scale, margin")
o = by_id(em.label_rects(scene, 50, 10, padding=0, scale=1, margin=0))
check("origin/padding/scale/margin are honoured", o["free"] == (50, 40, 80, 25), str(o["free"]))
check("origin shifts every rect", close(o["greek"], (550, 490, 150, 25)))

section("empty and odd scenes")
check("scene with no text gives []", em.label_rects({"type": "excalidraw", "elements": [scene["elements"][0]]}, 0, 0) == [])
check("scene with no elements gives []", em.label_rects({"type": "excalidraw", "elements": []}, 0, 0) == [])
check("scene without an elements key gives []", em.label_rects({"type": "excalidraw"}, 0, 0) == [])
check("the scene is not mutated", scene == json.load(open(os.path.join(ROOT, "tests/fixtures/io/flowchart.excalidraw"), encoding="utf-8")))

section("masks_svg")
svg = em.masks_svg(400, 300, rects(), "#FFEBA2", "#2D2D2D")
root = ET.fromstring(svg)
ns = "{http://www.w3.org/2000/svg}"
check("root is svg with width/height", root.tag == ns + "svg" and root.get("width") == "400" and root.get("height") == "300")
groups = root.findall(ns + "g")
titles = [g.find(ns + "title").text for g in groups]
check("Labels group then Masks group", titles == ["Labels", "Masks"], str(titles))
check("Labels group is empty", len(list(groups[0])) == 1)
mrects = groups[1].findall(ns + "rect")
check("one rect per entry", len(mrects) == len(rects()) == 6)
check("fill and stroke carried", all(r.get("fill") == "#FFEBA2" and r.get("stroke") == "#2D2D2D" for r in mrects))
check("no id on rects", all(r.get("id") is None for r in mrects))
first = mrects[0]
check("numbers are written to 5 decimals at most",
      all(len((first.get(k).split(".") + [""])[1]) <= 5 for k in "xy") and first.get("width") == "128", str(first.attrib))
r1 = em.masks_svg(10, 10, [("a", 1 / 3, 2.5, 3, 4)], "#fff", "#000")
check("1/3 is rounded to 5 decimals, integers stay bare",
      'x="0.33333"' in r1 and 'y="2.5"' in r1 and 'width="3"' in r1, r1)
check("empty rects gives an empty Masks group",
      len(ET.fromstring(em.masks_svg(5, 5, [], "#fff", "#000")).findall(ns + "g")[1].findall(ns + "rect")) == 0)
check("IOE attribute order (fill height stroke width x y)",
      '<rect fill="#FFEBA2" height="58" stroke="#2D2D2D" width="168" x="236" y="136"' in
      em.masks_svg(400, 300, [("free", 236, 136, 168, 58)], "#FFEBA2", "#2D2D2D"))


section("png_size: the one PNG size check (excal_tab and the reader)")
import struct  # noqa: E402

def png_head(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"

size = getattr(em, "png_size", None)
check("excal_masks.png_size exists", size is not None)
check("MAX_SIDE is 8192 (R2)", getattr(em, "MAX_SIDE", None) == 8192)
if size is not None:
    check("width and height from the IHDR", size(png_head(9000, 37)) == (9000, 37))
    for label, blob in (("empty", b""), ("GIF", b"GIF89a" + b"\0" * 30),
                        ("magic only", b"\x89PNG\r\n\x1a\n" + b"x" * 20),
                        ("a short IHDR", png_head(5, 5)[:20]),
                        ("another chunk first", png_head(5, 5).replace(b"IHDR", b"IDAT"))):
        try:
            size(blob)
            raised = False
        except ValueError:
            raised = True
        check(label + ": ValueError", raised)

raise SystemExit(report())
