"""Custom app background for Anki's deck and overview screens.

Pouya: "make it have a Gaussian blur of whatever the background is. If
the background is just a color, it should just be that color" — plus a
way to choose that background in Preferences. That request is realised
on the content panels only: a deck table and the page background it
sits on are the SAME document, so panel_css's ``backdrop-filter`` is
the real thing, no compositor tricks needed.

The top and bottom toolbars used to fake the same frost by painting a
blurred COPY of the background under them — their webview is a
separate document, so real backdrop-filter had nothing to blur. Pouya
asked for that removed (2026-08-30): the bars now always show flat
``--klaus-chrome`` (theme.toolbar_css / theme.bottombar_css), matching
the OS window's own colour, independent of whatever wallpaper is
chosen here.

Everything here is pure string/dict work (aqt-free) so
tests/test_background.py can exercise every branch; callers supply the
image URL, since only they know the addon's web-export name.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote

from . import theme as _theme

# mode: "theme" keeps Anki's own background (the default — Klaus paints
# nothing), "color" a flat fill, "image" a picture from user_files.
MODES = ("theme", "color", "image")
FITS = ("cover", "contain", "tile")

# White on purpose (2026-08-30, Pouya: "I just want those to be white
# for the default") — the deck and study backgrounds both default to a
# plain white ground; the old near-black #1E2225 made a fresh
# colour-mode switch open on a dark blob.
DEFAULT_COLOR = "#FFFFFF"
# ...by DAY. The ground follows Anki's theme (house rule: both
# palettes in one sheet, keyed on :root.night-mode — Anki flips the
# class with JS and never re-runs the injection): at night the white
# ground would be a floodlight (live complaint, 2026-08-30). The
# night ground is the BARS' own dark chrome token, by reference, so
# the window reads as one surface with its top and bottom bars
# (Pouya: "match the same color as the top and bottom bars" — the
# old #1E2225 drew a visible edge at both bar boundaries). Day
# matches for free: LIGHT["chrome"] IS white.
NIGHT_COLOR = _theme.DARK["chrome"]
DEFAULT_BLUR = 22          # px of Gaussian blur behind the deck panels

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


def design_enabled(cfg: Any) -> bool:
    """Whether the KlausBook design layer restyles Anki's own surfaces.

    Default OFF: Klaus ships as tools inside a stock Anki, and the
    KlausBook look is the opt-in. Deliberately the OPPOSITE polarity of
    heatmap.enabled's corrupt-reads-as-on rule — a corrupt config value
    must not surprise-restyle the user's whole app, so anything that is
    not literally True reads as off.

    This gates only what Klaus does to ANKI-owned surfaces (toolbar and
    bottom bars, backgrounds, frosted panels, the studied-line weld,
    dashboard widget editing). Klaus's own windows keep their design in
    both modes, and functional injections — the Library link, Curate
    Deck, the heatmap panel, every bridge — are never gated.
    """
    return isinstance(cfg, dict) and cfg.get("klausbook_design") is True


def effective_cfg(cfg: Any) -> Any:
    """What a surface should paint RIGHT NOW: the unsaved preview when
    one is armed, otherwise the stored config it was given."""
    return _PREVIEW_CFG if _PREVIEW_CFG is not None else cfg


def resolve(cfg: Any, prefix: str = "background") -> dict:
    """Normalise ONE background's config into a spec dict.

    Every field is validated and falls back to a safe default, so a
    hand-edited config can never produce broken CSS. *prefix* picks
    WHICH background: the deck screen's own ``background_*`` keys by
    default, or a second, independent set — ``reviewer_background_*``
    for the study screen (Pouya: separate from the main one on
    purpose, so `reviewer_css` is never tempted to fall back to the
    deck screen's picture). One validator for both keeps them
    trustworthy in the same way and on the same test coverage.
    """
    if not isinstance(cfg, dict):
        cfg = {}
    mode = cfg.get(f"{prefix}_mode")
    if mode not in MODES:
        mode = "theme"
    colour = cfg.get(f"{prefix}_color")
    if not isinstance(colour, str) or not _is_hex(colour):
        colour = DEFAULT_COLOR
    image = cfg.get(f"{prefix}_image")
    if not isinstance(image, str) or not image.strip():
        image = ""
    # An image mode with no image selected is just the theme.
    if mode == "image" and not image:
        mode = "theme"
    fit = cfg.get(f"{prefix}_fit")
    if fit not in FITS:
        fit = "cover"
    blur = cfg.get(f"{prefix}_blur")
    if not isinstance(blur, (int, float)) or not 0 <= blur <= 100:
        blur = DEFAULT_BLUR
    wash = cfg.get(f"{prefix}_wash")
    if not isinstance(wash, (int, float)) or not 0 <= wash <= 100:
        wash = 0
    # Colour mode IS a stack of gradient SPHERES (flat colour removed
    # 2026-08-30; multi-sphere the same day): `{prefix}_gradients` is
    # a list of up to four {color, x, y, size} dicts, each painted as
    # its own radial blob — the sphere's colour at its centre fading
    # to fully transparent at its edge. They compose over ONE
    # backdrop, and that backdrop is NOT an option (Pouya: "the edge
    # color... shouldn't be an option at all") — it is always the
    # default ground colour, white. Any stored {prefix}_color2 from
    # the brief era when it was configurable is ignored. A
    # missing/invalid sphere list is built from the legacy
    # single-gradient keys (color/grad_x/grad_y/grad_size), so every
    # older config keeps rendering.
    colour2 = DEFAULT_COLOR

    def _pct(key: str, lo: int, hi: int, default: int) -> int:
        v = cfg.get(f"{prefix}_{key}")
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            return default
        return int(v)

    def _entry_num(entry: dict, key: str, lo: int, hi: int, dflt: int) -> int:
        v = entry.get(key)
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            return dflt
        return int(v)

    grad_x = _pct("grad_x", 0, 100, 50)
    grad_y = _pct("grad_y", 0, 100, 42)
    grad_size = _pct("grad_size", 10, 200, 100)

    gradients: list = []
    raw_list = cfg.get(f"{prefix}_gradients")
    if isinstance(raw_list, list):
        for entry in raw_list[:MAX_SPHERES]:
            if not isinstance(entry, dict):
                continue
            g_col = entry.get("color")
            if not isinstance(g_col, str) or not _is_hex(g_col):
                continue
            gradients.append({
                # Normalised to #rrggbb: the CSS builder appends "00"
                # for the transparent stop, which needs six digits.
                "color": _norm_hex(g_col),
                "x": _entry_num(entry, "x", 0, 100, 50),
                "y": _entry_num(entry, "y", 0, 100, 42),
                "size": _entry_num(entry, "size", 10, 200, 100),
            })
    if not gradients:
        gradients = [{
            "color": _norm_hex(colour),
            "x": grad_x,
            "y": grad_y,
            "size": grad_size,
        }]

    return {
        "mode": mode,
        "color": colour,
        "image": image,
        "fit": fit,
        "blur": int(blur),
        "wash": int(wash),
        "color2": colour2,
        "grad_x": grad_x,
        "grad_y": grad_y,
        "grad_size": grad_size,
        "gradients": gradients,
    }


# Sphere cap: four blobs cover every wallpaper anyone has asked for,
# and each one costs a full-viewport gradient layer per paint.
MAX_SPHERES = 4


def _norm_hex(value: str) -> str:
    """#rgb → #rrggbb, lowercased — the transparent-stop trick appends
    an alpha byte and needs exactly six digits before it."""
    v = value.strip()
    if len(v) == 4:
        return "#" + "".join(ch * 2 for ch in v[1:]).lower()
    return v.lower()


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
    """Web-export URL for a stored background image. The name is
    percent-encoded (', #, ?, %, space…) so it embeds in a single-quoted
    CSS ``url()``; the media server matches the decoded path (#26)."""
    safe = safe_image_name(name)
    return f"/_addons/{addon}/user_files/{IMAGE_DIR}/{quote(safe, safe='')}" if safe else ""


# ── On-screen gradient editing (transient, never persisted) ──────────
# Armed by the OPEN Preferences dialog (dashboard._EDIT's pattern):
# while armed, the deck and study screens grow a draggable centre dot
# + size ring for their own gradient. JS owns the live visual during a
# drag (it repaints the page's background inline, no Python round-trip
# per move); Python owns the state — drag-end lands as a
# klaus_note:bggrad pycmd, is CLAMPED here (JS is never trusted), and
# flows into the dialog's pending spec through the registered sink.
_GRAD_EDIT = False
_GRAD_SINK: Any = None

# Removes the editor overlay from a live page (the reviewer keeps its
# page across refresh()'s eval path, so closing Preferences mid-review
# must clean up imperatively; the deck screen just rebuilds).
GRAD_EDIT_CLEANUP_JS = (
    "(function(){var e=document.getElementById('klaus-grad-edit');"
    "if(e){e.remove();}})();"
)


def set_grad_edit(active: bool, sink: Any = None) -> None:
    """Arm/disarm on-screen gradient editing. ``sink(target, x, y,
    size)`` is the open dialog's callback; dropped on disarm so a
    stale dialog can never be written into."""
    global _GRAD_EDIT, _GRAD_SINK
    _GRAD_EDIT = bool(active)
    _GRAD_SINK = sink if active else None


def grad_edit_active() -> bool:
    return _GRAD_EDIT


def grad_edit_event(data: Any) -> None:
    """An editor gesture landed over the bridge: validate the op,
    clamp every value (JS is never trusted — apply_action's rule) and
    forward ``sink(target, op, clean)`` if one is still registered.

    Ops: "geom" (a sphere moved/resized — i, x, y, size), "pick"
    (recolor sphere i — Python opens the colour dialog), "add" (one
    more sphere), "remove" (sphere i). The sink owns list bounds and
    the sphere cap; this owns the numbers.
    """
    sink = _GRAD_SINK
    if sink is None or not isinstance(data, dict):
        return
    op = data.get("op")
    if op not in ("geom", "pick", "add", "remove"):
        return

    def _num(key: str, lo: int, hi: int, default: int) -> int:
        v = data.get(key)
        if not isinstance(v, (int, float)):
            return default
        return int(min(hi, max(lo, v)))

    target = "reviewer" if data.get("target") == "reviewer" else "main"
    clean: dict = {"i": _num("i", 0, MAX_SPHERES - 1, 0)}
    if op == "geom":
        clean.update(
            x=_num("x", 0, 100, 50),
            y=_num("y", 0, 100, 42),
            size=_num("size", 10, 200, 100),
        )
    try:
        sink(target, op, clean)
    except Exception as exc:
        print(f"[klaus_note] gradient edit sink failed: {exc}")


def gradient_edit_eval_js(spec: dict, target: str) -> str:
    """The on-screen editor, as raw JS (for ``web.eval`` into a LIVE
    page — the reviewer mid-review). "" unless the spec is colour
    mode with at least one sphere. Self-guarding: a second injection
    is a no-op, so the eval path and the page-build path can both run.

    One set of handles PER SPHERE — the dot is painted in the
    sphere's own colour, so it doubles as its colour chip:

    - drag the dot        → move that sphere (op "geom")
    - drag its ring grip  → resize it (op "geom")
    - CLICK the dot       → recolor it (op "pick" — Python opens the
                            colour dialog; a click is a press that
                            travelled < 4px)
    - right-click the dot → remove it (op "remove")
    - the ＋ pill          → add a sphere (op "add"; hidden at the cap)

    Geometry drags repaint the whole stack INLINE per pointermove (no
    Python round-trips mid-drag) and send one bridge message on
    release; structural ops send immediately and Python replants the
    editor with fresh indices.
    """
    gradients = spec.get("gradients")
    if spec.get("mode") != "color" or not gradients:
        return ""
    tgt = "reviewer" if target == "reviewer" else "main"
    packed = json.dumps(
        [[g["color"], g["x"], g["y"], g["size"]] for g in gradients],
        separators=(",", ":"),
    )
    return (
        "(function(){"
        "if(document.getElementById('klaus-grad-edit')){return;}"
        f"var T={json.dumps(tgt)},DEF={json.dumps(DEFAULT_COLOR.lower())},"
        f"G={packed},CAP={int(MAX_SPHERES)};"
        "var wrap=document.createElement('div');"
        "wrap.id='klaus-grad-edit';"
        "wrap.style.cssText='position:fixed;inset:0;z-index:2147483000;"
        "pointer-events:none;';"
        "document.body.appendChild(wrap);"
        "var spheres=[];"
        # The JS mirrors gradient_css_value's unset-white skip, and
        # NEVER touches background-color inline: the ground lives in
        # the sheet, keyed on :root.night-mode — an inline colour
        # would floodlight night mode for the rest of the session the
        # moment a drag repainted (geom stays quiet, nothing rebuilds).
        "function stack(){var parts=[];"
        "for(var k=0;k<G.length;k++){var g=G[k];"
        "if(g[0].toLowerCase()===DEF){continue;}"
        "parts.push('radial-gradient(at '+g[1]+'% '+g[2]+'%, '+g[0]"
        "+' 0%, '+g[0]+'00 '+g[3]+'%)');}"
        "return parts.join(', ');}"
        # html only, like the sheet — inline-painting body too would
        # re-double the sphere layers the sheet just un-doubled.
        "function paintBg(){"
        "var el=document.documentElement;"
        "el.style.setProperty('background-image',stack(),'important');"
        "el.style.setProperty('background-attachment','fixed',"
        "'important');}"
        "function send(o){try{pycmd('klaus_note:bggrad:'"
        "+btoa(JSON.stringify(o)));}catch(e){}}"
        "function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v));}"
        "function place(i){var g=G[i],el=spheres[i];"
        "var w=innerWidth,h=innerHeight,cx=w*g[1]/100,cy=h*g[2]/100;"
        "var r=Math.hypot(w,h)/2*g[3]/100;"
        "el.dot.style.left=cx+'px';el.dot.style.top=cy+'px';"
        "el.ring.style.left=(cx-r)+'px';el.ring.style.top=(cy-r)+'px';"
        "el.ring.style.width=2*r+'px';el.ring.style.height=2*r+'px';"
        # The grip rides the ring along the ray toward the viewport
        # centre, CLAMPED into view (1dd33fc): at size 100 the ring
        # radius is the half-diagonal, so an unclamped grip sat
        # off-screen and the radius could never be adjusted. Its drag
        # math is distance-based, so it resizes from wherever it sits.
        "var ga=Math.atan2(h/2-cy,w/2-cx);"
        "var gx=cx+r*Math.cos(ga),gy=cy+r*Math.sin(ga);"
        "gx=clamp(gx,16,w-16);gy=clamp(gy,16,h-16);"
        "el.grip.style.left=gx+'px';el.grip.style.top=gy+'px';}"
        "function placeAll(){for(var i=0;i<spheres.length;i++){place(i);}}"
        # Click vs drag on one element: a press that never travels 4px
        # is a click (recolor); past 4px it is a drag (move/resize).
        # Primary button only: a right-press otherwise starts a drag
        # gesture whose buttonless release reads as a click — so a
        # right-click sent remove AND pick, and the colour dialog
        # opened over a sphere that was just deleted (caught live in
        # the harness payload log).
        "function dragify(el,i,move,clickFn){"
        "el.addEventListener('pointerdown',function(ev){"
        "if(ev.button!==0){return;}"
        "ev.preventDefault();el.setPointerCapture(ev.pointerId);"
        "var sx=ev.clientX,sy=ev.clientY,moved=false;"
        "function mv(e){"
        "if(!moved&&Math.hypot(e.clientX-sx,e.clientY-sy)<4){return;}"
        "moved=true;move(e,G[i]);place(i);paintBg();}"
        "function up(){"
        "el.removeEventListener('pointermove',mv);"
        "el.removeEventListener('pointerup',up);"
        "if(moved){send({target:T,op:'geom',i:i,"
        "x:G[i][1],y:G[i][2],size:G[i][3]});}"
        "else if(clickFn){clickFn();}}"
        "el.addEventListener('pointermove',mv);"
        "el.addEventListener('pointerup',up);});}"
        "function mkSphere(i){"
        "var ring=document.createElement('div');"
        "ring.style.cssText='position:absolute;border:1.5px dashed "
        "rgba(255,255,255,0.75);border-radius:50%;pointer-events:none;"
        "box-shadow:0 0 0 1px rgba(0,0,0,0.25),inset 0 0 0 1px "
        "rgba(0,0,0,0.25);';"
        "var dot=document.createElement('div');"
        "dot.title='Drag to move — click to recolor, "
        "right-click to remove';"
        "dot.style.cssText='position:absolute;width:18px;height:18px;"
        "border-radius:50%;transform:translate(-50%,-50%);"
        "border:2.5px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,0.28),"
        "0 1px 4px rgba(0,0,0,0.45);"
        "pointer-events:auto;cursor:grab;';"
        "dot.style.background=G[i][0];"
        "var grip=document.createElement('div');"
        "grip.title='Drag to resize the fade';"
        "grip.style.cssText='position:absolute;width:14px;height:14px;"
        "border-radius:50%;transform:translate(-50%,-50%);background:#fff;"
        "border:2px solid rgba(0,0,0,0.35);box-shadow:0 1px 3px "
        "rgba(0,0,0,0.4);pointer-events:auto;cursor:crosshair;';"
        "wrap.appendChild(ring);wrap.appendChild(dot);"
        "wrap.appendChild(grip);"
        "dot.addEventListener('contextmenu',function(ev){"
        "ev.preventDefault();ev.stopPropagation();"
        "send({target:T,op:'remove',i:i});});"
        "dragify(dot,i,function(e,g){"
        "g[1]=Math.round(clamp(e.clientX/innerWidth*100,0,100));"
        "g[2]=Math.round(clamp(e.clientY/innerHeight*100,0,100));},"
        "function(){send({target:T,op:'pick',i:i});});"
        "dragify(grip,i,function(e,g){"
        "var w=innerWidth,h=innerHeight,cx=w*g[1]/100,cy=h*g[2]/100;"
        "var r=Math.hypot(e.clientX-cx,e.clientY-cy);"
        "g[3]=Math.round(clamp(r/(Math.hypot(w,h)/2)*100,10,200));},"
        "null);"
        "spheres.push({ring:ring,dot:dot,grip:grip});}"
        "for(var i0=0;i0<G.length;i0++){mkSphere(i0);}"
        "if(G.length<CAP){"
        "var add=document.createElement('div');"
        "add.textContent='+ Add Sphere';"
        "add.title='Add another gradient sphere';"
        "add.style.cssText='position:fixed;left:50%;bottom:18px;"
        "transform:translateX(-50%);padding:6px 14px;border-radius:8px;"
        "background:var(--klaus-accent,#0a84ff);color:#fff;"
        "font:600 12px -apple-system,sans-serif;pointer-events:auto;"
        "cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.35);';"
        "add.addEventListener('click',function(){"
        "send({target:T,op:'add'});});"
        "wrap.appendChild(add);}"
        "addEventListener('resize',placeAll);"
        "placeAll();})();"
    )


def gradient_edit_js(spec: dict, target: str) -> str:
    """The same editor as body HTML, for ``web_content.body`` at page
    build time (deck browser rebuilds; a freshly rendered card)."""
    core = gradient_edit_eval_js(spec, target)
    return f"<script>{core}</script>" if core else ""


def gradient_css_value(spec: dict) -> str:
    """The ``background-image`` stack for colour mode: one radial
    layer per gradient sphere — the sphere's colour at its centre
    fading to the SAME colour at alpha 0 (``{color}00``: same-hue
    transparency, so the fade can't grey out through rgba(0,0,0,0)) —
    listed first-on-top. The shared backdrop (``color2``) is NOT a
    layer here: the builders paint it as ``background-color`` under
    the stack, which is what lets any number of spheres compose
    instead of the top one hiding the rest. "" only for a raw dict
    that never went through resolve() (which always supplies at least
    one sphere). Default ellipse shape on purpose: it scales with the
    viewport's aspect, so a wide window doesn't render a circle with
    clipped corners."""
    gradients = spec.get("gradients")
    if not isinstance(gradients, list) or not gradients:
        return ""
    # A sphere still wearing the default white is UNSET — it paints
    # nothing (over the white day-ground it is invisible anyway, and
    # at night it would sit as a phantom white glow the user never
    # chose). It keeps its handles in the editor; clicking its dot
    # gives it a colour and it joins the paint. Deliberate whites are
    # a hair off-white away.
    return ", ".join(
        f"radial-gradient(at {g['x']}% {g['y']}%, "
        f"{g['color']} 0%, {g['color']}00 {g['size']}%)"
        for g in gradients
        if g["color"].lower() != DEFAULT_COLOR.lower()
    )


def _wash_css(spec: dict) -> str:
    """The image wash (config ``{prefix}_wash``, 0–100, default 0 = off):
    ONE veil over the whole wallpaper, sitting between the picture and
    everything on it — a soft translucent layer plus a Gaussian blur of
    the picture behind it, so a busy photo can be muted without
    re-picking it. Theme-aware on purpose (Pouya picked this variant):
    white in light mode, near-black in night mode, so a wallpaper dims
    at night instead of glowing white; both palettes ship keyed on
    ``:root.night-mode`` (house rule — Anki flips the class with JS and
    never re-runs the injection hook).

    Mechanically a ``body::before`` at ``z-index:-1``: in the root
    stacking context a negative-z positioned descendant paints ABOVE
    the root element's background and BELOW every in-flow box — i.e.
    exactly between the picture (on ``<html>``, see the image branches)
    and the panels/cards. ``pointer-events:none`` so it can never eat a
    click. Distinct from the PANEL frost (``panel_css``): that blurs
    what sits behind each panel, this washes the whole picture once.
    """
    wash = spec.get("wash", 0)
    if not isinstance(wash, (int, float)) or not 0 < wash <= 100:
        return ""
    # Linear ramps, tuned by eye in the Chromium harness: full wash is
    # a heavy-but-not-opaque 0.85 veil over a 24px blur — the picture
    # stays findable at 100, invisible-by-default at 0.
    alpha = round(int(wash) * 0.0085, 4)
    blur_px = round(int(wash) * 0.24, 1)
    filt = f"blur({blur_px}px)"
    return (
        "body::before {"
        " content: '';"
        " position: fixed;"
        " inset: 0;"
        " z-index: -1;"
        " pointer-events: none;"
        f" background: rgba(255,255,255,{alpha});"
        f" -webkit-backdrop-filter: {filt};"
        f" backdrop-filter: {filt};"
        " }"
        ":root.night-mode body::before {"
        f" background: rgba(12,12,14,{alpha});"
        " }"
    )


def _fit_rules(fit: str) -> str:
    if fit == "tile":
        return "background-size: auto; background-repeat: repeat;"
    if fit == "contain":
        return "background-size: contain; background-repeat: no-repeat;"
    return "background-size: cover; background-repeat: no-repeat;"


def main_css(spec: dict, url: str = "") -> str:
    """Background for Anki's own screens (deck list and overview).

    Every mode carries panel_css — panels follow the DESIGN. The modes
    only decide the wallpaper: a photo, a flat colour, or (theme mode)
    none at all, leaving Anki's own ground with Klaus panels on it.
    Native mode never reaches here — top_bar._background_css returns
    "" for the whole design layer when the toggle is off.
    """
    mode = spec.get("mode")
    if mode == "color":
        # Colour mode: gradient spheres as background-image layers
        # over the THEME-AWARE ground as background-color — white by
        # day, the dark tone under :root.night-mode (both palettes in
        # one sheet, the house rule; a baked white ground was a
        # floodlight at night, live complaint 2026-08-30). The pair,
        # not the shorthand, so N spheres compose over one ground. An
        # all-unset stack (every sphere still default white) paints
        # the plain ground alone.
        stack = gradient_css_value(spec)
        image_rule = (
            f" background-image: {stack} !important;"
            " background-attachment: fixed !important;"
            if stack else ""
        )
        return (
            # html ALONE paints the stack, body forced transparent —
            # the image branch's proven layering. Painting both used
            # to composite every semi-transparent sphere layer TWICE,
            # and where the body box ended mid-screen the doubled
            # intensity stopped: a faint horizontal line across the
            # gradient (live complaint, 2026-08-30).
            "html {"
            f" background-color: {DEFAULT_COLOR} !important;"
            f"{image_rule}"
            " }"
            " body { background: transparent !important; }"
            ":root.night-mode {"
            f" background-color: {NIGHT_COLOR} !important;"
            " }"
            + panel_css(spec)
        )
    if mode == "image" and url:
        return (
            # The picture lives on <html> ALONE since the wash shipped
            # (2026-08-30), with <body> forced transparent — not the
            # old html+body pair — so the wash veil (body::before at
            # z-index -1, see _wash_css) has somewhere to sit: above
            # the root element's background, below every in-flow box.
            # With body still painting the image, the veil would be
            # sandwiched UNDER a second copy of the picture and wash
            # nothing. Anki's own sheet paints body with --canvas, so
            # the transparent override is load-bearing, not hygiene.
            "html {"
            f" background-color: {spec['color']} !important;"
            f" background-image: url('{url}') !important;"
            f" background-position: center top !important;"
            f" background-attachment: fixed !important;"
            f" {_fit_rules(spec['fit'])}"
            " }"
            " body { background: transparent !important; }"
            + _wash_css(spec)
            # Panels frost over the (washed) image so their text stays
            # readable.
            + panel_css(spec)
        )
    # Theme mode: no wallpaper — Anki's own ground, Klaus panels on it.
    return panel_css(spec)


def _reviewer_body_reset() -> str:
    """Stop the CARD from painting over the study wallpaper.

    The reviewer's ``<body>`` IS the card — Anki gives it
    ``class="card"`` plus ``nightMode``/``night_mode`` — and shared
    notetypes paint it opaque with !important. AnKing's, verified in
    Pouya's own collection (2026-08-31)::

        .nightMode.card,
        .night_mode .card { background-color: #272828 !important; }

    That is specificity (0,2,0) WITH !important, so it outranks a
    plain ``body { background: transparent !important }`` (0,0,1) and
    hid the wallpaper everywhere the card's box reached — the hard
    line across the study screen, ending at the card's bottom edge.
    The repeated ``.card`` is a deliberate specificity ladder
    ((0,3,2) here), enough headroom to outrank the notetypes in the
    wild without reaching for a higher-origin trick.

    A NARROW, deliberate exception to "a card is the user's own
    notetype, never Klaus's to restyle": only the BACKGROUND is
    neutralised — never text colour, borders, or anything else the
    card designed — and only while a study wallpaper is actually
    configured, since theme mode emits no CSS at all. Choosing
    "Anki's Own" for the study screen hands the card its background
    back.
    """
    return (
        " html body,"
        " html body.card.card,"
        " html body.card.card.nightMode,"
        " html body.card.card.night_mode"
        " { background: transparent !important; }"
    )


def reviewer_css(spec: dict, url: str = "") -> str:
    """Background for the reviewer's card screen — a SEPARATE picture
    from the deck screen's, on purpose (Pouya: "this needs to be
    separate from the background I set for the regular main section").
    Resolved from its own ``reviewer_background_*`` keys via
    ``resolve(cfg, prefix="reviewer_background")``, never coupled to
    the deck screen's spec.

    No panel_css here, and that is deliberate, not an oversight: the
    "panels" being frosted on the deck screen are ANKI'S surfaces
    (the deck table, the heatmap) that Klaus is choosing to restyle —
    the card is the user's own notetype, and Klaus never touches
    content that belongs to the collection. A wallpaper behind the
    card is exactly as far as this goes; if a notetype's own card
    background is opaque, it simply sits on top of it unchanged, the
    same freedom `main_css` already gives the deck screen.

    No PANEL-frost blur control: that blur exists to frost panels, and
    there are none here. The image WASH is a different layer and does
    ship (``_wash_css``, since 2026-08-30) — one theme-aware veil over
    the whole picture, between it and the card, with its own
    ``reviewer_background_wash`` key.
    """
    mode = spec.get("mode")
    if mode == "color":
        stack = gradient_css_value(spec)
        image_rule = (
            f" background-image: {stack} !important;"
            " background-attachment: fixed !important;"
            if stack else ""
        )
        return (
            # html-only + transparent body, same double-paint-seam
            # reason as main_css.
            "html {"
            f" background-color: {DEFAULT_COLOR} !important;"
            f"{image_rule}"
            " }"
            + _reviewer_body_reset()
            + ":root.night-mode {"
            f" background-color: {NIGHT_COLOR} !important;"
            " }"
        )
    if mode == "image" and url:
        return (
            # html-only + transparent body, same reason as main_css:
            # the wash veil sits between the root's picture and the
            # body's content, and a body-painted copy would bury it.
            "html {"
            f" background-color: {spec['color']} !important;"
            f" background-image: url('{url}') !important;"
            f" background-position: center top !important;"
            f" background-attachment: fixed !important;"
            f" {_fit_rules(spec['fit'])}"
            " }"
            + _reviewer_body_reset()
            + _wash_css(spec)
        )
    # Theme mode: Anki's own reviewer background, untouched.
    return ""


def panel_css(spec: dict) -> str:
    """The Klaus panel family — tint, border, corners, the welded
    stats line — for Anki's content panels, in EVERY background mode.

    Panels follow the DESIGN, the wallpaper follows the MODE: since the
    klausbook_design toggle shipped, native mode is where Anki looks
    stock, so "design on" must mean the same panel family whether the
    ground is a photo, a flat colour, or Anki's own — the old
    theme-mode early-return here made KlausBook-over-Anki's-own render
    a half-designed screen (stock grey hover pill, stranded studied
    line, live screenshots 2026-08-30). No gate in this function at
    all: the design gate lives upstream at top_bar._background_css,
    which returns "" for every caller when the toggle is off.

    Only the FROST is mode-dependent (image-only) — a Gaussian blur of
    a flat colour is that colour, so anywhere else backdrop-filter
    would cost a compositing layer per panel to change nothing.

    This is a REAL ``backdrop-filter``, not a painted copy: a deck
    table and the page background it sits on are the same document, so
    the compositor does the actual blurring. Anki was already 90% of
    the way there — ``.fancy table`` is painted with ``--canvas-glass``
    ("transparent background for surfaces containing text") and the
    theme defines ``--blur``, but nothing ever blurred behind it, so
    over a photo the glass was a see-through wash.

    Both palettes ship keyed on Anki's own ``:root.night-mode`` class
    rather than baking whichever is current — the same reason
    theme.toolbar_css takes no ``night`` argument: Anki flips that class
    with JS and never re-runs the hook that injected this.
    """
    mode = spec.get("mode")
    blur = spec.get("blur", DEFAULT_BLUR)
    if not isinstance(blur, (int, float)) or not 0 <= blur <= 100:
        blur = DEFAULT_BLUR
    blur = int(blur)
    # The frost itself is IMAGE-ONLY: a Gaussian blur of a flat colour is
    # that colour, so over a colour or theme ground backdrop-filter would
    # cost a compositing layer per panel to change nothing (this is the
    # panels' OWN frost — the toolbars no longer copy the background at
    # all). The tint, borders, corners and the welded stats line apply
    # in EVERY mode, so the panel LOOK is consistent whichever
    # background is chosen.
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
        # Anki's notice box; .klaus-hm = the review heatmap. All three are
        # real surfaces that carry text. The heatmap opts in here rather
        # than frosting itself so the panel family stays ONE rule —
        # retuning the tint or blur retunes the heatmap with it, and it
        # can never drift out of step with the deck table above it.
        " table, .callout, .klaus-hm {"
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
        # overview screen as well, where a bare `tr:hover td` lit up the
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
        # This row must NEVER take the hover treatment. Anki's own
        # deckbrowser.css hover rule is UNSCOPED — `.current td,
        # tr:hover:not(.top-level-drag-row) td` — so it matches ANY row
        # in the page, this injected one included; and its
        # :first-child/:last-child radius rules BOTH fire on the single
        # colSpan cell (it is first and last), which is what turned the
        # line into a solid grey pill on hover. None of Anki's rules
        # carry !important, so importance alone wins even against the
        # highest-specificity RTL variant ((0,3,2)); the :hover and
        # [dir=rtl] selectors are spelled out anyway, matching how the
        # deck-row rule above documents its RTL twins.
        #
        # Padding is a relationship, not a pair of numbers: generous
        # above (air between the last deck and the line), snug below
        # (the line hugs the panel's bottom edge) — top well over twice
        # the bottom. Pinned as that relationship in test_background.
        " tr.klaus-studied td,"
        " tr.klaus-studied:hover td,"
        " [dir=rtl] tr.klaus-studied:hover td {"
        " background: transparent !important;"
        " border-radius: 0 !important;"
        " padding: 1.4em 12px 0.5em 12px !important;"
        " border: none !important;"
        # Muted on purpose: the line is a status footnote, not a peer
        # of the deck names above it. Anki's own token, never a baked
        # hex, so night mode flips the shade for free.
        " color: var(--fg-subtle, var(--fg-faint)) !important;"
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
        print(f"[klaus_note] background copy failed: {exc}")
        return ""
