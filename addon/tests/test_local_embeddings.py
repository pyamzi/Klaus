"""Local adapter behavior, using the real adapter and a fake HTTP client."""
from __future__ import annotations
import importlib
import math
import os
import sys
import threading
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', 'klaus-test', 'scripts'))
from anki_stubs import install, check, report
install()
e = importlib.import_module('klausmate.embeddings')
c = importlib.import_module('klausmate.ollama_client')
check('local provider ignores legacy provider', e.provider_name({'embedding_provider': 'openai'}) == 'ollama')
check('default native signature', e.index_signature({}) == ('ollama', 'nomic-embed-text', 0))
check('old cloud index invalidated', not e.signature_matches('openai', 'nomic-embed-text', 768, e.index_signature({})))
check('model change invalidates', not e.signature_matches('ollama', 'old', 768, e.index_signature({})))
calls = []
class Client:
    def __init__(self, endpoint): self.endpoint = endpoint
    def embed(self, model, texts):
        calls.append((self.endpoint, model, list(texts)))
        return [[3, 4] for text in texts]
cfg = {'endpoint': 'http://localhost:12345', 'embedding_model': 'custom', 'embedding_dimensions': 1024}
with patch.object(c, 'OllamaClient', Client):
    provider = e.provider_from_config(lambda: cfg)
    try:
        batches = list(e.embed_batches(provider, ['one', 'two', 'three'], batch_size=2))
    except Exception as exc:
        check('local adapter works without key', False, str(exc))
    else:
        check('selected endpoint model ordering', calls == [(cfg['endpoint'], 'custom', ['one', 'two']), (cfg['endpoint'], 'custom', ['three'])])
        check('normalized vectors and offsets', [b[0] for b in batches] == [0, 2] and all(abs(sum(x*x for x in v)-1) < 1e-6 for _, vs in batches for v in vs))
    cancelled = threading.Event(); cancelled.set()
    check('cancel before request', list(e.embed_batches(provider, ['x'], cancel=cancelled)) == [])
with patch.object(c.OllamaClient, 'embed', side_effect=c.OllamaError('model missing')):
    try:
        e.provider_from_config(lambda: cfg).embed(['x'])
        check('local errors translated', False)
    except e.EmbeddingError as exc:
        check('local actionable error', 'Local models' in exc.user_message() and 'model missing' in str(exc))
# Drive the real readiness operation with deferred GUI callbacks.
from types import SimpleNamespace
setup = importlib.import_module('klausmate.setup_flow')
runtime = importlib.import_module('klausmate.ollama_runtime')
operations, main, events, patches = [], [], [], []
class Op:
    def __init__(self, parent, op, success):
        self.work, self.success, self.collection_free = op, success, False
        operations.append(self)
    def failure(self, fn): self.fail = fn; return self
    def without_collection(self): self.collection_free = True; return self
    def run_in_background(self): pass
config = {'endpoint': 'http://localhost:12345', 'runtime_auto_setup': True, 'color_theme': 'rose'}
pkg = SimpleNamespace(get_config=lambda: dict(config), patch_config=lambda value: patches.append(value))
def ensure(cfg, save_config):
    events.append('ensure')
    cfg['endpoint'] = 'http://127.0.0.1:12346'
    save_config(cfg)
    return runtime.EnsureResult('started', cfg['endpoint'])
with patch.object(setup, 'QueryOp', Op), patch.object(setup, '_pkg', lambda: pkg), patch.object(setup, 'mw', SimpleNamespace(taskman=SimpleNamespace(run_on_main=main.append))), patch.object(runtime, 'ensure_server', ensure), patch.object(runtime.server_manager, 'stop', lambda: events.append('stop')), patch.object(setup, '_offer_v2_index_sweep', lambda cfg: events.append('sweep')), patch.object(setup, '_readiness_check_body', lambda: events.append('nudge')):
    setup._readiness_after_library_root()
    check('startup deferred and collection free', operations[-1].collection_free and events == [])
    setup._first_run_dialog_shown_this_session = True
    count = len(operations)
    setup.setup_readiness_check()
    check('fresh profile starts runtime behind welcome', len(operations) == count + 1)
    setup._first_run_dialog_shown_this_session = False
    result = operations[-1].work(None)
    config['color_theme'] = 'ocean'
    main.pop(0)()
    operations[-1].success(result)
    check('only endpoint is patched', patches == [{'endpoint': 'http://127.0.0.1:12346'}])
    check('reachable startup offers stale sweep', events == ['ensure', 'sweep'])
    setup._readiness_after_library_root()
    result = operations[-1].work(None)
    setup.stop_local_runtime()
    main.pop(0)()
    operations[-1].success(result)
    check('closed profile discards save and UI callbacks', len(patches) == 1 and events[-1] == 'stop')
    setup._readiness_after_library_root()
    setup.stop_local_runtime()
    before = list(events)
    check('closed profile never begins pending startup', operations[-1].work(None) is None and events == before)
    config['runtime_auto_setup'] = False
    with patch('klausmate.ollama_setup.ollama_reachable', return_value=False):
        setup._readiness_after_library_root()
        result = operations[-1].work(None)
        operations[-1].success(result)
    check('disabled automatic management only probes then guides', events[-1] == 'nudge' and events.count('ensure') == 2)
raise SystemExit(report())
