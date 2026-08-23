"""State-machine tests for the reworked Manage-models dialog.

PyQt6 cannot be imported here (its sip is 3.13-only), so this reimplements
the dialog's decision logic against faithful combo semantics and asserts the
behaviours that matter: assignment round-trips, missing-model detection, the
syncing guard, and the empty-library edge case.

Kept in lockstep with manage_models_dialog by construction — the functions
below are transcribed from it; if that code changes these must too.
"""
import sys

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


class Combo:
    """QComboBox semantics: items carry (text, data); index changes signal."""

    def __init__(self, on_change=None):
        self.items = []
        self.index = -1
        self.on_change = on_change
        self._edit_text = ""

    def clear(self):
        self.items = []
        self.index = -1

    def addItem(self, text, data=None):
        self.items.append((text, data))
        if self.index == -1:
            self.index = 0

    def count(self):
        return len(self.items)

    def findData(self, data):
        for i, (_t, d) in enumerate(self.items):
            if d == data:
                return i
        return -1

    def setCurrentIndex(self, i):
        changed = i != self.index
        self.index = i
        if changed and self.on_change:
            self.on_change()

    def currentData(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index][1]
        return None

    def currentText(self):
        if self._edit_text:
            return self._edit_text
        return self.items[self.index][0] if 0 <= self.index < len(self.items) else ""

    def setEditText(self, t):
        self._edit_text = t

    def pick(self, data):
        """Simulate a user choosing the item with this data."""
        i = self.findData(data)
        assert i >= 0, f"no item with data {data!r}"
        self.setCurrentIndex(i)


class World:
    """The dialog's closure state, transcribed."""

    def __init__(self, cfg, models):
        self.cfg = dict(cfg)
        self.models = list(models)
        self.syncing = False
        self.saves = 0
        self.auto = Combo(on_change=self.save_jobs)
        self.ask = Combo(on_change=self.save_jobs)
        self.claude_key = ""
        self.warns = {}
        self.sync_jobs_widgets()

    # --- transcribed from manage_models_dialog ---

    def _fill_model_combo(self, combo, current):
        combo.clear()
        for name in self.models:
            combo.addItem(name, name)
        if current and current not in self.models:
            combo.addItem(f"{current}  (not installed)", current)
        if not combo.count():
            combo.addItem("(no models installed)", "")
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def sync_jobs_widgets(self):
        self.syncing = True
        try:
            auto_active = self.cfg.get("autocomplete_model", "")
            ask_active = self.cfg.get("ask_model", "")
            is_claude = self.cfg.get("klaus_engine") == "claude"
            self._fill_model_combo(self.auto, auto_active)

            self.ask.clear()
            for name in self.models:
                self.ask.addItem(f"Local — {name}", f"ollama:{name}")
            if ask_active and ask_active not in self.models:
                self.ask.addItem(
                    f"Local — {ask_active}  (not installed)", f"ollama:{ask_active}")
            if not self.ask.count():
                self.ask.addItem("Local — (none installed)", "ollama:")
            self.ask.addItem("Claude API…", "claude:")
            want = "claude:" if is_claude else f"ollama:{ask_active}"
            idx = self.ask.findData(want)
            self.ask.setCurrentIndex(idx if idx >= 0 else 0)
            self.claude_key = self.cfg.get("claude_api_key", "")
        finally:
            self.syncing = False
        self.update_jobs_status()

    def ask_selection(self):
        data = str(self.ask.currentData() or "")
        if data.startswith("claude"):
            return "claude", ""
        return "ollama", data[len("ollama:"):] if data.startswith("ollama:") else ""

    def update_jobs_status(self):
        engine, ask_name = self.ask_selection()
        is_claude = engine == "claude"
        auto_name = str(self.auto.currentData() or "")
        auto_missing = bool(auto_name) and auto_name not in self.models
        ask_missing = bool(ask_name) and ask_name not in self.models
        self.warns = {
            "claude_fields_visible": is_claude,
            "auto": "not installed" if auto_missing else None,
            "auto_pull": auto_missing,
            "ask": ("key needed" if (is_claude and not self.claude_key.strip())
                    else ("not installed" if ask_missing else None)),
            "ask_pull": ask_missing,
        }

    def save_jobs(self):
        if self.syncing:
            return
        self.saves += 1
        auto_name = str(self.auto.currentData() or "")
        if auto_name:
            self.cfg["autocomplete_model"] = auto_name
            self.cfg["model"] = auto_name
        engine, ask_name = self.ask_selection()
        self.cfg["klaus_engine"] = engine
        if engine == "ollama" and ask_name:
            self.cfg["ask_model"] = ask_name
        self.cfg["claude_api_key"] = self.claude_key.strip()
        self.update_jobs_status()


BASE = {"autocomplete_model": "qwen3:4b", "model": "qwen3:4b",
        "ask_model": "qwen3:4b", "klaus_engine": "ollama", "claude_api_key": ""}

print("== the bug from the screenshot: config points at a missing model ==")
w = World(BASE, models=[])            # exactly the reported state
check("autocomplete flagged not installed", w.warns["auto"] == "not installed")
check("its Pull-it button shows", w.warns["auto_pull"])
check("Ask flagged not installed", w.warns["ask"] == "not installed")
check("missing model still selectable, not dropped",
      w.auto.currentData() == "qwen3:4b")
check("no silent config rewrite on open", w.saves == 0)

print("== healthy library ==")
w = World(BASE, models=["qwen3:0.6b", "qwen3:4b"])
check("no warnings", w.warns["auto"] is None and w.warns["ask"] is None)
check("autocomplete preselected from config", w.auto.currentData() == "qwen3:4b")
check("ask preselected from config", w.ask.currentData() == "ollama:qwen3:4b")
check("claude fields hidden", not w.warns["claude_fields_visible"])
check("opening the dialog saves nothing", w.saves == 0)

print("== assignment round-trips ==")
w.auto.pick("qwen3:0.6b")
check("autocomplete write", w.cfg["autocomplete_model"] == "qwen3:0.6b")
check("legacy 'model' key kept in sync", w.cfg["model"] == "qwen3:0.6b")
check("ask untouched by autocomplete change", w.cfg["ask_model"] == "qwen3:4b")

w.ask.pick("ollama:qwen3:0.6b")
check("ask model write", w.cfg["ask_model"] == "qwen3:0.6b")
check("engine stays ollama", w.cfg["klaus_engine"] == "ollama")

print("== the merged Ask control ==")
w.ask.pick("claude:")
check("engine flips to claude", w.cfg["klaus_engine"] == "claude")
check("claude fields revealed", w.warns["claude_fields_visible"])
check("warns about missing key", w.warns["ask"] == "key needed")
check("last local model remembered", w.cfg["ask_model"] == "qwen3:0.6b")
w.claude_key = "sk-ant-xyz"
w.save_jobs()
check("key entered clears the warning", w.warns["ask"] is None)
w.ask.pick("ollama:qwen3:4b")
check("switching back restores ollama", w.cfg["klaus_engine"] == "ollama")
check("and sets that model", w.cfg["ask_model"] == "qwen3:4b")
check("claude key retained for next time", w.cfg["claude_api_key"] == "sk-ant-xyz")

print("== empty library must not force Claude (regression) ==")
w = World({**BASE, "ask_model": "", "klaus_engine": "ollama"}, models=[])
check("a local placeholder exists", w.ask.findData("ollama:") >= 0)
check("placeholder is selected, not Claude", w.ask.currentData() == "ollama:")
w.auto.setCurrentIndex(0)   # user touches an unrelated row
w.save_jobs()
check("engine still ollama after unrelated edit",
      w.cfg["klaus_engine"] == "ollama", w.cfg["klaus_engine"])

print("== syncing guard ==")
w = World(BASE, models=["qwen3:4b", "llama3"])
before = w.saves
w.sync_jobs_widgets()
check("repopulating combos writes no config", w.saves == before)

print("== claude engine restored from config ==")
w = World({**BASE, "klaus_engine": "claude", "claude_api_key": "sk-ant-1"},
          models=["qwen3:4b"])
check("claude preselected", w.ask.currentData() == "claude:")
check("no key warning when key present", w.warns["ask"] is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
