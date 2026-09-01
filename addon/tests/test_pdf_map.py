"""Tests for klausmate/pdf_map.py — the embedding map window (K-123).

Pure viewport model first (transform round-trips, fit-to-view centering,
the zoom-at-cursor fixed-point invariant, hit-testing, node sizing, the
edge-subset policy, label placement, the off-view recentre rule, tooltip
text), then the glue pins on the SOURCE: the "aqt glue" divider with
nothing aqt above it, the K-114 exec() ban (and the no-focus-steal
rule), the K-115 paintEvent try/finally painter.end() guard, no literal
hex colours, WA_DeleteOnClose + the closeEvent singleton clear, and the
open_map_window / select_pdf public surface. Then stub-harness smoke
(empty-graph window, singleton fronting, the fake-graph canvas path),
and finally a REAL offscreen-PyQt6 section.

Why the last section exists: the permissive _Dummy stubs have no
geometry and paint no pixels, so the two things K-138 is actually about
— that every note reaches the note layer, and that a PDF's name appears
only while its circle is active — cannot be asserted under them. Real Qt
can, by counting ink. Because open_map_window imports aqt.qt lazily
inside itself, swapping sys.modules["aqt.qt"] is the entire bootstrap
(test_drive.py's precedent), and the section SKIPs honestly if PyQt6 is
missing.

Run: python3 tests/test_pdf_map.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import io
import os
import random
import re
import shutil
import sys
import tempfile
import tokenize
import types

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

pdf_map = importlib.import_module("klausmate.pdf_map")
Viewport = pdf_map.Viewport

_SRC = open(os.path.join(ADDON, "pdf_map.py")).read()
_CODE = code_only(_SRC)  # comments AND strings stripped — real code only
_TREE = ast.parse(_SRC)


def _strip_comments(src: str) -> str:
    """Comments removed, STRINGS KEPT — the hex pin must still see a
    colour literal smuggled in as a string value."""
    try:
        kept = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(kept)
    except Exception:
        return src  # unstrippable -> scan raw (stricter, never laxer)


def _func_seg(name: str) -> str:
    """Source segment of the (unique) function/method ``name``."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(_SRC, node) or ""
    return ""


def _method_seg(cls_name: str, name: str) -> str:
    """Source of ``cls_name.name`` — needed because the canvas and the
    window both define ``__init__`` inside ``open_map_window``, and a
    bare name lookup would silently pick whichever ast.walk reaches
    first."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return ast.get_source_segment(_SRC, sub) or ""
    return ""


def _calls_in(fn_name: str, callee: str) -> list:
    """Every plain-name Call to ``callee`` inside the function
    ``fn_name`` — argument counts, not just "the name appears"."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return [
                c
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == callee
            ]
    return []


# ------------------------------------------------------------- transform

section("viewport transform — world<->screen round-trips")

_VPS = [
    Viewport(1.0, 0.0, 0.0),
    Viewport(3.7, -120.5, 44.25),
    Viewport(260.0, 400.0, 300.0),
    Viewport(0.05, 9999.0, -9999.0),
]
_PTS = [(0.0, 0.0), (1.0, 1.0), (-1.0, 0.5), (0.123456789, -0.987654321)]
ok = True
for vp in _VPS:
    for wx, wy in _PTS:
        sx, sy = pdf_map.world_to_screen(vp, wx, wy)
        rx, ry = pdf_map.screen_to_world(vp, sx, sy)
        if abs(rx - wx) > 1e-9 or abs(ry - wy) > 1e-9:
            ok = False
check("world->screen->world round-trips to 1e-9 across zooms and pans", ok)
check("screen_to_world guards a degenerate zero scale",
      pdf_map.screen_to_world(Viewport(0.0, 5.0, 5.0), 50.0, 50.0) == (0.0, 0.0))

sx0, sy0 = pdf_map.world_to_screen(_VPS[2], 0.25, 0.5)
vp_p = pdf_map.pan_by(_VPS[2], 10.0, -5.0)
sx1, sy1 = pdf_map.world_to_screen(vp_p, 0.25, 0.5)
check("pan_by shifts every screen position by exactly the delta",
      abs(sx1 - sx0 - 10.0) < 1e-9 and abs(sy1 - sy0 + 5.0) < 1e-9)

# ---------------------------------------------------------- fit_to_view

section("fit_to_view — centering, margin, degenerate bounds")

vp = pdf_map.fit_to_view((-1.0, -1.0, 1.0, 1.0), (800.0, 600.0), 40.0)
check("fit scale is the constraining axis's (600-80)/2 = 260",
      abs(vp.scale - 260.0) < 1e-9)
cx, cy = pdf_map.world_to_screen(vp, 0.0, 0.0)
check("world center lands on the widget center",
      abs(cx - 400.0) < 1e-9 and abs(cy - 300.0) < 1e-9)
x_lo, y_lo = pdf_map.world_to_screen(vp, -1.0, -1.0)
x_hi, y_hi = pdf_map.world_to_screen(vp, 1.0, 1.0)
check("constraining axis touches exactly the margin",
      abs(y_lo - 40.0) < 1e-9 and abs(y_hi - 560.0) < 1e-9)
check("non-constraining axis stays centered inside its margin",
      abs((x_lo + x_hi) / 2.0 - 400.0) < 1e-9 and x_lo >= 40.0 - 1e-9)

vp_d = pdf_map.fit_to_view((0.3, 0.3, 0.3, 0.3), (800.0, 600.0), 40.0)
check("zero-span bounds (a single node) still fit: positive scale, centered",
      vp_d.scale > 0
      and abs(pdf_map.world_to_screen(vp_d, 0.3, 0.3)[0] - 400.0) < 1e-9
      and abs(pdf_map.world_to_screen(vp_d, 0.3, 0.3)[1] - 300.0) < 1e-9)
vp_t = pdf_map.fit_to_view(pdf_map.DEFAULT_BOUNDS, (10.0, 10.0), 48.0)
check("a widget smaller than the margins still yields a positive scale",
      vp_t.scale > 0)

# -------------------------------------------------------------- zoom_at

section("zoom_at — the anchor world-point stays fixed (1e-9)")

vp = pdf_map.fit_to_view((-1.0, -1.0, 1.0, 1.0), (800.0, 600.0), 40.0)
cursor = (123.4, 456.7)
ok = True
for factor in (1.6, 0.25, 3.0, 1.0):
    before = pdf_map.screen_to_world(vp, *cursor)
    vp2 = pdf_map.zoom_at(vp, cursor, factor)
    after = pdf_map.screen_to_world(vp2, *cursor)
    if abs(after[0] - before[0]) > 1e-9 or abs(after[1] - before[1]) > 1e-9:
        ok = False
    if abs(vp2.scale - vp.scale * factor) > 1e-9 * max(1.0, vp.scale * factor):
        ok = False
check("single zooms keep the cursor's world point fixed and scale exactly", ok)

vp_c = pdf_map.zoom_at(pdf_map.zoom_at(vp, cursor, 1.5), cursor, 1.5)
w_c = pdf_map.screen_to_world(vp_c, *cursor)
w_0 = pdf_map.screen_to_world(vp, *cursor)
check("chained zooms at one cursor compound without drifting the anchor",
      abs(w_c[0] - w_0[0]) < 1e-9 and abs(w_c[1] - w_0[1]) < 1e-9
      and abs(vp_c.scale - vp.scale * 2.25) < 1e-6)

before = pdf_map.screen_to_world(vp, *cursor)
vp_max = pdf_map.zoom_at(vp, cursor, 1e12)
after = pdf_map.screen_to_world(vp_max, *cursor)
check("zoom clamps at MAX_SCALE and the anchor STILL holds",
      vp_max.scale == pdf_map.MAX_SCALE
      and abs(after[0] - before[0]) < 1e-9
      and abs(after[1] - before[1]) < 1e-9)
vp_min = pdf_map.zoom_at(Viewport(pdf_map.MIN_SCALE, 5.0, 6.0), (0.0, 0.0), 0.5)
check("zoom-out at MIN_SCALE is a no-op (ratio 1.0 — offsets untouched)",
      vp_min.scale == pdf_map.MIN_SCALE
      and vp_min.ox == 5.0 and vp_min.oy == 6.0)

# ------------------------------------------------------------- hit_test

section("hit_test — nearest, none, radius edge, junk")

nodes = [("a", 100.0, 100.0), ("b", 130.0, 100.0)]
check("nearest within radius wins",
      pdf_map.hit_test(nodes, (110.0, 100.0), 50.0) == "a")
check("outside every radius -> None",
      pdf_map.hit_test(nodes, (300.0, 300.0), 5.0) is None)
check("radius edge is INCLUSIVE (3-4-5 exactly on the rim)",
      pdf_map.hit_test([("a", 3.0, 4.0)], (0.0, 0.0), 5.0) == "a")
check("just inside the rim misses at r-epsilon",
      pdf_map.hit_test([("a", 3.0, 4.0)], (0.0, 0.0), 4.999) is None)
check("exact ties keep the first-seen node",
      pdf_map.hit_test([("a", 10.0, 0.0), ("b", -10.0, 0.0)],
                       (0.0, 0.0), 20.0) == "a")
check("empty node list -> None", pdf_map.hit_test([], (0.0, 0.0), 10.0) is None)
check("junk point / negative radius -> None, junk nodes skipped",
      pdf_map.hit_test(nodes, ("x", None), 10.0) is None
      and pdf_map.hit_test(nodes, (0.0, 0.0), -1.0) is None
      and pdf_map.hit_test([("x", "junk", 0.0), ("a", 1.0, 1.0)],
                           (0.0, 0.0), 5.0) == "a")

# ---------------------------------------------------------- node_radius

section("node_radius — sqrt growth with sane clamps")

check("zero / negative / junk / NaN counts all floor at NODE_R_MIN",
      pdf_map.node_radius(0) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(-3) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(None) == pdf_map.NODE_R_MIN
      and pdf_map.node_radius("junk") == pdf_map.NODE_R_MIN
      and pdf_map.node_radius(float("nan")) == pdf_map.NODE_R_MIN)
check("radius grows monotonically with match_count",
      pdf_map.node_radius(4) < pdf_map.node_radius(100))
check("sqrt law: 4 matches = MIN + 2*SPREAD",
      abs(pdf_map.node_radius(4)
          - (pdf_map.NODE_R_MIN + 2.0 * pdf_map.NODE_R_SPREAD)) < 1e-9)
check("a million-match monster clamps at NODE_R_MAX",
      pdf_map.node_radius(10 ** 9) == pdf_map.NODE_R_MAX)

# ------------------------------------------- edge subset / LOD / tooltip

section("edge subset, hover precedence, labels, tooltip")

_EDGES = [
    {"pdf": "a", "nid": 1, "score": 0.5},
    {"pdf": "b", "nid": 2, "score": 0.6},
    {"pdf": "a", "nid": 3, "score": 0.7},
    "not-a-dict",
]
sub = pdf_map.edges_for_selection(_EDGES, "a")
check("selection 'a' -> exactly its two edges",
      len(sub) == 2 and all(e["pdf"] == "a" for e in sub)
      and {e["nid"] for e in sub} == {1, 3})
check("no selection / empty / unknown pdf -> no edges drawn",
      pdf_map.edges_for_selection(_EDGES, None) == []
      and pdf_map.edges_for_selection(_EDGES, "") == []
      and pdf_map.edges_for_selection(_EDGES, "zzz") == [])
check("hover previews over the sticky selection; falls back; both-None",
      pdf_map.active_pdf("h", "s") == "h"
      and pdf_map.active_pdf(None, "s") == "s"
      and pdf_map.active_pdf("h", None) == "h"
      and pdf_map.active_pdf(None, None) is None)
# K-138 retired the whole label level-of-detail policy. K-133 had made
# names always-on below a 12-node cap because the map opened anonymous;
# Pouya looked at that and asked for the opposite — a name only when its
# circle is hovered or selected. So labels_visible, LABEL_ZOOM and
# LABEL_MAX_NODES are gone, and with them K-133's four pins on their
# behaviour plus K-123's zoom-gate pin. What replaces them is a single
# rule with no dial to get wrong: active_pdf decides, above.
check("the label level-of-detail gate is GONE, not just bypassed — "
      "names follow the selection now, and a stale caller must fail loud",
      not hasattr(pdf_map, "labels_visible")
      and not hasattr(pdf_map, "LABEL_ZOOM")
      and not hasattr(pdf_map, "LABEL_MAX_NODES"))

# label placement: beside the node, never on it (K-133 — this half of
# K-133 survives, because the one name that IS drawn still has to clear
# its own node and mirror at the view edge)
check("a label clears its own node by radius + LABEL_GAP and rides the "
      "node's centre line",
      pdf_map.label_anchor(100.0, 50.0, 12.0)
      == (100.0 + 12.0 + pdf_map.LABEL_GAP, 50.0 + pdf_map.LABEL_BASELINE_DY))
check("the gap also clears the SELECTED node's ring (drawn at r + 3 with "
      "a 2px pen, so outer edge r + 4)",
      pdf_map.LABEL_GAP > 4.0)
check("a label that would run past the right edge mirrors to the left of "
      "its node — still off the node, still legible",
      pdf_map.label_anchor(590.0, 10.0, 8.0, 120.0, 640.0)
      == (590.0 - 8.0 - pdf_map.LABEL_GAP - 120.0, 10.0 + pdf_map.LABEL_BASELINE_DY))
check("it mirrors only when it must, and never past the LEFT edge — a "
      "name wider than the view keeps its head visible, not its tail",
      pdf_map.label_anchor(100.0, 0.0, 8.0, 120.0, 640.0)[0] == 117.0
      and pdf_map.label_anchor(30.0, 0.0, 8.0, 700.0, 640.0)[0] == 47.0)
check("no view width (or a degenerate one) = no mirror decision to make",
      pdf_map.label_anchor(600.0, 0.0, 8.0, 500.0)[0] == 617.0
      and pdf_map.label_anchor(600.0, 0.0, 8.0, 500.0, 0.0)[0] == 617.0)
check("junk coordinates degrade instead of raising mid-paint",
      pdf_map.label_anchor("x", None, "r")
      == (pdf_map.LABEL_GAP, pdf_map.LABEL_BASELINE_DY)
      and pdf_map.label_anchor(10.0, 0.0, float("nan"))[0]
      == 10.0 + pdf_map.LABEL_GAP)

# ---- recenter_for: the pure half of the select_pdf seam (K-138) ----

section("recenter_for — reveal an off-view node, leave an on-view one alone")

_VP = pdf_map.Viewport(200.0, 300.0, 240.0)  # world 0,0 at screen 300,240
_SIZE = (600.0, 480.0)
check("a node already comfortably on screen does not move the map at all",
      pdf_map.recenter_for(_VP, (0.0, 0.0), _SIZE) is _VP
      and pdf_map.recenter_for(_VP, (0.5, 0.5), _SIZE) is _VP)
_off = pdf_map.recenter_for(_VP, (5.0, -3.0), _SIZE)
check("an off-view node is centred exactly, and the ZOOM is untouched — "
      "a jump plus a scale change loses all sense of where the view went",
      _off.scale == _VP.scale
      and pdf_map.world_to_screen(_off, 5.0, -3.0) == (300.0, 240.0))
# 5px in from the left edge: inside the widget, but inside the margin.
_edge = pdf_map.screen_to_world(_VP, 5.0, 240.0)
check("the margin is a real inset: a node inside the view but within "
      "RECENTER_MARGIN of its edge still gets centred",
      pdf_map.recenter_for(_VP, _edge, _SIZE) is not _VP
      and 0.0 < pdf_map.RECENTER_MARGIN < 200.0)
check("a widget with no usable size yet centres rather than guessing",
      pdf_map.world_to_screen(
          pdf_map.recenter_for(_VP, (0.0, 0.0), (0.0, 0.0)), 0.0, 0.0)
      == (0.0, 0.0))
# Judged from a viewport where the ORIGIN is far off-view, so "returned
# unchanged" cannot be an accident of a junk point falling back to (0, 0)
# and happening to land on screen.
_VPFAR = pdf_map.Viewport(200.0, -5000.0, -5000.0)
check("a malformed world point leaves the viewport exactly as it was, "
      "rather than steering the map at some fallback coordinate",
      pdf_map.recenter_for(_VPFAR, "junk", _SIZE) is _VPFAR
      and pdf_map.recenter_for(_VPFAR, (float("nan"), 0.0), _SIZE) is _VPFAR
      and pdf_map.recenter_for(_VPFAR, (0.0,), _SIZE) is _VPFAR)

tip = pdf_map.tooltip_text({
    "display": "Lecture 1", "safe": "Lecture_1", "folder": "Anatomy/Week 2",
    "match_count": 37, "retention": 0.834,
})
check("tooltip carries display, folder, match count and known retention",
      tip.splitlines() == [
          "Lecture 1", "Folder: Anatomy/Week 2",
          "Matched notes: 37", "Retention: 83%",
      ])
check("unknown retention (headless None) is simply omitted",
      "Retention" not in pdf_map.tooltip_text(
          {"display": "x", "match_count": 1, "retention": None}))
check("a bool can't cosplay as a retention score",
      "Retention" not in pdf_map.tooltip_text(
          {"display": "x", "match_count": 1, "retention": True}))
check("no folder -> no Folder line; missing display falls back to safe",
      "Folder" not in pdf_map.tooltip_text({"display": "x", "match_count": 0})
      and pdf_map.tooltip_text({"safe": "S_1"}).splitlines()[0] == "S_1")

# ----------------------------------------------------- bounds / parsing

section("parse_xy, bounds_of, graph_bounds")

check("parse_xy: lists, tuples, junk, short, NaN",
      pdf_map.parse_xy([0.5, -0.25]) == (0.5, -0.25)
      and pdf_map.parse_xy((1, 2)) == (1.0, 2.0)
      and pdf_map.parse_xy("junk") is None
      and pdf_map.parse_xy([1]) is None
      and pdf_map.parse_xy([float("nan"), 0]) is None
      and pdf_map.parse_xy(None) is None)
check("bounds_of: box, junk points skipped, empty -> DEFAULT_BOUNDS",
      pdf_map.bounds_of([(0, 0), (2, 3), (-1, 1)]) == (-1.0, 0.0, 2.0, 3.0)
      and pdf_map.bounds_of([("j", 1), (2, 2)]) == (2.0, 2.0, 2.0, 2.0)
      and pdf_map.bounds_of([]) == pdf_map.DEFAULT_BOUNDS)
check("graph_bounds spans notes AND pdf nodes; empty graph falls back",
      pdf_map.graph_bounds({
          "notes": [{"nid": 1, "xy": [0, 0]}],
          "pdfs": [{"safe": "a", "xy": [2, 2]}], "edges": [],
      }) == (0.0, 0.0, 2.0, 2.0)
      and pdf_map.graph_bounds({}) == pdf_map.DEFAULT_BOUNDS)

# ------------------------------------------------- end-to-end pure pipe

section("end-to-end: fake graph -> fit -> hit -> zoom -> hit")

FAKE = {
    "pdfs": [
        {"safe": "lec1", "display": "Lecture 1", "folder": None,
         "threshold": 0.4, "retention": None, "xy": [-0.5, -0.2],
         "match_count": 2},
        {"safe": "lec2", "display": "Lecture 2", "folder": "F",
         "threshold": 0.4, "retention": 0.9, "xy": [0.6, 0.4],
         "match_count": 1},
    ],
    "notes": [
        {"nid": 1, "xy": [-0.6, -0.1]},
        {"nid": 2, "xy": [-0.4, -0.3]},
        {"nid": 3, "xy": [0.6, 0.4]},
    ],
    "edges": [
        {"pdf": "lec1", "nid": 1, "score": 0.8},
        {"pdf": "lec1", "nid": 2, "score": 0.5},
        {"pdf": "lec2", "nid": 3, "score": 0.9},
    ],
}
b = pdf_map.graph_bounds(FAKE)
check("fake graph bounds", b == (-0.6, -0.3, 0.6, 0.4))
vp = pdf_map.fit_to_view(b, (640.0, 480.0), 48.0)
hit_r = pdf_map.node_radius(2) + pdf_map.HIT_SLOP


def _nodes(viewport):
    return [
        (p["safe"], *pdf_map.world_to_screen(viewport, *p["xy"]))
        for p in FAKE["pdfs"]
    ]


s1 = pdf_map.world_to_screen(vp, -0.5, -0.2)
check("hovering lec1's screen position hits lec1",
      pdf_map.hit_test(_nodes(vp), s1, hit_r) == "lec1")
c2 = pdf_map.world_to_screen(vp, 0.6, 0.4)
vp2 = pdf_map.zoom_at(pdf_map.zoom_at(vp, c2, 2.0), c2, 2.0)
w2 = pdf_map.screen_to_world(vp2, *c2)
check("after two anchored zooms lec2 is still under the cursor",
      abs(w2[0] - 0.6) < 1e-9 and abs(w2[1] - 0.4) < 1e-9
      and pdf_map.hit_test(_nodes(vp2), c2, hit_r) == "lec2")
check("its edge subset is exactly nid 3",
      [e["nid"] for e in pdf_map.edges_for_selection(FAKE["edges"], "lec2")]
      == [3])

# ------------------------------------------------------------ glue pins

section("glue pins on the source — divider, K-114, K-115, tokens")

_DIVIDER = "# ── aqt glue ──"
check("the aqt-glue divider is present", _DIVIDER in _SRC)
_head_code = code_only(_SRC.split(_DIVIDER)[0])
check("no aqt anywhere above the divider (comment/string-stripped)",
      "aqt" not in _head_code)
check("K-114: no .exec( anywhere — the window is show()-only",
      ".exec(" not in _CODE and "win.show()" in _CODE)
check("no focus steal: activateWindow appears nowhere in code",
      "activateWindow" not in _CODE)
check("no literal hex colours (comments stripped, strings KEPT)",
      re.search(r"#[0-9a-fA-F]{6}\b", _strip_comments(_SRC)) is None)
check("colours come from theme.palette tokens",
      "theme.palette(" in _CODE)

_paints = [n for n in ast.walk(_TREE)
           if isinstance(n, ast.FunctionDef) and n.name == "paintEvent"]


def _guarded(fn) -> bool:
    """True when the paintEvent holds a Try whose FINALLY ends the
    painter — the K-115 guarantee."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Attribute) and sub.attr == "end":
                        return True
    return False


check("K-115: exactly one paintEvent, guarded by try/finally painter.end()",
      len(_paints) == 1 and _guarded(_paints[0]))

check("WA_DeleteOnClose is set on the window", "WA_DeleteOnClose" in _CODE)

_closes = [n for n in ast.walk(_TREE)
           if isinstance(n, ast.FunctionDef) and n.name == "closeEvent"]


def _clears_singleton(fn) -> bool:
    has_global = any(
        isinstance(n, ast.Global) and "_instance" in n.names
        for n in ast.walk(fn)
    )
    clears = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_instance"
                for t in n.targets)
        and isinstance(n.value, ast.Constant) and n.value.value is None
        for n in ast.walk(fn)
    )
    return has_global and clears


check("closeEvent clears the module singleton (global + None assign)",
      len(_closes) == 1 and _clears_singleton(_closes[0]))

check("open_map_window(parent=None) is the public surface",
      list(inspect.signature(pdf_map.open_map_window).parameters) == ["parent"]
      and inspect.signature(pdf_map.open_map_window).parameters["parent"].default
      is None)
check("wheel zoom funnels through the anchored zoom_at math",
      "zoom_at(" in _func_seg("wheelEvent"))
check("the canvas draws edges through edges_for_selection only",
      "edges_for_selection(" in _func_seg("_paint"))
check("labels are placed by label_anchor, never inline arithmetic",
      len(_calls_in("_paint", "label_anchor")) == 1)

# ---- K-138: the note layer, and the name that follows the selection ----
_paint_seg = _func_seg("_paint")
check("K-138: the notes are drawn in ONE drawPoints call — no per-dot "
      "loop survives in the paint path (28k drawEllipse calls was 36 ms "
      "a frame; the Python transform loop alone was 9 ms of it)",
      _paint_seg.count("drawPoints(") == 1
      and "drawEllipse(QPointF(sx, sy), NOTE_DOT_R" not in _paint_seg
      and "for wx, wy in self._notes" not in _CODE)
check("the world->screen pass is QTransform.map on the POLYGON, and the "
      "PAINTER is never scaled — drawPoints under a scaled painter with "
      "a cosmetic pen degenerates into long horizontal strokes at zoom",
      "QTransform(" in _paint_seg
      and ".map(self._note_poly)" in _paint_seg
      and "painter.scale(" not in _CODE)
check("the note polygon is built ONCE, in the CANVAS constructor, in "
      "world space — the cloud does not change, the viewport does",
      "QPolygonF(" in _method_seg("_MapCanvas", "__init__")
      and _CODE.count("QPolygonF(") == 1)
check("K-138 reverses K-133: the painter names exactly the ACTIVE node, "
      "with no count or zoom gate left to consult",
      "if safe == active:" in _paint_seg
      and "labels_visible" not in _CODE
      and "show_labels" not in _CODE)
check("the header hint is ONE line naming both the legend and the "
      "gestures",
      "\n" not in pdf_map.HINT_TEXT
      and "PDF" in pdf_map.HINT_TEXT
      and "note" in pdf_map.HINT_TEXT
      and all(g in pdf_map.HINT_TEXT
              for g in ("hover", "drag", "pan", "scroll", "zoom")))
_hint_seg = _SRC.split("QLabel(HINT_TEXT", 1)[-1].split("addWidget(hint)", 1)[0]
check("it is drawn exactly once, from the pinned copy, in the muted token",
      _CODE.count("HINT_TEXT") == 2
      and "QLabel(HINT_TEXT" in _CODE
      and "muted_label_qss" in _hint_seg)
check("select_pdf(safe) is the public follow-the-viewer seam",
      list(inspect.signature(pdf_map.select_pdf).parameters) == ["safe"])
check("select_pdf reaches the canvas through the singleton and the one "
      "recenter_for rule — it never re-derives placement itself",
      "canvas.select(" in _func_seg("select_pdf")
      and "recenter_for(" in _method_seg("_MapCanvas", "select")
      and len(_calls_in("select", "recenter_for")) == 1)
check("hover tooltip rides QToolTip", "QToolTip.showText" in _CODE)
check("house logging prefix present", '"[klausmate] ' in _SRC.replace("f\"", "\""))
check("empty-state copy is pinned",
      pdf_map.EMPTY_TEXT == "No indexed PDFs to map yet."
      and "EMPTY_TEXT" in _CODE)

# ----------------------------------------------------- stub-harness smoke

section("glue smoke under the stub harness")

check("select_pdf with NO map open is a silent no-op — the viewer must "
      "be free to call it on every file without asking first",
      pdf_map._instance is None and pdf_map.select_pdf("anything") is False)

curation = importlib.import_module("klausmate.curation")
tmp = tempfile.mkdtemp(prefix="klaus_map_")
_orig_uf = curation.USER_FILES
curation.USER_FILES = tmp  # NEVER the real user_files
try:
    win = pdf_map.open_map_window(None)
    check("open_map_window builds under stubs (empty-graph path)",
          win is not None)
    check("the module singleton is set", pdf_map._instance is win)
    check("an empty graph builds the empty-state window (no canvas)",
          getattr(win, "canvas", "sentinel") is None)
    win2 = pdf_map.open_map_window(None)
    check("a second call fronts the SAME window", win2 is win)
    _cap, sys.stdout = sys.stdout, io.StringIO()
    try:
        _quiet = (pdf_map.select_pdf("lec1"), sys.stdout.getvalue())
    finally:
        sys.stdout = _cap
    check("an empty-graph window has no canvas, so select_pdf no-ops "
          "SILENTLY — not by raising into the blanket except and "
          "printing an error the reader can do nothing about",
          _quiet == (False, ""), repr(_quiet))
finally:
    curation.USER_FILES = _orig_uf
    pdf_map._instance = None
    shutil.rmtree(tmp, ignore_errors=True)

_orig_load = pdf_map._load_graph
_orig_fill = pdf_map._fill_retention
pdf_map._load_graph = lambda: FAKE
pdf_map._fill_retention = lambda g: None
try:
    win3 = pdf_map.open_map_window(None)
    check("a populated graph builds the canvas window",
          win3 is not None and getattr(win3, "canvas", None) is not None)
    check("the canvas indexed both pdf nodes and every positioned note",
          set(win3.canvas._pdf_xy) == {"lec1", "lec2"}
          and set(win3.canvas._note_xy) == {1, 2, 3})
    # The geometry half of select_pdf needs real widget sizes, so it
    # lives in the offscreen-Qt section below. Clearing needs none —
    # but it needs something to clear, or it passes vacuously.
    win3.canvas._selected = "lec1"
    check("an unknown name CLEARS the selection rather than leaving a "
          "stale ring over a PDF you are no longer looking at",
          pdf_map.select_pdf("not-on-this-map") is False
          and win3.canvas._selected is None)
    win3.canvas._selected = "lec1"
    check("None and the empty string clear it the same way",
          pdf_map.select_pdf(None) is False
          and win3.canvas._selected is None
          and pdf_map.select_pdf("") is False)
finally:
    pdf_map._load_graph = _orig_load
    pdf_map._fill_retention = _orig_fill
    pdf_map._instance = None

# ------------------------------------------------- real offscreen Qt

section("real offscreen Qt — the note layer, the name, the viewer seam")
# PyQt6 is installed for THIS interpreter (Anki's bundled one is 3.13
# bytecode; ours is not) — test_drive.py's precedent. open_map_window
# imports aqt.qt lazily inside itself, so swapping the module in
# sys.modules is the whole bootstrap: nothing needs re-importing.
# Everything here is a claim the _Any stubs above physically cannot
# make, because _Dummy has no geometry and paints no pixels.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402

    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "the pure model and source pins above still ran")

if _HAVE_QT:
    _qt_shim = types.ModuleType("aqt.qt")

    def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
        for _m in _mods:
            if hasattr(_m, name):
                return getattr(_m, name)
        if name == "qconnect":
            return lambda sig, fn: sig.connect(fn)
        raise AttributeError(name)

    _qt_shim.__getattr__ = _qt_getattr
    sys.modules["aqt.qt"] = _qt_shim

    theme = importlib.import_module("klausmate.theme")
    _orig_night = theme.night_mode
    _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    def _dark_pixels(widget, w, h):
        """Count near-black pixels in a rendered widget.

        With a light palette, no notes and one accent circle, the ONLY
        near-black ink on the canvas is text — which makes "is this PDF
        named right now?" a countable question rather than an opinion.
        """
        img = _QtG.QImage(w, h, _QtG.QImage.Format.Format_ARGB32)
        img.fill(0)
        widget.render(img)
        n = 0
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                c = img.pixelColor(x, y)
                if c.alpha() > 200 and c.red() + c.green() + c.blue() < 200:
                    n += 1
        return n

    # One PDF, NO notes: the only ink that can be dark is its name.
    NAMED = {
        "pdfs": [{"safe": "solo", "display": "Renal Physiology", "folder": None,
                  "threshold": 0.4, "retention": None, "xy": [0.0, 0.0],
                  "match_count": 9}],
        "notes": [], "edges": [],
    }
    pdf_map._fill_retention = lambda g: None
    try:
        theme.night_mode = lambda: False
        pdf_map._load_graph = lambda: NAMED
        w4 = pdf_map.open_map_window(None)
        w4.resize(700, 500)
        cv = w4.canvas
        cv.resize(660, 420)
        _app.processEvents()
        quiet = _dark_pixels(cv, 660, 420)
        cv._hover = "solo"
        named = _dark_pixels(cv, 660, 420)
        check("K-138 reverses K-133 ON THE PIXELS: at rest the map draws "
              "no PDF name at all, and hovering the circle draws one",
              quiet == 0 and named > 0,
              f"quiet={quiet} hovered={named}")
        cv._hover = None
        cv._selected = "solo"
        check("selecting names it too — that is what the viewer seam "
              "gets, since it selects rather than hovers",
              _dark_pixels(cv, 660, 420) > 0)
    finally:
        pdf_map._instance = None
        theme.night_mode = _orig_night

    # A real cloud: every note reaches the polygon, and both palettes
    # paint it without raising.
    _rng = random.Random(4)
    _notes = [{"nid": i, "xy": [_rng.gauss(0, .3), _rng.gauss(0, .3)]}
              for i in range(1500)]
    CLOUD = {
        "pdfs": [
            {"safe": "lec1", "display": "Lecture One", "folder": None,
             "threshold": .4, "retention": None, "xy": [-0.5, -0.2],
             "match_count": 40},
            {"safe": "lec2", "display": "Lecture Two", "folder": "F",
             "threshold": .4, "retention": None, "xy": [0.6, 0.4],
             "match_count": 12},
        ],
        "notes": _notes,
        "edges": [{"pdf": "lec1", "nid": i, "score": .9} for i in range(40)],
    }
    try:
        for _night in (False, True):
            theme.night_mode = lambda n=_night: n
            pdf_map._load_graph = lambda: CLOUD
            w5 = pdf_map.open_map_window(None)
            w5.resize(900, 640)
            cv = w5.canvas
            cv.resize(860, 560)
            _app.processEvents()
            if not _night:
                check("every positioned note reaches the note polygon — "
                      "no cap, no sample, no level-of-detail",
                      cv._note_poly.count() == len(_notes) == 1500,
                      f"{cv._note_poly.count()} of {len(_notes)}")
            _img = _QtG.QImage(860, 560, _QtG.QImage.Format.Format_ARGB32)
            _img.fill(0)
            cv.render(_img)
            _seen = {_img.pixelColor(x, y).name()
                     for y in range(0, 560, 3) for x in range(0, 860, 3)}
            check(f"the cloud paints in the {'night' if _night else 'day'} "
                  "palette (several distinct inks, nothing raised)",
                  len(_seen) > 3, str(len(_seen)))

            # ---- select_pdf's geometry half, on real widget sizes ----
            if not _night:
                cv._apply_fit(860.0, 560.0)
                _before = cv._vp
                check("select_pdf(known) selects that node and reports True",
                      pdf_map.select_pdf("lec2") is True
                      and cv._selected == "lec2")
                check("a node already in view is not chased — the map must "
                      "not jump under the reader on every file change",
                      cv._vp is _before)
                cv._vp = pdf_map.pan_by(cv._vp, -5000.0, -5000.0)
                _cw, _ch = float(cv.width()), float(cv.height())
                _sx, _sy = pdf_map.world_to_screen(cv._vp, -0.5, -0.2)
                check("(that node really was off-view first)",
                      not (0 <= _sx <= _cw and 0 <= _sy <= _ch))
                _took = pdf_map.select_pdf("lec1")
                _now = pdf_map.world_to_screen(cv._vp, -0.5, -0.2)
                check("select_pdf recentres an off-view node and keeps the "
                      "zoom the reader chose",
                      _took is True
                      and cv._selected == "lec1"
                      and cv._vp.scale == _before.scale
                      and abs(_now[0] - _cw / 2.0) < 1e-6
                      and abs(_now[1] - _ch / 2.0) < 1e-6,
                      f"node at {_now} in a {_cw}x{_ch} canvas")
            pdf_map._instance = None
    finally:
        pdf_map._instance = None
        pdf_map._load_graph = _orig_load
        pdf_map._fill_retention = _orig_fill
        theme.night_mode = _orig_night

raise SystemExit(report())
