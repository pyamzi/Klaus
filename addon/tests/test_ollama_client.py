from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install
install()
client_module = importlib.import_module('klaus_note.ollama_client')
OllamaClient = client_module.OllamaClient
OllamaError = client_module.OllamaError


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def do_DELETE(self):
        self.respond()

    def respond(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.requests.append((self.command, self.path, json.loads(body) if body else None))
        status, payload = self.server.routes[self.path]
        self.send_response(status)
        if status == 302:
            self.send_header('Location', self.server.redirect)
        self.end_headers()
        self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.requests = []
        self.server.routes = {
            '/api/tags': (200, {'models': [{'name': 'nomic-embed-text:latest'}]}),
            '/api/embed': (200, {'embeddings': [[1, 0], [0, 1]]}),
            '/api/pull': (200, b'{"status":"downloading","total":10,"completed":5}\n{"status":"success"}\n'),
            '/api/delete': (200, {}),
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        self.client = OllamaClient(self.url, timeout=1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_embedding_order_and_payload(self):
        self.assertEqual(self.client.embed('nomic-embed-text', ['a', 'b']), [[1, 0], [0, 1]])
        self.assertEqual(self.server.requests, [('POST', '/api/embed', {'model': 'nomic-embed-text', 'input': ['a', 'b'], 'truncate': True})])

    def test_model_capabilities(self):
        self.server.routes['/api/show'] = (200, {'capabilities': ['embedding']})
        self.assertEqual(self.client.model_capabilities('selected'), ['embedding'])
        self.assertEqual(self.server.requests[-1], ('POST', '/api/show', {'model': 'selected'}))
        for value in (None, 'embedding', {}):
            self.server.routes['/api/show'] = (200, {'capabilities': value})
            self.assertEqual(self.client.model_capabilities('selected'), [])
        self.server.routes['/api/show'] = (500, {'error': 'unavailable'})
        with self.assertRaises(OllamaError):
            self.client.model_capabilities('selected')

    def test_wrong_count(self):
        self.server.routes['/api/embed'] = (200, {'embeddings': [[1, 0]]})
        with self.assertRaises(OllamaError):
            self.client.embed('selected', ['a', 'b'])

    def test_server_error(self):
        self.server.routes['/api/embed'] = (500, {'error': 'model unavailable'})
        with self.assertRaisesRegex(OllamaError, 'model unavailable'):
            self.client.embed('missing', ['a'])

    def test_refused_connection(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            client = OllamaClient('http://127.0.0.1:%d' % reserved.getsockname()[1], timeout=1)
            self.assertFalse(client.health())
            with self.assertRaises(client_module.OllamaNotRunning):
                client.embed('selected', ['a'])

    def test_inventory_pull_delete(self):
        self.assertTrue(self.client.health())
        self.assertEqual(self.client.list_models(), ['nomic-embed-text:latest'])
        events = []
        self.client.pull('selected', events.append)
        self.assertEqual(events, [{'status': 'downloading', 'total': 10, 'completed': 5}, {'status': 'success'}])
        self.client.delete('selected')
        self.assertEqual(self.server.requests[-2:], [('POST', '/api/pull', {'name': 'selected', 'stream': True}), ('DELETE', '/api/delete', {'name': 'selected'})])

    def test_failed_and_truncated_pull(self):
        for payload in (b'{"error":"pull failed"}\n', b'{"status":"downloading"}\n', b'{"status":', b''):
            with self.subTest(payload=payload):
                self.server.routes['/api/pull'] = (200, payload)
                with self.assertRaises(OllamaError):
                    self.client.pull('selected')

    def test_remote_and_invalid_endpoints_rejected_before_request(self):
        for endpoint in ('https://127.0.0.1:11434', 'http://example.org:11434', 'http://127.0.0.1:0', 'http://127.0.0.1:65536', 'http://user@localhost:11434', 'http://localhost/path', 'http://localhost?x=1'):
            with self.subTest(endpoint=endpoint), patch('urllib.request.OpenerDirector.open') as request:
                with self.assertRaises(OllamaError):
                    OllamaClient(endpoint).embed('selected', ['private'])
                request.assert_not_called()

    def test_proxies_bypassed(self):
        with patch('urllib.request._opener', None), patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1', 'no_proxy': '', 'NO_PROXY': ''}):
            self.assertTrue(OllamaClient(self.url).health())

    def test_redirect_not_followed(self):
        self.server.routes['/api/tags'] = (302, {})
        self.server.redirect = self.url + '/api/delete'
        self.assertFalse(self.client.health())
        self.assertEqual([r[1] for r in self.server.requests], ['/api/tags'])


if __name__ == '__main__':
    unittest.main()
