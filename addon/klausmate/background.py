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

# ── Unsaved live preview ────────────────────────────────────────────────
# Appearance is the one class of setting a user judges by eye, so the
# Preferences dialog renders it LIVE while they configure it — but Save
# is still the only writer of config (see manage_models.mark_dirty). This
# holds the pending background keys in config shape; while it is armed
# every surface paints from it instead of from what is stored. Cleared on
# Save (stored config now matches) and on Cancel (revert to stored).
#
# Deliberately NOT consulted inside resolve(): that stays a pure function
# of its argument, so the hundreds of existing resolve(cfg) tests keep
# testing exactly what they say. The override is applied at the seam, by
# effective_cfg(), where a surface decides what to paint.
_PREVIEW_CFG: dict | None = None


def set_preview(cfg: Any) -> None:
    """Arm the unsaved preview with a config-shaped dict, or clear it
    with None (anything not a dict clears, so a caller cannot half-arm)."""
    global _PREVIEW_CFG
    _PREVIEW_CFG = cfg if isinstance(cfg, dict) else None


def preview_active() -> bool:
    """True while an unsaved appearance preview is on screen."""
    return _PREVIEW_CFG is not None


def effective_cfg(cfg: Any) -> Any:
    """What a surface should paint RIGHT NOW: the unsaved preview when
    one is armed, otherwise the stored config it was given."""
    return _PREVIEW_CFG if _PREVIEW_CFG is not None else cfg


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
    stock look is untouched, which is the default. Both painted modes
    also carry panel_css, so panels look the same either way.
    """
    mode = spec.get("mode")
    if mode == "color":
        return (
            "html, body { background: %s !important; }" % spec["color"]
            # Panels get the same treatment over a flat colour as
            # over a photo, so the look does not change with the
            # background that was chosen.
            + panel_css(spec)
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
            # Panels frost over the image so their text stays readable.
            + panel_css(spec)
        )
    return ""


def panel_css(spec: dict) -> str:
    """Frost Anki's content panels so they stay readable over a photo.

    Applies to BOTH painted backgrounds so the panel look does not
    change with the background chosen. The blur itself is image-only, by
    the same logic bar_css relies on — a Gaussian blur of a flat colour
    is that colour, so over a colour background backdrop-filter would
    cost a compositing layer per panel to change nothing. Theme mode is
    left alone: Klaus paints no background there, and Anki's stock look
    already gives these surfaces its own glass.

    Unlike the bars, this really is ``backdrop-filter``. The bars can't
    use it — the toolbar is a separate webview, so the window behind it
    never composites into that document — but a deck table and the page
    background it sits on ARE the same document, so the real thing works
    here. Anki was already 90% of the way: ``.fancy table`` is painted
    with ``--canvas-glass`` ("transparent background for surfaces
    containing text") and the theme defines ``--blur``, but nothing ever
    blurred behind it, so over a photo the glass was a see-through wash.

    Both palettes ship keyed on Anki's own ``:root.night-mode`` class
    rather than baking whichever is current — the same reason
    theme.toolbar_css takes no ``night`` argument: Anki flips that class
    with JS and never re-runs the hook that injected this.
    """
    mode = spec.get("mode")
    if mode not in ("image", "color"):
        # theme mode only. Klaus paints no background there, and Anki's
        # own stock look ALREADY gives these surfaces a glass treatment
        # (.fancy table is painted with --canvas-glass). Restyling them
        # would override Anki's default with our own for no gain.
        return ""
    blur = spec.get("blur", DEFAULT_BLUR)
    if not isinstance(blur, (int, float)) or not 0 <= blur <= 100:
        blur = DEFAULT_BLUR
    blur = int(blur)
    # The frost itself is IMAGE-ONLY: a Gaussian blur of a flat colour is
    # that colour, so over a colour background backdrop-filter would cost
    # a compositing layer per panel to change nothing. The tint, borders,
    # corners and the welded stats line apply to both modes, so the panel
    # LOOK is consistent whichever background is chosen.
    filt = f"blur({blur}px) saturate(140%)"
    frost = (
        f" -webkit-backdrop-filter: {filt} !important;"
        f" backdrop-filter: {filt} !important;"
    ) if mode == "image" else ""
    # Tint sits just above Anki's 0.4 --canvas-glass: that value is tuned
    # for a flat window colour, and an arbitrary photo (bright, busy,
    # high-contrast) needs a little more to keep small text legible.
    # Deliberately sheer — over a photo the BLUR earns the legibility, so
    # the picture still reads as a picture behind the glass. Tint and
    # blur are independent knobs: lowering one does not weaken the other.
    return (
        ":root {"
        " --klaus-panel: rgba(255,255,255,0.50);"
        " --klaus-panel-edge: rgba(255,255,255,0.55);"
        " --klaus-panel-strong: rgba(255,255,255,0.62);"
        " }"
        ":root.night-mode {"
        " --klaus-panel: rgba(38,38,38,0.50);"
        " --klaus-panel-edge: rgba(255,255,255,0.10);"
        " --klaus-panel-strong: rgba(48,48,48,0.62);"
        " }"
        # table = the deck list and the overview's count table; .callout =
        # Anki's notice box. Both are real surfaces that carry text.
        " table, .callout {"
        " background: var(--klaus-panel) !important;"
        + frost +
        " border: 1px solid var(--klaus-panel-edge) !important;"
        " border-radius: var(--border-radius-medium, 12px) !important;"
        " }"
        # The current/hovered deck row. Anki fills it with an OPAQUE
        # --border-subtle (--canvas-inset under [dir=rtl]), which punched
        # a solid slab through the frosted table above. It gets the glass
        # too, only a step heavier than the panel — enough to read as
        # raised and selected, not so much that it becomes a bright slab
        # of its own. It first shipped at 0.85 against a 0.62 panel; once
        # the panel went sheerer that gap read as inconsistent, so the
        # row tracks it. Keep the two in proportion when retuning: the
        # relationship is the design, not either number.
        #
        # MUST be scoped to tr.deck. Anki's own version of this rule is
        # unscoped, but it lives in deckbrowser.css and so only ever
        # reaches the deck list; ours is injected into the overview and
        # congrats screens as well, where a bare `tr:hover td` lit up the
        # overview's LAYOUT table — its cells turned into opaque white
        # slabs inside the frosted panel on hover. Anki emits deck rows as
        # <tr class='deck'> / <tr class='deck current'> (verified in
        # aqt/deckbrowser.pyc), so .deck is exactly the deck list and
        # nothing else.
        #
        # That also makes :not(.top-level-drag-row) redundant here — drag
        # rows are emitted as <tr class='top-level-drag-row'> with no
        # .deck — but it is kept so this selector still mirrors Anki's,
        # and because dropping it would LOWER specificity below Anki's
        # [dir=rtl] hover rule.
        #
        # No backdrop-filter of its own on purpose: the table beneath it
        # is already a backdrop root, so this tint composites straight
        # over the blur the table produced. Adding a second filter here
        # would blur an already-blurred result and cost another
        # compositing layer per row.
        #
        # The [dir=rtl] variants are spelled out because Anki's own RTL
        # rules are MORE specific than the plain ones; matching their
        # specificity is what lets this win there too.
        " tr.deck.current td,"
        " tr.deck:hover:not(.top-level-drag-row) td,"
        " [dir=rtl] tr.deck.current td,"
        " [dir=rtl] tr.deck:hover:not(.top-level-drag-row) td {"
        " background: var(--klaus-panel-strong) !important;"
        " }"
        # "Studied N cards in M seconds today" is moved INTO this table
        # by panel_js(), as a final full-width row, so it is GENUINELY
        # inside the panel instead of a second box styled to look joined.
        # That removes the width problem entirely: the table's own width
        # is its width, nothing to keep in sync. It is not a tr.deck, so
        # the hover/current rule above deliberately never touches it.
        " tr.klaus-studied td {"
        " padding: 0.7em 12px 0.4em 12px !important;"
        " border: none !important;"
        " text-align: center !important;"
        " }"
        # Anki gives the line margin:2em 0 for life outside the table.
        " tr.klaus-studied #studiedToday { margin: 0 !important; }"
    )


def panel_js(spec: dict) -> str:
    """Script that moves the studied-today line INTO the deck table.

    Anki renders ``<center><table>…</table><br>%(stats)s</center>``, so
    the line is a sibling of the panel, not part of it. Styling it as a
    second box to look joined meant keeping two widths in agreement —
    which is exactly what went wrong (forcing width:100% overflowed the
    panel, because Anki gives the table padding:1rem with content-box
    sizing). Reparenting it into the table sidesteps that permanently:
    one box, the table's own width, nothing to keep in sync.

    Runs on every deck-browser render because Anki rebuilds the whole
    page through ``stdHtml`` — the same hook that injects this. It is
    idempotent and entirely defensive: any failure leaves Anki's own
    layout exactly as it was, which is the pre-existing look.

    Empty whenever panel_css is (theme mode), so the two never disagree
    about whether Klaus is styling this screen at all.
    """
    if not panel_css(spec):
        return ""
    return (
        "<script>(function(){try{"
        "var s=document.getElementById('studiedToday');"
        "if(!s||s.closest('table'))return;"          # absent, or already moved
        "var t=null,ts=document.querySelectorAll('center > table');"
        "for(var i=0;i<ts.length;i++){"
        "if(ts[i].querySelector('tr.deck')){t=ts[i];break;}}"
        "if(!t)return;"                              # not the deck list
        "var r=t.insertRow(-1);r.className='klaus-studied';"
        "var c=r.insertCell(-1);"
        # Deliberately larger than any real column count: HTML clamps a
        # colspan to the row's actual width, so this spans the whole
        # table without hardcoding Anki's 9-column deck layout.
        "c.colSpan=99;c.appendChild(s);"
        "var b=t.parentNode.querySelector('br');if(b)b.remove();"
        "}catch(e){}})();</script>"
    )


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
       links — a photo swallows the muted tone. body #header button
       (1,1,1) must outrank the chip base's #header button (1,0,1);
       both carry !important, so specificity decides. */
    body #header button {{
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
