# Constellation Map and Panel Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the embedding map read as a dim, fully-connected constellation that visibly turns in 3D, lights up under the mouse and for the chosen PDF only, sits flat on the Library panel with no card, no plate and no glow — and make the Library's panels wear the top bar's colour with the PDF pane a step darker.

**Architecture:** Two file-disjoint phases so two board lanes can run them in parallel. Phase A is entirely inside `klausmate/pdf_map.py` (a pure-geometry top half tested headless, a Qt canvas class below a divider rendered offscreen): retire the canvas's own always-dark palette so it paints on the host's ground; drop the rounded card, vignette, node halo and label plate; add a canvas-wide `lit` factor animated on enter/leave; replace the 72 s full turn with a ±16° sway at a stronger perspective; and give `constellation_links` a connected `"constellation"` mode (minimum-spanning-tree backbone plus nearest neighbours). Phase B moves the Library's ground token from `bg` to `chrome` (the top bar's token) and paints the documentless `QPdfView` viewport in `bg`, which in both palettes is one step darker than `chrome`.

**Tech Stack:** Python (3.13 in Anki; system `python3` is 3.9.6 and is the test interpreter — it lacks `math.sumprod`, so never time on it; `python3.14` exists for timing), PyQt6 with `QT_QPA_PLATFORM=offscreen`, the repo's plain-script test harness (`check(name, cond, detail)` in `tests/test_*.py`, run with `python3 tests/test_X.py`), the agent board (`python3 board/board.py`).

**Spec:** Pouya, 2026-09-01, verbatim, in the `/superpowers:writing-plans` invocation:

> * Can you have all the nodes be interconnected in a satisfying way, and then have the constellation do a slight rotation in 3D so that 3D-ness is very apparent?
> * While I put my mouse over it, I want it to light up a little bit more. I want it to be dim, but then, as I put the mouse over it, it lights up to normal values, if that makes sense.
> * I want the "what is it called" when we choose a PDF, just for that one, to light up.
> * I want everything to be dim otherwise. Can you remove the little box around it and remove the general glow? I don't like the general glow that comes with it.
> * I want this to feel like it's integrated, like it's part of the actual panel.
> * I want the panels, like the left panel, to be the same color as the top bar.
> * I want the middle area for the PDF to be darker.

Reading of the ambiguous items, so every task argues from one interpretation: "the little box around it" is TWO boxes — the rounded card the canvas paints around itself (`_paint_ground`, `drawRoundedRect(card, 12, 12)`) and the label plate behind the focused PDF's name (`_paint_label`, `LABEL_PLATE_ALPHA`); both go. "The general glow" is the radial halo gradient on the lit PDF node (`NODE_HALO_F`) plus the vignette lift under the whole field (`VIGNETTE_LIFT`); the crisp ring and core of a PDF node — what he earlier called "the shininess of the PDFs" — stay. "What is it called" is the PDF's display name: it is drawn bare, bright for the selected PDF only. "Dim otherwise" is a canvas-wide brightness that rests at `DIM_LIT` and ramps to 1.0 while the pointer is over the canvas; the selected PDF and its name are exempt from the dimming.

## Global Constraints

- **Always edit the main checkout** `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`, never a worktree copy: Anki loads the addon through a symlink to the main checkout only, and the PostToolUse compile hook compiles that target. (CLAUDE.md)
- **Every task claims a board card before editing** (`python3 board/board.py add … && claim`), and the two phases must stay file-disjoint: Phase A touches `klausmate/pdf_map.py` and `tests/test_pdf_map.py`; Phase B touches `klausmate/theme.py`, `klausmate/library_explorer.py`, `klausmate/pdf_viewer.py`, `tests/test_theme.py`, `tests/test_library_explorer.py`, `tests/test_drive.py`. `board.py check-disjoint` must pass. (CLAUDE.md, "The agent board")
- **A card's `verify:` must fail before the work and pass after.** Every task below writes its failing pins first and shows the red run.
- **Every new pin is mutated once and watched failing** before the task's commit, with `PYTHONDONTWRITEBYTECODE=1` and both `__pycache__` and `~/Library/Caches/com.apple.python` purged — a same-size edit inside one mtime second runs stale bytecode. (CLAUDE.md, klaus-test skill)
- **Speed is a floor, not a target:** the map's frame stays under 4 ms measured (`python3.14`, median of 40 paints, 1100×660). Pouya: "you've made it a lot faster. I'm really happy with how you did that." Any task that raises the median above 2.5 ms must say so with the number.
- **No literal hex in UI files** — every colour is a `theme.palette()` token; `tests/test_drive.py` carries a tokenizer-based pin for `pdf_drive.py` and `tests/test_theme.py` audits builders. (CLAUDE.md, `theme.py` entry)
- **Every `paintEvent` is try/except-log/finally-`painter.end()`** (K-115); **no app-modal `exec()`** (K-114); **tests never touch `klausmate/user_files/`** — `tempfile.mkdtemp()` only.
- **Offscreen renders are the acceptance test**, and they can do more than "does it construct": `QT_SCALE_FACTOR=2` for Retina, `WA_UnderMouse` + `QtGui.QEnterEvent`/`QHoverEvent` for hover, `setDown(True)` for pressed, pixel-diff against a rest frame to prove a state took. What they cannot do: screencapture the live window or drive the real event loop (`singleShot(0)` needs one explicit `processEvents()`). `PyQt6-WebEngine` is not installed for system `python3`, so pdf.js pixels cannot be produced headless — say so rather than claim them. (CLAUDE.md, "Anki runtime & testing")
- **Never drive Pouya's running Anki as a test fixture.** If its process id changes to one you did not launch, he is at the machine.
- **Commit per task**, message ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; never stage `klausmate/user_files/` or `meta.json*`.

---

## File Structure

| File | Responsibility in this plan |
|---|---|
| `klausmate/pdf_map.py` (modify) | Phase A, all of it. Pure geometry above the `_canvas_class()` divider gains `sway_angle()`, `spanning_tree()`, a `"constellation"` link mode and a `lit` parameter on `star_colour()`; the canvas class below it loses its card/vignette/halo/plate painting, gains the `lit` property with its enter/leave animation, and sways instead of turning. Constants removed: `VIGNETTE_LIFT`, `VIGNETTE_SPREAD`, `NODE_HALO_F`, `LABEL_PLATE_ALPHA`, `LABEL_PAD_X`, `LABEL_PAD_Y`, `ROTATE_PERIOD_MS`. Added: `DIM_LIT`, `LIT_MS`, `SWAY_AMP`, `SWAY_PERIOD_MS`; `CAM_DISTANCE` 2.6 → 2.0; `LINK_MODE` `"knn"` → `"constellation"`. |
| `tests/test_pdf_map.py` (modify) | Phase A pins. Contradicting pins named in each task are inverted, never deleted silently. |
| `klausmate/theme.py` (modify) | Phase B: `library_qss()` paints the Library window and tree on `chrome`; `pdf_panel_qss()` keeps `bg`. |
| `klausmate/library_explorer.py` (modify) | Phase B: `BAND_BASE` becomes `"chrome"` so the selection band composites over the real ground. |
| `klausmate/pdf_viewer.py` (modify) | Phase B: the documentless `QPdfView` viewport paints `bg`. |
| `tests/test_theme.py`, `tests/test_library_explorer.py`, `tests/test_drive.py` (modify) | Phase B pins. |
| `CLAUDE.md` (modify, Task 9) | The `pdf_map.py` entry's "light palette stays dark" sentence and the K-174 look description become stale and are corrected. |

**Harness idiom every Phase A test step uses** (it is `tests/test_pdf_map.py`'s existing bootstrap — the file swaps `sys.modules["aqt.qt"]` for a PyQt6 shim and builds canvases with `pdf_map.map_canvas(None, graph)`; `FAKE` is the file's existing four-PDF fixture graph):

```python
# Already at the top of tests/test_pdf_map.py — shown so a step can be read alone.
import os, sys, types, importlib, math
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install; install()
from PyQt6 import QtCore as C, QtGui as G, QtWidgets as W
shim = types.ModuleType("aqt.qt")
def _get(name, mods=(W, C, G)):
    for m in mods:
        if hasattr(m, name): return getattr(m, name)
    if name == "qconnect": return lambda s, f: s.connect(f)
    raise AttributeError(name)
shim.__getattr__ = _get; sys.modules["aqt.qt"] = shim
pdf_map = importlib.import_module("klausmate.pdf_map")
theme = importlib.import_module("klausmate.theme")
app = W.QApplication.instance() or W.QApplication(["klaus-test"])

def _grab(cv, w=900, h=560, night=True):
    """Show a canvas at a fixed size with rotation off and return its QImage."""
    theme.night_mode = lambda n=night: n
    cv.resize(w, h); cv.show(); cv._reduce_motion = lambda: True
    for _ in range(3): app.processEvents()
    return cv.grab().toImage()

def _luma(img, x, y):
    px = img.pixel(int(x), int(y))
    return 0.2126 * ((px >> 16) & 255) + 0.7152 * ((px >> 8) & 255) + 0.0722 * (px & 255)

def _mean_luma(img, x0, y0, x1, y1, step=3):
    tot = n = 0
    for y in range(int(y0), int(y1), step):
        for x in range(int(x0), int(x1), step):
            tot += _luma(img, x, y); n += 1
    return tot / max(1, n)
```

---

## Phase A — the constellation (`klausmate/pdf_map.py`, `tests/test_pdf_map.py`)

### Task 1: The map paints on the panel's ground — no card, no vignette, no border

**Files:**
- Modify: `klausmate/pdf_map.py` — `_paint()` (~line 2525: `c = theme.palette(True)` / `host = theme.palette(theme.night_mode())`), `_paint_ground()` (~2580–2600), constants `VIGNETTE_LIFT` (598) and `VIGNETTE_SPREAD`
- Test: `tests/test_pdf_map.py`

**Interfaces:**
- Consumes: `theme.palette(night) -> dict` with keys `bg`, `chrome`, `surface`, `blue_bright`, `text`, `text_muted`, `grey_light`.
- Produces: the canvas's working palette `c` is now `dict(theme.palette(theme.night_mode()), bg=<that palette's "chrome">)` — every later task blends colours from `c["bg"]`, which is now the panel ground the map sits on. `_paint_ground(painter, c, w, h)` loses its `host` and `card` parameters.

- [ ] **Step 1: Claim the board card**

```bash
python3 board/board.py add --col Ready --title "Map: paint on the panel's ground — no card, vignette or border" --files "klausmate/pdf_map.py,tests/test_pdf_map.py" --priority P1 --tags "ui,phase-d,vibe" --verify "python3 tests/test_pdf_map.py" --body "Task 1 of docs/superpowers/plans/2026-09-01-constellation-and-panel-integration.md. The canvas paints its OWN always-dark palette inside a rounded 12px card with a radial vignette and a grey_light border — that card is what makes it read as a widget dropped onto the panel. It paints flat on the HOST palette's chrome token now, no card, no clip, no lift; the always-dark special case (K-174) is retired because the panel it lives on is the ground."
python3 board/board.py claim K-1XX --owner <you>   # K-1XX = the id `add` printed
python3 board/board.py check-disjoint
```

- [ ] **Step 2: Write the failing pins** (append to `tests/test_pdf_map.py` before its final `print(f"\n{PASS} passed…")`)

```python
print("== Task 1: the map paints on the panel's ground ==")
for _night in (True, False):
    _host = theme.palette(_night)
    _cv = pdf_map.map_canvas(None, FAKE)
    _img = _grab(_cv, night=_night)
    _ground = G.QColor(_host["chrome"])
    _corner = G.QColor(_img.pixel(1, 1))
    _centre_edge = G.QColor(_img.pixel(3, _img.height() // 2))
    check(f"night={_night}: the canvas corner IS the host chrome token — no rounded "
          "card, no border pixel, no clip: the map sits on the panel",
          (abs(_corner.red() - _ground.red()) <= 2
           and abs(_corner.green() - _ground.green()) <= 2
           and abs(_corner.blue() - _ground.blue()) <= 2),
          f"corner={_corner.name()} chrome={_ground.name()}")
    check(f"night={_night}: the ground is FLAT — an edge-middle pixel equals the "
          "corner, so the radial vignette lift is gone",
          _corner.rgb() == _centre_edge.rgb(),
          f"corner={_corner.name()} edge={_centre_edge.name()}")
    _cv.close()
check("VIGNETTE_LIFT and VIGNETTE_SPREAD are gone by name — the lift was the "
      "'general glow' under the whole field",
      not hasattr(pdf_map, "VIGNETTE_LIFT") and not hasattr(pdf_map, "VIGNETTE_SPREAD"))
check("the canvas no longer forces the dark palette: _paint reads the HOST palette "
      "(the always-dark special case of K-174 is retired)",
      "theme.palette(True)" not in _func_seg("_paint"),
      "found a hard-coded palette(True)")
```

(`_func_seg(name)` already exists in this file — it returns a method's source segment; it is used at line ~1259.)

- [ ] **Step 3: Run to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_map.py 2>&1 | grep -E "^ FAIL|^[0-9]+ passed"`
Expected: at least 4 FAIL lines naming Task 1 pins (corner is the dark `bg`, not chrome; `VIGNETTE_LIFT` present; `palette(True)` present).

- [ ] **Step 4: Implement — host palette, flat ground**

In `_paint()`, replace the two palette lines:

```python
            # The map is drawn ON the panel it lives in: its colour maths
            # (star_colour, links, nodes) all blend outward from c["bg"], so
            # pointing c["bg"] at the host's chrome token makes every layer
            # composite over the real ground in BOTH palettes. The
            # always-dark palette(True) of K-174 made the map a dark card on
            # a light panel — the exact "separate box" Pouya asked to lose.
            host = theme.palette(theme.night_mode())
            c = dict(host, bg=host["chrome"])
```

Delete the `host = theme.palette(theme.night_mode())` line that followed and the `card = QRectF(0.5, 0.5, w - 1.0, h - 1.0)` line; change the call to `self._paint_ground(painter, c, w, h)`.

Replace `_paint_ground` entirely:

```python
        def _paint_ground(self, painter, c, w, h) -> None:
            """Flat. The panel's own ground, edge to edge — no card, no
            border, no vignette. The field recedes by depth (size and
            brightness), not by a lift under it."""
            painter.fillRect(QRectF(0.0, 0.0, float(w), float(h)), QColor(c["bg"]))
```

Delete the `VIGNETTE_LIFT = 0.05` and `VIGNETTE_SPREAD = …` constants and their comment block. Grep for any other reader: `grep -n "VIGNETTE\|setClipPath" klausmate/pdf_map.py` — remove the clip (there is no card to clip to) and any `QRadialGradient` import that becomes unused only if `_paint_nodes` no longer uses it after Task 2 (leave it until then).

- [ ] **Step 5: Run to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_map.py 2>&1 | grep -E "^ FAIL|^[0-9]+ passed"`
Expected: `N passed, 0 failed`. If an OLD pin now fails because it read the dark ground (grep its title for "card", "rounded", "ground" — e.g. any pin asserting a `grey_light` border), invert it in place with a comment naming this task; do not delete it.

- [ ] **Step 6: Mutate once, watch red, restore**

```bash
cp klausmate/pdf_map.py /tmp/t1.bak
python3 - <<'EOF'
p="klausmate/pdf_map.py"; s=open(p).read()
s2=s.replace('c = dict(host, bg=host["chrome"])','c = dict(host, bg=host["bg"])',1); assert s2!=s; open(p,"w").write(s2)
EOF
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_map.py 2>&1 | grep -E "^[0-9]+ passed"   # expect ≥2 failed (corner is bg, not chrome)
cp /tmp/t1.bak klausmate/pdf_map.py
```

- [ ] **Step 7: Frame time and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3.14 - <<'EOF'
import os, sys, time, types, importlib, random
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install; install()
from PyQt6 import QtCore as C, QtGui as G, QtWidgets as W
shim = types.ModuleType("aqt.qt")
def _get(name, mods=(W, C, G)):
    for m in mods:
        if hasattr(m, name): return getattr(m, name)
    if name == "qconnect": return lambda s, f: s.connect(f)
    raise AttributeError(name)
shim.__getattr__ = _get; sys.modules["aqt.qt"] = shim
pdf_map = importlib.import_module("klausmate.pdf_map")
rng = random.Random(7); notes, edges, pdfs = [], [], []; nid = 0
for k, (cx, cy, cz) in enumerate(((-.45,-.2,.3), (-.38,-.14,.22), (.4,.3,-.25), (.1,-.5,.1))):
    for _ in range(700):
        nid += 1; notes.append({"nid": nid, "xyz": [cx+rng.gauss(0,.16), cy+rng.gauss(0,.16), cz+rng.gauss(0,.16)]})
        if rng.random() < .5: edges.append({"pdf": f"lec{k}", "nid": nid, "score": .8})
    pdfs.append({"safe": f"lec{k}", "display": f"Lecture {k}", "folder": None, "threshold": .4, "retention": .7, "xyz": [cx,cy,cz], "match_count": 350})
app = W.QApplication([]); cv = pdf_map.map_canvas(None, {"pdfs": pdfs, "notes": notes, "edges": edges})
cv.resize(1100, 660); cv.show(); cv._reduce_motion = lambda: True
for _ in range(3): app.processEvents()
ts = []
for _ in range(40):
    t = time.perf_counter(); cv.grab(); ts.append((time.perf_counter() - t) * 1000)
ts.sort(); print(f"median {ts[20]:.2f} ms  max {ts[-1]:.2f} ms  (floor 4.0; K-174 baseline 1.38-1.95)")
EOF
git add klausmate/pdf_map.py tests/test_pdf_map.py
git commit -m "Map paints flat on the panel's ground: no card, vignette or border (K-1XX)

The canvas painted its own always-dark palette inside a rounded card with
a radial lift and a grey_light border, which is exactly what made it read
as a widget dropped onto the Library. It now blends every layer outward
from the HOST palette's chrome token — the ground the panel wears — in
both palettes, and the K-174 'light palette stays dark' special case is
retired with it. Corner pixel == chrome, edge == corner (no lift), pinned
in both palettes; mutation to bg goes red.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
python3 board/board.py move K-1XX Review
```

---

### Task 2: The general glow — the lit node's halo — is gone; ring and core stay

**Files:**
- Modify: `klausmate/pdf_map.py` — `_paint_nodes()` (~2740–2830: the `QRadialGradient` halo block), constant `NODE_HALO_F` (592)
- Test: `tests/test_pdf_map.py`

**Interfaces:**
- Consumes: `c["blue_bright"]`, `c["text"]`, `node_radius(match_count) -> float`, `NODE_RING_W`, `NODE_CORE_F`, `GHOST_ALPHA`, `GHOST_HALO_F` (all existing).
- Produces: the lit node is exactly two shapes — a ring of width `NODE_RING_W` at radius `r` and a filled core of radius `r * NODE_CORE_F` — and nothing is painted between `r` and `r * 3.4` any more. Task 4 scales the ghost alpha; it relies on this task having removed the halo.

- [ ] **Step 1: Claim the board card** (as Task 1, title "Map: the lit PDF node loses its halo; ring and core stay", same files, verify `python3 tests/test_pdf_map.py`).

- [ ] **Step 2: Write the failing pins**

```python
print("== Task 2: no halo on the lit node ==")
_cv = pdf_map.map_canvas(None, FAKE)
_img = _grab(_cv)
_cv.select("lec0"); [app.processEvents() for _ in range(3)]; _img = _cv.grab().toImage()
_vp, _cam = _cv._vp, _cv._cam
_sx, _sy, _ = pdf_map.project_point(_vp, _cam, *_cv._pdf_xyz["lec0"])
_r = pdf_map.node_radius(FAKE["pdfs"][0]["match_count"])
_ground = _luma(_img, 2, 2)
# Sample an annulus well outside the ring (1.6r .. 3.0r) on 16 spokes: with a
# halo there, most samples are lifted off the ground; without it, almost none.
_lifted = 0; _samples = 0
for _k in range(16):
    _a = 2 * math.pi * _k / 16
    for _rr in (1.6 * _r, 2.2 * _r, 3.0 * _r):
        _x, _y = _sx + _rr * math.cos(_a), _sy + _rr * math.sin(_a)
        if 0 <= _x < _img.width() and 0 <= _y < _img.height():
            _samples += 1
            if abs(_luma(_img, _x, _y) - _ground) > 6: _lifted += 1
check("the lit node has NO halo: the annulus between 1.6r and 3.0r is ground "
      "(stars and links may cross it, so 'almost none', not none)",
      _samples >= 30 and _lifted / _samples < 0.12, f"{_lifted}/{_samples} lifted")
check("...but the ring is still there: pixels ON the radius differ from ground",
      abs(_luma(_img, _sx + _r, _sy) - _ground) > 20 or abs(_luma(_img, _sx, _sy + _r) - _ground) > 20)
check("...and the core is still lit: the centre pixel is bright",
      _luma(_img, _sx, _sy) > _ground + 60, f"centre={_luma(_img, _sx, _sy):.0f} ground={_ground:.0f}")
check("NODE_HALO_F is gone by name", not hasattr(pdf_map, "NODE_HALO_F"))
_cv.close()
```

- [ ] **Step 3: Run to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pdf_map.py 2>&1 | grep -E "^ FAIL|^[0-9]+ passed"`
Expected: FAIL on "NO halo" (the gradient lifts most annulus samples) and on `NODE_HALO_F`.

- [ ] **Step 4: Implement — delete the halo block**

In `_paint_nodes`, delete from `halo_r = r * NODE_HALO_F` through `painter.drawEllipse(pt, halo_r, halo_r)` (the `QRadialGradient` block, ~lines 59–70 of the method). Keep the ring (`painter.setPen(QPen(QColor(c["blue_bright"]), NODE_RING_W)); painter.drawEllipse(pt, r, r)`) and the core. Delete `NODE_HALO_F = 3.4` and its comment. If `QRadialGradient` is now unused in the file (`grep -c QRadialGradient klausmate/pdf_map.py` → only the import), remove it from the `from aqt.qt import (…)` block inside `_canvas_class()`.

Update the `_paint_nodes` docstring's first line from "PDF nodes as light sources: halo, ring, lit core" to "PDF nodes: ring and lit core — crisp, no halo (Pouya: 'I don't like the general glow')".

- [ ] **Step 5: Run to verify they pass** — same command; expect `0 failed`. If the existing pin at ~line 2358 ("an UNFOCUSED PDF is a ghost, not a second lit node") or any pin mentioning "halo" fails, read it: ghost rings still draw at `GHOST_ALPHA`, so it should pass; if it asserted halo pixels, invert it with a comment.

- [ ] **Step 6: Mutate once** — reinsert a single `painter.drawEllipse(pt, r * 2.4, r * 2.4)` with a 0.3-alpha brush before the ring, run, expect "NO halo" red, restore.

- [ ] **Step 7: Commit** — `git add klausmate/pdf_map.py tests/test_pdf_map.py && git commit -m "Map: the lit PDF node loses its halo; ring and core stay (K-1XX)…"` with the pin numbers; `board.py move K-1XX Review`.

---

### Task 3: The chosen PDF's name lights up — bare text, no plate, name only

**Files:**
- Modify: `klausmate/pdf_map.py` — `_paint_label()` (~2828–2895), `node_lines()` (1738), constants `LABEL_PLATE_ALPHA` (324), `LABEL_PAD_X` (322), `LABEL_PAD_Y` (323)
- Test: `tests/test_pdf_map.py` (inverts the pin at ~384 "the focused node's plate carries display, folder, matched NOTE count, retention" and ~2187 "the call order says so too: nodes, then the plate")

**Interfaces:**
- Consumes: `active_pdf(hover, selected)`, `label_anchor(...)`, `clamp_label(...)` (existing, unchanged), `self._selected`.
- Produces: `node_lines(pdf) -> list[str]` returns exactly `[display]`. `_paint_label` draws that one line with **no** background shape; ink is `c["text"]` when `active == self._selected`, `c["text_muted"]` when the label is a hover preview. Task 4 reads `self._selected` to exempt this text from dimming.

- [ ] **Step 1: Claim the board card** ("Map: the chosen PDF's name lights up — bare, no plate, name only").

- [ ] **Step 2: Write the failing pins**

```python
print("== Task 3: the name, bare, lit for the chosen PDF ==")
check("node_lines is the NAME and nothing else — no folder, matched or retention lines",
      pdf_map.node_lines(FAKE["pdfs"][0]) == [FAKE["pdfs"][0]["display"]],
      repr(pdf_map.node_lines(FAKE["pdfs"][0])))
_seg = _func_seg("_paint_label")
check("_paint_label draws NO plate: no rounded rect, no brush fill, no LABEL_PLATE_ALPHA",
      "drawRoundedRect" not in _seg and "setBrush" not in _seg and "LABEL_PLATE_ALPHA" not in _seg)
check("the plate constants are gone by name",
      not any(hasattr(pdf_map, n) for n in ("LABEL_PLATE_ALPHA", "LABEL_PAD_X", "LABEL_PAD_Y")))
_cv = pdf_map.map_canvas(None, FAKE); _grab(_cv)
_cv.select("lec0"); [app.processEvents() for _ in range(3)]; _img = _cv.grab().toImage()
_c = dict(theme.palette(True), bg=theme.palette(True)["chrome"])
_sx, _sy, _ = pdf_map.project_point(_cv._vp, _cv._cam, *_cv._pdf_xyz["lec0"])
_r = pdf_map.node_radius(FAKE["pdfs"][0]["match_count"])
_fm = G.QFontMetricsF(_cv.font()); _tw = _fm.horizontalAdvance(FAKE["pdfs"][0]["display"])
_lx, _ly = pdf_map.label_anchor(_sx, _sy, _r, _tw, _img.width())
# The label box: from the anchor, one line high. Count text-ink pixels vs the SAME
# box grabbed with nothing selected (so stars under it cancel out).
_cv.select(""); [app.processEvents() for _ in range(3)]; _blank = _cv.grab().toImage()
_ink = sum(1 for y in range(int(_ly - 11), int(_ly + 4)) for x in range(int(_lx), int(_lx + _tw))
           if _img.pixel(x, y) != _blank.pixel(x, y))
check("selecting a PDF paints its NAME: the label box differs from the unselected frame",
      _ink > 40, f"{_ink} changed px")
_text = G.QColor(_c["text"]); _hit = 0
for y in range(int(_ly - 11), int(_ly + 4)):
    for x in range(int(_lx), int(_lx + _tw)):
        _p = G.QColor(_img.pixel(x, y))
        if abs(_p.red() - _text.red()) <= 3 and abs(_p.green() - _text.green()) <= 3: _hit += 1
check("...in the FULL text ink — the chosen name lights up, it is not the muted preview colour",
      _hit > 20, f"{_hit} px in c['text']")
_cv.close()
```

- [ ] **Step 3: Run to verify they fail** — expect FAIL on `node_lines` (returns 3–4 lines), on the plate-source pin, on the constants.

- [ ] **Step 4: Implement**

`node_lines`:

```python
def node_lines(pdf: dict) -> list:
    """What the canvas writes beside the focused node: the NAME, alone.
    Folder, matched count and retention left with the plate (Pouya:
    'remove the little box around it'); they live in the Library tree."""
    return [str(pdf.get("display") or pdf.get("safe") or "")]
```

`_paint_label` body: keep the anchor/clamp lines; delete the plate (`plate = QColor(c["bg"]) … painter.drawRoundedRect(...)`); draw:

```python
                lit_name = active is not None and active == self._selected
                painter.setPen(QColor(c["text"] if lit_name else c["text_muted"]))
                painter.drawText(QPointF(lx, ly), lines[0])
```

Delete the loop over `lines[1:]`. Delete `LABEL_PLATE_ALPHA`, `LABEL_PAD_X`, `LABEL_PAD_Y` and their comments; `clamp_label`'s `LABEL_EDGE_PAD` stays. Update the `_paint_label` docstring: "Exactly ONE name, the focused node's, drawn bare: bright when chosen, muted while only hovered."

- [ ] **Step 5: Run to verify they pass.** Invert the old pins at ~384 (now: "the focused node's label is the name alone") and ~2187 ("nodes, then the name"), and any `clamp_label`/`label_anchor` pin that measured a plate width with padding — they measured text width plus `2*LABEL_PAD_X`; drop the padding term.

- [ ] **Step 6: Mutate once** — make `lit_name` always False (`lit_name = False`), run: the "FULL text ink" pin must go red. Restore.

- [ ] **Step 7: Frame-time check (global constraint)** — run Task 1's Step 7 timing block VERBATIM (same inline fixture, `python3.14`, 1100×660, 40 grabs; copy it from Task 1 — it is the one measurement every map task shares so medians stay comparable). The median must stay under 4.0 ms; if it rises above 2.5 ms say so with the number. Record the median and max in the board comment and the report.

- [ ] **Step 8: Commit** and move the card to Review.

---

### Task 4: Dim by default; the pointer lights the whole field to normal; the chosen PDF is exempt

**Files:**
- Modify: `klausmate/pdf_map.py` — `star_colour()` (1452), `_ensure_pens()` (2452), `_paint_constellation()`, `_paint_nodes()`, `_paint_label()`, the canvas `__init__` (~1933–2090), `leaveEvent` (~2983), new `enterEvent`, new `lit` property
- Test: `tests/test_pdf_map.py`

**Interfaces:**
- Consumes: `QPropertyAnimation`, `pyqtProperty`, `QEasingCurve` (already imported inside `_canvas_class()` for `fly`), `self._reduce_motion()`.
- Produces:
  - constants `DIM_LIT = 0.45`, `LIT_MS = 180`
  - `star_colour(c, pos, dim=False, lit=1.0) -> str` — `lit` in [0, 1] blends the result toward `c["bg"]`: `keep = STAR_DIM_KEEP + (1.0 - STAR_DIM_KEEP) * lit`, applied AFTER the existing `dim` blend.
  - canvas: `self._lit: float` (starts at `DIM_LIT`), `lit = pyqtProperty(float, _get_lit, _set_lit)`, `self._lit_anim: QPropertyAnimation`, `set_lit_target(value: float) -> None` (animates, or snaps under reduce-motion), `enterEvent` → `set_lit_target(1.0)`, `leaveEvent` → `set_lit_target(DIM_LIT)`.
  - Exempt from `lit`: the selected PDF's ring/core and its name (Task 3's `lit_name` branch).

- [ ] **Step 1: Claim the board card** ("Map: dim by default, lit under the pointer, the chosen PDF exempt").

- [ ] **Step 2: Write the failing pins**

```python
print("== Task 4: dim at rest, lit under the pointer ==")
_c = dict(theme.palette(True), bg=theme.palette(True)["chrome"])
check("star_colour takes a lit factor and 1.0 is the old colour",
      pdf_map.star_colour(_c, 0.8, False, 1.0) == pdf_map.star_colour(_c, 0.8, False))
_dimmed = G.QColor(pdf_map.star_colour(_c, 0.8, False, pdf_map.DIM_LIT))
_full = G.QColor(pdf_map.star_colour(_c, 0.8, False, 1.0)); _g = G.QColor(_c["bg"])
check("...and DIM_LIT pulls a star toward the ground without reaching it",
      _g.lightness() < _dimmed.lightness() < _full.lightness(),
      f"ground={_g.lightness()} dim={_dimmed.lightness()} full={_full.lightness()}")
_cv = pdf_map.map_canvas(None, FAKE); _rest = _grab(_cv)
_w, _h = _rest.width(), _rest.height()
_rest_l = _mean_luma(_rest, _w * 0.2, _h * 0.2, _w * 0.8, _h * 0.8)
check("the canvas RESTS dim: lit == DIM_LIT before any pointer", _cv.lit == pdf_map.DIM_LIT)
# Enter: reduce-motion is on in _grab, so the ramp snaps and one paint suffices.
_cv.setAttribute(C.Qt.WidgetAttribute.WA_UnderMouse, True)
W.QApplication.sendEvent(_cv, G.QEnterEvent(C.QPointF(5, 5), C.QPointF(5, 5), C.QPointF(5, 5)))
for _ in range(3): app.processEvents()
_lit_img = _cv.grab().toImage(); _lit_l = _mean_luma(_lit_img, _w * 0.2, _h * 0.2, _w * 0.8, _h * 0.8)
check("the pointer entering lights the field: lit == 1.0 and the mean luminance rises",
      _cv.lit == 1.0 and _lit_l > _rest_l * 1.15, f"rest={_rest_l:.1f} lit={_lit_l:.1f}")
W.QApplication.sendEvent(_cv, C.QEvent(C.QEvent.Type.Leave))
for _ in range(3): app.processEvents()
_back = _mean_luma(_cv.grab().toImage(), _w * 0.2, _h * 0.2, _w * 0.8, _h * 0.8)
check("...and leaving dims it again", _cv.lit == pdf_map.DIM_LIT and abs(_back - _rest_l) < 1.0,
      f"rest={_rest_l:.1f} back={_back:.1f}")
# The chosen PDF is exempt: its core is as bright dim as lit.
_cv.select("lec0"); [app.processEvents() for _ in range(3)]
_sx, _sy, _ = pdf_map.project_point(_cv._vp, _cv._cam, *_cv._pdf_xyz["lec0"])
_core_dim = _luma(_cv.grab().toImage(), _sx, _sy)
W.QApplication.sendEvent(_cv, G.QEnterEvent(C.QPointF(5, 5), C.QPointF(5, 5), C.QPointF(5, 5)))
for _ in range(3): app.processEvents()
_core_lit = _luma(_cv.grab().toImage(), _sx, _sy)
check("the CHOSEN PDF is exempt from dimming: its core is equally bright dim or lit",
      abs(_core_dim - _core_lit) < 3, f"dim={_core_dim:.0f} lit={_core_lit:.0f}")
check("the ramp is a property animation of LIT_MS with an easing curve, like fly",
      isinstance(getattr(_cv, "_lit_anim", None), C.QPropertyAnimation)
      and _cv._lit_anim.duration() == pdf_map.LIT_MS)
_cv.close()
```

- [ ] **Step 3: Run to verify they fail** — `star_colour` has no `lit` parameter → TypeError is caught by `check`? No: an unexpected keyword raises at module level. Wrap the first two checks in `try/except TypeError` recording `check(..., False, "no lit parameter")` so the run RECORDS rather than aborts (the file's rule). Expect ≥5 FAIL.

- [ ] **Step 4: Implement**

Constants (beside `GHOST_ALPHA`):

```python
# Pouya, 2026-09-01: "I want it to be dim, but then, as I put the mouse
# over it, it lights up to normal values." The canvas rests at DIM_LIT and
# ramps to 1.0 under the pointer; LIT_MS is the ramp, eased like fly. The
# chosen PDF and its name are exempt — "just for that one, to light up".
DIM_LIT = 0.45
LIT_MS = 180
```

`star_colour`:

```python
def star_colour(c: dict, pos: float, dim: bool = False, lit: float = 1.0) -> str:
    ...  # existing body up to the `dim` blend, then:
    keep = STAR_DIM_KEEP + (1.0 - STAR_DIM_KEEP) * _clamp(float(lit), 0.0, 1.0)
    if keep < 1.0:
        out = blend_hex(ground, out, keep)
    return out
```

`_ensure_pens(self, c, scale=1.0)`: quantise `q = round(self._lit * 16) / 16.0`, add `q` to `key`, pass `lit=q` to every `star_colour` call inside.

`_paint_constellation`: `ink = QColor(blend_hex(c["bg"], star_colour(c, 1.0, lit=self._lit), LINK_MIX))`.

`_paint_nodes`: for a ghost, `ring.setAlphaF(GHOST_ALPHA * self._lit)` and `dot.setAlphaF(min(1.0, GHOST_ALPHA * 1.8 * self._lit))`; for the lit node (`safe == active`): if `safe == self._selected` paint at full, else multiply the ring/core alpha by `self._lit`.

`_paint_label`: `lit_name` text is full ink; the muted preview ink gets `setAlphaF(self._lit)`.

Canvas `__init__` (beside `_fly_anim`):

```python
            self._lit = DIM_LIT
            self._lit_anim = QPropertyAnimation(self, b"lit", self)
            self._lit_anim.setDuration(LIT_MS)
            self._lit_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
```

Property and events (beside `fly`):

```python
        def _get_lit(self) -> float:
            return float(self._lit)

        def _set_lit(self, value: float) -> None:
            v = _clamp(float(value), 0.0, 1.0)
            if v != self._lit:
                self._lit = v
                self.update()

        lit = pyqtProperty(float, _get_lit, _set_lit)

        def set_lit_target(self, value: float) -> None:
            """Ramp the whole field to ``value`` — snap under reduce-motion."""
            try:
                self._lit_anim.stop()
                if self._reduce_motion() or not self.isVisible():
                    self._set_lit(value)
                    return
                self._lit_anim.setStartValue(self._lit)
                self._lit_anim.setEndValue(float(value))
                self._lit_anim.start()
            except Exception as exc:
                print(f"[klausmate] map lit ramp failed: {exc}")
                self._set_lit(value)

        def enterEvent(self, event) -> None:  # noqa: N802
            try:
                self.set_lit_target(1.0)
            except Exception:
                pass
            try:
                super().enterEvent(event)
            except Exception:
                pass
```

In the existing `leaveEvent`, add `self.set_lit_target(DIM_LIT)` inside its first `try`.

- [ ] **Step 5: Run to verify they pass.** The existing pin at ~1885 ("the far tier is dimmer AND smaller than the near one") compares tiers at the same `lit` — unaffected. Any pin that pixel-reads star brightness at rest against a fixed threshold now sees DIM_LIT; re-baseline it by sending the Enter event first, with a comment naming this task.

- [ ] **Step 6: Mutate once** — `DIM_LIT = 1.0`; run: "RESTS dim" and "lights the field" must go red. Restore. Then frame time: median of 40 grabs under `python3.14` while `_lit` is mid-ramp (set `_cv._lit = 0.7` by hand) — pens are rebuilt at most 17 times per ramp; report the number.

- [ ] **Step 7: Frame-time check (global constraint)** — run Task 1's Step 7 timing block VERBATIM (same inline fixture, `python3.14`, 1100×660, 40 grabs; copy it from Task 1 — it is the one measurement every map task shares so medians stay comparable). The median must stay under 4.0 ms; if it rises above 2.5 ms say so with the number. Record the median and max in the board comment and the report.

- [ ] **Step 8: Commit** and move the card to Review.

---

### Task 5: Every star is connected — a spanning-tree backbone under the nearest-neighbour links

**Files:**
- Modify: `klausmate/pdf_map.py` — `constellation_links()` (1549), new `spanning_tree()`, constant `LINK_MODE` (538)
- Test: `tests/test_pdf_map.py` (the pin at ~922 "no nearest-neighbour link is longer than the span" is scoped to knn edges)

**Interfaces:**
- Produces: `spanning_tree(points: Sequence[tuple]) -> list[tuple[int, int]]` — Prim's algorithm over Euclidean distance in the points' own space, `i < j` per pair, `n - 1` pairs for `n >= 2`, `[]` otherwise; pure, deterministic. `constellation_links(points, mode="constellation", …)` returns `sorted(set(spanning_tree(points)) | knn_pairs)` where the tree edges are NEVER subject to `cap`; `cap` bounds only the knn extras. `LINK_MODE = "constellation"`.

- [ ] **Step 1: Claim the board card** ("Map: a connected constellation — spanning-tree backbone plus nearest neighbours").

- [ ] **Step 2: Write the failing pins**

```python
print("== Task 5: the constellation is connected ==")
import random as _rnd
_rng = _rnd.Random(5)
# three clusters far apart: kNN alone leaves three islands
_pts = [(cx + _rng.gauss(0, .05), cy + _rng.gauss(0, .05), _rng.gauss(0, .05))
        for cx, cy in ((-.6, -.4), (.5, .3), (.1, -.7)) for _ in range(40)]
def _components(n, pairs):
    parent = list(range(n))
    def f(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for i, j in pairs: parent[f(i)] = f(j)
    return len({f(i) for i in range(n)})
_knn = pdf_map.constellation_links(_pts, "knn")
check("baseline: kNN alone leaves the three clusters as three islands",
      _components(len(_pts), _knn) == 3, f"{_components(len(_pts), _knn)} components")
_tree = pdf_map.spanning_tree(_pts)
check("spanning_tree returns n-1 unique i<j pairs", len(_tree) == len(_pts) - 1
      and len(set(_tree)) == len(_tree) and all(i < j for i, j in _tree))
check("...that connect every point", _components(len(_pts), _tree) == 1)
_all = pdf_map.constellation_links(_pts, "constellation")
check("the constellation mode is ONE component — no star is an island (the "
      "'satisfying interconnection')", _components(len(_pts), _all) == 1)
check("...and contains every backbone edge even under the cap",
      set(_tree) <= set(pdf_map.constellation_links(_pts, "constellation", cap=5)))
check("...and is deterministic", _all == pdf_map.constellation_links(_pts, "constellation"))
check("LINK_MODE defaults to the connected mode", pdf_map.LINK_MODE == "constellation")
```

- [ ] **Step 3: Run to verify they fail** — `spanning_tree` missing → wrap in `try/except AttributeError` recording FAILs; expect ≥4 red.

- [ ] **Step 4: Implement**

```python
def spanning_tree(points: Sequence) -> list:
    """Prim's minimum spanning tree over Euclidean distance — the backbone
    that makes the constellation ONE figure. O(n^2) on the sampled cloud
    (~520 points -> ~270k distances, measured under a millisecond); never
    run this on the full index.
    """
    n = len(points)
    if n < 2:
        return []
    in_tree = [False] * n
    best = [float("inf")] * n
    link = [-1] * n
    best[0] = 0.0
    out = []
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: best[i])
        in_tree[u] = True
        if link[u] >= 0:
            out.append((link[u], u) if link[u] < u else (u, link[u]))
        ux, uy, uz = points[u][0], points[u][1], points[u][2]
        for v in range(n):
            if in_tree[v]:
                continue
            d = (points[v][0] - ux) ** 2 + (points[v][1] - uy) ** 2 + (points[v][2] - uz) ** 2
            if d < best[v]:
                best[v] = d
                link[v] = u
    return sorted(out)
```

In `constellation_links`, add before the mode branches:

```python
    backbone: set = set()
    if mode == "constellation":
        backbone = set(spanning_tree(points))
        mode = "knn"
```

and after the cap/shuffle: `return sorted(backbone | set(out))` (the tree never counted against `limit`). Set `LINK_MODE = "constellation"` and add to its comment: `"constellation" = spanning-tree backbone (connected by construction) plus the kNN density; "knn" and "chord" remain reachable for comparison.`

- [ ] **Step 5: Run to verify they pass.** Scope the existing span pin at ~922 to knn pairs: `set(knn_only) - backbone` — backbone edges may legitimately exceed `LINK_MAX_SPAN` (they bridge gaps).

- [ ] **Step 6: Mutate once** — make `spanning_tree` return `out[:-1]` (drop one edge): "ONE component" and "n-1 pairs" go red. Restore. Frame time: the link count grows by ~n−1; re-measure `_paint_constellation` — one batched `drawLines`, expect <0.3 ms.

- [ ] **Step 7: Frame-time check (global constraint)** — run Task 1's Step 7 timing block VERBATIM (same inline fixture, `python3.14`, 1100×660, 40 grabs; copy it from Task 1 — it is the one measurement every map task shares so medians stay comparable). The median must stay under 4.0 ms; if it rises above 2.5 ms say so with the number. Record the median and max in the board comment and the report.

- [ ] **Step 8: Commit** and move the card to Review.

---

### Task 6: A slight sway, not a turn — with a stronger perspective so the depth is unmistakable

**Files:**
- Modify: `klausmate/pdf_map.py` — `_idle_tick()` (~2197), `sweep_bounds()` (1135), constants `ROTATE_PERIOD_MS` (380), `CAM_DISTANCE` (358), `SWEEP_STEPS` (390); new `sway_angle()`
- Test: `tests/test_pdf_map.py` (inverts ~953 "the 0.42 rad sway is gone and the scene TURNS — a full …" and ~966 "a rotating canvas frames the SWEPT box: at every pose of a full …")

**Interfaces:**
- Produces: `SWAY_AMP = 0.28` (radians, ±16°), `SWAY_PERIOD_MS = 14000.0`, `CAM_DISTANCE = 2.0`; `sway_angle(t_ms: float, rest: float = REST_ANGLE, amp: float = SWAY_AMP, period_ms: float = SWAY_PERIOD_MS) -> float` = `rest + amp * sin(2π t / period)`; `sweep_bounds(box, cam, steps=SWEEP_STEPS, amplitude=SWAY_AMP)` enumerates poses `cam.angle + amplitude * sin(2π i / steps)`; the canvas keeps `self._phase` as elapsed ms and sets `self._cam = Camera(sway_angle(self._phase), self._cam.distance)`.

- [ ] **Step 1: Claim the board card** ("Map: a slight 3D sway with a stronger perspective replaces the 72 s turn").

- [ ] **Step 2: Write the failing pins**

```python
print("== Task 6: sway, and visible depth ==")
_angles = [pdf_map.sway_angle(t) for t in range(0, int(pdf_map.SWAY_PERIOD_MS) + 1, 100)]
check("the sway stays within ±SWAY_AMP of REST_ANGLE over a whole period and comes back",
      all(abs(a - pdf_map.REST_ANGLE) <= pdf_map.SWAY_AMP + 1e-9 for a in _angles)
      and abs(_angles[-1] - _angles[0]) < 1e-6)
check("...and it is SLIGHT: SWAY_AMP is under a fifth of a turn", 0.1 < pdf_map.SWAY_AMP < 0.4)
check("the full-turn period is gone by name", not hasattr(pdf_map, "ROTATE_PERIOD_MS"))
check("the perspective is stronger: CAM_DISTANCE dropped from 2.6", pdf_map.CAM_DISTANCE <= 2.0)
# 3D-ness: two points at the SAME screen x at rest, one near and one far, move by
# DIFFERENT screen dx at the sway's extreme — that difference is the parallax.
_vp = pdf_map.fit_to_view((-1, -1, -1, 1, 1, 1), (900, 560))
_rest = pdf_map.Camera(pdf_map.REST_ANGLE, pdf_map.CAM_DISTANCE)
_peak = pdf_map.Camera(pdf_map.REST_ANGLE + pdf_map.SWAY_AMP, pdf_map.CAM_DISTANCE)
_near = pdf_map.project_point(_vp, _rest, 0.3, 0.0, 0.8)[0]; _far = pdf_map.project_point(_vp, _rest, 0.3, 0.0, -0.8)[0]
_near2 = pdf_map.project_point(_vp, _peak, 0.3, 0.0, 0.8)[0]; _far2 = pdf_map.project_point(_vp, _peak, 0.3, 0.0, -0.8)[0]
check("parallax is visible: a near and a far point drift apart by more than 12 px "
      "across the sway", abs((_near2 - _near) - (_far2 - _far)) > 12,
      f"near dx={_near2 - _near:.1f} far dx={_far2 - _far:.1f}")
_box = (-1, -1, -1, 1, 1, 1)
_sw = pdf_map.sweep_bounds(_box, _rest, 24)
_full = pdf_map.sweep_bounds(_box, _rest, 24, amplitude=math.pi)
check("sweep_bounds frames the sway's ARC, which is tighter than a full turn's box",
      (_sw[2] - _sw[0]) < (_full[2] - _full[0]))
```

- [ ] **Step 3: Run to verify they fail** — `sway_angle` missing (guard with try/except → FAIL), `ROTATE_PERIOD_MS` present, `CAM_DISTANCE == 2.6`.

- [ ] **Step 4: Implement**

Constants (replace `ROTATE_PERIOD_MS`'s block):

```python
# Pouya, 2026-09-01: "a slight rotation in 3D so that 3D-ness is very
# apparent." K-174's full turn at 72 s moved 5 degrees a second — never
# enough parallax in any one glance, and the far half flipped through the
# near half every quarter turn. A sinusoidal SWAY of ±SWAY_AMP around the
# rest angle keeps a visible drift going at all times and never flips.
SWAY_AMP = 0.28            # radians, ±16°
SWAY_PERIOD_MS = 14000.0   # one there-and-back
CAM_DISTANCE = 2.0         # was 2.6: nearer eye = stronger perspective = deeper
```

Pure function (beside `camera_point`):

```python
def sway_angle(t_ms: float, rest: float = REST_ANGLE, amp: float = SWAY_AMP,
               period_ms: float = SWAY_PERIOD_MS) -> float:
    """The camera yaw at time ``t_ms`` into the sway."""
    return rest + amp * math.sin(2.0 * math.pi * float(t_ms) / max(1.0, float(period_ms)))
```

`_idle_tick`: replace the phase arithmetic with

```python
                self._phase = (self._phase + IDLE_TICK_MS) % SWAY_PERIOD_MS
                self._cam = Camera(sway_angle(self._phase), self._cam.distance)
                self.update()
```

(`self._phase` was radians; it is milliseconds now — check `__init__` initialises it to `0.0` and nothing else reads it as an angle: `grep -n "_phase" klausmate/pdf_map.py`.)

`sweep_bounds(box, cam, steps=SWEEP_STEPS, amplitude=SWAY_AMP)`: the pose line becomes `pose = Camera(cam.angle + amplitude * math.sin(2.0 * math.pi * i / n), cam.distance)`; the docstring's "a full turn" becomes "the sway's arc"; the `pad` stays (the arc is still a sinusoid in the sample index).

- [ ] **Step 5: Run to verify they pass.** Invert ~953 to "the full turn is gone and the scene SWAYS ±SWAY_AMP" and ~966 to "…at every pose of the sway"; a pin asserting `band_order` flips on `cos(angle)` sign still holds (the sway never crosses ±90°, so it never flips — pin that too: `all(math.cos(a) > 0 for a in _angles)`).

- [ ] **Step 6: Mutate once** — `SWAY_AMP = 0.0`: the parallax pin and the "comes back" pin (trivially true) — parallax goes red. Restore. Render three frames at `t = 0, P/4, P/2` and LOOK at them: the near cluster must visibly slide relative to the far one.

- [ ] **Step 7: Frame-time check (global constraint)** — run Task 1's Step 7 timing block VERBATIM (same inline fixture, `python3.14`, 1100×660, 40 grabs; copy it from Task 1 — it is the one measurement every map task shares so medians stay comparable). The median must stay under 4.0 ms; if it rises above 2.5 ms say so with the number. Record the median and max in the board comment and the report.

- [ ] **Step 8: Commit** and move the card to Review.

---

## Phase B — the panel (`theme.py`, `library_explorer.py`, `pdf_viewer.py`, their tests)

### Task 7: The Library's panels wear the top bar's colour

**Files:**
- Modify: `klausmate/theme.py` — `library_qss()` (`QWidget#KlausLibraryWindow { background-color: {c['bg']} }` and the `QTreeWidget` rule, ~lines 48–61 of the function)
- Modify: `klausmate/library_explorer.py:62` — `BAND_BASE = "bg"` → `"chrome"`
- Test: `tests/test_theme.py`, `tests/test_library_explorer.py` (inverts ~299 "the depth-2 row's ground is the tree's bg (the sidebar token, not …" and retitles the band pins that say "(bg)")

**Interfaces:**
- Consumes: `theme.palette(night)["chrome"]` — the top bar's token (`toolbar_css` pushes it as `--klaus-chrome`; night `#232323`, day `#FFFFFF`).
- Produces: `library_qss(night)` paints `#KlausLibraryWindow`, its `QTreeWidget` and the header on `chrome`; `library_explorer.BAND_BASE == "chrome"` so `band_colour()` pre-composites the accent over the real ground. Task 1's map ground is the same token, which is what makes the map "part of the panel".

- [ ] **Step 1: Claim the board card** ("Library: the panels wear the top bar's chrome; the band composites over it") — files as listed; `check-disjoint` must show no overlap with the Phase A card.

- [ ] **Step 2: Write the failing pins**

In `tests/test_theme.py`:

```python
print("== Task 7: the Library ground is the top bar's token ==")
for _night in (True, False):
    _c = theme.palette(_night); _qss = theme.library_qss(_night)
    import re as _re
    _win = _re.search(r"QWidget#KlausLibraryWindow\s*\{[^}]*background-color:\s*(#[0-9A-Fa-f]{6})", _qss)
    check(f"night={_night}: #KlausLibraryWindow's ground is the chrome token — the same "
          "colour the top bar wears",
          _win is not None and _win.group(1).upper() == _c["chrome"].upper(),
          f"got {_win.group(1) if _win else None} chrome={_c['chrome']}")
    _tree = _re.search(r"QWidget#KlausLibraryWindow QTreeWidget\s*\{[^}]*background(?:-color)?:\s*(#[0-9A-Fa-f]{6})", _qss)
    check(f"night={_night}: ...and so is the tree's",
          _tree is not None and _tree.group(1).upper() == _c["chrome"].upper())
```

In `tests/test_library_explorer.py`:

```python
check("the selection band pre-composites over CHROME, the tree's real ground now",
      lx.BAND_BASE == "chrome" and
      lx.band_colour(True, False, True) == theme.accent_mix(True, lx.BAND_ALPHA, base="chrome"))
```

- [ ] **Step 3: Run to verify they fail** — `python3 tests/test_theme.py` and `python3 tests/test_library_explorer.py`: expect the three new pins red (grounds are `bg`; `BAND_BASE == "bg"`).

- [ ] **Step 4: Implement** — in `library_qss`, change both `{c['bg']}` grounds to `{c['chrome']}` and update the comment ("bg, not surface (K-175): VS Code's SIDEBAR is the grey ground") to: "chrome, not bg (2026-09-01, Pouya: 'the panels the same colour as the top bar'): the sidebar and the bar are one surface; the PDF pane, on bg, is the step darker." In `library_explorer.py`: `BAND_BASE = "chrome"  # the band is pre-composited over the TREE's ground, which is the top bar's token`.

- [ ] **Step 5: Run to verify they pass.** Invert `tests/test_library_explorer.py` ~299 ("the depth-2 row's ground is the tree's chrome") and retitle the two band pins that say "(bg)" to "(chrome)" — their assertions compare against `band_colour()`, so only the titles change. Run `tests/test_drive.py` too: its K-117/K-135 render pins read the tree ground; re-baseline any that hard-read `bg`.

- [ ] **Step 6: Render and look** — the Library at 1100×640, both palettes (the `_grab` idiom from Task 1's harness works on `pdf_drive.DriveWindow(embedded=True)` mounted in a host widget; see `tests/test_drive.py`'s K-173 block for the exact mount). The tree, the MAP box and the drop zone must be one flat surface; in night mode `#232323`, and the top bar is that same hex.

- [ ] **Step 7: Mutate once** — `BAND_BASE = "bg"`: the band pin goes red. Restore. Commit; move to Review.

---

### Task 8: The PDF pane is a step darker — the documentless viewport paints `bg`

**Files:**
- Modify: `klausmate/pdf_viewer.py` (~807–815, right after `self._pdf_view = QPdfView(self)`)
- Test: `tests/test_drive.py` (its offscreen section already builds a real `PdfSidebar`/`QPdfView` under the native renderer)

**Interfaces:**
- Consumes: `theme.palette(night)["bg"]` (night `#191919`, day `#F5F5F7` — in both palettes one step darker than `chrome`), `theme.night_mode()`.
- Produces: with no document loaded, the centre pixel of the `QPdfView` viewport is within 8/255 of `bg` on every channel. pdf.js already paints `body`/`#pages` with `var(--bg)`, emitted by `theme.css_vars` — no change there, and its pixels cannot be produced headless (say so in the report).

- [ ] **Step 1: Claim the board card** ("Viewer pane: the documentless QPdfView paints bg, a step darker than the panels"). This closes K-178; say so in the body.

- [ ] **Step 2: Write the failing pin** (in `tests/test_drive.py`'s real-offscreen section, after a `PdfSidebar` is built with the native renderer):

```python
print("== Task 8: the empty viewer pane is bg, not Qt's grey ==")
for _night in (True, False):
    theme.night_mode = lambda n=_night: n
    _sb = pdf_viewer.PdfSidebar(None, parent=None)
    _sb.resize(600, 400); _sb.show()
    for _ in range(3): app.processEvents()
    _v = _sb._pdf_view.viewport(); _img = _v.grab().toImage()
    _px = G.QColor(_img.pixel(_img.width() // 2, _img.height() // 2)); _bg = G.QColor(theme.palette(_night)["bg"])
    check(f"night={_night}: with no document the viewport's centre is the bg token, "
          "not QPdfView's raw grey (K-178)",
          max(abs(_px.red() - _bg.red()), abs(_px.green() - _bg.green()), abs(_px.blue() - _bg.blue())) <= 8,
          f"centre={_px.name()} bg={_bg.name()}")
    _sb.cleanup(); _sb.close()
```

- [ ] **Step 3: Run to verify it fails** — `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 tests/test_drive.py 2>&1 | grep -E "Task 8|^ FAIL"`: expect `centre=#a0a0a0`-ish (the grey) for both palettes.

- [ ] **Step 4: Implement** — after `self._pdf_view.setZoomMode(...)`:

```python
            # A documentless QPdfView paints its viewport in the palette's
            # Dark/Base roles — Qt's mid-grey, a slab between two dark panes
            # (K-178). Point every role it might read at the bg token, a
            # step darker than the chrome the panels wear (Pouya: "the middle
            # area for the PDF to be darker"). Roles, not a stylesheet: the
            # view paints the gap between pages itself, from its palette.
            try:
                from . import theme as _theme
                ground = QColor(_theme.palette(_theme.night_mode())["bg"])
                pal = self._pdf_view.palette()
                for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                             QPalette.ColorRole.Dark, QPalette.ColorRole.Mid):
                    pal.setColor(role, ground)
                self._pdf_view.setPalette(pal)
                self._pdf_view.viewport().setPalette(pal)
                self._pdf_view.viewport().setAutoFillBackground(True)
            except Exception as exc:
                print(f"[klausmate] viewer ground failed: {exc}")
```

(`QColor`/`QPalette` come from the `from aqt.qt import (...)` block at the top of `pdf_viewer.py`; add `QPalette` there if absent.)

- [ ] **Step 5: Run to verify it passes.** If the centre pixel is still grey — `QPdfView` may ignore the palette and fill from a private brush — apply Step 4b instead: keep the palette code and add K-178's overlay: a `QLabel(self._pdf_view)` named `KlausViewerEmpty`, `setAttribute(WA_TransparentForMouseEvents)`, geometry synced to the viewport in `resizeEvent`, stylesheet `background: {bg}` (token, via `pdf_panel_qss`, never literal), shown while `not self.is_loaded(...)` and hidden from the existing `_notify_loaded` path; the same pin then passes. Report which of the two landed.

- [ ] **Step 6: Mutate once** — comment out `setAutoFillBackground(True)` (or the overlay's `show()`): the pin goes red. Restore. Render the whole Library (Task 7's mount) in both palettes and look: three surfaces — panels on chrome, viewer on bg, map on chrome — with the viewer visibly the darkest.

- [ ] **Step 7: Commit** (close K-178 on the board with a comment naming this commit) and move the card to Review.

---

### Task 9: Integration renders, the speed number, and the docs delta

**Files:**
- Modify: `CLAUDE.md` — the `pdf_map.py` entry (the sentence "the light palette stays dark" and the K-174 look description), and the `pdf_drive.py`/`theme.py` entries' mention of the tree "on bg"
- Test: none new — this task runs the whole sweep and produces the renders

**Interfaces:** consumes everything above; produces nothing new. It exists because Phases A and B are separate lanes and the user's ask is "it feels integrated" — only a render of the assembled Library can answer that.

- [ ] **Step 1: Claim the board card** ("Constellation + panel: integration renders and docs") with files `CLAUDE.md` only.

- [ ] **Step 2: Full sweep** — `for t in tests/test_*.py; do python3 "$t" | tail -1; done` after purging `__pycache__` and `~/Library/Caches/com.apple.python`; every file `0 failed`.

- [ ] **Step 3: Renders** — one script (the harness above plus `tests/test_drive.py`'s K-173 mount): the embedded Library at 1100×640 and at `QT_SCALE_FACTOR=2`, night and day; the map at rest (dim), with the pointer over it (lit), with a PDF selected (only its name and ring lit), and at sway phases 0 / P/4 / P/2. Look at every one. The acceptance list, from the spec: no card, no plate, no halo; dim at rest, normal under the pointer, one PDF lit; every star connected; visible drift between near and far; panels one flat chrome surface; viewer darker.

- [ ] **Step 4: Speed** — `python3.14`, median of 40 paints at 1100×660, four states (rest/lit/selected/mid-sway). Record the numbers on the card. The floor is 4 ms; the K-174 baseline was 1.38–1.95 ms median.

- [ ] **Step 5: Docs** — in `CLAUDE.md`'s `pdf_map.py` entry replace the K-174 look sentences with: "Since 2026-09-01 the map is a DIM constellation on the panel's own ground: it reads the host palette (no always-dark special case, no card, no vignette), rests at `DIM_LIT` and ramps to 1.0 under the pointer (`lit` property, `LIT_MS`), lights only the selected PDF and its bare name (no plate, no halo), joins every star through a spanning-tree backbone plus nearest neighbours (`constellation_links` mode `"constellation"`), and SWAYS ±`SWAY_AMP` at `CAM_DISTANCE` 2.0 instead of turning." In the `theme.py` and `pdf_drive.py` entries, "tree on bg" becomes "tree on chrome — the top bar's token; the viewer pane on bg, a step darker (K-178 closed)".

- [ ] **Step 6: Commit** — `git add CLAUDE.md && git commit -m "Docs: the constellation map and the Library's one-surface panels (K-1XX)…"`; move every Phase A and B card to Done with a sign-off comment quoting the speed numbers and naming the render files.

---

## Self-Review

**Spec coverage.** Nodes interconnected satisfyingly → Task 5 (connected by construction, pinned with union-find). Slight 3D rotation, depth apparent → Task 6 (sway + stronger perspective; parallax pinned in pixels). Dim, lights up under the mouse → Task 4. The chosen PDF's name lights up, just that one → Task 3 (bare bright name) + Task 4 (exempt from dimming). Everything dim otherwise → Task 4's `DIM_LIT` rest state. Remove the little box → Task 1 (the card) + Task 3 (the plate). Remove the general glow → Task 1 (vignette) + Task 2 (halo). Integrated with the panel → Task 1 (host ground, no border) + Task 7 (same token) + Task 9 (render). Panels the same colour as the top bar → Task 7. Middle PDF area darker → Task 8. Gaps: none found.

**Placeholders.** Every code step shows code; the one conditional (Task 8, Step 5's fallback overlay) states its shape and its gate rather than "handle it". Board ids are written `K-1XX` because `board.py add` assigns them — that is the only symbol a worker must fill in, and Step 1 of each task says how.

**Type consistency.** `star_colour(c, pos, dim=False, lit=1.0)` is defined in Task 4 and used only there; `spanning_tree(points) -> list[(i, j)]` defined in Task 5 and consumed only by `constellation_links`; `sway_angle(t_ms, rest, amp, period_ms)` defined and consumed in Task 6; `_paint_ground(painter, c, w, h)` re-signed in Task 1 and not called elsewhere; `node_lines(pdf) -> [display]` re-specified in Task 3 and consumed by `_paint_label` only. `lit` the `pyqtProperty` and `set_lit_target(value)` are named identically in Task 4's interface block, implementation and pins.
