"""K-303: garbled text layers (unmapped glyph IDs) are detected and OCR'd or blanked."""
from __future__ import annotations
import base64, http.server, importlib, json, os, sys, tempfile, threading
sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install, check, section, report
install()
ph = importlib.import_module('klausmate.pdf_handler')
oc = importlib.import_module('klausmate.ollama_client')

# Verbatim from Bootcamp Heme/Onc page 70 (0-based 69) and a clean page.
GARBLED = ('%RRWFDPS\x11FRP2QFRORJ\\\x1d\x033ULQFLSOHV\x03RI\x032QFRORJ\\\x03DQG\x037KHUDSHXWLFV\n'
           '&HOO\x03*URZWK\x035HJXODWLRQ\nƔ* \x14ĺ\x036\x03FKHFNSRLQW\x1d\n')
CLEAN = ('Bootcamp.com\n• Vitamin-K Dependent Carboxylation:\n'
         '• Factors II, VII, IX, X, protein C and S require carboxylation in the liver\n')

section('detector')
check('garbled page flagged', ph.looks_garbled(GARBLED))
check('clean page not flagged', not ph.looks_garbled(CLEAN))
check('empty page not flagged', not ph.looks_garbled(''))
check('tabs and newlines are not garbage', not ph.looks_garbled('a\tb\r\nc\n\n\t\td'))
check('one stray control is not garbage', not ph.looks_garbled('Cell growth\x0c regulation'))


class FakeClient:
    def __init__(self, models=('nomic-embed-text:latest', 'glm-ocr:latest'), fail=False):
        self.models, self.fail, self.calls = models, fail, []
    def list_models(self):
        if self.models is None:
            raise oc.OllamaNotRunning('down')
        return self.models
    def generate(self, model, prompt, images):
        self.calls.append((model, prompt, images))
        if self.fail:
            raise oc.OllamaError('boom')
        return '  Cell Growth Regulation\n'


class Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f'client.{name} used on a clean document')


renders = []
def render(path, i):
    renders.append((path, i))
    return b'PNG%d' % i

section('repair')
pages = [CLEAN, GARBLED, CLEAN, GARBLED]
client = FakeClient()
out = ph.repair_garbled_pages('x.pdf', pages, client=client, render=render)
check('only flagged pages OCR\'d', out == [CLEAN, 'Cell Growth Regulation', CLEAN, 'Cell Growth Regulation'])
check('input list untouched', pages == [CLEAN, GARBLED, CLEAN, GARBLED])
check('rendered flagged pages only', renders == [('x.pdf', 1), ('x.pdf', 3)])
check('OCR model tag and base64 page image', client.calls[0] == ('glm-ocr:latest', ph.OCR_PROMPT, [base64.b64encode(b'PNG1').decode()]))

check('clean document never reaches Ollama', ph.repair_garbled_pages('x.pdf', [CLEAN], client=Untouchable(), render=render) == [CLEAN])

renders.clear()
out = ph.repair_garbled_pages('x.pdf', [CLEAN, GARBLED], client=FakeClient(models=['nomic-embed-text']), render=render)
check('no OCR model: garbled page blanked, no render', out == [CLEAN, ''] and renders == [])
out = ph.repair_garbled_pages('x.pdf', [CLEAN, GARBLED], client=FakeClient(models=None), render=render)
check('Ollama down: garbled page blanked', out == [CLEAN, ''])
out = ph.repair_garbled_pages('x.pdf', [GARBLED, CLEAN], client=FakeClient(fail=True), render=render)
check('OCR failure: garbled page blanked', out == ['', CLEAN])
def broken(path, i): raise RuntimeError('no QtPdf')
out = ph.repair_garbled_pages('x.pdf', [GARBLED], client=FakeClient(), render=broken)
check('render failure: garbled page blanked', out == [''])

section('ingest wiring')
if ph.PDF_AVAILABLE:
    seen = []
    real = ph.repair_garbled_pages
    ph.repair_garbled_pages = lambda path, pages: (seen.append(path), ['fixed'] * len(pages))[1]
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'deck.pdf')
        w = ph.pypdf.PdfWriter(); w.add_blank_page(100, 100)
        with open(src, 'wb') as f:
            w.write(f)
        check('extract_pages stays the raw layer', ph.extract_pages(src) == [''] and not seen)
        uf = os.path.join(tmp, 'uf')
        ph.save_pdf(uf, 'deck', src)
        check('save_pdf stores repaired text', ph.load_pages(uf, 'deck') == ['fixed'] and seen == [src])
    ph.repair_garbled_pages = real
else:
    print('SKIP ingest wiring: pypdf unavailable under this python')

section('ollama generate')
got = []
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        got.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        body = json.dumps({'response': 'slide text'}).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
srv = http.server.HTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
text = oc.OllamaClient(f'http://127.0.0.1:{srv.server_port}').generate('glm-ocr', 'Text Recognition:', ['aW1n'])
srv.shutdown()
check('generate returns response text', text == 'slide text')
check('generate posts a non-streaming image request', got == [('/api/generate', {'model': 'glm-ocr', 'prompt': 'Text Recognition:', 'images': ['aW1n'], 'stream': False})])

raise SystemExit(report())
