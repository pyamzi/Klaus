"""MCP contracts against scratch lecture data and an injected collection."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, check, report
install()
ep = importlib.import_module('klaus_note.anki_endpoint')
vc = importlib.import_module('klaus_note.viewer_context')
ps = importlib.import_module('klaus_note.page_store')
ph = importlib.import_module('klaus_note.pdf_handler')
at = importlib.import_module('klaus_note.anki_tools')

with tempfile.TemporaryDirectory(prefix='MCP contracts ') as scratch:
    root = Path(scratch)
    (root / 'contexts').mkdir()
    (root / 'pdfs').mkdir()
    for name, pages in [('A', ['A one', 'A two']), ('B', ['B one'])]:
        path = root / 'pdfs' / (name + '.pdf')
        path.write_bytes(b'%PDF-1.4 scratch placeholder')
        (root / 'contexts' / (name + '.txt')).write_text('\n'.join(pages))
        (root / 'contexts' / (name + '.json')).write_text(json.dumps({'pages': pages}))
        ps.ensure_records(scratch, name, str(path), pages)
    a = str(root / 'pdfs' / 'A.pdf')
    vc.report_document(1, 'A', 'Lecture A', a, 2)
    vc.activate(1)
    vc.report_page(1, 1)
    approvals, writes = [], []
    allow = [True]
    def approve(title, sections):
        approvals.append(sections)
        return allow[0]
    class Col:
        def find_notes(self, query): return []
    def create(col, args, ctx):
        if args.get('fields', {}).get('Front') == 'fail':
            raise at.ToolError('Invalid note fields')
        writes.append(args)
        return {'note_id': len(writes)}
    end = ep.Endpoint(col_getter=Col, run_on_main=lambda fn, timeout: fn(), approver=approve,
                      ctx_factory=lambda: {'user_files': scratch}, version='test')
    def rpc(method, params=None, **changes):
        body = dict(jsonrpc='2.0', id=1, method=method, params=params or {})
        body.update(changes)
        return ep.mcp_dispatch(end, body, None)[1]
    def call(name, arguments):
        return rpc('tools/call', {'name': name, 'arguments': arguments})
    def rejected(reply):
        return 'error' in reply or reply.get('result', {}).get('isError', False)
    note = dict(deck='Default', model='Basic', fields={'Front': 'one', 'Back': 'two'},
                source_pdf='A', source_page=2)
    with patch.dict(at._HANDLERS, create_note=create), patch.object(ps, 'render_page_png', return_value=b'png') as render:
        with patch.dict(at._HANDLERS, search_lecture_pdfs=lambda *args: {'chunks':[{'source':'A.txt','page':2,'text':'A two'}]}):
            hit = call('search_lecture_pdfs', {'query':'A'})['result']['structuredContent']['result'][0]
            check('lecture search returns a directly usable PDF id', hit['pdf'] == 'A' and hit['source'] == 'A.txt')
        current = call('current_page', {'include_image': False})['result']
        check('text-only current page skips image rendering', not current['isError'] and not render.called)
        check('page result has structured source', current.get('structuredContent', {}).get('result', {}).get('pdf') == 'A')
        vc.report_document(1, 'B', 'Lecture B', str(root/'pdfs/B.pdf'), 1)
        out = call('add_note', note)
        check('explicit source survives viewer switch', not rejected(out) and writes and 'klaus::from::A' in writes[-1]['tags'] and 'klaus::from::B' not in writes[-1]['tags'])
        check('approval names the explicit source', approvals and any('klaus::from::A' in text for _, text in approvals[-1]))
        before = (len(approvals), len(writes))
        for args in [dict(note, source_pdf='../A'), dict(note, source_pdf='missing'),
                     dict(note, source_page=3), dict(note, source_page=True),
                     dict(note, fields={'Front': 3}), dict(note, surprise=True),
                     {k:v for k,v in note.items() if k != 'source_pdf'}]:
            check('invalid note rejected before approval', rejected(call('add_note', args)) and before == (len(approvals), len(writes)))
        render.reset_mock()
        out = call('get_page', {'pdf_id':'A', 'page':2, 'include_image':False})
        check('explicit page reads unopened lecture', not rejected(out) and 'A two' in json.dumps(out))
        check('explicit page leaves viewer alone and skips image', vc.current().pdf_safe == 'B' and not render.called)
        out = call('get_page', {'pdf_id':'A', 'page':1, 'include_image':True})
        check('explicit page image is MCP image block', not rejected(out) and any(b['type']=='image' for b in out['result']['content']))
        for args in [{'pdf_id':'../A','page':1}, {'pdf_id':'missing','page':1}, {'pdf_id':'A','page':0}, {'pdf_id':'A','page':3}]:
            check('page lookup validates imported ID and bounds', rejected(call('get_page', args)))
        before = (len(approvals), len(writes))
        notes = [note, dict(note, fields={'Front':'fail'}), dict(note, source_pdf='B', source_page=1)]
        out = call('add_notes', {'notes':notes})
        outcomes = out.get('result', {}).get('structuredContent', {}).get('result', [])
        check('batch has one approval and independent outcomes', not rejected(out) and len(approvals)==before[0]+1 and len(writes)==before[1]+2 and len(outcomes)==3 and outcomes[0]['note_id'] and outcomes[1]['error'] and outcomes[2]['note_id'])
        check('batch notes retain their own sources', len(writes)>=2 and 'klaus::from::A' in writes[-2]['tags'] and 'klaus::from::B' in writes[-1]['tags'])
        before = (len(approvals), len(writes))
        for notes in [[], [note]*21, [note, dict(note, source_pdf='missing')]]:
            check('invalid batch rejected before any approval or write', rejected(call('add_notes', {'notes':notes})) and before==(len(approvals),len(writes)))
        allow[0] = False
        check('declined batch has no writes', rejected(call('add_notes', {'notes':[note]})) and len(writes)==before[1])
        end._ask = lambda *args: None
        check('timed out batch has no writes', rejected(call('add_notes', {'notes':[note]})) and len(writes)==before[1])
        for bad in ['text', [], True, 42]:
            check('malformed arguments are protocol errors', 'error' in call('current_view', bad))
        for args in [{'limit':0,'query':'a'}, {'limit':True,'query':'a'}, {'limit':101,'query':'a'}]:
            check('search limits validated', rejected(call('search_notes', args)))
        check('unknown tool is protocol error', rpc('tools/call', {'name':'missing'}) .get('error', {}).get('code') == -32602)
        check('invalid JSON-RPC envelope rejected', rpc('ping', jsonrpc='1.0').get('error', {}).get('code') == -32600)
        check('unknown requested version negotiates supported version', rpc('initialize', {'protocolVersion':'2099-01-01'})['result']['protocolVersion']=='2025-06-18')
        check('supported version retained', rpc('initialize', {'protocolVersion':'2025-06-18'})['result']['protocolVersion']=='2025-06-18')
        check('notifications have no response', ep.mcp_dispatch(end, {'jsonrpc':'2.0','method':'ping'}, None)[1] is None)
        tools = {t['name']:t for t in ep.mcp_tools()}
        check('tool annotations describe reads and writes', tools['current_page'].get('annotations', {}).get('readOnlyHint') is True and tools['add_note'].get('annotations', {}).get('readOnlyHint') is False)
        check('tools declare structured output', all('outputSchema' in t for t in tools.values()))
    vc.forget(1)
raise SystemExit(report())
