"""Exercise the actual Preferences controls with Qt and fake local services."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
from enum import IntEnum

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.claude/skills/klaus-test/scripts'))
from anki_stubs import install, exec_klausmate_under_qt, check, report
install()
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
scratch = tempfile.TemporaryDirectory()
K = exec_klausmate_under_qt(scratch.name)
store = json.loads(Path('klausmate/config.json').read_text())
store.update(embedding_model='saved-model', transcription_model_path='/saved model.bin')
writes, pending, operations, calls = [], [], [], []
K.get_config = lambda: dict(store)
def write(cfg):
    store.update(cfg)
    writes.append(dict(cfg))
K.write_config = write
mw = QtWidgets.QMainWindow()
mw.taskman = types.SimpleNamespace(run_on_main=pending.append)
mw.reset = lambda: None
mw.addonManager = types.SimpleNamespace(getConfig=lambda _: dict(store))
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
mm = importlib.import_module('klausmate.manage_models')
mm.mw = mw
importlib.import_module('klausmate.curation').index_stats = lambda: {'exists': False}
sweeps = []
importlib.import_module('klausmate.index_queue').offer_model_sweep = lambda *args: sweeps.append(args)
class Op:
    def __init__(self, parent, op, success):
        self.op, self.success, self.free = op, success, False
    def failure(self, callback):
        self.fail = callback
        return self
    def without_collection(self):
        self.free = True
        return self
    def run_in_background(self):
        check('operation has no collection access', self.free)
        operations.append(self)
mm.QueryOp = Op
rt = importlib.import_module('klausmate.ollama_runtime')
state = {'owned': False, 'version': 'old', 'error': False}
rt.runtime_download_size_hint = lambda: '~123 MB'
rt.find_managed_runtime = lambda: (state['version'], '/fake/ollama')
rt.server_manager = types.SimpleNamespace(
    active_binary=lambda: "/fake/ollama",
    spawned_or_adopted=lambda: state['owned'],
    stop=lambda: (calls.append('stop'), state.update(owned=False)))
def setup(cfg, on_progress=None, **kwargs):
    calls.append(('setup', cfg['endpoint']))
    if on_progress:
        on_progress({'status': 'Downloading runtime', 'completed': 25, 'total': 100})
    if state.get('setup_error'):
        raise RuntimeError('Install failed. Retry Install/start.')
    state['owned'] = True
    return rt.EnsureResult('started', cfg['endpoint'])
rt.full_setup = setup
def update(cfg, **kwargs):
    calls.append('update')
    if state.get('update_error'):
        raise RuntimeError('Update failed. Retry Update runtime.')
    state['version'] = rt.OLLAMA_VERSION
    return rt.EnsureResult('started', cfg['endpoint'])
rt.update_runtime = update
models = ['saved-model', 'new-model']
class Client:
    def __init__(self, endpoint, **kwargs):
        self.endpoint = endpoint
    def health(self):
        calls.append('health')
        return True
    def list_models(self):
        calls.append('list')
        if state.get('list_error'):
            raise RuntimeError('Inventory failed. Retry Refresh.')
        return list(models)
    def pull(self, name, on_event=None):
        calls.append(('pull', name))
        on_event({'status': 'Downloading model', 'completed': 50, 'total': 100})
        if state['error']:
            raise RuntimeError('Download failed. Retry Pull.')
        models.append(name)
    def delete(self, name):
        calls.append(('delete', name))
        if state.get('delete_error'):
            raise RuntimeError('Delete failed. Retry Delete.')
        models.remove(name)
importlib.import_module('klausmate.ollama_client').OllamaClient = Client

def drain():
    while pending:
        pending.pop(0)()
    app.processEvents()
def work():
    op = operations.pop(0)
    def run():
        try:
            result = op.op(None)
        except Exception as exc:
            pending.append(lambda exc=exc: op.fail(exc))
        else:
            pending.append(lambda: op.success(result))
    t = threading.Thread(target=run)
    t.start()
    t.join()
def button(text):
    return next((b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == text), None)
def save_preferences():
    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        button('Save').click()
    check('Save emits no application diagnostics', not diagnostics.getvalue().strip(), diagnostics.getvalue())
def field(name):
    return dlg.findChild(QtWidgets.QLineEdit, name)
def answer(yes):
    boxes = [b for b in dlg.findChildren(QtWidgets.QMessageBox) if b.isVisible()]
    check('confirmation opens without blocking', bool(boxes))
    if boxes:
        boxes[-1].button(QtWidgets.QMessageBox.StandardButton.Yes if yes else QtWidgets.QMessageBox.StandardButton.No).click()
        drain()

mm.manage_models_dialog()
dlg = mm._OPEN_DLG
nav = dlg.findChild(QtWidgets.QListWidget, 'SettingsNav')
nav.setCurrentRow(next(i for i in range(nav.count()) if nav.item(i).text() == 'Local models'))
app.processEvents()
check('opening Local models performs no runtime or network action', not calls and not operations and not writes)
required = ['Install/start', 'Stop managed server', 'Update runtime', 'Refresh', 'Pull', 'Delete']
check('runtime and inventory controls exist', all(button(s) for s in required))
if not all(button(s) for s in required):
    dlg.accept()
    raise SystemExit(report())
status = dlg.findChild(QtWidgets.QLabel, 'OllamaStatus')
progress = dlg.findChild(QtWidgets.QProgressBar, 'OllamaProgress')
inventory = dlg.findChild(QtWidgets.QListWidget, 'InstalledModels')
check('download size shown before install consent', any('~123 MB' in l.text() for l in dlg.findChildren(QtWidgets.QLabel)))
check('stop initially disabled', not button('Stop managed server').isEnabled())
button('Refresh').click()
work(); drain()
check('refresh retrieves installed names without changing config', inventory.count() == 2 and not writes and field('embedding_model').text() == 'saved-model')
check('external server cannot be stopped', not button('Stop managed server').isEnabled() and 'external' in status.text().lower())
inventory.setCurrentRow(1)
check('selection populates pending embedding field only', field('embedding_model').text() == 'new-model' and store['embedding_model'] == 'saved-model' and not writes)
auto = dlg.findChild(QtWidgets.QAbstractButton, 'runtime_auto_setup')
auto.setChecked(False)
field('transcription_model_path').setText('/new model.bin')
field('transcription_model_path').textEdited.emit('/new model.bin')
save_preferences()
check('Save persists selection and automatic management with transcription', store['embedding_model'] == 'new-model' and not store['runtime_auto_setup'] and store['transcription_model_path'] == '/new model.bin' and bool(sweeps))
button('Install/start').click()
check('explicit install click queues background setup', len(operations) == 1 and not button('Pull').isEnabled())
before = status.text()
work()
check('worker progress does not touch Qt directly', status.text() == before)
pending.pop(0)()
check('queued runtime progress reaches main-thread widgets', progress.value() == 25 and status.text() == 'Downloading runtime')
drain()
check('runtime progress and completion recover controls', ('setup', store['endpoint']) in calls and button('Pull').isEnabled() and button('Stop managed server').isEnabled())
state['update_error'] = True
button('Update runtime').click(); work(); drain()
check('failed update restores retry control', button('Update runtime').isEnabled() and 'Retry Update' in status.text())
state['update_error'] = False
button('Update runtime').click()
work(); drain()
check('update uses runtime helper and disables current version update', 'update' in calls and not button('Update runtime').isEnabled())
field('pull_model').setText('downloaded-model')
button('Pull').click()
work()
pending.pop(0)()
check('streamed model progress reaches main-thread widgets', progress.value() == 50 and status.text() == 'Downloading model')
drain()
check('pull downloads requested name and refreshes inventory', ('pull', 'downloaded-model') in calls and inventory.count() == 3 and store['embedding_model'] == 'new-model')
inventory.setCurrentRow(2)
button('Delete').click(); answer(False)
check('declining deletion performs no operation', not operations and 'downloaded-model' in models)
state['delete_error'] = True
button('Delete').click(); answer(True); work(); drain()
check('failed deletion restores selected delete control', button('Delete').isEnabled() and 'Retry Delete' in status.text())
state['delete_error'] = False
button('Delete').click(); answer(True)
work(); drain()
check('confirmed deletion invokes provider', ('delete', 'downloaded-model') in calls and inventory.count() == 2)
state['error'] = True
field('pull_model').setText('broken-model')
button('Pull').click(); work(); drain()
check('failure actionable and controls usable', 'Retry Pull' in status.text() and button('Pull').isEnabled() and button('Refresh').isEnabled())
button('Stop managed server').click(); work(); drain()
check('stop calls owned server manager', 'stop' in calls and not button('Stop managed server').isEnabled())
state['setup_error'] = True
button('Install/start').click(); work(); drain()
check('failed install restores controls', button('Install/start').isEnabled() and 'Retry Install/start' in status.text())
state['list_error'] = True
button('Refresh').click(); work(); drain()
check('failed refresh restores controls', button('Refresh').isEnabled() and 'Retry Refresh' in status.text())
state['list_error'] = False
# Save pending selection before closing and confirm stored values reload.
save_preferences()
dlg.accept()
mm.manage_models_dialog(); dlg = mm._OPEN_DLG
check('reopen loads saved local settings', field('embedding_model').text() == store['embedding_model'] and field('transcription_model_path').text() == '/new model.bin')
nav = dlg.findChild(QtWidgets.QListWidget, 'SettingsNav')
nav.setCurrentRow(next(i for i in range(nav.count()) if nav.item(i).text() == 'Local models'))
button('Refresh').click(); work(); drain()
render = os.environ.get('KLAUS_SETTINGS_RENDER')
if render:
    app.processEvents()
    dlg.grab().save(render)
    scroll = dlg.findChild(QtWidgets.QStackedWidget).currentWidget().findChild(QtWidgets.QScrollArea)
    check('page has no horizontal overflow', scroll.horizontalScrollBar().maximum() == 0)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents()
    dlg.grab().save(str(Path(render).with_stem(Path(render).stem + '-bottom')))
field('pull_model').setText('late-model')
button('Pull').click(); work()
late_status = dlg.findChild(QtWidgets.QLabel, 'OllamaStatus')
late_progress = dlg.findChild(QtWidgets.QProgressBar, 'OllamaProgress')
previous = (late_status.text(), late_progress.value())
dlg.accept()
drain()
check('closed dialog ignores queued progress and failure', mm._OPEN_DLG is None and previous == (late_status.text(), late_progress.value()))
mw.close()
raise SystemExit(report())
