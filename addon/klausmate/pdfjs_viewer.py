"""pdf.js-backed PDF viewer (K-095/K-096) — the flicker fix.

QPdfView flickers structurally: pdfium delivers page bitmaps async (blank
flash on scroll/zoom) and the Python-side selection overlay repaints in a
separate pass from the viewport. This module hosts ``web/pdfjs_viewer.html``
(vendored pdf.js 3.11.174 in ``web/pdfjs/``) in an AnkiWebView instead:
canvases are GPU-composited by Chromium, scrolling translates
already-rendered layers, and the text layer gives native browser selection.

Selected by config key ``pdf_renderer`` (``"native"`` default until parity
— see the K-095 umbrella card; flip is K-101). ``PdfSidebar`` branches on
:func:`renderer_from_config` at construction.

Feed pattern (SynapsePro's, notebook_sidebar._render_pdf_inline): read the
file in Python, base64, push into window globals in chunks (one giant
``eval`` string is fragile), then trigger the load. Pure helpers
(:func:`renderer_from_config`, :func:`chunk_b64`, :func:`build_page_html`)
stay aqt-free for the headless tests; only :class:`PdfJsViewer` needs Qt.

The annotations JSON and bake pipeline are renderer-independent and are
NOT touched by this module (highlights land in K-098).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Optional

# Guarded Qt imports — headless tests import this module with stub aqt.
try:
    from aqt import mw
    from aqt.qt import (
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
        Qt,
    )
    from aqt.webview import AnkiWebView

    PDFJS_AVAILABLE = True
except Exception:  # pragma: no cover — only in stripped test stubs
    mw = None  # type: ignore[assignment]
    QLabel = QSizePolicy = QVBoxLayout = QWidget = Qt = None  # type: ignore
    AnkiWebView = None  # type: ignore[assignment]
    PDFJS_AVAILABLE = False


# ~6 MB of base64 per eval call: large enough that a lecture PDF loads in
# a handful of calls, small enough that no single eval string is huge.
CHUNK_CHARS = 6 * 1024 * 1024

# Refuse beyond this — base64 inflates 4/3 and the whole document lives
# in webview memory (SynapsePro guards at a lower bound and asks; a
# standalone viewer shows the error inline instead).
MAX_PDF_MB = 200

_BRIDGE_PREFIX = "klausmate_pdfjs:"


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
    """Base64-encode *data* and split into eval-sized string chunks.

    Splitting the *encoded* string (not the raw bytes) keeps every chunk
    boundary safe — base64 can only be decoded once reassembled, which
    the JS side does with a plain join.
    """
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    b64 = base64.b64encode(data).decode("ascii")
    return [b64[i : i + chunk_chars] for i in range(0, len(b64), chunk_chars)]


def build_page_html(addon_name: str, night: bool) -> str:
    """The viewer page with both substitutions applied.

    Reads ``web/pdfjs_viewer.html`` next to this file and fills
    ``__ADDON__`` (web-export URL segment) and ``__THEME_VARS__``
    (theme tokens as CSS custom properties).
    """
    from . import theme

    path = os.path.join(os.path.dirname(__file__), "web", "pdfjs_viewer.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ADDON__", addon_name)
    html = html.replace("__THEME_VARS__", theme.css_vars(night))
    return html


class PdfJsViewer(QWidget):  # type: ignore[misc]
    """Drop-in for ``PdfViewer`` behind the ``pdf_renderer`` flag.

    Matches the surface PdfSidebar and the tab container actually use:
    ``load_path`` (the pdf.js-native entry — the sidebar calls it instead
    of ``set_document``), ``set_page_texts``, ``load_annotations``,
    ``clear_document``, ``go_to_page``, ``scroll_position``,
    ``toggle_thumbnails`` and ``_page_label``. Annotations/thumbnails are
    accepted-and-ignored stubs until their parity cards (K-098/K-099).
    """

    def __init__(
        self,
        on_page_changed: Callable[[int], None],
        parent: Optional[QWidget] = None,  # type: ignore[valid-type]
    ) -> None:
        super().__init__(parent)
        self._on_page_changed = on_page_changed
        self._name: str | None = None
        self._page_count = 0
        self._scroll_pos = 0
        self.on_count: Optional[Callable[[int], None]] = None

        # Same adoption contract as the native viewer: the tab container
        # re-parents this label into the panel header bar.
        self._page_label = QLabel("", self)
        try:
            from . import theme

            self._page_label.setStyleSheet(
                theme.muted_label_qss(theme.night_mode(), 10)
            )
        except Exception:
            pass
        self._page_label.setVisible(False)

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
                "pdf.js viewer could not start — set pdf_renderer to "
                '"native" in the addon config.',
                self,
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setWordWrap(True)
            lay.addWidget(fallback, 1)
        self._page_loaded = False

    # ---- bridge ---------------------------------------------------------

    def _on_bridge(self, cmd: str) -> Any:
        if not cmd.startswith(_BRIDGE_PREFIX):
            return None
        msg = cmd[len(_BRIDGE_PREFIX):]
        try:
            if msg.startswith("page:"):
                _, num, total = msg.split(":", 2)
                self._update_page_label(int(num), int(total))
            elif msg.startswith("count:"):
                self._page_count = int(msg.split(":", 1)[1])
                if self.on_count is not None:
                    self.on_count(self._page_count)
            elif msg.startswith("log:"):
                print(f"[klausmate] pdfjs: {msg[4:]}")
            # "boot"/"ready" need no action yet.
        except Exception as exc:
            print(f"[klausmate] pdfjs bridge error: {exc}")
        return (True, None)

    def _update_page_label(self, num: int, total: int) -> None:
        try:
            self._page_label.setText(f"{num} / {total or self._page_count}")
            self._on_page_changed(num - 1)
        except Exception:
            pass

    # ---- loading --------------------------------------------------------

    def _ensure_page(self) -> None:
        """Load the viewer HTML once, lazily, on first use."""
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

    def load_path(self, path: str, name: str) -> None:
        """Read the stored PDF and feed it to pdf.js (chunked base64)."""
        if self._web is None:
            return
        self._ensure_page()
        self._name = name
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > MAX_PDF_MB:
                self._web.eval(
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
        # pdf.js extracts its own text layer; retained only so the
        # sidebar's call sites stay identical across renderers.
        if self._page_count == 0:
            self._page_count = len(pages)

    def load_annotations(self, *_a: Any, **_k: Any) -> None:
        pass  # K-098 (highlights parity)

    def set_document(self, *_a: Any) -> None:
        pass  # native-renderer concept; load_path is the pdfjs entry

    def clear_document(self) -> None:
        self._name = None
        self._page_count = 0
        if self._web is not None and self._page_loaded:
            try:
                self._web.eval(
                    "window.klausPdfError && (function(){"
                    "document.getElementById('pages').textContent='';})();"
                )
            except Exception:
                pass

    def go_to_page(self, page: int) -> None:
        if self._web is not None and self._page_loaded:
            try:
                self._web.eval(
                    f"window.klausGoToPage && window.klausGoToPage({int(page) + 1});"
                )
            except Exception:
                pass

    def scroll_position(self) -> int:
        return self._scroll_pos

    def toggle_thumbnails(self) -> None:
        pass  # K-099 (find/thumbnails parity)
