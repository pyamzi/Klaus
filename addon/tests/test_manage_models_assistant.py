"""The Preferences dialog after the API-first reversal (2026-09-15,
K-227): the Assistant page reduced to what survives the local runtime's
deletion, and the retired keys gone from config.json / config.md.

Three layers, same recipe as tests/test_pdf_map.py and
tests/test_dialog_logic.py (PyQt6 cannot be imported here — see the
klaus-test skill):

  1. the module imports for real, so a leftover import of a deleted
     module fails loudly here rather than at Anki start-up.
  2. Structural/source pins on the RAW source (never anki_stubs.code_only
     for an absence check — code_only strips string literals, so a pin
     like '"assistant_api_key" not in code_only(...)' would trivially
     pass even if the key were still a live dict-literal string
     somewhere in the file; see klaus-design-language memory note "code_only
     strips strings"). _func_seg extracts one function's exact source via
     ast.walk, same recipe as test_pdf_map.py's _func_seg — it finds a
     FunctionDef by name regardless of nesting depth, which is what lets
     it reach into manage_models_dialog's closures (save_assistant,
     clear_assistant_sessions, etc.).
  3. config.json / config.md content pins (plain file reads + json.load).

Run: python3 tests/test_manage_models_assistant.py
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import textwrap
import tokenize

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", ".claude", "skills", "klaus-test", "scripts"
    ),
)

from anki_stubs import ADDON, check, code_only, install, report, section  # noqa: E402

install()

import importlib  # noqa: E402

manage_models = importlib.import_module("klausmate.manage_models")

_MM_PATH = os.path.join(ADDON, "manage_models.py")
_SRC = open(_MM_PATH).read()  # RAW source — absence pins must read this, not code_only
_CODE = code_only(_SRC)  # comments AND strings stripped, for shape/wiring pins
_TREE = ast.parse(_SRC)

_REPO_ROOT = os.path.dirname(ADDON)
_CONFIG_JSON_PATH = os.path.join(ADDON, "config.json")
_CONFIG_MD_PATH = os.path.join(ADDON, "config.md")


def _func_seg(name: str) -> str:
    """Source segment of the (unique) function/method ``name``, found by
    walking the WHOLE tree — reaches nested closures regardless of how
    deep inside manage_models_dialog they live. Same recipe as
    tests/test_pdf_map.py's _func_seg."""
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(_SRC, node) or ""
    return ""


def _strip_comments_keep_strings(src: str) -> str:
    """Comments removed, STRINGS KEPT — for pins that need to see a
    string literal (e.g. a dict key) but must not be fooled by a
    docstring/comment merely mentioning it."""
    try:
        kept = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(kept)
    except Exception:
        return src


def _call_arg_source(func_src: str, callee_name: str, arg_index: int):
    """Unparsed source of the positional arg at `arg_index` in the first
    Call to a bare-name `callee_name` found anywhere in `func_src`.

    `func_src` is typically a _func_seg(...) result — a nested-function
    segment that keeps its ORIGINAL indentation (4 or 8 spaces, since
    it's a closure inside manage_models_dialog), so it has to be
    textwrap.dedent()-ed before ast.parse() will accept it as a
    standalone module. Returns None (not "") when the call or that
    argument isn't found, so a caller can assert "found AND looks
    right" as one condition rather than a found-but-empty string
    silently reading as a mismatch.
    """
    try:
        tree = ast.parse(textwrap.dedent(func_src))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee_name
            and len(node.args) > arg_index
        ):
            return ast.unparse(node.args[arg_index])
    return None


def _if_test_source(func_src: str, marker: str):
    """Unparsed source of the `test` of the first `If` node in func_src
    whose unparsed test contains `marker` — a way to find ONE specific
    if-statement by a phrase unique to its condition, since ast.walk
    gives no other handle on "the if I mean" without a line number that
    would go stale on the next reformat. Same dedent/None contract as
    _call_arg_source."""
    try:
        tree = ast.parse(textwrap.dedent(func_src))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            src = ast.unparse(node.test)
            if marker in src:
                return src
    return None


# =====================================================================
section("the local-runtime era is gone from this module (spec D1)")
# =====================================================================
# One provider, no local runtime: the Ollama client/runtime/setup modules
# are deleted, so a module-top import of any of them would stop the whole
# add-on loading — and the pull/classify/preset machinery they fed goes
# with them. RAW source: code_only() strips string literals, which is
# exactly what an absence pin must still be able to see.
for _gone in ("ollama_client", "ollama_runtime", "ollama_setup", "page_ocr",
              "OllamaError", "InstallMethod", "install_methods",
              "ollama_reachable", "run_install_method", "full_setup"):
    check(f"{_gone} is not referenced anywhere in manage_models.py",
          _gone not in _SRC)

for _gone_attr in ("classify_model", "embedding_candidates",
                   "_resolve_ollama_model", "_EMBED_PRESETS", "_OCR_PRESETS",
                   "_MODEL_TYPE_LABELS", "_format_pull_event"):
    check(f"manage_models.{_gone_attr} no longer exists",
          not hasattr(manage_models, _gone_attr) and _gone_attr not in _SRC)

check("no pull / delete / install machinery survives — there is nothing "
      "local left to manage",
      "start_pull" not in _SRC and "delete_selected" not in _SRC
      and "start_install" not in _SRC and "start_auto_setup" not in _SRC
      and "pull_missing" not in _SRC)
check('the "endpoint" config key is gone with the local server',
      "endpoint_url" not in _SRC and '"endpoint"' not in _SRC)


# =====================================================================
section("config.json: the Assistant's own keys, the OCR/binary keys gone")
# =====================================================================
with open(_CONFIG_JSON_PATH) as f:
    _cfg_json_text = f.read()
_cfg = json.loads(_cfg_json_text)

_ASSISTANT_DEFAULTS = {
    "assistant_reopen": False,
    "assistant_dock_width": 420,
    # assistant_dock_open (final review I7): assistant_reopen was
    # written by Preferences and read by nobody. The dock now records
    # whether it was open here, and honours the pair on profile open.
    "assistant_dock_open": False,
}
for key, want in _ASSISTANT_DEFAULTS.items():
    check(f"config.json[{key!r}] == {want!r}",
          key in _cfg and _cfg[key] == want,
          f"got {_cfg.get(key, '<missing>')!r}")

for dropped in ("assistant_api_key", "assistant_backend", "assistant_token",
                "ocr_enabled", "ocr_model", "claude_binary",
                "assistant_model"):
    check(f"config.json no longer has {dropped!r}", dropped not in _cfg)

check("config.json is still valid, single, well-formed JSON (a hand "
      "edit that drops a trailing comma wrong would fail this)",
      isinstance(_cfg, dict))


# =====================================================================
section("source pins: every retired credential surface is gone")
# =====================================================================
# RAW source, deliberately not _CODE (code_only strips string literals,
# which would make an absence pin on a bare dict-key string vacuous).
_top_of_file = _CODE.split("def manage_models_dialog", 1)[0]

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
section("save_assistant: the Anthropic key and the two model names")
# =====================================================================
_save_assistant_src = _func_seg("save_assistant")
check("save_assistant was found in the source", bool(_save_assistant_src))
_save_body = _strip_comments_keep_strings(_save_assistant_src)
for key in ("api_key_anthropic", "reasoning_model", "transcription_model",
            "assistant_reopen", "assistant_dock_width", "assistant_dock_open"):
    check(f'"{key}" present in save_assistant\'s body',
          f'"{key}"' in _save_body)
# Parked T8 finding, fixed then and still pinned: meta.json is
# hand-editable, and a non-numeric stored width made int() raise INSIDE
# save_all — breaking the Save button for every other setting on the
# page, not just this one.
check("the round-tripped width int() is guarded, falling back to 420",
      "except (TypeError, ValueError)" in _save_assistant_src
      and "= 420" in _save_assistant_src)
check("save_assistant still writes through write_config, like every "
      "other save_* in this dialog",
      "write_config(cfg)" in code_only(_save_assistant_src))
check("no leftover write of any retired key inside save_assistant",
      not any(
          f'"{k}"' in _save_body
          for k in ("assistant_api_key", "assistant_backend",
                    "assistant_token", "ocr_enabled", "ocr_model",
                    "claude_binary", "assistant_model")
      ))


# =====================================================================
section("load_assistant: reads those keys back")
# =====================================================================
_load_assistant_src = _func_seg("load_assistant")
check("load_assistant was found in the source", bool(_load_assistant_src))
_load_body = _strip_comments_keep_strings(_load_assistant_src)
for key in ("api_key_anthropic", "reasoning_model", "transcription_model",
            "assistant_reopen"):
    check(f'load_assistant reads "{key}" back from config',
          f'"{key}"' in _load_body)


# =====================================================================
section("the Assistant page: two rows, no OCR row, no binary row")
# =====================================================================
check('the _page("Assistant", "Assistant", ...) call site still exists '
      "(same nav_label/title shape test_dialog_logic.py pins)",
      '"Assistant",\n        "Assistant",' in _SRC)
_assistant_page_call = _SRC.split(
    '"Assistant",\n        "Assistant",', 1
)[1].split(")", 1)[0]
check("the subtitle no longer promises practice or a podcast",
      "practise" not in _assistant_page_call.lower()
      and "podcast" not in _assistant_page_call.lower())
check("the subtitle no longer sends the user to install Claude Code — "
      "the assistant runs on the Anthropic key on the keys page",
      "Claude Code" not in _assistant_page_call
      and "Anthropic" in _assistant_page_call)

for widget_name in ("assistant_reopen_cb", "clear_sessions_btn"):
    check(f"{widget_name} constructed in the source", widget_name in _SRC)

check("every surviving control marks dirty, or Save would silently skip "
      "it (exactly how pdf_renderer shipped broken, per this file's own "
      "mark_dirty docstring)",
      "assistant_reopen_cb.toggled.connect" in _SRC
      and "anthropic_key_edit.textEdited.connect" in _SRC
      and "reasoning_model_edit.textEdited.connect" in _SRC
      and "transcription_model_edit.textEdited.connect" in _SRC)

check("Clear Sessions is a SecondaryButton", (
    'clear_sessions_btn.setObjectName("SecondaryButton")' in _SRC
))


# =====================================================================
section("Clear Sessions: window-modal confirm, never QMessageBox.question")
# =====================================================================
_clear_fn_candidates = [
    n for n in ("clear_assistant_sessions", "_clear_sessions_confirmed",
                "_on_clear_sessions_answered")
    if _func_seg(n)
]
check("a Clear Sessions handler function exists", bool(_clear_fn_candidates))
_clear_all_src = "\n".join(_func_seg(n) for n in (
    "clear_assistant_sessions", "_clear_sessions_confirmed",
))
_clear_all_code = code_only(_clear_all_src)
check("built by hand (QMessageBox(...) instance), not the blocking "
      "static QMessageBox.question(...)",
      "QMessageBox(" in _clear_all_code and "QMessageBox.question(" not in _clear_all_code)
check("raised window-modal: open() + a finished callback, K-125's "
      "pattern (never .exec())",
      "msg.open()" in _clear_all_code
      and "msg.finished.connect(" in _clear_all_code
      and ".exec()" not in _clear_all_code)
check("assistant_sessions.clear_all is imported lazily, never at "
      "module top",
      "assistant_sessions" not in _top_of_file)
check("only on a confirmed Yes does it call assistant_sessions.clear_all",
      "assistant_sessions.clear_all(" in _clear_all_code)
check("the import is guarded — a missing module degrades to a log line "
      "instead of crashing the whole dialog",
      "except" in _clear_all_src and "assistant_sessions" in _clear_all_src)


# =====================================================================
section("config.md: the Assistant keys, the retired ones gone")
# =====================================================================
with open(_CONFIG_MD_PATH) as f:
    _md = f.read()
check("an Assistant heading exists", "## Assistant" in _md)
for key in ("assistant_reopen", "assistant_dock_width", "assistant_dock_open"):
    check(f"config.md documents {key}", f"**{key}**" in _md)
for dropped in ("assistant_backend", "assistant_api_key", "assistant_token",
                "ocr_enabled", "ocr_model", "claude_binary",
                "assistant_model"):
    check(f"config.md no longer documents {dropped}",
          f"**{dropped}**" not in _md)
check("config.md names the two API keys the add-on actually uses",
      "**api_key_openai**" in _md and "**api_key_anthropic**" in _md)


# =====================================================================
section("AGENTS.md's privacy paragraph names the assistant (I9)")
# =====================================================================
# "the only network calls Klaus makes are for embeddings … No telemetry"
# became false the moment the assistant shipped: every turn sends the
# page's text, its image, the selection and the user's prompt to
# Anthropic. That paragraph is the first thing a privacy-conscious user
# reads. (The provider list in it is Task 8's to bring to the API-first
# world — pinned here only for what must never stop being true.)
_AGENTS_MD = os.path.join(os.path.dirname(_CONFIG_MD_PATH), "..", "AGENTS.md")
_AGENTS_MD = os.path.normpath(_AGENTS_MD)
with open(_AGENTS_MD) as f:
    _agents = f.read()
_privacy = _agents.split("---", 1)[0]
check("the privacy section no longer claims embeddings are the ONLY network calls",
      "the only network calls Klaus makes are for embeddings" not in _privacy)
check("it names Anthropic as a destination, and says it is the assistant's",
      "Anthropic" in _privacy and "assistant" in _privacy.lower())
check("it says what a turn actually carries (the page and the selection)",
      "select" in _privacy.lower() and "image" in _privacy.lower())
check("no telemetry is still stated", "telemetry" in _privacy.lower())


raise SystemExit(report())
