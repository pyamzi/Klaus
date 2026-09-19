"""Real offscreen Preferences and profile notification checks, using scratch storage."""
from __future__ import annotations

import contextlib
from enum import IntEnum
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.claude/skills/klaus-test/scripts'))
from anki_stubs import install, exec_klausmate_under_qt, check, report

install()
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
scratch = tempfile.TemporaryDirectory()
K = exec_klausmate_under_qt(scratch.name)
store = json.loads((Path(__file__).resolve().parents[1] / 'klausmate/config.json').read_text())
store.update(transcription_model_path='/saved model.bin', transcription_binary='/saved cli',
             transcription_language='fa', preserved_fixture='untouched')
K.get_config = lambda: dict(store)
writes = []
def write(cfg):
    store.clear()
    store.update(cfg)
    writes.append(dict(cfg))
K.write_config = write
pending = []
class Taskman:
    def run_on_main(self, callback):
        pending.append(callback)
    def run_in_background(self, task, done):
        raise AssertionError('Settings must not start background processing')
mw = QtWidgets.QMainWindow()
mw.taskman = Taskman()
mw.reset = lambda: None
mw.addonManager = types.SimpleNamespace(getConfig=lambda _package: dict(store))
mw.col = types.SimpleNamespace(note_count=lambda: 0,
                               db=types.SimpleNamespace(scalar=lambda _query: 0))
class Theme(IntEnum):
    SYSTEM = 0
    LIGHT = 1
    DARK = 2
theme_module = types.ModuleType('aqt.theme')
theme_module.Theme = Theme
theme_module.theme_manager = types.SimpleNamespace(night_mode=False)
sys.modules['aqt.theme'] = theme_module
mw.pm = types.SimpleNamespace(theme=lambda: Theme.SYSTEM)
K.mw = mw
sys.modules['aqt'].mw = mw
mm = importlib.import_module('klausmate.manage_models')
mm.mw = mw
index_queue = importlib.import_module('klausmate.index_queue')
index_queue.mw = mw
# Index status is synthetic; the dialog still runs its real load/save closures.
curation = importlib.import_module('klausmate.curation')
curation.index_stats = lambda: {'exists': False}
def click_save(button):
    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        button.click()
    check('Save emits no application diagnostics', not diagnostics.getvalue().strip(),
          diagnostics.getvalue())

mm.manage_models_dialog()
dlg = mm._OPEN_DLG
fields = {key: dlg.findChild(QtWidgets.QLineEdit, key) for key in
          ('transcription_model_path', 'transcription_binary', 'transcription_language')}
check('all local fields are real widgets', all(fields.values()))
if all(fields.values()):
    check('saved values populate', all(field.text() == store[key] for key, field in fields.items()))
    save = next(b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == 'Save')
    for key, value in [('transcription_model_path', '/new model.bin'),
                       ('transcription_binary', '/new cli'), ('transcription_language', 'de')]:
        fields[key].setText(value)
        fields[key].textEdited.emit(value)
    check('editing marks dialog dirty', save.isEnabled() and not writes)
    click_save(save)
    check('Save persists local fields and unrelated setting', store['transcription_model_path'] == '/new model.bin'
          and store['transcription_binary'] == '/new cli' and store['transcription_language'] == 'de'
          and store['preserved_fixture'] == 'untouched')
    dlg.close()
    mm.manage_models_dialog()
    dlg = mm._OPEN_DLG
    check('reopen reloads all saved values', all(dlg.findChild(QtWidgets.QLineEdit, key).text() == store[key]
                                               for key in fields))
    browse = dlg.findChild(QtWidgets.QPushButton, 'transcription_model_path_browse')
    browse.click()
    picker = dlg.findChild(QtWidgets.QFileDialog)
    check('Browse opens a real nonblocking file picker', picker is not None)
    if picker:
        picker.fileSelected.emit('/picked model.bin')
        picker.reject()
        check('Browse selection updates model field', dlg.findChild(QtWidgets.QLineEdit, 'transcription_model_path').text() == '/picked model.bin')
        click_save(next(b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == 'Save'))
    dlg.close()

shown = []
K.tooltip = shown.append
worker = K.uploader()
worker._notify_error('first error')
check('notification queues onto main thread', len(pending) == 1 and not shown)
pending.pop(0)()
check('active profile displays queued error', shown == ['first error'])
worker._notify_error('late error')
K._stop_lecture_uploader()
pending.pop(0)()
check('profile close suppresses late delivery', shown == ['first error'])
replacement = K.uploader()
worker._on_error('old worker error')
pending.pop(0)()
check('new profile rejects old uploader notification', shown == ['first error'])
K._stop_lecture_uploader()
mw.close()
raise SystemExit(report())
