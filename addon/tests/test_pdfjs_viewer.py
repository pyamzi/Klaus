"""Headless tests for the pdf.js viewer foundation (K-096).

Covers the aqt-free helpers (renderer flag, base64 chunking, HTML
substitution) plus the viewer HTML's structural contract. The webview
itself can only be verified live — see the K-095 umbrella card.
"""
import base64
import importlib
import os
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
pv = importlib.import_module("klausmate.pdfjs_viewer")

section("renderer flag resolution")
check("empty config -> native", pv.renderer_from_config({}) == "native")
check("explicit native", pv.renderer_from_config({"pdf_renderer": "native"}) == "native")
check("explicit pdfjs", pv.renderer_from_config({"pdf_renderer": "pdfjs"}) == "pdfjs")
check("unknown value degrades to native",
      pv.renderer_from_config({"pdf_renderer": "webgl"}) == "native")
check("non-dict degrades to native", pv.renderer_from_config(None) == "native")

section("base64 chunking")
data = os.urandom(100_000)
parts = pv.chunk_b64(data, chunk_chars=7_000)
check("chunks are bounded", all(len(p) <= 7_000 for p in parts))
check("multiple chunks for data beyond one chunk", len(parts) > 1)
check("reassembled chunks round-trip the bytes",
      base64.b64decode("".join(parts)) == data)
check("small payload -> single chunk", len(pv.chunk_b64(b"x" * 10)) == 1)
check("empty payload -> no chunks", pv.chunk_b64(b"") == [])
try:
    pv.chunk_b64(b"x", chunk_chars=0)
    bad_chunk_raised = False
except ValueError:
    bad_chunk_raised = True
check("chunk_chars=0 raises", bad_chunk_raised)

section("page HTML build")
html = pv.build_page_html("klausmate", night=False)
check("addon substituted into script srcs",
      '/_addons/klausmate/web/pdfjs/pdf.min.js' in html
      and '/_addons/klausmate/web/pdfjs/pdf.worker.min.js' in html)
check("no placeholder left behind",
      "__ADDON__" not in html and "__THEME_VARS__" not in html)
check("theme tokens injected (light bg)", "--bg: #F5F5F7;" in html)
dark = pv.build_page_html("klausmate", night=True)
check("theme tokens injected (dark bg)", "--bg: #191919;" in dark)
# Both substitutions are a GLOBAL str.replace, so a placeholder spelled
# in the template's prose gets the replacement — the entire palette,
# for the theme vars — spliced into that comment. It shipped that way
# through K-116: harmless (it lands inside a comment) but it bloats
# every rendered page and it is a trap for anything grepping the
# rendered output. build_page_html's docstring is where those names
# are spelled; the template describes them instead.
_TPL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "klausmate", "web",
                         "pdfjs_viewer.html"), encoding="utf-8").read()
check("template spells __THEME_VARS__ only at its real site "
      "(a prose mention would splice the whole palette in)",
      _TPL.count("__THEME_VARS__") == 1)
check("template spells __ADDON__ only at its two real sites",
      _TPL.count("__ADDON__") == 2)
check("so the rendered page carries the palette exactly once",
      html.count("--bg: ") == 1 and dark.count("--bg: ") == 1)
for fn in ("klausPdfChunk", "klausPdfLoad", "klausPdfError",
           "klausGoToPage", "klausSetZoom", "klausSetAnnotations",
           "klausToggleThumbs", "klausScrollTo", "klausZoomReset"):
    check(f"JS API {fn} present", fn in html)
check("bridge prefix wired", "klausmate_pdfjs:" in html)
for feature in ("findbar", "findinput", "ctxmenu", "thumbs", "marquee",
                "hlLayer", "noteLayer"):
    check(f"page has {feature}", feature in html)
# pdf.js 3.x text-layer contract: spans are sized via
# calc(var(--scale-factor) * ...). Shipping without setting it made
# every span fall back to ~13px — invisible-selection misalignment and
# broken highlights, found live. Never again.
check("--scale-factor is set on the pages container",
      '"--scale-factor"' in html and "applyScaleFactor" in html)
check("scale factor tracks every scale change (build + rezoom)",
      html.count("applyScaleFactor()") >= 2)
check("text layer is pinned against host CSS (Anki stdHtml)",
      "text-size-adjust: none" in html and "box-sizing: content-box" in html
      and "max-width: none !important" in html)
# The native viewer's documented double-draw rule, transplanted: baked
# marks are REAL PDF annotations, and the on-screen overlay draws the
# same records — so every canvas render (pages, thumbs, image copies)
# must suppress annotation painting or highlights/outside text show
# twice (found live 2026-08-25). Four render sites, four flags.
check("every render call disables annotation painting",
      html.count("annotationMode: pdfjsLib.AnnotationMode.DISABLE")
      == html.count("page.render({"))
# Audited 2026-08-31 (K-116): the fifth site is refreshPage, the
# swap-in-place zoom re-renderer — flag verified by the pin above.
check("there are exactly five render sites",
      html.count("page.render({") == 5)

section("bridge parsing")
check("non-klaus command ignored", pv.parse_bridge("ankiweb:xyz") is None)
check("action only", pv.parse_bridge("klausmate_pdfjs:ready") == ("ready", ""))
check("action + payload",
      pv.parse_bridge("klausmate_pdfjs:page:3:10") == ("page", "3:10"))
check("payload keeps colons (data urls)",
      pv.parse_bridge("klausmate_pdfjs:copy-image:iVBOR:w0KG")
      == ("copy-image", "iVBOR:w0KG"))
import base64 as _b64
payload = _b64.b64encode(b'{"id": "abc"}').decode()
check("b64 json round-trip", pv.decode_b64_json(payload) == {"id": "abc"})
check("bad b64 json degrades to None", pv.decode_b64_json("!!") is None)

section("highlight record minting")
recs = pv.records_from_rect_map(
    {"1": [[10.0, 20.0, 100.0, 12.0], [10.0, 34.0, 80.0, 12.0]],
     "0": [[5, 6, 7, 8]]})
check("one record per page", len(recs) == 2)
check("pages ordered and 0-based ints",
      [r["page"] for r in recs] == [0, 1])
check("rects are float quads",
      recs[1]["rects"] == [[10.0, 20.0, 100.0, 12.0], [10.0, 34.0, 80.0, 12.0]])
check("records get uuid ids", all(len(r["id"]) == 32 for r in recs))
check("default color is the native yellow",
      all(r["color"] == "#fadc50" for r in recs))
check("zero-size rects dropped, page skipped when empty",
      pv.records_from_rect_map({"0": [[1, 2, 0, 5]]}) == [])
check("malformed input degrades to empty",
      pv.records_from_rect_map(None) == []
      and pv.records_from_rect_map({"x": [[1, 2, 3, 4]]}) == [])

section("duck-typed viewer surface")
# Shared PdfSidebar/poller code calls these on WHICHEVER renderer is
# active (grep pdf_viewer.py for `self._viewer.` and `v._`). A missing
# one is a live AttributeError — _apply_mirror crashed exactly that way
# on 2026-08-25 (external-change poll against the pdfjs renderer).
for attr in ("load_path", "set_page_texts", "load_annotations",
             "set_document", "clear_document", "go_to_page",
             "scroll_position", "restore_scroll_position",
             "toggle_thumbnails", "_apply_mirror",
             "_refresh_highlight_overlay", "_start_foreign_mirror"):
    check(f"PdfJsViewer has {attr}", hasattr(pv.PdfJsViewer, attr))

section("webview cleanup (theme_did_change dangling-hook crash)")
# Anki's AnkiWebView.__init__ registers on_theme_did_change with the
# global theme_did_change hook and ONLY cleanup() unregisters it. A
# webview destroyed without that call left a dead bound method in the
# hook, so the user's next theme change crashed inside Anki's own
# iteration ("wrapped C/C++ object of type AnkiWebView has been
# deleted", live traceback 2026-08-25). Simulate that lifecycle.
theme_hook: list = []


class _FakeWeb:
    """Stands in for AnkiWebView: registers on construction, and its
    cleanup() is the only thing that unregisters."""

    def __init__(self) -> None:
        self.alive = True
        theme_hook.append(self.on_theme_did_change)

    def on_theme_did_change(self) -> None:
        if not self.alive:
            raise RuntimeError(
                "wrapped C/C++ object of type AnkiWebView has been deleted"
            )

    def cleanup(self) -> None:
        try:
            theme_hook.remove(self.on_theme_did_change)
        except ValueError:
            pass

    def destroy_cpp(self) -> None:
        self.alive = False


def _fire_theme_change() -> bool:
    """True when Anki's hook iteration survives (no dangling entry)."""
    try:
        for fn in list(theme_hook):
            fn()
        return True
    except RuntimeError:
        return False


viewer = pv.PdfJsViewer.__new__(pv.PdfJsViewer)  # no Qt construction
viewer._web = _FakeWeb()
viewer._page_loaded = True
check("webview registered with the theme hook", len(theme_hook) == 1)
check("PdfJsViewer exposes cleanup()", hasattr(viewer, "cleanup"))
viewer.cleanup()
check("cleanup unregisters the webview", theme_hook == [])
viewer._web = None  # simulate: C++ side now torn down
check("a theme change after cleanup does not crash", _fire_theme_change())
check("cleanup is idempotent (teardown paths may overlap)",
      viewer.cleanup() is None and theme_hook == [])
# ...and prove the test itself can catch the regression it guards.
leaked = _FakeWeb()
leaked.destroy_cpp()
check("the guard is real: a webview destroyed WITHOUT cleanup crashes",
      _fire_theme_change() is False)
leaked.cleanup()

section("cleanup is wired into every teardown path")
pdf_viewer = importlib.import_module("klausmate.pdf_viewer")
check("PdfSidebar forwards cleanup to the renderer",
      hasattr(pdf_viewer.PdfSidebar, "cleanup"))
check("a profile/quit sweep exists as backstop",
      hasattr(pdf_viewer, "cleanup_all_sidebars"))
_here = os.path.dirname(os.path.abspath(__file__))
_src = lambda n: open(os.path.join(_here, "..", "klausmate", n)).read()
check("Library close tears the sidebar down",
      "sidebar.cleanup()" in _src("pdf_drive.py"))
check("editor panel close tears the sidebar down",
      "_sidebar.cleanup()" in _src("__init__.py"))
check("sweep registered on profile switch AND quit",
      _src("__init__.py").count("cleanup_all_sidebars") >= 2)

section("vendored pdf.js present")
here = os.path.dirname(os.path.abspath(__file__))
pdfjs = os.path.join(here, "..", "klausmate", "web", "pdfjs")
check("pdf.min.js vendored",
      os.path.getsize(os.path.join(pdfjs, "pdf.min.js")) > 100_000)
check("pdf.worker.min.js vendored",
      os.path.getsize(os.path.join(pdfjs, "pdf.worker.min.js")) > 500_000)

section("config default")
import json
cfg = json.load(open(os.path.join(here, "..", "klausmate", "config.json")))
check("config.json defaults pdf_renderer to native",
      cfg.get("pdf_renderer") == "native")

section("bridge dialogs deferred past the webchannel call (live crash)")
# The deferral rule itself — QTimer.singleShot(0, ...) around every
# modal a webchannel-dispatched handler reaches — is pinned centrally
# in tests/test_bridge_reentrancy.py, which auto-discovers this
# module's whole _bridge_* dispatch table. Here: only what that suite
# doesn't cover — the SHAPE of the note-edit split, and that
# _goto_dialog's non-bridge caller stays synchronous.
_SRC = _src("pdfjs_viewer.py")
check("the dialog logic lives in a separate _do_note_edit, which "
      "re-looks-up the record by id rather than trusting a captured "
      "reference across the deferred tick",
      "def _do_note_edit(self, hl_id: str) -> None:" in _SRC
      and _SRC.index("def _do_note_edit")
      > _SRC.index("def _bridge_note_edit"))
check("_goto_dialog's OTHER caller (a native QLabel click, not the "
      "webchannel) stays synchronous — only the bridge entry defers",
      "self._goto_dialog()" in _SRC.split("def eventFilter", 1)[1]
      .split("def ", 1)[0])

section("context menu keeps the selection alive (live Blink repro)")
# Every selection-dependent menu item reads window.getSelection() inside
# its CLICK handler. Blink collapses the selection on a trusted mousedown
# over a non-editable element, and does it BEFORE click fires — so the
# menu offered "Highlight" on a real selection and the handler then saw
# nothing, reporting "select text first". Verified with actual mouse
# input in a real Blink engine: click-only wiring reads the selection as
# collapsed (alive: false, text: ""), the mousedown guard keeps it
# (alive: true, full text).
_HTML = _src(os.path.join("web", "pdfjs_viewer.html"))
check("the context menu cancels mousedown, so the selection survives to "
      "the click handler",
      'ctxmenu.addEventListener("mousedown"' in _HTML
      and "ev.preventDefault()" in _HTML.split(
          'ctxmenu.addEventListener("mousedown"', 1)[1].split("\n", 1)[0])
check("the guard is on the MENU CONTAINER, not per item — items are "
      "rebuilt on every open, a container listener catches them all",
      _HTML.index('ctxmenu.addEventListener("mousedown"')
      < _HTML.index('mi.addEventListener("click"'))
for _item in ("Highlight", "Copy Selection as Image"):
    check(f"'{_item}' is still offered only when there IS a selection "
          "(hasSel gate) — the guard fixes the handler, not the gate",
          f'["{_item}"' in _HTML and "if (hasSel) {" in _HTML)

section("K-116: one zoom engine behind every zoom path")
_HTML116 = _src(os.path.join("web", "pdfjs_viewer.html"))
check("a single clamp bounds every zoom writer",
      "const MIN_SCALE = 0.25, MAX_SCALE = 4.0;" in _HTML116
      and _HTML116.count("clampScale(") >= 5
      and "Math.min(4.0" not in _HTML116)
check("ctrl-wheel (macOS pinch) is claimed with a NON-passive listener "
      "so preventDefault can stop QtWebEngine's frame zoom",
      'document.addEventListener("wheel"' in _HTML116
      and "{ passive: false }" in _HTML116)
_WHEEL = _HTML116.split('document.addEventListener("wheel"', 1)[1]
_WHEEL = _WHEEL.split("},", 1)[0]
check("plain two-finger scroll is untouched; ctrl-pinch is consumed",
      "if (!ev.ctrlKey) return;" in _WHEEL
      and "ev.preventDefault();" in _WHEEL)
check("pinch zooms through the session, anchored at the cursor",
      "zoomTo(sessionTarget() * Math.exp(-ev.deltaY * PINCH_K)" in _HTML116)
check("gesture events are cancelled so nothing double-zooms",
      '"gesturestart"' in _HTML116 and '"gesturechange"' in _HTML116
      and '"gestureend"' in _HTML116)
_KSZ = _HTML116.split("window.klausSetZoom = function", 1)[1]
_KSZ = _KSZ.split("};", 1)[0]
_KZR = _HTML116.split("window.klausZoomReset = async function", 1)[1]
_KZR = _KZR.split("};", 1)[0]
check("keyboard/menu/toolbar zoom rides the SAME session — no direct "
      "synchronous rezoom left on the zoom paths (the width-refit "
      "observer legitimately keeps its rezoom)",
      "zoomTo(sessionTarget() * factor" in _KSZ
      and "rezoom(" not in _KSZ and "rezoom(" not in _KZR)
check("the fit/reset path rides it too, flagged so the width-refit "
      "observer stays armed", "zoomTo(fit, c[0], c[1], true)" in _HTML116)
check("zoom settle is debounced behind rapid steps",
      "setTimeout(zoomSettle, ZOOM_SETTLE_MS)" in _HTML116)
check("the interim is a compositor transform on #pages, origined at "
      "the anchor",
      "transformOrigin" in _HTML116
      and 'transform = "scale(" + p.factor + ")"' in _HTML116)
check("a page zoomed WIDER than the scroller stays scrollable — "
      "#pages sizes to its content (the old fixed width centered wide "
      "pages with the left half at unreachable negative offsets; "
      "caught by the K-116 harness' anchor check)",
      "width: max-content; min-width: 100%;" in _HTML116)
check("the settle puts the anchored PDF point back under the pointer "
      "(page-exact, proportional fallback over gaps)",
      "div.offsetTop + p.hit.yPt * state.scale - vy" in _HTML116
      and "p.cy0 * r - vy" in _HTML116)

section("K-116: zoom never blanks a rendered page")
_SETTLE = _HTML116.split("async function zoomSettle", 1)[1]
_SETTLE = _SETTLE.split("\n}\n", 1)[0]
check("zoomSettle re-lays-out softly, never the teardown twin",
      "softRelayout()" in _SETTLE
      and "relayout()" not in _SETTLE.replace("softRelayout()", ""))
check("zoomSettle neither tears a page down nor clears the render "
      "cache",
      "teardownPage" not in _SETTLE and "rendered.clear" not in _SETTLE)
check("softRelayout stretches the EXISTING canvas into the new "
      "geometry — old pixels stay up while crisp ones render",
      "r.canvas.style.width = w" in _HTML116)
check("crisp replacements swap in atomically, only once fully drawn",
      "replaceChild(canvas, entry.canvas)" in _HTML116)
check("the replacement text layer renders attached-but-hidden (pdf.js "
      "measures spans against computed style)",
      'textLayer.style.visibility = "hidden";' in _HTML116)
check("re-renders go visible pages first",
      "function refreshVisibleFirst" in _HTML116
      and "refreshVisibleFirst();" in _SETTLE)
check("superseded refreshes discard themselves (zoom generation)",
      "zoomGen++" in _HTML116 and "gen !== zoomGen" in _HTML116)
check("a render the settle overtook corrects itself",
      "Math.abs(viewport.scale - state.scale)" in _HTML116)

section("K-116: annobar — the always-visible tool bar")
check("annobar exists with all six controls",
      'id="annobar"' in _HTML116
      and all('id="%s"' % i in _HTML116 for i in
              ("abHl", "abText", "abZoomOut", "abZoomPct", "abZoomIn",
               "abZoomFit")))
check("HIG Title Case control-name tooltips, shortcuts in parens "
      "(glossary commit 14e2b05)",
      'title="Highlight"' in _HTML116
      and 'title="Add Text"' in _HTML116
      and 'title="Zoom Out (&#8984;&#8722;)"' in _HTML116
      and 'title="Zoom In (&#8984;+)"' in _HTML116
      and 'title="Actual Size (&#8984;0)"' in _HTML116)
_AB_CSS = _HTML116.split("#annobar {", 1)[1].split("}", 1)[0]
_AB_ACT = _HTML116.split("#annobar button.active", 1)[1].split("}", 1)[0]
check("annobar chrome stays in the findbar's var family",
      "var(--surface)" in _AB_CSS and "var(--grey-light)" in _AB_CSS
      and "var(--accent)" in _AB_ACT)
check("the family's hover token gets a fallback BEFORE the theme "
      "substitution (an undefined var() paints nothing)",
      0 <= _HTML116.find("--hover-subtle: rgba")
      < _HTML116.find(":root { __THEME_VARS__ }"))
_AB_MD = _HTML116.split('("annobar").addEventListener(', 1)[1][:80]
check("the bar cancels mousedown so a live selection survives a "
      "Highlight click (ctxmenu's documented Blink rule)",
      '"mousedown"' in _AB_MD and "preventDefault" in _AB_MD)
check("highlight tool: releasing a selection auto-highlights, gated "
      "on selectionRectMap so a bare click can never toast",
      'state.tool === "hl" && selectionRectMap()' in _HTML116)
check("arming Highlight consumes a selection that already exists",
      "if (arming && selectionRectMap()) addHighlightFromSelection()"
      in _HTML116)
check("text tool: a page click posts text-add with page-point coords "
      "and disarms (one-shot; the dialog flow owns the rest)",
      'postB64("text-add", { page: hit.page0, x: hit.xPt, y: hit.yPt })'
      in _HTML116 and "setTool(null);" in _HTML116)
check("Escape clears an armed tool (menu/findbar behaviour unchanged)",
      "if (state.tool) setTool(null);" in _HTML116)
check("the zoom readout is fed from the applyScaleFactor choke point",
      "updateZoomReadout(state.scale)" in _HTML116)
check("annobar zoom buttons ride the shared zoom API",
      'abZoomIn").addEventListener(\n  "click", () => window.klausSetZoom(1.2))'
      in _HTML116
      and 'abZoomFit").addEventListener(\n  "click", () => window.klausZoomReset())'
      in _HTML116)

section("K-116: text-add bridge — Python clamps, JS is never trusted")
check("parse_bridge routes text-add",
      pv.parse_bridge("klausmate_pdfjs:text-add:eyJ4IjogMX0=")
      == ("text-add", "eyJ4IjogMX0="))
check("valid payload -> (page, x, y)",
      pv.clamp_text_add({"page": 2, "x": 10.5, "y": 20.25}, 5)
      == (2, 10.5, 20.25))
check("page beyond the document is rejected",
      pv.clamp_text_add({"page": 5, "x": 1, "y": 1}, 5) is None)
check("unknown page_count admits any non-negative page",
      pv.clamp_text_add({"page": 99, "x": 1, "y": 1}, 0)
      == (99, 1.0, 1.0))
check("negative coords clamp to the page origin",
      pv.clamp_text_add({"page": 0, "x": -5, "y": -0.1}, 1)
      == (0, 0.0, 0.0))
check("absurd coords cap at the PDF spec's 14,400 pt",
      pv.clamp_text_add({"page": 0, "x": 1e9, "y": 2}, 1)
      == (0, 14400.0, 2.0))
check("non-finite coords are rejected (json admits NaN/Infinity)",
      pv.clamp_text_add({"page": 0, "x": float("nan"), "y": 1}, 1)
      is None
      and pv.clamp_text_add({"page": 0, "x": 1, "y": float("inf")}, 1)
      is None)
check("bool page is rejected (bool IS an int in Python)",
      pv.clamp_text_add({"page": True, "x": 1, "y": 1}, 5) is None)
check("bool/str coords, negative page, and junk all reject",
      pv.clamp_text_add({"page": 0, "x": True, "y": 1}, 1) is None
      and pv.clamp_text_add({"page": 0, "x": "1", "y": 1}, 1) is None
      and pv.clamp_text_add({"page": -1, "x": 1, "y": 1}, 1) is None
      and pv.clamp_text_add("nope", 1) is None
      and pv.clamp_text_add(None, 1) is None
      and pv.clamp_text_add({}, 1) is None)

section("K-116: outside-text record minting (K-077/K-083 shape)")
rec = pv.make_text_record(3, 100.0, 200.0, "hello world")
check("exact key set of the adopted-text schema",
      set(rec) == {"id", "kind", "page", "rects", "text", "note",
                   "color", "size"})
check("kind text, 0-based int page, single box rect",
      rec["kind"] == "text" and rec["page"] == 3
      and len(rec["rects"]) == 1 and len(rec["rects"][0]) == 4)
check("box is anchored at the click point",
      rec["rects"][0][0] == 100.0 and rec["rects"][0][1] == 200.0)
check("explicit black + 12pt — the validator backfills a missing "
      "color with highlight YELLOW",
      rec["color"] == "#000000" and rec["size"] == 12.0)
check("uuid id, empty note", len(rec["id"]) == 32 and rec["note"] == "")
check("NO origin key — native records must not claim to be external",
      "origin" not in rec)
_ph = importlib.import_module("klausmate.pdf_handler")
check("pdf_handler validation round-trips the record UNCHANGED",
      _ph._validate_highlight(rec) == rec)
_w1 = pv.text_box_size("abc")
_w2 = pv.text_box_size("abcdefghijklmnopqrstuvwxyz")
_w3 = pv.text_box_size("a\nb\nc")
check("box grows with the longest line", _w2[0] > _w1[0])
check("box grows with line count", _w3[1] > _w1[1])
check("bounds hold for degenerate and absurd input",
      pv.text_box_size("")[0] == 60.0
      and pv.text_box_size("x" * 10000)[0] == 480.0
      and pv.text_box_size("\n".join("x" * 999))[1] == 720.0)

section("K-116: the new dialog obeys K-114 (open(), never exec)")
import ast as _ast116
_SRC116 = _src("pdfjs_viewer.py")
_TREE116 = _ast116.parse(_SRC116)


def _fn116(name):
    for node in _ast116.walk(_TREE116):
        if isinstance(node, _ast116.FunctionDef) and node.name == name:
            return _ast116.get_source_segment(_SRC116, node) or ""
    return ""


_TA = _fn116("_bridge_text_add")
check("_bridge_text_add clamps THEN defers past the webchannel tick",
      "clamp_text_add" in _TA and "QTimer.singleShot" in _TA
      and -1 < _TA.find("clamp_text_add") < _TA.find("QTimer.singleShot"))
_OD = _fn116("_open_text_dialog")
check("the prompt opens window-modal via open() + signal callbacks",
      "dlg.open()" in _OD and "textValueSelected.connect" in _OD)
check("no exec()-shaped modal anywhere in the new flow",
      ".exec(" not in _OD and "QInputDialog.get" not in _OD)
from anki_stubs import code_only as _code_only116
check("the whole module still contains zero .exec( calls in CODE "
      "(the crash-history comments may spell it)",
      ".exec(" not in _code_only116(_SRC116))
check("a live prompt is a singleton (front, don't stack)",
      "raise_()" in _OD and "activateWindow()" in _OD)
_OA = _fn116("_on_text_added")
check("accepting persists through the SAME save + debounced-bake path "
      "and pushes canonical records back",
      "_save_annotations()" in _OA and "_push_annotations()" in _OA
      and "make_text_record" in _OA)
check("empty text mints nothing", "if not body:" in _OA)

raise SystemExit(report())
