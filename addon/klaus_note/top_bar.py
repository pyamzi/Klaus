"""The Klaus top bar — Anki's main-window toolbar, restyled in place.

What Pouya asked for after the Workspace detour: keep Anki's single
main window, but make the top toolbar a full-width Klaus bar with the
Klaus mark at the left edge. The toolbar is a webview rendering
``<div class="header">`` (left-tray | links | right-tray), so this is
pure web-side work through two sanctioned hooks:

1. ``webview_will_set_content`` — when the context is
   ``aqt.toolbar.TopToolbar``, inject ``theme.toolbar_css`` into the
   head (the exact mechanism SynapsePro uses). Runs on every toolbar
   draw, so a night-mode flip restyles on the toolbar's own redraw.
2. ``top_toolbar_will_set_left_tray_content`` — prepend the Klaus k
   as the first left-tray item, i.e. the window's left edge.

RESTYLE ONLY: no element is hidden or replaced. Anki's own links,
Klaus's Library link (pdf_drive._on_toolbar_links), and other addons'
toolbar items — AnkiHub included — keep their handlers and inherit the
new look via the shared ``.hitem`` class.

``logo_html`` is aqt-free (pure string) for tests/test_top_bar.py.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from . import settings

# Pouya's hand-drawn k (2026-10-01). ONE path of M/L/Z polygon
# subpaths, verbatim from the white shape in the brand source of record,
# docs/reference/brand/klaus-logo.svg; tests/test_top_bar.py pins the
# two equal so they cannot drift. The file's blue tile is the APP ICON
# only: inside Klaus the mark is the bare k in the text colour.
# Two subpaths (the left dash and the k's body), filled evenodd exactly
# as the file declares it; a traced outline is only guaranteed to read
# as drawn under the rule it was exported with.
#
# THIS IS THE ONE COPY: the toolbar inlines logo_svg(), and Qt surfaces
# (the Preferences sidebar) render the same string with QSvgRenderer.
_LOGO_PATH = (
    "M427,523L421,516L419,515L417,515L416,514L403,514L402,515L399,515L398,516L395,516L394,517L391,517L390,518L385,519L382,521L380,521L379,522L374,523L364,528L362,528L342,538L337,539L334,541L332,541L329,543L327,543L322,546L320,546L304,554L302,556L292,561L290,563L285,565L283,567L225,596L223,598L215,602L213,604L212,604L210,606L209,606L207,608L203,610L196,616L195,616L178,633L178,634L174,638L174,639L170,644L169,647L167,649L166,651L166,653L164,656L164,659L163,660L163,673L164,674L164,676L165,678L167,680L167,681L172,686L173,686L175,688L177,689L179,689L182,691L186,691L187,692L193,692L194,693L203,693L204,692L211,692L212,691L217,691L218,690L225,689L226,688L228,688L229,687L231,687L232,686L237,685L245,681L250,680L253,678L255,678L256,677L258,677L259,676L264,675L274,670L276,670L294,661L296,659L318,648L320,648L327,644L329,644L332,642L334,642L339,639L341,639L346,636L348,636L357,631L359,631L375,623L377,621L384,618L386,616L389,615L391,613L398,610L401,607L405,599L405,597L409,590L409,588L412,582L412,580L413,579L414,574L416,571L416,569L418,566L418,564L423,554L423,552L424,551L425,546L427,543L427,540L428,539L428,534L429,533L429,530L428,529L428,526L427,525Z M1092,510L1086,503L1085,503L1078,497L1070,493L1068,493L1067,492L1065,492L1064,491L1062,491L1061,490L1059,490L1055,488L1052,488L1051,487L1048,487L1047,486L1043,486L1042,485L1037,485L1036,484L1026,484L1025,483L1004,483L1003,484L992,484L991,485L984,485L983,486L977,486L976,487L971,487L970,488L965,488L964,489L959,489L958,490L951,491L947,493L944,493L940,495L937,495L936,496L934,496L930,498L927,498L926,499L923,499L919,501L912,502L908,504L905,504L904,505L901,505L900,506L897,506L896,507L893,507L892,508L889,508L888,509L881,510L877,512L874,512L870,514L867,514L863,516L860,516L859,517L857,517L853,519L850,519L849,520L847,520L846,521L844,521L843,522L838,523L835,525L833,525L830,527L828,527L820,531L818,531L784,548L782,550L769,556L767,558L762,560L757,564L754,565L752,567L748,569L745,572L741,574L734,580L733,580L731,582L730,582L728,584L727,584L725,586L724,586L713,594L703,599L701,601L696,603L694,605L687,608L685,610L680,612L678,614L675,615L673,617L670,618L668,620L660,624L658,626L657,626L655,628L654,628L652,630L651,630L649,632L648,632L646,634L645,634L643,636L642,636L640,638L639,638L637,640L633,642L626,648L622,650L619,653L618,653L615,656L614,656L611,659L610,659L607,662L606,662L603,665L602,665L598,669L597,669L594,672L593,672L590,675L589,675L585,679L584,679L581,682L580,682L577,685L576,685L573,688L572,688L568,692L567,692L563,696L562,696L554,703L553,703L550,706L549,706L540,714L539,714L538,713L538,711L539,710L539,707L540,706L540,704L541,703L541,701L542,700L542,698L543,697L543,695L544,694L544,692L546,688L546,685L548,681L548,678L549,677L549,675L550,674L550,672L551,671L551,669L552,668L552,666L554,662L554,659L555,658L555,656L556,655L556,653L558,649L558,646L559,645L559,643L560,642L560,640L561,639L561,637L563,633L563,630L565,627L565,625L566,624L566,622L567,621L567,619L568,618L568,616L569,615L569,613L570,612L571,607L573,604L573,602L574,601L574,599L575,598L575,596L576,595L577,590L579,587L579,585L580,584L580,582L581,581L581,579L582,578L582,576L583,575L583,573L584,572L584,570L586,566L586,563L587,562L587,560L589,556L589,553L590,552L590,549L591,548L592,541L594,537L594,534L596,530L596,527L597,526L597,524L598,523L598,521L599,520L600,515L602,512L602,510L603,509L604,504L606,501L606,499L608,496L608,494L611,489L611,487L614,482L614,480L618,473L618,471L621,466L621,464L625,457L625,455L628,450L628,448L633,438L634,433L636,430L636,428L637,427L637,425L638,424L638,422L640,418L640,415L642,411L643,404L644,403L644,401L645,400L645,398L646,397L647,392L651,384L651,382L662,360L664,358L668,349L670,347L678,331L678,329L681,324L682,319L684,316L684,314L686,310L686,307L688,303L688,300L689,299L689,297L690,296L690,294L691,293L692,288L694,285L694,283L696,280L696,278L698,275L698,273L699,272L699,270L700,269L700,267L702,263L702,258L703,257L703,235L702,234L702,230L701,229L700,222L699,221L699,219L695,211L691,207L691,206L689,205L686,202L678,198L675,198L674,197L657,197L656,198L653,198L652,199L649,199L646,201L644,201L630,208L628,210L625,211L617,218L616,218L609,225L609,226L602,234L599,240L597,242L596,245L594,247L591,253L589,255L588,258L586,260L585,263L583,265L583,266L581,268L581,269L579,271L579,272L577,274L577,275L575,277L573,281L570,284L570,285L564,293L563,296L561,298L560,301L558,303L547,325L547,327L544,332L543,337L541,340L541,342L539,345L539,347L535,355L534,360L531,365L531,367L528,372L528,374L525,379L525,381L523,384L523,386L519,394L519,396L518,397L518,399L516,403L516,406L515,407L515,410L514,411L513,418L512,419L512,423L511,424L510,431L509,432L509,434L508,435L508,438L507,439L507,441L506,442L506,444L504,448L504,451L503,452L503,454L502,455L502,457L501,458L501,460L500,461L500,463L499,464L499,466L498,467L498,469L497,470L497,472L496,473L496,475L495,476L494,481L492,484L492,486L491,487L490,492L488,495L488,497L487,498L486,503L484,506L484,508L483,509L482,514L480,517L480,519L479,520L479,522L478,523L478,525L477,526L477,528L475,532L475,535L474,536L474,538L473,539L473,541L472,542L472,544L470,548L470,551L469,552L469,554L468,555L468,557L467,558L467,560L466,561L466,563L464,567L464,570L463,571L463,573L462,574L462,576L461,577L461,579L460,580L460,582L459,583L459,585L458,586L458,588L456,592L456,595L454,599L454,602L453,603L453,606L452,607L452,610L451,611L451,614L450,615L450,619L449,620L449,624L448,625L448,630L447,631L447,636L446,637L446,642L445,643L445,647L444,648L444,652L443,653L443,656L442,657L442,660L441,661L440,668L439,669L439,671L438,672L438,675L437,676L437,678L436,679L436,681L435,682L435,684L434,685L434,687L432,691L432,694L431,695L431,697L430,698L429,703L427,706L427,708L426,709L426,711L425,712L424,717L422,720L422,722L421,723L420,728L418,731L418,733L417,734L417,736L416,737L416,739L415,740L415,742L414,743L414,745L412,749L412,752L410,756L410,759L409,760L409,763L408,764L408,767L407,768L407,771L406,772L406,775L405,776L405,779L404,780L404,783L403,784L402,791L401,792L401,794L400,795L400,798L399,799L399,801L398,802L398,804L397,805L397,807L395,811L395,814L394,815L394,817L393,818L392,823L390,826L389,831L387,834L386,839L384,842L384,844L382,847L382,849L378,857L378,859L377,860L376,865L374,868L374,871L372,874L372,877L371,878L371,880L369,884L369,887L367,891L366,898L365,899L365,901L363,905L363,908L362,909L362,911L361,912L360,917L358,920L358,922L355,928L355,930L353,933L353,935L349,942L349,944L345,951L345,953L339,965L338,970L336,973L336,975L334,979L334,982L333,983L333,987L332,988L332,993L331,994L331,1003L332,1004L332,1009L333,1010L333,1013L334,1014L334,1016L336,1019L336,1021L338,1023L340,1027L346,1033L347,1033L349,1035L355,1038L358,1038L359,1039L364,1039L365,1040L369,1040L370,1039L375,1039L376,1038L381,1037L387,1034L393,1029L394,1029L402,1021L403,1021L406,1018L406,1017L424,999L424,998L437,984L437,983L443,976L445,972L448,969L448,968L450,966L450,965L458,954L460,949L462,947L463,944L465,942L466,939L468,937L472,929L474,927L474,926L476,924L476,923L478,921L478,920L486,909L487,906L491,901L492,898L494,896L495,893L497,891L499,886L501,884L513,860L513,858L517,851L517,849L523,837L523,835L525,832L525,830L534,812L535,811L537,811L543,816L544,816L552,823L553,823L559,828L560,828L563,831L564,831L568,835L572,837L575,840L576,840L579,843L580,843L583,846L584,846L588,850L589,850L596,856L600,858L604,862L605,862L608,865L609,865L612,868L613,868L616,871L617,871L620,874L621,874L625,878L626,878L629,881L630,881L633,884L634,884L638,888L639,888L642,891L643,891L646,894L647,894L651,898L652,898L656,902L657,902L661,906L662,906L666,910L667,910L672,915L673,915L678,920L679,920L696,935L697,935L701,939L702,939L706,943L707,943L712,948L713,948L717,952L718,952L722,956L723,956L727,960L728,960L732,964L733,964L740,971L741,971L756,986L757,986L774,1003L775,1003L786,1013L787,1013L790,1016L794,1018L797,1021L800,1022L802,1024L805,1025L807,1027L825,1036L827,1036L830,1038L832,1038L838,1041L840,1041L844,1043L847,1043L851,1045L855,1045L856,1046L860,1046L861,1047L876,1047L877,1046L882,1046L883,1045L885,1045L893,1041L899,1036L899,1035L902,1032L905,1026L905,1024L906,1023L906,1020L907,1019L907,1001L906,1000L906,997L905,996L905,993L904,992L904,990L902,987L902,985L895,971L893,969L893,968L891,966L889,962L878,950L878,949L863,935L862,935L854,927L853,927L845,919L844,919L836,911L835,911L829,905L828,905L824,901L823,901L816,895L815,895L813,893L812,893L810,891L809,891L807,889L806,889L804,887L803,887L801,885L800,885L798,883L794,881L791,878L790,878L788,876L787,876L785,874L781,872L778,869L774,867L771,864L770,864L768,862L767,862L765,860L764,860L753,852L750,851L747,848L746,848L741,844L738,843L736,841L735,841L733,839L732,839L730,837L729,837L727,835L726,835L724,833L723,833L721,831L720,831L718,829L717,829L715,827L714,827L712,825L711,825L709,823L708,823L706,821L705,821L703,819L702,819L700,817L699,817L697,815L696,815L694,813L693,813L691,811L690,811L679,803L676,802L674,800L673,800L671,798L670,798L668,796L667,796L656,788L653,787L650,784L649,784L644,780L641,779L639,777L638,777L636,775L635,775L633,773L632,773L630,771L629,771L627,769L626,769L624,767L623,767L621,765L620,765L618,763L617,763L615,761L611,759L608,756L608,755L611,752L612,752L615,749L616,749L619,746L620,746L623,743L624,743L627,740L628,740L631,737L632,737L635,734L636,734L639,731L640,731L643,728L644,728L647,725L648,725L659,716L660,716L662,714L666,712L669,709L670,709L672,707L673,707L684,699L687,698L692,694L695,693L697,691L700,690L702,688L705,687L707,685L714,682L716,680L723,677L725,675L743,666L745,666L776,650L778,650L783,647L785,647L793,643L795,643L796,642L798,642L799,641L804,640L807,638L810,638L814,636L817,636L821,634L824,634L828,632L831,632L835,630L838,630L839,629L842,629L843,628L846,628L847,627L850,627L852,626L853,628L845,636L845,637L818,664L817,664L801,680L800,680L783,697L783,698L749,733L749,734L744,739L744,740L742,742L742,743L739,747L739,749L737,753L737,757L738,758L738,760L740,764L749,773L750,773L753,776L754,776L756,778L764,782L767,782L768,783L772,783L773,782L778,781L781,779L783,779L785,777L788,776L790,774L791,774L793,772L794,772L796,770L800,768L803,765L804,765L806,763L810,761L813,758L814,758L816,756L817,756L819,754L820,754L822,752L823,752L825,750L826,750L828,748L829,748L840,740L843,739L845,737L851,734L853,732L856,731L864,725L872,721L877,717L880,716L882,714L885,713L887,711L890,710L892,708L895,707L897,705L900,704L902,702L905,701L907,699L910,698L912,696L917,694L919,692L922,691L924,689L927,688L929,686L936,683L938,681L946,677L951,673L954,672L957,669L958,669L960,667L964,665L968,661L969,661L983,649L984,649L991,643L995,641L998,638L999,638L1007,632L1010,631L1012,629L1015,628L1017,626L1020,625L1025,621L1035,616L1037,614L1038,614L1040,612L1041,612L1043,610L1047,608L1054,602L1055,602L1063,594L1064,594L1066,592L1066,591L1073,584L1073,583L1076,580L1076,579L1084,568L1090,555L1092,553L1092,551L1094,548L1094,546L1095,545L1095,543L1097,539L1097,536L1098,535L1098,525L1097,524L1097,521L1096,520L1095,515L1092,511Z"
)

# The file's 1254 box cropped to the k's own bounds (x 163-1098,
# y 197-1047) plus about 4% margin, so the k fills its 26px seat
# instead of floating inside the tile's padding.
LOGO_VIEWBOX = "126 163 1010 918"


def logo_svg(fill: str) -> str:
    """The k as a standalone SVG, filled with ``fill`` (a CSS colour or
    ``var()``). Colour never lives here: the web side passes
    ``--klaus-text``, the Qt side theme.palette()'s text token."""
    return (
        f'<svg width="26" height="26" viewBox="{LOGO_VIEWBOX}" '
        'style="display: block" xmlns="http://www.w3.org/2000/svg">'
        f'<path fill="{escape(fill, quote=True)}" fill-rule="evenodd" '
        f'd="{_LOGO_PATH}"/></svg>'
    )


def logo_html() -> str:
    """The left-edge logo: the inline SVG k. Clicking it opens Klaus's
    own Preferences (``pycmd('klaus_note:settings')``, intercepted in
    :func:`_on_js_message`) — Anki's Decks link sits right beside it,
    so the k is better spent on the settings Anki has no entry for."""
    # The SEAT IS INLINE, and that is the point: these declarations
    # used to live in theme.toolbar_css's #klaus-logo block, which the
    # KlausBook design gate switches off — so the mark moved every time
    # the design layer did. Carrying its own geometry means one
    # definition serves both modes and the mark cannot shift.
    #
    # inline-flex, not flex: as a flex item (the KlausBook tray) it is
    # blockified to flex anyway, but on a stock toolbar's inline run it
    # must not claim its own line. vertical-align centres it against
    # the text links there, and is simply ignored once it IS a flex
    # item. display:block on the svg drops the inline descender gap.
    #
    # The k is in the text colour, matching the bar's labels and the
    # Preferences wordmark (Pouya, 2026-10-01). currentColor fallback:
    # --klaus-text only exists while the design layer injects toolbar_css. On a stock toolbar the k
    # fills in the link's own computed colour — Anki's native
    # foreground — rather than vanishing, since an unresolvable var()
    # makes the fill invalid.
    #
    # The link owns the accessible name; the inline SVG is decorative.
    seat = (
        "display: inline-flex; align-items: center;"
        " vertical-align: middle; padding: 0 8px 0 2px; cursor: pointer"
    )
    return (
        f'<a id="klaus-logo" style="{seat}" '
        'href=# onclick="return pycmd(\'klaus_note:settings\')" '
        'title="Klaus settings" aria-label="Klaus settings">'
        + logo_svg("var(--klaus-text, currentColor)") + "</a>"
    )


def native_chrome_color() -> str | None:
    """The window's ACTUAL background colour as Qt reports it, ``#rrggbb``.

    Pouya wants the bar to read as one surface with the OS title bar
    ("no lines, same exact color", macOS and Windows alike). Hardcoding
    a shade can't do that: the system chrome differs per OS, per
    version and per appearance. Qt's window-role colour follows all of
    that, so it is the closest thing to the title bar we can read
    without touching native window internals (NSWindow / DWM — the
    class of fiddling that killed single-window mode twice here).

    None whenever Qt is unavailable or the colour looks unusable, and
    the CSS token then stands as the fallback.
    """
    try:
        from aqt import mw
        from aqt.qt import QPalette

        colour = mw.palette().color(QPalette.ColorRole.Window)
        if not colour.isValid():
            return None
        return f"#{colour.red():02x}{colour.green():02x}{colour.blue():02x}"
    except Exception:
        return None


def chrome_override_js(colour: str | None) -> str:
    """JS that repaints the bar to ``colour`` (or clears the override).

    Sets the same custom property theme.toolbar_css defines, so the
    stylesheet stays the single source of the rules and this only
    overrides the one value. Clearing restores the token.
    """
    if not colour:
        return (
            "document.documentElement.style.removeProperty('--klaus-chrome');"
        )
    return (
        "document.documentElement.style.setProperty('--klaus-chrome', "
        + json.dumps(colour)
        + ");"
    )


def _push_chrome_colour() -> None:
    """Send the live window colour to the toolbar webview.

    Anki's theme switch never re-runs webview_will_set_content (it only
    toggles classes with JS), so the colour is pushed imperatively here
    instead — from our own theme_did_change hook, one tick later so
    Qt's palette has already been updated by Anki's own handler.
    """
    try:
        from aqt import mw
        from aqt.qt import QTimer

        from . import background

        # With the design layer off there is nothing consuming the
        # variable, and an off state should not be evaling into Anki's
        # toolbar at all. A toggle rebuilds the toolbar page outright,
        # so no stale value survives being un-pushed.
        if not background.design_enabled(background.effective_cfg(_config())):
            return

        def _send() -> None:
            try:
                web = getattr(getattr(mw, "toolbar", None), "web", None)
                if web is None:
                    return
                web.eval(chrome_override_js(native_chrome_color()))
            except Exception as exc:
                print(f"[klaus_note] top bar chrome push failed: {exc}")

        QTimer.singleShot(0, _send)
    except Exception as exc:
        print(f"[klaus_note] top bar chrome schedule failed: {exc}")


def _addon() -> str:
    """The addon's web-export name (its folder under addons21)."""
    try:
        from aqt import mw

        return mw.addonManager.addonFromModule(__name__)
    except Exception:
        return "klaus_note"


def _config() -> dict:
    from . import settings

    return settings.read()


def _background_css() -> str:
    """CSS for Anki's own screens (deck list, overview) — the chosen
    wallpaper plus the panel family. The top and bottom toolbars no
    longer call this: they used to paint a blurred copy of the same
    background under themselves, and Pouya asked for that removed
    (2026-08-30) — the bars now always show flat chrome, independent
    of whatever is chosen here."""
    try:
        from . import background

        # effective_cfg: an unsaved Preferences preview wins over stored
        # config, so appearance edits render live before Save.
        # The design gate lives HERE, at the paint funnel, and NOT in
        # background.resolve(): Preferences seeds its widgets through
        # resolve(stored config) and writes that spec back on Save, so
        # a resolve-level gate would show "theme" for a stored image
        # background and Save would silently wipe it.
        if not background.design_enabled(background.effective_cfg(_config())):
            return ""
        spec = background.resolve(background.effective_cfg(_config()))
        url = background.image_url(_addon(), spec["image"])
        return background.main_css(spec, url)
    except Exception as exc:
        print(f"[klaus_note] background css failed: {exc}")
        return ""


def _reviewer_background_css() -> str:
    """CSS for the reviewer's card screen — its OWN spec, resolved
    from ``reviewer_background_*`` keys, never the deck screen's
    (Pouya: "this needs to be separate from the background I set for
    the regular main section"). Same gate, same preview seam, same
    shape as :func:`_background_css` — just a different prefix and a
    different builder (no panels: see background.reviewer_css)."""
    try:
        from . import background

        if not background.design_enabled(background.effective_cfg(_config())):
            return ""
        cfg = background.effective_cfg(_config())
        spec = background.resolve(cfg, prefix="reviewer_background")
        url = background.image_url(_addon(), spec["image"])
        return background.reviewer_css(spec, url)
    except Exception as exc:
        print(f"[klaus_note] reviewer background css failed: {exc}")
        return ""


def _on_main_webview_content(web_content: Any, context: Any) -> None:
    """Paint custom backgrounds on Anki's own screens.

    The deck list and overview share ONE wallpaper, with the Klaus
    panel family and the studied-line weld on top of it. The reviewer
    gets a SEPARATE, independently configured wallpaper — no panels,
    since a card's background is the user's own notetype, never
    Klaus's to touch (see background.reviewer_css). Deliberately
    excluding the reviewer entirely was the original call here; Pouya
    asked for a study-screen picture of its own instead (2026-08-30).
    """
    try:
        from aqt.deckbrowser import DeckBrowser
        from aqt.overview import Overview
        from aqt.reviewer import Reviewer

        # No congrats screen here on purpose: aqt's deck-description
        # module still exists but the congrats-page class is gone from
        # it in this Anki, and the congrats page itself is a sveltekit
        # page loaded via load_url — it never goes through stdHtml, so
        # this hook never fires for it. An import of that dead symbol
        # lived here for a while, silently failing on every draw.
        if isinstance(context, (DeckBrowser, Overview)):
            css = _background_css()
            if css:
                web_content.head += "<style>" + css + "</style>"
                # Moves the studied-today line into the deck table so it
                # is really inside the panel. No-op on the other screen
                # (nothing there has that id) and in theme mode (empty).
                from . import background

                spec = background.resolve(background.effective_cfg(_config()))
                web_content.body += background.panel_js(spec)
                # Inside `if css` on purpose: css non-empty is the
                # design gate having passed — handles must never
                # appear on a stock screen.
                if background.grad_edit_active():
                    web_content.body += background.gradient_edit_js(
                        spec, "main"
                    )
            return

        # context=self in Reviewer._initWeb (verified against Anki's
        # own source) — the SAME webview showing #qa, not the bottom
        # answer bar (a different context class entirely, owned by
        # window_chrome's chrome-only reviewer sheet).
        if isinstance(context, Reviewer):
            css = _reviewer_background_css()
            if css:
                # The id matters: refresh() previews live edits into
                # this SAME tag by id (reviewer_style_push_js), so the
                # build-time sheet and every later push are one tag —
                # a push can restyle or even empty it, never stack a
                # second sheet under it.
                web_content.head += (
                    '<style id="klaus-reviewer-bg">' + css + "</style>"
                )
                from . import background

                if background.grad_edit_active():
                    web_content.body += background.gradient_edit_js(
                        background.resolve(
                            background.effective_cfg(_config()),
                            prefix="reviewer_background",
                        ),
                        "reviewer",
                    )
    except Exception as exc:
        print(f"[klaus_note] background inject failed: {exc}")


def _on_js_message(handled: tuple, message: str, context: Any) -> tuple:
    """Intercept the k logo's pycmd — Anki's toolbar would otherwise
    treat the unknown command as a link and do nothing — and the
    on-screen gradient editor's drag-end messages."""
    if message.startswith("klaus_note:bggrad:"):
        try:
            import base64

            from . import background

            payload = message.split(":", 2)[2]
            data = json.loads(base64.b64decode(payload).decode("utf-8"))
            # Clamping lives in grad_edit_event — JS is never trusted.
            background.grad_edit_event(data)
        except Exception as exc:
            print(f"[klaus_note] gradient edit message failed: {exc}")
        return (True, None)
    if message == "klaus_note:settings":
        try:
            from aqt.qt import QTimer

            from .manage_models import manage_models_dialog

            # Deferred so the webchannel bridge call unwinds before any
            # dialog work runs (hygiene per tests/test_bridge_reentrancy).
            # NOTE the deferral alone did NOT stop the 2026-08-26 segfault
            # spree — crash reports showed the same devicePixelRatio/
            # flush crash from webchannel, QAction, AND timer dispatch
            # alike. The actual fix is manage_models_dialog opening
            # window-modal via dlg.open() instead of app-modal exec()
            # (see the comment there).
            QTimer.singleShot(0, manage_models_dialog)
        except Exception as exc:
            print(f"[klaus_note] settings open failed: {exc}")
        return (True, None)
    return handled


def reviewer_style_push_js(css: str) -> str:
    """JS that installs ``css`` as the reviewer's Klaus background
    sheet, replace-not-stack (window_chrome's Stats pattern): one
    ``<style id="klaus-reviewer-bg">`` — the same tag the
    will_set_content injection writes — is created on demand, has its
    text swapped on every push, and is removed outright when ``css``
    is empty (theme mode / design off), so a discarded preview leaves
    no sheet behind. Pure string builder, aqt-free for tests."""
    return (
        "(function(){"
        "var el=document.getElementById('klaus-reviewer-bg');"
        f"var css={json.dumps(css)};"
        "if(!css){if(el){el.remove();}return;}"
        "if(!el){el=document.createElement('style');"
        "el.id='klaus-reviewer-bg';document.head.appendChild(el);}"
        "el.textContent=css;})();"
    )


def refresh() -> None:
    """Redraw the toolbar and the current screen after a settings change,
    so a new background lands without restarting Anki."""
    try:
        from aqt import mw

        if getattr(mw, "toolbar", None) is not None:
            mw.toolbar.draw()
        # Mid-review, mw.reset() REBUILDS THE STUDY QUEUES (its own
        # comment in aqt/main.py says so) and re-renders the card —
        # and with Preferences non-modal (2026-08-30) a live-preview
        # tick can land while a card is up, so resetting per tick
        # would flip the answer side away under the user. Push the
        # style into the live page instead: same CSS the
        # will_set_content hook injects, same tag, no rebuild. The
        # deck and overview screens keep the reset — their rebuild is
        # what re-runs the injection hooks and the panel_js weld.
        if getattr(mw, "state", None) == "review":
            web = getattr(getattr(mw, "reviewer", None), "web", None)
            if web is not None:
                web.eval(reviewer_style_push_js(_reviewer_background_css()))
                # The reviewer page persists across this path, so the
                # gradient editor must be planted/removed imperatively
                # too: ALWAYS clean, then re-plant while armed — a
                # planted editor holds the colours in its closure, so
                # replacing it (never skipping on "already there") is
                # what keeps a mid-review colour edit from dragging
                # with stale paint. No drag can be in flight during a
                # refresh: refreshes come from dialog edits, and one
                # pointer can't do both.
                from . import background

                editor_js = ""
                if background.grad_edit_active():
                    editor_js = background.gradient_edit_eval_js(
                        background.resolve(
                            background.effective_cfg(_config()),
                            prefix="reviewer_background",
                        ),
                        "reviewer",
                    )
                web.eval(background.GRAD_EDIT_CLEANUP_JS + editor_js)
            return
        mw.reset()
    except Exception as exc:
        print(f"[klaus_note] background refresh failed: {exc}")


def _on_left_tray(content: list, toolbar: Any) -> None:
    """First left-tray item = leftmost element of the bar. Other addons
    appending here (AnkiHub) land to the k's right, untouched."""
    try:
        content.insert(0, logo_html())
    except Exception as exc:
        print(f"[klaus_note] top bar logo failed: {exc}")


def _bar_zoom_css() -> str:
    """The top bar's and the bottom row's size (``bar_scale``; the
    Preferences preview wins), with Anki's own body zoom multiplied in."""
    from . import background, dashboard, theme

    try:
        from aqt import mw

        anki_zoom = float(mw.web.app_zoom_factor())
    except Exception:
        anki_zoom = 1.0
    scale = dashboard.bar_scale_from_cfg(background.effective_cfg(_config()))
    return theme.bar_zoom_css(scale, anki_zoom)


def _on_webview_will_set_content(web_content: Any, context: Any) -> None:
    try:
        from aqt.toolbar import TopToolbar

        from . import background

        # Bar size is a size preference, not the KlausBook restyle: it
        # comes before the design gate, so a stock bar shrinks too.
        if isinstance(context, TopToolbar) or type(context).__name__ in (
            "DeckBrowserBottomBar",
            "OverviewBottomBar",
        ):
            web_content.head += "<style>" + _bar_zoom_css() + "</style>"

        # The KlausBook design gate. Without it these two sheets were
        # injected UNCONDITIONALLY — the one part of the design layer
        # no config key reached. The _background_css calls below gate
        # themselves through the same check; this return also covers
        # the theme.*_css restyles.
        if not background.design_enabled(
            background.effective_cfg(_config())
        ):
            return

        # The bottom toolbar (deck-browser/overview buttons) gets the
        # SAME chrome as the top, so the window is bracketed by
        # matching bars. Matched by class NAME: these contexts live in
        # aqt.deckbrowser/aqt.overview and importing both here for an
        # isinstance would be needless coupling. The reviewer's answer
        # bar is deliberately excluded — its colours carry scheduling
        # meaning. No wallpaper copy here (removed 2026-08-30, Pouya's
        # call) — the bar is always flat chrome, whatever background
        # mode the deck screen is painted with.
        if type(context).__name__ in (
            "DeckBrowserBottomBar",
            "OverviewBottomBar",
        ):
            from . import theme

            web_content.head += (
                "<style>" + theme.bottombar_css() + "</style>"
            )
            return

        if not isinstance(context, TopToolbar):
            return
        from . import theme

        # No night_mode() snapshot on purpose: the sheet carries BOTH
        # palettes keyed on Anki's own night-mode classes, so the bar
        # follows a theme switch live (Anki toggles those classes with
        # JS and never re-runs this hook). See theme.toolbar_css.
        web_content.head += "<style>" + theme.toolbar_css() + "</style>"
    except Exception as exc:
        print(f"[klaus_note] top bar css failed: {exc}")


def _on_profile_open_redraw() -> None:
    """Redraw the top toolbar once the profile's accent theme is loaded.

    Anki draws the toolbar in ``finish_ui_setup()`` — BEFORE any profile
    opens (verified in aqt/main.py: finish_ui_setup runs during app
    setup, profile_did_open fires later inside loadProfile) — so the
    bar's first sheet bakes the DEFAULT accent, and the k launched
    blue on every restart whatever theme was saved (live repro,
    2026-08-30). ``__init__._apply_color_theme`` loads the saved accent
    on profile_did_open; this handler shares that hook and redraws the
    bar so its baked palette catches up. Deferred one tick
    (window_chrome's pattern) so it runs after EVERY other profile-open
    handler regardless of registration order. Ungated on purpose: in
    native mode the redraw just repaints the stock bar once — cheaper
    than a gate that would go stale if a profile flips the design on.
    """
    try:
        from aqt import mw
        from aqt.qt import QTimer

        def _redraw() -> None:
            try:
                if getattr(mw, "toolbar", None) is not None:
                    mw.toolbar.draw()
            except Exception as exc:
                print(f"[klaus_note] toolbar accent redraw failed: {exc}")

        QTimer.singleShot(0, _redraw)
    except Exception as exc:
        print(f"[klaus_note] toolbar accent redraw schedule failed: {exc}")


def setup() -> None:
    try:
        from aqt import gui_hooks

        gui_hooks.top_toolbar_will_set_left_tray_content.append(_on_left_tray)
        gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
        gui_hooks.webview_will_set_content.append(_on_main_webview_content)
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
        # Anki only toggles CSS classes on theme change; the native
        # window colour has to be re-read and pushed by us.
        gui_hooks.theme_did_change.append(_push_chrome_colour)
        # The bar is drawn before any profile opens (finish_ui_setup),
        # so the saved accent has to be redrawn onto it per profile.
        gui_hooks.profile_did_open.append(_on_profile_open_redraw)
    except Exception as exc:
        print(f"[klaus_note] top bar setup failed: {exc}")
