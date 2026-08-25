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
           "klausGoToPage", "klausSetZoom"):
    check(f"JS API {fn} present", fn in html)
check("bridge prefix wired", "klausmate_pdfjs:" in html)

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
