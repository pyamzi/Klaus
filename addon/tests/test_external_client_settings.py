"""Real Preferences clipboard and standalone external Python configuration."""
from __future__ import annotations
import importlib, json, os, sys, tempfile, types
from pathlib import Path
from enum import IntEnum
from unittest.mock import patch
sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, exec_klaus_note_under_qt, check, report, LiveStore
install()
import klaus_note.settings as _settings  # noqa: E402
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
with tempfile.TemporaryDirectory(prefix='external clients ') as root:
    K = exec_klaus_note_under_qt(root)
    cfg = json.loads(Path('klaus_note/config.json').read_text())
    writes = []
    _settings.store = LiveStore(cfg, writes)
    mw = QtWidgets.QMainWindow()
    mw.taskman = types.SimpleNamespace(run_on_main=lambda fn: None)
    mw.reset = lambda: None
    mw.addonManager = types.SimpleNamespace(getConfig=lambda _: dict(cfg))
    mw.col = types.SimpleNamespace(note_count=lambda: 0, db=types.SimpleNamespace(scalar=lambda _: 0))
    class Theme(IntEnum):
        SYSTEM=0; LIGHT=1; DARK=2
    theme = types.ModuleType('aqt.theme'); theme.Theme = Theme
    theme.theme_manager = types.SimpleNamespace(night_mode=False)
    sys.modules['aqt.theme'] = theme
    mw.pm = types.SimpleNamespace(theme=lambda: Theme.SYSTEM)
    K.mw = sys.modules['aqt'].mw = mw
    mm = importlib.import_module('klaus_note.manage_models'); mm.mw = mw
    pending_ops = []
    class Op:
        def __init__(self, parent, op, success):
            self.op, self.success, self.free = op, success, False
        def failure(self, callback):
            self.fail = callback; return self
        def without_collection(self):
            self.free = True; return self
        def run_in_background(self):
            check('interpreter lookup collection-free', self.free)
            pending_ops.append(self)
    mm.QueryOp = Op
    importlib.import_module('klaus_note.curation').index_stats = lambda: {'exists': False}
    bridge = importlib.import_module('klaus_note.scripts.mcp_stdio_bridge')
    script = str(Path(root)/'addon space/scripts/mcp_stdio_bridge.py')
    discovery = str(Path(root)/'user files/mcp_connection.json')
    interpreter = str(Path(root)/'Python 3/python3')
    raw = bridge.client_config(interpreter, script, discovery)
    config = json.loads(raw)['mcpServers']['klaus']
    check('paths remain separate argv', config == {'command':interpreter,'args':[script,'--discovery',discovery]})
    check('no credentials or endpoint in config', 'token' not in raw and '127.0.0.1' not in raw and 'port' not in config)
    calls = []
    def probe(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stdout='2' if len(calls)==1 else '3')
    with patch.object(sys, 'executable', '/Applications/Anki.app/Contents/MacOS/anki'), patch.object(bridge.shutil, 'which', side_effect=lambda n: '/external/'+n), patch.object(bridge.os.path, 'isfile', return_value=True), patch.object(bridge.subprocess, 'run', side_effect=probe):
        check('reject Python 2 and Anki executable', bridge.external_python() == '/external/python' and all('anki' not in a[0].lower() for a in calls))
    with patch.object(bridge.shutil, 'which', return_value='/Applications/Anki.app/Contents/MacOS/anki'), patch.object(bridge.os.path, 'isfile', return_value=False), patch.object(bridge.subprocess, 'run') as run:
        check('Anki candidate never launched', bridge.external_python() is None and not run.called)
    check('real external Python is usable', bridge.external_python() is not None)
    before = sorted(str(p.relative_to(root)) for p in Path(root).rglob('*'))
    with patch.object(bridge, 'external_python', return_value=interpreter):
        mm.manage_models_dialog()
        check('dialog opens before interpreter lookup', not mm._OPEN_DLG.findChild(QtWidgets.QPushButton, 'copy_external_client_config').isEnabled())
        op = pending_ops.pop(); op.success(op.op(None))
    dlg = mm._OPEN_DLG
    field = dlg.findChild(QtWidgets.QPlainTextEdit, 'external_client_config')
    button = dlg.findChild(QtWidgets.QPushButton, 'copy_external_client_config')
    check('readonly config', field is not None and field.isReadOnly())
    button.click()
    check('real clipboard exact JSON', app.clipboard().text() == field.toPlainText())
    actual = json.loads(field.toPlainText())['mcpServers']['klaus']
    check('actual runtime paths absolute', all(os.path.isabs(p) for p in (actual['command'],actual['args'][0],actual['args'][2])))
    check('discovery belongs to scratch user files', actual['args'][2] == str(Path(_settings.user_files())/'mcp_connection.json'))
    check('no configuration writes', not writes and before == sorted(str(p.relative_to(root)) for p in Path(root).rglob('*')))
    tester = dlg.findChild(QtWidgets.QPushButton, 'test_external_client_connection')
    status = next((label for label in dlg.findChildren(QtWidgets.QLabel) if label.property('mcp_status')), None)
    check('connection test available after interpreter discovery', tester is not None and tester.isEnabled())
    if tester is not None:
        # The UI only queues work. The actual subprocess handshake is covered
        # by test_mcp_stdio_bridge and the official-client integration gate.
        tester.click()
        check('connection test disables repeat clicks while running', not tester.isEnabled() and 'Testing' in status.text())
        op = pending_ops.pop()
        with patch.object(bridge, 'test_connection', return_value={'ok':True,'message':'Connected to Klaus. 17 tools available.','tool_count':17}) as diagnostic:
            op.success(op.op(None))
        check('diagnostic uses copied interpreter and paths', diagnostic.call_args.args == (actual['command'], actual['args'][0], actual['args'][2]))
        check('connection success restores button and shows status', tester.isEnabled() and '17 tools' in status.text())
        tester.click()
        op = pending_ops.pop()
        op.success({'ok':False, 'message':'Open Anki with your profile, then test again.'})
        check('diagnostic failure is actionable and retryable', tester.isEnabled() and 'profile' in status.text())
        tester.click()
        op = pending_ops.pop()
        op.fail(RuntimeError('sensitive exception text'))
        check('unexpected diagnostic failure is sanitized', tester.isEnabled() and 'sensitive' not in status.text() and 'again' in status.text())
        tester.click()
        late_test = pending_ops.pop()
        dlg.close(); app.processEvents()
        late_test.success({'ok':True,'message':'SHOULD NOT APPEAR'})
        check('late connection result ignores closed dialog', status.text() != 'SHOULD NOT APPEAR')
    dlg.close(); app.processEvents()
    with patch.object(bridge, 'external_python', return_value=None):
        mm.manage_models_dialog()
        check('dialog opens before interpreter lookup', not mm._OPEN_DLG.findChild(QtWidgets.QPushButton, 'copy_external_client_config').isEnabled())
        op = pending_ops.pop(); op.success(op.op(None))
    dlg = mm._OPEN_DLG
    button = dlg.findChild(QtWidgets.QPushButton, 'copy_external_client_config')
    check('missing interpreter disables copy', not button.isEnabled())
    check('missing interpreter actionable', any('Install Python 3' in label.text() for label in dlg.findChildren(QtWidgets.QLabel)))
    tester = dlg.findChild(QtWidgets.QPushButton, 'test_external_client_connection')
    check('missing interpreter disables connection test', tester is not None and not tester.isEnabled())
    dlg.close(); app.processEvents()
    with patch.object(bridge, 'external_python', return_value=interpreter):
        mm.manage_models_dialog()
        old = mm._OPEN_DLG
        late = pending_ops.pop()
        old.close(); app.processEvents()
        late.success(interpreter)
        check('late lookup cannot update closed dialog', not old.findChild(QtWidgets.QPushButton, 'copy_external_client_config').isEnabled())
raise SystemExit(report())
