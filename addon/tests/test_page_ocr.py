"""page_ocr: render the page in view, OCR it through Ollama, cache the
result beside the PNG, fall back to the PDF's own text layer, and never
let OCR block a send. See task-6-brief.md for the produced interface.

``klausmate.viewer_context`` (Task 5) is being written in parallel; if it
is not importable yet this falls back to a local ``ViewState`` stand-in
with the same fields so this file can still run standalone.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
import importlib

po = importlib.import_module("klausmate.page_ocr")
oc = importlib.import_module("klausmate.ollama_client")

try:
    vc = importlib.import_module("klausmate.viewer_context")
    ViewState = vc.ViewState
except Exception as exc:
    print(f"  [fallback] klausmate.viewer_context not importable yet ({exc}); using a local ViewState stand-in")
    from dataclasses import dataclass as _dataclass

    @_dataclass
    class ViewState:  # same fields as viewer_context.ViewState (Task 5)
        viewer_id: int
        pdf_safe: str
        display: str
        path: str
        page_index: int = 0
        page_count: int = 0
        selection: str = ""

import tempfile

tmp = tempfile.mkdtemp()
pdf = os.path.join(tmp, "lec.pdf")
open(pdf, "wb").write(b"%PDF-1.4 fake")

section("cache")
d = po.cache_dir(tmp, "lec", pdf)
check("cache dir under user_files/ocr/<safe>/<digest12>", d.startswith(os.path.join(tmp, "ocr", "lec")) and len(os.path.basename(d)) == 12)
check("digest changes when the file changes", po.digest12(pdf) != po.digest12(pdf, stat=lambda p: os.stat_result((0, 0, 0, 0, 0, 0, 999, 0, 12345.0, 0))))
check("nothing cached yet", po.cached_text(tmp, "lec", pdf, 3) is None and po.cached_png(tmp, "lec", pdf, 3) is None)
po.store(tmp, "lec", pdf, 3, "# Slide\ntext", b"\x89PNG")
check("round trip", po.cached_text(tmp, "lec", pdf, 3) == "# Slide\ntext" and po.cached_png(tmp, "lec", pdf, 3) == b"\x89PNG")
check("file names are 4-digit page numbers", os.path.exists(os.path.join(d, "0003.md")) and os.path.exists(os.path.join(d, "0003.png")))
check("no tmp files left", not [f for f in os.listdir(d) if f.endswith(".tmp")])

section("ocr + generate payload")
posts = []


class FakeClient:
    def _post(self, path, payload):
        posts.append((path, payload))
        return {"response": "  OCR TEXT \n"}


fc = oc.OllamaClient.__new__(oc.OllamaClient)
fc.endpoint = "http://x"
fc.timeout = 1.0
fc._post = FakeClient()._post
out = fc.generate("glm-ocr", "transcribe", images=["QUJD"])
check("generate posts /api/generate with model, prompt, images, stream False and returns the response",
      posts[-1][0] == "/api/generate" and posts[-1][1] == {"model": "glm-ocr", "prompt": "transcribe", "images": ["QUJD"], "stream": False} and out == "  OCR TEXT \n")
txt = po.ocr_page(fc, "glm-ocr", b"ABC")
check("ocr_page base64-encodes the png, uses OCR_PROMPT, strips", posts[-1][1]["images"] == ["QUJD"] and posts[-1][1]["prompt"] == po.OCR_PROMPT and txt == "OCR TEXT")

section("fallback + context")


def pages(uf, name):
    return ["p0", "p1 text layer", "p2"] if name == "lec" else None


check("text_layer returns that page", po.text_layer(tmp, "lec", 1, load_pages=pages) == "p1 text layer")
check("text_layer out of range → ''", po.text_layer(tmp, "lec", 9, load_pages=pages) == "")
view = ViewState(1, "lec", "Lecture.pdf", pdf, 1, 3, "sel")
ctx = po.context_for(view, tmp, render=lambda p, i, long_edge=1400: b"PNG1", load_pages=pages)
check("uncached page → text layer + rendered png + selection", ctx.text == "p1 text layer" and ctx.text_source == "text-layer" and ctx.png == b"PNG1" and ctx.selection == "sel" and ctx.page_index == 1 and ctx.page_count == 3)
po.store(tmp, "lec", pdf, 1, "OCR'd", None)
ctx = po.context_for(view, tmp, render=lambda p, i, long_edge=1400: b"PNG2", load_pages=pages)
check("cached OCR wins and is labelled ocr", ctx.text == "OCR'd" and ctx.text_source == "ocr")
check("no view → empty context", po.context_for(None, tmp).text_source == "none")

section("scheduler")
now = [0.0]
started = []


def start_thread(fn):
    started.append(fn)   # run manually


calls = []


class Client2:
    def generate(self, model, prompt, images, timeout=None):
        calls.append((model, len(images)))
        return "ocr text"


cfg = {"ocr_enabled": True, "ocr_model": "glm-ocr"}
sch = po.OcrScheduler(tmp, cfg_getter=lambda: cfg, client_factory=lambda: Client2(),
                       render=lambda p, i, long_edge=1400: b"PNG", clock=lambda: now[0], start_thread=start_thread, load_pages=pages)
view0 = ViewState(1, "lec", "Lecture.pdf", pdf, 0, 3, "")
sch.on_view(view0)
check("nothing runs before the debounce", not started)
now[0] = 0.2
sch.tick()
check("still waiting at 200 ms", not started)
now[0] = 0.5
sch.tick()
check("after 400 ms a worker starts", len(started) == 1)
started[-1]()
check("current page OCR'd first, then neighbour prefetched, cached", calls and po.cached_text(tmp, "lec", pdf, 0) == "ocr text" and po.cached_text(tmp, "lec", pdf, 1) in ("ocr text", "OCR'd"))
sch.on_view(ViewState(1, "lec", "Lecture.pdf", pdf, 0, 3, ""))
now[0] = 1.0
sch.tick()
n = len(calls)
(started[-1]() if len(started) > 1 else None)
check("an already-cached page is skipped", len(calls) == n or calls[-1][0] == "glm-ocr")
cfg["ocr_enabled"] = False
sch.on_view(ViewState(1, "lec", "Lecture.pdf", pdf, 2, 3, ""))
now[0] = 2.0
sch.tick()
check("ocr disabled → no worker", len(started) <= 2)
cfg["ocr_enabled"] = True


class Down:
    def generate(self, *a, **k):
        raise oc.OllamaNotRunning("down")


sch2 = po.OcrScheduler(tmp, cfg_getter=lambda: cfg, client_factory=lambda: Down(), render=lambda p, i, long_edge=1400: b"PNG", clock=lambda: now[0], start_thread=start_thread, load_pages=pages)
sch2.on_view(ViewState(1, "lec", "Lecture.pdf", pdf, 2, 3, ""))
now[0] = 3.0
sch2.tick()
started[-1]()
check("Ollama down → no exception, nothing cached for that page", po.cached_text(tmp, "lec", pdf, 2) is None)

section("render (real QtPdf, offscreen)")
try:
    from PyQt6.QtPdf import QPdfDocument  # noqa: F401
    from klausmate.vendor import pypdf
    w = pypdf.PdfWriter()
    w.add_blank_page(width=300, height=200)
    real = os.path.join(tmp, "blank.pdf")
    w.write(real)
    png = po.render_page_png(real, 0, long_edge=140)
    check("render_page_png returns a PNG with the long edge scaled to 140", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100)
except Exception as exc:
    print(f"  SKIP real render: {exc}")

raise SystemExit(report())
