"""KlausMate — semantic lecture-PDF library for Anki.

Bootstrap and Qt glue for the add-on: the PDF viewer panel and its tabs,
the editor's PDF bar, image cropping, and the Browse toolbar toggles.
Embeddings power the rest — see curation.py (the card index),
retention.py, and pdf_drive.py (the Library).
"""

from __future__ import annotations

import base64
import html as html_mod
import json
import os
import re
import traceback
import urllib.parse
from typing import Any

from aqt import gui_hooks, mw
from aqt.editor import Editor, EditorWebView
from aqt.qt import (
    QAction,
    QDockWidget,
    QEvent,
    QHBoxLayout,
    QImage,
    QLabel,
    QMenu,
    QRect,
    QTimer,
    QToolButton,
    QWidget,
    Qt,
)
from aqt.utils import showWarning, tooltip
from aqt.webview import WebContent

from . import pdf_handler
from .manage_models import manage_models_dialog
from .slot_guard import guarded as _guarded
from .browse_toggles import on_browser_will_show
from .setup_flow import first_run_check, setup_readiness_check
from . import settings

ADDON_DIR = os.path.dirname(__file__)

# The settings seam (settings.py): Anki's addon manager is the store, a
# background patch hops through the task manager, and a patch that hops is
# dropped if the profile changed before it landed.
settings.store = settings.AnkiStore(mw.addonManager, __name__)
settings.run_on_main = mw.taskman.run_on_main
settings.current_profile = lambda: getattr(mw, "col", None)


# Retired config keys, scrubbed from old profiles on next launch. Covers the
# old chat_* -> klaus_* rename pairs (both sides are now dead -- no renaming,
# just dropped) plus every key the removed autocomplete/Ask/Browse-search
# features owned.


# ----------------------------- card context ------------------------------


def _strip_html(s: str) -> str:
    """Strip HTML tags so sibling-field content goes into prompts as plain text."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</?(div|p|span|li|ul|ol|h[1-6])\b[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    # Common HTML entities (don't pull in html.parser just for this).
    s = (s.replace("&nbsp;", " ")
           .replace("&amp;", "&")
           .replace("&lt;", "<")
           .replace("&gt;", ">")
           .replace("&quot;", '"'))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _set_target_field(editor: Editor, field_name: str) -> None:
    """Point Anki's own ``editor.currentField`` at the field the user last
    clicked, for PDF page insert.

    That assignment is the WHOLE mechanism: Anki's own attribute is what
    carries the target from here on. Klaus used to shadow it with two
    private per-editor attributes (the field's index and its name, plus a
    default-init at editor setup); every one of them was write-only once
    autocomplete/Ask were removed, and K-140 deleted all four sites. Don't
    re-add a Klaus-side copy — nothing downstream wants one: image crop
    rewrites by scanning every entry of ``note.fields``, and PDF page
    insert travels through the system clipboard.
    """
    if not field_name:
        return
    idx: int | None = None
    try:
        note = getattr(editor, "note", None)
        if note is not None:
            nt = note.note_type() if hasattr(note, "note_type") else note.model()
            if nt:
                names = [f.get("name", "") for f in nt.get("flds", [])]
                if field_name in names:
                    idx = names.index(field_name)
    except Exception:
        pass
    if idx is not None:
        try:
            editor.currentField = idx
        except Exception:
            pass


# One-time-per-session guard for the sidebar self-heal. A prior broken
# build of this add-on could persist a zero-width / detached sidebar into
# the profile; we force it back open the first time Browse opens in a
# session, then respect the user's toggle on every subsequent open so the
# sidebar toggle button's state actually sticks.
_KLAUS_BROWSE_LAYOUT_HEALED = False


def _reset_browse_layout_to_defaults(browser: Any) -> None:
    """Force the Browse window's sidebar + splitter back to Anki's stock
    layout, undoing any leftover state from the now-removed dock-
    wrapping helpers.

    Anki persists ``QMainWindow.saveState()`` + ``QSplitter.saveState()``
    to the user's profile on browser close (see
    ``aqt/browser/browser.py:433-434``). If a previous build of this
    add-on moved the sidebar around or collapsed the editor splitter,
    that broken layout is restored on every subsequent open even after
    the offending code is gone. This helper re-anchors the sidebar to
    the side Anki originally docked it on and reinstates a sane
    splitter ratio if one pane is collapsed.

    On browser close, Anki re-saves the corrected state — so after one
    open this normally only no-ops on subsequent runs.
    """
    # ---- sidebar ----
    global _KLAUS_BROWSE_LAYOUT_HEALED
    dock = getattr(browser, "sidebarDockWidget", None)
    if dock is not None:
        try:
            # Snapshot the visibility Anki restored from the profile (or
            # the user last chose) BEFORE we touch the dock — addDockWidget
            # can implicitly re-show a hidden dock.
            was_visible = dock.isVisible()
            rtl = (
                browser.layoutDirection()
                == Qt.LayoutDirection.RightToLeft
            )
            area = (
                Qt.DockWidgetArea.RightDockWidgetArea
                if rtl
                else Qt.DockWidgetArea.LeftDockWidgetArea
            )
            # Restore Anki's original constraints (in case a prior
            # build of this add-on unlocked them).
            dock.setAllowedAreas(area)
            dock.setFloating(False)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
            # Re-anchor to the correct side regardless of the layout
            # restoreState() pulled out of the profile.
            browser.addDockWidget(area, dock)
            # Anki uses an empty title-bar widget to suppress the
            # drag-handle. Re-establish that.
            dock.setTitleBarWidget(QWidget())
            if not _KLAUS_BROWSE_LAYOUT_HEALED:
                # First Browse open this session: force the sidebar open
                # once to self-heal any zero-width/hidden state left by an
                # earlier build.
                dock.setVisible(True)
                _KLAUS_BROWSE_LAYOUT_HEALED = True
            else:
                # Subsequent opens: preserve the user's last choice so the
                # sidebar toggle button's state persists across reopens.
                dock.setVisible(was_visible)
            print("[klausmate] sidebar re-anchored to default position")
        except Exception as exc:
            print(f"[klausmate] sidebar reset failed: {exc}")

    # ---- editor splitter ----
    form = getattr(browser, "form", None)
    splitter = getattr(form, "splitter", None) if form is not None else None
    if splitter is not None and splitter.count() >= 2:
        try:
            sizes = list(splitter.sizes())
            # A pane of < 4 px is a degenerate state — likely a leftover
            # from when the editor was extracted into a dock and the
            # splitter was forced to [width, 0]. Restore the form's
            # ~3:1 default ratio.
            if any(s < 4 for s in sizes):
                total = max(1, sum(sizes)) or 800
                splitter.setSizes(
                    [int(total * 0.75), int(total * 0.25)]
                )
                print(
                    f"[klausmate] editor splitter reset from {sizes} "
                    "to 3:1 default"
                )
        except Exception as exc:
            print(f"[klausmate] editor splitter reset failed: {exc}")


# ----------------------------- web injection ------------------------------


def on_webview_will_set_content(web_content: WebContent, context: Any) -> None:
    if not isinstance(context, Editor):
        return
    pkg = mw.addonManager.addonFromModule(__name__)
    # ?v=<mtime>: QtWebEngine caches /_addons/ assets ACROSS RESTARTS, so
    # without a changing URL the page can keep running a stale copilot.js
    # long after the file changed on disk (K-066 — a click fix shipped
    # twice and never reached the page).
    try:
        _cop_v = int(os.path.getmtime(os.path.join(ADDON_DIR, "web", "copilot.js")))
    except Exception:
        _cop_v = 0
    web_content.js.append(f"/_addons/{pkg}/web/copilot.js?v={_cop_v}")
    # Inject runtime config so JS can read feature toggles.
    cfg = settings.read()
    runtime = {
        "image_crop_enabled": bool(cfg.get("image_crop_enabled", True)),
    }
    # "</" → "<\/" so a pathological config string can't terminate the
    # script block and dump the rest of the config as page text.
    blob = json.dumps(runtime).replace("</", "<\\/")
    web_content.head += f"<script>window.klausmateConfig = {blob};</script>"


# ----------------------------- pycmd routing ------------------------------


def on_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    if not message.startswith("klausmate:"):
        return handled
    if not isinstance(context, Editor):
        return (True, None)

    try:
        _, action, payload = message.split(":", 2)
    except ValueError:
        return (True, None)

    if action == "focus":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            field_name = str(data.get("field", "")).strip()
        except Exception:
            return (True, None)
        _set_target_field(context, field_name)
        return (True, None)

    if action == "crop":
        try:
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            fname = str(data.get("fname", "")).strip()
        except Exception:
            return (True, None)
        if fname and bool(settings.read().get("image_crop_enabled", True)):
            editor = context
            # Defer so the modal exec() doesn't run inside the webchannel
            # message handler (mirrors the singleShot pattern at editor init).
            QTimer.singleShot(0, lambda: _launch_crop_dialog(editor, fname))
        return (True, None)

    if action == "library":
        editor = context
        # Defer: _on_library_button can exec a QMenu (nested event loop),
        # which must not run inside the webchannel message handler.
        QTimer.singleShot(0, lambda: _on_library_button(editor))
        return (True, None)

    return (True, None)


# ----------------------------- image crop ---------------------------------


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(
    r"""(\bsrc\s*=\s*)("([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE
)


def _replace_img_src(
    html_text: str, old_fname: str, new_fname: str
) -> tuple[str, bool]:
    """Point every ``<img src>`` matching ``old_fname`` at ``new_fname``.

    Anki stores DECODED filenames in note fields (``reverse_url_quoting``
    unescapes on save), so we compare both the raw src and its
    percent-decoded form against ``old_fname`` — and additionally the
    HTML-entity-unescaped forms, because field HTML entity-escapes
    attribute values (a file named ``foo&bar.png`` is stored as
    ``src="foo&amp;bar.png"``). Returns ``(html, changed)``.
    """
    changed = False

    def fix_src(m: re.Match[str]) -> str:
        nonlocal changed
        raw = m.group(3) or m.group(4) or m.group(5) or ""
        try:
            decoded = urllib.parse.unquote(raw)
        except Exception:
            decoded = raw
        candidates = {raw, decoded}
        try:
            candidates.add(html_mod.unescape(raw))
            candidates.add(html_mod.unescape(decoded))
        except Exception:
            pass
        if old_fname not in candidates:
            return m.group(0)
        changed = True
        # Emit the canonical stored form: double-quoted, decoded,
        # entity-escaped so special chars round-trip through Anki's
        # field serialization (write_data-sanitized names contain no
        # quotes, but may contain e.g. '&').
        return f'{m.group(1)}"{html_mod.escape(new_fname, quote=True)}"'

    def fix_tag(m: re.Match[str]) -> str:
        return _SRC_ATTR_RE.sub(fix_src, m.group(0))

    return _IMG_TAG_RE.sub(fix_tag, html_text), changed


def _launch_crop_dialog(editor: Editor, fname: str) -> None:
    """Open the crop dialog for ``fname`` and apply the crop to the note.

    Shared by the context-menu and double-click triggers. The crop is
    always saved as a NEW media file; the original is never touched.
    """
    try:
        if editor.note is None:
            tooltip("Klaus: no note loaded", parent=editor.widget)
            return
        if getattr(editor, "_klausmate_crop_open", False):
            return
        # fname crosses the JS trust boundary — allow bare filenames
        # only (the media folder is flat, so that is always correct).
        if (
            not fname
            or "/" in fname
            or "\\" in fname
            or ".." in fname
        ):
            tooltip("Klaus: invalid image filename", parent=editor.widget)
            return
        path = os.path.join(editor.mw.col.media.dir(), fname)
        if not os.path.isfile(path):
            tooltip(
                f"Klaus: image not found: {fname}", parent=editor.widget
            )
            return
        image = QImage(path)
        if image.isNull():
            tooltip(
                "Klaus: could not load image (unsupported format)",
                parent=editor.widget,
            )
            return
        from .crop_dialog import ImageCropDialog, encode_cropped

        dlg = ImageCropDialog(image, fname, parent=editor.parentWindow)

        def on_accepted() -> None:
            try:
                cropped = dlg.cropped_image()
                if cropped is None or cropped.isNull():
                    return
                stem, _, ext = fname.rpartition(".")
                if not stem:
                    stem, ext = fname, ""
                data, out_ext = encode_cropped(cropped, ext)
                new_fname = editor.mw.col.media.write_data(
                    f"{stem}_crop.{out_ext}", data
                )

                def apply_to_note() -> None:
                    try:
                        note = editor.note
                        if note is None:
                            return  # editor closed while the dialog was up
                        any_change = False
                        for i, field_html in enumerate(note.fields):
                            new_html, field_changed = _replace_img_src(
                                field_html, fname, new_fname
                            )
                            if field_changed:
                                note.fields[i] = new_html
                                any_change = True
                        if not any_change:
                            tooltip(
                                f"Klaus: saved {new_fname}, but the note's "
                                "HTML doesn't reference the original image",
                                parent=editor.widget,
                            )
                            return
                        if not editor.addMode:
                            # Persist; initiator=editor so no auto-reload.
                            editor._save_current_note()
                        editor.loadNoteKeepingFocus()
                        tooltip(
                            f"Klaus: cropped image saved as {new_fname}",
                            parent=editor.widget,
                        )
                    except Exception as e:
                        print(
                            "[klausmate] crop apply failed: "
                            f"{type(e).__name__}: {e}"
                        )
                        traceback.print_exc()

                # Flush pending in-webview edits into note.fields FIRST
                # (call_after_note_saved evals JS saveNow(); key:/blur:
                # bridge cmds land in note.fields via onBridgeCmd before
                # the callback fires), THEN mutate the fields.
                editor.call_after_note_saved(apply_to_note, keepFocus=True)
            except Exception as e:
                print(f"[klausmate] crop failed: {type(e).__name__}: {e}")
                traceback.print_exc()

        @_guarded
        def on_finished(_r: int) -> None:
            # The open-guard spans the DIALOG'S lifetime now, not this
            # call's — reset here, where exec()'s finally used to.
            editor._klausmate_crop_open = False  # type: ignore[attr-defined]
            dlg.deleteLater()

        # K-114: window-modal open() + signal callbacks, never app-modal
        # exec() (the macOS 26 + Qt 6.11 segfault class; see
        # test_bridge_reentrancy). finished fires before accepted, but
        # deleteLater only lands once control returns to the event loop,
        # so on_accepted still sees a live dialog. The guard is set AFTER
        # open() succeeds: nothing can re-enter in between on one thread,
        # and a failed open() then can't strand the flag True.
        dlg.accepted.connect(on_accepted)
        dlg.finished.connect(on_finished)
        dlg.open()
        editor._klausmate_crop_open = True  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[klausmate] crop failed: {type(e).__name__}: {e}")
        traceback.print_exc()


def on_editor_context_menu(webview: EditorWebView, menu: QMenu) -> None:
    """Add "Crop Image" when the editor context menu opened on an <img>."""
    try:
        if not bool(settings.read().get("image_crop_enabled", True)):
            return
        editor = getattr(webview, "editor", None)
        if editor is None or editor.note is None:
            return
        if not hasattr(webview, "lastContextMenuRequest"):
            return  # older Anki without QWebEngineContextMenuRequest
        req = webview.lastContextMenuRequest()
        if req is None or req.mediaType() != req.MediaType.MediaTypeImage:
            return
        fname = req.mediaUrl().fileName()  # QUrl.fileName() -> decoded
        if not fname:
            return  # data: URIs / mathjax have no filename
        action = menu.addAction("Crop Image")
        action.triggered.connect(
            lambda _=False, e=editor, f=fname: _launch_crop_dialog(e, f)
        )
    except Exception as e:
        print(f"[klausmate] crop context menu failed: {type(e).__name__}: {e}")


# ----------------------------- menu / setup -------------------------------


def open_config() -> None:
    manage_models_dialog()


def install_menu() -> None:
    """Single Tools-menu entry point, at the top of the menu.

    Everything that used to live in a 'Klaus' submenu (Clear library tag,
    Manage models…, Check Connection) now lives inside the KlausMate
    Preferences dialog itself (manage_models.py) — a menu that only ever
    grows one deeper is still one click, and it keeps this menu from
    forking into a second place users have to think to look. Anki has
    already populated menuTools by the time main_window_did_init fires,
    so insertAction against its current first action is what puts us
    ahead of Anki's own items rather than appending after them.
    """
    menu = mw.form.menuTools
    action = QAction("KlausMate Preferences…", mw)
    action.triggered.connect(manage_models_dialog)
    existing_actions = menu.actions()
    if existing_actions:
        menu.insertAction(existing_actions[0], action)
    else:
        menu.addAction(action)


# ------------------------------ PDF import -------------------------------


def import_pdf_file(path: str) -> str | None:
    """Import one PDF into the store; returns its safe name, or None.

    Shared by every import surface (editor drop bar, deck-screen drop,
    drive window). Warnings are shown here, so callers only branch on the
    return value. Multi-PDF model: importing never replaces or deletes a
    previous PDF — save_pdf just repoints the active-PDF marker.
    """
    if not pdf_handler.PDF_AVAILABLE:
        showWarning(
            "PDF support is not enabled.\n\n"
            "Run this once in a terminal:\n"
            "    cd klausmate && pip install --target vendor pypdf\n"
            "Then restart Anki."
        )
        return None
    base = os.path.splitext(os.path.basename(path))[0]
    try:
        root = None
        try:
            root = pdf_handler.get_library_root(settings.read())
        except Exception:
            root = None
        info = pdf_handler.save_pdf(settings.user_files(), base, path, root=root)
    except Exception as e:
        showWarning(f"Could not read PDF: {e}")
        return None
    # PR1 review fix: seed page records right after the page text is
    # extracted and saved to contexts, not only inside the paid index run
    # (retention.do_build's ensure_pdf_index) — so the assistant has
    # slide text even with auto-index off, no OpenAI key, or a failed
    # index. Every import surface returns through this one funnel.
    try:
        from . import page_store

        pages = pdf_handler.load_pages(settings.user_files(), info["name"]) or []
        page_store.ensure_records(settings.user_files(), info["name"], path, pages)
    except Exception as e:
        print(f"[klausmate] page record seeding on import failed: {e}")
    if info["page_count"] == 0:
        showWarning(
            "No text extracted from this PDF.\n"
            "It might be a scanned image — OCR is not yet supported."
        )
    # Safe names are lossy; keep the original filename for the drive's
    # tree. Never let bookkeeping break an otherwise-good import.
    try:
        from . import drive_store

        drive_store.record_import(
            settings.user_files(), info["name"], os.path.basename(path)
        )
    except Exception as e:
        print(f"[klausmate] drive display-name record failed: {e}")
    tooltip(f"Klaus: loaded '{info['name']}'")
    # K-152: adding a PDF indexes it. This funnel is the ONE place every
    # import surface returns through, so hooking it here (rather than at
    # each drop site) is what makes the deck-screen drop, the deck-screen
    # square, the Library tree drop and the Library's Browse… all behave
    # the same. index_queue owns every gate — auto-index off, no profile,
    # no API key — and its own status bar; a failure to queue must never
    # cost the user an otherwise-good import.
    try:
        from . import index_queue

        index_queue.on_pdf_imported(str(info["name"]))
    except Exception as e:
        print(f"[klausmate] auto-index on import failed: {e}")
    return str(info["name"])


# ------------------------------- PDF panel --------------------------------


def _ensure_sidebar_pdf(editor: Editor) -> bool:
    """Load the active PDF into the dock viewer if it isn't already.

    Module-level since K-056 (which removed the bottom PDF bar and the
    panel widget that hosted it) — the toolbar "Library..." button and
    PdfDock.showEvent both need this and neither owns a panel widget to
    hang it off anymore.
    """
    active = pdf_handler.get_active_pdf(settings.user_files())
    if not active:
        return False
    sidebar = getattr(editor, "_klausmate_sidebar", None)
    if sidebar is None:
        return False
    if not sidebar.is_loaded(active):
        sidebar.load_pdf(active)
    return True


def _on_library_button(editor: Editor) -> None:
    """Toolbar "Library..." button: the old bottom bar's toggle role.

    If the PDF panel is visible, hide it. If hidden, show it — loading
    the active PDF into the viewer first if needed — and if that leaves
    no tab open, immediately pop the stored-PDF picker (_show_add_menu)
    so the user lands in "choose from the library". There is no other
    way to add a PDF from the editor anymore; only the Library window's
    drop zone can bring a new PDF into the store.
    """
    tabs = getattr(editor, "_klausmate_pdf_tabs", None)
    if tabs is None:
        tooltip("Klaus: PDF viewer is unavailable in this window")
        return
    try:
        if tabs.isVisible():
            tabs.panel_hide()
        else:
            _ensure_sidebar_pdf(editor)
            tabs.panel_show()
            strip = getattr(tabs._sidebar, "tabs", None)
            if strip is not None and not strip.names():
                tabs._sidebar._show_add_menu()
    except Exception as e:
        print(
            "[klausmate] library button action failed: "
            f"{type(e).__name__}: {e}"
        )


# Where the PDF dock may sit. Three window edges — the placement engine
# that anchored the panel on a PANE (above/below the editor, beside the
# note list) was deleted 2026-09-05 with the tear-off drag machinery
# (K-169's rules died with the code they guarded); Qt's QDockWidget does
# the moving now. Spec:
# docs/superpowers/specs/2026-09-05-pdf-dock-design.md
PANEL_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}
AREA_NAMES = {area: name for name, area in PANEL_AREAS.items()}


class _PanelBar(QWidget):
    """The dock's title bar: ``[◫]  …  [⧉] [✕]``. The tabs, ＋ and the
    page label live inside the reader (``PdfSidebar.tabs``, PDF reader
    3/5).

    Presses the bar does not handle are IGNORED so they reach the
    QDockWidget, which moves, docks and floats from them — Qt's
    setTitleBarWidget contract; the whole empty bar is the drag strip.
    With a custom title bar Qt draws no float or close button, hence
    the two at the right end. Colours only through theme tokens.
    """

    def __init__(self, dock: QWidget, sidebar: Any) -> None:
        super().__init__(dock)
        self.setObjectName("KlausPanelHeader")
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        # WA_StyledBackground because a plain QWidget won't paint a
        # stylesheet background.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        try:
            from . import theme as _theme

            self.setStyleSheet(_theme.panel_header_qss(_theme.night_mode()))
        except Exception as exc:
            print(f"[klausmate] panel header theme failed: {exc}")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 0)
        row.setSpacing(4)

        viewer = getattr(sidebar, "_viewer", None)

        # Thumbnails-strip toggle. No checked-state bookkeeping: the
        # strip itself is the visible indicator.
        self.thumbs_btn = QToolButton(self)
        self.thumbs_btn.setText("◫")
        self.thumbs_btn.setAutoRaise(True)
        self.thumbs_btn.setToolTip("Show/hide page thumbnails")

        def _toggle_thumbs() -> None:
            try:
                if viewer is not None:
                    viewer.toggle_thumbnails()
            except Exception as exc:
                print(f"[klausmate] thumbnails toggle failed: {exc}")

        self.thumbs_btn.clicked.connect(_toggle_thumbs)
        row.addWidget(self.thumbs_btn)
        row.addStretch(1)

        self.float_btn = QToolButton(self)
        self.float_btn.setText("⧉")
        self.float_btn.setAutoRaise(True)
        self.float_btn.setToolTip("Float the PDF panel / dock it back")
        row.addWidget(self.float_btn)

        self.hide_btn = QToolButton(self)
        self.hide_btn.setText("✕")
        self.hide_btn.setAutoRaise(True)
        self.hide_btn.setToolTip("Hide the PDF panel (Library… shows it again)")
        row.addWidget(self.hide_btn)

    # Ignore, never accept: the dock handles these (drag, double-click).
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()


class PdfDock(QDockWidget):
    """The PDF viewer panel: a native dock of its host window.

    One bar of chrome (``_PanelBar``) is the dock's title bar; the one
    shared ``PdfSidebar`` is its widget. Qt moves it, docks it left,
    right or bottom, floats it as an attached tool window (above the
    host, hidden and moved with it) and re-docks it — the 2026-08
    pane-anchored placement engine and its tear-off drag machine are
    gone (spec:
    docs/superpowers/specs/2026-09-05-pdf-dock-design.md).

    Persistence is Klaus's own: ``pdf_tabs.json``'s ``placement``
    (``left``/``right``/``bottom``/``float``, old values migrated by
    ``pdf_handler.migrate_placement`` at the read) and ``geom`` (the
    floating geometry). Applied on the first ``panel_show`` of the
    session, never from Anki's saved QMainWindow state, so a stale saved
    layout can never overrule the user's last move.

    - **⧉** floats the panel or docks it back; **✕** at the bar's end
      hides it (the toolbar's Library… button shows it again).
    - The tabs live in the reader (``PdfSidebar.tabs``): closing the last
      one hides the panel.

    Placement persists here; the tab set persists in the reader.
    """

    def __init__(self, editor: Editor, sidebar: Any, main_window: Any) -> None:
        super().__init__("PDF", main_window)
        self._editor = editor
        self._sidebar = sidebar
        self._win = main_window
        self._closed = False
        # _placed means the remembered placement has been applied this
        # session; until then panel_show() applies it.
        self._placed = False

        state = pdf_handler.load_panel_state(settings.user_files())
        self._placement: str = pdf_handler.migrate_placement(
            state.get("placement")
        )
        g = state.get("geom")
        self._float_geom: QRect | None = QRect(*g) if g else None

        self.setObjectName("KlausPdfDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self._bar = _PanelBar(self, sidebar)
        self._bar.float_btn.clicked.connect(self._toggle_float)
        self._bar.hide_btn.clicked.connect(self.panel_hide)
        self.setTitleBarWidget(self._bar)
        self.setWidget(sidebar)
        strip = getattr(sidebar, "tabs", None)
        if strip is not None:
            strip.closed.connect(self._on_tab_closed)

        # Nesting lets this dock share Browse's left area with Anki's own
        # sidebar dock (side by side, not only tabbed).
        try:
            main_window.setDockNestingEnabled(True)
        except Exception:
            pass
        # A dock floats and re-docks only once it belongs to a main
        # window: add it now, hidden, in its remembered area (or the
        # right area for a floating one to come back to).
        try:
            main_window.addDockWidget(
                PANEL_AREAS.get(self._placement, PANEL_AREAS["right"]), self
            )
        except Exception as exc:
            print(f"[klausmate] pdf dock add failed: {exc}")
        self.hide()
        # Connected AFTER the add above, so restoring a placement never
        # looks like the user moving the panel.
        self.dockLocationChanged.connect(self._on_area_changed)
        self.topLevelChanged.connect(self._on_floating_changed)

        # Host lifetime: the viewer's webview must be released before
        # the host's C++ objects die (PdfSidebar.cleanup), so watch
        # both the host's Close and its destroyed signal. These are NOT
        # primary/backstop: in Anki's real teardown (deleteLater()
        # posted before close(), verified against Browser/AddCards/
        # NewEditCurrent) the DeferredDelete runs first, so destroyed
        # is the path that actually releases the webview; the Close
        # branch below is deferred a further tick and arrives on an
        # already-dead host, which is why IT is the one guarded by
        # _closed (final-review M1 — the two were previously described
        # backwards).
        try:
            self._win.installEventFilter(self)
        except Exception:
            pass
        try:
            self._win.destroyed.connect(self._on_host_destroyed)
        except Exception:
            pass

    # ---- show / hide (the toolbar Library… button and chips) ----

    def panel_show(self) -> None:
        if not self._placed:
            self._placed = True
            if self._placement == "float":
                g = self._float_geom
                self.setFloating(True)
                if g is not None and g.width() > 200 and g.height() > 200:
                    self.setGeometry(g)
                else:
                    try:
                        wg = self._win.geometry()
                        self.setGeometry(
                            wg.x() + max(40, wg.width() - 560),
                            wg.y() + 80, 520, 640,
                        )
                    except Exception:
                        self.resize(520, 640)
                # setFloating(True) above synchronously fires
                # topLevelChanged -> _persist_state -> _remember_float_geom,
                # which stamps _float_geom with the hidden dock's
                # pre-layout rect (0, 0, 100, 30) and writes THAT to disk
                # before the geometry above is even applied — g was read
                # first so it survives that clobber for the setGeometry
                # call above, but _float_geom and disk are still wrong
                # afterward. Recapture the truth now the real geometry is
                # set, and flush it, or the first float of every session
                # is remembered as (0, 0, 100, 30) (final-review C1).
                self._float_geom = QRect(self.geometry())
                self._persist_state()
            else:
                area = PANEL_AREAS.get(self._placement, PANEL_AREAS["right"])
                try:
                    # NOT redundant with __init__'s addDockWidget: Qt's own
                    # "in case it was already in here" re-add is also what
                    # restores [sidebar, ours] order after Browse's own
                    # sidebar heal (_reset_browse_layout_to_defaults)
                    # re-appends Anki's sidebar dock one tick after ours
                    # (both are singleShot(0)s — ours posted first, during
                    # setupEditor; the heal's during browser_will_show).
                    # Deleting this call as "already done in __init__"
                    # loses that order (final-review M8).
                    self._win.addDockWidget(area, self)
                except Exception:
                    pass
                self.show()
                # 45% of the host on first use. resizeDocks needs the dock
                # visible and the host laid out, hence the show() above it.
                vertical = area == Qt.DockWidgetArea.BottomDockWidgetArea
                try:
                    total = self._win.height() if vertical else self._win.width()
                    self._win.resizeDocks(
                        [self], [max(200, int(total * 0.45))],
                        Qt.Orientation.Vertical if vertical
                        else Qt.Orientation.Horizontal,
                    )
                except Exception:
                    pass
        self.show()
        self.raise_()

    # Connected to the bar's ✕ (and called directly), so it carries the
    # slot guard like every other connected handler in this file — and
    # therefore ``*_args``: @_guarded's wrapper is (*args, **kwargs), so
    # PyQt hands it EVERY signal argument, and `clicked` carries a
    # `checked` bool. A guarded zero-arg slot on `clicked` raises
    # TypeError into its own guard and silently never runs (that is what
    # kept the ＋ button dead for two releases, and browse_toggles'
    # _sync_copy is the precedent).
    @_guarded
    def panel_hide(self, *_args) -> None:
        self.hide()

    def _toggle_float(self) -> None:
        try:
            self.setFloating(not self.isFloating())
        except Exception as exc:
            print(f"[klausmate] pdf dock float toggle failed: {exc}")

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        try:
            _ensure_sidebar_pdf(self._editor)
        except Exception:
            pass
        # Re-arm page-window retrieval (hideEvent cleared it).
        try:
            if self._sidebar._name is not None:
                self._sidebar._on_page_changed(
                    getattr(self._sidebar, "_current_page", 0)
                )
        except Exception:
            pass

    def hideEvent(self, ev) -> None:  # noqa: N802
        super().hideEvent(ev)
        self._remember_float_geom()
        try:
            self._sidebar._set_active(None)
        except Exception:
            pass

    # ---- placement memory ----

    @_guarded
    def _on_area_changed(self, area) -> None:
        if not self.isFloating():
            self._placement = AREA_NAMES.get(area, self._placement)
            self._persist_state()

    @_guarded
    def _on_floating_changed(self, floating: bool) -> None:
        if floating:
            self._placement = "float"
        else:
            try:
                self._placement = AREA_NAMES.get(
                    self._win.dockWidgetArea(self), self._placement
                )
            except Exception:
                pass
        self._persist_state()

    def _remember_float_geom(self) -> None:
        # A minimized window reports Dock-related geometry — don't let
        # that overwrite the real placement.
        try:
            if self.isFloating() and not self.isMinimized():
                self._float_geom = QRect(self.geometry())
        except Exception:
            pass

    def _persist_state(self) -> None:
        self._remember_float_geom()
        geom = None
        if self._float_geom is not None:
            g = self._float_geom
            geom = [g.x(), g.y(), g.width(), g.height()]
        try:
            pdf_handler.save_panel_state(
                settings.user_files(), placement=self._placement, geom=geom
            )
        except Exception:
            pass

    # ---- host lifetime ----

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        try:
            if obj is self._win and ev.type() == QEvent.Type.Close:
                # Leave the mouse pipeline NOW: a QPdfView deleted while
                # under the cursor segfaulted in sip's receiver conversion
                # (live crash, 2026-08-24). The host may still ignore()
                # this Close (AddCards' discard prompt), so never tear
                # down synchronously — check next tick.
                self._hidden_for_close = self.isVisible()
                if self._hidden_for_close:
                    try:
                        self.hide()
                    except Exception:
                        pass
                QTimer.singleShot(0, self._host_close_check)
                return False
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    def _host_close_check(self) -> None:
        """Deferred from the host's Close event: only tear down when the
        close was actually accepted — the host may have ignore()d it."""
        try:
            still_up = bool(self._win.isVisible())
        except Exception:
            # Dead wrapper — the host is definitely gone.
            still_up = False
        if not still_up:
            try:
                self._on_host_closing()
            except Exception as exc:
                print(f"[klausmate] pdf host-close teardown failed: {exc}")
        elif getattr(self, "_hidden_for_close", False):
            # The close was cancelled — undo the precautionary hide.
            self._hidden_for_close = False
            try:
                self.setVisible(True)
            except Exception:
                pass

    def _on_host_closing(self) -> None:
        """The Browse/Add window is closing: persist, release the
        renderer's webview while its C++ object still exists
        (PdfSidebar.cleanup — a webview destroyed without it crashes
        Anki's next theme change), drop the back-references. The dock
        itself is the host's child and dies with it."""
        if self._closed:
            return
        self._closed = True
        try:
            self._persist_state()
        except Exception:
            pass
        try:
            self._sidebar.cleanup()
        except Exception:
            pass
        try:
            self.hide()
        except Exception:
            pass
        try:
            self._win._klausmate_pdf_container = None
        except Exception:
            pass
        try:
            ed = self._editor
            if getattr(ed, "_klausmate_pdf_tabs", None) is self:
                ed._klausmate_pdf_tabs = None  # type: ignore[attr-defined]
                ed._klausmate_sidebar = None  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_host_destroyed(self, *_args) -> None:
        """The path that actually tears down in Anki's real close
        sequence, not a rare-case backstop: deleteLater() is posted
        before close() there, so this fires before the deferred Close
        check ever gets a turn (final-review M1). Still guarded either
        way — the C++ side of our widgets may already be gone — so a
        host destroyed with no Close event at all is equally safe."""
        try:
            self._on_host_closing()
        except Exception:
            pass

    @_guarded
    def _on_tab_closed(self, *_args) -> None:
        # The reader already cleared itself; the last tab gone hides us.
        if not self._sidebar.tabs.names():
            self.panel_hide()


def on_editor_did_init(editor: Editor) -> None:
    """Attach the tabbed PDF viewer panel (``PdfDock``) — a native dock
    of the host window, left, right, bottom or floating over it. The
    panel starts hidden and is toggled via the Library... button, or
    auto-shown when the user opens a PDF.
    """
    try:
        widget = editor.widget
        if widget is None:
            return
        layout = widget.layout()
        if layout is None:
            return
        pdf_handler.ensure_active_pdf(settings.user_files())

        # Default state for the page-aware retrieval helper.
        if not hasattr(editor, "_klausmate_active_pdf"):
            editor._klausmate_active_pdf = None  # type: ignore[attr-defined]
        # The panel is a QDockWidget now, so its host must be a
        # QMainWindow: Anki's three editor windows — Browse, Add Cards
        # and Edit Current — all are (verified against Anki 26.8.1 with
        # `strings` on editcurrent.pyc: zero QDialog, one QMainWindow;
        # `Ui_Dialog` is only the generated form's class name — final-
        # review I1) and all get the dock. Only an editor whose window
        # genuinely is not a QMainWindow (a third-party add-on's) gets
        # no panel rather than a broken one, and the Library... button
        # says so.
        parent_window = getattr(editor, "parentWindow", None)
        if parent_window is None:
            return
        if not hasattr(parent_window, "addDockWidget"):
            print("[klausmate] PDF panel needs a QMainWindow host — skipped")
            return
        if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
            return

        def _install_panel() -> None:
            # Deferred by one event-loop tick so the window's own docks
            # and layout are fully constructed before ours joins them.
            try:
                if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
                    return
                from . import pdf_viewer as _pdf_viewer

                # Reuse a panel this window already has (editor re-init).
                existing = getattr(
                    parent_window, "_klausmate_pdf_container", None
                )
                if isinstance(existing, PdfDock):
                    sidebar = existing._sidebar
                    editor._klausmate_pdf_tabs = existing  # type: ignore[attr-defined]
                    editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                    existing._editor = editor
                    sidebar._editor = editor
                    active = pdf_handler.get_active_pdf(settings.user_files())
                    # Lazy (PDF reader 3/5): a hidden dock loads on its
                    # first show (PdfDock.showEvent), never at install.
                    if active and existing.isVisible():
                        sidebar.load_pdf(active)
                    return

                sidebar = _pdf_viewer.PdfSidebar(editor, parent=None)
                try:
                    container = PdfDock(editor, sidebar, parent_window)
                except Exception:
                    # Parentless, it dies with this frame: unhook its
                    # webview from Anki's theme hook first (K-095).
                    sidebar.cleanup()
                    raise
                editor._klausmate_pdf_tabs = container  # type: ignore[attr-defined]
                editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                parent_window._klausmate_pdf_container = container
                # Nothing loads here: the dock starts hidden and loads its
                # active tab on the first show (PdfDock.showEvent).
            except Exception as e:
                print(
                    "[klausmate] PDF panel install failed: "
                    f"{type(e).__name__}: {e}"
                )
                traceback.print_exc()

        QTimer.singleShot(0, _install_panel)
    except Exception as e:
        print(f"[klausmate] editor_did_init failed: {type(e).__name__}: {e}")
        traceback.print_exc()


# ----------------------------- bootstrap ----------------------------------

# web/ assets plus the user's chosen background image — the top bar
# and the deck screens load it by URL rather than inlining megabytes
# of base64 into every webview.
mw.addonManager.setWebExports(
    __name__,
    # (?i:...) because store_image keeps the file's own name: IMG_1234.JPG
    # was stored as-is and then refused by a lower-case-only pattern.
    r"(web/.*\.(css|js)|user_files/backgrounds/.*\.(?i:png|jpg|jpeg|webp|gif))",
)
mw.addonManager.setConfigAction(__name__, open_config)


gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)
gui_hooks.main_window_did_init.append(install_menu)
from . import curation as _curation
# retention registers its two threshold migrations with settings at import;
# nothing else imports it at module level, so without this line
# settings.migrate (profile_did_open, below) would run only the legacy scrub.
from . import retention as _retention  # noqa: F401

_curation.setup_hooks()


def _flush_annotation_saves() -> None:
    """Bake every annotation save still debouncing before the profile
    goes (PDF reader 1/5)."""
    try:
        from . import annotation_save

        annotation_save.flush_all()
    except Exception as exc:
        print(f"[klausmate] annotation save flush failed: {exc}")


try:
    # Backstop against dangling AnkiWebViews in Anki's global hooks
    # (see pdf_viewer.PdfSidebar.cleanup): sweep every live sidebar on
    # profile switch and on quit. Pending saves flush FIRST, while the
    # viewers that hear their events still exist.
    from . import pdf_viewer as _pdf_viewer_cleanup

    gui_hooks.profile_will_close.append(_flush_annotation_saves)
    gui_hooks.profile_will_close.append(
        _pdf_viewer_cleanup.cleanup_all_sidebars
    )
    mw.app.aboutToQuit.connect(_pdf_viewer_cleanup.cleanup_all_sidebars)
except Exception as _e:
    print(f"[klausmate] sidebar cleanup hooks failed: {type(_e).__name__}: {_e}")


def _stop_endpoint_on_profile_close() -> None:
    """Stop Klaus's MCP/AnkiConnect endpoint when the profile closes."""
    try:
        from . import anki_endpoint

        anki_endpoint.stop_for_profile()
    except Exception as exc:
        print(f"[klausmate] assistant endpoint stop failed: {type(exc).__name__}: {exc}")


def _apply_color_theme() -> None:
    """Overlay the user's accent preset onto every later palette() call
    (SynapsePro's mechanism, K-107). Runs on profile_did_open — before
    the deck screen and its panels draw, but NOT before the top
    toolbar: Anki draws that once in finish_ui_setup(), before any
    profile opens (verified in aqt/main.py), so the bar's first sheet
    bakes the default accent. top_bar._on_profile_open_redraw shares
    this hook and redraws the bar a tick later; without it the star
    launched blue on every restart (live repro, 2026-08-30)."""
    try:
        from . import theme as _theme

        cfg = settings.read()
        # Colour first: set_active_theme("custom") is only meaningful
        # once the colour behind it is loaded.
        _theme.set_custom_colour(str(cfg.get("color_theme_custom") or ""))
        _theme.set_active_theme(str(cfg.get("color_theme") or "ocean"))
    except Exception as _exc:
        print(f"[klausmate] colour theme failed: {_exc}")


gui_hooks.profile_did_open.append(_apply_color_theme)
gui_hooks.profile_did_open.append(settings.migrate)
# One-time klaus:: -> !Library:: tag rename (K-038). After settings.migrate
# so the config store is already scrubbed when the migration reads its
# _library_tag_migrated guard flag.
from . import tag_migrate as _tag_migrate

gui_hooks.profile_did_open.append(_tag_migrate.migrate_on_profile_open)
# K-054: after the one-time klaus:: -> !Library:: rename, pick up any
# !Library tag the user renamed in Anki's own sidebar while Klaus was
# not running, so the PDF's name follows it (the reverse half of the
# tag/PDF invariant). Ordered after the migration so it never races a
# rename the migration itself is performing.
from . import tag_sync as _tag_sync


def _library_rescan_on_profile_open() -> None:
    """Folder -> Anki half of the two-way Library sync (K-073).

    Runs BEFORE the tag reconcile below on purpose: the disk is the
    source of truth for structure, so the tree follows the folder first
    and the tags then follow the tree.
    """
    try:
        from . import pdf_drive as _pdf_drive

        _pdf_drive.start_library_rescan()  # K-309: in the background
    except Exception as exc:  # noqa: BLE001 - never block profile open
        print(f"[klausmate] library rescan failed: {exc}")


gui_hooks.profile_did_open.append(_library_rescan_on_profile_open)
gui_hooks.profile_did_open.append(_tag_sync.reconcile_on_profile_open)
# K-306: the !Library tag branch is the Library, so a rename, drag or
# delete in Browse's sidebar reaches the PDF as soon as it happens.
gui_hooks.operation_did_execute.append(_tag_sync.on_operation_did_execute)
gui_hooks.profile_did_open.append(first_run_check)
gui_hooks.profile_did_open.append(setup_readiness_check)
from .setup_flow import stop_local_runtime
gui_hooks.profile_will_close.append(stop_local_runtime)


def _start_klaus_endpoint() -> None:
    """Start Klaus's AnkiConnect/MCP endpoint (anki_endpoint.py), bound for
    the life of this profile. mw.col only exists once profile_did_open
    fires, which is why this is a profile hook.
    Guarded: a failed bind must not cost the rest of profile_did_open."""
    try:
        from . import anki_endpoint

        anki_endpoint.start_for_profile()
    except Exception as exc:
        print(f"[klausmate] assistant endpoint start failed: {type(exc).__name__}: {exc}")


gui_hooks.profile_did_open.append(_start_klaus_endpoint)
gui_hooks.editor_did_init.append(on_editor_did_init)
if hasattr(gui_hooks, "browser_will_show"):
    gui_hooks.browser_will_show.append(on_browser_will_show)

# The deck-screen PDF import surface and the Library install
# independently — a failure in one must not cost the user the other (or
# the editor features above). The module is import-only since K-146 (the
# drop wrap, the drop square, and its file picker; nothing it installs
# touches a deck), and named pdf_drop for it since K-151.
try:
    from . import pdf_drop as _pdf_drop

    _pdf_drop.setup()
except Exception as _e:
    print(f"[klausmate] pdf drop setup failed: {type(_e).__name__}: {_e}")

gui_hooks.profile_will_close.append(_stop_endpoint_on_profile_close)

# The index runner: profile teardown only. Everything else about it is
# demand-driven (an import, a sidebar Re-embed, a model change), so
# there is no hook to register until a job exists.
try:
    from . import index_queue as _index_queue

    _index_queue.setup()
except Exception as _e:
    print(f"[klausmate] index queue setup failed: {type(_e).__name__}: {_e}")

try:
    from . import lecture_view as _lecture_view

    _lecture_view.setup()
except Exception as _e:
    print(f"[klausmate] lecture view setup failed: {type(_e).__name__}: {_e}")


try:
    from . import top_bar as _top_bar

    _top_bar.setup()
except Exception as _e:
    print(f"[klausmate] top bar setup failed: {type(_e).__name__}: {_e}")

try:
    from . import browse_highlight as _browse_highlight

    _browse_highlight.setup()
except Exception as _e:
    print(f"[klausmate] browse highlight setup failed: {type(_e).__name__}: {_e}")

try:
    from . import browse_retention as _browse_retention

    _browse_retention.setup()
except Exception as _e:
    print(f"[klausmate] browse retention setup failed: {type(_e).__name__}: {_e}")

try:
    # K-307: Browse's sidebar draws Library tags by their real names.
    from . import library_sidebar as _library_sidebar

    _library_sidebar.setup()
except Exception as _e:
    print(f"[klausmate] library sidebar setup failed: {type(_e).__name__}: {_e}")

try:
    # Browse's bottom bar (the task tracker's readout, gear, pane toggles).
    from . import status_bar as _status_bar

    _status_bar.setup()
except Exception as _e:
    print(f"[klausmate] status bar setup failed: {type(_e).__name__}: {_e}")

try:
    # The main window's bottom row: Anki's own, plus gear + task readout.
    from . import bottom_row as _bottom_row

    _bottom_row.setup()
except Exception as _e:
    print(f"[klausmate] bottom row setup failed: {type(_e).__name__}: {_e}")

try:
    # Other add-ons' top-level menus (AMBOSS, AnkiHub, …) go under Add-ons.
    from . import addons_menu as _addons_menu

    _addons_menu.setup()
except Exception as _e:
    print(f"[klausmate] add-ons menu setup failed: {type(_e).__name__}: {_e}")

try:
    from . import browse_toolkit as _browse_toolkit

    _browse_toolkit.setup_hooks()
except Exception as _e:
    print(f"[klausmate] browse toolkit setup failed: {type(_e).__name__}: {_e}")

try:
    from . import heatmap as _heatmap

    _heatmap.setup()
except Exception as _e:
    print(f"[klausmate] heatmap setup failed: {type(_e).__name__}: {_e}")

# AFTER heatmap on purpose: hook order is body order, and the dashboard
# boot script must parse after top_bar's panel_js weld AND after the
# heatmap exists to be wrapped. (The matching comment lives in
# dashboard._on_webview_will_set_content.)
try:
    from . import dashboard as _dashboard

    _dashboard.setup()
except Exception as _e:
    print(f"[klausmate] dashboard setup failed: {type(_e).__name__}: {_e}")

try:
    from . import window_chrome as _window_chrome

    _window_chrome.setup()
except Exception as _e:
    print(f"[klausmate] window chrome setup failed: {type(_e).__name__}: {_e}")


# NOTE: no editor_did_focus_field hook here. That hook's signature is
# (note: Note, current_field_idx: int) — it does not provide the Editor,
# so it can't drive _set_target_field reliably. Target-field tracking is
# handled by the JS bridge instead: copilot.js sends "klausmate:focus"
# with the field name, and on_js_message receives the owning Editor as
# its context.
