"""Headless tests for the pdf.js viewer foundation (K-096).

Covers the aqt-free helpers (renderer flag, base64 chunking, HTML
substitution) plus the viewer HTML's structural contract. The webview
itself can only be verified live — see the K-095 umbrella card.
"""
import base64
import importlib
import os
import subprocess
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
pv = importlib.import_module("klausmate.pdfjs_viewer")

section("PDF reader 2/5: the whole-file feed is gone")
check("chunk_b64 is gone", not hasattr(pv, "chunk_b64"))
check("CHUNK_CHARS is gone", not hasattr(pv, "CHUNK_CHARS"))

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
check("template spells __ADDON__ only at its three real sites "
      "(pdf.min.js, pdfjs_pure.js, the worker)",
      _TPL.count("__ADDON__") == 3)
check("so the rendered page carries the palette exactly once",
      html.count("--bg: ") == 1 and dark.count("--bg: ") == 1)
for fn in ("klausPdfOpen", "klausPdfError",
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

section("PDF reader 2/5: time to first page is logged")
check("the page posts firstpage:<ms> once page 1 has rendered",
      'if (num === 1 && state.t0 !== null) {' in html
      and 'post("firstpage:" + Math.round(performance.now() - state.t0));'
      in html)
import contextlib as _ctxl
import io as _io
_fp_stand = type("_FpStand", (), {})()
_fp_stand._name = "lecture.pdf"
_fp_out = _io.StringIO()
with _ctxl.redirect_stdout(_fp_out):
    pv.PdfJsViewer._bridge_firstpage(_fp_stand, "412")
check("Python prints the timing line",
      _fp_out.getvalue().strip()
      == "[klausmate] pdfjs first page lecture.pdf 412 ms")

section("PDF reader 2/5: piece loader (pdf.js asks Python for byte ranges)")
import builtins as _bi
import tempfile as _tf

_ps = importlib.import_module("klausmate.pdf_source")
_ph = importlib.import_module("klausmate.pdf_handler")
_tmp8 = _tf.mkdtemp()
_pdf8 = os.path.join(_tmp8, "lecture.pdf")
_w8 = _ph.pypdf.PdfWriter()
_w8.add_blank_page(width=200, height=200)
with open(_pdf8, "wb") as _f8:
    _w8.write(_f8)
    _f8.write(b"\n%" + b"k" * 400_000 + b"\n")   # comment padding past 256 KB
_data8 = open(_pdf8, "rb").read()
check("fixture is a real PDF larger than the first chunk",
      _data8.startswith(b"%PDF") and len(_data8) > _ps.FIRST_CHUNK)

check("parse_bridge routes range",
      pv.parse_bridge("klausmate_pdfjs:range:3:0:262144") == ("range", "3:0:262144"))
check("the viewer has a range handler", hasattr(pv.PdfJsViewer, "_bridge_range"))

_src8 = _ps.DocSource(_pdf8)
_r8 = pv.handle_range("1:0:262144", _src8, 1)
check("handle_range returns base64 of the first 256 KB",
      _b64.b64decode(_r8["b64"]) == _data8[:262144])
_r8 = pv.handle_range("1:1000:5000", _src8, 1)
check("...and of a range in the middle",
      _b64.b64decode(_r8["b64"]) == _data8[1000:5000])
check("an old generation is refused",
      pv.handle_range("0:0:10", _src8, 1) == {"refused": True})
for _bad in ("", "1", "1:0", "1:0:10:5", "1:-1:10", "1:0:-10", "1:0.5:10",
             "1:x:10", "True:0:10", "1:0:1e3", " 1:0:10", "1:²:10",
             "1::10", None, 7):
    check("malformed payload %r is refused" % (_bad,),
          pv.handle_range(_bad, _src8, 1) == {"refused": True})
check("no source (load failed) answers stale",
      pv.handle_range("1:0:10", None, 1) == {"stale": True})
_new8 = os.path.join(_tmp8, "new.pdf")
with open(_new8, "wb") as _f8:
    _f8.write(_data8 + b"%changed\n")
os.replace(_new8, _pdf8)
check("after the file is replaced the reply is stale",
      pv.handle_range("1:0:10", _src8, 1) == {"stale": True})
_data8 = open(_pdf8, "rb").read()


class _CountingFile:
    def __init__(self, f, box):
        self._f, self._box = f, box

    def read(self, n=-1):
        out = self._f.read(n)
        self._box[0] += len(out)
        return out

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._f.close()


_real_open8 = _bi.open


def _counting(box):
    def _open(*a, **k):
        return _CountingFile(_real_open8(*a, **k), box)
    return _open


_src8 = _ps.DocSource(_pdf8)
_box8 = [0]
_bi.open = _counting(_box8)
try:
    _len8, _first8 = pv.first_chunk(_src8)
finally:
    _bi.open = _real_open8
check("first_chunk returns the source's length", _len8 == len(_data8))
check("first_chunk returns base64 of the first 256 KB, read through the "
      "same source as every range",
      _b64.b64decode(_first8) == _data8[:_ps.FIRST_CHUNK])
check("first_chunk reads no more than FIRST_CHUNK bytes",
      0 < _box8[0] <= _ps.FIRST_CHUNK)


class _FakeWeb8:
    def __init__(self):
        self.js = []

    def eval(self, js):
        self.js.append(js)

    def setZoomFactor(self, _z):
        pass


_read8 = os.path.join(_tmp8, "reading")   # never the real user_files
pv._reading_dir = lambda: _read8


def _viewer8():
    v = pv.PdfJsViewer.__new__(pv.PdfJsViewer)   # no Qt construction
    v._web = _FakeWeb8()
    v._page_loaded = True
    v._gen = 0
    v._source = None
    v._path = None
    v._name = None
    v._scroll_pos = 0
    v._hold_scroll = False
    v._highlights = []
    return v


os.makedirs(_read8, exist_ok=True)
_leftover8 = os.path.join(_read8, "leftover.pdf")
open(_leftover8, "wb").close()
pv._SWEPT = False
_v8 = _viewer8()
_box8 = [0]
_bi.open = _counting(_box8)
try:
    _v8.load_path(_pdf8, "lecture.pdf")
finally:
    _bi.open = _real_open8
check("load_path reads only the first chunk on the main thread",
      0 < _box8[0] <= _ps.FIRST_CHUNK)
_open8 = [j for j in _v8._web.js if "klausPdfOpen(" in j]
check("load_path calls klausPdfOpen(gen, length, firstB64, name, keepView) once",
      _open8 == ["window.klausPdfOpen && window.klausPdfOpen(1, %d, %s, "
                 "\"lecture.pdf\", false);" % (len(_data8), '"' + _first8 + '"')])
check("no whole-file feed is sent", not any("klausPdfChunk" in j
                                            for j in _v8._web.js))
check("load_path bumps the generation and holds a DocSource",
      _v8._gen == 1 and _v8._source is not None
      and _v8._source.length == len(_data8))
_link8 = _v8._source.read_path
check("the source reads a hard-link snapshot under <user files>/reading",
      os.path.dirname(_link8) == _read8 and os.path.samefile(_link8, _pdf8))
check("the first load sweeps leftover snapshots, keeping its own",
      not os.path.exists(_leftover8) and os.path.exists(_link8))
_rep8 = _v8._on_bridge("klausmate_pdfjs:range:1:0:10")
check("_on_bridge RETURNS the range reply (Anki hands it to the JS callback)",
      isinstance(_rep8, dict) and _b64.b64decode(_rep8["b64"]) == _data8[:10])
check("other bridge commands keep the old (True, None) reply",
      _v8._on_bridge("klausmate_pdfjs:scroll:5") == (True, None)
      and _v8._scroll_pos == 5)
_bake8 = os.path.join(_tmp8, "bake.pdf")
with open(_bake8, "wb") as _f8:
    _f8.write(_data8 + b"%baked\n")
os.replace(_bake8, _pdf8)                     # what Klaus's own bake does
_rep8 = _v8._on_bridge("klausmate_pdfjs:range:1:100:200")
check("a bake (os.replace) does not make the open document stale (R20)",
      "b64" in _rep8 and _b64.b64decode(_rep8["b64"]) == _data8[100:200])
_data8 = open(_pdf8, "rb").read()

_v8._web.js.clear()
_out8 = _io.StringIO()
with _ctxl.redirect_stdout(_out8):
    _v8.load_path(os.path.join(_tmp8, "missing.pdf"), "missing.pdf")
check("a missing file at load does not raise and opens nothing",
      not any("klausPdfOpen(" in j for j in _v8._web.js)
      and "[klausmate] pdfjs read failed" in _out8.getvalue())
check("...the previous snapshot is closed", not os.path.exists(_link8))
check("...the page tears the old document down and shows the error",
      any(j.startswith("window.klausPdfClose && window.klausPdfClose(2, ")
          and "Could not open this PDF." in j for j in _v8._web.js))
check("...and the generation moved on, so the old page's ranges "
      "are refused", _v8._gen == 2
      and _v8._on_bridge("klausmate_pdfjs:range:1:0:10") == {"refused": True})

_v8._web.js.clear()
_max8 = pv.MAX_PDF_MB
pv.MAX_PDF_MB = 0
try:
    _v8.load_path(_pdf8, "lecture.pdf")
finally:
    pv.MAX_PDF_MB = _max8
check("MAX_PDF_MB still applies before anything is opened",
      not any("klausPdfOpen(" in j for j in _v8._web.js)
      and any(j.startswith("window.klausPdfClose && window.klausPdfClose(3, ")
              and "too large" in j for j in _v8._web.js))
check("...and leaves no snapshot behind", os.listdir(_read8) == [])

# stale: the page aborts its transport and posts stale:<gen>
_v8 = _viewer8()
_v8.load_path(_pdf8, "lecture.pdf")
_stale8 = []
_v8.on_stale = lambda: _stale8.append(1)


class _NowTimer:
    @staticmethod
    def singleShot(_ms, fn):
        fn()


_qt8 = pv.QTimer
pv.QTimer = _NowTimer
try:
    _v8._on_bridge("klausmate_pdfjs:stale:0")
    check("a stale report for an old generation is ignored", _stale8 == [])
    _v8._on_bridge("klausmate_pdfjs:stale:1")
    check("a stale report for the current generation calls on_stale",
          _stale8 == [1])
finally:
    pv.QTimer = _qt8
_v8._scroll_pos = 900
_old8 = _v8._source.read_path
_v8._web.js.clear()
pv.PdfJsViewer._reload_current(_v8)
check("the default on_stale reloads the current document, keeping the view",
      _v8._gen == 2 and any('klausPdfOpen(2, ' in j
                            and '"lecture.pdf", true);' in j for j in _v8._web.js))
check("...and closes the previous snapshot", not os.path.exists(_old8))
check("a stale reload keeps the scroll position", _v8._scroll_pos == 900)
_v8._on_bridge("klausmate_pdfjs:scroll:0")   # the teardown's scroll to the top
check("...through the teardown's scroll-to-top report", _v8._scroll_pos == 900)
_v8._web.js.clear()
_v8._on_bridge("klausmate_pdfjs:ready")
check("...and ready scrolls back there",
      any("klausScrollTo(900)" in j for j in _v8._web.js))
_v8._on_bridge("klausmate_pdfjs:scroll:40")
check("after ready, scroll reports count again", _v8._scroll_pos == 40)

_v8._web.js.clear()
_cur8 = _v8._source.read_path
_v8.clear_document()
check("clear_document bumps the generation and closes the snapshot",
      _v8._gen == 3 and _v8._source is None and not os.path.exists(_cur8))
check("...and tears the page's document down",
      "window.klausPdfClose && window.klausPdfClose(3);" in _v8._web.js)

_v8.load_path(_pdf8, "lecture.pdf")
_cur8 = _v8._source.read_path
_v8.cleanup = pv.PdfJsViewer.cleanup.__get__(_v8)
_v8._web = None
_v8.cleanup()
check("cleanup closes the snapshot", not os.path.exists(_cur8)
      and _v8._source is None)

_FEED8 = html.split("/* ==== feed", 1)[1].split("async function availWidth", 1)[0]
check("the page builds a PDFDataRangeTransport",
      "extends pdfjsLib.PDFDataRangeTransport" in _FEED8)
check("getDocument is range-loaded with the agreed options",
      "range: transport," in _FEED8
      and "disableAutoFetch: true," in _FEED8
      and "disableStream: true," in _FEED8
      and "rangeChunkSize: 262144," in _FEED8
      and "getDocument({ data" not in html)
check("ranges are fetched over the bridge with a callback",
      'pycmd("klausmate_pdfjs:range:" + gen + ":" + begin + ":" + end, resolve)'
      in _FEED8)
check("a stale reply aborts the transport and posts stale:<gen>",
      'this.abort();' in _FEED8 and 'post("stale:" + this.gen);' in _FEED8)
check("one onDataRange per request, at the begin pdf.js asked for",
      _FEED8.count("this.onDataRange(") == 1
      and "this.onDataRange(begin, chunk);" in _FEED8)
_TD8 = html.split("function teardown() {", 1)[1].split("\n}\n", 1)[0]
check("teardown aborts the transport and destroys the document",
      "transport.abort();" in _TD8 and "await task.destroy();" in _TD8)
check("the whole-file feed is gone from the page",
      "b64parts" not in html and "klausPdfChunk" not in html
      and "klausPdfLoad" not in html)
check("first-page timing is measured from klausPdfOpen",
      "window.klausPdfOpen = function (gen, length, firstB64, _name, keepView) {\n"
      "  state.t0 = performance.now();" in html)
check("a reload keeps a user zoom instead of refitting",
      "if (!(state.keepZoom && state.userZoomed))" in html)
_OD8 = html.split("async function openDocument(", 1)[1].split("\n}\n", 1)[0]
check("openDocument re-checks the generation after building placeholders",
      "await buildPlaceholders();\n  if (gen !== state.gen) return;" in _OD8)
_PC8 = html.split("window.klausPdfClose = function", 1)[1].split("\n};\n", 1)[0]
check("klausPdfClose tears the document down, then shows any error where "
      "#pages was", "state.gen = gen;" in _PC8 and "teardown()" in _PC8
      and "window.klausPdfError(text)" in _PC8)

section("live selection reported over the bridge (K-196 task 10)")
_sel_payload = _b64.b64encode(b'{"text": "abc"}').decode()
check("parse_bridge routes sel",
      pv.parse_bridge("klausmate_pdfjs:sel:" + _sel_payload)
      == ("sel", _sel_payload))
check("decode_b64_json decodes the selection payload",
      pv.decode_b64_json(_sel_payload) == {"text": "abc"})
check("the page listens for selectionchange",
      'addEventListener("selectionchange"' in html)
check("...and posts it as a debounced sel: bridge message",
      'postB64("sel"' in html)


class _SelStand:
    """A stand-in for PdfJsViewer: _bridge_sel only reads/calls
    self.on_selection, so the unbound method runs on anything that has
    one — no Qt construction needed."""


_sel_seen = []
_sel_stand = _SelStand()
_sel_stand.on_selection = _sel_seen.append
pv.PdfJsViewer._bridge_sel(_sel_stand, _sel_payload)
check("_bridge_sel decodes the payload and forwards the text to "
      "on_selection", _sel_seen == ["abc"])

_sel_stand_unset = _SelStand()
_sel_stand_unset.on_selection = None
try:
    pv.PdfJsViewer._bridge_sel(_sel_stand_unset, _sel_payload)
    _sel_unset_survived = True
except Exception:
    _sel_unset_survived = False
check("_bridge_sel is a no-op with nothing wired (on_selection is None)",
      _sel_unset_survived)

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
# PdfSidebar and its hosts call these on the viewer (grep reader_panel.py
# for `self._viewer.` and `v.`). A missing one is a live AttributeError —
# _apply_mirror crashed exactly that way on 2026-08-25 (external-change
# poll against the pdfjs renderer).
for attr in ("load_path", "set_page_texts", "load_annotations",
             "clear_document", "go_to_page",
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
reader_panel = importlib.import_module("klausmate.reader_panel")
check("PdfSidebar forwards cleanup to the renderer",
      hasattr(reader_panel.PdfSidebar, "cleanup"))
check("a profile/quit sweep exists as backstop",
      hasattr(reader_panel, "cleanup_all_sidebars"))
_here = os.path.dirname(os.path.abspath(__file__))
_src = lambda n: open(os.path.join(_here, "..", "klausmate", n)).read()
check("the reader host's release() tears the sidebar down, and a Browse closing with no home calls it",
      "r.cleanup()" in _src("reader_host.py") and "reader_host.release()" in _src("library_viewer.py"))
check("sweep registered on profile switch AND quit",
      _src("__init__.py").count("cleanup_all_sidebars") >= 2)

section("vendored pdf.js present")
here = os.path.dirname(os.path.abspath(__file__))
pdfjs = os.path.join(here, "..", "klausmate", "web", "pdfjs")
check("pdf.min.js vendored",
      os.path.getsize(os.path.join(pdfjs, "pdf.min.js")) > 100_000)
check("pdf.worker.min.js vendored",
      os.path.getsize(os.path.join(pdfjs, "pdf.worker.min.js")) > 500_000)

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

section("K-154: annobar carries a thumbnails toggle — reachable from "
        "every host, not just the editor panel's own header button")
# K-153 found the thumbnail toggle lived ONLY in the editor panel
# (__init__.py's tab-header button); on the pdfjs renderer
# klausToggleThumbs (below) had no in-page control and no keyboard
# binding at all, so thumbnails were 100% unreachable from the Library
# and the Lecture dock. The fix mirrors K-116's own move for
# Highlight/Add Text: put the affordance INSIDE the already
# host-agnostic annobar rather than in one host's chrome.
check("annobar grows an eighth control: Thumbnails (the seven from "
      "K-116/K-150 plus this one)",
      'id="annobar"' in _HTML116 and 'id="abThumbs"' in _HTML116)
check("HIG Title Case tooltip, matching Highlight/Add Text's own "
      "shortcut-less style",
      'title="Thumbnails"' in _HTML116)
_AB_THUMBS_SPLIT = _HTML116.split('("abThumbs").addEventListener(', 1)
check("clicking it drives the SAME klausToggleThumbs API the editor "
      "panel's header button already used — no second toggle path",
      len(_AB_THUMBS_SPLIT) == 2
      and "klausToggleThumbs()" in _AB_THUMBS_SPLIT[1][:200])
check("the button lives INSIDE #annobar (the bar every host already "
      "renders), not a host-specific chrome row",
      'id="abThumbs"' in _ANNOBAR_MARKUP)

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


section("a partial Qt surface degrades the WIDGET, not the whole module (K-164)")
# ``class PdfJsViewer(QWidget)`` with ``QWidget = None`` in the import
# fallback is a hard TypeError AT IMPORT TIME — "NoneType takes no
# arguments" — so a partial Qt surface does not cost the viewer, it costs
# the WHOLE MODULE: the six aqt-free helpers this file spends 1500 lines
# on go down with it, and ``PDFJS_AVAILABLE`` never gets to be False
# because the module never finishes importing to set it. The handler is
# commented "only in stripped test stubs", which is precisely the
# environment where the fallback is load-bearing and precisely where it
# did not work. Third instance of one defect: index_queue._StatusDock
# (K-152), lecture_view.LectureDock (K-161), this one.
#
# Run in a SUBPROCESS, deliberately. The pin swaps aqt.qt for a namespace
# WITHOUT QWidget and re-imports; in process that would leave a
# differently-configured pdfjs_viewer in sys.modules for every section
# above it (they all read the module-level ``pv``). A fresh interpreter is
# also where the defect actually lives: it is an import-time failure, so
# importing IS the test.

_PARTIAL_QT_PROBE = r'''
import importlib, sys, types
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
import anki_stubs
anki_stubs.install()


class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()


# An EXPLICIT aqt.qt whose hand-listed names do not include QWidget
# (test_lecture_view.py's shape, itself tests/test_drive.py's). anki_stubs'
# own aqt.qt is PERMISSIVE — a PEP 562 __getattr__ auto-vivifies every
# name — which is why this whole class of defect is invisible to the
# default bootstrap and why this pin builds its own stub instead.
shim = types.ModuleType("aqt.qt")
for _n in ("QApplication", "QImage", "QInputDialog", "QLabel",
           "QSizePolicy", "QTimer", "QVBoxLayout"):
    setattr(shim, _n, _Any)
shim.Qt = _Any()
sys.modules["aqt.qt"] = shim
sys.modules.pop("klausmate.pdfjs_viewer", None)

pv = importlib.import_module("klausmate.pdfjs_viewer")

# Importing is most of the point, but on its own it would also pass if the
# probe simply failed to reproduce a partial surface. So prove the module
# really did take the fallback, really did degrade the base, and really is
# still the module the rest of Klaus imports it for.
assert pv.QWidget is None, "probe did not reproduce a partial aqt.qt"
assert pv.PDFJS_AVAILABLE is False, pv.PDFJS_AVAILABLE
assert pv.PdfJsViewer.__bases__ == (object,), pv.PdfJsViewer.__bases__

# The aqt-free helpers the card names, each actually exercised (the
# renderer-flag reader among them is gone with the setting).
assert pv.handle_range("1:0", None, 1) == {"refused": True}
assert "__ADDON__" not in pv.build_page_html("klausmate", night=False)
assert pv.parse_bridge("klausmate_pdfjs:hl-add:a:b") == ("hl-add", "a:b")
assert pv.decode_b64_json("eyJhIjogMX0=") == {"a": 1}
assert pv.records_from_rect_map({"0": [[1, 2, 3, 4]]})[0]["page"] == 0

# ...and the degraded class refuses to build rather than half-making
# itself on ``object`` (lecture_view._ensure_dock returning None is the
# same gate; a constructor cannot return None, so it raises by name).
try:
    pv.PdfJsViewer(lambda _p: None)
except RuntimeError:
    pass
else:
    raise AssertionError("a degraded PdfJsViewer must refuse to build")
print("PROBE-OK")
'''

_probe164 = subprocess.run(
    [sys.executable, "-c", _PARTIAL_QT_PROBE],
    capture_output=True, text=True, cwd=os.getcwd(),
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
)
check(
    "pdfjs_viewer IMPORTS under an aqt.qt with no QWidget — a partial Qt "
    "surface must cost the viewer widget, not the helpers and not "
    "PDFJS_AVAILABLE itself%s" % (
        "" if _probe164.returncode == 0
        else "\n      probe stderr: " + _probe164.stderr.strip().splitlines()[-1]
        if _probe164.stderr.strip() else ""),
    _probe164.returncode == 0 and "PROBE-OK" in _probe164.stdout,
)


section("PDFJS_AVAILABLE is the gate, and it guards the one build site")
# Now that PDFJS_AVAILABLE can actually BE False, the flag has to be worth
# something: the class exists under a partial Qt surface as a plain-object
# husk, so anything that builds it without consulting the flag gets a husk.
# There is exactly one build site and it lives in another module — K-161's
# other half (its caller had to learn to expect the refusal), which here is
# already right and is pinned so it stays that way.
import ast as _ast164
import glob as _glob164


def _ctor_sites164():
    out = []
    for path in sorted(_glob164.glob("klausmate/**/*.py", recursive=True)):
        rel = path.replace(os.sep, "/")
        if "/vendor/" in rel:
            continue
        with open(path, encoding="utf-8") as fh:
            tree = _ast164.parse(fh.read())
        for node in _ast164.walk(tree):
            if (isinstance(node, _ast164.Call)
                    and _ast164.unparse(node.func).split(".")[-1]
                    == "PdfJsViewer"):
                out.append(f"{rel}:{node.lineno}")
    return out


_sites164 = _ctor_sites164()
check("exactly one module builds a PdfJsViewer — a second one would need "
      "its own copy of the gate: %s" % (_sites164,),
      len(_sites164) == 1 and _sites164[0].startswith("klausmate/reader_panel.py:"))

_RP164 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "klausmate", "reader_panel.py")
with open(_RP164, encoding="utf-8") as _fh164:
    _rptree164 = _ast164.parse(_fh164.read())


def _guarded_builds164(node, guarded=False, out=None):
    """(lineno, guarded-by-PDFJS_AVAILABLE?) for every ``PdfJsViewer(...)``
    call in reader_panel.py. Only an ``if`` BODY is guarded by its test;
    the else leg is not."""
    out = [] if out is None else out
    if isinstance(node, _ast164.If):
        inner = "PDFJS_AVAILABLE" in _ast164.unparse(node.test) or guarded
        for sub in node.body:
            _guarded_builds164(sub, inner, out)
        for sub in node.orelse:
            _guarded_builds164(sub, guarded, out)
        return out
    if (isinstance(node, _ast164.Call)
            and _ast164.unparse(node.func).split(".")[-1] == "PdfJsViewer"):
        out.append((node.lineno, guarded))
    for child in _ast164.iter_child_nodes(node):
        _guarded_builds164(child, guarded, out)
    return out


_builds164 = _guarded_builds164(_rptree164)
check("the PdfJsViewer build in reader_panel.py was actually found — none "
      "would make the gate check below vacuous", len(_builds164) == 1)
check("...and it sits inside an ``if ... PDFJS_AVAILABLE`` body: that is "
      "the whole gate (PDF reader 5/5: no native fallback, the else leg "
      "is the unavailable label): %s" % (_builds164,),
      all(g for _ln, g in _builds164))


section("PDF reader 2/5: trackpad pinch and smart zoom go to the PDF, "
        "never the whole page")
# The page cancels every ctrl-wheel, yet a pinch still zoomed the WHOLE
# page (gray background too): Chromium pinch-zooms the visual viewport
# for gestures the page never sees as a cancellable wheel — one landing
# before the page script attached, or the macOS two-finger double-tap.
# So Qt takes the native gesture before Chromium does and hands it to
# the page's own zoom.
import math as _m10
from types import SimpleNamespace as _NS10

from PyQt6.QtCore import QObject as _QObj10, QPointF as _QPF10, Qt as _Qt10
from PyQt6.QtGui import QNativeGestureEvent as _NGE10
from PyQt6.QtGui import QPointingDevice as _QPD10
from PyQt6.QtWidgets import QApplication as _QApp10, QWidget as _QW10

_NG10 = _Qt10.NativeGestureType
check("a zoom gesture is a pinch by exp(value)",
      pv.gesture_action(_NG10.ZoomNativeGesture, 0.1)
      == ("pinch", _m10.exp(0.1)))
check("the two-finger double-tap is a smart zoom",
      pv.gesture_action(_NG10.SmartZoomNativeGesture, 0.0) == ("smart",))
for _g10 in (_NG10.BeginNativeGesture, _NG10.EndNativeGesture,
             _NG10.RotateNativeGesture, _NG10.PanNativeGesture,
             _NG10.SwipeNativeGesture):
    check(f"{_g10.name} passes through",
          pv.gesture_action(_g10, 0.3) is None)

_app10 = _QApp10.instance() or _QApp10([])


class _Recv10(_QW10):
    """QWebEngineView's focusProxy stand-in: records what reaches it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.got = []

    def event(self, e):
        if e.type() == e.Type.NativeGesture:
            self.got.append(e.gestureType())
        return super().event(e)


_view10 = _QW10()
_proxy10 = _Recv10(_view10)
_proxy10.setGeometry(10, 20, 300, 300)
_js10 = []
_stand10 = _NS10(_page_label=None, _web=_view10, _eval=_js10.append,
                 _claimed=lambda _e: False)


class _Filter10(_QObj10):
    """PdfJsViewer.eventFilter itself, installed on the stand-in."""

    def eventFilter(self, obj, ev):
        return pv.PdfJsViewer.eventFilter(_stand10, obj, ev)


_filter10 = _Filter10()
_proxy10.installEventFilter(_filter10)
_view10.installEventFilter(_filter10)


_view10.move(100, 200)   # so global, view and proxy coordinates all differ


def _gesture10(kind, value, recv, x=5.0, y=6.0):
    """A gesture at local (x, y) on ``recv``, its global point consistent."""
    p = _QPF10(x, y)
    g = recv.mapToGlobal(p)
    return _NGE10(kind, _QPD10.primaryPointingDevice(), 2, p, p, g,
                  value, _QPF10(0, 0))


_QApp10.sendEvent(_proxy10, _gesture10(_NG10.ZoomNativeGesture, 0.1, _proxy10))
check("a pinch on the focusProxy never reaches Chromium",
      _proxy10.got == [], repr(_proxy10.got))
check("...and becomes ONE klausPinch at the point in view coordinates",
      _js10 == ["window.klausPinch && window.klausPinch(%r, 15.0, 26.0);"
                % _m10.exp(0.1)], repr(_js10))
_js10.clear()
_QApp10.sendEvent(_proxy10, _gesture10(_NG10.SmartZoomNativeGesture, 0.0, _proxy10))
check("a two-finger double-tap is consumed and becomes klausSmartZoom",
      _proxy10.got == []
      and _js10 == ["window.klausSmartZoom && window.klausSmartZoom();"],
      repr(_js10))
_js10.clear()
_QApp10.sendEvent(_proxy10, _gesture10(_NG10.RotateNativeGesture, 0.2, _proxy10))
check("a non-zoom gesture is not consumed",
      _proxy10.got == [_NG10.RotateNativeGesture] and _js10 == [])
_QApp10.sendEvent(_view10, _gesture10(_NG10.ZoomNativeGesture, -0.1, _view10))
check("a pinch delivered to the view itself lands at its view point",
      _js10 == ["window.klausPinch && window.klausPinch(%r, 5.0, 6.0);"
                % _m10.exp(-0.1)], repr(_js10))
_label10 = _Recv10()                  # the page label lives in the header
_stand10._page_label = _label10
_label10.installEventFilter(_filter10)
_js10.clear()
_QApp10.sendEvent(_label10, _gesture10(_NG10.ZoomNativeGesture, 0.1, _label10))
check("a pinch over the page label (outside the view) is left alone",
      _js10 == [] and _label10.got == [_NG10.ZoomNativeGesture])

# Backstop: if Chromium zooms the visual viewport anyway, only a new
# page resets it — the page reports it, Python reloads the HTML and
# re-opens the document at the same scroll and zoom.
_v10 = _viewer8()
_v10.load_path(_pdf8, "lecture.pdf")
_v10._scroll_pos = 700
_pages10 = []


def _ensure10():   # stdHtml stand-in; a no-op once loaded, like the real one
    if _v10._page_loaded:
        return
    _pages10.append(1)
    _v10._page_loaded = True


_v10._ensure_page = _ensure10
class _Timer10:
    """singleShot(0) runs now (the deferred reload); anything longer is
    held until the test fires it (the end-of-gap retry)."""
    held = []

    @staticmethod
    def singleShot(ms, fn):
        if ms == 0:
            fn()
        else:
            _Timer10.held.append((ms, fn))


_qt10 = pv.QTimer
pv.QTimer = _Timer10
_out10 = _io.StringIO()


def _bridge10(cmd):
    with _ctxl.redirect_stdout(_out10):
        _v10._on_bridge("klausmate_pdfjs:" + cmd)


_BAD10 = ("abc", "nan", "inf", "-2", "", "1.0", "1.005")
_REARM10 = "window.klausVvRearm && window.klausVvRearm();"
try:
    _bridge10("zoom:abc")
    _bridge10("zoom:1.75")
    _v10._web.js.clear()
    for _bad10 in _BAD10:
        _bridge10("vv-scale:" + _bad10)
    check("malformed or unzoomed vv-scale reports are ignored",
          _pages10 == [] and _v10._web.js == [] and _Timer10.held == [],
          repr(_v10._web.js))
    _bridge10("vv-scale:1.4")
    check("a zoomed visual viewport reloads the page once", _pages10 == [1])
    _open10 = [i for i, j in enumerate(_v10._web.js)
               if "klausPdfOpen(2, " in j and '"lecture.pdf", true);' in j]
    _keep10 = [i for i, j in enumerate(_v10._web.js)
               if j == "window.klausKeepZoom && window.klausKeepZoom(1.75);"]
    check("...re-opens the document once, keeping the view",
          len(_open10) == 1, repr(_v10._web.js))
    check("...at the user's zoom, set before the document opens",
          len(_keep10) == 1 and _keep10[0] < _open10[0], repr(_v10._web.js))
    check("...and the scroll position", _v10._scroll_pos == 700)

    _v10._web.js.clear()
    _bridge10("vv-scale:1.4")
    _bridge10("vv-scale:1.6")
    check("reports inside the gap do not reload again (no loop if a "
          "reload ever kept the scale)", _pages10 == [1])
    check("...but schedule exactly ONE retry, at the end of the gap",
          len(_Timer10.held) == 1
          and 0 < _Timer10.held[0][0] <= pv.VV_RELOAD_GAP_S * 1000 + 1,
          repr(_Timer10.held))
    check("...and nothing reaches the page until it fires",
          _v10._web.js == [])
    _ms10, _fire10 = _Timer10.held.pop()
    _fire10()
    check("the retry re-arms the page so it re-checks and re-reports "
          "if still zoomed", _v10._web.js == [_REARM10], repr(_v10._web.js))
    _bridge10("vv-scale:1.4")
    check("...while still inside the gap a report schedules a new single "
          "retry rather than reloading", _pages10 == [1]
          and len(_Timer10.held) == 1)
    _Timer10.held.clear()
    _v10._vv_retry_pending = False

    _v10._vv_reload_at -= pv.VV_RELOAD_GAP_S + 1    # the gap has passed
    _bridge10("vv-scale:1.4")
    check("a report after the gap reloads again — the backstop is never "
          "dead for the viewer's life", _pages10 == [1, 1]
          and _Timer10.held == [])
    _v10._web.js.clear()
    for _bad10 in _BAD10:
        _bridge10("vv-scale:" + _bad10)
    check("...and malformed reports are still ignored after that",
          _pages10 == [1, 1] and _v10._web.js == [] and _Timer10.held == [])
finally:
    pv.QTimer = _qt10
check("the recovery is logged and nothing raised",
      "pdfjs page zoomed to 1.40; reloading" in _out10.getvalue()
      and "retrying in" in _out10.getvalue()
      and "error" not in _out10.getvalue(), _out10.getvalue())

_v10._path = None
_v10._web.js.clear()
pv.PdfJsViewer._vv_retry(_v10)
check("a retry with no document loaded does nothing",
      _v10._web.js == [] and _v10._vv_retry_pending is False)
_v10._path = _pdf8

_claimed10 = []
_v10._web.installEventFilter = lambda f: _claimed10.append(("view", f))
_v10._web.focusProxy = lambda: _NS10(
    installEventFilter=lambda f: _claimed10.append(("proxy", f)))
_bridge10("ready")
check("ready (re)claims the live focusProxy, so the gesture filter is on it",
      _claimed10 == [("view", _v10), ("proxy", _v10)], repr(_claimed10))

_v10.load_path(_pdf8, "lecture.pdf")
check("a new document forgets the user zoom", _v10._user_zoom == 0.0)

_HTML10 = _src(os.path.join("web", "pdfjs_viewer.html"))
_KP10 = _HTML10.split("window.klausPinch = function", 1)[1].split("\n};\n", 1)[0]
check("klausPinch feeds the SAME zoom session as ctrl-wheel, at the point",
      "zoomTo(sessionTarget() * factor, x, y, false)" in _KP10
      and 'getElementById("scroll").contains(' in _KP10)
_SZ10 = _HTML10.split("window.klausSmartZoom = async function", 1)[1]
_SZ10 = _SZ10.split("\n};\n", 1)[0]
check("klausSmartZoom toggles fit-width and the previous user zoom "
      "(2x fit if none), centred",
      "zoomTo(fit, c[0], c[1], true)" in _SZ10
      and "state.prevZoom || fit * 2" in _SZ10
      and "viewportCenter()" in _SZ10)
check("the page watches visualViewport resize and scroll",
      'window.visualViewport.addEventListener("resize", vvCheck)' in _HTML10
      and 'window.visualViewport.addEventListener("scroll", vvCheck)'
      in _HTML10)
_VV10 = _HTML10.split("function vvCheck()", 1)[1].split("\n}\n", 1)[0]
check("...and posts vv-scale once, debounced, only when zoomed",
      'post("vv-scale:" + vv.scale)' in _VV10
      and "Math.abs(vv.scale - 1) <= 0.01" in _VV10
      and "vvPosted" in _VV10 and ", 200)" in _VV10)
check("...checking once at boot too (a pinch before the script ran)",
      "\nvvCheck();\n" in _HTML10)
check("every committed zoom is reported so a page reload can restore it",
      'post("zoom:" + (state.userZoomed ? state.scale : 0))' in _HTML10
      and "window.klausKeepZoom = function" in _HTML10)
check("...and forgets the previous document's smart-zoom target",
      "if (!state.keepZoom) state.prevZoom = 0;" in _HTML10)
check("the page re-arms the backstop when the scale returns to 1, and "
      "exposes klausVvRearm for Python's retry",
      "if (Math.abs(vv.scale - 1) <= 0.01) { vvPosted = false; return; }"
      in _HTML10
      and "window.klausVvRearm = function () { vvPosted = false; vvCheck(); };"
      in _HTML10)
check("a fresh document's fit clears a stale user-zoom flag",
      "state.scale = clampScale(avail / base.width);\n"
      "    state.userZoomed = false;" in _HTML10)

section("the no-webview fallback names no switch that no longer exists")
with open(pv.__file__, encoding="utf-8") as _fh:
    _PY_SRC = _fh.read()
check("no 'switch off the pdf.js viewer' copy (PDF reader 5/5 deleted the switch)",
      "switch off the pdf.js" not in _PY_SRC and "The PDF viewer could not start." in _PY_SRC)

raise SystemExit(report())
