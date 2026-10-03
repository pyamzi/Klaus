"""Image Occlusion Enhanced v1.4.0, built into Klaus (see UPSTREAM.md).

klaus_note/__init__.py calls setup() once at bootstrap. IOE's own modules load
only after the conflict guard, so with the separate add-on enabled nothing of
this package is registered: no hook, no menu, no note type work.
"""
from __future__ import annotations

from aqt import mw
from aqt.utils import tooltip

CONFLICT_ADDON = "1374772155"
# IOE's folder names: AnkiWeb's id, and its package name when installed from
# the .ankiaddon file.
CONFLICT_ADDONS = (CONFLICT_ADDON, "image_occlusion_enhanced")
CONFLICT_TOOLTIP = (
    "Image Occlusion is now built into KlausNote. Disable the separate Image "
    "Occlusion Enhanced add-on and restart Anki."
)

# True once setup() has registered IOE; entry points elsewhere read it.
_active = False


def setup() -> bool:
    """Register IOE's hooks and menus. False when the separate add-on is on."""
    global _active
    mgr = mw.addonManager
    # allAddons() first: isEnabled() is True for a folder that isn't there.
    installed = mgr.allAddons()
    if any(name in installed and mgr.isEnabled(name) for name in CONFLICT_ADDONS):
        # Add-ons load before the main window shows; a tooltip now is unseen.
        mw.progress.single_shot(
            1000,
            lambda: tooltip(CONFLICT_TOOLTIP, period=8000),
            requires_collection=False,
        )
        return False
    from .main import setup_main

    setup_main(mw)
    _active = True
    return True


def occlude(editor, image_path: str | None = None, initial_svg: str | None = None,
            draw: bool = False) -> bool:
    """Open the mask editor on image_path for editor's note; initial_svg, if
    given, is loaded as the starting masks. With draw, the image is a blank
    PNG and the editor opens on its Draw tab ("Draw a diagram…"). False,
    doing nothing, while the conflict guard is tripped."""
    if not _active:
        return False
    from .main import on_image_occlusion_button

    origin = "addcards" if editor.addMode else "editcurrent"
    return bool(on_image_occlusion_button(editor, origin, image_path, initial_svg, draw=draw))
