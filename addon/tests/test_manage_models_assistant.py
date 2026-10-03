"""Preferences retired-surface checks and sidebar logo rendering."""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

import importlib  # noqa: E402

manage_models = importlib.import_module("klaus_note.manage_models")

_MM_PATH = os.path.join(ADDON, "manage_models.py")
_SRC = open(_MM_PATH).read()  # RAW source — absence pins must read this, not code_only
_CODE = code_only(_SRC)  # comments AND strings stripped, for shape/wiring pins
_TREE = ast.parse(_SRC)

def _func_seg(name: str) -> str:
    """Source segment of the (unique) function/method ``name``, found by
    walking the WHOLE tree — reaches nested closures regardless of how
    deep inside manage_models_dialog they live. Same recipe as
    tests/test_pdf_map.py's _func_seg."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(_SRC, node) or ""
    return ""


# =====================================================================
section("retired local surfaces stay absent during Ollama restoration")
# D4 restores the runtime and full_setup. OCR and the old installation
# chooser remain retired; the real control behavior has offscreen coverage
# in test_local_model_settings.py.
for _gone in ("ollama_setup", "page_ocr", "OllamaError", "InstallMethod",
              "install_methods", "ollama_reachable", "run_install_method"):
    check(f"{_gone} is not referenced anywhere in manage_models.py",
          _gone not in _SRC)

for _gone_attr in ("classify_model", "embedding_candidates",
                   "_resolve_ollama_model", "_EMBED_PRESETS", "_OCR_PRESETS",
                   "_MODEL_TYPE_LABELS", "_format_pull_event"):
    check(f"manage_models.{_gone_attr} no longer exists",
          not hasattr(manage_models, _gone_attr) and _gone_attr not in _SRC)

check("retired runtime dialog handlers remain absent",
      "start_pull" not in _SRC and "delete_selected" not in _SRC
      and "start_install" not in _SRC and "start_auto_setup" not in _SRC
      and "pull_missing" not in _SRC)
check("local endpoint is configurable", 'cfg["endpoint"] = endpoint_edit.text()' in _SRC)


# =====================================================================
section("source pins: every retired credential surface is gone")
# =====================================================================
# RAW source, deliberately not _CODE (code_only strips string literals,
# which would make an absence pin on a bare dict-key string vacuous).

for dropped_literal in ('"assistant_api_key"', '"assistant_backend"',
                        '"assistant_token"', '"ocr_enabled"', '"ocr_model"',
                        '"claude_binary"', '"assistant_model"'):
    check(f"{dropped_literal} absent from manage_models.py (raw source)",
          dropped_literal not in _SRC)
check('"podcast" absent from manage_models.py (raw source) — the old '
      "Assistant subtitle promised one",
      "podcast" not in _SRC.lower())
check('"practise" / "practice" absent too — the other promise the old '
      "subtitle made",
      "practise" not in _SRC.lower() and "practice" not in _SRC.lower())

for gone_name in ("assistant_key_edit", "assistant_token_edit",
                  "assistant_backend_combo", "assistant_key_row",
                  "assistant_token_row", "_sync_assistant_rows",
                  "ocr_enabled_cb", "ocr_model_combo", "ocr_pull_btn",
                  "_fill_ocr_model_combo", "_pull_ocr_selected",
                  "claude_binary_lbl", "claude_override_btn",
                  "_pick_claude_binary", "_resolve_claude_binary",
                  "assistant_model_edit"):
    check(f"{gone_name} no longer defined/referenced", gone_name not in _SRC)


# =====================================================================
section("the sidebar k is FILLED in the text colour (real pixels)")
# =====================================================================
# The Preferences sidebar mark is a baked QPixmap, so the only honest
# proof that it renders — and renders in the text colour, not a stroke and
# not black — is to read its pixels. _logo_pixmap does all of its Qt
# work through a LAZY `from aqt.qt import ...`, so swapping that one
# module for a real-PyQt6 shim is enough; no purge, no re-import.
check("the sidebar documents sharing the toolbar SVG",
      "same SVG as the toolbar" in (manage_models._logo_pixmap.__doc__ or ""))
check("the sidebar renders the toolbar SVG in the text colour",
      "QSvgRenderer(_top_bar.logo_svg(colour).encode(" in _func_seg("_logo_pixmap")
      and "renderer.render(painter," in _func_seg("_logo_pixmap"))

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
    import types as _types

    _qt_shim = _types.ModuleType("aqt.qt")

    def _qt_getattr(name, _mods=(_QtW, _QtC, _QtG)):
        for _m in _mods:
            if hasattr(_m, name):
                return getattr(_m, name)
        if name == "qconnect":
            return lambda sig, fn: sig.connect(fn)
        raise AttributeError(name)

    _qt_shim.__getattr__ = _qt_getattr
    sys.modules["aqt.qt"] = _qt_shim
    _app = _QtW.QApplication.instance() or _QtW.QApplication(["klaus-test"])

    _theme = importlib.import_module("klaus_note.theme")
    _ink = _QtG.QColor(_theme.palette(_theme.night_mode())["text"])

    # devicePixelRatio FOLLOWS THE WIDGET: the sidebar label is the one
    # that knows what screen it is on. A baked 2.0 renders soft on a 1x
    # display and is the kind of thing nobody notices until a screenshot.
    _lbl = _QtW.QLabel()
    _px = manage_models._logo_pixmap(64, _lbl.devicePixelRatioF())
    check("the sidebar logo pixmap renders at all", _px is not None)
    check("its devicePixelRatio follows the widget, not a baked 2.0",
          _px is not None
          and _px.devicePixelRatio() == _lbl.devicePixelRatioF())
    check("the real sidebar size (24) renders too",
          manage_models._logo_pixmap(24, 1.0) is not None)

    if _px is not None:
        _img = _px.toImage().convertToFormat(
            _QtG.QImage.Format.Format_ARGB32)
        _w, _h = _img.width(), _img.height()
        _opaque = 0
        _wrong = 0
        for _y in range(_h):
            for _x in range(_w):
                _c = _img.pixelColor(_x, _y)
                if _c.alpha() > 250:
                    _opaque += 1
                    if (_c.red(), _c.green(), _c.blue()) != (
                            _ink.red(), _ink.green(), _ink.blue()):
                        _wrong += 1
        check("the mark actually covers the box — a filled k, not an "
              "empty pixmap and not a hairline outline",
              _opaque > _w * _h * 0.10, f"{_opaque}/{_w * _h} opaque")
        check("every solid pixel is the ACCENT — no baked #171717 from "
              "the asset, no second colour from a stroke",
              _wrong == 0, f"{_wrong} off-colour")
        # The k never reaches the box's corners; a mark that filled
        # them would be the brand file's blue tile, i.e. the app icon.
        _k = max(2, _w // 12)
        _corners = [(0, 0), (_w - _k, 0), (0, _h - _k), (_w - _k, _h - _k)]
        _corner_ink = sum(
            1
            for _cx, _cy in _corners
            for _y in range(_cy, _cy + _k)
            for _x in range(_cx, _cx + _k)
            if _img.pixelColor(_x, _y).alpha() != 0
        )
        check("all four corners stay empty — the k's own silhouette, no tile",
              _corner_ink == 0, f"{_corner_ink} inked corner px")


raise SystemExit(report())
