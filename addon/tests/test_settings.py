"""The settings seam: one aqt-free module owns the stored config, its
migrations, the merge write and the user-files path (spec
docs/superpowers/specs/2026-09-30-settings-seam-design.md).

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_settings.py
"""
from __future__ import annotations

import importlib
import os
import sys
import threading

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section  # noqa: E402

install()
st = importlib.import_module("klaus_note.settings")

section("DictStore")
d = st.DictStore({"a": 1, "nested": {"x": [1]}})
got = d.read()
got["nested"]["x"].append(2)
check("read hands out copies", d.read() == {"a": 1, "nested": {"x": [1]}})
d.write({"b": 2})
check("write replaces", d.read() == {"b": 2})

section("read and patch on the main thread")
hops: list = []
st.store = st.DictStore({"a": 1, "gone": True})
st.run_on_main = lambda fn: hops.append(fn)
st.current_profile = lambda: "p1"
one = st.read()
one["a"] = 99
check("read returns a fresh dict each call", st.read()["a"] == 1)
st.patch({"b": 2}, remove=["gone", "missing"])
check("patch merges, removes, and applies INLINE on the main thread (no hop)",
      st.read() == {"a": 1, "b": 2} and hops == [])

section("patch from a background thread")
done = threading.Event()
threading.Thread(target=lambda: (st.patch({"c": 3}), done.set())).start()
done.wait(2)
check("a background patch is handed to run_on_main, not applied yet", len(hops) == 1 and "c" not in st.read())
hops.pop()()
check("…and lands when the hop runs", st.read().get("c") == 3)
done.clear()
threading.Thread(target=lambda: (st.patch({"d": 4}), done.set())).start()
done.wait(2)
st.current_profile = lambda: "p2"  # the profile switched before the hop ran
hops.pop()()
check("patch from a background thread after a profile switch is dropped", "d" not in st.read())
st.run_on_main = None
st.current_profile = None
done.clear()
threading.Thread(target=lambda: (st.patch({"e": 5}), done.set())).start()
done.wait(2)
check("with no run_on_main installed (tests, early boot) a background patch applies inline", st.read().get("e") == 5)

section("user files")
check("user_files() is the add-on's user_files directory by default",
      st.user_files().endswith(os.sep + "user_files") and st.user_files() == st.user_files_dir)
st.user_files_dir = "/tmp/klaus-uf-test"
check("…and follows an assignment", st.user_files() == "/tmp/klaus-uf-test")

section("migrations")
st.store = st.DictStore({"k": 1})
st._migrations.clear()
order: list = []


def m_noop(cfg):
    order.append("noop")
    return cfg


def m_bump(cfg):
    order.append("bump")
    if cfg.get("k") == 1:
        cfg = dict(cfg)
        cfg["k"] = 2
    return cfg


st.register_migration(m_noop)
st.register_migration(m_bump)
check("migrate runs in order and writes back on change", st.migrate() is True and order == ["noop", "bump"] and st.read()["k"] == 2)
order.clear()
check("a second migrate changes nothing and writes nothing", st.migrate() is False and order == ["noop", "bump"])
st._migrations.clear()

section("the legacy scrub (moved from the bootstrap)")
check("LEGACY_KEYS_DROPPED still names the retired keys",
      {"single_window_mode", "workspace_enabled", "claude_api_key", "pdf_index_max_chunks"} <= set(st.LEGACY_KEYS_DROPPED))
cfg = st._scrub_legacy({"claude_api_key": "x", "keep": 1})
check("scrub drops retired keys and applies the embeddings default once",
      "claude_api_key" not in cfg and cfg["keep"] == 1 and cfg["embedding_provider"] == "ollama"
      and cfg["embedding_model"] == "nomic-embed-text" and cfg["_local_embeddings_migrated"] is True)
again = st._scrub_legacy(dict(cfg, embedding_model="custom"))
check("…and never re-applies the default over a later choice", again["embedding_model"] == "custom")
check("the scrub is registered by default", st._scrub_legacy in st.DEFAULT_MIGRATIONS)

section("the package root no longer owns config or the user-files path")
_init = open("klaus_note/__init__.py").read()
check("no accessor, no USER_FILES constant, no legacy list, no _migrate_config on the package root",
      not any(t in _init for t in ("def get_config", "def write_config", "def patch_config",
                                    "\nUSER_FILES =", "_LEGACY_KEYS_DROPPED", "def _migrate_config")))
check("the bootstrap installs the Anki store, the main-thread hop and the profile token, and runs migrations on profile open",
      "settings.store = settings.AnkiStore(" in _init and "settings.run_on_main = " in _init
      and "settings.current_profile = " in _init and "profile_did_open.append(settings.migrate)" in _init)

section("no module reaches back for config or the user-files path")
import glob  # noqa: E402

offenders = {}
for path in sorted(glob.glob("klaus_note/*.py")):
    name = os.path.basename(path)
    if name in ("settings.py", "__init__.py"):
        continue
    src = open(path).read()
    hits = [t for t in ("addonManager.getConfig", "addonManager.writeConfig", "from . import USER_FILES",
                        "_pkg().get_config()", "_pkg().write_config(", "_pkg().USER_FILES",
                        "curation.USER_FILES", "retention.USER_FILES", "curation.INDEX_DIR", "retention.INDEX_DIR")
            if t in src]
    if hits:
        offenders[name] = hits
check("every module reads and writes through settings", not offenders, str(offenders))
check("the config-only reach-back helpers are gone",
      all("def _pkg" not in open(f"klaus_note/{m}.py").read() for m in ("setup_flow", "tag_migrate", "tag_sync")))

section("retention's threshold migrations are pure and registered")
import types  # noqa: E402

rt = importlib.import_module("klaus_note.retention")
check("both are registered with settings", rt._migrate_threshold_scale in st._migrations and rt._migrate_default_threshold in st._migrations)
cleared: list = []
rt.clear_threshold_overrides = lambda: cleared.append(1) or 0
raw = {"pdf_match_threshold": 0.9, "_threshold_user_set": True}
scaled = rt._migrate_threshold_scale(raw)
check("the scale migration resets the threshold, drops the user-set mark, clears overrides once, and does not write",
      scaled["pdf_match_threshold"] == rt.DEFAULT_THRESHOLD and "_threshold_user_set" not in scaled
      and scaled["_threshold_scale"] == rt.SCORE_SCALE and cleared == [1] and raw["pdf_match_threshold"] == 0.9)
check("…and is a no-op afterwards", rt._migrate_threshold_scale(scaled) is scaled and cleared == [1])
keep = {"pdf_match_threshold": 0.42, "_threshold_user_set": True, "_threshold_scale": rt.SCORE_SCALE}
check("the default migration leaves a deliberate value alone", rt._migrate_default_threshold(keep) is keep)
st.store = st.DictStore({"pdf_match_threshold": 0.55, "_threshold_scale": rt.SCORE_SCALE})
st.migrate()
check("migrate() carries an inherited default forward through the registered list",
      st.read()["pdf_match_threshold"] == rt.DEFAULT_THRESHOLD)

section("bootstrap: the registering module is imported and the harness fence lets patches land")
import json  # noqa: E402
import subprocess  # noqa: E402

# A fresh process, because this file has already imported retention itself:
# the question is what __init__ ALONE registers before profile_did_open
# runs settings.migrate, and whether exec_klaus_note_under_qt leaves a
# settings.patch that can land (the stub mw's col is a new _Dummy per
# access, so a live current_profile() fence would drop every write).
_PROBE = """
import json, sys, tempfile
sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import install, exec_klaus_note_under_qt
install()
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
K = exec_klaus_note_under_qt(tempfile.mkdtemp(prefix="klaus-boot-probe-"))
import klaus_note.settings as st
loaded = "klaus_note.retention" in sys.modules
st.store = st.DictStore({})
st.patch({"probe": 1})
print(json.dumps({"retention_loaded": loaded, "migrations": [f.__name__ for f in st._migrations],
                  "patched": st.read().get("probe") == 1}))
"""
_env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
_out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, env=_env, timeout=120)
_probe = json.loads(_out.stdout.strip().splitlines()[-1]) if _out.stdout.strip() else {}
check("__init__ imports retention at module level, so its two threshold migrations are registered before profile_did_open runs settings.migrate",
      _probe.get("retention_loaded") is True
      and {"_migrate_threshold_scale", "_migrate_default_threshold"} <= set(_probe.get("migrations", [])),
      repr(_probe) + _out.stderr[-400:])
check("after exec_klaus_note_under_qt a main-thread settings.patch lands (no stub-mw profile fence, no swallowed hop)",
      _probe.get("patched") is True, repr(_probe))

section("pdf_path_for falls back to the configured library root through settings")
import tempfile  # noqa: E402

ph = importlib.import_module("klaus_note.pdf_handler")
tmp = tempfile.mkdtemp()
uf = os.path.join(tmp, "uf")
os.makedirs(os.path.join(uf, "pdfs"))
root = os.path.join(tmp, "root")
os.makedirs(root)
open(os.path.join(root, "lecture.pdf"), "wb").write(b"%PDF")
import json  # noqa: E402

open(os.path.join(uf, "library_map.json"), "w").write(json.dumps({"lecture": "lecture.pdf"}))
st.store = st.DictStore({"library_root": root})
check("resolves under the configured root with no explicit root argument",
      ph.pdf_path_for(uf, "lecture") == os.path.join(root, "lecture.pdf"))
st.store = st.DictStore({})
check("…and returns None with no root configured and no file", ph.pdf_path_for(uf, "lecture") is None)

section("dashboard.write_cfg writes through settings and keeps its preview rule")
dash = importlib.import_module("klaus_note.dashboard")
bg = importlib.import_module("klaus_note.background")
st.store = st.DictStore({"heatmap_enabled": True})
armed: list = []
bg.preview_active = lambda: True
bg.effective_cfg = lambda _c: {"background_mode": "theme"}
bg.set_preview = lambda d: armed.append(d)
dash.write_cfg({"heatmap_enabled": False})
check("stored config is patched", st.read()["heatmap_enabled"] is False)
check("the armed preview is re-armed with the same patch", armed == [{"background_mode": "theme", "heatmap_enabled": False}])

raise SystemExit(report())
