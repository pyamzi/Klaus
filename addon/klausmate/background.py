"""Custom app background + the frosted top bar that sits over it.

Pouya: "make it have a Gaussian blur of whatever the background is. If
the background is just a color, it should just be that color" — plus a
way to choose that background in Preferences.

How the frosting actually works. The toolbar is its OWN webview, so CSS
``backdrop-filter`` there has nothing to blur: the window behind it is a
different widget and never composites into that document. Real vibrancy
would mean NSVisualEffectView / DWM — the native fiddling that killed
single-window mode twice here. So the bar instead paints THE SAME
background itself, blurred and top-aligned, in a layer beneath its
content. Over a photo that reads as frosted glass; over a solid colour a
Gaussian blur is a no-op, so the bar is exactly that colour and the seam
with the window chrome disappears on its own — which is the whole point.

Everything here is pure string/dict work (aqt-free) so
tests/test_background.py can exercise every branch; callers supply the
image URL, since only they know the addon's web-export name.
"""

from __future__ import annotations

import os
from typing import Any

# mode: "theme" keeps Anki's own background (the default — Klaus paints
# nothing), "color" a flat fill, "image" a picture from user_files.
MODES = ("theme", "color", "image")
FITS = ("cover", "contain", "tile")

DEFAULT_COLOR = "#1E2225"
DEFAULT_BLUR = 22          # px of Gaussian blur under the bar
DEFAULT_TINT = 0.55        # chrome tint over the blur. Tuned for
                           # READABILITY: a bright photo washed the
                           # muted link colour out entirely.

# Where chosen images are copied. Inside the addon folder so Anki's
# web exports can serve them; user_files is gitignored.
IMAGE_DIR = "backgrounds"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def resolve(cfg: Any) -> dict:
    """Normalise the background config into a spec dict.

    Every field is validated and falls back to a safe default, so a
    hand-edited config can never produce broken CSS.
    """
    if not isinstance(cfg, dict):
        cfg = {}
    mode = cfg.get("background_mode")
    if mode not in MODES:
        mode = "theme"
    colour = cfg.get("background_color")
    if not isinstance(colour, str) or not _is_hex(colour):
        colour = DEFAULT_COLOR
    image = cfg.get("background_image")
    if not isinstance(image, str) or not image.strip():
        image = ""
    # An image mode with no image selected is just the theme.
    if mode == "image" and not image:
        mode = "theme"
    fit = cfg.get("background_fit")
    if fit not in FITS:
        fit = "cover"
    blur = cfg.get("background_blur")
    if not isinstance(blur, (int, float)) or not 0 <= blur <= 100:
        blur = DEFAULT_BLUR
    return {
        "mode": mode,
        "color": colour,
        "image": image,
        "fit": fit,
        "blur": int(blur),
    }


def _is_hex(value: str) -> bool:
    v = value.strip()
    if not v.startswith("#") or len(v) not in (4, 7):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in v[1:])


def safe_image_name(name: str) -> str:
    """Basename only, extension allow-listed — a stored background can
    never point outside ``user_files/backgrounds`` or at an arbitrary
    file type."""
    base = os.path.basename(str(name or "").strip())
    if not base or base.startswith("."):
        return ""
    if os.path.splitext(base)[1].lower() not in IMAGE_EXTS:
        return ""
    return base


def image_url(addon: str, name: str) -> str:
    """Web-export URL for a stored background image."""
    safe = safe_image_name(name)
    return f"/_addons/{addon}/user_files/{IMAGE_DIR}/{safe}" if safe else ""


def _fit_rules(fit: str) -> str:
    if fit == "tile":
        return "background-size: auto; background-repeat: repeat;"
    if fit == "contain":
        return "background-size: contain; background-repeat: no-repeat;"
    return "background-size: cover; background-repeat: no-repeat;"


def main_css(spec: dict, url: str = "") -> str:
    """Background for Anki's own screens (deck list, overview, congrats).

    Empty string in ``theme`` mode — Klaus paints nothing and Anki's
    stock look is untouched, which is the default.
    """
    mode = spec.get("mode")
    if mode == "color":
        return (
            "html, body { background: %s !important; }" % spec["color"]
        )
    if mode == "image" and url:
        return (
            "html, body {"
            f" background-color: {spec['color']} !important;"
            f" background-image: url('{url}') !important;"
            f" background-position: center top !important;"
            f" background-attachment: fixed !important;"
            f" {_fit_rules(spec['fit'])}"
            " }"
        )
    return ""


def bar_css(spec: dict, url: str = "", bottom: bool = False) -> str:
    """The frosted layer for a toolbar — the top bar by default, the
    bottom bar with ``bottom=True``.

    A ``::before`` layer under the bar's content carries the same
    background, blurred. It is inset by ``-blur`` px and scaled so the
    blur kernel never samples past the element and leaves pale edges.
    In ``color`` mode there is nothing to blur, so the bar just takes
    the colour — a Gaussian blur of a flat fill is that same fill.

    The top toolbar's container is the ``.header`` class div; the
    bottom toolbar has no such class (its table is ``#header``), so the
    bottom frost hangs off ``body`` instead — and samples the IMAGE'S
    BOTTOM edge, since that is the slice of the window background the
    bar visually continues.
    """
    mode = spec.get("mode")
    if bottom:
        return _bottom_bar_css(spec, url)
    if mode == "color":
        return (
            ".header { background: %s !important; }" % spec["color"]
        )
    if mode == "image" and url:
        blur = spec["blur"]
        return f"""
    .header {{
        background: {spec['color']} !important;
        position: relative;
        isolation: isolate;
        overflow: hidden;
    }}
    .header::before {{
        content: "";
        position: absolute;
        /* Bleed past every edge so the blur never samples emptiness. */
        top: {-blur * 2}px; right: {-blur * 2}px;
        bottom: {-blur * 2}px; left: {-blur * 2}px;
        background-color: {spec['color']};
        background-image: url('{url}');
        background-position: center top;
        {_fit_rules(spec['fit'])}
        filter: blur({blur}px);
        z-index: -1;
    }}
    /* Chrome tint over the frost, so links stay readable on any photo. */
    .header::after {{
        content: "";
        position: absolute;
        inset: 0;
        background: var(--klaus-chrome);
        opacity: {DEFAULT_TINT};
        z-index: -1;
    }}
    .header > * {{ position: relative; z-index: 1; }}
    /* Over a photo the muted link colour disappears — take full
       contrast, and a soft shadow so light patches can't swallow it. */
    .header .hitem {{
        color: var(--klaus-text) !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
    }}
    .header .hitem:hover {{ color: var(--klaus-text) !important; }}
    """
    return ""


def _bottom_bar_css(spec: dict, url: str = "") -> str:
    """bar_css's bottom-toolbar variant — same frost, different roots."""
    mode = spec.get("mode")
    if mode == "color":
        return (
            "html, body { background: %s !important; }" % spec["color"]
        )
    if mode == "image" and url:
        blur = spec["blur"]
        return f"""
    body {{
        background: {spec['color']} !important;
        position: relative;
        isolation: isolate;
        overflow: hidden;
    }}
    body::before {{
        content: "";
        position: absolute;
        top: {-blur * 2}px; right: {-blur * 2}px;
        bottom: {-blur * 2}px; left: {-blur * 2}px;
        background-color: {spec['color']};
        background-image: url('{url}');
        background-position: center bottom;
        {_fit_rules(spec['fit'])}
        filter: blur({blur}px);
        z-index: -1;
    }}
    body::after {{
        content: "";
        position: absolute;
        inset: 0;
        background: var(--klaus-chrome);
        opacity: {DEFAULT_TINT};
        z-index: -1;
    }}
    #header {{ position: relative; z-index: 1; }}
    /* Full contrast + soft shadow, same treatment as the top bar's
       links — a photo swallows the muted tone. */
    body button {{
        color: var(--klaus-text) !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
    }}
    """
    return ""


def store_image(user_files_dir: str, src_path: str) -> str:
    """Copy a chosen image into ``user_files/backgrounds`` and return its
    stored basename ("" on failure).

    Copied rather than referenced so the background survives the source
    file being moved or deleted, and so Anki's web exports (which only
    serve paths under the addon folder) can reach it.
    """
    import shutil

    src = str(src_path or "")
    ext = os.path.splitext(src)[1].lower()
    if not os.path.isfile(src) or ext not in IMAGE_EXTS:
        return ""
    dest_dir = os.path.join(user_files_dir, IMAGE_DIR)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        base = safe_image_name(os.path.basename(src))
        if not base:
            return ""
        dest = os.path.join(dest_dir, base)
        # Same name, different picture: version it so the webview cache
        # can't keep serving the old bytes.
        if os.path.isfile(dest) and not os.path.samefile(src, dest):
            stem, ext2 = os.path.splitext(base)
            n = 2
            while os.path.isfile(os.path.join(dest_dir, f"{stem}-{n}{ext2}")):
                n += 1
            base = f"{stem}-{n}{ext2}"
            dest = os.path.join(dest_dir, base)
        if not (os.path.isfile(dest) and os.path.samefile(src, dest)):
            shutil.copyfile(src, dest)
        return base
    except OSError as exc:
        print(f"[klausmate] background copy failed: {exc}")
        return ""
