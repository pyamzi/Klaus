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

# mode: "theme" keeps Anki's own background (the default — Klaus paints
# nothing), "color" a flat fill, "image" a picture from user_files.
MODES = ("theme", "color", "image")
FITS = ("cover", "contain", "tile")

# White on purpose (2026-08-30, Pouya: "I just want those to be white
# for the default") — the deck and study backgrounds both default to a
# plain white ground; the old near-black #1E2225 made a fresh
# colour-mode switch open on a dark blob.
DEFAULT_COLOR = "#FFFFFF"
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
    # Colour mode IS a gradient (flat colour removed 2026-08-30,
    # Pouya: "remove the flat color feature"): color is the CENTRE,
    # color2 the EDGE. A missing/invalid color2 — every pre-gradient
    # config — is DERIVED from the centre colour rather than read as
    # flat, so old configs upgrade to a subtle fade instead of keeping
    # a mode the UI no longer offers. Filled whatever the mode, so a
    # spec that flips to "color" in the open dialog is never caught
    # edgeless. grad_x/grad_y are the centre as % of the viewport,
    # grad_size the edge colour's stop position along the ray.
    colour2 = cfg.get(f"{prefix}_color2")
    if not isinstance(colour2, str) or not _is_hex(colour2):
        colour2 = derive_edge_colour(colour)

    def _pct(key: str, lo: int, hi: int, default: int) -> int:
        v = cfg.get(f"{prefix}_{key}")
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            return default
        return int(v)

    return {
        "mode": mode,
        "color": colour,
        "image": image,
        "fit": fit,
        "blur": int(blur),
        "wash": int(wash),
        "color2": colour2,
        "grad_x": _pct("grad_x", 0, 100, 50),
        "grad_y": _pct("grad_y", 0, 100, 42),
        "grad_size": _pct("grad_size", 10, 200, 100),
    }


def derive_edge_colour(colour: str) -> str:
    """The edge colour a gradient falls back to when none is stored:
    the centre colour pulled ~45% toward black — a quiet vignette, so
    an upgraded pre-gradient config reads as depth, not as a new look.
    Handles both #rgb and #rrggbb (everything _is_hex admits); any
    parse surprise falls back to DEFAULT_COLOR rather than raising."""
    try:
        v = colour.strip().lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
        f = 0.55
        return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))
    except Exception:
        return DEFAULT_COLOR


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


# ── On-screen gradient editing (transient, never persisted) ──────────
# Armed by the OPEN Preferences dialog (dashboard._EDIT's pattern):
# while armed, the deck and study screens grow a draggable centre dot
# + size ring for their own gradient. JS owns the live visual during a
# drag (it repaints the page's background inline, no Python round-trip
# per move); Python owns the state — drag-end lands as a
# klausmate:bggrad pycmd, is CLAMPED here (JS is never trusted), and
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
    """A drag landed over the bridge: clamp every value (JS is never
    trusted — apply_action's rule) and forward to the sink, if one is
    still registered."""
    sink = _GRAD_SINK
    if sink is None or not isinstance(data, dict):
        return

    def _num(key: str, lo: int, hi: int, default: int) -> int:
        v = data.get(key)
        if not isinstance(v, (int, float)):
            return default
        return int(min(hi, max(lo, v)))

    target = "reviewer" if data.get("target") == "reviewer" else "main"
    try:
        sink(
            target,
            _num("x", 0, 100, 50),
            _num("y", 0, 100, 42),
            _num("size", 10, 200, 100),
        )
    except Exception as exc:
        print(f"[klausmate] gradient edit sink failed: {exc}")


def gradient_edit_eval_js(spec: dict, target: str) -> str:
    """The editor itself, as raw JS (for ``web.eval`` into a LIVE page
    — the reviewer mid-review). "" unless the spec is actually a
    gradient. Self-guarding: a second injection is a no-op, so the
    eval path and the page-build path can both run.

    The drag repaints the gradient INLINE on html/body per pointermove
    (same value shape gradient_css_value emits) and only sends the
    bridge message on release — dragging costs zero Python round
    trips, and the sink side must never refresh the page mid-drag.
    """
    if spec.get("mode") != "color" or not spec.get("color2"):
        return ""
    tgt = "reviewer" if target == "reviewer" else "main"
    return (
        "(function(){"
        "if(document.getElementById('klaus-grad-edit')){return;}"
        f"var T={json.dumps(tgt)},X={int(spec['grad_x'])},"
        f"Y={int(spec['grad_y'])},S={int(spec['grad_size'])},"
        f"C={json.dumps(spec['color'])},C2={json.dumps(spec['color2'])};"
        "var wrap=document.createElement('div');"
        "wrap.id='klaus-grad-edit';"
        "wrap.style.cssText='position:fixed;inset:0;z-index:2147483000;"
        "pointer-events:none;';"
        "var ring=document.createElement('div');"
        "ring.style.cssText='position:absolute;border:1.5px dashed "
        "rgba(255,255,255,0.75);border-radius:50%;pointer-events:none;"
        "box-shadow:0 0 0 1px rgba(0,0,0,0.25),inset 0 0 0 1px "
        "rgba(0,0,0,0.25);';"
        "var dot=document.createElement('div');"
        "dot.title='Drag to move the gradient';"
        "dot.style.cssText='position:absolute;width:18px;height:18px;"
        "border-radius:50%;transform:translate(-50%,-50%);"
        "background:var(--klaus-accent,#0a84ff);border:2.5px solid #fff;"
        "box-shadow:0 1px 4px rgba(0,0,0,0.45);pointer-events:auto;"
        "cursor:grab;';"
        "var grip=document.createElement('div');"
        "grip.title='Drag to resize the fade';"
        "grip.style.cssText='position:absolute;width:14px;height:14px;"
        "border-radius:50%;transform:translate(-50%,-50%);background:#fff;"
        "border:2px solid rgba(0,0,0,0.35);box-shadow:0 1px 3px "
        "rgba(0,0,0,0.4);pointer-events:auto;cursor:crosshair;';"
        "wrap.appendChild(ring);wrap.appendChild(dot);wrap.appendChild(grip);"
        "document.body.appendChild(wrap);"
        "function place(){"
        "var w=innerWidth,h=innerHeight,cx=w*X/100,cy=h*Y/100;"
        "var r=Math.hypot(w,h)/2*S/100;"
        "dot.style.left=cx+'px';dot.style.top=cy+'px';"
        "ring.style.left=(cx-r)+'px';ring.style.top=(cy-r)+'px';"
        "ring.style.width=2*r+'px';ring.style.height=2*r+'px';"
        # The grip rides the ring along the ray toward the viewport
        # centre, CLAMPED into view: at grad_size 100 the ring's
        # radius is the half-diagonal, i.e. off-screen — an unclamped
        # grip was unreachable and the radius could then never be
        # adjusted at all. Its drag math is distance-based, so a
        # clamped grip still resizes correctly from wherever it sits.
        "var ga=Math.atan2(h/2-cy,w/2-cx);"
        "var gx=cx+r*Math.cos(ga),gy=cy+r*Math.sin(ga);"
        "gx=Math.max(16,Math.min(w-16,gx));"
        "gy=Math.max(16,Math.min(h-16,gy));"
        "grip.style.left=gx+'px';grip.style.top=gy+'px';}"
        "function paintBg(){"
        "var g='radial-gradient(at '+X+'% '+Y+'%, '+C+' 0%, '+C2+' '+S+'%)';"
        "[document.documentElement,document.body].forEach(function(el){"
        "el.style.setProperty('background',g,'important');"
        "el.style.setProperty('background-attachment','fixed','important');"
        "});}"
        "function send(){try{pycmd('klausmate:bggrad:'+btoa(JSON.stringify("
        "{target:T,x:X,y:Y,size:S})));}catch(e){}}"
        "function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v));}"
        "function dragify(el,move){"
        "el.addEventListener('pointerdown',function(ev){"
        "ev.preventDefault();el.setPointerCapture(ev.pointerId);"
        "function mv(e){move(e);place();paintBg();}"
        "function up(){el.removeEventListener('pointermove',mv);"
        "el.removeEventListener('pointerup',up);send();}"
        "el.addEventListener('pointermove',mv);"
        "el.addEventListener('pointerup',up);});}"
        "dragify(dot,function(e){"
        "X=Math.round(clamp(e.clientX/innerWidth*100,0,100));"
        "Y=Math.round(clamp(e.clientY/innerHeight*100,0,100));});"
        "dragify(grip,function(e){"
        "var w=innerWidth,h=innerHeight,cx=w*X/100,cy=h*Y/100;"
        "var r=Math.hypot(e.clientX-cx,e.clientY-cy);"
        "S=Math.round(clamp(r/(Math.hypot(w,h)/2)*100,10,200));});"
        "addEventListener('resize',place);"
        "place();})();"
    )


def gradient_edit_js(spec: dict, target: str) -> str:
    """The same editor as body HTML, for ``web_content.body`` at page
    build time (deck browser rebuilds; a freshly rendered card)."""
    core = gradient_edit_eval_js(spec, target)
    return f"<script>{core}</script>" if core else ""


def gradient_css_value(spec: dict) -> str:
    """The CSS background value for colour mode: a two-stop radial
    gradient, the centre colour (``color``) fading to the edge colour
    (``color2``). resolve() always supplies color2 (deriving one when
    the config has none — flat colour was removed 2026-08-30), so ""
    here only guards a raw dict that never went through resolve().
    Default ellipse shape on purpose: it scales with the viewport's
    aspect, so a wide window doesn't render a circle with clipped
    corners. Centre and size come from ``grad_x``/``grad_y``/
    ``grad_size`` — the values the on-screen drag editor writes."""
    if not spec.get("color2"):
        return ""
    return (
        f"radial-gradient(at {spec['grad_x']}% {spec['grad_y']}%, "
        f"{spec['color']} 0%, {spec['color2']} {spec['grad_size']}%)"
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
        # Colour mode is ALWAYS a gradient now (resolve() derives an
        # edge colour when none is stored — the flat branch was
        # removed 2026-08-30, Pouya's call). The bare-colour fallback
        # below only guards a raw dict that never went through
        # resolve().
        grad = gradient_css_value(spec)
        if grad:
            return (
                # Fixed attachment so scrolling the deck list doesn't
                # slide the gradient's centre — same behaviour as the
                # image wallpaper.
                "html, body {"
                f" background: {grad} !important;"
                " background-attachment: fixed !important;"
                " }"
                + panel_css(spec)
            )
        return (
            "html, body { background: %s !important; }" % spec["color"]
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
        grad = gradient_css_value(spec)
        if grad:
            return (
                "html, body {"
                f" background: {grad} !important;"
                " background-attachment: fixed !important;"
                " }"
            )
        return "html, body { background: %s !important; }" % spec["color"]
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
            " body { background: transparent !important; }"
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
        print(f"[klausmate] background copy failed: {exc}")
        return ""
