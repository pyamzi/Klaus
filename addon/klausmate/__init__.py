"""KlausMate — semantic lecture-PDF library for Anki.

Bootstrap and Qt glue for the add-on: the PDF viewer panel and its tabs,
the editor's PDF bar, image cropping, and the Browse toolbar toggles.
Embeddings power the rest — see curation.py (the card index),
retention.py, and pdf_drive.py (the Library).
"""

from __future__ import annotations

import atexit
import base64
import html as html_mod
import json
import os
import re
import time
import traceback
import urllib.parse
from typing import Any, Callable

from aqt import gui_hooks, mw
from aqt.editor import Editor, EditorWebView
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QCursor,
    QDockWidget,
    QDragEnterEvent,
    QDropEvent,
    QEvent,
    QHBoxLayout,
    QImage,
    QLabel,
    QApplication,
    QMenu,
    QMouseEvent,
    QPoint,
    QPointF,
    QPushButton,
    QRect,
    QSize,
    QSplitter,
    QTabBar,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import askUser, showInfo, showWarning, tooltip
from aqt.webview import WebContent

from . import pdf_handler
from .ollama_client import OllamaClient, OllamaNotRunning
from . import ollama_runtime
from .ollama_runtime import (
    ensure_server,
    server_manager,
)
from .manage_models import manage_models_dialog
from .slot_guard import guarded as _guarded
from .browse_toggles import on_browser_will_show
from .setup_flow import first_run_check, setup_readiness_check

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")


# ----------------------------- config helpers -----------------------------


def get_config() -> dict[str, Any]:
    cfg = mw.addonManager.getConfig(__name__) or {}
    return cfg


def write_config(cfg: dict[str, Any]) -> None:
    mw.addonManager.writeConfig(__name__, cfg)


# Retired config keys, scrubbed from old profiles on next launch. Covers the
# old chat_* -> klaus_* rename pairs (both sides are now dead -- no renaming,
# just dropped) plus every key the removed autocomplete/Ask/Browse-search
# features owned.
_LEGACY_KEYS_DROPPED = (
    "chat_system_prompt", "chat_use_pdf_context", "chat_max_tokens",
    "chat_engine", "chat_claude_api_key", "chat_claude_model", "chat_turn_timeout_s",
    "model", "autocomplete_model", "ask_model", "generate_timeout_s",
    "temperature", "top_p", "top_k", "repeat_penalty", "completion_mode",
    "ask_hotkey", "cycle_forward_hotkey", "cycle_backward_hotkey",
    "debounce_ms", "min_chars_before_trigger", "paste_cooldown_ms",
    "dismissal_cooldown_ms", "accept_cooldown_ms", "retrieval_method",
    "retrieval_top_k", "system_prompt", "ask_system_prompt",
    "autocomplete_enabled", "ask_enabled", "chat_hotkey", "klaus_engine",
    "claude_api_key", "claude_model", "claude_timeout_s",
    "autofill_system_prompt",
    # Retired by K-044: curation no longer has its own top-k/cutoff — the
    # per-PDF sensitivity is the single control for curation, retention
    # and the !Library tags alike. Dropped rather than migrated; there is
    # nothing left that reads either key.
    "curate_top_k", "curate_min_score",
    # Retired 2026-08-25: single-window mode (K-059..K-062, K-090..K-094)
    # removed as too buggy to stabilize — dark webview panes survived five
    # rework rounds. Anki reverts to stock multi-window behavior.
    "single_window_mode",
    # Retired 2026-08-25 same-day: the Klaus Workspace (K-102) shipped and
    # was replaced by the top-bar restyle before any release.
    "workspace_enabled",
)


def _migrate_config() -> None:
    """One-time migration of retired config keys (idempotent).

    Scrubs keys owned by removed features (chat_*, autocomplete, Ask,
    Browse NL search) from old profiles. Once meta.json holds none of them
    this is a no-op (the defaults no longer define them).
    """
    cfg = get_config()
    changed = False
    for old in _LEGACY_KEYS_DROPPED:
        if old in cfg:
            cfg.pop(old)
            changed = True
    # One-time guard for the ollama→voyage embedding default flip: an install
    # from before `embedding_provider` existed in config.json would silently
    # inherit the new cloud default while owning an ollama-built index (and no
    # API key). Pin such installs back to ollama; leave fresh installs and
    # deliberate cloud configs alone.
    if not cfg.get("_embed_default_migrated"):
        cfg["_embed_default_migrated"] = True
        changed = True
        from . import curation, embeddings

        if embeddings.provider_name(cfg) != "ollama":
            has_cloud_key = any(
                str(cfg.get(f"embedding_api_key_{p}") or "").strip()
                for p in ("voyage", "openai")
            )
            try:
                index_exists = bool(curation.index_stats().get("exists"))
            except Exception:
                index_exists = False
            is_existing = bool(cfg.get("_first_run_done")) or index_exists
            if is_existing and not has_cloud_key:
                cfg["embedding_provider"] = "ollama"
    if changed:
        write_config(cfg)




def client(timeout: float | None = None) -> OllamaClient:
    """Short-timeout client for health checks and model list/delete."""
    cfg = get_config()
    t = float(timeout) if timeout is not None else 30.0
    return OllamaClient(cfg.get("endpoint", "http://localhost:11434"), timeout=t)


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


# ----------------------------- error surfacing ----------------------------


# Once per session: when a request fails only because the server isn't
# running, try to start a managed/system Ollama silently before dialoging.
_ollama_autostart_attempted = False


def _save_config_on_main(cfg: dict[str, Any]) -> None:
    """write_config marshalled to the main thread — ensure_server may need
    to persist a new endpoint from inside a QueryOp worker thread."""
    mw.taskman.run_on_main(lambda: write_config(cfg))


def _try_silent_autostart(exc: Exception) -> bool:
    """Start a local server in the background instead of showing a dialog.

    Returns True when an attempt was kicked off (caller suppresses its
    dialog — if the start fails, the next error surfaces normally).
    """
    global _ollama_autostart_attempted
    if _ollama_autostart_attempted:
        return False
    if not isinstance(exc, OllamaNotRunning):
        return False
    if "timed out" in (str(exc) or "").lower():
        return False  # server is up, model is just slow — nothing to start
    if not get_config().get("runtime_auto_setup", True):
        return False
    if not (ollama_runtime.find_managed_runtime() or ollama_runtime.find_system_ollama()):
        return False  # nothing to start — needs the one-click setup instead
    _ollama_autostart_attempted = True
    tooltip("Klaus: starting local AI engine…")

    def do() -> Any:
        return ensure_server(get_config(), save_config=_save_config_on_main)

    def on_done(res: Any) -> None:
        if getattr(res, "ok", False):
            tooltip("Klaus: local AI ready — try again")
        else:
            print(f"[klausmate] silent autostart failed: {getattr(res, 'detail', '')}")

    op = QueryOp(parent=mw, op=lambda col: do(), success=on_done)
    op.failure(lambda e: print(f"[klausmate] silent autostart error: {e}"))
    op.without_collection().run_in_background()
    return True


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
    cfg = get_config()
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
        if fname and bool(get_config().get("image_crop_enabled", True)):
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
        if not bool(get_config().get("image_crop_enabled", True)):
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
            root = pdf_handler.get_library_root(get_config())
        except Exception:
            root = None
        info = pdf_handler.save_pdf(USER_FILES, base, path, root=root)
    except Exception as e:
        showWarning(f"Could not read PDF: {e}")
        return None
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
            USER_FILES, info["name"], os.path.basename(path)
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
    _PdfTabContainer.showEvent both need this and neither owns a panel
    widget to hang it off anymore.
    """
    active = pdf_handler.get_active_pdf(USER_FILES)
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
            if tabs._tabs.count() == 0:
                tabs._show_add_menu()
    except Exception as e:
        print(
            "[klausmate] library button action failed: "
            f"{type(e).__name__}: {e}"
        )


def _pdf_display_name(safe: str) -> str:
    """Human label for a stored PDF, falling back to its safe basename.

    A drive_store lookup that is safe on any failure: display names are
    bookkeeping, and a missing or corrupt drive.json must cost a label,
    never a menu.
    """
    try:
        from . import drive_store

        return drive_store.display_name(USER_FILES, safe)
    except Exception:
        return safe


# Placements anchored on Browse's NOTE-TABLE column instead of the editor
# pane (K-169). They exist only in a window that HAS a note table, which is
# why they are kept out of the shared placement key — see
# _load_browse_placement below.
NOTES_PLACEMENTS = ("notes-left", "notes-right")

# Where a notes-* placement is remembered inside pdf_tabs.json. Its own key,
# never the shared "placement" one: EVERY host window reads that one, and
# Add Cards has no note table to anchor on. (pdf_handler.load_panel_state
# also whitelists the five editor-anchored values, so a notes-* placement
# written there would be silently dropped on the next read — the panel would
# come back "above" and the Browse choice would be lost either way.)
_BROWSE_PLACEMENT_KEY = "browse_placement"


def _load_browse_placement() -> str | None:
    """Browse's own remembered placement, or None. Anything that is not a
    live notes-* value reads as None, so a hand-edited or stale file can
    only cost the preference, never the panel."""
    try:
        val = pdf_handler._load_tabs_file(USER_FILES).get(
            _BROWSE_PLACEMENT_KEY
        )
    except Exception:
        return None
    return val if val in NOTES_PLACEMENTS else None


def _save_browse_placement(value: str | None) -> None:
    """Remember (or, with None, forget) Browse's notes-anchored placement.
    Goes through pdf_handler._save_tabs_file so it MERGES into
    pdf_tabs.json like every other writer of that file — lecture_view.py's
    precedent for a key pdf_handler has no accessor for."""
    try:
        pdf_handler._save_tabs_file(USER_FILES, {_BROWSE_PLACEMENT_KEY: value})
    except Exception:
        pass


class _PdfTabContainer(QWidget):
    """The PDF viewer panel, with native-feeling window management.

    One bar of chrome: ``[tabs ✕] [page n/m] [＋]``. The panel docks
    beside one of the host window's panes, or FLOATS as a normal macOS
    window. Docking wraps the anchor pane in a private splitter (created
    once, kept for the window's lifetime), so "above" means above *that
    pane*, never the whole window.

    There are TWO anchors. above/below/left/right wrap ``editor.widget``;
    in Browse, notes-left/notes-right wrap the NOTE-TABLE column instead
    (K-169), which is the only way to sit beside the note list — the
    editor pane there IS the right-hand column. See the placement engine
    below.

    Window management mirrors macOS conventions:

    - **drag a tab out of the tab-bar band** (or drag any empty bar
      space) → the REAL panel floats instantly and macOS moves it live
      under the cursor (``QWindow.startSystemMove``); wide bands over
      the editor pane — and, in Browse, over the note table — preview
      exactly where it would dock (arrow + caption, sized like the real
      45% split). Release on a band to dock there, anywhere else to
      stay floating. Dragging an already-floating panel by its bar is
      the same native move. Drags that
      stay inside the tab bar just reorder tabs, in any direction. A
      translucent-ghost fallback covers the rare case where the OS
      refuses/drops the native move (see the drag state machine in
      ``__init__``).
    - the floating panel is a real, parentless macOS window: it shows
      in Mission Control, minimizes to the Dock, and Anki can come in
      front of it. Its red traffic light hides the panel; its lifetime
      is tied to the host window via ``_on_host_closing``.
    - **✕ on each tab** closes that PDF (the stored file survives; reopen
      it from ＋). Closing the last tab hides the panel.
    - **＋** opens another stored PDF or a new file from disk

    One viewer instance is reused across tabs; switching loads that PDF
    and repoints the active-PDF marker. Per-tab reading position is kept
    for the session; the tab set and placement persist across restarts.
    """

    def __init__(
        self,
        editor: Editor,
        sidebar: Any,
        main_window: Any,
    ) -> None:
        super().__init__(None)
        self._editor = editor
        self._sidebar = sidebar
        self._win = main_window
        self._syncing = False
        self._last_page: dict[str, int] = {}

        # Placement state (persisted). _placed means the panel has been
        # physically put somewhere this session; until then panel_show()
        # applies the remembered placement.
        state = pdf_handler.load_panel_state(USER_FILES)
        self._placement: str = state.get("placement", "above")
        g = state.get("geom")
        self._float_geom: QRect | None = QRect(*g) if g else None
        self._placed = False
        # Browse remembers its own side of the note table, in its own key.
        # Read only in a window that has a note table, so an Add Cards
        # panel can never inherit a placement its window cannot anchor.
        if self._browse_form() is not None:
            browse_placement = _load_browse_placement()
            if browse_placement is not None:
                self._placement = browse_placement

        # Drag state machine. A bar/tab drag instantly floats the REAL
        # panel and hands the move to macOS via
        # QWindow.startSystemMove(); Qt then stops delivering mouse
        # events to us, so the gesture's end is detected by a 100ms
        # heartbeat timer plus an application-level event filter (see
        # _drag_tick / _finalize_drag). On Cocoa, startSystemMove()
        # returns True even when the window never actually follows the
        # cursor (performWindowDragWithEvent: can silently no-op when
        # the NSEvent originated in the old host window) — a watchdog
        # in the heartbeat detects that and falls back to manually
        # following the cursor; the old translucent-ghost tear-off is
        # kept only for gestures after native move is proven broken.
        #
        # _drag_state ∈ {idle, pressed, native, armed, manual_follow,
        # manual_ghost}:
        #   idle          — no gesture
        #   pressed       — button down on the bar, threshold not met
        #   native        — macOS is (believed to be) moving the window
        #   armed         — drag went quiet; next definitive event ends it
        #   manual_follow — heartbeat/mouse events move the window
        #   manual_ghost  — embedded fallback: ghost follows, panel
        #                   relocates on release (pre-native behavior)
        self._press_gp: QPoint | None = None
        self._press_on_tab = False
        self._drag_state = "idle"
        # True only while WE send the synthetic tab-release below —
        # sendEvent re-enters this eventFilter, and the release branch
        # must let it pass through to the tab bar untouched instead of
        # resetting the gesture that is just starting.
        self._synthetic_release = False
        # None = untested, True = proven working, False = proven broken
        # (watchdog tripped / startSystemMove refused) → fall back.
        self._native_move_ok: bool | None = None
        self._drag_off: QPoint | None = None
        self._active_zone: str | None = None
        self._zone_overlay: QWidget | None = None
        self._ghost: QLabel | None = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(100)
        self._drag_timer.timeout.connect(self._drag_tick)
        self._drag_started = 0.0
        self._last_activity = 0.0
        # Direct drag evidence only: panel moveEvents while the gesture
        # owns the window, and mouse events with the left button held.
        # _last_activity (raw cursor motion) is too weak for the embed
        # freshness gate — it keeps refreshing after an unobserved
        # release; it is kept only for the armed 10s give-up cap.
        self._last_drag_evidence = 0.0
        self._last_cursor: QPoint | None = None
        self._move_seen = False
        # Where the window / cursor were when the drag machinery armed:
        # a moveEvent only counts as proof that the native move works
        # once one of them has travelled >8px — a spurious post-tear-off
        # geometry adjustment must not disarm the watchdog.
        self._drag_origin_pos: QPoint | None = None
        self._drag_start_cursor: QPoint | None = None
        self._app_filter_installed = False
        self._closed = False

        # Host lifetime: the floating panel is a PARENTLESS window (so
        # macOS treats it as a real one — Mission Control, Dock
        # minimize, can go behind Anki), which means it no longer dies
        # with the Browse/Add window that spawned it. Watch the host
        # for Close and take the panel down with it; the destroyed
        # signal is a backstop for hosts torn down without a Close.
        try:
            self._win.installEventFilter(self)
        except Exception:
            pass
        try:
            self._win.destroyed.connect(self._on_host_destroyed)
        except Exception:
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # The header is a real widget (not a bare layout) so it can take
        # mouse events: dragging its empty area moves/tears off the panel.
        self._header = QWidget(self)
        self._header.setFixedHeight(30)
        self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        # SynapsePro-style chrome: surface bar, hairline bottom border,
        # pill tabs/buttons (theme.panel_header_qss). WA_StyledBackground
        # because a plain QWidget won't paint a stylesheet background.
        try:
            from . import theme as _theme

            self._header.setObjectName("KlausPanelHeader")
            self._header.setAttribute(
                Qt.WidgetAttribute.WA_StyledBackground, True
            )
            self._header.setStyleSheet(
                _theme.panel_header_qss(_theme.night_mode())
            )
        except Exception as exc:
            print(f"[klausmate] panel header theme failed: {exc}")
        header = QHBoxLayout(self._header)
        header.setContentsMargins(6, 2, 6, 0)
        header.setSpacing(4)
        self._header.installEventFilter(self)

        self._tabs = QTabBar(self._header)
        self._tabs.setDocumentMode(True)
        self._tabs.setDrawBase(False)
        self._tabs.setMovable(True)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setExpanding(False)
        self._tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabMoved.connect(lambda *_: self._persist())
        # The tab bar stretches across the whole row, so it — not the
        # header — is what the user actually drags. Filter it too.
        self._tabs.installEventFilter(self)

        # Controls sit on the LEFT of the bar (Preview-style: sidebar
        # toggle at the far left), the tabs take the remaining width.
        viewer = getattr(sidebar, "_viewer", None)

        # Thumbnails-strip toggle. No checked-state bookkeeping: the
        # strip itself is the visible indicator.
        thumbs_btn = QToolButton(self._header)
        thumbs_btn.setText("◫")
        thumbs_btn.setAutoRaise(True)
        thumbs_btn.setToolTip("Show/hide page thumbnails")

        def _toggle_thumbs() -> None:
            try:
                if viewer is not None:
                    viewer.toggle_thumbnails()
            except Exception as exc:
                print(f"[klausmate] thumbnails toggle failed: {exc}")

        thumbs_btn.clicked.connect(_toggle_thumbs)
        header.addWidget(thumbs_btn)

        add_btn = QToolButton(self._header)
        add_btn.setText("＋")
        add_btn.setAutoRaise(True)
        add_btn.setToolTip("Open another PDF in a new tab")
        add_btn.clicked.connect(self._show_add_menu)
        self._add_btn = add_btn
        header.addWidget(add_btn)

        header.addWidget(self._tabs, 1)

        # The viewer's page indicator sits at the right end of the bar.
        page_label = (
            getattr(viewer, "_page_label", None) if viewer is not None else None
        )
        if page_label is not None:
            page_label.setVisible(True)
            header.addWidget(page_label)

        lay.addWidget(self._header)
        lay.addWidget(sidebar, 1)

        sidebar.on_loaded = self._on_sidebar_loaded

        # Restore last session's tab set as labels only — the document
        # itself loads lazily when a tab is selected / the panel is shown.
        self._syncing = True
        try:
            for name in pdf_handler.load_open_tabs(USER_FILES):
                if self._find_tab(name) < 0:
                    self._decorate_tab(self._tabs.addTab(name))
        finally:
            self._syncing = False

    # ---- show / hide (called by the Klaus bar toggle & chips) ----

    def panel_show(self) -> None:
        if not self._placed:
            if self._placement == "float":
                self._make_floating(self._float_geom)
            else:
                self._embed(self._placement)
        if self.isWindow():
            try:
                if self.isMinimized():
                    self.showNormal()
            except Exception:
                pass
            self.show()
            self.raise_()
        else:
            self.setVisible(True)

    def panel_hide(self) -> None:
        self.hide()

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
        if self.isWindow():
            self._remember_float_geom()
        try:
            self._sidebar._set_active(None)
        except Exception:
            pass

    # ---- placement engine ----
    #
    # TWO ANCHORS, ONE ENGINE (K-169). Every docked placement wraps some
    # PANE of the host window in a private QSplitter and inserts the panel
    # beside it:
    #
    #   above / below / left / right  → the EDITOR pane   (_ensure_vsplit)
    #   notes-left / notes-right      → Browse's NOTE-TABLE column
    #                                                  (_ensure_notes_split)
    #
    # The editor anchor is the original one, and its docstring's warning
    # still holds for it: "above" means above *that pane*, never the whole
    # window. In Browse the editor pane is the right-hand column, so it can
    # never reach the note list — which is why the second anchor exists.
    #
    # Both anchors share _wrap_pane (the wrap) and _dock_into (the insert +
    # sizing), so there is exactly one copy of the reparent sequence and of
    # the size-policy re-assert that QSplitter.setOrientation makes
    # necessary. A third anchor is a third _ensure_* cache in front of the
    # same two helpers.

    def _wrap_pane(self, pane: QWidget, vertical: bool) -> QSplitter | None:
        """Put ``pane`` inside a fresh QSplitter, in its own place in the
        host layout. Returns the wrapper, or None if the pane has nowhere
        to be replaced.

        Called once per anchor per window; the _ensure_* methods below
        cache the result.
        """
        parent = pane.parentWidget()
        if parent is None:
            return None
        split = QSplitter(
            Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        )
        split.setChildrenCollapsible(False)
        try:
            # Inherit the pane's size policy. AddCards' fieldsArea carries
            # verticalStretch=10 — the only hint giving it ALL surplus
            # window height. QSplitter's default policy is orientation-
            # dependent (vertically Preferred when horizontal), so without
            # this the Type/Deck row balloons into blank space whenever
            # the panel docks left/right.
            split.setSizePolicy(pane.sizePolicy())
        except Exception:
            pass
        if isinstance(parent, QSplitter):
            idx = parent.indexOf(pane)
            sizes = parent.sizes()
            parent.insertWidget(idx, split)
            split.addWidget(pane)  # reparents pane out of parent
            try:
                parent.setSizes(sizes)
            except Exception:
                pass
        else:
            lay = parent.layout()
            if lay is None:
                return None
            lay.replaceWidget(pane, split)
            split.addWidget(pane)
        pane.setVisible(True)
        return split

    def _ensure_vsplit(self) -> QSplitter | None:
        """Wrap the editor pane in a vertical splitter (once per window)."""
        existing = getattr(self._editor, "_klausmate_vsplit", None)
        if existing is not None:
            return existing
        ed_w = getattr(self._editor, "widget", None)
        if ed_w is None:
            return None
        vsplit = self._wrap_pane(ed_w, True)
        if vsplit is None:
            return None
        self._editor._klausmate_vsplit = vsplit  # type: ignore[attr-defined]
        return vsplit

    # ---- the Browse note-table anchor (K-169) ----

    def _browse_form(self) -> Any:
        """Browse's generated form, or None in every other host.

        Identified by the widgets this anchor actually uses rather than by
        class name: the Browser's standalone edit-current window hosts an
        Editor too, and AddCards has a form of its own — neither carries a
        ``splitter`` + ``tableView`` pair.
        """
        form = getattr(self._win, "form", None)
        if form is None:
            return None
        if not isinstance(getattr(form, "splitter", None), QSplitter):
            return None
        if getattr(form, "tableView", None) is None:
            return None
        return form

    def _browse_note_pane(self) -> QWidget | None:
        """Browse's note-table COLUMN — the pane this anchor docks beside.

        Found by walking UP from ``form.tableView`` to the direct child of
        whatever currently owns that column, which is browse_toggles'
        method for the editor column and for the same reason: naming the
        generated attribute (``form.widget``) would break silently on an
        Anki rename, and Anki mutates this layout after setupUi anyway.

        The walk stops at the Browse splitter, or at OUR wrapper once the
        panel is docked here — so it keeps returning the note column
        itself in both states, never the wrapper that contains it.
        """
        form = self._browse_form()
        if form is None:
            return None
        splitter = form.splitter
        wrap = getattr(self._win, "_klausmate_notes_split", None)
        w: QWidget | None = form.tableView
        while w is not None:
            p = w.parentWidget()
            if p is splitter or (wrap is not None and p is wrap):
                return w
            w = p
        return None

    def _ensure_notes_split(self) -> QSplitter | None:
        """Wrap Browse's note-table column in a horizontal splitter (once
        per window). None in any window without a note table.

        The wrapper is remembered on the HOST WINDOW, not on the editor:
        it wraps a widget the window owns, and Browse's editor is
        re-initialised more often than its layout is.

        Deliberately a WRAPPER rather than a third child of
        ``form.splitter``: Anki persists that splitter with
        saveState()/restoreState() (aqt.utils.saveSplitter, profile key
        "editor3Splitter") and restore applies the saved sizes positionally
        against however many children exist. Docking into it directly would
        write a three-size state that, read back into the two-child
        splitter of a session where the panel is never opened, hands the
        editor column the PDF's width. Wrapping keeps ``form.splitter`` at
        exactly two children and one handle, so Anki's own Browse layout
        round-trips untouched.
        """
        existing = getattr(self._win, "_klausmate_notes_split", None)
        if existing is not None:
            return existing
        pane = self._browse_note_pane()
        if pane is None:
            return None
        split = self._wrap_pane(pane, False)
        if split is None:
            return None
        self._win._klausmate_notes_split = split  # type: ignore[attr-defined]
        return split

    def _dock_into(
        self,
        split: QSplitter,
        pane: QWidget | None,
        vertical: bool,
        first: bool,
        mode: str,
    ) -> None:
        """Insert the panel into an anchor's wrapper and size it. The one
        implementation both anchors run — a new anchor must not grow a
        second copy."""
        split.setOrientation(
            Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
        )
        # setOrientation transposes QSplitter's size policy — re-assert the
        # inherited pane policy so the wrapper keeps absorbing the window's
        # surplus height in every orientation.
        try:
            if pane is not None:
                split.setSizePolicy(pane.sizePolicy())
        except Exception:
            pass
        split.insertWidget(0 if first else split.count(), self)
        self.setVisible(True)
        total = max(1, split.height() if vertical else split.width())
        pdf_share = int(total * 0.45)
        sizes = (
            [pdf_share, total - pdf_share]
            if first
            else [total - pdf_share, pdf_share]
        )
        try:
            split.setSizes(sizes)
        except Exception:
            pass
        self._placement = mode
        self._placed = True
        self._persist_state()

    def _embed(self, mode: str) -> None:
        """Dock the panel beside one of the host window's panes.

        notes-left / notes-right anchor on Browse's note table; every
        other mode anchors on the editor pane, where the wrapper
        splitter's orientation follows the side: above/below → vertical,
        left/right → horizontal.
        """
        if mode in NOTES_PLACEMENTS:
            notes_split = self._ensure_notes_split()
            if notes_split is not None:
                self._dock_into(
                    notes_split,
                    self._browse_note_pane(),
                    False,
                    mode == "notes-left",
                    mode,
                )
                return
            # No note table in this window — the anchor does not exist
            # here. Fall through to the editor anchor on the same side
            # rather than stranding the panel in a float.
            mode = "left" if mode == "notes-left" else "right"
        vsplit = self._ensure_vsplit()
        if vsplit is None:
            self._make_floating(self._float_geom)
            return
        self._dock_into(
            vsplit,
            getattr(self._editor, "widget", None),
            mode in ("above", "below"),
            mode in ("above", "left"),
            mode,
        )

    def _make_floating(self, geom: QRect | None) -> None:
        """Turn the panel into a real, PARENTLESS macOS window: it shows
        in Mission Control, minimizes to the Dock, and Anki can come in
        front of it (a child window would be forced always-on-top of its
        parent). Its red ✕ still just hides the panel (default QWidget
        close), and _on_host_closing() ties its lifetime to the host.

        Sequence matters: setParent(None) → flags → geometry → show() —
        only after show() does windowHandle() exist for
        startSystemMove()."""
        self.setParent(None)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setWindowTitle("PDF — KlausMate")
        if geom is not None and geom.width() > 200 and geom.height() > 200:
            self.setGeometry(geom)
        else:
            try:
                wg = self._win.geometry()
                self.setGeometry(
                    wg.x() + max(40, wg.width() - 560),
                    wg.y() + 80,
                    520,
                    640,
                )
            except Exception:
                self.resize(520, 640)
        self.show()
        self.raise_()
        self._placement = "float"
        self._placed = True
        self._persist_state()

    def _remember_float_geom(self) -> None:
        # A minimized window reports Dock-related geometry — don't let
        # that overwrite the real placement.
        try:
            if self.isMinimized():
                return
        except Exception:
            pass
        if self.isWindow():
            self._float_geom = QRect(self.geometry())

    def _persist_state(self) -> None:
        geom = None
        if self.isWindow():
            self._remember_float_geom()
        if self._float_geom is not None:
            g = self._float_geom
            geom = [g.x(), g.y(), g.width(), g.height()]
        notes = self._placement in NOTES_PLACEMENTS
        if self._browse_form() is not None:
            # Written on EVERY Browse placement change, None included:
            # dragging the panel back onto the editor pane (or floating
            # it) has to CLEAR the notes choice, or the next Browse open
            # would silently overrule the move that just happened.
            _save_browse_placement(self._placement if notes else None)
        try:
            pdf_handler.save_panel_state(
                USER_FILES,
                # A notes-* placement never reaches the SHARED key — Add
                # Cards reads it too and has no note table. Passing None
                # leaves the last editor-anchored choice standing there,
                # which is exactly what Add Cards should still get.
                placement=None if notes else self._placement,
                geom=geom,
            )
        except Exception:
            pass

    # ---- host lifetime ----

    def _host_close_check(self) -> None:
        """Deferred from the host's Close event: only tear down when the
        close was actually accepted — the host may have evt.ignore()d it
        (e.g. AddCards' discard prompt was cancelled), in which case
        tearing down would leave live references to a dead panel."""
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
            # The close was cancelled (AddCards' discard prompt) — undo
            # the precautionary hide from the Close filter.
            self._hidden_for_close = False
            try:
                self.setVisible(True)
            except Exception:
                pass

    def _on_host_closing(self) -> None:
        """The Browse/Add window that spawned this panel is closing.
        Embedded panels die with it naturally; a floating panel is
        parentless (see _make_floating) and must be taken down
        explicitly or it would linger as a zombie window."""
        if self._closed:
            return
        try:
            if self._drag_state != "idle":
                self._reset_drag()
        except Exception:
            pass
        try:
            self._persist_state()
        except Exception:
            pass
        # Release the renderer's webview from Anki's global hooks while
        # its C++ object still exists — a webview destroyed without
        # AnkiWebView.cleanup() crashes Anki's next theme change (see
        # PdfSidebar.cleanup).
        try:
            self._sidebar.cleanup()
        except Exception:
            pass
        # The drop-zone overlay is a parentless top-level window too.
        ov = self._zone_overlay
        if ov is not None:
            self._zone_overlay = None
            try:
                ov.hide()
                ov.deleteLater()
            except Exception:
                pass
        if self.isWindow():
            self._closed = True
            print("[klausmate] pdf drag: host closing — closing floating panel")
            try:
                self.close()
            except Exception:
                pass
            try:
                self.deleteLater()
            except Exception:
                pass
        # The host is really going away — drop the back-references so a
        # later editor re-init / toggle can't reach a dead widget.
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
        """Backstop for hosts destroyed without a Close event. The C++
        side of our widgets may already be gone, so everything is
        guarded — worst case this is a silent no-op."""
        try:
            self._on_host_closing()
        except Exception:
            pass

    # ---- drag: tear off / move / drop-dock ----

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()

        # -- host lifetime -------------------------------------------
        try:
            if obj is self._win and t == QEvent.Type.Close:
                # Leave the mouse pipeline NOW: if the close goes through,
                # the embedded viewer dies with the window, and a hidden
                # widget can no longer be Qt's hover/tracking target — a
                # QPdfView deleted while under the cursor segfaulted in
                # sip's receiver conversion (live crash, 2026-08-24).
                self._hidden_for_close = self.isVisible()
                if self._hidden_for_close:
                    try:
                        self.hide()
                    except Exception:
                        pass
                # The host may still evt.ignore() this Close (e.g. the
                # user cancels AddCards' discard prompt), so NEVER tear
                # down synchronously — check next tick whether the
                # window actually went away.
                QTimer.singleShot(0, self._host_close_check)
                return False  # never block the host's close
        except Exception:
            pass

        # -- application-level drag finalize --------------------------
        # While macOS runs a system move, Qt may never deliver the
        # release to this widget at all. This filter (installed on the
        # QApplication only for the drag's duration) closes the gesture
        # out on the next definitive event ANYWHERE: a release, a fresh
        # press, or a mouse move with no buttons held (i.e. the release
        # happened while Qt wasn't looking). Application filters run
        # before object filters, so a new press on our own bar first
        # finalizes the old drag here, then starts cleanly below.
        if (
            self._app_filter_installed
            and not self._synthetic_release
            and self._drag_state in ("native", "manual_follow", "armed")
        ):
            try:
                if t == QEvent.Type.MouseButtonRelease:
                    self._finalize_drag(True, "app-filter release")
                elif t == QEvent.Type.MouseButtonPress:
                    self._finalize_drag(True, "app-filter press")
                elif t == QEvent.Type.MouseMove:
                    if ev.buttons() == Qt.MouseButton.NoButton:
                        self._finalize_drag(
                            True, "app-filter buttonless move"
                        )
                    elif ev.buttons() & Qt.MouseButton.LeftButton:
                        # Left button demonstrably still held → the
                        # drag is alive (feeds the freshness gate).
                        self._last_drag_evidence = time.time()
            except Exception:
                pass

        # -- bar / tab gestures ---------------------------------------
        if obj is self._header or obj is self._tabs:
            if (
                t == QEvent.Type.MouseButtonPress
                and ev.button() == Qt.MouseButton.LeftButton
            ):
                gp = ev.globalPosition().toPoint()
                self._press_gp = gp
                self._drag_state = "pressed"
                # A press on an actual tab must stay draggable-for-
                # reorder; it only becomes a panel drag once the cursor
                # leaves the tab-bar band. A press on empty tab-bar
                # space (or header margins / page label) drags the
                # panel after a small threshold.
                self._press_on_tab = (
                    obj is self._tabs
                    and self._tabs.tabAt(ev.position().toPoint()) >= 0
                )
                if self.isWindow():
                    self._drag_off = (
                        gp - self.window().frameGeometry().topLeft()
                    )
                else:
                    self._drag_off = None
                return False  # let the tab bar select/reorder normally
            if t == QEvent.Type.MouseMove and self._press_gp is not None:
                gp = ev.globalPosition().toPoint()
                state = self._drag_state
                if state == "pressed":
                    if self._press_on_tab:
                        # Tab presses tear off when the cursor leaves
                        # the tab-bar band — in ANY direction. Inside
                        # the band, drags keep reordering tabs forever.
                        try:
                            band = self._tabs.rect().adjusted(-4, -4, 4, 4)
                            escaped = not band.contains(
                                self._tabs.mapFromGlobal(gp)
                            )
                        except Exception:
                            escaped = False
                    else:
                        escaped = (gp - self._press_gp).manhattanLength() > 8
                    if not escaped:
                        return False
                    self._header.setCursor(Qt.CursorShape.ClosedHandCursor)
                    if self._press_on_tab:
                        # The tab bar started a reorder-drag; close it out
                        # with a synthetic release so it doesn't keep a
                        # half-dragged tab while we move the whole panel.
                        # (_synthetic_release keeps the reentrant filter
                        # call from resetting our gesture state.)
                        self._synthetic_release = True
                        try:
                            QApplication.sendEvent(
                                self._tabs,
                                QMouseEvent(
                                    QEvent.Type.MouseButtonRelease,
                                    QPointF(
                                        self._tabs.mapFromGlobal(gp)
                                    ),
                                    QPointF(gp),
                                    Qt.MouseButton.LeftButton,
                                    Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier,
                                ),
                            )
                        except Exception:
                            pass
                        finally:
                            self._synthetic_release = False
                    self._start_panel_drag(gp)
                    return True
                if state == "manual_ghost":
                    # Fallback tear-off: drive the ghost only — the real
                    # panel is relocated on release. Reparenting it here,
                    # mid-gesture, would destroy the NSView that owns the
                    # Cocoa drag session and kill the mouse tracking.
                    self._drag_ghost_to(gp)
                    self._update_zone(gp)
                    return True
                if state == "manual_follow":
                    # Fallback live-move for a floating panel (mouse
                    # tracking is sound here — nothing was reparented).
                    try:
                        self.window().move(
                            gp - (self._drag_off or QPoint(60, 15))
                        )
                    except Exception:
                        pass
                    self._update_zone(gp)
                    self._last_activity = time.time()
                    try:
                        if ev.buttons() & Qt.MouseButton.LeftButton:
                            self._last_drag_evidence = time.time()
                    except Exception:
                        pass
                    return True
                if state in ("native", "armed"):
                    # Shouldn't normally arrive while the OS owns the
                    # move; treat it as a sign of life either way.
                    self._last_activity = time.time()
                    try:
                        if ev.buttons() & Qt.MouseButton.LeftButton:
                            self._last_drag_evidence = time.time()
                    except Exception:
                        pass
                    if state == "armed":
                        if self._native_move_ok is False:
                            # Native move is proven broken — resume in
                            # the mode that actually works and handle
                            # THIS event as a cursor-follow move.
                            self._drag_state = "manual_follow"
                            try:
                                self.window().move(
                                    gp
                                    - (self._drag_off or QPoint(60, 15))
                                )
                            except Exception:
                                pass
                            self._update_zone(gp)
                        else:
                            self._drag_state = "native"
                    return True
                return False
            if (
                t == QEvent.Type.MouseButtonRelease
                and ev.button() == Qt.MouseButton.LeftButton
            ):
                # Only the LEFT release ends a gesture — the press that
                # started it was LeftButton-gated, so a stray middle /
                # right click mid-drag must pass through untouched.
                if self._synthetic_release:
                    # Our own synthetic tab-release passing through on
                    # its way to the tab bar — not a gesture end.
                    return False
                state = self._drag_state
                if state == "pressed":
                    self._press_gp = None
                    self._drag_state = "idle"
                    return False  # plain click: let the tab bar have it
                if state == "manual_ghost":
                    gp = ev.globalPosition().toPoint()
                    zone = self._active_zone
                    self._reset_drag()
                    print(
                        "[klausmate] pdf drag: ghost drop "
                        f"(zone={zone})"
                    )
                    if zone:
                        # Embedded → re-dock on another side. Deferred:
                        # we are inside event delivery (_defer_placement).
                        self._defer_placement(self._embed, zone)
                    else:
                        # Float at the drop point. The button is up, but
                        # the reparent still must not run inside this
                        # event's delivery (_defer_placement).
                        self._defer_placement(self._tear_off, gp)
                    return True
                if state in ("native", "manual_follow", "armed"):
                    self._finalize_drag(True, "bar release")
                    return True
                return False
        return super().eventFilter(obj, ev)

    def _start_panel_drag(self, gp: QPoint) -> None:
        """A bar/tab drag gesture crossed its threshold — route it.

        Primary path: float the REAL panel at the cursor and hand the
        move to macOS (startSystemMove). Once _native_move_ok is False
        (startSystemMove refused, or the watchdog caught it lying),
        embedded tear-offs take the translucent-ghost path. An ALREADY-
        FLOATING panel always re-probes startSystemMove() — no reparent
        is involved, so this is the guaranteed-sound case — and the
        watchdog / moveEvent verdict lets _native_move_ok heal back to
        True (or stay False) for this session."""
        if self._native_move_ok is False and not self.isWindow():
            self._drag_state = "manual_ghost"
            print("[klausmate] pdf drag: begin (manual_ghost fallback)")
            self._drag_ghost_to(gp)
            self._update_zone(gp)
            return
        if not self.isWindow():
            self._tear_off(gp)
        started = False
        try:
            wh = self.window().windowHandle()
            if wh is not None:
                started = bool(wh.startSystemMove())
        except Exception:
            started = False
        if not started:
            # Refused outright → proven broken; this drag still works
            # via cursor-follow, future gestures use the ghost path.
            self._native_move_ok = False
            print(
                "[klausmate] pdf drag: startSystemMove refused — "
                "cursor-follow fallback"
            )
        self._arm_drag_machinery("native" if started else "manual_follow")

    def _arm_drag_machinery(self, state: str) -> None:
        """Start the heartbeat + app filter that shepherd a native (or
        cursor-follow) drag to its finalize."""
        now = time.time()
        self._drag_started = now
        self._last_activity = now
        # The gesture just crossed its threshold under a held left
        # button — that IS direct drag evidence.
        self._last_drag_evidence = now
        self._move_seen = False
        try:
            self._last_cursor = QPoint(QCursor.pos())
        except Exception:
            self._last_cursor = None
        try:
            self._drag_start_cursor = QPoint(QCursor.pos())
        except Exception:
            self._drag_start_cursor = None
        # Post-tear-off origin: a moveEvent only proves the native move
        # once the window (or cursor) has left this point by >8px.
        try:
            self._drag_origin_pos = QPoint(
                self.window().frameGeometry().topLeft()
            )
        except Exception:
            self._drag_origin_pos = None
        self._drag_state = state
        self._install_app_filter()
        if not self._drag_timer.isActive():
            self._drag_timer.start()
        print(f"[klausmate] pdf drag: begin ({state})")

    def _install_app_filter(self) -> None:
        if self._app_filter_installed:
            return
        try:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._app_filter_installed = True
        except Exception:
            pass

    def _displaced_enough(self) -> bool:
        """True once the window or the cursor has demonstrably travelled
        (>8px) since the drag machinery armed — the bar a moveEvent must
        clear before it counts as proof that the native move works."""
        try:
            if self._drag_origin_pos is not None:
                d = (
                    self.window().frameGeometry().topLeft()
                    - self._drag_origin_pos
                )
                if d.manhattanLength() > 8:
                    return True
        except Exception:
            pass
        try:
            if self._drag_start_cursor is not None:
                d = QCursor.pos() - self._drag_start_cursor
                if d.manhattanLength() > 8:
                    return True
        except Exception:
            pass
        return False

    def moveEvent(self, ev) -> None:  # noqa: N802
        super().moveEvent(ev)
        # Gated strictly on the drag state: ordinary moves (title-bar
        # drags of the floating window, layout changes) stay inert.
        if self._drag_state not in ("native", "armed", "manual_follow"):
            return
        now = time.time()
        if self._drag_state == "armed":
            # Only a move backed by recent drag evidence resumes the
            # gesture. Anything else (a native title-bar drag of a
            # zombie-armed panel, an async layout adjustment) is a
            # plain user reposition — no zone tracking, no promotion.
            held = False
            try:
                held = bool(
                    QApplication.mouseButtons()
                    & Qt.MouseButton.LeftButton
                )
            except Exception:
                pass
            if not held and now - self._last_drag_evidence > 1.0:
                return
            self._drag_state = (
                "manual_follow"
                if self._native_move_ok is False
                else "native"
            )
        if not self._move_seen:
            if (
                self._drag_state == "native"
                and not self._displaced_enough()
            ):
                # A spurious async geometry adjustment right after
                # tear-off must not count as native confirmation — it
                # would set _native_move_ok and permanently disarm the
                # watchdog. Stay unconfirmed.
                return
            self._move_seen = True
            if self._drag_state == "native":
                # The window demonstrably follows → native move works.
                self._native_move_ok = True
        self._last_activity = now
        # The panel moved while the gesture owns the window — direct
        # drag evidence (feeds the freshness gate in _finalize_drag).
        self._last_drag_evidence = now
        try:
            self._update_zone(QCursor.pos())
        except Exception:
            pass

    def _drag_tick(self) -> None:
        """100ms heartbeat while a native/cursor-follow drag runs.

        startSystemMove() lies on Cocoa — it returns True even when
        performWindowDragWithEvent: silently no-ops — and during a REAL
        system move Qt receives no mouse events, so the gesture's end
        can't be observed directly. Tiers:

        1. watchdog (only until the first moveEvent): the cursor has
           clearly travelled but the window never moved → native move
           is dead; demote to cursor-follow and remember the verdict.
        2. primary end: Qt saw every button go up → finalize.
        3. staleness: nothing moved for a while → "armed"; the app
           filter finalizes on the next definitive event, a new
           moveEvent re-activates, and a 10s cap gives up WITHOUT
           embedding.
        """
        state = self._drag_state
        if state not in ("native", "manual_follow", "armed"):
            self._drag_timer.stop()
            return
        now = time.time()
        try:
            cur = QPoint(QCursor.pos())
        except Exception:
            return
        moved = self._last_cursor is not None and cur != self._last_cursor
        self._last_cursor = cur
        if moved:
            self._last_activity = now

        # 1. Watchdog.
        if (
            state == "native"
            and not self._move_seen
            and now - self._drag_started >= 0.3
            and self._press_gp is not None
            and (cur - self._press_gp).manhattanLength() > 40
        ):
            self._native_move_ok = False
            self._drag_state = state = "manual_follow"
            print(
                "[klausmate] pdf drag: watchdog — native move dead, "
                "cursor-follow fallback"
            )

        # Cursor-follow: the heartbeat IS the drag.
        if state == "manual_follow":
            try:
                self.window().move(cur - (self._drag_off or QPoint(60, 15)))
            except Exception:
                pass
            self._update_zone(cur)

        # 2. Primary end.
        try:
            buttons_up = (
                QApplication.mouseButtons() == Qt.MouseButton.NoButton
            )
        except Exception:
            buttons_up = False
        if buttons_up:
            self._finalize_drag(True, "buttons-up")
            return

        # 3. Staleness.
        if state in ("native", "manual_follow"):
            if not moved and now - self._last_activity > 0.6:
                self._drag_state = "armed"
                # A quiet gesture may already be a dead one (the
                # release can be unobservable) — drop the dock preview
                # so a stray late finalize can't embed a stale zone.
                try:
                    self._hide_zone()
                except Exception:
                    pass
                print("[klausmate] pdf drag: armed (no activity)")
        elif state == "armed":
            if moved:
                # User resumed the gesture (button still down as far as
                # Qt knows).
                self._drag_state = (
                    "manual_follow"
                    if self._native_move_ok is False
                    else "native"
                )
            elif now - self._last_activity > 10.0:
                self._finalize_drag(False, "armed 10s cap")

    def _reset_drag(self) -> None:
        """Tear down all drag machinery and return to idle."""
        try:
            if self._drag_timer.isActive():
                self._drag_timer.stop()
        except Exception:
            pass
        if self._app_filter_installed:
            try:
                app = QApplication.instance()
                if app is not None:
                    app.removeEventFilter(self)
            except Exception:
                pass
            self._app_filter_installed = False
        self._hide_zone()
        self._destroy_ghost()
        self._press_gp = None
        self._move_seen = False
        self._last_cursor = None
        self._drag_origin_pos = None
        self._drag_start_cursor = None
        self._drag_state = "idle"
        try:
            self._header.setCursor(Qt.CursorShape.OpenHandCursor)
        except Exception:
            pass

    def _defer_placement(self, fn, *args) -> None:
        """Run a placement change (embed / tear-off) AFTER the current
        event finishes delivering.

        Reparenting this panel moves the live QPdfView between native
        windows, which destroys and recreates the whole subtree's window
        handles. Doing that synchronously inside ``eventFilter`` — where
        every drop path below is called from — leaves Qt delivering a
        mouse event into freed widgets: the next event's receiver
        pointer is dangling and sip segfaults converting it to Python
        before any of our code runs, so no try/except can catch it
        (SIGSEGV in sipSubClass_QPdfView, reproduced live by tearing the
        panel out and docking it back in, 2026-08-24). It is the same
        "never reparent mid-mouse-gesture" rule the tear-off already
        respects at pickup time, applied at drop time.

        singleShot(0) returns control to Qt first; the app-level event
        filter is already removed by ``_reset_drag`` (which every caller
        runs BEFORE scheduling this), so by the time ``fn`` runs there is
        no event in flight and no filter on the stack.
        """

        def run() -> None:
            try:
                if self._closed:
                    return
                fn(*args)
            except RuntimeError:
                pass  # panel died between scheduling and running
            except Exception as exc:  # noqa: BLE001
                print(f"[klausmate] pdf drag: deferred placement failed: {exc}")

        QTimer.singleShot(0, run)

    def _finalize_drag(self, allow_embed: bool, why: str) -> None:
        """Common end for native/cursor-follow drags: tear the machinery
        down, then dock into the active zone or stay floating in place.

        Embeds are additionally gated on freshness (<2s since the last
        DIRECT drag evidence — a panel moveEvent during the gesture or
        a mouse event with the left button held; raw cursor motion is
        deliberately not enough, it keeps flowing after an unobserved
        release): the staleness tiers can fire long after the user
        actually let go, and a surprise late dock is worse than staying
        floating. Esc-to-cancel was considered and dropped — key events
        are unobservable while macOS runs a system move, so a cancel
        gesture cannot be detected reliably."""
        zone = self._active_zone
        fresh = (time.time() - self._last_drag_evidence) < 2.0
        self._reset_drag()
        print(
            f"[klausmate] pdf drag: finalize via {why} "
            f"(zone={zone}, fresh={fresh}, embed_ok={allow_embed})"
        )
        if allow_embed and zone is not None and fresh:
            # Deferred: this runs inside eventFilter (see _defer_placement).
            self._defer_placement(self._embed, zone)
        else:
            self._persist_state()

    def _tear_off(self, gp: QPoint) -> None:
        w = max(480, self.width() or 480)
        h = max(400, self.height() or 400)
        self._drag_off = QPoint(w // 2, 15)
        self._make_floating(QRect(gp - self._drag_off, QSize(w, h)))

    def _drag_ghost_to(self, gp: QPoint) -> None:
        """Show/move the translucent drag preview under the cursor.
        FALLBACK ONLY: used when native window moves are proven broken
        (``_native_move_ok is False``) and the panel is still embedded —
        reparenting mid-gesture would kill Cocoa's mouse tracking, so
        the ghost stands in and the panel relocates on release."""
        g = self._ghost
        if g is None:
            pm = self.grab()
            if pm.width() > 420:
                pm = pm.scaledToWidth(
                    420, Qt.TransformationMode.SmoothTransformation
                )
            g = QLabel(self._win)
            g.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            g.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            g.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            g.setPixmap(pm)
            g.resize(pm.size())
            g.setWindowOpacity(0.55)
            self._ghost = g
        g.move(gp - QPoint(g.width() // 2, 12))
        if not g.isVisible():
            g.show()
            g.raise_()

    def _destroy_ghost(self) -> None:
        if self._ghost is not None:
            try:
                self._ghost.hide()
                self._ghost.deleteLater()
            except Exception:
                pass
            self._ghost = None

    _ZONE_CAPTIONS = {
        "above": "⬆  Dock above",
        "below": "⬇  Dock below",
        "left": "⬅  Dock left",
        "right": "➡  Dock right",
        "notes-left": "⬅  Dock left of the notes",
        "notes-right": "➡  Dock right of the notes",
    }

    def _update_zone(self, gp: QPoint) -> None:
        """Track which dock zone (if any) the cursor is over and preview
        it. Detection: generous 40% bands along each edge of the editor
        pane; the central 20%×20% — and anywhere outside the pane — is
        an easy "stay floating". In a corner the proportionally nearer
        edge wins. The preview shows the TRUE post-drop layout: the 45%
        band _embed() will actually allocate.

        In Browse the note-table column carries the SAME grammar over its
        own rect, minus the vertical pair: 40% bands left and right for
        the two notes-* placements, a neutral 20% middle. The two panes
        are siblings and never overlap, and this test runs only after the
        editor pane declined, so the original bands are untouched."""
        zone: str | None = None
        pane = getattr(self._editor, "widget", None)
        if pane is not None and pane.isVisible():
            r = QRect(pane.mapToGlobal(QPoint(0, 0)), pane.size())
            if r.contains(gp):
                w, h = max(1, r.width()), max(1, r.height())
                rel_x = gp.x() - r.left()
                rel_y = gp.y() - r.top()
                in_v = rel_y <= h * 0.4 or rel_y >= h * 0.6
                in_h = rel_x <= w * 0.4 or rel_x >= w * 0.6
                # In a corner, pick the edge the cursor is proportionally
                # closest to.
                dy = min(rel_y, h - rel_y) / h
                dx = min(rel_x, w - rel_x) / w
                if in_v and (not in_h or dy <= dx):
                    zone = "above" if rel_y <= h * 0.4 else "below"
                elif in_h:
                    zone = "left" if rel_x <= w * 0.4 else "right"
        if zone is None:
            notes_pane = self._browse_note_pane()
            if notes_pane is not None and notes_pane.isVisible():
                r = QRect(
                    notes_pane.mapToGlobal(QPoint(0, 0)), notes_pane.size()
                )
                if r.contains(gp):
                    w = max(1, r.width())
                    rel_x = gp.x() - r.left()
                    if rel_x <= w * 0.4:
                        zone = "notes-left"
                    elif rel_x >= w * 0.6:
                        zone = "notes-right"
                    if zone is not None:
                        pane = notes_pane
        if zone == self._active_zone:
            return
        self._active_zone = zone
        if zone is None:
            if self._zone_overlay is not None:
                self._zone_overlay.hide()
            return
        try:
            self._show_zone_overlay(zone, pane)
        except Exception:
            pass

    def _show_zone_overlay(self, zone: str, pane: QWidget) -> None:
        """Place the drop-zone preview over ``pane``, the pane the zone
        belongs to (the editor pane, or Browse's note column for a
        notes-* zone). The overlay is ONE reusable TOP-LEVEL window, not
        a child of that pane — during a native drag the panel itself is a
        window floating over it, and a child overlay would be covered."""
        ov = self._zone_overlay
        if ov is None:
            ov = QWidget(None)
            ov.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowTransparentForInput
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            ov.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            ov.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            lab = QLabel(ov)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            try:
                from . import theme as _theme

                _night = _theme.night_mode()
                _fill = _theme.accent_rgba(_night, 0.30)
                _edge = _theme.accent_rgba(_night, 0.85)
            except Exception:
                _fill = "rgba(58, 130, 247, 0.30)"
                _edge = "rgba(58, 130, 247, 0.85)"
            lab.setStyleSheet(
                f"background: {_fill};"
                f"border: 2px solid {_edge};"
                "border-radius: 10px;"
                "color: white; font-size: 20px; font-weight: 600;"
            )
            box = QVBoxLayout(ov)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(lab)
            ov._klaus_zone_label = lab  # type: ignore[attr-defined]
            self._zone_overlay = ov
        try:
            ov._klaus_zone_label.setText(
                self._ZONE_CAPTIONS.get(zone, zone)
            )
        except Exception:
            pass
        origin = pane.mapToGlobal(QPoint(0, 0))
        ew, eh = pane.width(), pane.height()
        if zone in ("above", "below"):
            band = max(60, int(eh * 0.45))
            geo = QRect(
                origin.x(),
                origin.y() if zone == "above" else origin.y() + eh - band,
                ew,
                band,
            )
        else:
            band = max(60, int(ew * 0.45))
            left_side = zone in ("left", "notes-left")
            geo = QRect(
                origin.x() if left_side else origin.x() + ew - band,
                origin.y(),
                band,
                eh,
            )
        ov.setGeometry(geo)
        ov.show()
        ov.raise_()

    def _hide_zone(self) -> None:
        self._active_zone = None
        if self._zone_overlay is not None:
            self._zone_overlay.hide()

    # ---- per-tab ✕ ----

    def _decorate_tab(self, idx: int) -> None:
        btn = QToolButton(self._tabs)
        btn.setText("✕")
        btn.setAutoRaise(True)
        btn.setFixedSize(16, 16)
        btn.setStyleSheet("font-size: 10px; border: none;")
        btn.setToolTip("Close this PDF (keeps the stored file)")
        btn.clicked.connect(lambda _=False, b=btn: self._close_tab_of(b))
        self._tabs.setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

    def _close_tab_of(self, btn: QToolButton) -> None:
        for i in range(self._tabs.count()):
            if self._tabs.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self._on_tab_close(i)
                return

    # ---- tab bookkeeping ----

    def _tab_names(self) -> list[str]:
        return [self._tabs.tabText(i) for i in range(self._tabs.count())]

    def _find_tab(self, name: str) -> int:
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == name:
                return i
        return -1

    def _persist(self) -> None:
        try:
            pdf_handler.save_open_tabs(USER_FILES, self._tab_names())
        except Exception:
            pass

    def _set_active_pointer(self, name: str) -> None:
        try:
            pdf_handler.set_active_pdf(USER_FILES, name)
        except Exception:
            pass
        try:
            # Recency signal for the ＋ menu's most-recent-first ordering.
            pdf_handler.touch_last_used(USER_FILES, name)
        except Exception:
            pass

    def _on_sidebar_loaded(self, name: str) -> None:
        """Sidebar loaded a PDF (from any call site): make sure a tab
        exists for it and is selected, without re-triggering a load."""
        if not name:
            return
        self._last_page.setdefault(name, 0)
        self._syncing = True
        try:
            idx = self._find_tab(name)
            if idx < 0:
                idx = self._tabs.addTab(name)
                self._decorate_tab(idx)
            if self._tabs.currentIndex() != idx:
                self._tabs.setCurrentIndex(idx)
        finally:
            self._syncing = False
        self._persist()
        self._set_active_pointer(name)

    @_guarded
    def _on_tab_changed(self, idx: int) -> None:
        if self._syncing or idx < 0:
            return
        name = self._tabs.tabText(idx)
        if not name:
            return
        prev = getattr(self._sidebar, "_name", None)
        if prev and prev != name:
            self._last_page[prev] = getattr(
                self._sidebar, "_current_page", 0
            )
        if self._sidebar.is_loaded(name):
            self._set_active_pointer(name)
            return
        self._sidebar.load_pdf(name)
        page = self._last_page.get(name, 0)
        if page > 0:
            # One tick so QPdfView finishes laying out the new document
            # before we jump back to the remembered position.
            QTimer.singleShot(
                0, lambda: self._sidebar.jump_to_page(page)
            )

    def _on_tab_close(self, idx: int) -> None:
        name = self._tabs.tabText(idx)
        # Removing the current tab makes QTabBar select a neighbour, which
        # fires currentChanged and loads that PDF into the viewer.
        self._tabs.removeTab(idx)
        self._last_page.pop(name, None)
        self._persist()
        if self._tabs.count() == 0:
            try:
                self._sidebar.clear()
            except Exception:
                pass
            try:
                pdf_handler.clear_active_pdf(USER_FILES)
            except Exception:
                pass
            self.panel_hide()

    def close_tab(self, name: str) -> None:
        idx = self._find_tab(name)
        if idx >= 0:
            self._on_tab_close(idx)

    # ---- ＋ menu / placement ----

    @_guarded
    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        open_names = set(self._tab_names())
        stored: list[str] = []
        # Most recently used first (pdf_handler.list_by_recency ranks by
        # last_used, falling back to contexts/<safe>.txt mtime — ingest
        # time — rather than pdfs/<safe>.pdf's mtime, which shutil.copy2
        # preserves from the source file).
        for base in pdf_handler.list_by_recency(USER_FILES):
            if base in open_names:
                continue
            if pdf_handler.pdf_path_for(USER_FILES, base):
                stored.append(base)
        # No cap. This menu is the only way to open a stored PDF in the
        # editor's viewer, so truncating it would strand every PDF past
        # the cut with no route in. (The deck screen used to carry a
        # top-20 curate-from-recent menu, the shortcut this was
        # contrasted against; K-146 removed it and the Library is the
        # full path now.) QMenu scrolls natively when it overflows.
        for base in stored:
            act = menu.addAction(_pdf_display_name(base))
            act.triggered.connect(
                lambda _=False, b=base: self._sidebar.load_pdf(b)
            )
        if not stored:
            # The editor deliberately has no way to ADD a PDF (K-056) —
            # only the Library window's drop zone imports new ones.
            hint = menu.addAction(
                "Every Library PDF is already open"
                if open_names
                else "No PDFs in your Library yet"
            )
            hint.setEnabled(False)
        menu.exec(
            self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft())
        )


def on_editor_did_init(editor: Editor) -> None:
    """Attach the tabbed PDF viewer panel (``_PdfTabContainer``) that
    docks above/below the editor pane or floats as its own window. The
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
        pdf_handler.ensure_active_pdf(USER_FILES)

        # Default state for the page-aware retrieval helper.
        if not hasattr(editor, "_klausmate_active_pdf"):
            editor._klausmate_active_pdf = None  # type: ignore[attr-defined]
        # The viewer panel needs a top-level Anki window to float against
        # and an editor pane to dock around. Both the Add window and the
        # Browser qualify; the Browser's standalone edit-current window
        # does too (any QWidget window works — no dock APIs involved).
        parent_window = getattr(editor, "parentWindow", None)
        if parent_window is None:
            return
        if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
            return

        def _install_panel() -> None:
            # Deferred by one event-loop tick so the window's layout is
            # fully constructed before we wrap the editor pane.
            try:
                if getattr(editor, "_klausmate_pdf_tabs", None) is not None:
                    return
                from . import pdf_viewer as _pdf_viewer

                # Reuse a panel this window already has (editor re-init).
                existing = getattr(
                    parent_window, "_klausmate_pdf_container", None
                )
                if isinstance(existing, _PdfTabContainer):
                    sidebar = existing._sidebar
                    editor._klausmate_pdf_tabs = existing  # type: ignore[attr-defined]
                    editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                    existing._editor = editor
                    sidebar._editor = editor
                    active = pdf_handler.get_active_pdf(USER_FILES)
                    if active:
                        sidebar.load_pdf(active)
                    return

                sidebar = _pdf_viewer.PdfSidebar(editor, parent=None)
                container = _PdfTabContainer(editor, sidebar, parent_window)
                container.hide()  # placed + shown on first toggle/chip
                editor._klausmate_pdf_tabs = container  # type: ignore[attr-defined]
                editor._klausmate_sidebar = sidebar  # type: ignore[attr-defined]
                parent_window._klausmate_pdf_container = container

                active = pdf_handler.get_active_pdf(USER_FILES)
                if active:
                    sidebar.load_pdf(active)
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
    r"(web/.*\.(css|js)|user_files/backgrounds/.*\.(png|jpg|jpeg|webp|gif))",
)
mw.addonManager.setConfigAction(__name__, open_config)


def _shutdown_managed_server() -> None:
    """Stop an `ollama serve` we spawned/adopted. A reused user-owned
    Ollama is never touched (ServerManager enforces that)."""
    try:
        server_manager.stop()
    except Exception as e:
        print(f"[klausmate] managed server shutdown failed: {e}")


# aboutToQuit (not profile_will_close — that fires on profile *switches*
# and the server must survive those) plus atexit as a crash-adjacent backup.
if getattr(mw, "app", None) is not None:
    mw.app.aboutToQuit.connect(_shutdown_managed_server)
atexit.register(_shutdown_managed_server)


gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
gui_hooks.webview_did_receive_js_message.append(on_js_message)
gui_hooks.editor_will_show_context_menu.append(on_editor_context_menu)
gui_hooks.main_window_did_init.append(install_menu)
from . import curation as _curation

_curation.setup_hooks()

try:
    # Backstop against dangling AnkiWebViews in Anki's global hooks
    # (see pdf_viewer.PdfSidebar.cleanup): sweep every live sidebar on
    # profile switch and on quit.
    from . import pdf_viewer as _pdf_viewer_cleanup

    gui_hooks.profile_will_close.append(
        _pdf_viewer_cleanup.cleanup_all_sidebars
    )
    mw.app.aboutToQuit.connect(_pdf_viewer_cleanup.cleanup_all_sidebars)
except Exception as _e:
    print(f"[klausmate] sidebar cleanup hooks failed: {type(_e).__name__}: {_e}")

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

        cfg = get_config()
        # Colour first: set_active_theme("custom") is only meaningful
        # once the colour behind it is loaded.
        _theme.set_custom_colour(str(cfg.get("color_theme_custom") or ""))
        _theme.set_active_theme(str(cfg.get("color_theme") or "ocean"))
    except Exception as _exc:
        print(f"[klausmate] colour theme failed: {_exc}")


# The Library screen must step aside whenever Anki moves to one of its own
# states, or it sits on top of the deck list forever — Anki changes state
# without knowing another widget is covering its webviews.
try:
    from . import library_tab as _library_tab

    _library_tab.install_hooks()
except Exception as _e:
    print(f"[klausmate] library tab hooks not installed: {_e}")

gui_hooks.profile_did_open.append(_apply_color_theme)
gui_hooks.profile_did_open.append(_migrate_config)
# One-time klaus:: -> !Library:: tag rename (K-038). After _migrate_config
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

        _pdf_drive.rescan_library_root()
    except Exception as exc:  # noqa: BLE001 - never block profile open
        print(f"[klausmate] library rescan failed: {exc}")


gui_hooks.profile_did_open.append(_library_rescan_on_profile_open)
gui_hooks.profile_did_open.append(_tag_sync.reconcile_on_profile_open)
gui_hooks.profile_did_open.append(first_run_check)
gui_hooks.profile_did_open.append(setup_readiness_check)
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

try:
    from . import pdf_drive as _pdf_drive

    _pdf_drive.setup()
except Exception as _e:
    print(f"[klausmate] pdf drive setup failed: {type(_e).__name__}: {_e}")

# The index runner: profile teardown only. Everything else about it is
# demand-driven (an import, the Library's button, a model change), so
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
