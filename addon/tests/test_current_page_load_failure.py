"""Failed real sidebar loads must not expose the previous page through MCP."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

import klaus_note.settings as _settings  # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6 import QtCore, QtGui, QtWidgets

# Real-Qt aqt shim.
shim = types.ModuleType("aqt.qt")
def qt_getattr(name):
    for module in (QtWidgets, QtCore, QtGui):
        if hasattr(module, name):
            return getattr(module, name)
    if name == "qconnect":
        return lambda signal, callback: signal.connect(callback)
    raise AttributeError(name)
shim.__getattr__ = qt_getattr
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["klaus-test"])
sys.modules["aqt"].mw.taskman = types.SimpleNamespace(
    run_on_main=lambda callback: QtCore.QTimer.singleShot(0, callback))
rp = importlib.import_module("klaus_note.reader_panel")
vc = importlib.import_module("klaus_note.viewer_context")
ps = importlib.import_module("klaus_note.page_store")
ep = importlib.import_module("klaus_note.anki_endpoint")
pj = importlib.import_module("klaus_note.pdfjs_viewer")


class FakeJsViewer(QtWidgets.QWidget):
    """Stands in for PdfJsViewer (no QtWebEngine headless)."""
    def __init__(self, on_page_changed=None, parent=None):
        super().__init__(parent)
    def set_page_texts(self, pages): pass
    def load_path(self, path, name, keep_view=False): pass
    def load_annotations(self, name): pass
    def clear_document(self): pass
    def cleanup(self): pass


pj.PdfJsViewer, pj.PDFJS_AVAILABLE = FakeJsViewer, True

with tempfile.TemporaryDirectory(prefix="klaus_page_failure_") as root:
    _settings.user_files_dir = root
    for folder in ("pdfs", "contexts"):
        Path(root, folder).mkdir()
    for name in ("Sample", "Healthy"):
        path = str(Path(root, "pdfs", name + ".pdf"))
        writer = QtGui.QPdfWriter(path)
        painter = QtGui.QPainter(writer)
        painter.drawText(100, 200, name + " slide text")
        painter.end()
        del writer
        Path(root, "contexts", name + ".json").write_text(
            json.dumps({"pages": [name + " slide text"]}))
        ps.ensure_records(root, name, path, [name + " slide text"])
        png = ps.render_page_png(path, 0)
        check(name + " fixture renders a real page", bool(png))
        ps.store_page_png(root, name, path, 0, png)
    endpoint = ep.Endpoint(col_getter=lambda: object(),
        run_on_main=lambda fn, timeout: fn(), approver=lambda *args: False,
        ctx_factory=lambda: {"user_files": root}, version="test")
    def current_page():
        return ep.mcp_dispatch(endpoint, {"jsonrpc": "2.0", "id": 7,
            "method": "tools/call", "params": {"name": "current_page",
            "arguments": {}}}, None)[1]["result"]

    for other in (False, True):
        section(f"missing load, healthy second viewer={other}")
        vc.reset()
        healthy = rp.PdfSidebar(None) if other else None
        if healthy is not None:
            healthy.load_pdf("Healthy")
        sidebar = rp.PdfSidebar(None)
        sidebar.load_pdf("Sample")
        app.processEvents()
        before = current_page()
        sample_images = [b["data"] for b in before["content"] if b["type"] == "image"]
        check("successful actual load supplies Sample text and image",
              not before["isError"] and "Sample slide text" in before["content"][0]["text"]
              and bool(sample_images) and sidebar.is_loaded("Sample")
              and sidebar._page_count == 1)
        sidebar.load_pdf("Missing")
        app.processEvents()
        after = current_page()
        check("failed sidebar does not expose previous text",
              "Sample" not in json.dumps(after))
        check("failed sidebar does not expose previous image",
              all(b.get("data") not in sample_images for b in after["content"]))
        if healthy is None:
            check("no remaining viewer gives explicit No active page",
                  len(after["content"]) == 1
                  and "No active page" in after["content"][0]["text"])
        else:
            check("other healthy viewer remains readable",
                  not after["isError"]
                  and "Healthy slide text" in after["content"][0]["text"]
                  and any(b["type"] == "image" for b in after["content"]))
            healthy.cleanup()
            healthy.close()
        sidebar.cleanup()
        sidebar.close()
    vc.reset()
raise SystemExit(report())
