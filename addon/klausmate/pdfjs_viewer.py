"""pdf.js-backed PDF viewer (K-095/K-096; parity K-097..K-099) — the
flicker fix.

QPdfView flickers structurally: pdfium delivers page bitmaps async (blank
flash on scroll/zoom) and the Python-side selection overlay repaints in a
separate pass from the viewport. This module hosts ``web/pdfjs_viewer.html``
(vendored pdf.js 3.11.174 in ``web/pdfjs/``) in an AnkiWebView instead:
canvases are GPU-composited by Chromium, scrolling translates
already-rendered layers, and the text layer gives native browser selection.

Selected by config key ``pdf_renderer`` (``"native"`` default until the
K-101 cutover). ``PdfSidebar`` branches on :func:`renderer_from_config`.

Division of labour (K-097..K-099): the page owns rendering and gestures;
THIS MODULE OWNS THE ANNOTATIONS JSON. JS sends mutations over the bridge
(``hl-add``/``hl-remove``/``note-edit``), Python mutates ``_highlights``,
persists via ``pdf_handler.save_annotations`` + the same debounced bake
the native viewer uses, then pushes the canonical records back through
``window.klausSetAnnotations``. Record schema is identical to the native
viewer's (0-based ``page``, ``rects`` in top-left-origin page points), so
the bake pipeline and K-081 external-delete tombstones are shared, not
forked.

Feed pattern (SynapsePro's): read the file in Python, base64, push into
window globals in chunks, then trigger the load. Pure helpers
(:func:`renderer_from_config`, :func:`chunk_b64`, :func:`build_page_html`,
:func:`parse_bridge`, :func:`decode_b64_json`,
:func:`records_from_rect_map`) stay aqt-free for the headless tests.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from typing import Any, Callable, Optional

import os

# Guarded Qt imports — headless tests import this module with stub aqt.
try:
    from aqt import mw
    from aqt.qt import (
        QApplication,
        QImage,
        QInputDialog,
        QLabel,
        QSizePolicy,
        QTimer,
        QVBoxLayout,
        QWidget,
        Qt,
    )
    from aqt.utils import tooltip
    from aqt.webview import AnkiWebView

    PDFJS_AVAILABLE = True
except Exception:  # pragma: no cover — only in stripped test stubs
    mw = None  # type: ignore[assignment]
    QApplication = QImage = QInputDialog = None  # type: ignore
    QLabel = QSizePolicy = QTimer = QVBoxLayout = QWidget = Qt = None  # type: ignore
    tooltip = None  # type: ignore[assignment]
    AnkiWebView = None  # type: ignore[assignment]
    PDFJS_AVAILABLE = False


# ~6 MB of base64 per eval call: large enough that a lecture PDF loads in
# a handful of calls, small enough that no single eval string is huge.
CHUNK_CHARS = 6 * 1024 * 1024

# Refuse beyond this — base64 inflates 4/3 and the whole document lives
# in webview memory.
MAX_PDF_MB = 200

_BRIDGE_PREFIX = "klausmate_pdfjs:"

HIGHLIGHT_COLOR = "#fadc50"  # native viewer's default highlight yellow


def renderer_from_config(cfg: Any) -> str:
    """``"pdfjs"`` or ``"native"`` from the addon config dict.

    Unknown values and malformed configs degrade to ``"native"`` — the
    proven path stays the default until the K-101 cutover.
    """
    if not isinstance(cfg, dict):
        return "native"
    val = cfg.get("pdf_renderer")
    return "pdfjs" if val == "pdfjs" else "native"


def chunk_b64(data: bytes, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """Base64-encode *data* and split into eval-sized string chunks."""
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    b64 = base64.b64encode(data).decode("ascii")
    return [b64[i : i + chunk_chars] for i in range(0, len(b64), chunk_chars)]


def build_page_html(addon_name: str, night: bool) -> str:
    """The viewer page with ``__ADDON__``/``__THEME_VARS__`` filled in."""
    from . import theme

    path = os.path.join(os.path.dirname(__file__), "web", "pdfjs_viewer.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ADDON__", addon_name)
    html = html.replace("__THEME_VARS__", theme.css_vars(night))
    return html


def parse_bridge(cmd: str) -> tuple[str, str] | None:
    """Split a ``klausmate_pdfjs:<action>[:<payload>]`` bridge string.

    Returns ``(action, payload)`` (payload ``""`` when absent) or None
    for commands that are not ours. Splits on the FIRST colon after the
    prefix only — payloads (base64, data URLs) may contain colons.
    """
    if not cmd.startswith(_BRIDGE_PREFIX):
        return None
    msg = cmd[len(_BRIDGE_PREFIX):]
    if ":" in msg:
        action, payload = msg.split(":", 1)
    else:
        action, payload = msg, ""
    return action, payload


def decode_b64_json(payload: str) -> Any:
    """UTF-8 JSON out of a base64 bridge payload (None on any failure)."""
    try:
        return json.loads(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        return None


def records_from_rect_map(
    pages: Any, color: str = HIGHLIGHT_COLOR
) -> list[dict]:
    """New highlight records from the JS selection map
    ``{page0: [[x, y, w, h] page points, ...]}`` — same shape the native
    viewer's ``_add_highlight_from_selection`` mints (uuid id, 0-based
    int page, float rects, default yellow). Malformed pages/rects are
    skipped, never raised on."""
    out: list[dict] = []
    if not isinstance(pages, dict):
        return out
    keyed: list[tuple[int, Any]] = []
    for page_key in pages:
        try:
            keyed.append((int(page_key), page_key))
        except (TypeError, ValueError):
            continue
    for page, page_key in sorted(keyed):
        rects: list[list[float]] = []
        for r in pages[page_key] or []:
            try:
                x, y, w, h = (float(v) for v in r)
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            rects.append([x, y, w, h])
        if rects:
            out.append(
                {
                    "id": uuid.uuid4().hex,
                    "page": page,
                    "rects": rects,
                    "color": color,
                }
            )
    return out


class PdfJsViewer(QWidget):  # type: ignore[misc]
    """Drop-in for ``PdfViewer`` behind the ``pdf_renderer`` flag.

    Matches the surface PdfSidebar and the tab container actually use:
    ``load_path`` (the pdf.js entry — the sidebar calls it instead of
    ``set_document``), ``set_page_texts``, ``load_annotations``,
    ``clear_document``, ``go_to_page``, ``scroll_position`` /
    ``restore_scroll_position``, ``toggle_thumbnails``, ``_page_label``.
    """

    def __init__(
        self,
        on_page_changed: Callable[[int], None],
        parent: Optional[QWidget] = None,  # type: ignore[valid-type]
    ) -> None:
        super().__init__(parent)
        self._on_page_changed = on_page_changed
        self._name: str | None = None
        self._annotations_name: str | None = None
        self._highlights: list[dict] = []
        self._page_count = 0
        self._scroll_pos = 0
        self.on_count: Optional[Callable[[int], None]] = None

        # Debounced bake, same shape as the native viewer's: pending
        # jobs are a SET so annotating PDF A then PDF B inside one
        # debounce window bakes both.
        self._bake_timer: Any = None
        self._bake_pending: dict[tuple[str, str], bool] = {}
        self._bake_lock = threading.Lock()
        self._bake_running = False

        # Same adoption contract as the native viewer: the tab container
        # re-parents this label into the panel header bar. Clicking it
        # opens Go to Page (native parity).
        self._page_label = QLabel("", self)
        try:
            from . import theme

            self._page_label.setStyleSheet(
                theme.muted_label_qss(theme.night_mode(), 10)
            )
        except Exception:
            pass
        self._page_label.setVisible(False)
        try:
            self._page_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self._page_label.setToolTip("Go to page (Cmd+Option+G)")
        except Exception:
            pass
        self._page_label.installEventFilter(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._web: Any = None
        try:
            self._web = AnkiWebView(parent=self)
            self._web.set_bridge_command(self._on_bridge, self)
            lay.addWidget(self._web, 1)
        except Exception as exc:
            print(f"[klausmate] pdfjs webview failed: {exc}")
            fallback = QLabel(
                "pdf.js viewer could not start — switch off the pdf.js "
                "viewer in KlausMate Preferences.",
                self,
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            lay.addWidget(fallback, 1)
        self._page_loaded = False

    # Keys the PAGE owns. Without claiming these via ShortcutOverride
    # (the same gotcha the native viewer documents), Anki's window-level
    # QActions fire first: Cmd+/- zooms the WHOLE webview frame (page,
    # sidebar and all) instead of the PDF, and Cmd+F opens the host
    # window's find. Accepting the override delivers the key to the
    # focused webview instead, where the page's JS keydown handler is
    # the single owner of the behaviour.
    _CLAIMED_KEYS: Any = None  # built lazily; Qt enums need aqt present

    def _claimed(self, event: Any) -> bool:
        try:
            if PdfJsViewer._CLAIMED_KEYS is None:
                K, M = Qt.Key, Qt.KeyboardModifier
                ctrl, shift, alt = M.ControlModifier, M.ShiftModifier, M.AltModifier
                PdfJsViewer._CLAIMED_KEYS = {
                    (K.Key_Plus, ctrl), (K.Key_Equal, ctrl),
                    (K.Key_Minus, ctrl), (K.Key_0, ctrl),
                    (K.Key_F, ctrl),
                    (K.Key_G, ctrl), (K.Key_G, ctrl | shift),
                    (K.Key_G, ctrl | alt),
                    (K.Key_H, ctrl | shift), (K.Key_A, ctrl | shift),
                }
            mods = event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.AltModifier
            )
            return (event.key(), mods) in PdfJsViewer._CLAIMED_KEYS
        except Exception:
            return False

    def eventFilter(self, obj: Any, event: Any) -> bool:
        try:
            if obj is self._page_label and event.type() == event.Type.MouseButtonRelease:
                self._goto_dialog()
                return True
            if event.type() == event.Type.ShortcutOverride and self._claimed(event):
                event.accept()
                return True
        except Exception:
            pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def _claim_shortcuts(self) -> None:
        """Filter the webview AND its focusProxy — QWebEngineView routes
        key events through the proxy child, which only exists once the
        page is up, so this is (re)run per load; installEventFilter is
        idempotent."""
        if self._web is None:
            return
        try:
            self._web.installEventFilter(self)
            proxy = self._web.focusProxy()
            if proxy is not None:
                proxy.installEventFilter(self)
        except Exception:
            pass

    # ---- bridge ---------------------------------------------------------

    def _on_bridge(self, cmd: str) -> Any:
        parsed = parse_bridge(cmd)
        if parsed is None:
            return None
        action, payload = parsed
        try:
            handler = getattr(self, f"_bridge_{action.replace('-', '_')}", None)
            if handler is not None:
                handler(payload)
            # "boot" needs no action.
        except Exception as exc:
            print(f"[klausmate] pdfjs bridge {action} error: {exc}")
        return (True, None)

    def _bridge_page(self, payload: str) -> None:
        num, total = payload.split(":", 1)
        try:
            self._page_label.setText(f"{int(num)} / {int(total) or self._page_count}")
        except Exception:
            pass
        self._on_page_changed(int(num) - 1)

    def _bridge_count(self, payload: str) -> None:
        self._page_count = int(payload)
        if self.on_count is not None:
            self.on_count(self._page_count)

    def _bridge_ready(self, _payload: str) -> None:
        # openDocument's teardown() wiped page state — (re)push whatever
        # records we hold so annotations survive load order races.
        self._push_annotations()
        if self._scroll_pos:
            self._eval(f"window.klausScrollTo && window.klausScrollTo({int(self._scroll_pos)});")

    def _bridge_log(self, payload: str) -> None:
        print(f"[klausmate] pdfjs: {payload}")

    def _bridge_scroll(self, payload: str) -> None:
        try:
            self._scroll_pos = int(payload)
        except ValueError:
            pass

    def _bridge_toast(self, payload: str) -> None:
        try:
            text = base64.b64decode(payload).decode("utf-8")
        except Exception:
            return
        if tooltip is not None:
            tooltip(text)

    def _bridge_hl_add(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        records = records_from_rect_map(data.get("pages"))
        if not records:
            return
        self._highlights.extend(records)
        self._save_annotations()
        self._push_annotations()
        if tooltip is not None:
            tooltip("Klaus: highlight added")

    def _bridge_hl_remove(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        hl_id = data.get("id")
        removed = [h for h in self._highlights if h.get("id") == hl_id]
        if not removed:
            return
        self._highlights = [
            h for h in self._highlights if h.get("id") != hl_id
        ]
        # A deleted ADOPTED mark must stay deleted (K-081) — tombstone
        # external records so the next foreign-annotation scan doesn't
        # resurrect them. Same rule as the native viewer's
        # _remove_highlight.
        try:
            rec = removed[0]
            if rec.get("origin") == "external" and self._annotations_name:
                from . import USER_FILES  # type: ignore
                from . import pdf_handler

                pdf_handler.add_suppressed(
                    USER_FILES, self._annotations_name, rec
                )
        except Exception as exc:
            print(f"[klausmate] pdfjs tombstone failed: {exc}")
        self._save_annotations()
        self._push_annotations()

    def _bridge_note_edit(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        hl_id = data.get("id")
        record = next(
            (h for h in self._highlights if h.get("id") == hl_id), None
        )
        if record is None or QInputDialog is None:
            return
        existing = str(record.get("note") or "")
        try:
            if hasattr(QInputDialog, "getMultiLineText"):
                text, ok = QInputDialog.getMultiLineText(
                    self, "Highlight Note", "Note:", existing
                )
            else:
                text, ok = QInputDialog.getText(
                    self, "Highlight Note", "Note:", text=existing
                )
        except Exception as exc:
            print(f"[klausmate] pdfjs note dialog failed: {exc}")
            return
        if not ok:
            return
        record["note"] = str(text).strip()
        self._save_annotations()
        self._push_annotations()

    def _bridge_copy_text(self, payload: str) -> None:
        data = decode_b64_json(payload) or {}
        text = str(data.get("text") or "").strip()
        if text and QApplication is not None:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(text)  # selection copy: silent, Preview-style
                if data.get("toast"):
                    # Menu-driven page capture — parity with the native
                    # viewer's confirmation (critique H1 finding).
                    try:
                        from aqt.utils import tooltip

                        tooltip("Klaus: page text copied")
                    except Exception:
                        pass

    def _bridge_copy_image(self, payload: str) -> None:
        if QImage is None or QApplication is None:
            return
        try:
            raw = base64.b64decode(payload)
        except Exception:
            return
        img = QImage()
        if img.loadFromData(raw, "PNG") and not img.isNull():
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setImage(img)
                if tooltip is not None:
                    tooltip("Klaus: copied as image")

    def _bridge_goto_request(self, _payload: str) -> None:
        self._goto_dialog()

    def _goto_dialog(self) -> None:
        if QInputDialog is None or self._page_count <= 0:
            return
        try:
            page, ok = QInputDialog.getInt(
                self, "Go to Page", f"Page (1–{self._page_count}):",
                1, 1, self._page_count,
            )
        except Exception:
            return
        if ok:
            self.go_to_page(page - 1)

    # ---- annotations persistence ----------------------------------------

    def _push_annotations(self) -> None:
        self._eval(
            "window.klausSetAnnotations && window.klausSetAnnotations("
            + json.dumps(self._highlights)
            + ");"
        )

    def _refresh_highlight_overlay(self) -> None:
        """Duck-typed by shared sidebar code (_reload_records_for's
        post-bake refresh sets ``v._highlights`` then calls this) — for
        this renderer, refreshing the overlay means pushing the records
        to the page."""
        self._push_annotations()

    def _save_annotations(self) -> None:
        """Synchronous write-through + debounced bake (native parity)."""
        if self._annotations_name is None:
            return
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            pdf_handler.save_annotations(
                USER_FILES, self._annotations_name, self._highlights
            )
            self._schedule_bake(USER_FILES, self._annotations_name)
        except Exception as exc:
            print(f"[klausmate] pdfjs save annotations failed: {exc}")

    def _schedule_bake(self, user_files_dir: str, name: str) -> None:
        self._bake_pending[(user_files_dir, name)] = True
        try:
            if self._bake_timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(500)
                timer.timeout.connect(self._on_bake_timer)
                self._bake_timer = timer
            self._bake_timer.start()
        except Exception as exc:
            print(f"[klausmate] pdfjs bake schedule failed: {exc}")

    def _on_bake_timer(self) -> None:
        jobs = list(self._bake_pending.keys())
        self._bake_pending.clear()
        if not jobs:
            return
        with self._bake_lock:
            if self._bake_running:
                # Re-arm; the running bake predates this batch's saves.
                for j in jobs:
                    self._bake_pending[j] = True
                try:
                    self._bake_timer.start()
                except Exception:
                    pass
                return
            self._bake_running = True

        def work() -> None:
            try:
                from . import pdf_handler

                for user_files_dir, name in jobs:
                    try:
                        pdf_handler.bake_annotations(user_files_dir, name)
                    except Exception as exc:
                        print(f"[klausmate] pdfjs bake failed for {name}: {exc}")
            finally:
                with self._bake_lock:
                    self._bake_running = False

        threading.Thread(target=work, daemon=True).start()

    # ---- loading --------------------------------------------------------

    def _eval(self, js: str) -> None:
        if self._web is not None and self._page_loaded:
            try:
                self._web.eval(js)
            except Exception:
                pass

    def _ensure_page(self) -> None:
        if self._page_loaded or self._web is None:
            return
        try:
            from . import theme

            addon = mw.addonManager.addonFromModule(__name__)
            html = build_page_html(addon, theme.night_mode())
            self._web.stdHtml(html, context=self)
            self._page_loaded = True
        except Exception as exc:
            print(f"[klausmate] pdfjs page load failed: {exc}")
            return
        # Frame zoom must stay 1.0 — PDF zoom is the page's own
        # re-render (klausSetZoom), not Chromium magnification.
        try:
            self._web.setZoomFactor(1.0)
        except Exception:
            pass
        self._claim_shortcuts()

    def load_path(self, path: str, name: str) -> None:
        """Read the stored PDF and feed it to pdf.js (chunked base64)."""
        if self._web is None:
            return
        self._ensure_page()
        self._claim_shortcuts()  # focusProxy may only exist by now
        try:
            self._web.setZoomFactor(1.0)
        except Exception:
            pass
        self._name = name
        self._scroll_pos = 0
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > MAX_PDF_MB:
                self._eval(
                    "window.klausPdfError && window.klausPdfError("
                    + json.dumps(
                        f"This PDF is {size_mb:.0f} MB — too large for the "
                        "pdf.js viewer."
                    )
                    + ");"
                )
                return
            with open(path, "rb") as f:
                data = f.read()
        except Exception as exc:
            print(f"[klausmate] pdfjs read failed: {exc}")
            return
        for part in chunk_b64(data):
            self._web.eval(
                "window.klausPdfChunk && window.klausPdfChunk("
                + json.dumps(part)
                + ");"
            )
        self._web.eval("window.klausPdfLoad && window.klausPdfLoad();")

    # ---- PdfViewer-surface parity ---------------------------------------

    def set_page_texts(self, pages: list[str]) -> None:
        # pdf.js extracts its own text layer; retained so the sidebar's
        # call sites stay identical across renderers.
        if self._page_count == 0:
            self._page_count = len(pages)

    def load_annotations(self, name: str) -> None:
        """Load the shared annotations JSON and push it to the page."""
        self._annotations_name = name
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            self._highlights = pdf_handler.load_annotations(USER_FILES, name)
        except Exception as exc:
            print(f"[klausmate] pdfjs annotations load failed: {exc}")
            self._highlights = []
        self._push_annotations()
        self._start_foreign_mirror(name)

    # ---- outside-annotation mirror (K-082) -------------------------------
    # PdfSidebar's external-change poller duck-types the viewer: it calls
    # v._apply_mirror(name, res) on whichever renderer is active (this
    # crashed live as AttributeError until PdfJsViewer grew the method).
    # The scan/merge machinery is pdf_handler's and fully shared; only
    # the last hop — putting refreshed records on screen — differs, and
    # here that is a push through klausSetAnnotations.

    def _apply_mirror(self, name: str, res: dict) -> None:
        """Main-thread half of the mirror: records follow the file for
        outside marks. Schedules NO bake — the file already holds those
        marks, and baking here would re-feed the watcher loop."""
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler

            changed = pdf_handler.mirror_foreign_annotations(
                USER_FILES, name, res
            )
            if not changed:
                return
            if self._annotations_name == name:
                self._highlights = pdf_handler.load_annotations(
                    USER_FILES, name
                )
                self._push_annotations()
                if tooltip is not None:
                    tooltip(f"Klaus: synced {changed} outside change(s)")
        except Exception as exc:
            print(f"[klausmate] pdfjs mirror apply failed: {exc}")

    def _start_foreign_mirror(self, name: str) -> None:
        """Scan the working PDF for outside text/highlights on a daemon
        thread (multi-MB pypdf parse must never block the UI); the
        merge/save hops back to the main thread so it cannot race the
        synchronous _save_annotations writes. Same shape as the native
        viewer's method."""
        try:
            from . import USER_FILES  # type: ignore
            from . import pdf_handler
        except Exception:
            return
        if not getattr(pdf_handler, "BAKE_AVAILABLE", False):
            return

        def _worker() -> None:
            try:
                res = pdf_handler.scan_working_annotations(USER_FILES, name)
                if res is None:
                    return
                if res.get("foreign"):
                    working = pdf_handler._working_pdf_path(USER_FILES, name)
                    if not pdf_handler._capture_pristine_stripped(
                        USER_FILES, name, working
                    ):
                        return
                if mw is not None:
                    mw.taskman.run_on_main(
                        lambda: self._apply_mirror(name, res)
                    )
            except Exception as exc:
                print(f"[klausmate] pdfjs mirror scan failed: {exc}")

        threading.Thread(
            target=_worker, name="klausmate-pdfjs-extmirror", daemon=True
        ).start()

    def set_document(self, *_a: Any) -> None:
        pass  # native-renderer concept; load_path is the pdfjs entry

    def clear_document(self) -> None:
        self._name = None
        self._annotations_name = None
        self._highlights = []
        self._page_count = 0
        self._scroll_pos = 0
        self._eval(
            "(function(){var p=document.getElementById('pages');"
            "if(p)p.textContent='';})();"
        )

    def go_to_page(self, page: int) -> None:
        self._eval(
            f"window.klausGoToPage && window.klausGoToPage({int(page) + 1});"
        )

    def scroll_position(self) -> int:
        return self._scroll_pos

    def restore_scroll_position(self, pos: Any) -> None:
        try:
            y = int(pos)
        except (TypeError, ValueError):
            return
        self._scroll_pos = y
        self._eval(f"window.klausScrollTo && window.klausScrollTo({y});")

    def toggle_thumbnails(self) -> None:
        self._eval("window.klausToggleThumbs && window.klausToggleThumbs();")

    def cleanup(self) -> None:
        """Unregister the webview from Anki's global hooks BEFORE its
        C++ object dies.

        ``AnkiWebView.__init__`` appends ``on_theme_did_change`` to
        ``gui_hooks.theme_did_change`` (and other global hooks) and only
        ``AnkiWebView.cleanup()`` removes them — Anki even logs
        "destroyed without a cleanup() call" for the ones it catches.
        A webview destroyed without it leaves a dead bound method in
        that hook, so the user's NEXT theme change crashes inside
        Anki's own iteration with "wrapped C/C++ object of type
        AnkiWebView has been deleted" (live traceback 2026-08-25:
        Library window closed, then the theme was switched). Idempotent
        and safe to call twice.
        """
        web, self._web = self._web, None
        self._page_loaded = False
        if web is None:
            return
        try:
            web.cleanup()
        except Exception as exc:
            print(f"[klausmate] pdfjs webview cleanup failed: {exc}")
