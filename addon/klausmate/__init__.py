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
import time
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
    QMenu,
    QRect,
    QTabBar,
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

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")


# ----------------------------- config helpers -----------------------------


def get_config() -> dict[str, Any]:
    cfg = mw.addonManager.getConfig(__name__) or {}
    return cfg


def write_config(cfg: dict[str, Any]) -> None:
    mw.addonManager.writeConfig(__name__, cfg)


def patch_config(updates: dict[str, Any]) -> None:
    """Merge *updates* into the STORED config, on the main thread.

    ``write_config`` REPLACES the whole blob (that is why ``_migrate_config``
    can scrub keys by popping them), so a partial dict handed to it wipes
    every other setting. This is the one config writer a background thread
    may use, and the writer every ``plus.*`` sink must be.
    """
    def _apply() -> None:
        try:
            cfg = get_config()
            cfg.update(updates)
            write_config(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"[klausmate] patch_config failed: {e.__class__.__name__}")
    try:
        mw.taskman.run_on_main(_apply)
    except Exception:  # no taskman (tests, early boot): apply inline
        _apply()


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
    # Retired 2026-09-01: Task 8 dropped these from config.json/config.md
    # when the premium/hosted assistant path was cut back to Claude Code
    # (D1) — there is no separate assistant API key/backend/token to
    # store, the user's own `claude` login is the credential.
    "assistant_api_key", "assistant_backend", "assistant_token",
    # Retired 2026-09-15 (K-226, spec D1/D8): Klaus went API-first. The
    # local Ollama runtime and the vision-model OCR path are gone, so
    # every key that only ever addressed them goes with them; the two
    # one key that carried a VALUE worth keeping (embedding_api_key_openai)
    # is renamed in _migrate_config BEFORE this loop runs, and only its
    # spent old name is dropped here. assistant_model is a plain drop:
    # see _migrate_config for why a rename could never have fired.
    "embedding_provider", "embedding_api_key_voyage", "embedding_api_key_openai",
    "ocr_enabled", "ocr_model", "runtime_auto_setup", "claude_binary",
    "endpoint", "pdf_index_max_chunks", "pdf_match_agg", "assistant_model",
    "_embed_default_migrated",
)


def _migrate_config() -> None:
    """One-time migration of retired config keys (idempotent).

    Scrubs keys owned by removed features (chat_*, autocomplete, Ask,
    Browse NL search) from old profiles. Once meta.json holds none of them
    this is a no-op (the defaults no longer define them).
    """
    cfg = get_config()
    changed = False
    # 2026-09-15 (K-226): ONE retired key carried a VALUE the user set and
    # would have to re-enter, so it is RENAMED before the drop loop below
    # spends its old name. An empty destination only — a profile that
    # already holds the new key keeps what it holds.
    #
    # assistant_model is NOT in here (K-236): Anki's getConfig returns
    # config.json's defaults merged UNDER the profile's keys, so
    # reasoning_model is never empty and the copy could never fire. It is
    # dropped below, which is the better outcome anyway — the stored value
    # is a Claude Code model alias the Messages API would reject, and
    # nothing reads reasoning_model yet (K-235).
    for old, new in (("embedding_api_key_openai", "api_key_openai"),):
        if old in cfg:
            if not str(cfg.get(new) or "").strip():
                cfg[new] = cfg[old]
            cfg.pop(old)
            changed = True
    # 2026-09-16 (K-236): the embedding MODEL belonged to the provider
    # being scrubbed — the pre-plan dialog wrote the resolved Ollama model
    # into this key, and "nomic-embed-text" in an OpenAI-only world prices
    # as a KeyError in cost.PRICES and embeds as an HTTP 404. "" resolves
    # to embeddings.DEFAULT_MODELS' OpenAI default.
    if str(cfg.get("embedding_provider") or "openai") != "openai":
        cfg["embedding_model"] = ""
        changed = True
    for old in _LEGACY_KEYS_DROPPED:
        if old in cfg:
            cfg.pop(old)
            changed = True
    if changed:
        # 2026-09-16 (K-236): a profile that carried ANY retired key comes
        # from the pre-API-first world, where an embedding key was optional
        # because a local engine existed. `_embed_key_setup_declined` was a
        # "no thanks" to an OPTIONAL key, and leaving it set silences the
        # ONE profile-open message saying Klaus now REQUIRES one — the
        # user's next signal would be a refusal tooltip on a drop. Cleared
        # here, and only here: `changed` can never be True twice (the keys
        # that set it are gone after this write), so the new regime gets
        # exactly one fresh nudge and a decline made AFTER it is honoured
        # forever.
        cfg.pop("_embed_key_setup_declined", None)
        write_config(cfg)




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

    Task 11: the assistant's Tools entry is inserted right after
    Preferences, reusing assistant_dock's OWN QAction
    (assistant_dock.menu_action()) rather than building a second one —
    that action already carries the Ctrl+Shift+K shortcut
    (assistant_dock.setup(), called at import time below, alongside
    _pdf_drive.setup()), so this never registers a second shortcut for
    the same chord. menu_action() answers None if setup() has not run
    (or Qt is unavailable) — skipped rather than forcing a stub action.
    """
    menu = mw.form.menuTools
    action = QAction("KlausMate Preferences…", mw)
    action.triggered.connect(manage_models_dialog)
    existing_actions = menu.actions()
    if existing_actions:
        menu.insertAction(existing_actions[0], action)
    else:
        menu.addAction(action)
    try:
        from . import assistant_dock

        assistant_action = assistant_dock.menu_action()
    except Exception as exc:
        print(f"[klausmate] assistant menu action unavailable: {exc}")
        assistant_action = None
    if assistant_action is not None:
        if existing_actions:
            menu.insertAction(existing_actions[0], assistant_action)
        else:
            menu.addAction(assistant_action)


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
    # PR1 review fix: seed page records right after the page text is
    # extracted and saved to contexts, not only inside the paid index run
    # (retention.do_build's ensure_pdf_index) — so the assistant has
    # slide text even with auto-index off, no OpenAI key, or a failed
    # index. Every import surface returns through this one funnel.
    try:
        from . import page_store

        pages = pdf_handler.load_pages(USER_FILES, info["name"]) or []
        page_store.ensure_records(USER_FILES, info["name"], path, pages)
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
    PdfDock.showEvent both need this and neither owns a panel widget to
    hang it off anymore.
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
    """The dock's title bar: ``[◫] [＋] [tabs]  …  [page n/m] [⧉] [✕]``.

    Presses the bar does not handle are IGNORED so they reach the
    QDockWidget, which moves, docks and floats from them — Qt's
    setTitleBarWidget contract. The tab bar does NOT stretch over the
    empty space (a stretch follows it), so a press there is the bar's
    and starts a drag, while a press on a tab stays the tab bar's.
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

        self.add_btn = QToolButton(self)
        self.add_btn.setText("＋")
        self.add_btn.setAutoRaise(True)
        self.add_btn.setToolTip("Open another PDF in a new tab")
        row.addWidget(self.add_btn)

        self.tabs = QTabBar(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setDrawBase(False)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        # Stretch factor 0 plus the stretch below: the tab bar takes only
        # the width its tabs need, and the leftover belongs to the bar —
        # which is the surface Qt drags the dock by.
        row.addWidget(self.tabs, 0)
        row.addStretch(1)

        # The viewer's page indicator sits at the right end of the bar.
        page_label = (
            getattr(viewer, "_page_label", None) if viewer is not None else None
        )
        if page_label is not None:
            page_label.setVisible(True)
            row.addWidget(page_label)

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

        # First layout, before any resizeEvent fires: keep the cap right
        # from the very first paint (F1, review round 1). 220, not the
        # review's suggested 200: measured at a real 450px bar with four
        # saturated tabs, 200 caps the tab bar at 250px and leaves only a
        # 53px strip — 7px short of the >= 60px this is meant to
        # guarantee (fixed chrome — the two icon buttons each side, the
        # bar's own margins and inter-widget spacing — measures 147px
        # regardless of the cap, so strip = bar_width - 147 - cap; 200
        # does not clear 60 at this width, 220 clears it with margin).
        self.tabs.setMaximumWidth(max(80, self.width() - 220))

    def resizeEvent(self, ev) -> None:  # noqa: N802
        # Cap the tab bar so a drag strip always survives between it and
        # the float button, however many tabs are open: past one tab the
        # trailing stretch alone collapsed to a measured 4px (F1, review
        # round 1) — with the placement menu gone, dragging this bar is
        # the only way to move the panel between areas.
        super().resizeEvent(ev)
        self.tabs.setMaximumWidth(max(80, self.width() - 220))

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

    - **✕ on each tab** closes that PDF (the stored file survives; reopen
      it from ＋). Closing the last tab hides the panel.
    - **＋** opens another stored PDF.
    - **⧉** floats the panel or docks it back; **✕** at the bar's end
      hides it (the toolbar's Library… button shows it again).

    One viewer instance is reused across tabs; per-tab reading position
    is kept for the session; the tab set and placement persist.
    """

    def __init__(self, editor: Editor, sidebar: Any, main_window: Any) -> None:
        super().__init__("PDF", main_window)
        self._editor = editor
        self._sidebar = sidebar
        self._win = main_window
        self._syncing = False
        self._last_page: dict[str, int] = {}
        self._closed = False
        # _placed means the remembered placement has been applied this
        # session; until then panel_show() applies it.
        self._placed = False

        state = pdf_handler.load_panel_state(USER_FILES)
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
        self._tabs = self._bar.tabs
        self._add_btn = self._bar.add_btn
        self._bar.add_btn.clicked.connect(self._show_add_menu)
        self._bar.float_btn.clicked.connect(self._toggle_float)
        self._bar.hide_btn.clicked.connect(self.panel_hide)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabMoved.connect(lambda *_: self._persist())
        self.setTitleBarWidget(self._bar)
        self.setWidget(sidebar)
        sidebar.on_loaded = self._on_sidebar_loaded

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

        # Restore last session's tab set as labels only — the document
        # itself loads lazily when a tab is selected / the panel is shown.
        self._syncing = True
        try:
            for name in pdf_handler.load_open_tabs(USER_FILES):
                if self._find_tab(name) < 0:
                    self._decorate_tab(self._tabs.addTab(name))
        finally:
            self._syncing = False

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
                USER_FILES, placement=self._placement, geom=geom
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


    # ---- per-tab ✕ ----

    def _decorate_tab(self, idx: int) -> None:
        # Both call sites (session restore, _on_sidebar_loaded) route
        # through here, so this is the one place a tab's tooltip needs
        # setting: the FULL name, since ElideMiddle can only show part
        # of it once tabs saturate the bar (final-review M9).
        self._tabs.setTabToolTip(idx, self._tabs.tabText(idx))
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
    def _show_add_menu(self, *_args) -> None:
        # *_args for the same reason as panel_hide: ＋ is a `clicked`
        # button and @_guarded's wrapper accepts every signal argument.
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
        pdf_handler.ensure_active_pdf(USER_FILES)

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
                    active = pdf_handler.get_active_pdf(USER_FILES)
                    if active:
                        sidebar.load_pdf(active)
                    return

                sidebar = _pdf_viewer.PdfSidebar(editor, parent=None)
                container = PdfDock(editor, sidebar, parent_window)
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


def _stop_assistant_on_profile_close() -> None:
    """Mirror of _start_assistant_endpoint (registered on profile_did_open,
    below) — but ORDER matters here in a way it doesn't there: the dock's
    own host (the child `claude` process) must close BEFORE the endpoint
    it talks to goes down, never after, or a turn still in flight could
    have its MCP tool call hit a connection that is already refused.

    Registration order is the primary fix (gui_hooks fires listeners in
    append order): this function's own .append() call, further down this
    file, is deliberately placed AFTER assistant_dock.setup() — which
    registers assistant_dock._teardown (the function that actually calls
    dock.shutdown() -> self._host.close()) on this SAME hook — so
    _teardown always fires first in the real profile-close pass.

    This body is belt-and-braces on top of that, in case setup() itself
    never ran (a guarded import failure at import time, say) or some
    future edit reorders the two .append() calls again without noticing:
    it calls _teardown() explicitly FIRST — the exact function setup()
    would otherwise register, safe to call twice since it is a no-op once
    _dock_instance is already None — then close_assistant() (a no-op by
    then too, in the common case; kept as its own independent guarded
    step), then stops the endpoint LAST, always.
    """
    try:
        from . import assistant_dock

        assistant_dock._teardown()
    except Exception as exc:
        print(f"[klausmate] assistant dock teardown (belt-and-braces) failed: {type(exc).__name__}: {exc}")
    try:
        from . import assistant_dock

        assistant_dock.close_assistant()
    except Exception as exc:
        print(f"[klausmate] assistant dock close failed: {type(exc).__name__}: {exc}")
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


def _start_assistant_endpoint() -> None:
    """Klaus's own AnkiConnect/MCP endpoint (anki_endpoint.py), bound for
    the life of this profile — mw.col only exists once profile_did_open
    fires, which is why this is a profile hook rather than the top-level
    setup() call below (that one only needs mw, which exists earlier).
    Guarded: a failed bind must not cost the rest of profile_did_open,
    and the assistant dock already copes with anki_endpoint.current()
    being None (chat still works, just without Anki tools — see
    assistant_dock._on_init's mcp_ok branch)."""
    try:
        from . import anki_endpoint

        anki_endpoint.start_for_profile()
    except Exception as exc:
        print(f"[klausmate] assistant endpoint start failed: {type(exc).__name__}: {exc}")


gui_hooks.profile_did_open.append(_start_assistant_endpoint)
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

# The assistant dock's Tools-menu action + Ctrl+Shift+K shortcut: a plain
# QAction on mw, live regardless of profile state (see assistant_dock.setup's
# own docstring), so — like _pdf_drive.setup() just above — this runs once
# at import time rather than waiting on a profile hook. install_menu() is
# only REGISTERED against main_window_did_init above (it fires later, once
# Anki finishes constructing the main window) — so this synchronous call,
# reached during the same module import, always completes first and
# menu_action() already answers the real QAction by the time install_menu()
# actually runs.
try:
    from . import assistant_dock

    assistant_dock.setup()
except Exception as _e:
    print(f"[klausmate] assistant dock setup failed: {type(_e).__name__}: {_e}")

# Registered here — AFTER assistant_dock.setup() above, not beside
# _stop_assistant_on_profile_close's own definition further up this file
# — on purpose: gui_hooks fires profile_will_close listeners in append
# order, and setup() is what registers assistant_dock._teardown (closes
# the child claude process) on this same hook. This ordering is what
# makes the dock's host close before _stop_assistant_on_profile_close
# stops the endpoint it talks to; see that function's own docstring.
gui_hooks.profile_will_close.append(_stop_assistant_on_profile_close)

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
