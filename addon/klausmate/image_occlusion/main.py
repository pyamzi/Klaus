# -*- coding: utf-8 -*-

# Image Occlusion Enhanced Add-on for Anki
#
# Copyright (C) 2016-2020  Aristotelis P. <https://glutanimate.com/>
# Copyright (C) 2012-2015  Tiago Barroso <tmbb@campus.ul.pt>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.

"""
Sets up buttons and menus and calls other modules.
"""

import logging
import sys
from typing import TYPE_CHECKING, Optional

from aqt import mw
from aqt.editcurrent import EditCurrent
from aqt.editor import Editor
from aqt.qt import QAction, QDesktopServices, QMenu, Qt, QUrl
from aqt.utils import tooltip

from .add import ImgOccAdd
from .config import *
from .consts import *
from .dialogs import io_critical, ioHelp
from .lang import _
from .options import ImgOccOpts
from .web import setup_webview_injections
from .qt import qconnect

if TYPE_CHECKING:
    from aqt.main import AnkiQt
    from aqt.qt import QWebEngineContextMenuRequest
    from aqt.editor import EditorWebView

logging.basicConfig(stream=sys.stdout, level=logging.ERROR)


def on_io_settings():
    """Call settings dialog if Editor not active"""
    # TODO: fix ImgOccEdit detection
    if hasattr(mw, "ImgOccEdit") and mw.ImgOccEdit.visible:
        tooltip(_("Please close Image Occlusion Editor to access the Options."))
        return
    dialog = ImgOccOpts()
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


def on_io_help():
    """Call main help dialog"""
    ioHelp("main", parent=mw)


def on_image_occlusion_button(self, origin=None, image_path=None, initial_svg=None):
    """Launch Image Occlusion Enhanced"""
    origin = origin or get_editor_parent_instance(self)
    io_model = getOrCreateModel()
    if io_model:
        io_model_fields = mw.col.models.fieldNames(io_model)
        conf = mw.col.get_config("imgocc")
        if conf is not None:
            dflt_fields = list(conf["flds"].values())
        else:
            dflt_fields = list(IO_FLDS.values())
        # note type integrity check
        if not all(x in io_model_fields for x in dflt_fields):
            io_critical("model_error", help="notetype", parent=self.parentWindow)
            return False
    try:  # allows us to fall back to old image if necessary
        oldimg = self.imgoccadd.image_path
    except AttributeError:
        oldimg = None
    self.imgoccadd = ImgOccAdd(self, origin, oldimg)
    return self.imgoccadd.occlude(image_path, initial_svg)


# legacy alias for third-party add-ons calling IO
onImgOccButton = on_image_occlusion_button


def on_setup_editor_buttons(buttons, editor):
    """Add IO button to Editor"""
    conf = mw.pm.profile.get("imgocc")
    if not conf:
        hotkey = IO_HOTKEY
    else:
        hotkey = conf.get("hotkey", IO_HOTKEY)

    origin = get_editor_parent_instance(editor)

    if origin == "addcards":
        tt = _("Add Image Occlusion")
        icon_name = "add.png"
    else:
        tt = _("Edit Image Occlusion")
        icon_name = "edit.png"

    icon = os.path.join(ICONS_PATH, icon_name)

    b = editor.addButton(
        icon,
        _("I/O"),
        lambda editor=editor: onImgOccButton(editor),
        tip="{} ({})".format(tt, hotkey),
        keys=hotkey,
        disables=False,
    )

    buttons.append(b)
    return buttons


def get_editor_parent_instance(editor):
    """Determine parent instance of editor widget"""
    # Klaus (R7): from editor.addMode. Anki 26.09's NewAddCards is not an
    # AddCards, so isinstance missed the new Add window.
    if editor.addMode:
        return "addcards"
    elif isinstance(editor.parentWindow, EditCurrent):
        return "editcurrent"
    else:
        return "browser"


def open_image(path):
    """Open path with default system app"""
    import subprocess

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        QDesktopServices.openUrl(QUrl("file://" + path))


def maybe_add_image_menu(webview: "EditorWebView", menu: QMenu):
    try:  # Qt6
        context_menu_request: "QWebEngineContextMenuRequest" = (
            webview.lastContextMenuRequest()
        )
    except AttributeError:  # Qt5
        context_menu_request = (
            webview.page().contextMenuData()  # type: ignore[attr-defined]
        )
    url = context_menu_request.mediaUrl()
    image_name = url.fileName()
    path = os.path.join(mw.col.media.dir(), image_name)
    if url.isValid() and path:
        a = menu.addAction(_("Occlude Image"))
        qconnect(
            a.triggered,
            lambda _, u=path, editor=webview.editor: onImgOccButton(
                editor, image_path=u
            ),
        )
        a = menu.addAction(_("Open Image"))
        qconnect(a.triggered, lambda _, u=path: open_image(u))


def get_js_to_inject(note) -> Optional[str]:
    note_type = note.note_type()

    if note_type is None:
        # invalid note?
        return None

    is_io_note_type = note and note_type["name"] == IO_MODEL_NAME

    if not is_io_note_type:
        return """document.body.classList.remove("ionote");"""

    js = ["""document.body.classList.add("ionote");"""]

    id_field_name = IO_FLDS["id"]
    note_type_fields = note_type["flds"]

    for id_field_index, field in enumerate(note_type_fields):
        if field["name"] == id_field_name:
            break
    else:
        # Should not happen
        return "\n".join(js)

    js.append(f"""imageOcclusion.markIdField({id_field_index})""")

    return "\n".join(js)


def on_editor_did_load_note(editor: Editor):

    note = editor.note

    if note is None or editor.web is None:
        return

    js_to_inject = get_js_to_inject(note)

    if js_to_inject is None:
        return

    editor.web.eval(
        f"""
require("anki/ui").loaded.then(() => {{
    {js_to_inject}
}}
);
"""
    )


def on_editor_will_load_note(js: str, note, editor: Editor) -> str:
    js_to_inject = get_js_to_inject(note)

    if js_to_inject is None:
        return js

    return js + js_to_inject


def on_profile_loaded():
    """Setup add-on config and templates, update if necessary"""
    # Klaus: a malformed imgocc config is logged, never raised into
    # profile_did_open (that would skip the callbacks after this one).
    try:
        getSyncedConfig()
        getLocalConfig()
        getOrCreateModel()
    except Exception as e:
        print(f"[klausmate] image occlusion profile setup failed: {type(e).__name__}: {e}")


# Mask toggle hotkey


def on_hint_hotkey():
    mw.web.eval("imageOcclusion.toggleMasks();")


def on_mw_state_shortcuts(state: str, shortcuts: list):
    """Add hint hotkey when in Reviewer"""
    if state != "review":
        return
    shortcuts.append(("G", on_hint_hotkey))


# Retain scroll position when answering

# TODO: Handle in JS

# Klaus: two gui_hooks instead of wrapping Reviewer._showAnswer.
# card_will_show runs before the answer is rendered, and
# reviewer_did_show_answer after it.
_answer_scroll_pos = None


def _is_io_card(card):
    return card.note_type()["name"] == IO_MODEL_NAME


def on_card_will_show(text, card, kind):
    """Remember the scroll position before the answer replaces the question"""
    global _answer_scroll_pos
    if kind == "reviewAnswer" and _is_io_card(card):
        _answer_scroll_pos = mw.reviewer.web.page().scrollPosition()
    return text


def on_reviewer_did_show_answer(card):
    """Retain scroll position across answering the card"""
    global _answer_scroll_pos
    scroll_pos, _answer_scroll_pos = _answer_scroll_pos, None
    if scroll_pos is None or not _is_io_card(card):
        return
    mw.reviewer.web.eval(
        "window.scrollTo({}, {});".format(scroll_pos.x(), scroll_pos.y())
    )


def setup_menus(main_window: "AnkiQt"):
    # Klaus: no setConfigAction. It would replace Klaus's own Config button;
    # the options live in the Tools menu only.
    options_action = QAction(_("Image Occlusion Options…"), mw)
    qconnect(options_action.triggered, on_io_settings)
    help_action = QAction(_("Image Occlusion Help…"), mw)
    qconnect(help_action.triggered, on_io_help)
    main_window.form.menuTools.addAction(options_action)
    main_window.form.menuHelp.addAction(help_action)


def setup_main(main_window: "AnkiQt"):
    from aqt.gui_hooks import (
        browser_menus_did_init,
        card_will_show,
        editor_did_init_buttons,
        editor_did_load_note,
        editor_will_show_context_menu,
        profile_did_open,
        reviewer_did_show_answer,
        state_shortcuts_will_change,
    )

    from .nconvert import setupMenu as setup_browser_menu

    # Web assets

    setup_webview_injections()

    # Qt menus

    setup_menus(main_window)

    # Profile

    profile_did_open.append(on_profile_loaded)

    # Editor

    editor_did_init_buttons.append(on_setup_editor_buttons)
    editor_will_show_context_menu.append(maybe_add_image_menu)
    editor_did_load_note.append(on_editor_did_load_note)

    # Browser

    browser_menus_did_init.append(setup_browser_menu)

    # Reviewer

    card_will_show.append(on_card_will_show)
    reviewer_did_show_answer.append(on_reviewer_did_show_answer)
    state_shortcuts_will_change.append(on_mw_state_shortcuts)
