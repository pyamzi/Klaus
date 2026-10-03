"""The main window's bottom row: Anki's own deck-list / overview row,
extended with a gear (Anki's Preferences) at its left edge and the
running-task readout at its right edge. Review's answer row is left exactly as Anki draws it.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_bottom_row.py
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

shim = types.ModuleType("aqt.qt")


def _ga(name):
    for m in (QtWidgets, QtCore, QtGui):
        if hasattr(m, name):
            return getattr(m, name)
    if name == "qconnect":
        return lambda sig, fn: sig.connect(fn)
    raise AttributeError(name)


shim.__getattr__ = _ga
sys.modules["aqt.qt"] = shim
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])

calls: list[str] = []
evals: list[str] = []
mw = types.SimpleNamespace(
    onPrefs=lambda: calls.append("prefs"),
    state="deckBrowser",
    bottomWeb=types.SimpleNamespace(eval=evals.append),
)
sys.modules["aqt"].mw = mw

tasks = importlib.import_module("klaus_note.tasks")
tasks.clock = lambda: 1000.0
tasks.run_on_main = lambda fn: fn()
theme = importlib.import_module("klaus_note.theme")
sb = importlib.import_module("klaus_note.status_bar")
br = importlib.import_module("klaus_note.bottom_row")
Task = tasks.Task

section("row_state: what the readout shows")
check("idle: nothing", br.row_state([], 1000.0) == {"text": "", "error": False, "running": False,
                                                   "busy": False, "done": 0, "total": 0})
s = br.row_state([Task("i", "Anemia — Embedding", 3, 10, True, "", 1.0)], 1000.0)
check("a known total fills the bar", s["running"] and not s["busy"] and (s["done"], s["total"]) == (3, 10)
      and s["text"] == "Anemia — Embedding", str(s))
s = br.row_state([Task("s", "Syncing…", 0, 0, False, "", 1.0)], 1000.0)
check("an unknown total animates", s["running"] and s["busy"], str(s))
s = br.row_state([Task("s", "Syncing…", 0, 0, False, "", 999.9)], 1000.0)
check("a task that just began doesn't flash the row", s["text"] == "" and not s["running"], str(s))
s = br.row_state([Task("o", "Ollama", 0, 0, False, "Pull failed: offline", 1.0, True)], 1000.0)
check("a failure reads as one", s["error"] and s["text"] == "Pull failed: offline" and not s["running"], str(s))

section("row_html: the gear and the readout")
html = br.row_html(br.row_state([Task("i", "Anemia", 3, 10, True, "", 1.0)], 1000.0), False)
check("the gear opens Anki's Preferences", f'pycmd("{br.PREFS_CMD}")' in html and "<svg" in html)
check("the readout opens the task list", f'pycmd("{br.TASKS_CMD}")' in html)
check("the gear is no <button> (Anki's bottom-bar CSS would frame it)", "<button" not in html)
check("it starts in the state it was rendered with", "klausStatus(" in html and '"Anemia"' in html)
check("the readout is sized against Anki's first button, and re-sized with the window, so it never runs under it",
      "#outer button" in html and "addEventListener('resize'" in html)
check("the commands are underscore-namespaced (the editor bridge claims klaus_note:)",
      not br.PREFS_CMD.startswith("klaus_note:") and not br.TASKS_CMD.startswith("klaus_note:"))
for night in (False, True):
    pal = {v.lower() for v in theme.palette(night).values() if isinstance(v, str) and v.startswith("#")}
    hexes = {h.lower() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", br.row_html(br.row_state([], 1000.0), night))}
    check(f"night={night}: palette colours only", hexes <= pal, str(hexes - pal))

section("which rows get it")


class DeckBrowserBottomBar:
    pass


class OverviewBottomBar:
    pass


class ReviewerBottomBar:
    pass


for ctx in (DeckBrowserBottomBar(), OverviewBottomBar()):
    wc = types.SimpleNamespace(body="<center>Anki's buttons</center>")
    br._on_webview_content(wc, ctx)
    check(f"{type(ctx).__name__}: Anki's buttons stay, the row is added",
          wc.body.startswith("<center>Anki's buttons</center>") and br.PREFS_CMD in wc.body)
wc = types.SimpleNamespace(body="<center>answer</center>")
br._on_webview_content(wc, ReviewerBottomBar())
check("review's answer row is left exactly as Anki draws it", wc.body == "<center>answer</center>")

section("clicks")
shown: list = []
sb.show_task_list = lambda parent, items, anchor: shown.append(items)
_r = br._on_js_message((False, None), br.PREFS_CMD, DeckBrowserBottomBar())
check("the gear click is claimed, and opens nothing inside the webchannel call", _r == (True, None) and calls == [])
app.processEvents()
check("...Preferences opens a tick later", calls == ["prefs"], str(calls))
tasks.clear()
tasks.clock = lambda: 990.0
tasks.begin("i", "Indexing")
tasks.clock = lambda: 1000.0  # past the show delay
_r = br._on_js_message((False, None), br.TASKS_CMD, None)
app.processEvents()
check("the readout click opens the task list", _r == (True, None) and shown and [t.key for t in shown[-1]] == ["i"],
      str(shown))
check("anything else passes through", br._on_js_message((False, None), "shared", None) == (False, None))

section("live updates")
br.setup()
check("setup listens to the task tracker", br._push in tasks._listeners)
evals.clear()
tasks.update("i", done=2, total=4)
check("a task change reaches the row on the deck screens",
      evals and "klausStatus(" in evals[-1] and json.dumps("Indexing") in evals[-1], str(evals[-1:]))
evals.clear()
mw.state = "review"
tasks.update("i", done=3)
check("...but not during review, whose row is Anki's answer bar", evals == [], str(evals))
mw.state = "overview"
tasks.end("i")
check("...and again on the overview", evals and "klausStatus(" in evals[-1])
tasks.clear()

section("no dock toggle (the Add tab replaced the right dock)")
state = br.row_state([], 1000.0)
html = br.row_html(state, False)
check("the row has no dock toggle and no DOCK_CMD", "klaus_note_row_dock" not in html and not hasattr(br, "DOCK_CMD") and not hasattr(br, "_dock_toggle"))
# The deck screens bind no Space shortcut, so a row button left focused by
# a mouse click took the next Space through klausKey. Mouse presses must
# not focus them; Tab still does.
check("a mouse press never leaves focus on a row button (Space would re-fire it)",
      "addEventListener('mousedown'" in html and ".klaus-edge [role=button]" in html
      and "preventDefault" in html.split("addEventListener('mousedown'", 1)[-1][:200])
check("…while Tab still reaches them", html.count('tabindex="0"') == html.count('role="button"') == 3)  # gear, sync entry, readout
check("an unknown command is left alone", br._on_js_message((False, None), "klaus_note_row_dock", None) == (False, None))
css = html.split("<style>", 1)[-1]
gear_rule = [r for r in css.split("}") if ".kr-gear:hover" in r]
check("the gear keeps its own hover/focus rule (I-3): a wash and no focus ring, not the readout's block",
      len(gear_rule) == 1 and "outline: none" in gear_rule[0] and ".kr-readout" not in gear_rule[0]
      and "min-width" not in gear_rule[0], str(gear_rule))
check("no stray '+' debris in the row html", "+ <" not in html and "+<" not in html)

section("the readout sits at the bottom right, like the Add and Browse bars")
_html = br.row_html(br.row_state([], 1000.0), False)
check("the gear is pinned left, the readout right", re.search(r"#klaus-row \{ left: 8px", _html)
      and re.search(r"#klaus-status \{ right: 8px", _html)
      and _html.index('id="klaus-row"') < _html.index('class="kr-gear"') < _html.index('id="klaus-status"'))
check("…the task name, then its progress bar", _html.index('class="kr-text"') < _html.index('class="kr-track"'))
check("klausStatus and klausFit drive the right-hand block", "getElementById('klaus-status')" in _html
      and "getElementById('klaus-row')" not in _html)

section("the Decks row's height is what the Add and Browse bars follow")
heights = []
real_set = sb.set_row_height
sb.set_row_height = heights.append
web = types.SimpleNamespace(height=lambda: 41)
mw.state = "deckBrowser"
br._report_height(web)
mw.state = "review"
br._report_height(web)
mw.state = "deckBrowser"
check("reported on a deck screen, never from the taller review row", heights == [41], str(heights))
sb.set_row_height = real_set

section("the sync entry (auto sync)")
auto = importlib.import_module("klaus_note.auto_sync")
synced: list = []
auto.sync_now = lambda: synced.append(1)
TIP = "Synced with AnkiWeb 4 min ago. Click to sync now."
html = br.row_html(br.row_state([], 1000.0), False, {"visible": True, "state": "synced", "tip": TIP, "red": False})
check("the icon sits at the far right, after the readout",
      'id="klaus-sync"' in html and html.index('id="klaus-sync"') > html.index('class="kr-readout"')
      and br.SYNC_CMD in html, html[-900:])
check("...an icon, no text; the tooltip explains it",
      auto.icon_svg("synced", br.SYNC_ICON_PX) in html and f'title="{TIP}"' in html and f'aria-label="{TIP}"' in html
      and ">Synced" not in html)
red = br.row_html(br.row_state([], 1000.0), False, {"visible": True, "state": "failed", "tip": "x", "red": True})
check("red state carries the error class", "kr-sync-red" in red)
spin = br.row_html(br.row_state([], 1000.0), False, {"visible": True, "state": "syncing", "tip": "x", "red": False})
check("syncing spins (and stops under reduce-motion)", "kr-sync-spin" in spin and "reduce-motion" in spin)
off = br.row_html(br.row_state([], 1000.0), False, {"visible": False, "state": "never", "tip": "", "red": False})
check("hidden when logged out", 'id="klaus-sync"' in off and 'style="display:none"' in off)
check("the sync click is deferred a tick",
      br._on_js_message((False, None), br.SYNC_CMD, None) == (True, None) and synced == [])
app.processEvents()
check("...then runs sync_now", synced == [1], str(synced))
evals.clear()
mw.state = "overview"
br._push_sync({"visible": True, "state": "full", "tip": "t", "red": True})
check("live update evals klausSync with the icon on the deck screens",
      any("klausSync(" in e and "svg" in e for e in evals), str(evals))
evals.clear()
mw.state = "review"
br._push_sync({"visible": True, "state": "synced", "tip": "t", "red": False})
check("...never during review", evals == [])
mw.state = "deckBrowser"
check("setup listens to auto sync", br._push_sync in auto._listeners)

raise SystemExit(report())
