"""The occlusion editor's Draw tab. Klaus addition (not part of IOE).

"Draw a diagram…" opens IOE's own editor (ImgOccEdit) on blank_png() with a
third tab, Draw: DrawTab, an Excalidraw webview (excalidraw/, built by
scripts/build_excalidraw.sh) with a Qt "Use drawing" button under it. The
button asks the page to export; the page answers
pycmd("klausexcal:occlude:<base64 JSON>") with {png, scene, originX,
originY, width, height} or {error}. prepare_occlusion turns a good answer
into the PNG, IOE's mask SVG (one mask per text label, excal_masks) and the
sidecar JSON that is saved as "_<image media name>.excalidraw" once IOE has
added or updated the notes (ImgOccAdd.use_drawing / _onAddNotesButton /
_onEditNotesButton). The leading underscore keeps Check Media from listing
it as unused; read_diagram reads it back for re-editing in edit mode.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import os
import tempfile
import time
from typing import Callable, Optional

from aqt import mw
from aqt.qt import QColor, QHBoxLayout, QImage, QPushButton, Qt, QUrl, QVBoxLayout, QWidget
from aqt.utils import tooltip
from aqt.webview import AnkiWebPage, AnkiWebView

from .excal_masks import MAX_SIDE, label_rects, masks_svg, png_size

# entry.jsx exports at these; label masks get MARGIN image px around the text.
PADDING, SCALE, MARGIN = 20, 2, 4
# The page's folder on Anki's add-on server, from this package's own name
# (as consts.MODULE_ADDON is): "klaus_note", or an AnkiWeb install's number.
PAGE_DIR = "/_addons/%s/excalidraw/" % "/".join(__name__.split(".")[:-1])
PREFIX = "klausexcal:"
EMPTY_TIP = "Draw something first, then press Use drawing"


def blank_png(tmpdir: str) -> str:
    """An 800×600 white PNG in tmpdir: the image a draw session opens on."""
    path = os.path.join(tmpdir, "blank.png")
    img = QImage(800, 600, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    if not img.save(path, "PNG"):
        raise OSError("could not write " + path)
    return path


def _error_text(error) -> str:
    if error == "empty":
        return EMPTY_TIP
    return "Klaus: couldn't export the drawing (%s)" % error


def prepare_occlusion(result: dict, tmpdir: str, fill: str, stroke: str) -> tuple[str, str, str]:
    """(png_path, svg_path, sidecar_json) for a page result. ValueError,
    with the message to show, when there is nothing usable; nothing is
    written then. Each use gets its own folder under tmpdir, so two uses in
    one second never share a file (svg-edit would show the cached one)."""
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError(_error_text(result.get("error") if isinstance(result, dict) else "?"))
    scene = result.get("scene")
    if not isinstance(scene, dict) or not any(
            not el.get("isDeleted") for el in scene.get("elements") or []):
        raise ValueError(EMPTY_TIP)
    try:
        png = base64.b64decode(result.get("png") or "", validate=True)
    except (binascii.Error, ValueError, TypeError):
        png = b""
    try:
        width, height = png_size(png)
    except ValueError:
        raise ValueError("Klaus: the drawing didn't export as an image") from None
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError(
            "Klaus: the drawing is too large to occlude (%d × %d px, at most %d a side). "
            "Make it smaller and press Use drawing again." % (width, height, MAX_SIDE))
    try:
        ox, oy = float(result["originX"]), float(result["originY"])
    except (KeyError, TypeError, ValueError):
        ox = oy = math.nan
    if not (math.isfinite(ox) and math.isfinite(oy)):
        raise ValueError("Klaus: the drawing came back without its position; "
                         "press Use drawing again")
    folder = tempfile.mkdtemp(dir=tmpdir)
    stem = time.strftime("diagram-%Y%m%d-%H%M%S")
    png_path = os.path.join(folder, stem + ".png")
    svg_path = os.path.join(folder, stem + "-masks.svg")
    with open(png_path, "wb") as f:
        f.write(png)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(masks_svg(width, height, label_rects(scene, ox, oy, PADDING, SCALE, MARGIN),
                          fill, stroke))
    sidecar = json.dumps({"type": "excalidraw", **scene,
                          "klaus": {"originX": ox, "originY": oy,
                                    "padding": PADDING, "scale": SCALE}})
    return png_path, svg_path, sidecar


def read_diagram(media_dir: str, image_name: str) -> Optional[dict]:
    """The scene saved beside image_name (media's _<image_name>.excalidraw,
    with its klaus block), or None when it is missing or unreadable: then the
    note stays an ordinary image occlusion."""
    try:
        with open(os.path.join(media_dir, "_" + image_name + ".excalidraw"),
                  encoding="utf-8") as f:
            data = json.load(f)
        meta = data["klaus"]
        if isinstance(data.get("elements"), list) and all(
                math.isfinite(float(meta[k])) for k in ("originX", "originY", "padding", "scale")):
            return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def theme_css() -> str:
    """Klaus's accent and UI font as Excalidraw's CSS variables (light: the
    canvas and its export are always light). #root beats .theme--dark."""
    from .. import theme

    c = theme.palette(False)
    return (
        "#root .excalidraw{"
        "--color-primary:%s;--color-primary-darker:%s;--color-primary-darkest:%s;"
        "--color-primary-hover:%s;--color-primary-light:%s;--color-primary-light-darker:%s;"
        "--ui-font:%s}"
        % (c["blue_accent"], c["blue_hover"], c["blue_pressed"], c["blue_hover"],
           theme.accent_rgba(False, 0.16), theme.accent_rgba(False, 0.28), theme.FONT_FAMILY))


class DrawPage(AnkiWebPage):
    def acceptNavigationRequest(self, url, navType, isMainFrame):
        # The page itself only, on Anki's own server. Excalidraw's links
        # (GitHub, help, libraries, embeds) never leave the tab and never
        # reach the system browser.
        server = QUrl(mw.serverURL())
        return (url.scheme() == server.scheme() and url.host() == server.host()
                and url.port() == server.port() and url.path().startswith(PAGE_DIR))


class DrawWebView(AnkiWebView):
    def createWindow(self, windowType):
        return None  # target=_blank: no new window

    def onEsc(self):
        # Escape leaves Excalidraw's text editing; Anki's default would
        # close the whole occlusion editor and lose the drawing.
        pass


class DrawTab(QWidget):
    """The Draw tab: Excalidraw, and "Use drawing" under it."""

    def __init__(self, parent: QWidget, on_use: Callable[[dict], bool]) -> None:
        super().__init__(parent)
        self._on_use: Optional[Callable[[dict], bool]] = on_use
        self._ready = False
        # Changed since the last Use drawing (or load). The page says so once
        # per change through klausexcal:dirty: its scene version, the sum of
        # the element versions, moved away from the one it last exported.
        self.dirty = False
        self.edits = 0  # dirty messages so far: a change during a pending use
        self._load_js: Optional[str] = None
        self.web = DrawWebView(parent=self)
        self.web._page = DrawPage(self.web._onBridgeCmd)
        self.web.setPage(self.web._page)
        self.web.set_bridge_command(self._on_bridge, self)
        self.use_btn = QPushButton("Use drawing")
        self.use_btn.setAutoDefault(False)
        self.use_btn.setToolTip("Use this drawing as the image; its text labels become masks")
        self.use_btn.clicked.connect(self.use)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.use_btn)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.web, 1)
        box.addLayout(row)
        self.web.setUrl(QUrl(mw.serverURL().rstrip("/") + PAGE_DIR + "index.html"))

    def load(self, scene: Optional[dict]) -> None:
        """Show scene (None: an empty canvas), once the page is ready. The
        loaded scene is the clean state."""
        self.dirty = False
        arg = json.dumps(json.dumps(scene) if scene is not None else None)
        self._load_js = "klausExcalidraw.load(%s);" % arg
        if self._ready:
            self.web.eval(self._load_js)

    def mark_used(self, edits: int) -> None:
        """The drawing taken when `edits` dirty messages had come has landed:
        clean, unless the page reported a change since."""
        if self.edits == edits:
            self.dirty = False

    def use(self, *_args) -> None:
        if self._on_use is None or not self._ready:
            return
        self.web.eval("klausExcalidraw.occlude();")

    def keyPressEvent(self, event) -> None:
        # Escape the canvas did not use must not travel on to the dialog
        # (QDialog would reject, i.e. close): the Draw tab never closes the window.
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    def shutdown(self) -> None:
        """The editor closed: drop late answers (Review Focus 4)."""
        self._on_use = None

    def _on_bridge(self, cmd: str):
        if not cmd.startswith(PREFIX) or self._on_use is None:
            return None
        try:
            action, _, payload = cmd[len(PREFIX):].partition(":")
            data = json.loads(base64.b64decode(payload).decode("utf-8")) if payload else {}
            if action == "ready":
                self._ready = True
                self.web.eval(
                    "(function(){var s=document.createElement('style');s.textContent=%s;"
                    "document.head.appendChild(s);})();" % json.dumps(theme_css()))
                if self._load_js:
                    self.web.eval(self._load_js)
            elif action == "dirty":
                self.dirty = True
                self.edits += 1
            elif action == "occlude":
                if not isinstance(data, dict) or data.get("error"):
                    tooltip(_error_text(data.get("error") if isinstance(data, dict) else "?"),
                            parent=self)
                    return None
                self._on_use(data)  # it marks the drawing used once it lands
        except Exception as exc:  # a slot exception would abort Anki
            print(f"[klaus_note] draw tab: {cmd[:40]}: {type(exc).__name__}: {exc}")
        return None
