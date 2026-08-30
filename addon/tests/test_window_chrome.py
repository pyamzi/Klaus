"""Headless tests for klausmate.window_chrome — the KlausBook layer on
Anki's other windows (Add Cards, Browse, Stats, reviewer bottom bar).

Qt widgets are never constructed here; what CAN be proven headlessly:
the emitted style strings, the gate behaviour (exercised for real with
fakes), the injection JS's escaping, and the wiring shape.
"""
import importlib
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section  # noqa: E402

install()
wc = importlib.import_module("klausmate.window_chrome")
theme = importlib.import_module("klausmate.theme")
background = importlib.import_module("klausmate.background")


# ------------------------------------------------------------- builders
section("browse: harmonize, never transform")
for night in (False, True):
    q = theme.browse_qss(night)
    c = theme.palette(night)
    check(f"night={night}: the table takes the token selection colour",
          f"selection-background-color: {c['selection_bg']}" in q)
    check(f"night={night}: the WINDOW background is explicit — Anki's "
          "optional 'Anki' widget style ships an app-scope "
          "QWidget{background:none}, and only a widget-scope sheet "
          "with a real background survives it",
          f"QMainWindow {{\n        background-color: {c['bg']};" in q)
    check(f"night={night}: the search combo speaks the find bar's "
          "field language (accent focus ring)",
          "QComboBox#searchEdit:focus" in q
          and c["blue_bright"] in q)
check("no layout transformation: the sheet never touches row heights, "
      "paddings on the table, or display",
      "QTableView::item" not in theme.browse_qss(False)
      and "height" not in theme.browse_qss(False))

section("sidebar tree: an instance sheet that re-declares Anki's")
for night in (False, True):
    q = theme.sidebar_tree_qss(night)
    check(f"night={night}: re-declares the padding and zero border "
          "Anki's own widget-level sheet carried — replacing it "
          "wholesale must not visibly shift the tree",
          "padding: 3px;" in q and "padding-right: 0px;" in q
          and "border: 0;" in q)

section("utility windows: grey polarity, one accent")
_u = theme.utility_window_qss(False)
_c = theme.palette(False)
check("bare buttons are SECONDARY grey (Library polarity) — Add, "
      "Close, Help, History and the choosers must not all scream blue",
      f"QPushButton {{\n        background-color: {_c['grey_light']};" in _u)
check("only the dialog-default action takes the accent",
      "QPushButton:default {" in _u and _c["blue"] in _u)

section("editor css: restyle only")
_e = theme.editor_css()
check("both palettes keyed on the night classes AnkiWebView flips live",
      ":root {" in _e and ":root.night-mode," in _e)
check("nothing is ever hidden — restyle, never remove",
      "display: none" not in _e and "display:none" not in _e)
check("the field CONTENT is never styled — only the chrome around it "
      "(toolbar, container border, label)",
      ".field-container {" in _e and ".rich-text-input" not in _e
      and ".editing-area {" not in _e.replace(
          ".field-container", ""))

section("reviewer bar: chrome only, semantics survive by omission")
_r = theme.reviewer_bar_css()
check("the chips are the SAME shared declaration blocks as the top "
      "and deck bottom bars — three bars agree by construction, and "
      "top_bar.py never has to name this surface",
      theme._chip_base_rules() in _r
      and theme._chip_hover_rules() in _r
      and theme._chip_active_rules() in _r)
check("both chrome palettes ship keyed on the night classes",
      "--klaus-chrome" in _r and ":root.night-mode," in _r)
for span in (".stattxt", ".new-count", ".learn-count", ".review-count"):
    check(f"NO rule for {span} — its colour carries scheduling "
          "meaning and passes through untouched",
          span not in _r)
check("keyboard focus stays visible on the reshaped buttons — the "
      "chip strips the border the stock :focus rule relied on",
      "button:focus-visible" in _r and "--klaus-accent" in _r)

section("stats css: four structural vars, nothing else")
_s = theme.stats_css()
for var in ("--canvas:", "--canvas-elevated:", "--border:", "--border-subtle:"):
    check(f"overrides {var}", var in _s)
check("never touches a foreground or graph-semantic variable — the "
      "young/mature/ease series colours carry meaning",
      "--fg" not in _s and "ease" not in _s)
check("both palettes, keyed on Anki's night class",
      ":root {" in _s and ":root.night-mode {" in _s)


# ----------------------------------------------------- injection JS
section("stats injection JS")
# This JS is passed to webview.eval(), never embedded in a <script>
# element — so HTML sequences inside the CSS are inert; the property
# that matters is that the whole CSS travels as ONE JSON string
# literal (quotes, backslashes and newlines escaped), which json.dumps
# guarantees and this asserts by exact presence.
import json as _json
_hostile = 'body{--x:"a\\b"}\n/*}"; alert(1); //*/'
_js = wc.stats_inject_js(_hostile)
check("the CSS travels as exactly one json.dumps literal — quotes, "
      "backslashes and newlines cannot escape into the script",
      _json.dumps(_hostile) in _js)
check("replace-not-stack: removes any prior node by id before append",
      "getElementById" in _js and "old.remove()" in _js
      and wc.STATS_STYLE_ID in _js)


# ------------------------------------------------------- gate behaviour
section("the gate, exercised for real")


class _FakeContent:
    def __init__(self):
        self.head = ""


class ReviewerBottomBar:  # the name IS the contract (name-match branch)
    pass


_orig_config = wc._config
wc._config = lambda: {}
_content = _FakeContent()
wc._on_webview_will_set_content(_content, ReviewerBottomBar())
check("gate off: the reviewer bar webview is left byte-stock",
      _content.head == "")
wc._config = lambda: {"klausbook_design": True}
wc._on_webview_will_set_content(_content, ReviewerBottomBar())
check("gate on: the reviewer sheet lands in head",
      "<style>" in _content.head and "--klaus-chrome" in _content.head)
_content2 = _FakeContent()
wc._on_webview_will_set_content(_content2, object())
check("an unknown context falls through untouched — the deck screen "
      "and its bars stay top_bar's exclusively",
      _content2.head == "")
wc._config = _orig_config

section("wiring shape (source pins)")
_SRC = open("klausmate/window_chrome.py", encoding="utf8").read()
_CODE = code_only(_SRC)
for fn in ("_on_add_cards_did_init", "_on_browser_will_show",
           "_on_stats_dialog_will_show"):
    _slice = _CODE.split(f"def {fn}")[1].split("def _on_")[0]
    check(f"{fn} applies only behind the gate",
          "_gate_on()" in _slice)
check("refresh() reads the gate at WALK time, through the preview "
      "seam — Preferences previews reach open windows",
      "_gate_on()" in _CODE.split("def refresh")[1].split("def _on_add")[0])
check("widgets are remembered UNGATED — a window opened native must "
      "be reachable when the toggle flips on (aqt.dialogs caches "
      "instances all session)",
      "_remember(addcards," in _CODE.split("def _on_add_cards_did_init")[1]
      .split("if _gate_on()")[0])
check("un-apply restores the STASHED original sheet, never a bare "
      "empty string — Anki's own widget-level sheets (sidebar tree, "
      "tag bar) must come back exactly",
      "_klausmate_saved_qss" in _CODE)
check("the theme-change walk is ONE deferred tick — the sidebar tree "
      "re-applies its stock sheet from a handler registered at "
      "Browser construction, so only running after the WHOLE chain "
      "beats it deterministically",
      "QTimer.singleShot(0, refresh)" in _CODE)
check("the stats hook is registered behind hasattr — absence on an "
      "older Anki degrades to a stock stats page, never a crash "
      "(checked against raw source: code_only strips the hook-name "
      "string literal out of the call)",
      'hasattr(gui_hooks, "webview_did_inject_style_into_page")' in _SRC)
check("stats identification prefers the webview kind with a URL "
      "basename fallback",
      "AnkiWebViewKind" in _SRC and "basename" in _CODE)
check("top_bar.py still never names the reviewer bar surface",
      "ReviewerBottomBar" not in open("klausmate/top_bar.py").read())
check("pure half is genuinely aqt-free: the divider exists and "
      "stats_inject_js sits above it (matched as the literal comment "
      "line — the module docstring NAMES the divider earlier, and a "
      "prose match would invert this pin)",
      _SRC.index("def stats_inject_js") < _SRC.index("# aqt glue"))

raise SystemExit(report())
