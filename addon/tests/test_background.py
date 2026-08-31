"""Headless tests for the custom background + frosted deck panels."""
import importlib
import os
import re
import sys
import tempfile

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
bg = importlib.import_module("klausmate.background")

section("resolve: defaults and validation")
d = bg.resolve({})
check("default mode paints nothing", d["mode"] == "theme")
check("non-dict degrades", bg.resolve(None)["mode"] == "theme")
check("unknown mode falls back", bg.resolve({"background_mode": "x"})["mode"] == "theme")
check("bad colour falls back to the default",
      bg.resolve({"background_color": "red"})["color"] == bg.DEFAULT_COLOR)
check("short hex accepted", bg.resolve({"background_color": "#abc"})["color"] == "#abc")
check("bad fit falls back", bg.resolve({"background_fit": "zoom"})["fit"] == "cover")
check("out-of-range blur falls back",
      bg.resolve({"background_blur": 999})["blur"] == bg.DEFAULT_BLUR
      and bg.resolve({"background_blur": "x"})["blur"] == bg.DEFAULT_BLUR)
check("image mode with no image is just the theme",
      bg.resolve({"background_mode": "image", "background_image": ""})["mode"]
      == "theme")

section("image names are contained")
check("path traversal stripped to a basename",
      bg.safe_image_name("../../../../etc/passwd.png") == "passwd.png")
check("non-image extensions refused",
      bg.safe_image_name("evil.py") == "" and bg.safe_image_name("x.exe") == "")
check("dotfiles refused", bg.safe_image_name(".hidden.png") == "")
check("url built under the addon's web export",
      bg.image_url("klausmate", "wall.jpg")
      == "/_addons/klausmate/user_files/backgrounds/wall.jpg")
check("no url without a valid image", bg.image_url("klausmate", "x.py") == "")

section("main_css: Anki's own screens")
check("theme mode paints no WALLPAPER — but the panel family still "
      "ships: panels follow the design, only the wallpaper follows "
      "the mode (KlausBook over Anki's own ground was a half-designed "
      "screen before — stock grey hover, stranded studied line)",
      "html, body { background" not in bg.main_css(bg.resolve({}))
      and "--klaus-panel:" in bg.main_css(bg.resolve({})))
colour = bg.resolve({"background_mode": "color", "background_color": "#123456"})
check("colour mode fills html/body", "#123456" in bg.main_css(colour))
img = bg.resolve({"background_mode": "image", "background_image": "w.jpg"})
url = bg.image_url("klausmate", "w.jpg")
css = bg.main_css(img, url)
check("image mode references the export url", url in css)
check("image mode is fixed + covering",
      "background-attachment: fixed" in css and "cover" in css)
check("image mode without a url degrades to panels-without-wallpaper "
      "— a broken image must not strip the whole panel family",
      "background-image" not in bg.main_css(img, "")
      and "--klaus-panel:" in bg.main_css(img, ""))

section("image wash: ONE veil between the picture and everything on it")
check("resolve reads {prefix}_wash — clamped, default 0 (off)",
      bg.resolve({})["wash"] == 0
      and bg.resolve({"background_wash": 60})["wash"] == 60
      and bg.resolve({"background_wash": 300})["wash"] == 0
      and bg.resolve({"background_wash": "lots"})["wash"] == 0
      and bg.resolve({"reviewer_background_wash": 40},
                     prefix="reviewer_background")["wash"] == 40)
_washed = bg.resolve({"background_mode": "image",
                      "background_image": "w.jpg",
                      "background_wash": 60})
_wcss = bg.main_css(_washed, url)
check("the veil ships only when wash > 0 — the default emits nothing",
      "body::before" in _wcss and "body::before" not in css)
check("the veil sits BETWEEN picture and content: image on <html> "
      "ALONE, body forced transparent (Anki paints body with --canvas "
      "— without the override the veil would be buried under a second "
      "copy of the picture), veil fixed at z-index -1, click-through",
      "html {" in _wcss
      and "body { background: transparent !important; }" in _wcss
      and "z-index: -1;" in _wcss
      and "pointer-events: none;" in _wcss)
check("theme-aware (Pouya picked this variant): white veil by day, "
      "near-black under Anki's own night class — both palettes ship "
      "in one sheet, keyed on :root.night-mode (house rule)",
      "rgba(255,255,255,0.51)" in _wcss
      and ":root.night-mode body::before" in _wcss
      and "rgba(12,12,14,0.51)" in _wcss)
check("the wash blurs the picture itself (backdrop-filter on the "
      "veil), independent of the panels' own frost knob",
      "backdrop-filter: blur(14.4px)" in _wcss)
check("the panel family still frosts ON TOP of the washed picture",
      "--klaus-panel:" in _wcss)
check("the reviewer gets the same veil from its OWN key — and its "
      "image also moves to html-only with the transparent body",
      "body::before" in bg.reviewer_css(
          bg.resolve({"reviewer_background_mode": "image",
                      "reviewer_background_image": "s.jpg",
                      "reviewer_background_wash": 30},
                     prefix="reviewer_background"), "u.png")
      and "body { background: transparent !important; }"
      in bg.reviewer_css(
          bg.resolve({"reviewer_background_mode": "image",
                      "reviewer_background_image": "s.jpg"},
                     prefix="reviewer_background"), "u.png"))

section("colour mode IS a stack of gradient spheres (flat removed)")
# Flat colour was removed outright (2026-08-30), and the backdrop is
# NOT an option (Pouya: "the edge color... shouldn't be an option at
# all") — every sphere fades over the default white ground, and any
# color2 stored during the brief era it was configurable is ignored.
check("the backdrop is ALWAYS the default ground — a stored color2 "
      "is ignored, never an option",
      bg.resolve({"background_mode": "color"})["color2"]
      == bg.DEFAULT_COLOR
      and bg.resolve({"background_color2": "#123456"})["color2"]
      == bg.DEFAULT_COLOR
      and not hasattr(bg, "derive_edge_colour"))
check("the GROUND follows the theme — white by day, the dark tone "
      "under :root.night-mode, both palettes in one sheet (house "
      "rule; a baked white ground was a floodlight at night — live "
      "complaint 2026-08-30) — in BOTH builders",
      f"background-color: {bg.DEFAULT_COLOR} !important;"
      in bg.main_css(colour)
      and ":root.night-mode, :root.night-mode body {"
      in bg.main_css(colour)
      and f"background-color: {bg.NIGHT_COLOR} !important;"
      in bg.main_css(colour)
      and f"background-color: {bg.NIGHT_COLOR} !important;"
      in bg.reviewer_css(bg.resolve(
          {"reviewer_background_mode": "color"},
          prefix="reviewer_background")))
check("an UNSET sphere (still default white) paints nothing — over "
      "the white day-ground it is invisible anyway, and at night it "
      "would sit as a phantom glow the user never chose; the default "
      "colour spec renders as the plain theme-aware ground",
      bg.gradient_css_value(bg.resolve({"background_mode": "color"})) == ""
      and "background-image" not in bg.main_css(
          bg.resolve({"background_mode": "color"}))
      and "radial-gradient(" in bg.main_css(colour))
_grad = bg.resolve({"background_mode": "color",
                    "background_color": "#102030",
                    "background_color2": "#a0b0c0",
                    "background_grad_x": 30, "background_grad_y": 70,
                    "background_grad_size": 120})
check("one sphere = one radial layer, its own colour fading to the "
      "SAME colour at alpha 0 (never through black transparent), at "
      "the dragged position and size",
      bg.gradient_css_value(_grad)
      == "radial-gradient(at 30% 70%, #102030 0%, #10203000 120%)")
_multi = bg.resolve({
    "background_mode": "color", "background_color2": "#0b0b10",
    "background_gradients": [
        {"color": "#ff0000", "x": 20, "y": 30, "size": 50},
        {"color": "#00ff00", "x": 80, "y": 60, "size": 90},
        {"color": "not-a-colour"},
        "junk",
    ],
})
check("MULTIPLE spheres stack first-on-top over ONE backdrop — bad "
      "entries are dropped, and the backdrop rides as "
      "background-color so the layers can compose",
      bg.gradient_css_value(_multi)
      == "radial-gradient(at 20% 30%, #ff0000 0%, #ff000000 50%), "
         "radial-gradient(at 80% 60%, #00ff00 0%, #00ff0000 90%)"
      and f"background-color: {bg.DEFAULT_COLOR} !important;"
      in bg.main_css(_multi)
      and "background-image: radial-gradient" in bg.main_css(_multi))
check("the sphere list is capped at MAX_SPHERES and a missing list "
      "is built from the legacy single-gradient keys, #rgb colours "
      "normalised to six digits (the alpha-0 stop needs them)",
      len(bg.resolve({"background_gradients": [
          {"color": "#111111"}] * 9})["gradients"]) == bg.MAX_SPHERES
      and _grad["gradients"] == [
          {"color": "#102030", "x": 30, "y": 70, "size": 120}]
      and bg.resolve({"background_gradients": [
          {"color": "#AbC"}]})["gradients"][0]["color"] == "#aabbcc")
_gcss = bg.main_css(_grad)
check("colour mode paints the gradient fixed — scrolling must not "
      "slide its centre — with the panel family still on top",
      "radial-gradient(at 30% 70%" in _gcss
      and "background-attachment: fixed" in _gcss
      and "--klaus-panel:" in _gcss)
check("geometry is clamped and defaulted — bad values land on centre "
      "50/42 and size 100, and a bad edge colour is re-derived from "
      "the centre: hand-edited config can never emit broken CSS",
      bg.resolve({"background_grad_x": 999})["grad_x"] == 50
      and bg.resolve({"background_grad_y": -3})["grad_y"] == 42
      and bg.resolve({"background_grad_size": 5})["grad_size"] == 100
      and bg.resolve({"background_color2": "red"})["color2"]
      == bg.DEFAULT_COLOR)
_rev_grad = bg.reviewer_css(bg.resolve(
    {"reviewer_background_mode": "color",
     "reviewer_background_gradients": [
         {"color": "#3a6ea5", "x": 40, "y": 40, "size": 80}]},
    prefix="reviewer_background"))
check("the reviewer's colour mode takes the same gradient from its "
      "OWN keys — and still no panel family",
      "radial-gradient(" in _rev_grad
      and "--klaus-panel" not in _rev_grad)

section("on-screen gradient editor (drag on the actual screen)")
_events: list = []
bg.set_grad_edit(True, lambda t, op, d: _events.append((t, op, d)))
bg.grad_edit_event({"target": "reviewer", "op": "geom", "i": 99,
                    "x": 105, "y": -5, "size": 999})
bg.grad_edit_event({"target": "weird", "op": "pick", "i": 1.9})
bg.grad_edit_event({"target": "main", "op": "add"})
bg.grad_edit_event({"target": "main", "op": "explode", "i": 0})
bg.set_grad_edit(False, None)
bg.grad_edit_event({"target": "main", "op": "geom", "i": 0,
                    "x": 1, "y": 1, "size": 50})
check("bridge ops are validated and every value clamped (index "
      "included), the target normalised, unknown ops dropped, and "
      "the whole channel dead after disarm — JS is never trusted and "
      "a stale dialog can never be written into",
      _events == [
          ("reviewer", "geom",
           {"i": bg.MAX_SPHERES - 1, "x": 100, "y": 0, "size": 200}),
          ("main", "pick", {"i": 1}),
          ("main", "add", {"i": 0}),
      ]
      and bg.grad_edit_active() is False)
_ed = bg.gradient_edit_eval_js(_grad, "main")
check("the editor ships for every colour-mode spec (colour mode IS a "
      "gradient now) — image and theme specs grow no handles",
      "klaus-grad-edit" in bg.gradient_edit_eval_js(colour, "main")
      and bg.gradient_edit_eval_js(img, "main") == ""
      and bg.gradient_edit_eval_js(bg.resolve({}), "main") == ""
      and "klaus-grad-edit" in _ed)
check("self-guarding, clamped drag math, drag-end bridge message "
      "(the whole loop verified LIVE in the Chromium harness: a real "
      "drag to the upper-left sent target/x/y/size 'main'/25/25/100 "
      "and repainted the page's gradient inline)",
      "if(document.getElementById('klaus-grad-edit')){return;}" in _ed
      and "klausmate:bggrad:" in _ed
      and "clamp(" in _ed
      and "setPointerCapture" in _ed)
check("each sphere's size grip is CLAMPED into the viewport along "
      "the ray toward the screen centre — at size 100 a ring's "
      "radius is the half-diagonal, so an unclamped grip sat "
      "off-screen and the radius could never be adjusted at all",
      "Math.atan2(h/2-cy,w/2-cx)" in _ed
      and "gx=clamp(gx,16,w-16);" in _ed
      and "gy=clamp(gy,16,h-16);" in _ed)
check("the editor grows one handle set PER sphere, the dot painted "
      "in that sphere's own colour (the dot IS its colour chip), "
      "with click→pick, right-click→remove, and a ＋ pill gated on "
      "the cap",
      "for(var i0=0;i0<G.length;i0++){mkSphere(i0);}" in _ed
      and "dot.style.background=G[i][0];" in _ed
      and "op:'pick'" in _ed and "op:'remove'" in _ed
      and "op:'add'" in _ed and "if(G.length<CAP){" in _ed)
check("the editor never sets background-color inline (the ground "
      "lives in the sheet, keyed on night-mode — an inline colour "
      "would floodlight night for the session) and mirrors the "
      "unset-white skip during drags; the dot carries a hairline "
      "ring so a white sphere's chip stays findable on white",
      "background-color" not in _ed
      and "if(g[0].toLowerCase()===DEF){continue;}" in _ed
      and "0 0 0 1px rgba(0,0,0,0.28)" in _ed)
check("drag/click gestures take the PRIMARY button only — without "
      "the filter a right-press's buttonless release read as a "
      "click, so right-click sent remove AND pick and the colour "
      "dialog opened over a just-deleted sphere (caught live in the "
      "harness payload log)",
      "if(ev.button!==0){return;}" in _ed)
check("the body wrapper is the same core in a <script> tag, and "
      "empty exactly when the core is",
      bg.gradient_edit_js(_grad, "main").startswith("<script>")
      and bg.gradient_edit_js(_grad, "main").endswith("</script>")
      and bg.gradient_edit_js(img, "main") == "")
check("the cleanup JS removes the overlay by id (the reviewer's page "
      "persists across refresh, so removal must be imperative there)",
      "klaus-grad-edit" in bg.GRAD_EDIT_CLEANUP_JS
      and "remove()" in bg.GRAD_EDIT_CLEANUP_JS)

section("resolve(cfg, prefix=...): a second, INDEPENDENT background")
# Pouya: "this needs to be separate from the background I set for the
# regular main section." One validator, two isolated results.
check("prefix defaults to the deck screen's own keys — every existing "
      "caller (resolve(cfg), no second argument) is unaffected",
      bg.resolve({"background_mode": "color"})["mode"] == "color")
_both = {
    "background_mode": "color", "background_color": "#111111",
    "reviewer_background_mode": "image",
    "reviewer_background_image": "study.jpg",
    "reviewer_background_color": "#222222",
}
_main = bg.resolve(_both)
_study = bg.resolve(_both, prefix="reviewer_background")
check("the two reads never cross-contaminate — setting the deck "
      "screen to a colour has NO effect on the study screen's own "
      "mode, and vice versa",
      _main["mode"] == "color" and _main["color"] == "#111111"
      and _study["mode"] == "image" and _study["color"] == "#222222")
check("the study screen's image is its OWN key, never the deck "
      "screen's (there isn't one here to fall back to)",
      _study["image"] == "study.jpg")
check("an unset study background degrades to theme mode, same as an "
      "unset main one — a profile that never touched this setting "
      "gets Anki's own reviewer background, not a crash",
      bg.resolve({}, prefix="reviewer_background")["mode"] == "theme")
check("bad values in the study prefix fall back exactly like the "
      "main prefix's do — one validator, one set of guarantees",
      bg.resolve({"reviewer_background_color": "not-a-colour"},
                 prefix="reviewer_background")["color"] == bg.DEFAULT_COLOR
      and bg.resolve({"reviewer_background_fit": "zoom"},
                     prefix="reviewer_background")["fit"] == "cover")

section("reviewer_css: the study screen's wallpaper — no panels, no blur")
check("theme mode paints nothing — Anki's own reviewer background, "
      "untouched",
      bg.reviewer_css(bg.resolve({}, prefix="reviewer_background")) == "")
_study_colour = bg.resolve(
    {"reviewer_background_mode": "color",
     "reviewer_background_color": "#654321"},
    prefix="reviewer_background",
)
_colour_css = bg.reviewer_css(_study_colour)
check("colour mode fills html/body", "#654321" in _colour_css)
check("NO panel family — a card's background is the user's own "
      "notetype, never Klaus's to touch",
      "table, .callout" not in _colour_css
      and "--klaus-panel" not in _colour_css)
_study_image = bg.resolve(
    {"reviewer_background_mode": "image",
     "reviewer_background_image": "study.jpg"},
    prefix="reviewer_background",
)
_study_url = bg.image_url("klausmate", "study.jpg")
_image_css = bg.reviewer_css(_study_image, _study_url)
check("image mode references the export url, fixed + covering",
      _study_url in _image_css
      and "background-attachment: fixed" in _image_css
      and "cover" in _image_css)
check("image mode without a url degrades to nothing — same discipline "
      "as the deck screen, a broken image must not paint a blank fill",
      bg.reviewer_css(_study_image, "") == "")
check("NO blur anywhere — there is nothing behind the card for a "
      "compositing layer to frost, so no control does anything here",
      "blur(" not in _colour_css and "blur(" not in _image_css
      and "backdrop-filter" not in _colour_css
      and "backdrop-filter" not in _image_css)
check("the reviewer's own spec still carries a validated blur field "
      "(resolve() is one validator for both) — it is simply never "
      "READ by reviewer_css, which is the guarantee that matters",
      "blur" in _study_colour)

section("store_image")
tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "pic.png")
open(src, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
stored = bg.store_image(tmp, src)
check("stored under user_files/backgrounds", stored == "pic.png")
check("the copy really exists",
      os.path.isfile(os.path.join(tmp, bg.IMAGE_DIR, "pic.png")))
other = os.path.join(tmp, "sub")
os.makedirs(other, exist_ok=True)
src2 = os.path.join(other, "pic.png")
open(src2, "wb").write(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
stored2 = bg.store_image(tmp, src2)
check("a different picture with the same name is versioned, not clobbered",
      stored2 == "pic-2.png"
      and open(os.path.join(tmp, bg.IMAGE_DIR, "pic.png"), "rb").read()
      != open(os.path.join(tmp, bg.IMAGE_DIR, "pic-2.png"), "rb").read())
check("non-images refused",
      bg.store_image(tmp, os.path.join(tmp, "nope.py")) == "")
check("missing files refused", bg.store_image(tmp, "/no/such/file.png") == "")

section("frosted panels over an image (readability)")
# Anki paints .fancy table with --canvas-glass but never blurs behind
# it, so over a photo the "glass" was just a see-through wash. Panels
# are in the SAME document as the page background, so unlike the bars
# they can use a real backdrop-filter.
_img = bg.resolve({"background_mode": "image", "background_image": "p.png",
                   "background_blur": 18})
_panels = bg.panel_css(_img)


def _alphas(css, token):
    """Every alpha declared for a token, light palette then night."""
    import re
    return [float(m) for m in
            re.findall(rf"{token}: rgba\([\d, ]+,\s*([\d.]+)\)", css)]


check("panels frost with a REAL backdrop-filter (same document as the "
      "background, unlike the separate-webview toolbars)",
      "backdrop-filter: blur(18px)" in _panels
      and "-webkit-backdrop-filter: blur(18px)" in _panels)
check("the blur follows the user's own blur setting",
      "blur(18px)" in _panels
      and "blur(22px)" in bg.panel_css(
          bg.resolve({"background_mode": "image",
                      "background_image": "p.png",
                      "background_blur": 22})))
check("the deck table, Anki's callout box and the review heatmap all "
      "get it — the heatmap joins this ONE rule instead of frosting "
      "itself, so it cannot drift out of step with the deck table",
      "table, .callout, .klaus-hm {" in _panels)
check("panels sit on a tint so text stays legible on a busy photo — "
      "a RANGE, not an exact value, so the look can be retuned without "
      "churning this test: sheer enough that the picture still reads as "
      "a picture, opaque enough to lift small text off it",
      all(0.35 <= a <= 0.75
          for a in _alphas(_panels, "--klaus-panel")))
check("BOTH palettes ship, keyed on Anki's own night-mode class — the "
      "theme flips that class with JS and never re-runs our injector",
      ":root.night-mode {" in _panels
      and "--klaus-panel: rgba(38,38,38," in _panels
      and len(_alphas(_panels, "--klaus-panel")) == 2)
check("rules use !important, since Anki's own sheet also sets these",
      _panels.count("!important") >= 4)
check("panels round to Anki's own container radius, with a fallback",
      "var(--border-radius-medium, 12px)" in _panels)

check("the current/hovered deck row joins the glass instead of punching "
      "an opaque slab through it (Anki fills it with --border-subtle)",
      "tr.deck.current td," in _panels
      and "tr.deck:hover:not(.top-level-drag-row) td," in _panels
      and "background: var(--klaus-panel-strong) !important;" in _panels)
check("the row rule is scoped to tr.deck — unscoped, it also matched the "
      "OVERVIEW's layout table and turned its cells into opaque slabs on "
      "hover, inside the frosted panel (Anki's own copy of this rule is "
      "unscoped but ships only in deckbrowser.css; ours is injected into "
      "the overview screen too)",
      "tr:hover" not in _panels.replace("tr.deck:hover", "")
      and " .current td," not in _panels)
_pa, _sa = _alphas(_panels, "--klaus-panel"), _alphas(_panels,
                                                      "--klaus-panel-strong")
check("...and is heavier than the panel in BOTH palettes, but only by a "
      "step — computed from the emitted alphas, so the row can neither "
      "dissolve into the panel nor go back to being a bright slab of its "
      "own. The RELATIONSHIP is the design; either number may be retuned",
      len(_pa) == 2 and len(_sa) == 2
      and all(0 < (s - p) <= 0.25 for s, p in zip(_sa, _pa)))
_row_rule = _panels.split("tr.deck.current td,", 1)[1].split("}", 1)[0]
check("the row does NOT stack a second backdrop-filter — it sits INSIDE "
      "the table, which is already a backdrop root, so one blur is "
      "enough (#studiedToday is a SIBLING of the table and does need "
      "its own, which is why this asks about the row rule specifically)",
      "backdrop-filter" not in _row_rule)
check("Anki's RTL rules are more specific than its plain ones, so the "
      "row selector spells the [dir=rtl] variants out to match them — "
      "scoped to tr.deck like their LTR twins",
      "[dir=rtl] tr.deck.current td," in _panels
      and "[dir=rtl] tr.deck:hover:not(.top-level-drag-row) td {"
      in _panels)

section("the studied-today line lives INSIDE the deck panel")
# Anki renders <center><table>..</table><br>%(stats)s</center>, so the
# line is a SIBLING of the panel. It was first styled as a second box
# made to look joined, which meant keeping two widths in agreement —
# and forcing width:100% overflowed the panel off-screen, because Anki
# gives the table padding:1rem with content-box sizing. panel_js now
# reparents it into the table instead: one box, the table's own width.
check("the row is styled for life inside the table, not as its own box",
      "tr.klaus-studied td," in _panels
      and "tr.klaus-studied #studiedToday { margin: 0 !important; }"
      in _panels)

# Anki's deckbrowser.css hover rule is UNSCOPED (`.current td,
# tr:hover:not(.top-level-drag-row) td`) so it reaches this injected
# row too, and its :first-child/:last-child radius rules both fire on
# the one colSpan cell — the row lit up as a solid grey PILL on hover.
_studied_rule = _panels.split(" tr.klaus-studied td,", 1)[1].split("}")[0]
check("hovering the studied line paints NOTHING — background forced "
      "transparent with !important, which beats Anki's rule at any "
      "specificity since Anki's carries none",
      "background: transparent !important" in _studied_rule
      and "tr.klaus-studied:hover td," in _panels)
check("...in RTL too: Anki's [dir=rtl] hover variant is its most "
      "specific rule (0,3,2), so the RTL twin is spelled out like the "
      "deck-row rule's",
      "[dir=rtl] tr.klaus-studied:hover td {" in _panels)
check("the pill radius is neutralised — first/last-child rounding both "
      "fire on a single colSpan cell",
      "border-radius: 0 !important" in _studied_rule)
check("the line reads as a status footnote, not a peer of the deck "
      "names — colour demoted to Anki's own muted foreground token "
      "(never a baked hex), so night mode flips the shade for free",
      re.search(r"color: var\(--fg-[^;]*!important", _studied_rule)
      is not None)
_pad = re.search(
    r"padding: ([\d.]+)em 12px ([\d.]+)em", _studied_rule)
check("padding is a RELATIONSHIP, not two magic numbers: generous air "
      "above (>= 1.2em, so the line stands off the decks), snug below "
      "(<= 0.6em, hugging the panel's bottom edge), top more than "
      "double the bottom — retunable without churning this test",
      _pad is not None
      and float(_pad.group(1)) >= 1.2
      and float(_pad.group(2)) <= 0.6
      and float(_pad.group(1)) > 2 * float(_pad.group(2)),
      _pad.group(0) if _pad else "no padding rule")
check("no width is set anywhere — that overflow is exactly what the "
      "reparenting removed the need for",
      "width:" not in _panels.replace("min-width", ""))
check("the old two-box weld is fully gone (no flattened table corners, "
      "no <br> hiding, no second panel box)",
      "center > table:has(tr.deck)" not in _panels
      and "center:has(#studiedToday)" not in _panels)
check("the moved row is NOT a tr.deck, so the hover/current rule cannot "
      "highlight it as if it were a deck",
      "tr.klaus-studied" not in _row_rule)
check("the script ships exactly when the panel styling does — which "
      "is now EVERY mode, theme included: the weld belongs to the "
      "design, not to the wallpaper",
      bool(bg.panel_js(_img))
      and bool(bg.panel_js(bg.resolve(
          {"background_mode": "color", "background_color": "#123456"})))
      and bool(bg.panel_js(bg.resolve({"background_mode": "theme"}))))
check("it is a self-contained, fully guarded <script>",
      bg.panel_js(_img).startswith("<script>")
      and bg.panel_js(_img).endswith("</script>")
      and "try{" in bg.panel_js(_img))

# The script is the ONE piece of Klaus that manipulates Anki's DOM, and
# no string pin can tell whether it actually works. tests/
# panel_js_dom_test.js runs it against a fake DOM shaped like Anki's
# real markup. node is not required to develop this addon, so when it is
# missing this is reported as SKIPPED rather than counted as a pass —
# an unverified behaviour must never look like a verified one.
import shutil
import subprocess

if shutil.which("node"):
    _js_body = bg.panel_js(_img).replace("<script>", "").replace(
        "</script>", "")
    _js_path = os.path.join(tempfile.mkdtemp(), "panel.js")
    open(_js_path, "w").write(_js_body)
    _here = os.path.dirname(os.path.abspath(__file__))
    _proc = subprocess.run(
        ["node", os.path.join(_here, "panel_js_dom_test.js"), _js_path],
        capture_output=True, text=True)
    check("the generated script is valid JS and behaves correctly against "
          "a DOM shaped like Anki's — moves the line into the deck table, "
          "removes the gap, is idempotent across re-renders, leaves the "
          "overview alone, and no-ops when there is nothing to move",
          _proc.returncode == 0,
          (_proc.stdout + _proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  panel_js DOM behaviour (node not installed) — NOT "
          "counted as a pass")

section("the KlausBook design gate (design_enabled)")
check("default OFF: Klaus ships as tools inside a stock Anki, and the "
      "KlausBook look is the opt-in",
      bg.design_enabled({}) is False and bg.design_enabled(None) is False)
check("on only when literally True",
      bg.design_enabled({"klausbook_design": True}) is True)
check("corrupt values read as OFF — the OPPOSITE polarity of "
      "heatmap.enabled's corrupt-reads-as-on rule, because a corrupt "
      "entry must not surprise-restyle the user's whole app",
      bg.design_enabled({"klausbook_design": "yes"}) is False
      and bg.design_enabled({"klausbook_design": 1}) is False)
check("resolve() IGNORES the design key — the gate lives at the paint "
      "funnel (top_bar._background_css), never in resolve: Preferences "
      "seeds its widgets through resolve(stored config) and writes the "
      "spec back on Save, so a resolve-level gate would display "
      "'theme' for a stored image background and Save would silently "
      "WIPE it",
      bg.resolve({"background_mode": "image", "background_image": "x.png",
                  "klausbook_design": False})["mode"] == "image")

_colour_panels = bg.panel_css(bg.resolve(
    {"background_mode": "color", "background_color": "#123456"}))
check("panels look the SAME whichever background is painted — colour "
      "mode gets the tint, borders, corners and welded stats line too",
      "table, .callout, .klaus-hm {" in _colour_panels
      and "#studiedToday {" in _colour_panels
      and "--klaus-panel:" in _colour_panels)
check("...but NOT the blur: a Gaussian blur of a flat colour is that "
      "colour, so backdrop-filter there would cost a compositing layer "
      "per panel to change nothing",
      "backdrop-filter" not in _colour_panels)
_theme_panels = bg.panel_css(bg.resolve({"background_mode": "theme"}))
check("theme mode gets the SAME panel family as the painted modes — "
      "since the klausbook_design toggle shipped, NATIVE mode is the "
      "stock-keeper, so 'design on' must mean one look on every "
      "ground (Pouya's call, 2026-08-30)",
      "table, .callout, .klaus-hm {" in _theme_panels
      and "tr.klaus-studied td," in _theme_panels
      and "--klaus-panel:" in _theme_panels)
check("...but the FROST stays image-only in theme mode too — blurring "
      "Anki's flat ground would cost a compositing layer per panel to "
      "change nothing",
      "backdrop-filter" not in _theme_panels)
check("main_css carries the panels in BOTH painted modes",
      "--klaus-panel:" in bg.main_css(bg.resolve(
          {"background_mode": "color", "background_color": "#123456"}))
      and "--klaus-panel:" in bg.main_css(_img, "pic.png"))
check("an out-of-range blur falls back rather than emitting junk CSS",
      f"blur({bg.DEFAULT_BLUR}px)" in bg.panel_css(
          {"mode": "image", "blur": 9999}))
check("main_css ships the panel rules with the image background, so one "
      "injection covers the deck list and the overview alike",
      "backdrop-filter" in bg.main_css(_img, "pic.png")
      and "backdrop-filter" not in bg.main_css(
          bg.resolve({"background_mode": "color"})))

section("unsaved live preview (Appearance previews before Save)")
# Appearance is judged by eye, so Preferences renders accent+background
# live while you configure them — but Save stays the ONLY writer of
# config. The pending background lives here as an override that every
# painting surface consults through effective_cfg().
_STORED = {"background_mode": "color", "background_color": "#112233"}
_PENDING = {"background_mode": "image", "background_image": "pic.png",
            "background_fit": "tile", "background_blur": 5}

bg.set_preview(None)
check("nothing armed by default — a fresh session paints stored config",
      bg.preview_active() is False
      and bg.effective_cfg(_STORED) is _STORED)

bg.set_preview(_PENDING)
check("an armed preview shadows stored config at the paint seam",
      bg.preview_active() is True
      and bg.effective_cfg(_STORED) is _PENDING)
check("the preview really changes what gets painted, end to end",
      bg.resolve(bg.effective_cfg(_STORED))["mode"] == "image"
      and bg.resolve(bg.effective_cfg(_STORED))["fit"] == "tile")
check("resolve() stays a PURE function of its argument — the override "
      "lives at the seam, so every existing resolve(cfg) test still "
      "tests exactly what it says",
      bg.resolve(_STORED)["mode"] == "color"
      and bg.resolve(_STORED)["color"] == "#112233")

bg.set_preview(None)
check("clearing restores stored config (Save and Cancel both land here)",
      bg.preview_active() is False
      and bg.resolve(bg.effective_cfg(_STORED))["mode"] == "color")
bg.set_preview("not a dict")
check("a non-dict clears rather than half-arming the preview",
      bg.preview_active() is False)
bg.set_preview(None)

raise SystemExit(report())
