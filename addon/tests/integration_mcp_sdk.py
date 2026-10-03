"""Optional official-client gate; no Anki profile, user data or runtime SDK dependency.

Run: uv run --no-project --python 3.12 --with mcp==2.2.0 python tests/integration_mcp_sdk.py
"""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, check, report
install()
ep = importlib.import_module('klaus_note.anki_endpoint')
at = importlib.import_module('klaus_note.anki_tools')


async def main():
    with tempfile.TemporaryDirectory(prefix='Klaus SDK ') as scratch:
        root = Path(scratch)
        (root/'contexts').mkdir()
        (root/'pdfs').mkdir()
        (root/'contexts/lecture.txt').write_text('Test lecture')
        (root/'contexts/lecture.json').write_text(json.dumps({'pages':['Test lecture']}))
        (root/'pdfs/lecture.pdf').write_bytes(b'%PDF-1.4 fixture')
        class Col:
            def find_notes(self, query): return []
        approvals = []
        def approve(*args):
            approvals.append(args)
            return True
        end = ep.Endpoint(col_getter=Col, run_on_main=lambda fn, timeout: fn(), approver=approve,
                          ctx_factory=lambda: {'user_files':scratch}, version='integration',
                          discovery_path=str(root/'connection.json'))
        end.start()
        params = StdioServerParameters(command=sys.executable,
            args=[str(Path('klaus_note/scripts/mcp_stdio_bridge.py').resolve()), '--discovery', str(root/'connection.json')])
        try:
            async with Client(params, read_timeout_seconds=10) as client:
                check('official SDK negotiates the supported protocol', client.protocol_version=='2025-06-18')
                check('official SDK identifies Klaus', client.server_info.name=='klaus')
                tools = {t.name:t for t in (await client.list_tools()).tools}
                check('official SDK discovers all tools', set(tools)==set(ep.MCP_TO_ACTION))
                for tool in tools.values():
                    Draft202012Validator.check_schema(tool.input_schema)
                    Draft202012Validator.check_schema(tool.output_schema)
                check('published schemas are valid JSON Schema', True)
                out = await client.call_tool('get_page', {'pdf_id':'lecture', 'page':1})
                check('official SDK reads an explicit page', not out.is_error and out.structured_content['result']['slide_text']=='Test lecture')
                Draft202012Validator(tools['get_page'].output_schema).validate(out.structured_content)
                check('page response matches advertised output schema', True)
                bad = await client.call_tool('get_page', {'pdf_id':'lecture', 'page':0})
                check('official SDK receives recoverable validation error', bad.is_error)
                note = dict(deck='Default', model='Basic', fields={'Front':'Question'}, source_pdf='lecture', source_page=1)
                with patch.dict(at._HANDLERS, create_note=lambda *args: {'note_id':42}):
                    out = await client.call_tool('add_notes', {'notes':[note]})
                    check('official SDK creates approved scratch batch', not out.is_error and out.structured_content['result'][0]['note_id']==42 and len(approvals)==1)
                Draft202012Validator(tools['add_notes'].output_schema).validate(out.structured_content)
                check('batch response matches advertised output schema', True)
                end.stop()
                end.start()
                out = await client.call_tool('current_view', {})
                check('existing SDK connection survives endpoint restart', not out.is_error)
        finally:
            end.stop()


asyncio.run(main())
raise SystemExit(report())
