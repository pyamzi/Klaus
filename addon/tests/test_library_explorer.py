"""Tests for library_explorer — the Library tree as VS Code's Explorer (K-175).

Three layers, in the order they can fail:

* PURE geometry and colour pins, under the aqt stubs — the 4px grid, the
  guide positions, the icon points inside their box, tokens only.
* REAL offscreen PyQt6 — the delegate on a genuine QTreeWidget under the
  real theme sheet, grabbed to an image and read back pixel by pixel:
  one continuous band across the cells, guides where the pure helper
  says, icon ink in the item's own colour.
* The Library WINDOW — a real DriveWindow built offscreen with the
  delegate and the glyph actions wired in.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_library_explorer.py
"""
import ast
import contextlib
import importlib
import io
import os
import re
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

_SRC = open("klausmate/library_explorer.py", encoding="utf-8").read()
le = importlib.import_module("klausmate.library_explorer")
theme = importlib.import_module("klausmate.theme")

# ---------------------------------------------------------------- pure
section("geometry on the 4px grid")
check("22px rows — K-117's ask, K-130: do not inflate", le.ROW_H == 22)
check("the branch cell is one 16px twisty box", le.INDENT == 16)
check("codicon-size icon box", le.ICON_BOX == 16)
check("the label starts 24px in: pad + icon + gap, on the grid",
      le.label_inset() == 24 and le.label_inset() % le.GRID == 0)
check("action hit box is VS Code's 22px row, 24 wide",
      (le.ACTION_W, le.ACTION_H) == (24, 22))
check("the sash is a hairline plus a 4px grab", le.SASH_W == 5)
check("a top-level row has no guides", le.guide_xs(0) == ())
check("a depth-1 row's guide sits at its parent's twisty centre (8)",
      le.guide_xs(1) == (8,))
check("a depth-3 row hangs under all three ancestors' chevrons",
      le.guide_xs(3) == (8, 24, 40))
check("guides follow the tree's own indentation, not the constant",
      le.guide_xs(2, indent=12) == (6, 18))
check("the icon box is padded 4 and centred in a 22px cell",
      le.icon_rect(0, 0, 22) == (4, 3, 16, 16))
check("...and translates with the cell",
      le.icon_rect(40, 100, 22) == (44, 103, 16, 16))


def _inside(points, x=0.0, y=0.0, size=16.0):
    return all(x <= px <= x + size and y <= py <= y + size for px, py in points)


_folder = le.folder_icon(0, 0)
check("the folder icon is a closed outline of at least six points, all "
      "inside its 16px box", len(_folder) >= 6 and _inside(_folder))
check("...with a tab: a top edge higher than the body's top",
      min(p[1] for p in _folder) < sorted({p[1] for p in _folder})[1])
_outline, _fold = le.page_icon(0, 0)
check("the page icon stays inside its box", _inside(_outline) and _inside(_fold))
check("...and the fold shares the page's turned corner",
      _fold[0] in _outline and _fold[-1] in _outline)
for _kind in le.KINDS:
    _g = le.glyph(_kind, 0, 0)
    _pts = []
    for key in ("polygons", "polylines"):
        for poly in _g.get(key, ()):
            _pts += list(poly)
    for a, b in _g.get("lines", ()):
        _pts += [a, b]
    for (ax, ay, w, h, _s, _sp) in _g.get("arcs", ()):
        _pts += [(ax, ay), (ax + w, ay + h)]
    for cx, cy, r in _g.get("dots", ()):
        _pts += [(cx - r, cy - r), (cx + r, cy + r)]
    check(f"glyph {_kind!r} draws something, all of it inside the 16px box",
          len(_pts) >= 2 and _inside(_pts), repr(_pts))
check("the four kinds are exactly the four caption actions",
      le.KINDS == ("new-folder", "refresh", "map", "fit"))
try:
    le.glyph("sparkle", 0, 0)
    check("an unknown glyph kind raises rather than drawing nothing", False)
except ValueError:
    check("an unknown glyph kind raises rather than drawing nothing", True)


class _Invalid:
    def isValid(self):
        return False

    def parent(self):
        return self


_INVALID = _Invalid()


class _Idx:
    def __init__(self, parent=None):
        self._p = parent

    def parent(self):
        return self._p if self._p is not None else _INVALID

    def isValid(self):
        return True


check("depth_of: top-level is 0", le.depth_of(_Idx()) == 0)
check("depth_of: counts every ancestor",
      le.depth_of(_Idx(_Idx(_Idx(_Idx())))) == 3)

section("colours are tokens, never invented")
for night in (False, True):
    c = theme.palette(night)
    check(f"night={night}: the selected band is the accent pre-composited "
          "over the TREE's ground (bg), the exact ink the sheet uses",
          le.band_colour(True, False, night)
          == theme.accent_mix(night, 0.16, base="bg"))
    check(f"night={night}: the hover band is the hover_subtle token",
          le.band_colour(False, True, night) == c["hover_subtle"])
    check(f"night={night}: selected beats hover",
          le.band_colour(True, True, night)
          == le.band_colour(True, False, night))
    check(f"night={night}: a resting row has no band",
          le.band_colour(False, False, night) is None)
    check(f"night={night}: icon ink defaults to text_muted",
          le.ink_colour(night) == c["text_muted"])
    check(f"night={night}: ...follows an item's own foreground",
          le.ink_colour(night, c["text_faint"]) == c["text_faint"])
    check(f"night={night}: ...and goes faint when disabled, whatever the "
          "foreground",
          le.ink_colour(night, c["text"], enabled=False) == c["text_faint"])
    check(f"night={night}: guides are grey_mid", le.guide_colour(night) == c["grey_mid"])
check("no hex colour literal anywhere in the module (raw source, not "
      "code_only — string literals are exactly where one would hide)",
      not re.search(r"#[0-9A-Fa-f]{6}\b", _SRC))
check("accent_mix still defaults to surface — every other caller is "
      "unchanged by the new base parameter",
      theme.accent_mix(False, 0.16) == theme.accent_mix(False, 0.16, base="surface")
      and theme.accent_mix(False, 0.16) != theme.accent_mix(False, 0.16, base="bg"))

section("the two paint guards")
_tree = ast.parse(_SRC)
_fns = {n.name: n for n in ast.walk(_tree) if isinstance(n, ast.FunctionDef)}


def _ends_painter_in_finally(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and node.finalbody:
            dumped = ast.dump(ast.Module(body=node.finalbody, type_ignores=[]))
            if "attr='end'" in dumped:
                return True
    return False


check("GlyphButton.paintEvent ends its QPainter in a finally (K-115: a "
      "painter left live after an exception segfaults the next flush)",
      "paintEvent" in _fns and _ends_painter_in_finally(_fns["paintEvent"]))
check("ExplorerDelegate.paint cannot let an exception reach C++ (K-172: "
      "an unhandled one in a virtual is qFatal)",
      "paint" in _fns and isinstance(_fns["paint"].body[0], ast.Try)
      and any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
              for h in _fns["paint"].body[0].handlers))
check("the painter's save/restore around the icon is balanced by a finally",
      "_paint_name_cell" in _fns
      and any(isinstance(n, ast.Try) and n.finalbody
              and "attr='restore'" in ast.dump(
                  ast.Module(body=n.finalbody, type_ignores=[]))
              for n in ast.walk(_fns["_paint_name_cell"])))

# ------------------------------------------------------------ real Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC
    from PyQt6 import QtGui as _QtG
    from PyQt6 import QtWidgets as _QtW
    _HAVE_QT = True
except Exception as _e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable ({_e}) — widget checks skipped")

if not _HAVE_QT:
    raise SystemExit(report())

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
for _name in [m for m in list(sys.modules) if m.startswith("klausmate.")]:
    del sys.modules[_name]
pkg = sys.modules["klausmate"]
le = importlib.import_module("klausmate.library_explorer")
theme = importlib.import_module("klausmate.theme")
app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

ROLE_SAFE = _QtC.Qt.ItemDataRole.UserRole
ROLE_FOLDER = _QtC.Qt.ItemDataRole.UserRole + 1


def _hex(img, x, y):
    return _QtG.QColor(img.pixel(int(x), int(y))).name().upper()


def _box_pixels(img, rect):
    x, y, w, h = rect
    return {(px, py): _hex(img, px, py)
            for px in range(x, x + w) for py in range(y, y + h)}


section("real Qt: the delegate paints an Explorer row")
_wrap = _QtW.QWidget()
_wrap.setObjectName("KlausLibraryWindow")
_wrap.setAttribute(_QtC.Qt.WidgetAttribute.WA_StyledBackground, True)
_wrap.setStyleSheet(theme.library_qss(False))
_lay = _QtW.QVBoxLayout(_wrap)
_lay.setContentsMargins(0, 0, 0, 0)
_t = _QtW.QTreeWidget(_wrap)
_t.setColumnCount(4)
_t.setHeaderLabels(["PDF", "Retention", "Cards", "Notes"])
_t.header().setStretchLastSection(False)
_t.header().setSectionResizeMode(0, _QtW.QHeaderView.ResizeMode.Stretch)
for _col in (1, 2, 3):
    _t.header().setSectionResizeMode(_col, _QtW.QHeaderView.ResizeMode.Fixed)
_t.setColumnWidth(1, 84)
_t.setColumnWidth(2, 88)
_t.setColumnWidth(3, 88)
_t.setIndentation(le.INDENT)
_t.setUniformRowHeights(True)
_t.setMouseTracking(True)
_lay.addWidget(_t)
_delegate = le.install(_t, False, lambda idx: bool(idx.data(ROLE_FOLDER)))
check("install() puts an ExplorerDelegate on the tree and keeps it alive",
      isinstance(_t.itemDelegate(), le.ExplorerDelegate)
      and _t._klaus_explorer is _delegate)

_folder = _QtW.QTreeWidgetItem(_t, ["Epidemiology", "", "", ""])
_folder.setData(0, ROLE_FOLDER, "Epidemiology")
_child = _QtW.QTreeWidgetItem(_folder, ["Measures of Disease Frequency", "41%", "43", "12"])
_child.setData(0, ROLE_SAFE, "Measures")
_sub = _QtW.QTreeWidgetItem(_folder, ["Unit 2", "", "", ""])
_sub.setData(0, ROLE_FOLDER, "Epidemiology/Unit 2")
_grand = _QtW.QTreeWidgetItem(_sub, ["RCTs and Measures of Association", "47%", "31", "9"])
_grand.setData(0, ROLE_SAFE, "RCTs")
_folder.setExpanded(True)
_sub.setExpanded(True)
_wrap.resize(520, 260)
_wrap.show()
app.processEvents()
_t.setCurrentItem(_child)
app.processEvents()

_log = io.StringIO()
with contextlib.redirect_stdout(_log):
    _img = _t.viewport().grab().toImage()
    app.processEvents()
check("painting three levels raised nothing — a delegate failure logs and "
      "falls back, and nothing was logged", "[klausmate]" not in _log.getvalue(),
      _log.getvalue())

_c0 = _t.visualRect(_t.indexFromItem(_child, 0))
_c2 = _t.visualRect(_t.indexFromItem(_child, 2))
_mid = _c0.center().y()
check("rows are exactly 22px under the sheet + delegate", _c0.height() == 22,
      f"{_c0.height()}px")
_band = theme.accent_mix(False, 0.16, base="bg")
check("the selected row's name cell carries the accent band from its very "
      "first pixel (the delegate paints the WHOLE cell, not the stepped "
      "text rect)", _hex(_img, _c0.x() + 1, _mid) == _band,
      f"{_hex(_img, _c0.x() + 1, _mid)} vs {_band}")
check("...and the Cards cell, painted by the sheet, is the SAME ink — one "
      "bar across every cell", _hex(_img, _c2.x() + 2, _mid) == _band,
      f"{_hex(_img, _c2.x() + 2, _mid)} vs {_band}")
check("the branch cell to the left is that ink too (show-decoration-"
      "selected + ::branch:selected, the K-130 trio)",
      _hex(_img, _c0.x() - 8, _mid) == _band,
      f"{_hex(_img, _c0.x() - 8, _mid)}")

_g0 = _t.visualRect(_t.indexFromItem(_grand, 0))
_gmid = _g0.center().y()
_origin = _g0.x() - 3 * le.INDENT
check("the depth-2 row's ground is the tree's bg (the sidebar token, not "
      "a white card)", _hex(_img, _g0.x() + 1, _gmid) == theme.palette(False)["bg"],
      _hex(_img, _g0.x() + 1, _gmid))
for _gx in le.guide_xs(2):
    check(f"an indent guide at x={_gx} of the depth-2 row, in grey_mid",
          _hex(_img, _origin + _gx, _gmid) == theme.palette(False)["grey_mid"],
          _hex(_img, _origin + _gx, _gmid))
check("...and NO guide where the row has no ancestor (the top-level "
      "folder's own twisty column is clean)",
      _hex(_img, _origin + le.guide_xs(1)[0],
           _t.visualRect(_t.indexFromItem(_folder, 0)).center().y())
      != theme.palette(False)["grey_mid"])

_child_box = _box_pixels(_img, le.icon_rect(_c0.x(), _c0.y(), _c0.height()))
_ink_px = [p for p, col in _child_box.items() if col != _band]
check("a page icon is painted in the selected row's icon box",
      len(_ink_px) >= 8, f"{len(_ink_px)} ink pixels")
check("...in text_muted, the default icon ink (a fully covered stroke "
      "pixel is exact, not blended)",
      theme.palette(False)["text_muted"] in _child_box.values())
_f0 = _t.visualRect(_t.indexFromItem(_folder, 0))
_folder_box = _box_pixels(_img, le.icon_rect(_f0.x(), _f0.y(), _f0.height()))
_fold_px = {p for p, col in _folder_box.items() if col != theme.palette(False)["bg"]}
# Compared as POSITIONS relative to each row's own icon box: the same
# glyph on two grounds marks the same positions, so equal sets mean the
# same icon. (The first cut translated one set the wrong way and could
# never fail — caught by mutating the folder icon into the page icon.)
_fold_rel = {(x - _f0.x(), y - _f0.y()) for (x, y) in _fold_px}
_page_rel = {(x - _c0.x(), y - _c0.y()) for (x, y) in _ink_px}
check("a folder row gets a DIFFERENT icon from a PDF row",
      _fold_rel and _page_rel and _fold_rel != _page_rel,
      f"{len(_fold_rel)} vs {len(_page_rel)} marked positions")
check("the label starts past the icon: the pixel column right after the "
      "icon gap is band, not glyph",
      _hex(_img, _c0.x() + le.label_inset() - 1, _mid) == _band)

# A fully suspended PDF dims its whole row (K-117) — the icon follows.
_faint = _QtG.QBrush(_QtG.QColor(theme.palette(False)["text_faint"]))
for _col in range(4):
    _grand.setForeground(_col, _faint)
app.processEvents()
_img2 = _t.viewport().grab().toImage()
_grand_box = _box_pixels(_img2, le.icon_rect(_g0.x(), _g0.y(), _g0.height()))
check("a dimmed row's icon is painted in the row's own faint foreground",
      theme.palette(False)["text_faint"] in _grand_box.values())

section("real Qt: glyph actions")
for _kind in le.KINDS:
    _b = le.GlyphButton(_kind, f"{_kind} — does a thing", False)
    _b.show()
    app.processEvents()
    _bi = _b.grab().toImage()
    _ground = _hex(_bi, 0, 0)
    _drawn = sum(1 for x in range(_bi.width()) for y in range(_bi.height())
                 if _hex(_bi, x, y) != _ground)
    check(f"{_kind}: paints a glyph ({_drawn} px), 24x22, tooltip and "
          "accessible name set",
          _drawn >= 8 and (_b.width(), _b.height()) == (24, 22)
          and _b.toolTip().startswith(_kind)
          and _b.accessibleName() == _kind)
    _b.setEnabled(False)
    _log = io.StringIO()
    with contextlib.redirect_stdout(_log):
        _bi2 = _b.grab().toImage()
    _drawn2 = sum(1 for x in range(_bi2.width()) for y in range(_bi2.height())
                  if _hex(_bi2, x, y) != _hex(_bi2, 0, 0))
    check(f"{_kind}: disabled still paints (faint), and logs nothing",
          _drawn2 >= 8 and "[klausmate]" not in _log.getvalue())
try:
    le.GlyphButton("sparkle", "no", False)
    check("an unknown kind is refused at construction", False)
except ValueError:
    check("an unknown kind is refused at construction", True)
check("an accessible name drops the ellipsis and the sentence",
      le.GlyphButton("new-folder", "New Folder…", False).accessibleName()
      == "New Folder")

section("wired into the Library window")
_uf = tempfile.mkdtemp(prefix="klaus_k175_uf_")
os.makedirs(os.path.join(_uf, "contexts"), exist_ok=True)
pkg.USER_FILES = _uf
_PD_SRC = open("klausmate/pdf_drive.py", encoding="utf-8").read()
check("pdf_drive imports the Explorer behind a guard — test_drive's fixed "
      "aqt.qt stub lacks QToolButton/QStyledItemDelegate, and a missing "
      "module must cost the look, never the Library",
      re.search(r"try:\s*\n\s*from \. import library_explorer\s*\n"
                r"except Exception:.*\n\s*library_explorer = None", _PD_SRC))
check("the K-117 text buttons survive as the explicit fallback",
      'QPushButton("Map", left)' in _PD_SRC
      and 'QPushButton("New Folder…", left)' in _PD_SRC
      and 'QPushButton("Refresh", left)' in _PD_SRC)
try:
    pdf_drive = importlib.import_module("klausmate.pdf_drive")
    _log = io.StringIO()
    with contextlib.redirect_stdout(_log):
        _win = pdf_drive.DriveWindow()
        app.processEvents()
    check("the Library's tree carries the ExplorerDelegate",
          isinstance(_win.tree.itemDelegate(), le.ExplorerDelegate))
    _glyphs = _win.findChildren(le.GlyphButton)
    check("the caption rows carry the four glyph actions",
          sorted(g.kind for g in _glyphs) == sorted(le.KINDS),
          repr(sorted(g.kind for g in _glyphs)))
    _tips = {g.kind: g.toolTip() for g in _glyphs}
    check("each glyph names its action in the tooltip",
          _tips.get("new-folder", "").startswith("New Folder")
          and _tips.get("refresh") == "Refresh"
          and _tips.get("map", "").startswith("Embedding map")
          and _tips.get("fit", "").startswith("Fit"))
    check("Fit is the map box's own button, disabled until a canvas exists",
          isinstance(_win.map_fit_btn, le.GlyphButton)
          and not _win.map_fit_btn.isEnabled())
    check("the header stays — sorting by column is the Library's ranking "
          "UI, worst-first by default",
          not _win.tree.isHeaderHidden() and _win.tree.isSortingEnabled()
          and _win.tree.sortColumn() == 1)
    check("the main sash is VS Code's: hairline + 4px grab",
          _win.splitter.handleWidth() == le.SASH_W,
          f"{_win.splitter.handleWidth()}px")
    check("nothing about the Explorer failed while building the window",
          "explorer" not in _log.getvalue() and "glyph" not in _log.getvalue(),
          _log.getvalue()[-400:])
    _win.close()
except Exception as _e:  # noqa: BLE001
    check(f"offscreen DriveWindow checks ran ({_e})", False)

raise SystemExit(report())
