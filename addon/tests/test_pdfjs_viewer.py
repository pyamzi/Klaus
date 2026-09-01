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
      "if (arming && selectionRectMap()) addHighlightFromSelection();"
      in _HTML116)
# K-150 rewrote this one: the placement click used to post text-add
# with nothing but coordinates, because a modal dialog collected the
# body afterwards. It now opens the in-place editor and posts NOTHING
# — the bridge call moved to commitTextEdit, where there is finally a
# body to send. K-159 then made the tool STICKY; the disarm half of
# this check moved to that section, SCOPED to the handler (a bare
# `"setTool(null);" in _HTML116` passed on the Escape handler's copy
# and could never have caught the change).
check("text tool: a page click opens the in-place editor at the "
      "page-point; nothing is posted yet",
      "openTextEdit(hit.page0, hit.xPt, hit.yPt, null);" in _HTML116
      and 'postB64("text-add", { page: hit.page0, x: hit.xPt, y: hit.yPt })'
      not in _HTML116)
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

section("K-150: the text flow has no dialog left to crash (was K-114)")
# K-116 shipped Add Text as a window-modal QInputDialog and these pins
# guarded HOW it opened: open() + signal callbacks, never exec(),
# clamp-before-defer, one prompt at a time. K-150 deleted the dialog
# instead — the box is typed on the page — so the pins were REWRITTEN
# rather than dropped. The crash class they guarded is real and
# undiminished; what changed is that this flow no longer touches it,
# and these checks now say exactly that, in a way that fails the day
# a dialog comes back.
import ast as _ast116
_SRC116 = _src("pdfjs_viewer.py")
_TREE116 = _ast116.parse(_SRC116)


def _fn116(name):
    for node in _ast116.walk(_TREE116):
        if isinstance(node, _ast116.FunctionDef) and node.name == name:
            return _ast116.get_source_segment(_SRC116, node) or ""
    return ""


from anki_stubs import code_only as _code_only116
_TA = _fn116("_bridge_text_add")
_TU = _fn116("_bridge_text_update")
# Both handlers DESCRIBE the validators they call, so every substance
# check below reads the strings-and-comments-stripped source. Dropping
# sanitize_text from the body and leaving the docstring alone kept the
# first draft of this pin green — caught in the falsification sweep,
# which is the fourth time prose has faked a pin in this repo.
_TAC, _TUC = _code_only116(_TA), _code_only116(_TU)
check("both text handlers were found in the source", bool(_TA) and bool(_TU))
check("the dialog and its whole singleton apparatus are GONE — no "
      "prompt, so nothing to defer, front, or tear down",
      not _fn116("_open_text_dialog") and not _fn116("_on_text_dialog_closed")
      and not _fn116("_on_text_added")
      and "_text_dialog" not in _code_only116(_SRC116))
check("neither text handler builds a QInputDialog (that is what the "
      "deferral and never-exec rules exist to protect)",
      "QInputDialog" not in _TAC and "QInputDialog" not in _TUC)
check("...nor defers, because there is nothing to defer past: they "
      "mint synchronously on _bridge_hl_add's proven path",
      "QTimer" not in _TAC and "QTimer" not in _TUC)
check("the whole module still contains zero .exec( calls in CODE "
      "(the crash-history comments may spell it)",
      ".exec(" not in _code_only116(_SRC116))
check("the OTHER prompts this module still owns keep the K-114 shape "
      "— an instance, open(), signal callbacks, never a static helper",
      "dlg.open()" in _code_only116(_fn116("_do_note_edit"))
      and "dlg.open()" in _code_only116(_fn116("_goto_dialog"))
      and "QInputDialog.get" not in _code_only116(_SRC116))
check("text-add still clamps the untrusted coordinates FIRST",
      "clamp_text_add" in _TAC
      and -1 < _TAC.find("clamp_text_add") < _TAC.find("make_text_record"))
check("...and now validates the BODY too, which used to arrive from a "
      "Qt dialog and now arrives over the bridge",
      "sanitize_text" in _TAC and "validate_hex_color" in _TAC
      and "validate_text_size" in _TAC)
check("minting persists through the SAME save + debounced-bake path "
      "and pushes canonical records back",
      "_save_annotations()" in _TAC and "_push_annotations()" in _TAC
      and "make_text_record" in _TAC)
check("empty text mints nothing (the dialog-era rule, kept)",
      "if not body:" in _TAC)
check("a no-op commit costs no save and no bake — but the push is "
      "UNCONDITIONAL, because the page dropped this record's static "
      "twin while its editor was open and is waiting for canonical "
      "records to draw it again",
      "if changed:" in _TU
      and "\n            self._save_annotations()" in _TU
      and "\n        self._push_annotations()" in _TU
      and "\n            self._push_annotations()" not in _TU)

section("K-100: Cmd/Ctrl double-click copies the slide (native gesture)")
_H100 = _src(os.path.join("web", "pdfjs_viewer.html"))
check("a dblclick listener gates on meta/ctrl and routes through the "
      "SAME copyPageImage -> copy-image bridge the menu uses, so the "
      "editor-side insert path (clipboard, then paste) stays shared",
      'addEventListener("dblclick"' in _H100
      and "if (!(ev.metaKey || ev.ctrlKey)) return;" in _H100
      and _H100.split('addEventListener("dblclick"', 1)[1]
      .split("});", 1)[0].count("copyPageImage(hit.page0);") == 1)

section("K-100: persisted marquee — kept after release, like Preview")
check("creation release copies AND persists (native keeps the rect)",
      "copyRegionImage(m.page0, x0, y0, w, h);" in _H100
      and "persistMarquee(m.page0, x0, y0, w, h);" in _H100)
check("the region render is factored out and shared by the clipboard "
      "copy and the drag-out cache",
      "async function renderRegionCanvas(" in _H100
      and _H100.count("renderRegionCanvas(") >= 3)
check("native press rules: plain left press outside collapses it; a "
      "press ON it arms drag-out instead; alt-press starting a new "
      "marquee collapses the old one first",
      'ev.target.id === "marqueeKeep"' in _H100
      and _H100.count("clearPersistMarquee();") >= 3
      and -1 < _H100.find("if (ev.altKey) {")
      < _H100.find("state.marquee = { page0: hit.page0"))
check("the overlay re-lands at the current scale on every overlay pass "
      "and on the zoom settle's soft relayout",
      "state.persistMarquee.page0 === num - 1" in _H100
      and "positionPersistMarquee();" in _H100.split(
          "async function softRelayout", 1)[1].split("\n}\n", 1)[0])
check("drag-out ships the cached PNG as HTML with a data URI — "
      "setData is synchronous, the render is not, so the PNG is "
      "cached at persist time and a cache miss cancels the drag",
      'addEventListener("dragstart"' in _H100
      and "el.draggable = true;" in _H100
      and 'setData(\n          "text/html", \'<img src="\' + cur.dataUrl'
      in _H100
      and "if (!cur || !cur.dataUrl) { ev.preventDefault(); return; }"
      in _H100)
check("the context menu re-offers the native marquee re-copy while one "
      "stands (marquee_act's label), region frozen into the closure",
      "else if (state.persistMarquee) {" in _H100
      and _H100.count('["Copy Selection as Image"') == 2
      and "copyRegionImage(pm.page0, pm.x, pm.y, pm.w, pm.h)" in _H100)
check("document teardown forgets it",
      "state.persistMarquee = null;   // its overlay dies" in _H100)
check("the overlay keeps the marquee's var family (no literal colours)",
      "#marqueeKeep {" in _H100
      and "var(--accent-selection)" in _H100.split("#marqueeKeep {", 1)[1]
      .split("}", 1)[0])

section("K-100: exact-substring find highlighting")
check("matches now carry page-string offsets beside the owning span",
      "matches.push({ page0: p, itemIdx, start: at, len: q.length });"
      in _H100)
check("painted via the CSS Custom Highlight API — Ranges over the text "
      "nodes, no DOM mutation of pdf.js's measured spans",
      'CSS.highlights.set("klaus-find", new Highlight(...ranges));'
      in _H100
      and 'CSS.highlights.delete("klaus-find");' in _H100
      and "::highlight(klaus-find)" in _H100)
check("the owning-span ring survives as the guarded fallback (no API, "
      "no text node, stale match shape)",
      'anchor.classList.add("findCurrent");' in _H100
      and "if (!painted)" in _H100
      and "span.findCurrent" in _H100)
check("highlight styling stays in the theme var family",
      "var(--accent-selection)" in _H100.split("::highlight(klaus-find)", 1)[1]
      .split("}", 1)[0])

section("K-100: matchSegments math (real JS under node)")
# The offset arithmetic is the risky part — per-item slices of a match
# that can cross item boundaries and step over the "\n" EOL joiners
# that belong to NO item. No browser needed: the function is pure, so
# it runs under node against a stubbed state. Honest SKIP without node
# (dashboard_js_dom_test's precedent).
import json as _json100
import re as _re100
import shutil as _shutil100
import subprocess as _sub100
import tempfile as _tmp100

_node = _shutil100.which("node")
_seg_src = _re100.search(
    r"function matchSegments\(m\) \{[\s\S]*?\n\}", _H100)
check("matchSegments extracted from the page source", _seg_src is not None)
if _node is None:
    print("  SKIP node not installed — matchSegments math + JS syntax "
          "unverified on this machine")
elif _seg_src is not None:
    _harness = (
        '"use strict";\n'
        "const state = { pageTexts: [\n"
        '  { str: "Hello\\nworld",'
        " items: [ {start:0,len:5}, {start:6,len:5} ] },\n"
        '  { str: "abcdefg",'
        " items: [ {start:0,len:3}, {start:3,len:0}, {start:3,len:4} ] },\n"
        "] };\n"
        + _seg_src.group(0) + "\n"
        "console.log(JSON.stringify([\n"
        "  matchSegments({page0:0, itemIdx:0, start:3, len:5}),\n"
        "  matchSegments({page0:0, itemIdx:1, start:6, len:5}),\n"
        "  matchSegments({page0:1, itemIdx:0, start:2, len:3}),\n"
        "  matchSegments({page0:9, itemIdx:0, start:0, len:1}),\n"
        "]));\n"
    )
    with _tmp100.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as _f:
        _f.write(_harness)
        _hpath = _f.name
    try:
        _out = _sub100.run(
            [_node, _hpath], capture_output=True, text=True, timeout=30
        )
        _got = _json100.loads(_out.stdout.strip() or "null")
    except Exception as _e:
        _got = f"node run failed: {_e}"
    check("a match crossing the EOL joiner slices per owning span and "
          "skips the joiner ('lo\\nwo' over Hello\\nworld)",
          isinstance(_got, list)
          and _got[0] == [{"itemIdx": 0, "a": 3, "b": 5},
                          {"itemIdx": 1, "a": 0, "b": 2}], repr(_got))
    check("an interior match maps to one span slice ('world')",
          isinstance(_got, list)
          and _got[1] == [{"itemIdx": 1, "a": 0, "b": 5}], repr(_got))
    check("zero-length items are stepped over, never sliced",
          isinstance(_got, list)
          and _got[2] == [{"itemIdx": 0, "a": 2, "b": 3},
                          {"itemIdx": 2, "a": 0, "b": 2}], repr(_got))
    check("a match on a page with no text data yields no slices",
          isinstance(_got, list) and _got[3] == [], repr(_got))
    # And the whole inline script still parses — a net under every
    # future JS edit, since no browser harness exists for this page.
    _inline = _re100.findall(r"<script>([\s\S]*?)</script>", _H100)
    with _tmp100.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as _f2:
        _f2.write(max(_inline, key=len))
        _spath = _f2.name
    _chk = _sub100.run(
        [_node, "--check", _spath], capture_output=True, text=True,
        timeout=30,
    )
    check("the page's inline script parses clean under node --check",
          _chk.returncode == 0, _chk.stderr[:300])

section("K-149: one drag, one layer of paint")
# THE MEASUREMENT behind merge_rects, taken in Blink (Chromium, the same
# engine QtWebEngine runs) against a DOM built to pdf.js's text-layer
# contract — absolutely positioned, shrink-wrapped, line-height 1 spans:
#
#   range over ONE fully covered span -> TWO rects
#     [21, 21,   110.28, 16  ]   the span's border box
#     [21, 19.5, 110.28, 18.5]   its text node's quad (taller, nests it)
#
# Per the DOM spec Range.getClientRects() yields an element's border box
# AND its text quads when the range covers that element completely, so a
# three-line drag returns SIX rects. Every one of them cleared the old
# sub-pixel guard, became its own .hl div, and two layers of the
# 43%-alpha paint composite to 67.5% — the reported "double- and
# triple-highlighted" look, from a single drag with no user error.
_BLINK_3_LINES = [
    [21, 21, 110.28, 16], [21, 19.5, 110.28, 18.5],
    [21, 45, 120.09, 16], [21, 43.5, 120.09, 18.5],
    [21, 69, 104.95, 16], [21, 67.5, 104.95, 18.5],
]
_QUADS_3_LINES = [
    [21.0, 19.5, 110.28, 18.5],
    [21.0, 43.5, 120.09, 18.5],
    [21.0, 67.5, 104.95, 18.5],
]
check("the six rects Blink returns for a three-line drag merge to three",
      pv.merge_rects(_BLINK_3_LINES) == _QUADS_3_LINES,
      repr(pv.merge_rects(_BLINK_3_LINES)))
check("the survivor is the OUTER box — the taller text quad, which "
      "covers the glyphs instead of clipping their descenders",
      all(r[3] == 18.5 for r in pv.merge_rects(_BLINK_3_LINES)))
# Measured for the same drag started/ended mid-word: the end spans give
# one (partial) rect each, the fully covered middle span still gives two.
_BLINK_PARTIAL = [
    [41.45, 19.5, 89.83, 18.5],
    [21, 45, 120.09, 16], [21, 43.5, 120.09, 18.5],
    [21, 67.5, 36.45, 18.5],
]
check("a partial drag keeps its clipped ends and de-doubles only the "
      "fully covered span in the middle",
      pv.merge_rects(_BLINK_PARTIAL) == [
          [41.45, 19.5, 89.83, 18.5],
          [21.0, 43.5, 120.09, 18.5],
          [21.0, 67.5, 36.45, 18.5]],
      repr(pv.merge_rects(_BLINK_PARTIAL)))
check("exact duplicates collapse", pv.merge_rects(
    [[10, 20, 100, 12], [10, 20, 100, 12]]) == [[10.0, 20.0, 100.0, 12.0]])
check("containment collapses either way round",
      pv.merge_rects([[10, 20, 100, 12], [20, 22, 40, 8]])
      == [[10.0, 20.0, 100.0, 12.0]]
      and pv.merge_rects([[20, 22, 40, 8], [10, 20, 100, 12]])
      == [[10.0, 20.0, 100.0, 12.0]])
check("the several spans of one line stitch into one box across a "
      "hairline gap (cleaner quad_points for the bake too)",
      pv.merge_rects([[10, 20, 50, 12], [60.5, 20, 40, 12]])
      == [[10.0, 20.0, 90.5, 12.0]])
# The two rules that keep the merge from eating real layout.
check("a two-column gutter is NOT stitched (gap >> the hairline)",
      len(pv.merge_rects([[10, 20, 50, 12], [300, 20, 50, 12]])) == 2)
check("consecutive lines that share a few points of leading stay "
      "separate (>50% of the shorter rect is what makes a line)",
      len(pv.merge_rects([[10, 20, 100, 12], [10, 30, 100, 12]])) == 2)
check("merging is idempotent",
      pv.merge_rects(pv.merge_rects(_BLINK_3_LINES)) == _QUADS_3_LINES)
check("input order cannot change the result",
      pv.merge_rects(list(reversed(_BLINK_3_LINES))) == _QUADS_3_LINES)
check("malformed and degenerate rects are dropped, never raised on",
      pv.merge_rects(None) == [] and pv.merge_rects([[1, 2, 0, 5]]) == []
      and pv.merge_rects([["a", 2, 3, 4], [1, 2, 3, 4]])
      == [[1.0, 2.0, 3.0, 4.0]]
      and pv.merge_rects([[float("inf"), 2, 3, 4]]) == [])
check("records_from_rect_map runs the merge at the mint choke point "
      "(the page dedupes too, but JS is never trusted)",
      pv.records_from_rect_map({"0": _BLINK_3_LINES})[0]["rects"]
      == _QUADS_3_LINES)
# This is the half that keeps the PAYLOAD honest, not the paint: the
# page never renders a highlight optimistically (state.annots arrives
# only through klausSetAnnotations), so what is drawn is always the
# canonical record Python merged. What the page's own pass buys is a
# wire format of one rect per line instead of two — a forty-line
# selection ships forty rects, not eighty.
check("selectionRectMap folds each page's rects before they leave the "
      "page",
      "for (const page of Object.keys(map)) map[page] = mergeRects(map[page]);"
      in _HTML116)

section("K-149: the ink is picked in the page, validated in Python")
check("validate_hex_color normalizes to the lowercase #rrggbb every "
      "pre-K-149 record on disk already uses",
      pv.validate_hex_color("#8AE08C") == "#8ae08c"
      and pv.validate_hex_color("8AE08C") == "#8ae08c"
      and pv.validate_hex_color("#ABC") == "#aabbcc")
check("anything that is not a hex colour falls back, never lands in "
      "the JSON verbatim",
      pv.validate_hex_color("red") == pv.HIGHLIGHT_COLOR
      and pv.validate_hex_color("#12345") == pv.HIGHLIGHT_COLOR
      and pv.validate_hex_color("#gggggg") == pv.HIGHLIGHT_COLOR
      and pv.validate_hex_color(None) == pv.HIGHLIGHT_COLOR
      and pv.validate_hex_color({"x": 1}) == pv.HIGHLIGHT_COLOR
      and pv.validate_hex_color("") == pv.HIGHLIGHT_COLOR)
check("a chosen ink reaches the record",
      pv.records_from_rect_map(
          {"0": [[1, 2, 3, 4]]}, color="#8ae08c")[0]["color"] == "#8ae08c")
_theme149 = importlib.import_module("klausmate.theme")
check("the swatch palette lives in theme.py, not in the page",
      len(_theme149.HIGHLIGHT_INKS) == 5)
check("yellow stays first and IS the native default — the two "
      "constants cannot drift apart",
      _theme149.HIGHLIGHT_INK_DEFAULT.lower() == pv.HIGHLIGHT_COLOR)
check("every ink is a hex the validator accepts unchanged",
      all(pv.validate_hex_color(v) == v.lower()
          for _n, v in _theme149.HIGHLIGHT_INKS))
_INK_NAMES = [n for n, _v in _theme149.HIGHLIGHT_INKS]
# The trap the K-116 annobar documented: a trusted mousedown over
# non-editable UI collapses the selection before click fires. The
# swatches are INSIDE #annobar precisely so the bar's cancel covers
# them — a popover hung off <body> would eat the selection it was
# aimed at.
_ANNOBAR_MARKUP = _HTML116.split('<div id="annobar">', 1)[1].split(
    "</div>\n    </div>", 1)[0]
check("the page's swatches name exactly the theme's inks, in order",
      _re100.findall(r'data-ink="([a-z]+)"', _ANNOBAR_MARKUP) == _INK_NAMES,
      repr(_re100.findall(r'data-ink="([a-z]+)"', _ANNOBAR_MARKUP)))
_INK_CSS = _HTML116.split("#abInks {", 1)[1].split("#abZoomPct", 1)[0]
_INK_CSS_FLAT = " ".join(_INK_CSS.split())
check("each swatch is painted from its theme var — no hex in the page "
      "(CLAUDE.md: UI files must not hardcode colours)",
      all(f'button.inkSw[data-ink="{n}"] {{ background: var(--ink-{n}); }}'
          in _INK_CSS_FLAT for n in _INK_NAMES), _INK_CSS_FLAT[:300])
check("...including the selected-swatch cue and the whole ink block",
      not _re100.search(r"#[0-9a-fA-F]{3,8}\b", _INK_CSS), _INK_CSS[:200])
check("the chosen ink is read BACK out of that custom property, so "
      "the colour seen is the colour recorded",
      'getPropertyValue("--ink-" + state.ink)' in _HTML116)
check("the hl-add payload carries it",
      'postB64("hl-add", { pages: map, color: currentInk() })' in _HTML116)
check("an unresolvable var sends nothing rather than a bad string — "
      "Python's default takes over",
      "return v || null;" in _HTML116)
check("the swatch row lives inside #annobar, so it inherits the bar's "
      "mousedown cancel and the selection survives the click",
      'id="abInks"' in _ANNOBAR_MARKUP
      and all(f'data-ink="{n}"' in _ANNOBAR_MARKUP for n in _INK_NAMES))
check("picking a colour with a live selection highlights it now "
      "(same move as arming Highlight)",
      "if (selectionRectMap()) addHighlightFromSelection();" in _HTML116)

section("K-149: merging happens at MINT time, never in storage")
# pdf_handler collapses duplicates ONLY for origin=="external" records
# (Preview autosaves the same box repeatedly while you type), and
# test_klausmate pins that overlapping NATIVE highlights are never
# collapsed there — K-081's architecture. So the second-drag merge
# lives here, in the mint path.
_YEL, _GRN = "#fadc50", "#8ae08c"
_base = [{"id": "a" * 32, "page": 0, "rects": [[10, 20, 100, 12]],
          "color": _YEL, "note": ""}]
_again = pv.records_from_rect_map({"0": [[10, 20, 100, 12]]}, color=_YEL)
check("re-highlighting the same text in the same ink changes nothing "
      "(no second record, so no 67.5% composite)",
      pv.merge_highlight_records(_base, _again) == _base)
_wider = pv.records_from_rect_map({"0": [[10, 20, 140, 12]]}, color=_YEL)
_grown = pv.merge_highlight_records(_base, _wider)
check("an overlapping drag in the same ink extends the record it "
      "touches instead of stacking a second one",
      len(_grown) == 1 and _grown[0]["id"] == "a" * 32
      and _grown[0]["rects"] == [[10.0, 20.0, 140.0, 12.0]],
      repr(_grown))
_recol = pv.merge_highlight_records(
    _base, pv.records_from_rect_map({"0": [[10, 20, 100, 12]]}, color=_GRN))
check("dragging over a mark in a DIFFERENT ink recolours it — one "
      "record, the new colour, never two inks compositing",
      len(_recol) == 1 and _recol[0]["color"] == _GRN, repr(_recol))
_partial = pv.merge_highlight_records(
    [{"id": "b" * 32, "page": 0,
      "rects": [[10, 20, 100, 12], [10, 40, 100, 12]],
      "color": _YEL, "note": ""}],
    pv.records_from_rect_map({"0": [[10, 40, 100, 12]]}, color=_GRN))
check("a partial recolour keeps the untouched line yellow and splits "
      "off the new green one",
      len(_partial) == 2
      and _partial[0]["rects"] == [[10.0, 20.0, 100.0, 12.0]]
      and _partial[1]["color"] == _GRN, repr(_partial))
_mid = pv.merge_highlight_records(
    _base, pv.records_from_rect_map({"0": [[40, 20, 25, 12]]}, color=_GRN))
check("re-marking words INSIDE an existing mark cuts the old ink out "
      "of exactly that span — yellow either side, green between, never "
      "one ink composited over the other",
      len(_mid) == 2
      and _mid[0]["rects"] == [[10.0, 20.0, 30.0, 12.0],
                               [65.0, 20.0, 45.0, 12.0]]
      and _mid[1]["rects"] == [[40.0, 20.0, 25.0, 12.0]], repr(_mid))
check("a different-ink mark that shares no ink with the old one — "
      "further along the same line, or on the line below — leaves it "
      "untouched (the cut is same-line and x-bounded, not a bounding "
      "box)",
      pv.merge_highlight_records(
          _base, pv.records_from_rect_map(
              {"0": [[200, 20, 25, 12]]}, color=_GRN))[0] == _base[0]
      and pv.merge_highlight_records(
          _base, pv.records_from_rect_map(
              {"0": [[40, 40, 25, 12]]}, color=_GRN))[0] == _base[0])
check("a highlight on another page is never touched",
      len(pv.merge_highlight_records(
          [dict(_base[0], page=3)],
          pv.records_from_rect_map({"0": [[10, 20, 100, 12]]}))) == 2)
_ext = [{"id": "c" * 32, "page": 0, "rects": [[10, 20, 100, 12]],
         "color": _YEL, "note": "", "origin": "external"}]
_over_ext = pv.merge_highlight_records(
    _ext, pv.records_from_rect_map({"0": [[10, 20, 100, 12]]}, color=_GRN))
check("an ADOPTED external mark is never rewritten or dropped here — "
      "it may only leave through _bridge_hl_remove, which tombstones "
      "it (K-081), or the next foreign scan resurrects it",
      _over_ext[0] == _ext[0] and len(_over_ext) == 2, repr(_over_ext))
_txt = [{"id": "d" * 32, "page": 0, "rects": [[10, 20, 100, 12]],
         "color": "#000000", "note": "", "kind": "text", "text": "hi"}]
check("an outside-text box is not a highlight and is left alone",
      pv.merge_highlight_records(
          _txt, pv.records_from_rect_map({"0": [[10, 20, 100, 12]]}))[0]
      == _txt[0])
_src149 = _code_only116(_src("pdfjs_viewer.py"))
check("_bridge_hl_add mints through the merge, not a blind extend",
      "merge_highlight_records(self._highlights, records)" in _src149
      and "self._highlights.extend(records)" not in _src149)
check("...and validates the page's colour before it becomes a record",
      "validate_hex_color(data.get(" in _src149)
check("a mint that changes nothing saves nothing and toasts nothing",
      "if merged == self._highlights:" in _src149)
check("pdf_handler is NOT where any of this happens (K-081's "
      "self-healing stays scoped to external records)",
      "merge_rects" not in _src("pdf_handler.py")
      and "merge_highlight_records" not in _src("pdf_handler.py"))

section("K-149: JS and Python merge the same rects the same way")
_js_merge = _re100.search(r"function mergeRects\(rects\) \{[\s\S]*?\n\}\n",
                          _HTML116)
check("mergeRects extracted from the page source", _js_merge is not None)
if _node is None:
    print("  SKIP node not installed — JS/Python merge agreement "
          "unverified on this machine")
elif _js_merge is not None:
    # The last four cases straddle the two constants — a gap just
    # inside vs just outside the hairline, and a vertical overlap just
    # over vs just under half the shorter rect. Without those, a page
    # that merged with GAP=60 still agreed with Python on every case
    # and the check pinned nothing (caught by falsifying it).
    _CASES = [
        _BLINK_3_LINES, _BLINK_PARTIAL,
        [[10, 20, 50, 12], [60.5, 20, 40, 12]],
        [[10, 20, 50, 12], [62, 20, 40, 12]],
        [[10, 20, 50, 12], [300, 20, 50, 12]],
        [[10, 20, 100, 12], [10, 25, 100, 12]],
        [[10, 20, 100, 12], [10, 27, 100, 12]],
    ]
    _h = ('"use strict";\n' + _js_merge.group(0) + "\n"
          "console.log(JSON.stringify([\n"
          + "".join(f"  mergeRects({_json100.dumps(c)}),\n" for c in _CASES)
          + "]));\n")
    with _tmp100.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as _f3:
        _f3.write(_h)
        _mpath = _f3.name
    try:
        _mout = _sub100.run([_node, _mpath], capture_output=True,
                            text=True, timeout=30)
        _mgot = _json100.loads(_mout.stdout.strip() or "null")
    except Exception as _e:
        _mgot = f"node run failed: {_e}"
    _want = [pv.merge_rects(c) for c in _CASES]
    check("the page's mergeRects agrees with pdfjs_viewer.merge_rects on "
          "the measured Blink rects and on both sides of both merge "
          "constants — two implementations of one rule, so neither can "
          "drift silently",
          _mgot == _want, f"js={_mgot!r} py={_want!r}")

section("K-149: pdf.js markedContent parity")
# Tagged PDFs make renderTextLayer wrap glyph spans in
# <span class="markedContent"> groups. Upstream viewer.css zeroes them;
# this page shipped without that rule, leaving auto-sized wrappers on
# the selection-geometry path. Measured in Blink they lay out 0x0 (and
# selectionRectMap's sub-pixel guard drops them either way), so this is
# parity, not a bug fix — but a wrapper that ever did get a box would
# hand a phantom rect straight into a highlight.
check("the wrapper-zeroing rule is present",
      ".textLayer span.markedContent { top: 0; height: 0; }" in _HTML116)
check("pdf.js really does build those wrappers (the rule is not "
      "guarding a case that cannot happen)",
      'classList.add("markedContent")'
      in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "klausmate", "web", "pdfjs",
                           "pdf.min.js"), encoding="utf-8").read())

section("K-149: a non-yellow ink survives the bake (end to end)")
# The step that would otherwise silently fall back to #fadc50: mint ->
# annotations JSON -> bake -> the PDF's own /C array -> back to hex.
#
# Vendored pypdf needs typing_extensions, which this machine's python3.9
# does not ship — shim it BEFORE pdf_handler's guarded import so
# BAKE_AVAILABLE matches the Anki runtime (py3.13 has it) instead of
# silently SKIPPING the one check that proves the ink reaches the file.
# Same shim as test_klausmate.py's, deliberately local: it has to run
# before this file's first pdf_handler import, and pdfjs_viewer only
# ever imports pdf_handler lazily, inside functions.
try:
    import typing_extensions  # noqa: F401
except ImportError:
    import types as _ty149
    import typing as _typing149

    class _TESub149:
        def __getitem__(self, _i):
            return _typing149.Any

        def __call__(self, *a, **k):
            return _typing149.Any

    class _TEModule149(_ty149.ModuleType):
        def __getattr__(self, n):
            return getattr(_typing149, n, _TESub149())

    sys.modules["typing_extensions"] = _TEModule149("typing_extensions")

_ph149 = importlib.import_module("klausmate.pdf_handler")
import tempfile as _tf149
_uf149 = _tf149.mkdtemp(prefix="klaus_k149_")
if not _ph149.BAKE_AVAILABLE:
    print("  SKIP pypdf unavailable — bake round-trip unverified")
else:
    from pypdf import PdfReader as _R149, PdfWriter as _W149

    _N149 = "K149_Lecture"
    os.makedirs(os.path.join(_uf149, "pdfs"))
    _work149 = os.path.join(_uf149, "pdfs", _N149 + ".pdf")
    _w149 = _W149()
    _w149.add_blank_page(width=612, height=792)
    with open(_work149, "wb") as _fh149:
        _w149.write(_fh149)
    # Minted exactly as the bridge does: the page's chosen ink through
    # the validator, through records_from_rect_map.
    _green = pv.validate_hex_color(
        dict(_theme149.HIGHLIGHT_INKS)["green"])
    _recs149 = pv.records_from_rect_map(
        {"0": [[100, 172, 100, 20]]}, color=_green)
    _ph149.save_annotations(_uf149, _N149, _recs149)
    check("stored record carries the picked ink, not the default",
          _ph149.load_annotations(_uf149, _N149)[0]["color"] == _green
          and _green != pv.HIGHLIGHT_COLOR)
    check("bake succeeds", _ph149.bake_annotations(_uf149, _N149))
    _annots149 = [a.get_object()
                  for a in (_R149(_work149).pages[0].get("/Annots") or [])]
    _hl149 = [o for o in _annots149 if str(o.get("/Subtype")) == "/Highlight"]
    check("one baked highlight, not one per duplicated rect",
          len(_hl149) == 1, repr([str(o.get("/Subtype")) for o in _annots149]))
    check("the PDF's own /C reads back as the ink that was picked",
          _hl149 and _ph149._annot_color(_hl149[0]) == _green,
          repr(_hl149 and _hl149[0].get("/C")))
    # And a six-rect Blink selection bakes as three quads, not six.
    _ph149.save_annotations(
        _uf149, _N149,
        pv.records_from_rect_map({"0": _BLINK_3_LINES}, color=_green))
    check("re-bake succeeds", _ph149.bake_annotations(_uf149, _N149))
    _hl149b = [a.get_object()
               for a in (_R149(_work149).pages[0].get("/Annots") or [])
               if str(a.get_object().get("/Subtype")) == "/Highlight"]
    check("the doubled rects never reach the PDF: 3 quads (8 floats "
          "each), not 6",
          len(_hl149b) == 1 and len(_hl149b[0]["/QuadPoints"]) == 24,
          repr(len(_hl149b[0]["/QuadPoints"]) if _hl149b else None))
import shutil as _sh149
_sh149.rmtree(_uf149, ignore_errors=True)

# ── K-150: Preview-style in-place text boxes ─────────────────────────
_H150 = _src(os.path.join("web", "pdfjs_viewer.html"))

section("K-150: text ink and highlight ink are different problems")
# The orchestrator's question, answered by measurement rather than
# taste: SHARE THE ROW, FORK THE VALUES. A highlight is read THROUGH
# at 43% alpha over paper; text is read AS opaque glyphs on it. K-149's
# yellow #FADC50 is a fine wash and a 1.36:1 catastrophe as letters.
# So the two rows share their names, their hues, their swatch chrome
# and their mousedown cancel — and nothing else.
_TINKS = pv.text_inks()
_TNAMES = [n for n, _v in _TINKS]
check("the row is black plus every highlight ink, by NAME",
      _TNAMES == ["black"] + _INK_NAMES, repr(_TNAMES))
check("black leads and IS the legacy default, so the default swatch "
      "mints a record byte-identical to a pre-K-150 one (K-149's "
      "yellow-first rule, same reason)",
      _TINKS[0] == ("black", pv.TEXT_COLOR_DEFAULT))
check("not one text ink equals its highlight twin",
      all(dict(_TINKS)[n] != v for n, v in _theme149.HIGHLIGHT_INKS))
check("...because as glyphs the highlight inks are unreadable — every "
      "one of them is under 2.5:1 on white paper",
      all(pv._contrast_on_white(pv._hex_to_rgb(v)) < 2.5
          for _n, v in _theme149.HIGHLIGHT_INKS),
      repr([round(pv._contrast_on_white(pv._hex_to_rgb(v)), 2)
            for _n, v in _theme149.HIGHLIGHT_INKS]))
check("...and every text ink clears WCAG AA on the same paper",
      all(pv._contrast_on_white(pv._hex_to_rgb(v))
          >= pv.TEXT_INK_MIN_CONTRAST for _n, v in _TINKS),
      repr([(n, round(pv._contrast_on_white(pv._hex_to_rgb(v)), 2))
            for n, v in _TINKS]))
_hls150 = __import__("colorsys").rgb_to_hls
def _hue150(hexv):
    r, g, b = pv._hex_to_rgb(hexv)
    return _hls150(r / 255.0, g / 255.0, b / 255.0)[0]
check("the hue is preserved, so the yellow text ink still reads as "
      "the yellow highlighter's sibling rather than a new colour",
      all(abs(_hue150(dict(_TINKS)[n]) - _hue150(v)) < 0.01
          for n, v in _theme149.HIGHLIGHT_INKS),
      repr([(n, round(_hue150(v), 3), round(_hue150(dict(_TINKS)[n]), 3))
            for n, v in _theme149.HIGHLIGHT_INKS]))
check("DERIVED from theme.HIGHLIGHT_INKS, never a second hand-kept "
      "table — retune a hue there and the text ink follows it, still "
      "legible by construction",
      all(dict(_TINKS)[n] == pv.ink_for_text(v)
          for n, v in _theme149.HIGHLIGHT_INKS))
check("a malformed source colour degrades to black, never to a "
      "broken CSS value", pv.ink_for_text("nope") == pv.TEXT_COLOR_DEFAULT
      and pv.ink_for_text("") == pv.TEXT_COLOR_DEFAULT)
check("they reach the page as --tink-* beside K-149's --ink-*, "
      "IDENTICALLY in both modes — the value bakes into the PDF's /C "
      "and that file opens in Preview, where night mode does not exist",
      pv.text_ink_vars() in html and pv.text_ink_vars() in dark
      and all(f"--tink-{n}: {v};" in html for n, v in _TINKS))
check("so the template still spells no hex of its own",
      all(f"var(--tink-{n})" in _H150 for n, v in _TINKS)
      and not _re100.search(r"--tink-[a-z]+:", _H150))

section("K-150: one swatch row, two palettes")
_AB150 = _H150.split('<div id="annobar">', 1)[1].split(
    "</div>\n    </div>", 1)[0]
check("the row is the same swatches with a black one in front",
      _re100.findall(r'data-tink="([a-z]+)"', _AB150) == _TNAMES,
      repr(_re100.findall(r'data-tink="([a-z]+)"', _AB150)))
check("K-149's data-ink list is untouched — black carries no ink "
      "name, because there is no black highlighter",
      _re100.findall(r'data-ink="([a-z]+)"', _AB150) == _INK_NAMES
      and 'data-tink="black"' in _AB150 and 'data-ink="black"' not in _AB150)
check("text values are one rule per swatch, OUTRANKING the --ink rule "
      "(one more class) instead of replacing it, so K-149's block "
      "stays exactly as it was written",
      all(f'#abInks.textMode button.inkSw[data-tink="{n}"]' in _H150
          for n in _TNAMES)
      and all(f'#annobar button.inkSw[data-ink="{n}"]' in _H150
              for n in _INK_NAMES))
check("black shows only in text mode",
      '#annobar button.inkSw[data-tink="black"] { display: none; }' in _H150
      and '#abInks.textMode button.inkSw[data-tink="black"] { display: flex; }'
      in _H150)
check("the chosen text ink is read BACK out of its custom property, "
      "exactly as currentInk does for highlights",
      'getPropertyValue("--tink-" + name)' in _H150
      and "function currentTextInk()" in _H150)
check("the swatches live INSIDE #annobar in both modes, so picking a "
      "text colour inherits the bar's mousedown cancel and the caret "
      "never moves", 'id="abInks"' in _AB150)
check("the size stepper exists only while text mode is on — absent, "
      "not disabled",
      "#annobar.textMode #abTsz { display: flex" in _H150
      and 'id="abTszDown"' in _AB150 and 'id="abTszUp"' in _AB150)
check("arming the text tool OR opening a box is what turns the row "
      "over", 'state.tool === "text" || state.textEdit !== null' in _H150
      and "syncAnnobarMode();   /* K-150: the ink row follows the "
          "armed tool */" in _H150)

section("K-150: the editor outlives every layer rebuild")
# THE hazard: renderAnnotLayers destroys .hlLayer and .noteLayer and
# rebuilds them from scratch, from four call sites — renderPage,
# klausSetAnnotations, softRelayout's zoom settle and refreshPage's
# crisp swap — plus teardownPage on scroll-out. A contenteditable in
# either layer dies mid-keystroke, most cruelly on the push that
# follows its own save. So the box is a direct child of .page, and
# these pins hold that arrangement in place.
_RAL150 = _H150.split("function renderAnnotLayers(", 1)[1].split("\n}\n", 1)[0]
_TDP150 = _H150.split("function teardownPage(", 1)[1].split("\n}\n", 1)[0]
check("renderAnnotLayers still destroys exactly .hlLayer/.noteLayer "
      "on every pass — the reason the editor cannot live in either",
      'for (const cls of [".hlLayer", ".noteLayer"]) {' in _RAL150
      and "div.removeChild(old)" in _RAL150)
check("...and it is still reached from all four sites plus the "
      "teardown, so this is not a hazard that quietly went away",
      _H150.count("renderAnnotLayers(num, div)") == 3
      and "renderAnnotLayers(num, state.pageDivs[num - 1])" in _H150)
check("neither destroyer names the editor",
      "editLayer" not in _RAL150 and "editLayer" not in _TDP150
      and "textEdit" not in _TDP150)
check("the editor is appended to the PAGE div, beside the layers "
      "rather than inside one",
      "el.className = \"editLayer\";" in _H150
      and "div.appendChild(el);" in _H150)
check("the static twin is skipped while its own record is being "
      "edited, so nothing ghosts a glyph off under the live box",
      "if (state.textEdit && state.textEdit.id === rec.id) continue;"
      in _RAL150)
# FOUND IN AN OFFSCREEN RENDER, not by any source pin: the skip alone
# was not enough. Opening the editor on an existing record does not
# re-run renderAnnotLayers, so the twin drawn by the LAST pass went on
# sitting under the live box — the double-click screenshot showed the
# sentence twice, a glyph apart. Opening and closing must each force
# that page's layers through the skip.
_OTE150 = _H150.split("function openTextEdit(", 1)[1].split("\n}\n", 1)[0]
_CTE150 = _H150.split("function closeTextEdit(", 1)[1].split("\n}\n", 1)[0]
check("opening forces the skip to take effect NOW, or the twin the "
      "last pass drew stays under the live box",
      "repaintAnnotPage(page0);" in _OTE150)
check("closing puts it back — and passes on that only when a bridge "
      "call is already on its way, whose canonical push repaints "
      "anyway (repainting here would flash the pre-edit text)",
      "if (te && repaint !== false) repaintAnnotPage(te.page0);" in _CTE150
      and "closeTextEdit(!te.id);" in _H150)
check("every overlay pass RE-LANDS it (never rebuilds it), the "
      "contract positionPersistMarquee has kept since K-100",
      "if (state.textEdit && state.textEdit.page0 === num - 1) {"
      in _RAL150 and "positionTextEdit();" in _RAL150)
_SR150 = _H150.split("async function softRelayout(", 1)[1].split("\n}\n", 1)[0]
check("the zoom settle re-lands it unconditionally, beside the "
      "marquee — its page need not be in the rendered set",
      "positionPersistMarquee();" in _SR150 and "positionTextEdit();" in _SR150)
_RL150 = _H150.split("async function relayout(", 1)[1].split("\n}\n", 1)[0]
check("so does the panel-resize relayout, which tears every page down",
      "positionTextEdit();" in _RL150)
_TD150 = _H150.split("function teardown() {", 1)[1].split("\n}\n", 1)[0]
check("a new document drops the reference with the DOM it lived in",
      "state.textEdit = null;" in _TD150)
check("positionTextEdit only ever re-parents when something else took "
      "the box away — moving a focused node blurs it in Blink",
      "if (te.el.parentNode !== div) div.appendChild(te.el);" in _H150)

section("K-150: points and a transform, never px arithmetic")
check("the box is placed at page-point * scale and SCALED, so its "
      "wrap points are identical at 25% and at 400%",
      'te.el.style.left = te.x * s + "px";' in _H150
      and 'te.el.style.transform = "scale(" + s + ")";' in _H150)
check("its layout width and font size are POINTS — the transform "
      "carries them to the current zoom",
      'te.el.style.width = box[0] + "px";' in _H150
      and 'body.style.fontSize = size + "px";   // POINTS' in _H150)
check("the frame takes NO layout space (an outline, and a grip offset "
      "above it), so the glyphs sit exactly where the committed "
      "record draws them and nothing shifts on commit",
      "outline: 1px solid var(--accent); outline-offset: 3px;" in _H150
      and "padding: 0; border: none; background: transparent;" in _H150
      and "top: -11px;" in _H150)
check("the page carries textBoxSize with the SAME constants as "
      "text_box_size, so the box you type in is the box you get "
      "(mergeRects' two-implementations arrangement)",
      "function textBoxSize(text, size, rows)" in _H150
      and "* 0.6 + 8, 60), 480)" in _H150
      and "* 1.35 + 6, size * 1.5), 720)" in _H150)
check("and sanitizeEditText mirroring sanitize_text, on the same cap",
      "function sanitizeEditText(value)" in _H150
      and "MAX_TEXT_CHARS = 4000" in _H150 and pv.MAX_TEXT_CHARS == 4000)

section("K-150: the commit is the only bridge call")
check("placement opens the editor and posts nothing; the record is "
      "minted at COMMIT, from text that did not exist at click time",
      "function commitTextEdit()" in _H150
      and 'postB64("text-add", {' in _H150
      and _H150.find("openTextEdit(hit.page0")
      < _H150.find("function commitTextEdit()"))
check("an existing box re-commits through text-update",
      'postB64("text-update", {' in _H150)
check("emptying a box routes to hl-remove rather than forking a "
      "delete into the update handler — that path already tombstones "
      "an adopted record (K-081)",
      'if (!text) { postB64("hl-remove", { id: te.id }); return; }' in _H150)
check("an empty NEW box mints nothing at all",
      "if (!te.id) {\n    if (!text) return;" in _H150)
check("blur commits (clicking away, Preview's gesture) and so does "
      "Escape, which stops propagating so it cannot also clear a tool",
      'body.addEventListener("blur"' in _H150
      and 'if (ev.key === "Escape"' in _H150
      and "ev.stopPropagation();\n      commitTextEdit();" in _H150)
check("dragging is by the GRIP only and preventDefaults, so the caret "
      "and the un-committed text survive the move",
      "function startTextDrag(ev)" in _H150
      and "grip.addEventListener(\"mousedown\", startTextDrag);" in _H150
      and "ev.preventDefault();\n  ev.stopPropagation();\n  state.textDrag ="
      in _H150)
check("double-clicking an existing box re-opens it, gated OFF the "
      "Cmd/Ctrl slide-copy gesture so the two never overlap",
      "if (ev.metaKey || ev.ctrlKey || state.textEdit) return;" in _H150
      and _H150.find("if (!(ev.metaKey || ev.ctrlKey)) return;")
      < _H150.find("if (ev.metaKey || ev.ctrlKey || state.textEdit) return;"))
check("parse_bridge routes text-update",
      pv.parse_bridge("klausmate_pdfjs:text-update:e30=")
      == ("text-update", "e30="))

section("K-150: the body is untrusted input now")
check("newlines survive, a tab becomes one space, control characters "
      "go", pv.sanitize_text("a\r\nb\tc\x00d\x1f") == "a\nb cd",
      repr(pv.sanitize_text("a\r\nb\tc\x00d\x1f")))
check("bounded, stripped, and non-strings are empty",
      len(pv.sanitize_text("x" * 99_999)) == pv.MAX_TEXT_CHARS
      and pv.sanitize_text("  hi  ") == "hi"
      and pv.sanitize_text(None) == "" and pv.sanitize_text(12) == "")
check("size clamps into a sane range; junk falls back to 12pt",
      pv.validate_text_size(18) == 18.0
      and pv.validate_text_size(1) == pv.TEXT_SIZE_MIN
      and pv.validate_text_size(1e9) == pv.TEXT_SIZE_MAX
      and pv.validate_text_size(True) == pv.TEXT_SIZE_DEFAULT
      and pv.validate_text_size("18") == pv.TEXT_SIZE_DEFAULT
      and pv.validate_text_size(float("nan")) == pv.TEXT_SIZE_DEFAULT)
check("the ink goes through K-149's validator, defaulting to BLACK "
      "here rather than to highlight yellow",
      pv.validate_hex_color("#137BBB", pv.TEXT_COLOR_DEFAULT) == "#137bbb"
      and pv.validate_hex_color("javascript:x", pv.TEXT_COLOR_DEFAULT)
      == pv.TEXT_COLOR_DEFAULT)

section("K-150: a box is sized to hold what was typed in it")
check("a long single line WRAPS into rows — it used to get a one-line "
      "box, and both .hltext and the baked FreeText CLIP to it",
      pv.text_box_size("x" * 400)[1] > pv.text_box_size("x" * 40)[1])
check("the page's measured row count raises the estimate and never "
      "lowers it (the browser knows its own font metrics; this "
      "formula only approximates them)",
      pv.text_box_size("hi", 12.0, 9)[1] > pv.text_box_size("hi", 12.0)[1]
      and pv.text_box_size("hi", 12.0, 1) == pv.text_box_size("hi", 12.0))
check("an untrusted row count degrades to the formula alone",
      pv.text_box_size("hi", 12.0, -5) == pv.text_box_size("hi", 12.0)
      and pv.text_box_size("hi", 12.0, 10 ** 9)[1] == 720.0)
check("the commit sends its measured rows",
      "rows: rows," in _H150 and "te.body.scrollHeight" in _H150)
_KEYS150 = {"id", "kind", "page", "rects", "text", "note", "color", "size"}
check("a picked ink and size are written EXPLICITLY, and the KEY SET "
      "is still closed: the editor's frame is chrome, not record "
      "state (Preview shows a frame only while a box is selected), so "
      "there is no border flag to keep in step with the bake",
      set(pv.make_text_record(0, 0, 0, "x", color="#137bbb", size=18.0))
      == _KEYS150)
_PH150 = _src("pdf_handler.py")
check("...and the bake still passes None for border and background, "
      "so the box on screen and the baked PDF agree by construction",
      "border_color=None," in _PH150 and "background_color=None," in _PH150)

section("K-150: re-editing an existing box")
_base150 = pv.make_text_record(1, 10.0, 20.0, "hello")
_other150 = {"id": "other", "page": 1, "rects": [[0.0, 0.0, 1.0, 1.0]],
             "color": "#fadc50", "note": ""}
_recs150 = [_other150, _base150]
_out150, _ch150 = pv.apply_text_update(
    _recs150, {"id": _base150["id"], "text": "hello there",
               "color": "#137BBB", "size": 18, "x": 30, "y": 40})
check("one edit moves text, ink, size and anchor together",
      _ch150 and _out150[1]["text"] == "hello there"
      and _out150[1]["color"] == "#137bbb" and _out150[1]["size"] == 18.0
      and _out150[1]["rects"][0][:2] == [30.0, 40.0], repr(_out150[1]))
check("the box is re-measured for the new text AND the new size",
      _out150[1]["rects"][0][2:]
      == list(pv.text_box_size("hello there", 18.0)))
check("every other record is untouched and the input list is never "
      "mutated in place",
      _out150[0] is _other150 and _recs150[1] == _base150
      and _out150 is not _recs150)
check("an unknown id, a non-text record, an empty body and junk all "
      "change nothing",
      pv.apply_text_update(_recs150, {"id": "nope", "text": "x"})[1] is False
      and pv.apply_text_update(_recs150, {"id": "other", "text": "x"})[1]
      is False
      and pv.apply_text_update(_recs150,
                               {"id": _base150["id"], "text": "  "})[1]
      is False
      and pv.apply_text_update(_recs150, "nope")[1] is False
      and pv.apply_text_update(_recs150, {"text": "x"})[1] is False
      and pv.apply_text_update(None, {"id": "x", "text": "y"})[1] is False)
check("re-committing an untouched box reports NO change, so clicking "
      "away costs no save, no bake and no push",
      pv.apply_text_update(
          _recs150, {"id": _base150["id"], "text": "hello",
                     "color": _base150["color"],
                     "size": _base150["size"]})[1] is False)
check("origin survives an edit — an adopted box must stay adopted or "
      "K-081 tombstoning stops working on it",
      pv.apply_text_update([dict(_base150, origin="external")],
                           {"id": _base150["id"], "text": "edited"})[0][0]
      .get("origin") == "external")
check("a junk colour/size falls back instead of landing in the JSON",
      pv.apply_text_update(
          _recs150, {"id": _base150["id"], "text": "hi",
                     "color": "rgb(1,2,3)", "size": "huge"})[0][1]
      == dict(_base150, text="hi",
              rects=[[10.0, 20.0]
                     + list(pv.text_box_size("hi", pv.TEXT_SIZE_DEFAULT))]))
check("a junk or absent anchor keeps the record's own",
      pv.apply_text_update(
          _recs150, {"id": _base150["id"], "text": "hi",
                     "x": float("inf"), "y": "nope"})[0][1]["rects"][0][:2]
      == [10.0, 20.0])
check("an absurd anchor clamps to the PDF spec's 14,400 pt",
      pv.apply_text_update(
          _recs150, {"id": _base150["id"], "text": "hi",
                     "x": 1e9, "y": -5})[0][1]["rects"][0][:2]
      == [pv.MAX_PAGE_PT, 0.0])
check("the updated record still validates round-trip through storage",
      _ph149._validate_highlight(_out150[1]) == _out150[1])

section("K-159: the annotation tools stay armed")
# "When you're adding text to a PDF, I don't want it to automatically
# toggle out of add-text mode. I want to stay in that mode" — and the
# same for Highlight. Every pin here is SCOPED to its handler: the
# check this replaces asked for `"setTool(null);" in _HTML116`, which
# the Escape handler's own copy satisfied, so it could not have failed
# whatever the tools did (scripts/AUDIT.md's recurring shape).
_H159 = _src(os.path.join("web", "pdfjs_viewer.html"))
_HL_MOUSEUP159 = _H159.split(
    'if (state.tool === "hl" && selectionRectMap()) {', 1)[1].split(
    "}, 0);", 1)[0]
_TEXT_CLICK159 = _H159.split(
    'if (state.tool !== "text" || ev.button !== 0) return;', 1)[1].split(
    "\n});", 1)[0]
_ABHL159 = _H159.split('("abHl").addEventListener("click", () => {', 1)[1] \
    .split("});", 1)[0]
_SWATCH159 = _H159.split('if (!sw.dataset.ink) return;', 1)[1].split(
    "\n  });", 1)[0]
check("a highlight minted from a selection release leaves the tool "
      "ARMED — the next drag marks again with no second click",
      "addHighlightFromSelection();" in _HL_MOUSEUP159
      and "setTool(null)" not in _HL_MOUSEUP159, _HL_MOUSEUP159)
check("arming Highlight over a live selection marks it and stays "
      "armed", "addHighlightFromSelection();" in _ABHL159
      and "setTool(null)" not in _ABHL159, _ABHL159)
check("so does picking an ink over a live selection",
      "addHighlightFromSelection();" in _SWATCH159
      and "setTool(null)" not in _SWATCH159, _SWATCH159)
check("placing a text box leaves Add Text armed for the next one",
      "openTextEdit(" in _TEXT_CLICK159
      and "setTool(null)" not in _TEXT_CLICK159, _TEXT_CLICK159)
# What DISARMS, now that nothing else does.
check("Escape disarms whichever tool is armed",
      "if (state.tool) setTool(null);" in _H159)
check("...and the toolbar button disarms by toggling — setTool's one "
      "line is what makes a second click turn the tool off",
      "state.tool = state.tool === tool ? null : tool;" in _H159)
# The regression a sticky text tool would otherwise introduce, twice.
check("the open box swallows CLICK as well as mousedown, or a click "
      "inside your own box would commit it and open an empty one on "
      "top (stopping mousedown does not stop the click that follows)",
      'el.addEventListener("click", (ev) => ev.stopPropagation());'
      in _H159)
check("an armed click ON an existing box re-edits it instead of "
      "dropping an empty one over it — the dblclick editor is "
      "unreachable while armed, so the armed click has to do that job",
      "const rec = textRecordAt(hit.page0, hit.xPt, hit.yPt);"
      in _TEXT_CLICK159
      and "openTextEdit(rec.page | 0, rec.rects[0][0], rec.rects[0][1], rec)"
      in _TEXT_CLICK159)
check("the dblclick editor still bails while a box is open, which is "
      "why the armed path above is the one that reaches an existing "
      "record", "if (ev.metaKey || ev.ctrlKey || state.textEdit) return;"
      in _H159)

section("K-159: sticky highlighting cannot re-stack the paint")
# K-149 made Highlight one-shot as "cause 2" of the double-highlight
# bug, so un-doing that needs PROOF, not an argument. The load-bearing
# half of K-149 was never the one-shot: it was the merge. merge_rects
# stops ONE drag minting two coincident rects (Blink returns a fully
# covered span's border box AND its text quad); merge_highlight_records
# stops the SECOND drag stacking a second record on the first. Sticky
# mode only adds more mints, so this drags the same sentence three
# times, through the exact mint path _bridge_hl_add uses, on the RAW
# six-rect Blink geometry (the page merges too, but JS is never
# trusted, so the unmerged payload is the stricter case).
_hl159 = []
for _pass159 in range(3):
    _hl159 = pv.merge_highlight_records(
        _hl159, pv.records_from_rect_map({"0": _BLINK_3_LINES},
                                         color=_YEL))
check("three drags over the same sentence leave ONE record with ONE "
      "rect per line — no second layer of 43% paint to composite with",
      len(_hl159) == 1 and _hl159[0]["rects"] == _QUADS_3_LINES,
      repr(_hl159))
_once159 = pv.merge_highlight_records(
    [], pv.records_from_rect_map({"0": _BLINK_3_LINES}, color=_YEL))
check("...and passes two and three changed nothing at all, so "
      "_bridge_hl_add's `merged == self._highlights` returns before any "
      "save, bake or push",
      pv.merge_highlight_records(
          _once159,
          pv.records_from_rect_map({"0": _BLINK_3_LINES}, color=_YEL))
      == _once159)
check("a drag that only PARTLY overlaps still grows the one record "
      "rather than adding a second — sticky mode's realistic case, "
      "since a second drag never lands on the same pixels",
      len(pv.merge_highlight_records(
          _once159,
          pv.records_from_rect_map(
              {"0": [[21, 19.5, 200, 18.5]]}, color=_YEL))) == 1)
_cut159 = pv.merge_highlight_records(
    _once159,
    pv.records_from_rect_map({"0": [[60, 19.5, 25, 18.5]]}, color=_GRN))
check("and a DIFFERENT ink still CUTS rather than composites — "
      "K-149's yellow/green/yellow, unchanged by stickiness: yellow "
      "keeps a piece either side of the green on line one and both "
      "lines below untouched, green is one rect, nothing overlaps",
      len(_cut159) == 2 and _cut159[1]["color"] == _GRN
      and _cut159[1]["rects"] == [[60.0, 19.5, 25.0, 18.5]]
      and _cut159[0]["rects"] == [[21.0, 19.5, 39.0, 18.5],
                                  [85.0, 19.5, 46.28, 18.5],
                                  [21.0, 43.5, 120.09, 18.5],
                                  [21.0, 67.5, 104.95, 18.5]],
      repr(_cut159))


# The bridging drag itself — the case the property walk turned up, and
# the reason step 3 folds EVERY touching record rather than the first.
# Marked on the live page as three drags of one line (left third, right
# third, then across the gap): the old rule left two records whose
# rects overlapped by 26pt, painted twice at 43%.
_LEFT159 = pv.records_from_rect_map({"0": [[72.97, 61.93, 83.36, 14.02]]},
                                    color=_YEL)
_RIGHT159 = pv.records_from_rect_map({"0": [[260.39, 61.93, 70.7, 14.02]]},
                                     color=_YEL)
_BRIDGE159 = pv.records_from_rect_map({"0": [[125.65, 61.93, 160.76, 14.02]]},
                                      color=_YEL)
_pair159 = pv.merge_highlight_records(
    pv.merge_highlight_records([], _LEFT159), _RIGHT159)
check("two separated marks on one line stay two records — they share "
      "no ink, so there is nothing to fold",
      len(_pair159) == 2)
_bridged159 = pv.merge_highlight_records(_pair159, _BRIDGE159)
check("a drag ACROSS the gap collapses BOTH into one record covering "
      "the whole span — folding into only the first (pre-K-159) left "
      "the second overlapping it by 26pt at 43% on 43%",
      len(_bridged159) == 1 and len(_bridged159[0]["rects"]) == 1
      and all(abs(a - b) < 0.01 for a, b in zip(
          _bridged159[0]["rects"][0], [72.97, 61.93, 258.12, 14.02])),
      repr(_bridged159))
check("...and the surviving record is the FIRST host, id intact — "
      "K-149's rule for one host, unchanged for several",
      _bridged159[0]["id"] == _pair159[0]["id"])
check("a note on an ABSORBED record is carried onto the survivor, not "
      "dropped with it (`.get` so a dropped note reports one honest "
      "failure instead of a KeyError that aborts the file)",
      pv.merge_highlight_records(
          [_pair159[0], dict(_pair159[1], note="from the right mark")],
          _BRIDGE159)[0].get("note") == "from the right mark")
check("...and the host's own note wins when both carry one",
      pv.merge_highlight_records(
          [dict(_pair159[0], note="host"),
           dict(_pair159[1], note="absorbed")],
          _BRIDGE159)[0].get("note") == "host")


def _same_ink_overlap(records):
    """Any two SAME-INK rects that overlap anywhere in *records*.

    This is the paint invariant itself, not a proxy: two overlapping
    rects in one ink are exactly what composites 43% + 43% into the
    67.5% "double-highlighted" look, whether they sit in one record or
    in two.
    """
    flat = []
    for rec in records:
        ink = pv.validate_hex_color(rec.get("color"))
        for r in rec.get("rects") or []:
            flat.append((ink, r))
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            (ink1, a), (ink2, b) = flat[i], flat[j]
            if ink1 != ink2:
                continue
            if (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
                    and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]):
                return (a, b)
    return None


# The fixed sequence above proves the reported gesture. This proves the
# RULE, over 400 random sticky sessions: whatever a user drags, in
# whatever ink, in whatever order, no two same-ink rects ever end up
# overlapping. A random walk found nothing; that is the claim.
import random as _rnd159

_rng159 = _rnd159.Random(159)
_INKS159 = [v for _n, v in _theme149.HIGHLIGHT_INKS]
_worst159 = None
for _trial in range(400):
    _recs159: list = []
    for _drag in range(6):
        _x = _rng159.randrange(0, 160)
        _y = _rng159.choice([20, 24, 44, 68])
        _w = _rng159.randrange(10, 120)
        _rects159 = [[_x, _y, _w, 18.5]]
        if _rng159.random() < 0.5:      # Blink's doubled border box
            _rects159.append([_x, _y + 1.5, _w, 16])
        _recs159 = pv.merge_highlight_records(
            _recs159,
            pv.records_from_rect_map(
                {"0": _rects159}, color=_rng159.choice(_INKS159)))
        _bad159 = _same_ink_overlap(_recs159)
        if _bad159 and _worst159 is None:
            _worst159 = (_trial, _drag, _bad159)
check("400 random sticky sessions of six drags each: not one pair of "
      "same-ink rects ever overlaps",
      _worst159 is None, repr(_worst159))
# The property check has to be able to FAIL, or it pins nothing: the
# pre-K-149 behaviour was a blind append, and that is what it caught.
check("...and that walk really would have caught the old blind "
      "append (the check is not vacuously true)",
      _same_ink_overlap(
          [dict(_base[0]),
           dict(_base[0], id="z" * 32)]) is not None)

raise SystemExit(report())
