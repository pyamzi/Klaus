"""KlausNote — semantic lecture-PDF library for Anki.

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
    QImage,
    QMenu,
    QTimer,
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


# ----------------------------- card context ------------------------------


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
    web_content.head += f"<script>window.klausNoteConfig = {blob};</script>"


# ----------------------------- pycmd routing ------------------------------


def on_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    if not message.startswith("klaus_note:"):
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
            tooltip("KlausNote: no note loaded", parent=editor.widget)
            return
        if getattr(editor, "_klaus_note_crop_open", False):
            return
        # fname crosses the JS trust boundary — allow bare filenames
        # only (the media folder is flat, so that is always correct).
        if (
            not fname
            or "/" in fname
            or "\\" in fname
            or ".." in fname
        ):
            tooltip("KlausNote: invalid image filename", parent=editor.widget)
            return
        path = os.path.join(editor.mw.col.media.dir(), fname)
        if not os.path.isfile(path):
            tooltip(
                f"KlausNote: image not found: {fname}", parent=editor.widget
            )
            return
        image = QImage(path)
        if image.isNull():
            tooltip(
                "KlausNote: could not load image (unsupported format)",
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
                                f"KlausNote: saved {new_fname}, but the note's "
                                "HTML doesn't reference the original image",
                                parent=editor.widget,
                            )
                            return
                        if not editor.addMode:
                            # Persist; initiator=editor so no auto-reload.
                            editor._save_current_note()
                        editor.loadNoteKeepingFocus()
                        tooltip(
                            f"KlausNote: cropped image saved as {new_fname}",
                            parent=editor.widget,
                        )
                    except Exception as e:
                        print(
                            "[klaus_note] crop apply failed: "
                            f"{type(e).__name__}: {e}"
                        )
                        traceback.print_exc()

                # Flush pending in-webview edits into note.fields FIRST
                # (call_after_note_saved evals JS saveNow(); key:/blur:
                # bridge cmds land in note.fields via onBridgeCmd before
                # the callback fires), THEN mutate the fields.
                editor.call_after_note_saved(apply_to_note, keepFocus=True)
            except Exception as e:
                print(f"[klaus_note] crop failed: {type(e).__name__}: {e}")
                traceback.print_exc()

        @_guarded
        def on_finished(_r: int) -> None:
            # The open-guard spans the DIALOG'S lifetime now, not this
            # call's — reset here, where exec()'s finally used to.
            editor._klaus_note_crop_open = False  # type: ignore[attr-defined]
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
        editor._klaus_note_crop_open = True  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[klaus_note] crop failed: {type(e).__name__}: {e}")
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
        print(f"[klaus_note] crop context menu failed: {type(e).__name__}: {e}")


# ----------------------------- menu / setup -------------------------------


def open_config() -> None:
    manage_models_dialog()


def install_menu() -> None:
    """Single Tools-menu entry point, at the top of the menu.

    Everything that used to live in a 'KlausNote' submenu (Clear library tag,
    Manage models…, Check Connection) now lives inside the KlausNote
    Preferences dialog itself (manage_models.py) — a menu that only ever
    grows one deeper is still one click, and it keeps this menu from
    forking into a second place users have to think to look. Anki has
    already populated menuTools by the time main_window_did_init fires,
    so insertAction against its current first action is what puts us
    ahead of Anki's own items rather than appending after them.
    """
    menu = mw.form.menuTools
    action = QAction("KlausNote Preferences…", mw)
    action.triggered.connect(manage_models_dialog)
    existing_actions = menu.actions()
    if existing_actions:
        menu.insertAction(existing_actions[0], action)
    else:
        menu.addAction(action)


# ------------------------------ PDF import -------------------------------


def import_pdf_file(path: str, replace: bool = False) -> str | None:
    """Import one PDF into the store; returns its safe name, or None.

    Shared by every import surface (editor drop bar, deck-screen drop,
    drive window). Warnings are shown here, so callers only branch on the
    return value. A name already in the Library is kept beside it under
    a unique name (#10); ``replace`` (the deck-screen prompt's Replace)
    sends the old file to the Trash and starts the new one without marks.
    """
    if not pdf_handler.PDF_AVAILABLE:
        showWarning(
            "PDF support is not enabled.\n\n"
            "Run this once in a terminal:\n"
            "    cd klaus_note && pip install --target vendor pypdf\n"
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
        trash = None
        if replace:
            from . import pdf_drive

            blocked = pdf_handler.replace_blocker(settings.user_files(), base, root)
            if blocked:  # refuse before any reader tab is closed
                raise pdf_handler.ReplaceRefused(blocked)

            # Readers of the old file let go first (delete_pdf's rule):
            # their flush bakes into the old file, and none can later
            # save its marks onto the new one.
            pdf_drive._close_in_panels(pdf_handler._safe_basename(base))
            trash = pdf_drive._move_to_trash
        info = pdf_handler.save_pdf(
            settings.user_files(), base, path, root=root, replace=trash
        )
        if replace:
            try:
                from . import annotation_save

                # Replaced: no pending bake of the old marks may run.
                annotation_save.pipeline().forget(info["name"])
            except Exception as e:
                print(f"[klaus_note] save pipeline forget failed: {e}")
    except pdf_handler.ReplaceRefused as e:
        from aqt.utils import show_warning  # window-modal open(), never exec

        show_warning(str(e), parent=mw)
        return None
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
        print(f"[klaus_note] page record seeding on import failed: {e}")
    if info["page_count"] == 0:
        showWarning(
            "KlausNote: no text was found in this PDF.\n"
            "A scanned PDF with no text layer still can't be searched. Pages "
            "whose text is garbled are read with OCR once the local Ollama "
            "model glm-ocr is installed."
        )
    # Safe names are lossy; keep the original filename for the drive's
    # tree. Never let bookkeeping break an otherwise-good import.
    try:
        from . import drive_store

        drive_store.record_import(
            settings.user_files(),
            info["name"],
            info.get("filename") or os.path.basename(path),
        )
    except Exception as e:
        print(f"[klaus_note] drive display-name record failed: {e}")
    tooltip(f"KlausNote: loaded '{info['name']}'")
    # Importing does not index: the Library's ⟳ does (manual indexing).
    return str(info["name"])


# ----------------------------- bootstrap ----------------------------------

# web/ assets plus the user's chosen background image — the top bar
# and the deck screens load it by URL rather than inlining megabytes
# of base64 into every webview — plus Image Occlusion's web/ and its
# Excalidraw page (svg-edit loads by file URL, so it is not exported).
mw.addonManager.setWebExports(
    __name__,
    # (?i:...) because store_image keeps the file's own name: IMG_1234.JPG
    # was stored as-is and then refused by a lower-case-only pattern.
    # Keep it ONE string literal: tests read the first one after the call.
    r"(web/.*\.(css|js|ttf)|user_files/backgrounds/.*\.(?i:png|jpg|jpeg|webp|gif)|image_occlusion/web/.*\.(css|js)|image_occlusion/excalidraw/.*\.(html|js|css|woff2|png))",
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
        print(f"[klaus_note] annotation save flush failed: {exc}")


try:
    # Backstop against dangling AnkiWebViews in Anki's global hooks
    # (see reader_panel.PdfSidebar.cleanup): sweep every live sidebar on
    # profile switch and on quit. Pending saves flush FIRST, while the
    # viewers that hear their events still exist.
    from . import reader_panel as _reader_panel_cleanup

    gui_hooks.profile_will_close.append(_flush_annotation_saves)
    gui_hooks.profile_will_close.append(
        _reader_panel_cleanup.cleanup_all_sidebars
    )
    mw.app.aboutToQuit.connect(_reader_panel_cleanup.cleanup_all_sidebars)
except Exception as _e:
    print(f"[klaus_note] sidebar cleanup hooks failed: {type(_e).__name__}: {_e}")


def _stop_endpoint_on_profile_close() -> None:
    """Stop Klaus's MCP/AnkiConnect endpoint when the profile closes."""
    try:
        from . import anki_endpoint

        anki_endpoint.stop_for_profile()
    except Exception as exc:
        print(f"[klaus_note] assistant endpoint stop failed: {type(exc).__name__}: {exc}")


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
        print(f"[klaus_note] colour theme failed: {_exc}")


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
        print(f"[klaus_note] library rescan failed: {exc}")


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
        print(f"[klaus_note] assistant endpoint start failed: {type(exc).__name__}: {exc}")


gui_hooks.profile_did_open.append(_start_klaus_endpoint)
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
    print(f"[klaus_note] pdf drop setup failed: {type(_e).__name__}: {_e}")

gui_hooks.profile_will_close.append(_stop_endpoint_on_profile_close)

# The index runner: profile teardown only. Everything else about it is
# demand-driven (an import, a sidebar Re-embed, a model change), so
# there is no hook to register until a job exists.
try:
    from . import index_queue as _index_queue

    _index_queue.setup()
except Exception as _e:
    print(f"[klaus_note] index queue setup failed: {type(_e).__name__}: {_e}")

try:
    from . import lecture_view as _lecture_view

    _lecture_view.setup()
except Exception as _e:
    print(f"[klaus_note] lecture view setup failed: {type(_e).__name__}: {_e}")


try:
    from . import top_bar as _top_bar

    _top_bar.setup()
except Exception as _e:
    print(f"[klaus_note] top bar setup failed: {type(_e).__name__}: {_e}")

try:
    from . import browse_highlight as _browse_highlight

    _browse_highlight.setup()
except Exception as _e:
    print(f"[klaus_note] browse highlight setup failed: {type(_e).__name__}: {_e}")

try:
    from . import browse_retention as _browse_retention

    _browse_retention.setup()
except Exception as _e:
    print(f"[klaus_note] browse retention setup failed: {type(_e).__name__}: {_e}")

try:
    # K-307: Browse's sidebar draws Library tags by their real names.
    from . import library_sidebar as _library_sidebar

    _library_sidebar.setup()
except Exception as _e:
    print(f"[klaus_note] library sidebar setup failed: {type(_e).__name__}: {_e}")

try:
    # Browse's bottom bar (the task tracker's readout, gear, pane toggles).
    from . import status_bar as _status_bar

    _status_bar.setup()
except Exception as _e:
    print(f"[klaus_note] status bar setup failed: {type(_e).__name__}: {_e}")

try:
    # The main window's bottom row: Anki's own, plus gear + task readout.
    from . import bottom_row as _bottom_row

    _bottom_row.setup()
except Exception as _e:
    print(f"[klaus_note] bottom row setup failed: {type(_e).__name__}: {_e}")

try:
    # Automatic sync: quiet background syncs, Sync button hidden or Log In
    # (spec 2026-10-02-auto-sync-design.md).
    from . import auto_sync as _auto_sync

    _auto_sync.setup()
except Exception as _e:
    print(f"[klaus_note] auto sync setup failed: {type(_e).__name__}: {_e}")

try:
    # Other add-ons' top-level menus (AMBOSS, AnkiHub, …) go under Add-ons.
    from . import addons_menu as _addons_menu

    _addons_menu.setup()
except Exception as _e:
    print(f"[klaus_note] add-ons menu setup failed: {type(_e).__name__}: {_e}")

# Single window: Add and Browse as tabs (the Add tab: Library tree | PDF reader |
# editor), Edit Current in a right dock, all built inside the main window
# (specs 2026-09-30-single-window-design.md, 2026-10-01-add-tab-design.md).
try:
    from . import single_window as _single_window

    _single_window.setup()
except Exception as _e:
    print(f"[klaus_note] single window setup failed: {type(_e).__name__}: {_e}")


try:
    from . import heatmap as _heatmap

    _heatmap.setup()
except Exception as _e:
    print(f"[klaus_note] heatmap setup failed: {type(_e).__name__}: {_e}")

# AFTER heatmap on purpose: hook order is body order, and the dashboard
# boot script must parse after top_bar's panel_js weld AND after the
# heatmap exists to be wrapped. (The matching comment lives in
# dashboard._on_webview_will_set_content.)
try:
    from . import dashboard as _dashboard

    _dashboard.setup()
except Exception as _e:
    print(f"[klaus_note] dashboard setup failed: {type(_e).__name__}: {_e}")

try:
    from . import window_chrome as _window_chrome

    _window_chrome.setup()
except Exception as _e:
    print(f"[klaus_note] window chrome setup failed: {type(_e).__name__}: {_e}")

# Image Occlusion Enhanced, built in; off while the separate add-on is enabled.
try:
    from . import image_occlusion as _image_occlusion

    _image_occlusion.setup()
except Exception as _e:
    print(f"[klaus_note] image occlusion setup failed: {type(_e).__name__}: {_e}")


# NOTE: no editor_did_focus_field hook here. That hook's signature is
# (note: Note, current_field_idx: int) — it does not provide the Editor,
# so it can't drive _set_target_field reliably. Target-field tracking is
# handled by the JS bridge instead: copilot.js sends "klaus_note:focus"
# with the field name, and on_js_message receives the owning Editor as
# its context.
