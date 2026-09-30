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
store.update(embedding_model='saved-model')
# A profile whose one-time threshold migration (retention, K-302) already
# ran: these tests pin what SETTINGS write, not that migration's write.
store.update(_threshold_scale='centered', _threshold_default_applied=0.45)
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
        if self.success.__name__ == 'external_ready':
            # External-client discovery has its own real Preferences suite.
            self.success(None)
            return
        operations.append(self)
mm.QueryOp = Op
rt = importlib.import_module('klausmate.ollama_runtime')
real_setup, real_update, real_ensure = rt.full_setup, rt.update_runtime, rt.ensure_server
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
    def model_capabilities(self, name):
        return ['vision', 'completion'] if name == 'vision-model' else ['embedding']
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
def launch_work():
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
    return t
def work():
    launch_work().join()
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
advanced = dlg.findChild(QtWidgets.QPushButton, 'AdvancedModelSettings')
check('advanced toggle exists', advanced is not None)
check('technical endpoint hidden by default', not field('endpoint').isVisible())
if advanced:
    advanced.click(); app.processEvents()
    check('advanced toggle reveals endpoint', field('endpoint').isVisible())
    advanced.click(); app.processEvents()
    check('advanced toggle hides endpoint again', not field('endpoint').isVisible())
search = dlg.findChild(QtWidgets.QLineEdit, 'SettingsSearch')
if search is None:
    search = next(w for w in dlg.findChildren(QtWidgets.QLineEdit) if w.placeholderText() == 'Search')
search.setText('Ollama endpoint'); app.processEvents()
check('search reveals matching advanced setting', field('endpoint').isVisible())
search.clear(); app.processEvents()
check('clearing search restores collapsed advanced state', not field('endpoint').isVisible())
required = ['Install/start', 'Stop managed server', 'Update runtime', 'Refresh', 'Download', 'Delete']
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
check('installed model shows its purpose', 'Card matching' in inventory.item(0).text())
models.append('vision-model')
button('Refresh').click(); work(); drain()
inventory.setCurrentRow(2)
check('vision model is labeled', 'Images' in inventory.item(2).text())
check('vision selection preserves card model', field('embedding_model').text() == 'saved-model')
models.remove('vision-model')
button('Refresh').click(); work(); drain()
inventory.setCurrentRow(1)
check('selection populates pending embedding field only', field('embedding_model').text() == 'new-model' and store['embedding_model'] == 'saved-model' and not writes)
auto = dlg.findChild(QtWidgets.QAbstractButton, 'runtime_auto_setup')
auto.setChecked(False)
save_preferences()
check('Save persists selection and automatic management', store['embedding_model'] == 'new-model' and not store['runtime_auto_setup'] and bool(sweeps))
button('Install/start').click()
check('explicit install click queues background setup', len(operations) == 1 and not button('Download').isEnabled())
before = status.text()
work()
check('worker progress does not touch Qt directly', status.text() == before)
pending.pop(0)()
check('queued runtime progress reaches main-thread widgets', progress.value() == 25 and status.text() == 'Downloading runtime')
drain()
check('runtime progress and completion recover controls', ('setup', store['endpoint']) in calls and button('Download').isEnabled() and button('Stop managed server').isEnabled())
state['update_error'] = True
button('Update runtime').click(); work(); drain()
check('failed update restores retry control', button('Update runtime').isEnabled() and 'Retry Update' in status.text())
state['update_error'] = False
button('Update runtime').click()
work(); drain()
check('update uses runtime helper and disables current version update', 'update' in calls and not button('Update runtime').isEnabled())
field('pull_model').setText('downloaded-model')
_tasks = importlib.import_module('klausmate.tasks')
_tasks.run_on_main = lambda fn: fn()
_tasks.clear()
button('Download').click()
check('a download shows in the status bar while it runs',
      [t.label for t in _tasks.snapshot() if t.key == 'ollama'] == ['Ollama: Pull downloaded-model'], str(_tasks.snapshot()))
work()
_o = [t for t in _tasks.snapshot() if t.key == 'ollama']
check('...with its streamed progress', len(_o) == 1 and _o[0].done == 50 and _o[0].total == 100, str(_o))
pending.pop(0)()
check('streamed model progress reaches main-thread widgets', progress.value() == 50 and status.text() == 'Downloading model')
drain()
check('...and leaves the bar when it finishes', all(t.key != 'ollama' for t in _tasks.snapshot()), str(_tasks.snapshot()))
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
button('Download').click(); work(); drain()
check('failure actionable and controls usable', 'Retry Pull' in status.text() and button('Download').isEnabled() and button('Refresh').isEnabled())
check('a failed download leaves its reason in the bar',
      [t.message for t in _tasks.snapshot() if t.key == 'ollama'] == ['Pull failed: Download failed. Retry Pull.'], str(_tasks.snapshot()))
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
check('reopen loads saved local settings', field('embedding_model').text() == store['embedding_model'])
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
button('Download').click(); work()
late_status = dlg.findChild(QtWidgets.QLabel, 'OllamaStatus')
late_progress = dlg.findChild(QtWidgets.QProgressBar, 'OllamaProgress')
previous = (late_status.text(), late_progress.value())
dlg.accept()
drain()
check('closed dialog ignores queued progress and failure', mm._OPEN_DLG is None and previous == (late_status.text(), late_progress.value()))
# Runtime lifetime is profile scoped, including operations launched from
# dialogs that have already closed. Exercise the real profile stop hook and
# readiness coordinator with blocked fake runtime workers.
sf = importlib.import_module('klausmate.setup_flow')
sf.mw = mw
sf.QueryOp = Op
sf._first_run_dialog_shown_this_session = True
sys.modules['aqt.gui_hooks'].profile_will_close = []
store['runtime_auto_setup'] = True
state['setup_error'] = False
state['error'] = False

def close_profile():
    sf.stop_local_runtime()
    for hook in list(sys.modules['aqt.gui_hooks'].profile_will_close):
        if getattr(hook, '__name__', '') == '_on_profile_will_close':
            hook()
    drain()

for action, helper, raises in [('Install/start', 'full_setup', False),
                                ('Update runtime', 'update_runtime', False),
                                ('Install/start', 'full_setup', True),
                                ('Update runtime', 'update_runtime', True)]:
    case = action + (' exception' if raises else '')
    state.update(owned=True, version='old')
    mm.manage_models_dialog(); dlg = mm._OPEN_DLG
    button('Refresh').click(); work(); drain()
    entered, release, next_entered = threading.Event(), threading.Event(), threading.Event()
    lifetime_events, cancellation = [], []
    def stop():
        lifetime_events.append('stop')
        state['owned'] = False
    rt.server_manager.stop = stop
    original = getattr(rt, helper)
    def delayed(cfg, cancel_flag=None, **kwargs):
        cancellation.append(cancel_flag)
        entered.set()
        if not release.wait(3):
            raise RuntimeError('test worker release timed out')
        # Simulate a cancellation checkpoint racing with the final spawn.
        lifetime_events.append('old spawn')
        state['owned'] = True
        if raises:
            raise RuntimeError('Synthetic failure after late spawn')
        return rt.EnsureResult('started', cfg['endpoint'])
    setattr(rt, helper, delayed)
    button(action).click()
    old_worker = launch_work()
    check(case + ' fake worker entered', entered.wait(2))
    close_profile()
    check(case + ' receives profile cancellation', bool(cancellation and cancellation[0] is not None and cancellation[0].is_set()))
    def next_ensure(cfg, **kwargs):
        lifetime_events.append('new spawn')
        state['owned'] = True
        next_entered.set()
        return rt.EnsureResult('started', cfg['endpoint'])
    rt.ensure_server = next_ensure
    sf._readiness_after_library_root()
    new_worker = launch_work()
    check(case + ' next profile waits for old startup cleanup', not next_entered.wait(0.05))
    release.set()
    old_worker.join(3); new_worker.join(3)
    drain()
    check(case + ' late server cleaned before new profile starts',
          lifetime_events == ['stop', 'old spawn', 'stop', 'new spawn'] and state['owned'])
    setattr(rt, helper, original)

# A queued old operation must never start after the next profile is active.
for action in ('Install/start', 'Stop managed server', 'Update runtime'):
    state.update(owned=True, version='old')
    mm.manage_models_dialog(); dlg = mm._OPEN_DLG
    button('Refresh').click(); work(); drain()
    button(action).click()
    old_op = operations.pop(0)
    close_profile()
    sf._readiness_after_library_root(); work(); drain()
    before = list(calls), list(lifetime_events)
    operations.append(old_op)
    work(); drain()
    check('queued old ' + action + ' cannot affect next profile runtime',
          before == (calls, lifetime_events) and state['owned'])

# Ordinary dialog close does not invalidate this profile's install consent.
state.update(owned=False, setup_error=False)
mm.manage_models_dialog(); dlg = mm._OPEN_DLG
button('Install/start').click()
dlg.accept()
work(); drain()
check('ordinary dialog close still permits same-profile background install', state['owned'])
# Exercise the real occupied-port decision ladder without native processes.
rt.full_setup, rt.update_runtime, rt.ensure_server = real_setup, real_update, real_ensure
rt.provision_runtime = lambda *args: None
rt.cleanup_old_runtimes = lambda **kwargs: None
rt._port_in_use = lambda *args: True
rt._free_port = lambda: 11435
running = {'endpoint': None}
rt.ollama_reachable = lambda endpoint: endpoint == running['endpoint']
def spawn(binary, host):
    running['endpoint'] = 'http://' + host
    state['owned'] = True
rt.server_manager = types.SimpleNamespace(
    active_binary=lambda: '/fake/ollama',
    spawned_or_adopted=lambda: state['owned'],
    spawn=spawn, poll_ready=lambda endpoint: (True, ''),
    adopt_orphan_if_any=lambda endpoint: None,
    stop=lambda: (state.update(owned=False), running.update(endpoint=None)))
embed_calls = []
Client.embed = lambda self, model, texts: (embed_calls.append((self.endpoint, model)) or [[3, 4]])
provider = importlib.import_module('klausmate.embeddings').provider_from_config(K.get_config)
main_ident = threading.get_ident()
write_threads = []
def traced_write(cfg):
    write_threads.append(threading.get_ident())
    write(cfg)
K.write_config = traced_write
for action in ('Install/start', 'Update runtime'):
    for variant in ('close', 'new endpoint', 'unsaved endpoint', 'stale profile', 'open'):
        case = action + ' relocation ' + variant
        store.update(endpoint='http://127.0.0.1:11434', embedding_model='saved-model', color_theme='rose')
        state.update(owned=False, version='old')
        running['endpoint'] = None
        mm.manage_models_dialog(); dlg = mm._OPEN_DLG
        if action == 'Update runtime':
            state['owned'] = True
            button('Refresh').click(); work(); drain()
        field('embedding_model').setText('unsaved-model')
        if variant == 'unsaved endpoint':
            field('endpoint').setText('http://127.0.0.1:11436')
        button(action).click()
        work()
        check(case + ' worker never writes config', store['endpoint'].endswith(':11434'))
        store['color_theme'] = 'ocean'
        if variant == 'new endpoint':
            store['endpoint'] = 'http://127.0.0.1:11437'
        if variant == 'stale profile':
            sf.stop_local_runtime()
        if variant != 'open':
            dlg.accept()
        drain()
        expected = ('http://127.0.0.1:11437' if variant == 'new endpoint' else
                    'http://127.0.0.1:11434' if variant in ('unsaved endpoint', 'stale profile') else
                    'http://127.0.0.1:11435')
        check(case + ' endpoint delivery respects ownership', store['endpoint'] == expected)
        check(case + ' preserves unrelated and unsaved settings',
              store['color_theme'] == 'ocean' and store['embedding_model'] == 'saved-model')
        if variant in ('close', 'open'):
            result = rt.ensure_server(K.get_config())
            check(case + ' subsequent startup reaches running server', result.ok and result.endpoint == running['endpoint'])
            provider.embed(['test'])
            check(case + ' provider uses saved relocation', embed_calls[-1] == (running['endpoint'], 'saved-model'))
        if variant == 'open':
            check(case + ' visible endpoint follows saved relocation', field('endpoint').text() == expected)
            dlg.accept()
check('relocation config writes all execute on main thread', bool(write_threads) and set(write_threads) == {main_ident})
# Welcome retains its actual primary and secondary actions after dead-code removal.
store['_first_run_done'] = False
sf.QMessageBox = QtWidgets.QMessageBox
welcome_boxes = []
original_box = sf._themed_message_box
def capture_box(*args):
    box = original_box(*args)
    welcome_boxes.append(box)
    return box
sf._themed_message_box = capture_box
sf.first_run_check()
welcome = welcome_boxes[-1]
check('welcome shows local model guidance and Preferences plus Later',
      sf.LOCAL_MODELS_COPY in welcome.text() and sorted(b.text() for b in welcome.buttons()) == ['KlausMate Preferences', 'Later']
      and welcome.defaultButton().text() == 'KlausMate Preferences')
welcome.accept()
mw.close()
raise SystemExit(report())
