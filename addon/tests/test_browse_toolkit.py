"""K-170 — the Klaus toolkit strip along the bottom of Browse.

Run: env QT_QPA_PLATFORM=offscreen python3 tests/test_browse_toolkit.py

Three sections, and the middle one is the point.

1. PURE LOGIC — the registry, the refusal ladder, the tier readback, the
   ordering that encodes K-168's finding, and the copy.

2. REAL OFFSCREEN Qt — PyQt6 IS importable under this python (unlike
   Anki's bundled one), so the strip is built for real against a replica
   of Anki's Browse tree read out of ``_aqt/forms/browser_qt6.pyc``.
   This section exists because of the hole the K-169 lane left behind:
   its first sweep passed seventeen mutations while every read-side pin
   was either a negative case or a write, so DISABLING THE FEATURE
   OUTRIGHT left the suite green. So the pins here are deliberately
   POSITIVE — the strip lands in the layout, the buttons exist, the
   tool opens, the gate says YES on a good index, rows reach the tree,
   and the click produces the exact native search string. Break any of
   those and this file goes red.

3. SOURCE PINS — the rules that have no runtime signature: no literal
   hex, no app-modal exec, the K-115 painter finally, the deliberate
   ABSENCE of a klausbook_design gate, the absence of any private search
   token, and the worker-thread discipline (the progress callback
   assigns one attribute and touches no widget).
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import types

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import (  # noqa: E402
    check,
    code_only,
    install,
    install_package_stub,
    report,
    section,
)

install()

import klausmate.settings as _settings  # noqa: E402

import importlib  # noqa: E402

bt = importlib.import_module("klausmate.browse_toolkit")
dup = importlib.import_module("klausmate.duplicates")

_SRC = open("klausmate/browse_toolkit.py").read()
_CODE = code_only(_SRC)
_TREE = ast.parse(_SRC)


def _func_src(name: str, parent: str = "") -> str:
    """Source of one function by name (AST, so a docstring that merely
    mentions the name cannot fake a pass). ``parent`` scopes the lookup
    to a nested function inside another one."""
    root = _TREE
    if parent:
        for node in ast.walk(_TREE):
            if isinstance(node, ast.FunctionDef) and node.name == parent:
                root = node
                break
        else:
            return ""
    for node in ast.walk(root):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            if node is root:
                continue
            return ast.get_source_segment(_SRC, node) or ""
    return ""


# ═════════════════════════════════════════════════════════════════════
# 1. Pure logic
# ═════════════════════════════════════════════════════════════════════

section("the registry — one tuple is one tool")

check("TOOLS is a tuple of 4-tuples (id, label, tooltip, factory name)",
      isinstance(bt.TOOLS, tuple)
      and all(isinstance(t, tuple) and len(t) == 4 for t in bt.TOOLS))
check("the duplicate finder is registered and is the only tool so far",
      bt.tool_ids() == ["duplicates"])
check("tool_entry finds a registered tool and misses an unknown one",
      bt.tool_entry("duplicates") is not None
      and bt.tool_entry("nope") is None)
# The factory is named as a STRING (window_chrome._BUILDERS' shape, which
# is what keeps the registry aqt-free). A string that names nothing is
# exactly the failure that shape invites, so pin the resolution too.
check("every registered factory name resolves to a real callable on the "
      "module — a registry entry that names nothing is a dead button",
      all(callable(getattr(bt, name, None))
          for _id, _l, _t, name in bt.TOOLS))
check("tool_factory_name is total: an unknown id yields \"\", never a raise",
      bt.tool_factory_name("duplicates") == "_build_duplicates_panel"
      and bt.tool_factory_name("nope") == ""
      and bt.tool_factory_name(None) == "")
check("every tool's tooltip carries the KlausMate attribution — this "
      "surface ships ungated against stock Anki chrome, so the tooltip "
      "is where it says whose button it is (browse_retention's rule)",
      all(tip.startswith("KlausMate:") for _i, _l, tip, _f in bt.TOOLS))


section("the refusal ladder — a message, not a shrug")

_GOOD = {"exists": True, "count": 500, "provider": "p", "model": "m", "dims": 0}

check("no engine -> the engine message",
      bt.disabled_reason(engine=None, has_profile=True, stats=_GOOD,
                         signature_ok=True) == bt.NO_ENGINE_TEXT)
check("no collection -> the profile message",
      bt.disabled_reason(engine=dup, has_profile=False, stats=_GOOD,
                         signature_ok=True) == bt.NO_PROFILE_TEXT)
check("no index on disk -> the build-an-index message",
      bt.disabled_reason(engine=dup, has_profile=True,
                         stats={"exists": False}, signature_ok=False)
      == bt.NO_INDEX_TEXT)
check("a stats value that is not even a dict still refuses honestly",
      bt.disabled_reason(engine=dup, has_profile=True, stats=None,
                         signature_ok=True) == bt.NO_INDEX_TEXT)
check("wrong embedding model -> the re-index message",
      bt.disabled_reason(engine=dup, has_profile=True, stats=_GOOD,
                         signature_ok=False) == bt.STALE_INDEX_TEXT)
# Order matters: an index built by another model is wrong at any size, so
# "too few notes" would name the wrong thing to fix.
check("signature is checked BEFORE size — a one-note index from the "
      "wrong model reports the model, not the size",
      bt.disabled_reason(engine=dup, has_profile=True,
                         stats={"exists": True, "count": 1},
                         signature_ok=False) == bt.STALE_INDEX_TEXT)
check("an index too small to hold a pair -> the thin-index message",
      bt.disabled_reason(engine=dup, has_profile=True,
                         stats={"exists": True, "count": 1},
                         signature_ok=True) == bt.THIN_INDEX_TEXT)
check("a corrupt count degrades to thin rather than raising",
      bt.disabled_reason(engine=dup, has_profile=True,
                         stats={"exists": True, "count": "many"},
                         signature_ok=True) == bt.THIN_INDEX_TEXT)
check("everything in place -> no refusal at all",
      bt.disabled_reason(engine=dup, has_profile=True, stats=_GOOD,
                         signature_ok=True) == "")
check("every refusal is a real sentence, not a shrug",
      all(len(t) > 20 and t.endswith((".", "…"))
          for t in (bt.NO_ENGINE_TEXT, bt.NO_PROFILE_TEXT, bt.NO_INDEX_TEXT,
                    bt.STALE_INDEX_TEXT, bt.THIN_INDEX_TEXT)))


section("tiers are READ off the engine, never re-spelled")

_tiers = dict((tid, value) for tid, _label, value in bt.tier_choices())
check("the three tier thresholds ARE duplicates.DUPLICATE/NEAR/CLOSE — "
      "the band edges were calibrated on one collection with one model "
      "and a second copy here could silently drift from the engine",
      _tiers == {"duplicate": dup.DUPLICATE, "near": dup.NEAR,
                 "close": dup.CLOSE})
check("tier_choices is ordered tightest first",
      [v for _t, _l, v in bt.tier_choices()]
      == sorted((v for _t, _l, v in bt.tier_choices()), reverse=True))
check("the default tier is the TIGHTEST band — 66,411 pairs across all "
      "three is not a UI, so the surface opens at 2,067 and loosens",
      bt.DEFAULT_TIER == "duplicate"
      and bt.threshold_for(bt.DEFAULT_TIER) == dup.DUPLICATE)
check("threshold_for falls back to the default tier for an unknown id",
      bt.threshold_for("bogus") == dup.DUPLICATE)
check("tier_label names the tiers and misses cleanly",
      bt.tier_label("near") == "Near duplicates" and bt.tier_label("x") == "")


section("wording — a badge and a sort, never a filter")

check("the wording bands are duplicates.py's MEASURED numbers: 0.85 was "
      "the sibling-note floor and 0.40 the genuine-find ceiling",
      bt.SAME_WORDING == 0.85 and bt.SIMILAR_WORDING == 0.40)
check("wording_label bands at exactly those edges",
      bt.wording_label(0.9) == bt.WORDING_SAME
      and bt.wording_label(0.85) == bt.WORDING_SAME
      and bt.wording_label(0.5) == bt.WORDING_SIMILAR
      and bt.wording_label(0.4) == bt.WORDING_SIMILAR
      and bt.wording_label(0.39) == bt.WORDING_DIFFERENT)
check("wording_label is total over junk", bt.wording_label(None) == "")

# THE FINDING, pinned. The highest-scoring pair in Pouya's collection is
# a deliberate contrast pair whose two notes have IDENTICAL word sets
# (the swap is an ordering, not a vocabulary); the genuine find scores
# lower and shares almost no wording. Cosine order puts the untouchable
# pair first. The default order must not.
_CONTRAST = {"a": 1, "b": 2, "score": 0.9983,
             "overlap": dup.lexical_overlap(
                 "increased plasma protein pi GC decreased FF",
                 "decreased plasma protein pi GC increased FF")}
_GENUINE = {"a": 3, "b": 4, "score": 0.9686,
            "overlap": dup.lexical_overlap(
                "HDL transfers cholesteryl esters via CETP",
                "Cholesteryl ester inside of mature HDL may be moved by "
                "the enzyme CETP")}
check("the contrast pair really does have word-set overlap 1.0 — this is "
      "why lexical_overlap sinks it, and it is measured here, not assumed",
      _CONTRAST["overlap"] == 1.0)
check("the genuine find sits under the 0.40 ceiling duplicates.py measured",
      _GENUINE["overlap"] < bt.SIMILAR_WORDING)
check("DEFAULT order puts the genuine find ABOVE the higher-scoring "
      "contrast pair — cosine's top of the list is its worst part",
      [r["a"] for r in bt.sort_rows([_CONTRAST, _GENUINE], bt.DEFAULT_ORDER)]
      == [3, 1])
check("the raw cosine order is still available and really is cosine order",
      [r["a"] for r in bt.sort_rows([_GENUINE, _CONTRAST], bt.ORDER_SCORE)]
      == [1, 3])
check("NEITHER order drops a row — overlap is a sort, never a filter, "
      "because three identical 'Medial lemniscus' notes are real "
      "duplicates at ~0.9 overlap",
      len(bt.sort_rows([_CONTRAST, _GENUINE], bt.DEFAULT_ORDER)) == 2
      and len(bt.sort_rows([_CONTRAST, _GENUINE], bt.ORDER_SCORE)) == 2)
check("equal wording falls back to score descending",
      [r["a"] for r in bt.sort_rows(
          [{"a": 1, "score": 0.90, "overlap": 0.5},
           {"a": 2, "score": 0.95, "overlap": 0.5}], bt.DEFAULT_ORDER)]
      == [2, 1])
check("the default order is the wording one, and both are offered",
      bt.DEFAULT_ORDER == bt.ORDER_DISTINCT
      and [o for o, _l in bt.ORDER_CHOICES]
      == [bt.ORDER_DISTINCT, bt.ORDER_SCORE])


section("rows, ids and copy")


class _P:
    def __init__(self, a, b, score, tier=""):
        self.nid_a, self.nid_b, self.score, self.tier = a, b, score, tier


_rows = bt.build_rows(
    [_P(11, 22, 0.97, "duplicate"), _P(33, 44, 0.96, "duplicate")],
    {11: "alpha beta gamma", 22: "alpha beta gamma", 33: "one two", 44: ""})
# Indexed through a total accessor: dropping a row is one of the
# mutations this section hunts, and an IndexError would abort the whole
# file instead of reporting one clean red line.


def _row(i: int) -> dict:
    return _rows[i] if i < len(_rows) else {}


check("a pair whose note text is missing still renders — dropping it "
      "would be a silent filter over real ids",
      len(_rows) == 2 and _row(1).get("b") == 44)
check("build_rows carries both notes' TEXT — a row of two ids and a "
      "score cannot tell a duplicate from a contrast pair",
      _row(0).get("text_a") == "alpha beta gamma"
      and _row(0).get("text_b") == "alpha beta gamma")
check("build_rows computes overlap once, from the engine's own function",
      _row(0).get("overlap") == 1.0 and _row(1).get("overlap") == 0.0)
check("row_nids flattens in display order, deduplicated",
      bt.row_nids(_rows) == [11, 22, 33, 44])
check("normalize_nids drops junk, zero and negatives, keeps first-seen order",
      bt.normalize_nids([5, "6", 5, 0, -1, None, "x", 7]) == [5, 6, 7])
check("normalize_nids is total over None", bt.normalize_nids(None) == [])

check("result_summary reports the TRUE total beside the shown count, so "
      "a display cap never reads as the answer",
      bt.result_summary(500, {"duplicate": 2067}, "duplicate")
      == "Showing 500 of 2,067 duplicates pairs.")
check("result_summary says nothing found when nothing was",
      bt.result_summary(0, {"duplicate": 0}, "duplicate")
      == "No duplicates pairs found.")
check("result_summary singularises one pair",
      bt.result_summary(1, {"duplicate": 1}, "duplicate")
      == "1 duplicates pair.")
check("a cancelled scan is LABELLED partial, never presented as complete",
      "partial" in bt.result_summary(9, {"duplicate": 9}, "duplicate", True))
check("progress_text is a percentage, total over junk",
      bt.progress_text(50, 100) == "Scanning… 50%"
      and bt.progress_text(1, 0) == bt.SCANNING_TEXT
      and bt.progress_text(None, None) == bt.SCANNING_TEXT)
check("preview_text collapses whitespace and caps with an ellipsis",
      bt.preview_text("  a\n b\tc  ") == "a b c"
      and bt.preview_text("abcdefghij", 5) == "abcd…")
check("the empty state carries the ARGUMENT for the tool: exact_text_"
      "groups returns zero on this collection, so Anki's own Find "
      "Duplicates would show nothing at all",
      "Find Duplicates" in bt.EXACT_NOTE and "mean the same" in bt.EXACT_NOTE)
check("score_text renders three decimals and survives junk",
      bt.score_text(0.9483) == "0.948" and bt.score_text(None) == "")


# ═════════════════════════════════════════════════════════════════════
# 3. Source pins (run before the Qt section, which re-imports the module)
# ═════════════════════════════════════════════════════════════════════

section("Browse is HARMONIZE ONLY — tokens, never a literal colour")

# RAW source, not code_only: every colour in this file lives inside an
# f-string, and code_only strips string literals — a hex pin read
# through it would pass no matter what was there.
import re  # noqa: E402

check("no literal #rrggbb anywhere in the raw source",
      not re.search(r"#[0-9A-Fa-f]{6}\b", _SRC))
check("no literal #rgb / rgb() / rgba() colour either — the accent comes "
      "from theme.accent_rgba, which is the one place alpha is composed",
      not re.search(r"#[0-9A-Fa-f]{3}\b", _SRC)
      and not re.search(r"\brgba?\(\s*\d", _SRC))
# Read from _SRC, not _CODE: accent_rgba is called from INSIDE the QSS
# f-string, and code_only strips string literals whole — the expressions
# in an f-string included. A pin for it read through code_only would be
# vacuously false, which is the mirror image of the trap that pin exists
# for.
check("colours are read from theme.palette and theme.accent_rgba",
      "theme.palette(" in _SRC and "theme.accent_rgba(" in _SRC)


section("the gate: this strip is FUNCTION, so it is not design-gated")

check("klausbook_design is never read here — a duplicate finder is a "
      "functional injection (browse_toggles' and browse_retention's "
      "rule), and that gate defaults FALSE, so gating would ship the "
      "feature invisible to every default profile",
      "klausbook_design" not in _CODE and "design_enabled" not in _CODE)
check("background.py is not even imported — nothing here can grow a "
      "design gate by accident",
      "from . import background" not in _CODE
      and "background." not in _CODE)
check("the decision is ARGUED in the module docstring, not just made",
      "klausbook_design" in _SRC and "DEFAULTS TO FALSE" in _SRC)


section("results reach the table by a NATIVE search (K-131's warning)")

# code_only, not the raw segment: note_search's own DOCSTRING names all
# three, so a raw pin passed even after the body was replaced by a
# hand-spelled string. Strings stripped, only the real names count.
_search = code_only(_func_src("note_search"))
check("note_search builds the search with SearchNode(nids=IdList(...)) "
      "through build_search_string — Anki's own documented way",
      "SearchNode" in _search and "IdList" in _search
      and "build_search_string" in _search)
check("no private search token, and no browser_will_search resolver: "
      "K-131's klausday: token assigned search_context.card_ids and "
      "SearchContext has no such field (it is `ids`), so Anki parsed it "
      "as a field search and matched nothing",
      "browser_will_search" not in _CODE
      and "search_context" not in _CODE
      and "card_ids" not in _CODE)
# NOT `"nid:" not in _CODE`: code_only strips string literals, so that
# pin was vacuously true and could never see a hand-spelled search.
# Walk note_search's own string constants instead, docstring excluded.
_search_node = next(
    n for n in ast.walk(_TREE)
    if isinstance(n, ast.FunctionDef) and n.name == "note_search")
_search_strings = [
    n.value for n in ast.walk(_search_node)
    if isinstance(n, ast.Constant) and isinstance(n.value, str)
][1:]  # [0] is the docstring
check("the search string is never hand-spelled — the backend owns the "
      "grammar, so note_search holds no search-syntax literal at all",
      not any(":" in t for t in _search_strings), repr(_search_strings))


section("no app-modal exec, K-115 painters, no destructive action")

check("no exec() / exec_() anywhere in real code (K-114/K-125)",
      ".exec(" not in _CODE and ".exec_(" not in _CODE
      and "exec_(" not in _CODE)
check("no askUser / getText / QMessageBox.question — the banned class "
      "execs internally",
      "askUser" not in _CODE and "QMessageBox" not in _CODE
      and "getText(" not in _CODE and "getInt(" not in _CODE)

_paint = code_only(_func_src("paintEvent"))
check("the one paintEvent exists and closes its painter in a finally "
      "(K-115: a painter left open corrupts the backing store)",
      _paint and "finally" in _paint and "painter.end()" in _paint)
check("exactly one paintEvent in the file — every new one needs the "
      "same guard, so a second must be a deliberate change here",
      sum(1 for n in ast.walk(_TREE)
          if isinstance(n, ast.FunctionDef) and n.name == "paintEvent") == 1)

check("this surface can DELETE nothing — the finding says cosine's top "
      "of the list is where the untouchable pairs live, so the only "
      "action a row offers is a search",
      "remove_notes" not in _CODE and "remove_cards" not in _CODE
      and "col.remove" not in _CODE and "CollectionOp" not in _CODE)
check("nothing is pre-selected in the results tree",
      "setCurrentItem(None)" in _CODE and "clearSelection()" in _CODE)
check("no multi-select and no select-all affordance on the results",
      "SingleSelection" in _CODE and "selectAll" not in _CODE)


section("the engine is USED, never reimplemented (K-168 owns duplicates.py)")

check("the matching engine is imported, not copied",
      "from . import duplicates" in _CODE)
check("no arithmetic from the engine is duplicated here",
      "sumprod" not in _CODE and "bit_count" not in _CODE
      and "popcount" not in _CODE and "hamming" not in _CODE.lower())
check("both engine shapes are driven: the 36s collection scan and the "
      "0.24s single-note lookup",
      "scan_index(" in _CODE and "duplicates_of(" in _CODE)
check("group_pairs is NOT led with — it overreaches at these thresholds "
      "(2,067 pairs collapse to 1,405 clusters, largest an entire deck "
      "section), so pairs stay the primitive",
      "group_pairs" not in _CODE)


section("threading: QueryOp, a seq token, and no widget on the worker")

_scan = _func_src("_start_scan")
check("the long scan runs on a QueryOp parented to mw, never to the "
      "panel (a QueryOp whose parent dies takes its callback with it)",
      "QueryOp(parent=mw" in code_only(_scan))
check("a failure handler is attached, so a crashed scan reports rather "
      "than hanging the button on 'Scanning…'",
      "op.failure(" in code_only(_scan))
check("both success callbacks are seq-guarded and _alive()-guarded — "
      "pdf_drive's contract: a stale worker's result must never overwrite "
      "a newer one, and a dead window's callback must not run at all",
      _SRC.count("if seq != self._seq or not self._alive():") == 4)

# The worker calls on_progress; a widget touched from there is a crash
# waiting for a slow machine. Assert the callback's whole body.
_prog = _func_src("progress", parent="_start_scan")
_prog_body = list(ast.parse(_prog.strip()).body[0].body)
# Strip a LEADING DOCSTRING only. The first version of this pin dropped
# every ast.Expr to skip a docstring — and a bare `self.host.set_status()`
# call is an ast.Expr, so the filter deleted exactly the statement the pin
# was hunting for. Injecting a widget call survived it.
if (_prog_body and isinstance(_prog_body[0], ast.Expr)
        and isinstance(_prog_body[0].value, ast.Constant)
        and isinstance(_prog_body[0].value.value, str)):
    _prog_body = _prog_body[1:]
check("the worker's progress callback assigns ONE attribute and touches "
      "no widget — the main-thread QTimer is what reaches the label",
      len(_prog_body) == 1 and isinstance(_prog_body[0], ast.Assign)
      and ast.unparse(_prog_body[0].targets[0]) == "self._progress")
check("a main-thread QTimer polls that counter",
      "QTimer(self)" in _CODE and "self._tick.timeout.connect" in _CODE)
check("the scan is cancellable and the engine's cancel Event is threaded "
      "through",
      "threading.Event()" in _CODE and "cancel=cancel" in _CODE)


section("every Qt slot is guarded — an unguarded one ABORTS Anki")

# PyQt6 turns an unhandled Python exception inside a slot into
# qFatal() -> abort() in a bare interpreter: a SIGABRT with no log line.
# This file's TEST PROCESS caused one on 2026-09-01 (QAbstractButton::
# click -> PyQtSlotProxy::unislot -> pyqt6_err_print -> fatal). In Anki,
# whose excepthook PyQt6 honours instead, the same slot is a modal error
# dialog (K-183) — either way the rule is
# CLAUDE.md's: "defensive try/except around every Qt call".
#
# DERIVED, never hand-listed: the set is read out of this module's own
# `.connect(self.X)` calls plus every Qt override, so a handler added
# tomorrow is audited tomorrow without anyone remembering to add it.
_QT_OVERRIDES = {"eventFilter"}
_connected = set()
for _n in ast.walk(_TREE):
    if not (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "connect"):
        continue
    for _a in _n.args:
        if (isinstance(_a, ast.Attribute) and isinstance(_a.value, ast.Name)
                and _a.value.id == "self"):
            _connected.add(_a.attr)


def _is_guarded(fn: ast.FunctionDef) -> bool:
    """True when the WHOLE body (docstring aside) is one try/except."""
    body = [b for b in fn.body
            if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                    and isinstance(b.value.value, str))]
    return len(body) == 1 and isinstance(body[0], ast.Try)


_slots = []
_unguarded = []
for _n in ast.walk(_TREE):
    if not isinstance(_n, ast.FunctionDef):
        continue
    if not (_n.name in _connected or _n.name.endswith("Event")
            or _n.name in _QT_OVERRIDES):
        continue
    _slots.append(_n.name)
    if not _is_guarded(_n):
        _unguarded.append(f"{_n.name}:{_n.lineno}")

check("the sweep actually found this module's slots — an empty set would "
      "make the pin below vacuously true",
      len(_slots) >= 10, f"found {sorted(_slots)}")
check("EVERY connected slot and Qt override wraps its whole body in "
      "try/except — an unguarded one does not raise, it aborts the "
      "interpreter and takes Anki with it",
      not _unguarded, f"unguarded: {_unguarded}")
# AST, not a substring count over _CODE: code_only strips string
# literals, so a `print(f"[klausmate] ...")` pin read through it is
# vacuously false. Walk each guard's except-body instead.
_silent = []
for _n in ast.walk(_TREE):
    if not (isinstance(_n, ast.FunctionDef) and _n.name in _slots):
        continue
    if not _is_guarded(_n):
        continue
    for _h in _n.body[-1].handlers:
        if not any(isinstance(_c, ast.Call) and isinstance(_c.func, ast.Name)
                   and _c.func.id == "print" for _c in ast.walk(_h)):
            _silent.append(f"{_n.name}:{_n.lineno}")
check("every guard LOGS rather than swallowing silently — a crash that "
      "becomes nothing at all is only half fixed",
      not _silent, f"silent: {_silent}")


section("registration: ONE line in __init__.py")

_INIT = open("klausmate/__init__.py").read()
check("__init__.py calls browse_toolkit.setup_hooks() exactly once — "
      "that file is 2,600+ lines and every lane wants a piece of it",
      _INIT.count("_browse_toolkit.setup_hooks()") == 1)
check("and imports the module in exactly one place",
      _INIT.count("from . import browse_toolkit") == 1)
check("setup_hooks registers browser_will_show and the theme walk",
      "browser_will_show.append" in _CODE
      and "theme_did_change.append" in _CODE)
check("no js-message handler is registered — this is a pure Qt surface, "
      "so test_bridge_reentrancy's five-handler roster is untouched",
      "webview_did_receive_js_message" not in _CODE)
check("Anki 26.8.1 ships no browser_will_close hook, so teardown rides "
      "the window's own Close event instead of a hook that is not there",
      "browser_will_close" not in _CODE and "QEvent.Type.Close" in _CODE)


# ═════════════════════════════════════════════════════════════════════
# 2. Real offscreen Qt
# ═════════════════════════════════════════════════════════════════════

print("== K-170: real offscreen Qt — the strip as it lands in Browse ==")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore as _QtC  # noqa: E402
    from PyQt6 import QtGui as _QtG  # noqa: E402
    from PyQt6 import QtWidgets as _QtW  # noqa: E402
    _HAVE_QT = True
except Exception as _qt_e:  # noqa: BLE001
    _HAVE_QT = False
    print(f"  SKIP: PyQt6 unavailable under this python ({_qt_e}) — "
          "the source pins above still ran")

if _HAVE_QT:
    try:
        import array
        import json
        import tempfile

        # aqt.qt backed by REAL PyQt6, the K-169 section's shim.
        _qt_shim = types.ModuleType("aqt.qt")

        def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
            for _m in _mods:
                if hasattr(_m, name):
                    return getattr(_m, name)
            if name == "qconnect":
                return lambda sig, fn: sig.connect(fn)
            raise AttributeError(name)

        _qt_shim.__getattr__ = _qt_getattr
        sys.modules["aqt.qt"] = _qt_shim
        for _name in [m for m in list(sys.modules) if m.startswith("klausmate")]:
            del sys.modules[_name]
        install_package_stub()

        _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])
        bt = importlib.import_module("klausmate.browse_toolkit")
        _settings = importlib.import_module("klausmate.settings")  # rebuilt with the package above
        card_index = importlib.import_module("klausmate.card_index")
        embeddings = importlib.import_module("klausmate.embeddings")
        theme = importlib.import_module("klausmate.theme")

        # ---- a real card index on disk, so the GATE can say YES ----
        _IDX = tempfile.mkdtemp(prefix="klaus_k170_idx_")
        _CFG = {"embedding_provider": "ollama",
                "embedding_model": "nomic-embed-text"}
        _SIG = embeddings.index_signature(_CFG)
        _idx = card_index.empty_index(*_SIG)
        _idx.dims = 4
        for _n in range(6):
            _idx.nids.append(1000 + _n)
            _idx.mods.append(0)
            _idx.hashes.append(f"h{_n}")
            _idx.vectors.extend(array.array("f", [1.0, 0.0, 0.0, 0.0]))
        card_index.save(_idx, _IDX)
        bt._index_dir = lambda: _IDX  # the module's own seam
        _settings.store = _settings.DictStore(_CFG)

        # ---- Browse replica: the real tree from _aqt/forms/browser_qt6 ----
        #   splitter[0] = widget > verticalLayout_2 > (gridLayout>searchEdit)
        #                                           > tableView
        #   splitter[1] = verticalLayoutWidget > verticalLayout > fieldsArea
        # and centralwidget > verticalLayout_3 > splitter, which is the
        # layout this strip appends to.
        class _FakeCol:
            def __init__(self):
                self.built = []

            def build_search_string(self, node):
                self.built.append(node)
                return "nid:" + ",".join(str(i) for i in node.ids)

        class _FakeBrowser(_QtW.QMainWindow):
            def __init__(self):
                super().__init__()
                self.col = _FakeCol()
                self.searched = []
                central = _QtW.QWidget()
                self.setCentralWidget(central)
                body = _QtW.QVBoxLayout(central)
                body.setContentsMargins(0, 0, 0, 0)
                split = _QtW.QSplitter(_QtC.Qt.Orientation.Horizontal)
                split.setChildrenCollapsible(False)
                body.addWidget(split)

                col = _QtW.QWidget(split)
                col.setObjectName("widget")
                col_box = _QtW.QVBoxLayout(col)
                grid = _QtW.QGridLayout()
                search = _QtW.QLineEdit()
                grid.addWidget(search, 0, 1)
                grid.addWidget(_QtW.QToolButton(), 0, 0)
                col_box.addLayout(grid)
                table = _QtW.QTableWidget(12, 3)
                col_box.addWidget(table)

                ed = _QtW.QWidget(split)
                ed.setObjectName("verticalLayoutWidget")
                _QtW.QVBoxLayout(ed).addWidget(_QtW.QWidget(ed))
                split.setSizes([700, 300])

                self.form = types.SimpleNamespace(
                    splitter=split, widget=col, gridLayout=grid,
                    searchEdit=search, tableView=table,
                    verticalLayoutWidget=ed)
                self._selected = []

            def search_for(self, search, prompt=None):
                self.searched.append(search)

            def selected_notes(self):
                return list(self._selected)

        # A real anki.collection.SearchNode so the search path is
        # exercised end to end rather than pinned by source alone.
        class _IdList:
            def __init__(self, ids):
                self.ids = list(ids)

        class _SearchNode:
            IdList = _IdList

            def __init__(self, nids=None, **kw):
                self.nids = nids
                self.ids = list(nids.ids) if nids is not None else []

        _anki_col = types.ModuleType("anki.collection")
        _anki_col.SearchNode = _SearchNode
        sys.modules["anki.collection"] = _anki_col

        win = _FakeBrowser()
        win.resize(1100, 700)

        section("the strip lands INSIDE the note column, under the list only")
        col = bt.browse_note_column(win)
        check("browse_note_column walks UP from form.tableView to the direct "
              "child of form.splitter — the note column itself, never the "
              "table and never the splitter",
              col is win.form.widget)
        strip = bt.install(win)
        check("install() returns a strip and it is a real widget",
              isinstance(strip, _QtW.QWidget))
        col_box = col.layout()
        check("the strip is the LAST row of the note column's own layout — "
              "under the note list, never under the editor column "
              "(Pouya, 2026-09-05: 'only under the list, just the middle "
              "section')",
              col_box.itemAt(col_box.count() - 1).widget() is strip
              and strip.parentWidget() is col)
        body = bt.browse_body_layout(win)
        check("and the body layout that owns the splitter is untouched — "
              "still one child, the splitter, no separate note-column "
              "wrapper — so form.splitter's saved state round-trips "
              "unchanged",
              body.count() == 1)
        win.show()
        _app.processEvents()
        check("so the strip is exactly as wide as the note column's content "
              "box and narrower than the splitter",
              strip.width() == col.width() - col_box.contentsMargins().left()
              - col_box.contentsMargins().right()
              and strip.width() < win.form.splitter.width(),
              f"strip={strip.width()} column={col.width()} "
              f"splitter={win.form.splitter.width()}")
        check("install is idempotent — the Browser instance is cached all "
              "session and the hook can fire again",
              bt.install(win) is strip and col_box.count() == 3)
        check("a window with no splitter is a clean no-op, not a crash",
              bt.browse_note_column(types.SimpleNamespace(form=None)) is None
              and bt.browse_body_layout(types.SimpleNamespace(form=None)) is None
              and bt.install(types.SimpleNamespace(form=None)) is None)
        win2 = _FakeBrowser()
        win2.form.tableView = None
        strip2 = bt.install(win2)
        check("no tableView to walk from → the full-width body-layout "
              "placement is the FALLBACK, not a crash",
              isinstance(strip2, _QtW.QWidget)
              and bt.browse_body_layout(win2).count() == 2
              and strip2.parentWidget() is win2.form.splitter.parentWidget())

        section("the tool row and the panel")
        buttons = strip.findChildren(_QtW.QToolButton)
        check("one button per registry entry, carrying the registry's label",
              [b.text() for b in buttons] == [t[1] for t in bt.TOOLS])
        check("the tool panel is closed at rest",
              strip.open_tool_id() == "")
        strip.toggle_tool("duplicates")
        panel = strip._panels.get("duplicates")
        check("clicking the tool opens its panel and checks the button",
              strip.open_tool_id() == "duplicates" and panel is not None
              and buttons[0].isChecked())
        check("the results tree has both notes' TEXT as its own columns — "
              "a score and two ids cannot tell a duplicate from a "
              "contrast pair",
              panel.tree.columnCount() == 4
              and panel.tree.headerItem().text(bt.COL_A) == "Note"
              and panel.tree.headerItem().text(bt.COL_B) == "Other note")
        check("an unknown tool id opens nothing and does not raise",
              strip.open_tool("no-such-tool") is None)
        strip.toggle_tool("duplicates")
        check("clicking again closes it and unchecks the button",
              strip.open_tool_id() == "" and not buttons[0].isChecked())
        strip.toggle_tool("duplicates")

        section("the gate says YES on a good index (the positive pin)")
        check("with a real matching index on disk the tool is RUNNABLE — "
              "this is the pin that fails if the feature simply never "
              "comes up working",
              panel.refusal() == "" and panel.scan_btn.isEnabled()
              and panel.selected_btn.isEnabled())
        check("the empty state says why this tool exists at all, WHERE "
              "the results would be — not only in the corner",
              not panel.empty.isHidden()
              and panel.empty.text() == bt.EXACT_NOTE
              and panel.tree.isHidden())

        section("the disabled state, with its reason on screen")
        _EMPTY = tempfile.mkdtemp(prefix="klaus_k170_none_")
        bt._index_dir = lambda: _EMPTY
        panel._sync_enabled()
        check("no index -> the Scan button is disabled",
              not panel.scan_btn.isEnabled()
              and not panel.selected_btn.isEnabled())
        check("...and the REASON is on screen, not swallowed",
              panel.empty.text() == bt.NO_INDEX_TEXT
              and not panel.empty.isHidden())
        check("...exactly ONCE — rendered in both places the refusal read "
              "as a bug rather than as emphasis",
              strip.status.full_text() == "")
        check("...and repeated on the disabled button's tooltip",
              panel.scan_btn.toolTip() == bt.NO_INDEX_TEXT)
        check("pressing a disabled path still refuses in words",
              panel._start_scan() is None
              and strip.status.full_text() == bt.NO_INDEX_TEXT)
        panel._sync_enabled()
        # A stale signature is a different message on the same surface.
        _settings.store = _settings.DictStore({"embedding_model": "different-local-model"})
        bt._index_dir = lambda: _IDX
        panel._sync_enabled()
        check("an index from another embedding model says SO, and does "
              "not pretend the index is missing",
              panel.empty.text() == bt.STALE_INDEX_TEXT)
        _settings.store = _settings.DictStore(_CFG)
        panel._sync_enabled()
        check("fixing the model re-enables the tool",
              panel.refusal() == "" and panel.scan_btn.isEnabled())

        section("results populate, and reach the note table")
        payload = {
            "rows": bt.build_rows(
                [_P(11, 22, 0.9983), _P(33, 44, 0.9686)],
                {11: "increased plasma protein pi GC decreased FF",
                 22: "decreased plasma protein pi GC increased FF",
                 33: "HDL transfers cholesteryl esters via CETP",
                 44: "Cholesteryl ester inside mature HDL moved by the "
                     "enzyme CETP"}),
            "counts": {"duplicate": 2067}, "cancelled": False,
            "tier": "duplicate"}
        panel._absorb(payload)
        check("every row reaches the tree", panel.tree.topLevelItemCount() == 2)
        check("the genuine find is on top, not the higher-scoring "
              "contrast pair — the finding, on screen",
              panel.tree.topLevelItem(0).text(bt.COL_A).startswith("HDL"))
        check("the wording badge is drawn from lexical_overlap",
              panel.tree.topLevelItem(0).text(bt.COL_WORDING)
              == bt.WORDING_DIFFERENT
              and panel.tree.topLevelItem(1).text(bt.COL_WORDING)
              == bt.WORDING_SAME)
        check("NOTHING is pre-selected and 'Show in table' starts disabled "
              "— a default selection would aim the next action at the "
              "rows the user must not touch",
              panel.tree.currentItem() is None
              and not panel.tree.selectedItems()
              and not panel.show_btn.isEnabled())
        check("the summary reports the true total beside the shown count",
              strip.status.full_text()
              == "Showing 2 of 2,067 duplicates pairs.")
        check("switching order re-sorts without a rescan and drops nothing",
              (panel.order_combo.setCurrentIndex(1),
               panel.tree.topLevelItemCount() == 2
               and panel.tree.topLevelItem(0).text(bt.COL_A)
               .startswith("increased"))[1])
        panel.order_combo.setCurrentIndex(0)

        panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
        check("selecting a row enables 'Show in table'",
              panel.show_btn.isEnabled())
        panel.show_btn.click()
        check("the click runs a NATIVE search built by the backend from "
              "SearchNode(nids=IdList(...)) — verified against the real "
              "proto field name in anki/search_pb2.pyc",
              win.searched == ["nid:33,44"]
              and len(win.col.built) == 1
              and win.col.built[0].ids == [33, 44])
        panel.show_all_btn.click()
        check("'Show all in table' searches every listed note, in display "
              "order",
              win.searched[-1] == "nid:33,44,11,22")
        check("an empty selection produces no search at all",
              bt.show_in_table(win, []) is False
              and len(win.searched) == 2)

        section("selection lookup and the tier/rescan honesty")
        win._selected = [1000]
        check("selected_nids reads Anki's own selected_notes()",
              bt.selected_nids(win) == [1000])
        win._selected = []
        panel._on_selected_clicked()
        check("with nothing selected the tool SAYS so",
              strip.status.full_text() == bt.NO_SELECTION_TEXT)
        panel._absorb(payload)
        panel.tier_combo.setCurrentIndex(2)
        check("loosening the tier after a scan says the results are now "
              "stale rather than silently showing the old ones",
              "scan again" in strip.status.full_text())
        panel.tier_combo.setCurrentIndex(0)

        section("the strip must not decide how narrow Browse may be")
        # Measured regression: laid out directly, the open panel's seven
        # controls pushed this window's minimumSizeHint from 130px to
        # 924px — a Klaus panel setting Anki's Browse minimum. The
        # control row now rides in a no-frame QScrollArea, so the panel's
        # minimum is its viewport's.
        # BOTH windows must be shown before measuring: an unshown
        # window's layout is never activated, so minimumSizeHint comes
        # back stale and the first version of this pin could not see a
        # 924px floor at all.
        bare = _FakeBrowser()
        bare.show()
        _app.processEvents()
        bare_min = bare.minimumSizeHint().width()
        with_strip = _FakeBrowser()
        bt.install(with_strip)
        with_strip.show()
        _app.processEvents()
        strip_closed_min = with_strip.minimumSizeHint().width()
        with_strip._klausmate_toolkit.open_tool("duplicates")
        _app.processEvents()
        with_strip.layout().activate()
        with_strip.centralWidget().layout().activate()
        _app.processEvents()
        strip_open_min = with_strip.minimumSizeHint().width()
        check("opening the tool does not raise Browse's minimum width at "
              "all — a bottom strip may never dictate the window's floor",
              strip_open_min <= bare_min + 8
              and strip_closed_min <= bare_min + 8,
              f"bare={bare_min} closed={strip_closed_min} "
              f"open={strip_open_min}")
        check("the control row is in a frameless scroller with no vertical "
              "bar — that is the mechanism, not a lucky sizeHint",
              with_strip._klausmate_toolkit._panels["duplicates"]
              .control_scroll.verticalScrollBarPolicy()
              == _QtC.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        section("the results tree is sized to its content")
        panel._absorb(payload)
        two_h = panel.tree.height()
        many = dict(payload)
        many["rows"] = payload["rows"] * 12
        panel._absorb(many)
        check("more rows means a taller tree, capped at RESULTS_MAX_H — a "
              "fixed height showed six results in a half-empty box and "
              "took that space from the note table for nothing",
              panel.tree.height() > two_h
              and panel.tree.height() <= bt.RESULTS_MAX_H,
              f"two={two_h} many={panel.tree.height()}")
        panel._rows = []
        panel._render_rows()
        check("with no rows the tree is HIDDEN and the message stands in "
              "its place — an empty results box is a void the size of the "
              "note table it just took space from",
              panel.tree.isHidden() and not panel.empty.isHidden())
        panel._absorb(payload)

        section("geometry: the strip and the table")
        win.show()
        _app.processEvents()
        strip.close_tool()
        _app.processEvents()
        col.layout().activate()
        _app.processEvents()
        closed_h = strip.height()
        split_h = win.form.splitter.height()
        check("closed, the strip is a thin row and the splitter keeps "
              "essentially the whole window",
              0 < closed_h <= 48 and split_h > 500,
              f"strip={closed_h} splitter={split_h}")
        check("the note table is still visible and tall",
              win.form.tableView.isVisible()
              and win.form.tableView.height() > 400,
              f"table={win.form.tableView.height()}")
        strip.open_tool("duplicates")
        _app.processEvents()
        col.layout().activate()
        _app.processEvents()
        check("open, the strip grows but stays bounded and the table "
              "survives",
              strip.height() > closed_h
              and strip.height() <= bt.RESULTS_MAX_H + 160
              and win.form.tableView.height() > 150,
              f"strip={strip.height()} table={win.form.tableView.height()}")

        check("browse_note_column has no wrapper branch left — the note anchor "
              "is gone with the placement engine (2026-09-05)",
              "_klausmate_notes_split" not in inspect.getsource(bt.browse_note_column))

        section("narrow width")
        win.resize(620, 620)
        _app.processEvents()
        check("the tool button keeps its full width at 620px — the status "
              "label yields, the controls do not",
              buttons[0].width() >= buttons[0].sizeHint().width())
        strip.set_status("A long status line that cannot possibly fit "
                         "inside a narrow Browse window without eliding.")
        _app.processEvents()
        check("the status label ELIDES instead of forcing the strip wider",
              strip.status.text() != strip.status.full_text()
              and strip.status.text().endswith("…"))
        check("and the full text survives on its tooltip",
              strip.status.toolTip() == strip.status.full_text())
        win.resize(1100, 700)
        _app.processEvents()

        section("a raising slot is caught, not fatal")
        # The source pin above reads the guard; this one exercises it.
        # A pin that only read source would have PASSED on the code that
        # aborted, because the guard was missing at runtime and nowhere
        # else. The negative direction is not re-run here on purpose: an
        # unguarded slot does not fail, it SIGABRTs the interpreter and
        # files a macOS crash report, which is the whole defect.
        _real_show = bt.show_in_table

        def _boom(*_a, **_k):
            raise RuntimeError("stale nid / closed browser / bad search")

        bt.show_in_table = _boom
        panel._absorb(payload)
        panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
        before = len(win.searched)
        panel.show_btn.click()
        panel.show_all_btn.click()
        bt.show_in_table = _real_show
        check("a handler whose work raises is caught and logged — the "
              "process is still here and the click did nothing",
              len(win.searched) == before)
        check("the strip and its panel survive the failure intact",
              panel.tree.topLevelItemCount() == 2
              and strip.open_tool_id() == "duplicates")

        section("painting and teardown")
        _pix = strip.grab()
        check("the strip paints its hairline without raising",
              not _pix.isNull() and _pix.width() > 0)
        _dark = strip.grab()  # second grab: the painter really was closed
        check("a second paint succeeds — proof the painter was ended",
              not _dark.isNull())
        panel._running = True
        panel._tick.start()
        strip.cleanup()
        check("cleanup stops the poll timer and bumps the seq so a landing "
              "callback is discarded",
              not panel._tick.isActive() and not panel._running)

    except Exception as _e170:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        check(f"K-170 offscreen checks ran ({_e170!r})", False)

raise SystemExit(report())
