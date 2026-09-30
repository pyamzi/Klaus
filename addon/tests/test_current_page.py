"""Current page context uses only the captured viewer and scratch page store."""
from __future__ import annotations
import base64, importlib, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, check, report
install()
ep = importlib.import_module('klausmate.anki_endpoint')
vc = importlib.import_module('klausmate.viewer_context')
ps = importlib.import_module('klausmate.page_store')
ph = importlib.import_module('klausmate.pdf_handler')
with tempfile.TemporaryDirectory() as root:
    approvals, main = [], []
    end = ep.Endpoint(col_getter=lambda: object(), run_on_main=lambda fn, timeout: (main.append(True), fn())[1],
                      approver=lambda *a: approvals.append(a), ctx_factory=lambda: {'user_files': root}, version='test')
    def call():
        return ep.mcp_dispatch(end, {'jsonrpc':'2.0','id':7,'method':'tools/call',
               'params':{'name':'current_page','arguments':{}}}, None)[1]['result']
    a = str(Path(root) / 'A.pdf')
    ps.ensure_records(root, 'A', a, ['first', 'slide A'])
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=')
    ps.store_page_png(root, 'A', a, 1, png)
    vc.report_document(1, 'A', 'Lecture A', a, 2)
    vc.activate(1); vc.report_page(1, 1); vc.report_selection(1, 'selected A')
    out = call()
    check('tool succeeds', not out['isError'])
    text = out['content'][0]['text']
    check('current metadata and text', all(s in text for s in ('Lecture A', 'slide A', 'selected A')))
    check('native MCP image', any(b.get('type') == 'image' and b.get('mimeType') == 'image/png' and base64.b64decode(b['data']) == png for b in out['content']))
    check('one-based metadata', json.loads(text)['page'] == 2 and json.loads(text)['count'] == 2)
    check('current_view unchanged', end.handle('klausCurrentView', {}, False)['result'] == {'pdf':'A','display':'Lecture A','page':2,'count':2,'selection':'selected A'})
    check('AnkiConnect serializable', bool(json.dumps(end.handle('klausCurrentPage', {}, False))))
    vc.report_document(1, 'B', 'Lecture B', str(Path(root)/'B.pdf'), 1)
    ph.extract_pages = lambda path: ['slide B']
    renders = []
    def render(path, page):
        renders.append((path, page))
        vc.report_document(1, 'C', 'Lecture C', 'C.pdf', 1)
        return png
    ps.render_page_png = render
    out = call(); text = out['content'][0]['text']
    check('switch has no previous content', 'slide B' in text and 'slide A' not in text and 'selected A' not in text)
    check('render keeps captured view', 'Lecture B' in text and 'Lecture C' not in text and renders == [(str(Path(root)/'B.pdf'), 0)])
    def failed(*args): raise RuntimeError('render failed')
    ps.render_page_png = failed
    out = call()
    check('image failure preserves text', not out['isError'] and 'slide B' in out['content'][0]['text'] and 'unavailable' in out['content'][0]['text'])
    vc.forget(1)
    out = call()
    check('closed view explicit no page', 'No active page' in out['content'][0]['text'] and len(out['content']) == 1)
    check('read uses main thread without approval', bool(main) and not approvals)
raise SystemExit(report())
