"""Offscreen tests for the transcript strip (Plan 2 Task 6, K-258).

Covers klausmate.pdf_viewer.PdfSidebar's native-renderer transcript
strip: set_transcript's visibility/label contract (the brief's Step 1
acceptance), the page_store integration (append_segment then a page
change shows it; an untouched page stays hidden), the LIVE
page_store.subscribe wiring, the chevron's collapse/expand, and that
cleanup() actually unsubscribes. The pdf.js side (the bridge call,
the in-page JS) is tests/test_pdfjs_viewer.py's job; the QSS tokens
are test_theme.py's.

Real offscreen PyQt6 (tests/test_drive.py's K-117 section and the
klaus-test skill): this machine's system python3 has its own PyQt6,
so a genuine QPdfView/QScrollArea/QToolButton renders and can be
inspected offscreen, even though Anki's own bundled Python cannot be
imported here at all.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_transcript_strip.py
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtCore as _QtC
    from PyQt6 import QtGui as _QtG
    from PyQt6 import QtWidgets as _QtW

    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — this "
          "whole suite is widget-shaped, nothing else to fall back to")

if _HAVE_QT:
    # Real PyQt6 behind aqt.qt (test_drive.py's K-117 pattern): klausmate
    # imports QScrollArea/QFrame/QToolButton/QPdfView/... by name from
    # aqt.qt (and PyQt6.QtPdf* directly), and only a genuine Qt can
    # construct, lay out and report .isVisible() on them.
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

    pkg = sys.modules["klausmate"]
    app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    # K-257 fix round 1 (cross-task): pdf_viewer._on_page_store_notify now
    # marshals through _run_on_main, which (with a real aqt.mw) posts to
    # mw.taskman.run_on_main — anki_stubs' permissive aqt.mw is a _Dummy
    # whose "run_on_main(cb)" auto-vivifies and never calls cb at all, so
    # every live-update check in this file would silently stop seeing any
    # notification. A real deferred post (QTimer.singleShot(0, ...)) is
    # what actually behaves like Anki's own taskman and is what this
    # file's existing app.processEvents() loops are already built to pump.
    class _FakeTaskman:
        def run_on_main(self, cb):
            _QtC.QTimer.singleShot(0, cb)

    sys.modules["aqt"].mw.taskman = _FakeTaskman()

    theme = importlib.import_module("klausmate.theme")
    page_store = importlib.import_module("klausmate.page_store")
    pdf_handler = importlib.import_module("klausmate.pdf_handler")
    drive_store = importlib.import_module("klausmate.drive_store")
    pdf_viewer = importlib.import_module("klausmate.pdf_viewer")

    def _one_page_pdf(path: str) -> None:
        """One page, real content — test_drive.py's K-173 `_proof_pdf`
        shape, reused verbatim (a proven-loadable minimal PDF) rather
        than inventing a leaner one that might trip some pdfium edge
        case this card has no reason to go looking for."""
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        ]
        stream = (b"0 0 0 rg 72 400 468 300 re f\n"
                  b"BT /F1 36 Tf 72 200 Td (KLAUS TRANSCRIPT PROOF) Tj ET\n")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream
                    + b"endstream")
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont "
                    b"/Helvetica >>")
        out, offs = bytearray(b"%PDF-1.4\n"), []
        for i, body in enumerate(objs, start=1):
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n" % (len(objs) + 1)
        out += b"0000000000 65535 f \n"
        for off in offs:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n"
                b"%%%%EOF\n" % (len(objs) + 1, xref))
        with open(path, "wb") as fh:
            fh.write(bytes(out))

    uf = tempfile.mkdtemp(prefix="klaus_transcript_uf_")
    os.makedirs(os.path.join(uf, "contexts"), exist_ok=True)
    os.makedirs(os.path.join(uf, "pdfs"), exist_ok=True)
    _one_page_pdf(os.path.join(uf, "pdfs", "Sample.pdf"))
    with open(os.path.join(uf, "contexts", "Sample.json"), "w",
              encoding="utf-8") as _fh:
        json.dump({"pages": ["Slide one text"]}, _fh)
    drive_store.record_import(uf, "Sample", "Sample Lecture.pdf")
    _one_page_pdf(os.path.join(uf, "pdfs", "Quiet.pdf"))
    with open(os.path.join(uf, "contexts", "Quiet.json"), "w",
              encoding="utf-8") as _fh:
        json.dump({"pages": ["Other slide"]}, _fh)
    drive_store.record_import(uf, "Quiet", "Quiet Lecture.pdf")
    pkg.USER_FILES = uf

    section("PdfSidebar.set_transcript — visibility/label contract (brief Step 1)")
    sb = pdf_viewer.PdfSidebar(None, parent=None)
    sb.show()
    for _ in range(3):
        app.processEvents()
    check("no config -> native renderer (the brief's acceptance path)",
          sb._renderer == "native")
    check("the strip exists and starts hidden",
          sb._transcript is not None and not sb._transcript.isVisible())
    _NoFocus = _QtC.Qt.FocusPolicy.NoFocus
    check("fix round 1 (M1): the chevron declares NoFocus explicitly, "
          "not just Qt's own default — this file's established pattern "
          "for 'don't let an ancillary widget steal the viewer's "
          "shortcuts' (CLAUDE.md: Host-window shortcut ambiguity)",
          sb._transcript_chevron.focusPolicy() == _NoFocus)
    check("...the scroll area too",
          sb._transcript_scroll.focusPolicy() == _NoFocus)
    check("...and the label",
          sb._transcript_label.focusPolicy() == _NoFocus)
    # PR #4 third re-review (Copilot): QLabel.setText defaults to
    # Qt.TextFormat.AutoText, which sniffs the string and renders
    # anything that looks like markup AS markup — `<img src=...>`, a
    # link, a bold run. Transcript text is untrusted: it comes off a
    # microphone and back out of a transcription API. The pdf.js half of
    # this same strip already writes with textContent; PlainText is the
    # Qt-side equivalent, declared ONCE where the label is built so
    # every set_transcript inherits it.
    check("the label is PlainText, so no set_transcript can ever parse "
          "markup out of a transcript",
          sb._transcript_label.textFormat() == _QtC.Qt.TextFormat.PlainText,
          repr(sb._transcript_label.textFormat()))
    sb.set_transcript(0, "<b>bold</b>")
    # text() is format-independent (QLabel keeps the string it was
    # given either way), so the pin above is the load-bearing one; this
    # one documents the whole contract end to end: what the strip is
    # asked to show is what a reader sees, tag characters and all.
    check("...and a transcript carrying markup is shown as its literal "
          "characters",
          sb._transcript_label.text() == "<b>bold</b>",
          repr(sb._transcript_label.text()))
    sb.set_transcript(0, "hello transcript")
    check("set_transcript shows the strip with the given text",
          sb._transcript.isVisible()
          and sb._transcript_label.text() == "hello transcript")
    sb.set_transcript(1, "")
    check("set_transcript(..., '') hides it again",
          not sb._transcript.isVisible())
    sb.cleanup()
    sb.close()

    section("PdfSidebar — page_store integration: append_segment then load")
    path_sample = pdf_handler.pdf_path_for(uf, "Sample")
    check("the scratch PDF resolves through pdf_handler's own choke point",
          path_sample is not None)
    page_store.ensure_records(uf, "Sample", path_sample, ["Slide one text"])
    page_store.append_segment(uf, "Sample", path_sample, 0, 0.0, 5.0,
                               "the professor said something")
    sb2 = pdf_viewer.PdfSidebar(None, parent=None)
    sb2.show()
    for _ in range(5):
        app.processEvents()
    sb2.load_pdf("Sample")
    for _ in range(10):
        app.processEvents()
    check("after append_segment, loading the PDF shows page 0's transcript",
          sb2._transcript.isVisible()
          and sb2._transcript_label.text() == "the professor said something")
    check("...and it is the SPOKEN text, never the slide text",
          "Slide one text" not in sb2._transcript_label.text())

    section("PdfSidebar — a page with no segments never shows the strip")
    sb3 = pdf_viewer.PdfSidebar(None, parent=None)
    sb3.show()
    for _ in range(5):
        app.processEvents()
    sb3.load_pdf("Quiet")
    for _ in range(10):
        app.processEvents()
    check("an empty page_store record hides the strip",
          not sb3._transcript.isVisible())
    sb3.cleanup()
    sb3.close()

    section("PdfSidebar — page_store.subscribe wires a LIVE update in")
    page_store.append_segment(uf, "Sample", path_sample, 0, 5.0, 9.0,
                               "and then something else")
    for _ in range(5):
        app.processEvents()
    check("appending a segment to the CURRENT page updates the strip with "
          "no explicit refresh call from this test — subscribe did it",
          sb2._transcript_label.text()
          == "the professor said something\nand then something else")
    # Fix round 1 (M3): checking the resulting TEXT alone (as this pin
    # used to) cannot tell "the filter blocked the notification" apart
    # from "the filter let it through, but _refresh_transcript recomputed
    # the SAME value anyway" — it always reads from sb2's OWN self._name,
    # never from the notification's pdf_safe argument, so a silently
    # broken filter would still show the right text by coincidence. Count
    # _refresh_transcript calls instead: that is what the filter actually
    # gates, so this pin fails if the `pdf_safe == self._name` guard is
    # ever dropped, even though the label would still read correctly.
    _refresh_calls: list[int] = []
    _orig_refresh = sb2._refresh_transcript
    sb2._refresh_transcript = lambda: (
        _refresh_calls.append(1), _orig_refresh()
    )[-1]
    page_store.append_segment(
        uf, "Quiet", pdf_handler.pdf_path_for(uf, "Quiet"),
        0, 0.0, 1.0, "irrelevant to sb2")
    for _ in range(5):
        app.processEvents()
    check("a segment for a DIFFERENT pdf_safe never even calls "
          "_refresh_transcript — the subscriber's filter really gates "
          "the refresh, not just the text that happens to come out",
          _refresh_calls == [])
    page_store.append_segment(uf, "Sample", path_sample, 0, 6.0, 7.0,
                               "own pdf tick")
    for _ in range(5):
        app.processEvents()
    check("...but a notification for ITS OWN pdf_safe (same page) does",
          _refresh_calls == [1])
    sb2._refresh_transcript = _orig_refresh
    check("and the label reflects that real refresh",
          sb2._transcript_label.text()
          == "the professor said something\nand then something else"
             "\nown pdf tick")

    section("PdfSidebar — the chevron collapses and expands the strip")
    check("starts expanded", sb2._transcript_scroll.isVisible())
    sb2._transcript_chevron.setChecked(False)
    check("collapsing hides the scroll area but keeps the strip (and its "
          "header) visible — only the body is what collapses",
          not sb2._transcript_scroll.isVisible()
          and sb2._transcript.isVisible())
    sb2._transcript_chevron.setChecked(True)
    check("expanding shows the body again", sb2._transcript_scroll.isVisible())

    section("PdfSidebar — fix round 1 (M2): the no-native-viewer fallback "
            "also refreshes the transcript")
    # The strip is built whenever the renderer isn't pdfjs, independent
    # of PDF_VIEWER_AVAILABLE — so on a hypothetical Anki build without
    # QtPdf/QtPdfWidgets, load_pdf's "no native viewer at all" branch used
    # to leave a previous PDF's transcript on screen forever, since it
    # never called _on_page_changed (the ONLY other call site) either.
    _orig_pdf_avail = pdf_viewer.PDF_VIEWER_AVAILABLE
    pdf_viewer.PDF_VIEWER_AVAILABLE = False
    try:
        sb4 = pdf_viewer.PdfSidebar(None, parent=None)
        sb4.show()
        for _ in range(3):
            app.processEvents()
        check("the fallback branch is really the one under test — no "
              "real viewer, the label-only fallback instead",
              sb4._viewer is None and sb4._fallback_label is not None)
        sb4.load_pdf("Sample")
        for _ in range(5):
            app.processEvents()
        check("...and it still shows page 0's transcript via "
              "_refresh_transcript, not just the fallback label",
              sb4._transcript is not None and sb4._transcript.isVisible()
              and "professor" in sb4._transcript_label.text())
        sb4.cleanup()
        sb4.close()
    finally:
        pdf_viewer.PDF_VIEWER_AVAILABLE = _orig_pdf_avail

    section("PdfSidebar.cleanup() unsubscribes from page_store")
    sb2.cleanup()
    _before = sb2._transcript_label.text()
    page_store.append_segment(uf, "Sample", path_sample, 0, 9.0, 12.0,
                               "after cleanup this must not land")
    for _ in range(5):
        app.processEvents()
    check("a cleaned-up sidebar's subscription is gone — a later "
          "append_segment leaves its label frozen",
          sb2._transcript_label.text() == _before)
    sb2.close()

    section("PdfSidebar — a FAILED native load clears the strip "
            "(PR #4 fifth re-review)")
    # The missing-PDF branch and the no-native-viewer fallback both
    # refresh the strip; QPdfDocument.load() blowing up only called
    # _set_active(None) and returned — so switching from a lecture with a
    # transcript to an unloadable PDF left the previous PDF's spoken text
    # on screen over a blank viewer.
    sb6 = pdf_viewer.PdfSidebar(None, parent=None)
    sb6.show()
    for _ in range(5):
        app.processEvents()
    sb6.load_pdf("Sample")
    for _ in range(10):
        app.processEvents()
    check("the sidebar really is showing a transcript before the bad load",
          sb6._transcript.isVisible()
          and "professor" in sb6._transcript_label.text())

    class _UnloadableDoc:
        """Both load() overloads raise — the exact double-except path
        (str first, then QUrl.fromLocalFile) load_pdf falls through."""

        def load(self, *_a, **_k):
            raise RuntimeError("pdfium said no")

    sb6._doc = _UnloadableDoc()
    sb6.load_pdf("Quiet")
    for _ in range(5):
        app.processEvents()
    check("a load that fails leaves no stale transcript behind",
          not sb6._transcript.isVisible()
          and sb6._transcript_label.text() == "",
          repr(sb6._transcript_label.text()))
    # K-276 review: clearing the strip was not enough — the sidebar still
    # NAMED the old PDF, so the next page_store notify or page change for
    # that name re-read its record and put the transcript straight back.
    # The failed load must forget the document, like the no-path branch.
    check("...and the sidebar no longer names the PDF that loaded before it",
          sb6._name is None, repr(sb6._name))
    sb6._refresh_transcript()
    for _ in range(3):
        app.processEvents()
    check("...so a later refresh cannot bring the old transcript back",
          not sb6._transcript.isVisible() and sb6._transcript_label.text() == "",
          repr(sb6._transcript_label.text()))
    sb6.cleanup()
    sb6.close()

    section("PdfSidebar._on_page_store_notify marshals through "
            "_run_on_main (K-257 fix round 1, cross-task)")
    # page_store.append_segment calls _notify (hence
    # _on_page_store_notify) SYNCHRONOUSLY, on whatever thread calls it —
    # and the lecture recorder's Uploader calls append_segment from its
    # own daemon worker thread. Every OTHER section in this file calls
    # append_segment from the main thread (the test script itself), so
    # none of them would ever catch a missing marshal. Faking
    # pdf_viewer._run_on_main to just RECORD the closure (never running
    # it) is what proves the widget touch is deferred rather than
    # applied inline on the calling thread. Run LAST, after every other
    # sidebar (sb2/sb3/sb4) is already cleaned up/closed, so sb5 is the
    # only live subscriber and _recorded_cbs can't pick up a second
    # sidebar's own notification for the same segment.
    import threading

    sb5 = pdf_viewer.PdfSidebar(None, parent=None)
    sb5.show()
    for _ in range(5):
        app.processEvents()
    sb5.load_pdf("Sample")
    for _ in range(10):
        app.processEvents()
    _before5 = sb5._transcript_label.text()

    _recorded_cbs: list = []
    _orig_run_on_main = pdf_viewer._run_on_main
    pdf_viewer._run_on_main = lambda cb: _recorded_cbs.append(cb)
    try:
        _thread_names: list = []

        def _bg_append():
            _thread_names.append(threading.current_thread().name)
            page_store.append_segment(uf, "Sample", path_sample, 0,
                                       20.0, 21.0, "cross thread segment")

        t = threading.Thread(target=_bg_append, name="Klaus-Uploader-Probe")
        t.start()
        t.join()
        for _ in range(5):
            app.processEvents()
        check("the notification really ran on a background thread — "
              "the exact shape of Uploader._one calling append_segment",
              _thread_names == ["Klaus-Uploader-Probe"])
        check("the widget is untouched immediately after — only the "
              "closure was recorded, never applied inline on that thread",
              len(_recorded_cbs) == 1
              and sb5._transcript_label.text() == _before5)
        _recorded_cbs[0]()
        check("running the recorded closure (simulating the main-thread "
              "hop) applies the refresh, picking up the segment the "
              "worker thread appended",
              sb5._transcript_label.text() == _before5 + "\ncross thread segment")

        # PR #4 fifth re-review: that deferred closure can still be in
        # Qt's event queue when the dock tears the sidebar down — the
        # uploader's notification then runs _refresh_transcript against
        # widgets whose C++ side is gone (RuntimeError, raised out of
        # taskman). cleanup() latches a liveness flag BEFORE it
        # unsubscribes, and the closure checks it.
        _after5 = sb5._transcript_label.text()
        _recorded_cbs.clear()
        t2 = threading.Thread(target=lambda: page_store.append_segment(
            uf, "Sample", path_sample, 0, 30.0, 31.0, "after teardown"),
            name="Klaus-Uploader-Probe-2")
        t2.start()
        t2.join()
        check("the post-teardown notification was deferred as well",
              len(_recorded_cbs) == 1)
        sb5.cleanup()
        _torn_ok = True
        try:
            _recorded_cbs[0]()
        except Exception as _exc:  # noqa: BLE001
            _torn_ok = False
            print(f"    (raised: {_exc.__class__.__name__}: {_exc})")
        check("a closure that lands AFTER cleanup() raises nothing and "
              "refreshes nothing",
              _torn_ok and sb5._transcript_label.text() == _after5,
              repr(sb5._transcript_label.text()))

        # Belt and braces behind that flag: a widget torn down by Qt
        # itself (deleteLater, a parent going away) makes the refresh
        # raise RuntimeError even while the sidebar still looks live.
        # Swallow it with one log line rather than let it out of the
        # uploader's notify chain.
        sb5._torn_down = False

        def _raise_deleted():
            raise RuntimeError("wrapped C/C++ object of type QLabel has been deleted")

        sb5._refresh_transcript = _raise_deleted
        _recorded_cbs.clear()
        # Called straight on the subscriber — cleanup() above already
        # unsubscribed it from page_store, and this pin is about what the
        # deferred closure does with a raising refresh, not about how the
        # notification reached it.
        sb5._on_page_store_notify("Sample", 0)
        _deleted_ok = True
        try:
            _recorded_cbs[0]()
        except Exception as _exc:  # noqa: BLE001
            _deleted_ok = False
            print(f"    (raised: {_exc.__class__.__name__}: {_exc})")
        check("a deleted-widget RuntimeError inside the refresh is "
              "swallowed, never propagated into the notification chain",
              _deleted_ok)
    finally:
        pdf_viewer._run_on_main = _orig_run_on_main
    sb5.cleanup()
    sb5.close()

    shutil.rmtree(uf, ignore_errors=True)
else:
    print("  SKIP: PyQt6 unavailable — no source-only fallback is "
          "meaningful for a widget-shaped card")

raise SystemExit(report())
