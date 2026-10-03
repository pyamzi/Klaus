"""Real Preferences dialog: its profile-close handler (#35).

Anki's hook runner loops over the LIVE handler list, so removing the
running Preferences handler from inside it skipped the next handler.

Run: PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python3 tests/test_prefs_profile_close_hook.py
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
from enum import IntEnum
from pathlib import Path

sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import check, exec_klaus_note_under_qt, install, report, section, LiveStore  # noqa: E402

install()
import klaus_note.settings as settings  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
scratch = tempfile.mkdtemp(prefix='klaus-g4-prefs-')
K = exec_klaus_note_under_qt(scratch)
cfg = json.loads(Path('klaus_note/config.json').read_text())
settings.store = LiveStore(cfg)
mw = QtWidgets.QMainWindow()
mw.taskman = types.SimpleNamespace(run_on_main=lambda fn: None)
mw.reset = lambda: None
mw.addonManager = types.SimpleNamespace(getConfig=lambda _: dict(cfg))
mw.col = types.SimpleNamespace(note_count=lambda: 0, db=types.SimpleNamespace(scalar=lambda _: 0))


class Theme(IntEnum):
    SYSTEM = 0
    LIGHT = 1
    DARK = 2


theme = types.ModuleType('aqt.theme')
theme.Theme = Theme
theme.theme_manager = types.SimpleNamespace(night_mode=False)
sys.modules['aqt.theme'] = theme
mw.pm = types.SimpleNamespace(theme=lambda: Theme.SYSTEM)
K.mw = sys.modules['aqt'].mw = mw
mm = importlib.import_module('klaus_note.manage_models')
mm.mw = mw
importlib.import_module('klaus_note.curation').index_stats = lambda: {'exists': False}
ops = []


class Op:
    def __init__(self, parent, op, success):
        self.op, self.success = op, success

    def failure(self, fn):
        self.fail = fn
        return self

    def without_collection(self):
        return self

    def run_in_background(self):
        if self.success.__name__ == 'external_ready':
            self.success(None)
            return
        ops.append(self)


mm.QueryOp = Op
tips = []
mm.tooltip = lambda text='', **_k: tips.append(text)
mm.showWarning = lambda *a, **k: tips.append(a[0] if a else '')


class LiveHook(list):
    """Anki 26.09's runner: ``for hook in self._hooks`` over the live list."""

    def __call__(self):
        for hook in self:
            hook()


def turn():
    for _ in range(3):
        app.processEvents()


def prefs_handlers(hook):
    return [h for h in hook if getattr(h, '__name__', '') == '_on_profile_will_close']


section('#35: closing for a profile switch does not skip the next handler')
hook = LiveHook()
sys.modules['aqt.gui_hooks'].profile_will_close = hook
mm.manage_models_dialog()
dlg = mm._OPEN_DLG
ran = []
hook.append(lambda: ran.append('sentinel'))
check('Preferences registered its handler first', len(prefs_handlers(hook)) == 1 and hook.index(prefs_handlers(hook)[0]) == 0)
hook()
check('the handler after Preferences ran', ran == ['sentinel'], str(ran))
check('the dialog closed', mm._OPEN_DLG is None)
turn()
check('...and its handler is gone a tick later', prefs_handlers(hook) == [], str(hook))

section('#35: a normal close still unregisters the handler')
hook = LiveHook()
sys.modules['aqt.gui_hooks'].profile_will_close = hook
mm.manage_models_dialog()
check('registered while open', len(prefs_handlers(hook)) == 1)
mm._OPEN_DLG.reject()
turn()
check('gone after Cancel', prefs_handlers(hook) == [], str(hook))

raise SystemExit(report())
