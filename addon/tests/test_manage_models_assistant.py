"""Tests for Task 8 of the Klaus-assistant-on-Claude-Code plan: model-type
classification, the OCR presets, the rewritten Assistant page, and the six
new config keys — all in klausmate/manage_models.py plus config.json and
config.md.

Three layers, same recipe as tests/test_pdf_map.py and
tests/test_dialog_logic.py (PyQt6 cannot be imported here — see the
klaus-test skill):

  1. classify_model is pure and aqt-free — imported for real and called
     directly.
  2. Structural/source pins on the RAW source (never anki_stubs.code_only
     for an absence check — code_only strips string literals, so a pin
     like '"assistant_api_key" not in code_only(...)' would trivially
     pass even if the key were still a live dict-literal string
     somewhere in the file; see klaus-design-language memory note "code_only
     strips strings"). _func_seg extracts one function's exact source via
     ast.walk, same recipe as test_pdf_map.py's _func_seg — it finds a
     FunctionDef by name regardless of nesting depth, which is what lets
     it reach into manage_models_dialog's closures (save_assistant,
     refresh, rebuild_library_list, clear_assistant_sessions, etc.).
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
section("classify_model (pure)")
# =====================================================================
check('capabilities ["completion", "vision"] -> "ocr"',
      manage_models.classify_model({"capabilities": ["completion", "vision"]})
      == "ocr")
check('capabilities ["embedding"] -> "embedding"',
      manage_models.classify_model({"capabilities": ["embedding"]}) == "embedding")
check("no capabilities key at all -> \"chat\"",
      manage_models.classify_model({}) == "chat")
check('a junk (non-list) capabilities value -> "chat", not a lucky '
      "substring match (\"embedding\" is not a substring of \"junk\", but "
      "the point is the TYPE check, not the coincidence)",
      manage_models.classify_model({"capabilities": "junk"}) == "chat")
check("embedding wins over vision when a model absurdly claims both "
      "(spec order: embedding checked first)",
      manage_models.classify_model(
          {"capabilities": ["embedding", "vision"]}
      ) == "embedding")
check("None input never raises — refresh() calls this once per "
      "installed model and one odd response must not crash Preferences",
      manage_models.classify_model(None) == "chat")
check("missing capabilities key (only other junk present) -> \"chat\"",
      manage_models.classify_model({"other": 1}) == "chat")


# =====================================================================
section("_OCR_PRESETS")
# =====================================================================
check("_OCR_PRESETS exists", hasattr(manage_models, "_OCR_PRESETS"))
_OCR = manage_models._OCR_PRESETS
check("index 0 is glm-ocr", _OCR[0][0] == "glm-ocr")
_ocr_ids = [row[0] for row in _OCR]
check("deepseek-ocr present", "deepseek-ocr" in _ocr_ids)
check("exactly the two presets from the brief, no more, no fewer",
      _ocr_ids == ["glm-ocr", "deepseek-ocr"])
check("every preset is a real (id, description) pair",
      all(isinstance(row, tuple) and len(row) == 2 for row in _OCR))


# =====================================================================
section("embedding_candidates (pure) — K-194 review Critical #1 fix")
# =====================================================================
# The review's reproduction: manage_models._resolve_ollama_model('',
# ['glm-ocr'], '', 'nomic-embed-text') -> 'glm-ocr', because that
# resolver has no type awareness and was fed the UNFILTERED inventory.
# embedding_candidates is the fix's pure core: build the filtered list
# ONCE and hand it to both the resolver call and the write guard in
# sync_embed_widgets, instead of the raw unfiltered ui_state["models"].
check("embedding_candidates exists", hasattr(manage_models, "embedding_candidates"))
check('a lone OCR-typed install yields no candidates — this is the '
      "exact reproduction shape from the review",
      manage_models.embedding_candidates(["glm-ocr"], {"glm-ocr": "ocr"}) == [])
check("mixed install: only the embedding-typed name survives",
      manage_models.embedding_candidates(
          ["glm-ocr", "nomic-embed-text"],
          {"glm-ocr": "ocr", "nomic-embed-text": "embedding"},
      ) == ["nomic-embed-text"])
check("a chat-typed name is excluded too, not just ocr",
      manage_models.embedding_candidates(["llama3"], {"llama3": "chat"}) == [])
check("a name absent from model_types (unclassified, e.g. "
      "mid-classification) is excluded, not assumed embedding",
      manage_models.embedding_candidates(["mystery-model"], {}) == [])
check("empty inputs -> empty output, never raises",
      manage_models.embedding_candidates([], {}) == [])
check("order is preserved from the input models list, not sorted or "
      "reordered",
      manage_models.embedding_candidates(
          ["b", "a"], {"a": "embedding", "b": "embedding"}
      ) == ["b", "a"])
check("reproduces the review's own repro end to end: feeding the "
      "FILTERED list (not the raw one) into _resolve_ollama_model no "
      "longer resolves an OCR model as the embedding choice",
      manage_models._resolve_ollama_model(
          "",
          manage_models.embedding_candidates(["glm-ocr"], {"glm-ocr": "ocr"}),
          "",
          "nomic-embed-text",
      ) == "nomic-embed-text")


# =====================================================================
section("config.json: six new keys, spec defaults, three keys dropped")
# =====================================================================
with open(_CONFIG_JSON_PATH) as f:
    _cfg_json_text = f.read()
_cfg = json.loads(_cfg_json_text)

_NEW_DEFAULTS = {
    "ocr_enabled": True,
    "ocr_model": "glm-ocr",
    "claude_binary": "",
    "assistant_model": "",
    "assistant_reopen": False,
    "assistant_dock_width": 420,
    # assistant_dock_open (final review I7): assistant_reopen was
    # written by Preferences and read by nobody. The dock now records
    # whether it was open here, and honours the pair on profile open.
    "assistant_dock_open": False,
}
for key, want in _NEW_DEFAULTS.items():
    check(f"config.json[{key!r}] == {want!r}",
          key in _cfg and _cfg[key] == want,
          f"got {_cfg.get(key, '<missing>')!r}")

for dropped in ("assistant_api_key", "assistant_backend", "assistant_token"):
    check(f"config.json no longer has {dropped!r}", dropped not in _cfg)

check("config.json is still valid, single, well-formed JSON (a hand "
      "edit that drops a trailing comma wrong would fail this)",
      isinstance(_cfg, dict))


# =====================================================================
section("source pins: old assistant credential surface fully gone")
# =====================================================================
# RAW source, deliberately not _CODE (code_only strips string literals,
# which would make an absence pin on a bare dict-key string vacuous).
for dropped_literal in ('"assistant_api_key"', '"assistant_backend"',
                        '"assistant_token"'):
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
                  "assistant_token_row", "_sync_assistant_rows"):
    check(f"{gone_name} no longer defined/referenced", gone_name not in _SRC)


# =====================================================================
section("save_assistant: writes exactly the six new keys")
# =====================================================================
_save_assistant_src = _func_seg("save_assistant")
check("save_assistant was found in the source", bool(_save_assistant_src))
_save_body = _strip_comments_keep_strings(_save_assistant_src)
for key in ("ocr_enabled", "ocr_model", "claude_binary", "assistant_model",
            "assistant_reopen", "assistant_dock_width", "assistant_dock_open"):
    check(f'"{key}" present in save_assistant\'s body',
          f'"{key}"' in _save_body)
# Parked T8 finding, fix now: meta.json is hand-editable, and a
# non-numeric stored width made int() raise INSIDE save_all — breaking
# the Save button for every other setting on the page, not just this one.
check("the round-tripped width int() is guarded, falling back to 420",
      "except (TypeError, ValueError)" in _save_assistant_src
      and "= 420" in _save_assistant_src)
check("save_assistant still writes through write_config, like every "
      "other save_* in this dialog",
      "write_config(cfg)" in code_only(_save_assistant_src))
check("no leftover write of the three dropped keys inside save_assistant",
      not any(
          f'"{k}"' in _save_body
          for k in ("assistant_api_key", "assistant_backend", "assistant_token")
      ))


# =====================================================================
section("load_assistant: reads the six new keys back")
# =====================================================================
_load_assistant_src = _func_seg("load_assistant")
check("load_assistant was found in the source", bool(_load_assistant_src))
_load_body = _strip_comments_keep_strings(_load_assistant_src)
for key in ("ocr_enabled", "claude_binary", "assistant_model",
            "assistant_reopen"):
    check(f'load_assistant reads "{key}" back from config',
          f'"{key}"' in _load_body)


# =====================================================================
section("the Assistant page: subtitle rewritten, six rows present")
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
check("the subtitle names Claude Code as the engine and the login step",
      "Claude Code" in _assistant_page_call and "claude" in _assistant_page_call)

for widget_name in ("ocr_enabled_cb", "ocr_model_combo", "ocr_pull_btn",
                    "claude_binary_lbl", "claude_override_btn",
                    "assistant_model_edit", "assistant_reopen_cb",
                    "clear_sessions_btn"):
    check(f"{widget_name} constructed in the source", widget_name in _SRC)

check("OCR model row: a Pull button wired to the existing start_pull() "
      "path, not a second pull implementation",
      "def _pull_ocr_selected" in _CODE and "start_pull()" in _CODE
      and _CODE.count("def start_pull") == 1)

check("every new control marks dirty, or Save would silently skip it "
      "(exactly how pdf_renderer shipped broken, per this file's own "
      "mark_dirty docstring)",
      "ocr_enabled_cb.toggled.connect" in _SRC
      and "ocr_model_combo.currentIndexChanged.connect" in _SRC
      and "assistant_model_edit.textEdited.connect" in _SRC
      and "assistant_reopen_cb.toggled.connect" in _SRC)

check("Clear Sessions is a SecondaryButton", (
    'clear_sessions_btn.setObjectName("SecondaryButton")' in _SRC
))


# =====================================================================
section("Claude binary: read-only auto-detect + window-modal Override")
# =====================================================================
check("agent_host is imported lazily (function-local), never at module "
      "top — Task 2 may not exist yet in this checkout",
      "from . import agent_host" not in _CODE.split("def manage_models_dialog", 1)[0]
      if "def manage_models_dialog" in _CODE else True)
_top_of_file = _CODE.split("def manage_models_dialog", 1)[0]
check("no module-level 'import klausmate.agent_host' or bare "
      "'from . import agent_host' before manage_models_dialog begins",
      "agent_host" not in _top_of_file)

_pick_claude_src = _func_seg("_pick_claude_binary")
check("_pick_claude_binary was found in the source", bool(_pick_claude_src))
_pick_claude_code = code_only(_pick_claude_src)
check("the Override... flow imports QFileDialog lazily inside the "
      "function, same convention as pick_bg_image/change_library_folder",
      "from aqt.qt import QFileDialog" in _pick_claude_code)
check("Override opens an INSTANCE window-modal (open()), never the "
      "static getOpenFileName()/getExistingDirectory() convenience "
      "(those exec() internally)",
      "QFileDialog(" in _pick_claude_code
      and ".open()" in _pick_claude_code
      and "QFileDialog.get" not in _pick_claude_code)
check("the picked path is consumed via a signal (fileSelected), not a "
      "blocking return value",
      "fileSelected.connect" in _pick_claude_code)

check("find_claude is imported lazily inside a function, never at "
      "module top (Task 2's agent_host.py may not exist yet)",
      "find_claude" not in _top_of_file)
_claude_label_refresh_candidates = [
    _func_seg(n) for n in ("_refresh_claude_binary_label", "_resolve_claude_binary")
]
_claude_label_refresh_src = "\n".join(s for s in _claude_label_refresh_candidates if s)
check("some helper resolves the claude binary via agent_host.find_claude, "
      "guarded so an ImportError degrades instead of crashing Preferences",
      "agent_host" in _claude_label_refresh_src
      and "find_claude" in _claude_label_refresh_src
      and "except" in _claude_label_refresh_src)
check('"not found" is the degrade text when nothing resolves',
      "not found" in _SRC)


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
      "module top (Task 7's assistant_sessions.py may not exist yet)",
      "assistant_sessions" not in _top_of_file)
check("only on a confirmed Yes does it call assistant_sessions.clear_all",
      "assistant_sessions.clear_all(" in _clear_all_code)
check("the import is guarded — a missing Task-7 module degrades to a "
      "log line instead of crashing the whole dialog",
      "except" in _clear_all_src and "assistant_sessions" in _clear_all_src)


# =====================================================================
section("Local model library: a Type column from classify_model over "
        "/api/show, classification off the GUI thread (K-194 review "
        "Important #1)")
# =====================================================================
_refresh_src = _func_seg("refresh")
check("refresh() was found in the source", bool(_refresh_src))
_refresh_lit = _strip_comments_keep_strings(_refresh_src)
check("refresh() delegates classification to _classify_models_async "
      "instead of running the /api/show loop inline — the N sequential "
      "network calls (each up to OllamaClient's 30s timeout) must never "
      "block the GUI thread",
      "_classify_models_async(models)" in _refresh_src
      and '_post("/api/show"' not in _refresh_lit
      and "classify_model(" not in code_only(_refresh_src))

_classify_src = _func_seg("_classify_models_async")
check("_classify_models_async was found in the source", bool(_classify_src))
_classify_code = code_only(_classify_src)
# Comments-stripped-but-STRINGS-KEPT here, not code_only: "/api/show" and
# "model_types"/"classify_gen" are string literals (an endpoint path, a
# dict key) and code_only would strip them clean out of the text, making
# a pin that looks for their quoted form vacuously fail — the exact
# code_only trap this file's own module docstring warns about.
_classify_lit = _strip_comments_keep_strings(_classify_src)
check("it calls classify_model once per installed model via "
      "client()._post(\"/api/show\", ...)",
      "classify_model(" in _classify_code and '_post("/api/show"' in _classify_lit)
check("a failed /api/show tolerates and does not abort the pass — the "
      "brief's \"tolerate failure -> chat\" contract",
      "except" in _classify_src)
check("the classification is cached on ui_state for the dialog's life, "
      "not re-fetched by every reader",
      'ui_state["model_types"]' in _classify_lit
      or "ui_state['model_types']" in _classify_lit)
check("the network work is handed to a QueryOp — the same off-main-"
      "thread pattern start_pull/delete_selected/start_install already "
      "use in this file — not called directly from refresh()",
      "QueryOp(" in _classify_code
      and ".without_collection()" in _classify_code
      and ".run_in_background()" in _classify_code)
check("results land back on the main thread only via QueryOp's own "
      "success callback (on_done), never written from inside the "
      "worker function passed as op=",
      "success=on_done" in _classify_code)
check("a stale/superseded pass is dropped via a generation counter, so "
      "a slow classification from an earlier refresh() can't clobber a "
      "newer one's result",
      'ui_state["classify_gen"]' in _classify_lit
      or "ui_state['classify_gen']" in _classify_lit)

_rebuild_src = _func_seg("rebuild_library_list")
check("rebuild_library_list was found in the source", bool(_rebuild_src))
check("the Local Models list renders each model's type (a Type column) "
      "using the cached classification, not re-deriving it",
      "model_types" in _rebuild_src)


# =====================================================================
section("the embedding combo now only offers embedding-typed models, "
        "AND the auto-heal/write-guard use the same filtered list "
        "(K-194 review Critical #1)")
# =====================================================================
_sync_embed_src = _func_seg("sync_embed_widgets")
check("sync_embed_widgets was found in the source", bool(_sync_embed_src))
check("it builds ONE embedding_candidates(...) list rather than "
      "filtering ui_state[\"models\"] inline in more than one place",
      "embedding_candidates(" in _sync_embed_src)

# The review's exact bug: the DISPLAY loop filtered by type, but the
# resolver call and the write guard three lines below it still read the
# raw, unfiltered ui_state["models"] — so a lone OCR-typed install got
# silently resolved (and then WRITTEN to config.json) as embedding_model.
# These two checks inspect the actual AST of the two call/condition
# sites, not just "the string 'model_types' appears somewhere" (which
# the pre-fix code would also have satisfied, since the display loop
# alone contained it) — see _call_arg_source / _if_test_source above.
_resolver_models_arg = _call_arg_source(
    _sync_embed_src, "_resolve_ollama_model", 1
)
check("the auto-heal resolver call receives the FILTERED "
      "embedding_models list as its models argument, not the raw "
      "unfiltered inventory",
      _resolver_models_arg == "embedding_models",
      f"got {_resolver_models_arg!r}")

_write_guard_test = _if_test_source(_sync_embed_src, "resolved != configured_model")
check("the write-to-disk guard also checks the FILTERED list — the "
      "second of the two spots the unfiltered list used to reach "
      "(marker distinguishes this if from the unrelated early "
      "provider_override/dirty guard at the top of the function, which "
      "also contains the phrase \"provider_override is None\")",
      _write_guard_test is not None
      and "embedding_models" in _write_guard_test
      and "ui_state['models']" not in _write_guard_test
      and 'ui_state["models"]' not in _write_guard_test,
      f"got {_write_guard_test!r}")


# =====================================================================
section("config.md: documents the six keys under an Assistant heading, "
        "the old assistant_backend/api_key/token prose is gone")
# =====================================================================
with open(_CONFIG_MD_PATH) as f:
    _md = f.read()
check("an Assistant heading exists", "## Assistant" in _md)
for key in ("ocr_enabled", "ocr_model", "claude_binary", "assistant_model",
            "assistant_reopen", "assistant_dock_width", "assistant_dock_open"):
    check(f"config.md documents {key}", f"**{key}**" in _md)
for dropped in ("assistant_backend", "assistant_api_key", "assistant_token"):
    check(f"config.md no longer documents {dropped}",
          f"**{dropped}**" not in _md)


# =====================================================================
section("AGENTS.md's privacy paragraph names the assistant (I9)")
# =====================================================================
# "the only network calls Klaus makes are for embeddings … No telemetry"
# became false the moment the assistant shipped: every turn sends the
# page's text, its image, the selection and the user's prompt to
# Anthropic through the user's own claude login. That paragraph is the
# first thing a privacy-conscious user reads.
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
check("it still names the embedding providers",
      "Voyage" in _privacy and "ollama" in _privacy.lower())
check("it says OCR is local",
      "OCR" in _privacy and "local" in _privacy.lower() and "Ollama" in _privacy)
check("no telemetry is still stated", "telemetry" in _privacy.lower())


# =====================================================================
section("the OCR copy describes what the code actually does (M5)")
# =====================================================================
# page_ocr OCRs the viewed page AND its two neighbours regardless of any
# text layer, and the text layer still goes when OCR is off — so both
# "when the PDF has no extractable text layer" and "off means no page
# context at all" were false. Raw source/markdown, never code_only: these
# are string literals.
_ocr_row = _func_seg("manage_models_dialog") or _SRC
check("the Preferences OCR row no longer claims OCR is text-layer-gated",
      "no extractable text layer" not in _SRC)
check("config.md no longer claims that either",
      "no extractable text layer" not in _md)
check("config.md no longer claims OCR-off means no page context at all",
      "no page context at all" not in _md)
check("config.md says what OCR-off actually leaves: the PDF's own text layer",
      "text layer" in _md)
# page_ocr.PREFETCH is (1, -1): one neighbour ahead, one BEHIND. The
# round-1 copy said "its two neighbours, ahead of you" (re-review
# addendum). Whitespace-normalised, because markdown rewraps.
_md_flat = " ".join(_md.split())
check("config.md does not claim both OCR neighbours are ahead of you",
      "two neighbours, ahead of you" not in _md_flat)
check("...it names the next page AND the previous one",
      "the next page and the previous one" in _md_flat)


# =====================================================================
section("the claude binary lookup is cached for the profile (M12)")
# =====================================================================
# Step 3 of find_claude spawns the user's LOGIN SHELL with a 3 s timeout,
# and the resolver runs on the main thread every time Preferences opens
# or the label refreshes. Spec 4.1 always said "cached in memory for the
# profile session"; nothing implemented it.
check("the resolver goes through find_claude_cached, not the uncached find_claude",
      "find_claude_cached" in _claude_label_refresh_src)
check("picking an Override… clears that cache so the new path resolves for real",
      "clear_binary_cache" in (_func_seg("_pick_claude_binary") or ""))


raise SystemExit(report())
