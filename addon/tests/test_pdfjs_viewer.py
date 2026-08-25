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
check("there are exactly four render sites",
      html.count("page.render({") == 4)

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

raise SystemExit(report())
