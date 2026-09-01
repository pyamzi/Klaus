"""Headless tests for klausmate.dashboard — the Control-Center-style
widget editing on the deck-browser screen.

The DOM half (wrapping, edit chrome, drag) is tested for real by
tests/dashboard_js_dom_test.js under node, invoked from here; this file
covers the pure Python layer — the registry, the config policy, the
boot state, the stylesheet — and pins the aqt glue's shape.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, code_only, install, report, section  # noqa: E402

install()
dash = importlib.import_module("klausmate.dashboard")
theme = importlib.import_module("klausmate.theme")


# ------------------------------------------------------------- registry
section("the widget registry")

check("decks is mandatory — no visibility key, so no delete badge and "
      "no way to remove Anki's own deck list",
      dict((w, k) for w, k, _l in dash.WIDGETS)["decks"] is None)
check("every removable widget's visibility key is a real config key, "
      "so ⊖/＋ writes land on something the defaults define",
      all(f'"{key}"' in open("klausmate/config.json").read()
          for _w, key, _l in dash.WIDGETS if key))
check("today's registry is exactly decks + heatmap",
      dash.widget_ids() == ["decks", "heatmap"]
      and dash.removable_ids() == ["heatmap"])
check("every widget carries a human label for the ＋ menu",
      all(label for _w, _k, label in dash.WIDGETS))

section("order normalisation")
check("a non-list degrades to registry order",
      dash.normalize_order(None) == ["decks", "heatmap"]
      and dash.normalize_order("garbage") == ["decks", "heatmap"])
check("unknown ids are dropped — a corrupt entry can never enter config",
      dash.normalize_order(["evil", "heatmap", "decks"])
      == ["heatmap", "decks"])
check("duplicates keep the first occurrence",
      dash.normalize_order(["heatmap", "decks", "heatmap"])
      == ["heatmap", "decks"])
check("missing known ids are appended, so a widget can never be LOST "
      "through the order key (visibility is the bools' job)",
      dash.normalize_order(["heatmap"]) == ["heatmap", "decks"])
check("a saved custom order round-trips untouched",
      dash.normalize_order(["heatmap", "decks"]) == ["heatmap", "decks"])
check("order_from_cfg survives a non-dict",
      dash.order_from_cfg(None) == ["decks", "heatmap"])

section("visibility")
check("mandatory widgets are always shown",
      dash.widget_shown({}, "decks")
      and dash.widget_shown({"heatmap_enabled": False}, "decks"))
check("a removable widget follows its own bool",
      dash.widget_shown({"heatmap_enabled": True}, "heatmap") is True
      and dash.widget_shown({"heatmap_enabled": False}, "heatmap") is False)
check("a corrupt value reads as SHOWN (heatmap.enabled's rule — bad "
      "config must not silently hide a feature)",
      dash.widget_shown({"heatmap_enabled": "no"}, "heatmap") is True)
# The corrupt-VALUE branch above was pinned; the corrupt-CONFIG branch
# beside it was not, and inverting it survived the K-139 mutation audit
# (finding 4). Same documented rule, one step earlier: config that is not
# a dict at all is still not permission to hide a feature.
check("a config that is not a dict at all reads as SHOWN too — the same "
      "rule one step earlier, and the branch a whole unreadable config "
      "falls into",
      dash.widget_shown(None, "heatmap") is True
      and dash.widget_shown("garbage", "heatmap") is True
      and dash.widget_shown([("heatmap_enabled", False)], "heatmap") is True)
check("an unknown id is not shown", dash.widget_shown({}, "evil") is False)


# ------------------------------------------------------- mutation policy
section("apply_action — the gate between the bridge and config")

check("order is re-normalised, never written raw",
      dash.apply_action({"action": "order",
                         "order": ["evil", "heatmap", "heatmap"]})
      == {"dashboard_order": ["heatmap", "decks"]})
check("remove/add write ONLY the widget's own bool",
      dash.apply_action({"action": "remove", "id": "heatmap"})
      == {"heatmap_enabled": False}
      and dash.apply_action({"action": "add", "id": "heatmap"})
      == {"heatmap_enabled": True})
check("removing the mandatory widget is refused",
      dash.apply_action({"action": "remove", "id": "decks"}) is None)
check("unknown ids and junk are refused",
      dash.apply_action({"action": "remove", "id": "evil"}) is None
      and dash.apply_action({"action": "explode"}) is None
      and dash.apply_action("not a dict") is None
      and dash.apply_action(None) is None)

section("bridge payload parsing")
import base64  # noqa: E402
_good = base64.b64encode(json.dumps({"action": "edit-on"}).encode()).decode()
check("a well-formed payload decodes", dash.parse_bridge(_good)
      == {"action": "edit-on"})
check("garbage decodes to None, never an exception into Anki",
      dash.parse_bridge("!!!") is None
      and dash.parse_bridge("") is None
      and dash.parse_bridge(base64.b64encode(b"[1,2]").decode()) is None)


# ------------------------------------------------------------ boot state
section("boot state and boot html")

# Read BEFORE the bridge section below flips it: this is the module's boot
# value, and the audit (finding 3) flipped `_EDIT: bool = False` to True
# with nothing noticing — every deck browser would boot into jiggle mode.
# The flag's RESET paths are source-pinned; its default was not pinned at
# all, and "never persisted, reopening Anki always starts calm" is only
# true if the module-level default is False.
check("edit mode boots OFF — a fresh session must never open jiggling",
      dash._EDIT is False)

_state = dash.boot_state({"heatmap_enabled": False,
                          "dashboard_order": ["heatmap", "decks"]}, True)
check("order, edit flag, removables and labels all ship",
      _state["order"] == ["heatmap", "decks"] and _state["edit"] is True
      and _state["removable"] == ["heatmap"]
      and _state["labels"] == {"heatmap": "Review Heatmap"})
check("hidden is CONFIG-driven — the disabled heatmap is offered "
      "under ＋ even though no DOM was consulted",
      _state["hidden"] == [{"id": "heatmap", "label": "Review Heatmap"}])
check("nothing hidden when everything is enabled",
      dash.boot_state({}, False)["hidden"] == [])

_html = dash.boot_html({"order": [], "note": "</script><b>"}, "/x/dashboard.js?v=5")
check("the state blob cannot terminate its own script element",
      "</script><b>" not in _html.split('<script src')[0]
      and "<\\/script>" in _html)
check("the script src lands verbatim, version and all",
      '<script src="/x/dashboard.js?v=5"></script>' in _html)


# ------------------------------------------------------------ stylesheet
section("stylesheet")

_css = dash.dashboard_css()
check("both palettes ship, keyed on Anki's own night-mode class",
      ":root {" in _css and ":root.night-mode {" in _css)
# K-142 (found by scripts/mutation_audit.py, confirmed by hand): the
# check above only proves the two SELECTORS exist. Swapping the palette
# blocks — light mode painting the DARK palette — left the whole suite
# green, and so did making night identical to day. The invariant is
# that each block carries ITS OWN palette, so pin the values.
_day_blk = re.search(r":root \{(.*?)\}", _css, re.S)
_night_blk = re.search(r":root\.night-mode \{(.*?)\}", _css, re.S)
check("the two palette blocks are not identical — a night mode that "
      "merely repeats day mode is the bug this pin exists to prevent",
      _day_blk is not None and _night_blk is not None
      and _day_blk.group(1) != _night_blk.group(1))
check("...and each block carries its OWN palette's ink, so the two "
      "cannot be swapped and still pass",
      theme.palette(False)["text"].lower() in _day_blk.group(1).lower()
      and theme.palette(True)["text"].lower() in _night_blk.group(1).lower()
      and theme.palette(True)["text"].lower()
      not in _day_blk.group(1).lower())
check("dashboard_css takes no `night` argument (Anki flips the class "
      "with JS and never re-runs the injecting hook)",
      dash.dashboard_css.__code__.co_argcount == 0)
_ocean = dash.dashboard_css()
theme.set_active_theme("claude")
check("the chrome recolours with the accent theme",
      dash.dashboard_css() != _ocean)
theme.set_active_theme("ocean")
check("the jiggle exists and honours Anki's reduce-motion mechanism — "
      "Anki ships NO prefers-reduced-motion CSS; it live-toggles "
      "body.reduce-motion from Python, so keying on that class is the "
      "only off-switch that works",
      "@keyframes klaus-jiggle" in _css
      and "body.klaus-dash-editing .klaus-widget" in _css
      and "body.reduce-motion .klaus-widget { animation: none !important; }"
      in _css)
_wrapper_rule = _css.split(".klaus-widget {", 1)[1].split("}")[0]
check("the wrapper's ONLY width is fit-content — hugs a narrow deck "
      "table (badge on the panel corner, click-outside works beside "
      "it) yet caps at the viewport so the heatmap's max-width:100% "
      "scroller keeps engaging; a forced width (the content-box "
      "overflow class of bug) never appears anywhere",
      "width: fit-content" in _wrapper_rule
      and "max-width: 100%" in _wrapper_rule
      and _wrapper_rule.count("width") == 2
      and not re.search(r"(?<!max-)width: 100%", _css))
check("edit chrome floats ABOVE pdf_drop's PDF drop square "
      "(fixed, z-index 50): bar 60, menus 70",
      "z-index: 60" in _css and "z-index: 70" in _css)
check("the shield outranks page content but sits under the badge",
      "z-index: 5;" in _css and "z-index: 6;" in _css)
check("the ⊖ badge's hit target outgrows its 22px disc via an "
      "invisible halo (HIG asks ~28px+ for pointer targets) — a "
      "pseudo-element is part of the button's hit area",
      ".klaus-w-remove::after {" in _css
      and "inset: -6px" in _css.split(".klaus-w-remove::after {")[1])
check("the badge mirrors to the leading corner in RTL",
      "[dir=rtl] .klaus-w-remove { left: auto; right: -8px; }" in _css)
check("the wrapper hugs what the user can SEE: a wrapped heatmap's "
      "own margins are neutralised, because a child margin sits "
      "INSIDE the wrapper box and floated the \u2296 badge into empty "
      "page space above the panel (screenshot 2026-08-30)",
      ".klaus-widget > .klaus-hm { margin: 0; }" in _css)
check("...and the wrapper carries the vertical rhythm itself",
      "margin: 0 auto 1.1em auto;" in _css)
check("a dragged widget stops jiggling — a CSS animation would "
      "otherwise override the inline drag transform outright",
      "animation: none !important; z-index: 7;" in _css)

section("the wiring (source pins)")
_SRC = open("klausmate/dashboard.py").read()
_CODE = code_only(_SRC)
_gate_slice = _SRC.split("def _on_webview_will_set_content")[1].split(
    "def _on_js_message")[0]
check("the whole dashboard is behind the KlausBook design gate — "
      "widget editing IS design layer, so native mode gets Anki's "
      "stock deck screen with the heatmap in its stock position",
      "design_enabled" in _gate_slice)
check("the off-branch clears the edit flag: toggling the layer off "
      "mid-jiggle leaves no JS to ever send edit-off, and a stale "
      "flag would boot a later re-enable jiggling unprompted",
      "_EDIT = False" in _gate_slice)
check("setup registers content, js-message and profile-open hooks",
      "webview_will_set_content.append(_on_webview_will_set_content)"
      in _CODE
      and "webview_did_receive_js_message.append(_on_js_message)" in _CODE
      and "profile_did_open.append(_on_profile_open)" in _CODE)
check("the add-refresh is deferred, never run inside the webchannel "
      "handler", "QTimer.singleShot(0, _refresh)" in _CODE)
check("_refresh only repaints while the user is still ON the deck "
      "browser — a deferred call may land after they moved on",
      'getattr(mw, "state", "") == "deckBrowser"' in _SRC)
check("the script URL is mtime-versioned (QtWebEngine caches /_addons/ "
      "assets across restarts)", "?v={version}" in _SRC)
check("edit mode is cleared on profile switch",
      "_EDIT = False" in _CODE.split("def _on_profile_open")[1])
check("config writes patch an armed Preferences preview, or the next "
      "preview tick would revert the edit the user just watched",
      "background.preview_active()" in _CODE
      and "background.set_preview(patched)" in _CODE)

section("bridge handler behaviour (stubbed)")
_calls = []
dash.write_cfg = lambda u: _calls.append(u)  # glue stubbed; policy real
check("a foreign message passes through untouched",
      dash._on_js_message(("sentinel",), "klausmate:settings", None)
      == ("sentinel",))
_b = lambda obj: "klausmate:dash:" + base64.b64encode(
    json.dumps(obj).encode()).decode()
_r_on = dash._on_js_message((False, None), _b({"action": "edit-on"}), None)
check("edit-on arms the session flag", dash._EDIT is True)
_r_off = dash._on_js_message((False, None), _b({"action": "edit-off"}), None)
check("edit-off clears it", dash._EDIT is False)
_r_rm = dash._on_js_message(
    (False, None), _b({"action": "remove", "id": "heatmap"}), None)
check("remove writes the widget's bool through the policy gate",
      _calls == [{"heatmap_enabled": False}])
_r_mand = dash._on_js_message(
    (False, None), _b({"action": "remove", "id": "decks"}), None)
check("removing the mandatory widget writes NOTHING",
      _calls == [{"heatmap_enabled": False}])
check("malformed payloads are swallowed",
      dash._on_js_message((False, None), "klausmate:dash:!!!", None)
      == (True, None))

# The "we handled this" half of the bridge contract. Every RETURN out of a
# dash: message must be (True, None): returning False re-opens the message
# to the rest of Anki's hook chain, which then sees an unknown pycmd. The
# K-139 audit flipped five of this handler's six such returns to False with
# nothing noticing (only the malformed-payload one above was pinned). Four
# of those five are reachable and are pinned here; the fifth guards an
# IndexError on message.split(":", 2)[2], which the startswith() check
# above it makes impossible — that one is dead defensive code, and stays a
# survivor by construction rather than by omission.
check("EVERY dash: outcome reports the message handled — armed, cleared, "
      "refused by the policy gate, and written — so a klausmate: pycmd "
      "never falls through to the rest of Anki's hook chain",
      _r_on == (True, None) and _r_off == (True, None)
      and _r_mand == (True, None) and _r_rm == (True, None))
check("a foreign message is the ONE case that keeps travelling, and it "
      "travels unchanged",
      dash._on_js_message(("passing", "through"), "klausmate:lecture", None)
      == ("passing", "through"))


# ----------------------------------------------- the DOM half, for real
section("web/dashboard.js against a fake Anki DOM (node)")
# The dashboard's DOM work — wrapping, ordering, the whole edit mode —
# cannot be proven by source pins. node is not required to develop this
# addon, so when missing this is reported as SKIPPED rather than
# counted as a pass — an unverified behaviour must never look verified.
if shutil.which("node"):
    _here = os.path.dirname(os.path.abspath(__file__))
    _proc = subprocess.run(
        ["node", os.path.join(_here, "dashboard_js_dom_test.js"),
         os.path.join(_here, "..", "klausmate", "web", "dashboard.js")],
        capture_output=True, text=True)
    check("wraps both widgets, applies the saved order, survives theme "
          "mode and foreign addon content, is idempotent, and the whole "
          "edit mode (menu, shields, badge, ＋, Done, Esc) behaves",
          _proc.returncode == 0,
          (_proc.stdout + _proc.stderr).strip().replace("\n", " | "))
else:
    print("  SKIP  dashboard.js DOM behaviour (node not installed) — NOT "
          "counted as a pass")

raise SystemExit(report())
