# Page Store and API Clients Implementation Plan (API-first Klaus, Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Klaus embeds one vector per lecture page from a page record (slide text plus transcript segments), through OpenAI only, with a stdlib Anthropic Messages client ready for Plans 2 and 3, a cost estimator, two API keys in Preferences, and the Ollama runtime, OCR and their config gone.

**Architecture:** A new aqt-free `page_store.py` owns one JSON record per (PDF, page). `pdf_index.py` embeds `combined_text` per page and re-embeds only pages whose text hash changed. `openai_client.py` (embeddings, transcription) and `anthropic_client.py` (Messages, SSE) are stdlib `urllib` clients in the house pattern; `embeddings.py` keeps only OpenAI; `cost.py` is pure arithmetic over a price table. Deletions are complete: modules, imports, config keys, Preferences rows, tests, docs.

**Tech Stack:** Python 3.9-compatible source (Anki 26.8.1 runs 3.13; system python3 3.9.6 runs the tests), stdlib only (`urllib`, `json`, `hashlib`, `wave`), PyQt6 offscreen for the one Qt helper, the `tests/` harness (`anki_stubs`, `check`/`section`/`report`).

**Spec:** `docs/superpowers/specs/2026-09-15-api-first-klaus-design.md` — decisions D1, D2, D3, D8.

## Global Constraints

- Always edit the main checkout `/Users/pyamzi/Documents/Github/KlausMate-Context/klausmate/`; Anki loads it through the `addons21` symlink and the PostToolUse compile hook must stay loud.
- Headless testing: stub `aqt`/`anki`; real widgets only under `QT_QPA_PLATFORM=offscreen`; run with `PYTHONDONTWRITEBYTECODE=1`; purge `__pycache__` first. Never point tests at the real `klausmate/user_files/`; never read `meta.json`; never open, click or restart the user's running Anki. No test makes a paid API call unless `KLAUS_LIVE_API=1` is set; otherwise those checks SKIP honestly.
- Conventions: no app-modal `exec()`; defensive `try/except` around every Qt call; guarded imports; `print("[klausmate] ...")` logging; UI files never hardcode colours — `theme` tokens only; every new pin mutated once (red, then restored byte-identical, md5 recorded); the full loop `for t in tests/test_*.py; do python3 "$t" || echo FAILED; done` ends `0 failed` for every file.
- Board: one card per task, files as listed, `verify:` fails before and passes after; workers never run git write commands (the orchestrator commits after review); column moves are the orchestrator's.
- Config keys after this plan: `api_key_openai`, `api_key_anthropic`, `embedding_model` (`text-embedding-3-large`), `embedding_dimensions` (`1024`), `reasoning_model` (`claude-sonnet-5`), `transcription_model` (`gpt-4o-mini-transcribe`). Gone: `embedding_provider`, `embedding_api_key_openai` (migrated), `embedding_api_key_voyage`, `ocr_enabled`, `ocr_model`, `runtime_auto_setup`, `claude_binary`, `endpoint`, `pdf_index_max_chunks`, `pdf_match_agg`, `assistant_model` (migrated to `reasoning_model`).
- Keys live in Anki's addon config (`meta.json`), never in the repo, never logged.
- Every cache still compares signatures through `embeddings.signature_matches`, never a tuple `==`.
- Plan 3 still needs `agent_host.py`, `anki_endpoint.py` and `assistant_dock.py` to import and run in this plan: where they reference `page_ocr` or `ollama_client`, Task 6 rewires them to `page_store` with the text-layer path and no OCR (the assistant keeps working on the text layer plus the page image until Plan 3).

---

## File structure

- Create: `klausmate/page_store.py`, `klausmate/openai_client.py`, `klausmate/anthropic_client.py`, `klausmate/cost.py`; tests `tests/test_page_store.py`, `tests/test_openai_client.py`, `tests/test_anthropic_client.py`, `tests/test_cost.py`, fixtures `tests/fixtures/anthropic/*.sse`.
- Modify: `klausmate/pdf_index.py`, `klausmate/retention.py`, `klausmate/lecture_view.py` (the `best_chunk` rename), `klausmate/embeddings.py`, `klausmate/index_queue.py`, `klausmate/manage_models.py`, `klausmate/setup_flow.py`, `klausmate/__init__.py`, `klausmate/assistant_dock.py` + `klausmate/agent_host.py` (page_ocr → page_store rewire), `klausmate/config.json`, `klausmate/config.md`, `CLAUDE.md`, `AGENTS.md`, and the tests `tests/test_klausmate.py`, `tests/test_index_queue.py`, `tests/test_dialog_logic.py`, `tests/test_manage_models_assistant.py`, `tests/test_assistant_dock.py`, `tests/test_lecture_view.py`, `tests/test_retention_history.py` (if it names chunks).
- Delete: `klausmate/ollama_client.py`, `klausmate/ollama_runtime.py`, `klausmate/ollama_setup.py`, `klausmate/page_ocr.py`, `tests/test_page_ocr.py`, and any `tests/test_ollama_*.py`.

Lanes (file-disjoint): Task 1 (`page_store`) ∥ Task 2 (`openai_client` + `embeddings`) ∥ Task 3 (`anthropic_client`) ∥ Task 4 (`cost`). Then Task 5 (`pdf_index` + `retention` + `lecture_view`) after Tasks 1–2. Task 6 (deletions, `__init__`, `setup_flow`, `assistant_dock`/`agent_host` rewire, config) after Tasks 1–2. Task 7 (`manage_models` + `index_queue` sweep estimate) after Tasks 2, 4, 6. Task 8 (docs + `test_klausmate` re-baseline) after everything. Task 9 (integration, live checklist) last.

---

### Task 1: The page record store

**Files:**
- Create: `klausmate/page_store.py`
- Create: `tests/test_page_store.py`

**Interfaces:**
- Consumes: `pdf_handler.load_pages(user_files, name) -> list[str] | None` (existing; `contexts/<safe>.json`); `page_ocr.digest12`/`_atomic`/`render_page_png` bodies (copied here, then deleted with `page_ocr` in Task 6).
- Produces: `digest12(path) -> str`; `record_dir(user_files, pdf_safe, path) -> str`; `record_path(user_files, pdf_safe, path, page_index) -> str`; `load_record(user_files, pdf_safe, path, page_index) -> dict`; `ensure_records(user_files, pdf_safe, path, pages: list[str]) -> int` (returns the number written); `append_segment(user_files, pdf_safe, path, page_index, t0: float, t1: float, text: str) -> dict`; `combined_text(rec) -> str`; `text_hash(rec) -> str`; `page_texts(user_files, pdf_safe, path, page_count) -> list[tuple[int, str, str]]` (page 1-based, hash, combined text); `subscribe(cb) -> unsubscribe`; `render_page_png(path, page_index, long_edge=1400) -> bytes` (Qt, below the divider).

- [ ] **Step 1: Write the failing tests.** `tests/test_page_store.py` (bootstrap head copied from `tests/test_pdf_notes.py`: repo root on `sys.path`, `from anki_stubs import check, section, report`, module imported without executing `klausmate/__init__.py`):

```python
import os, tempfile, json
ps = importlib.import_module("klausmate.page_store")
root = tempfile.mkdtemp(prefix="klaus-pages-")
pdf = os.path.join(root, "lec.pdf"); open(pdf, "wb").write(b"%PDF-1.4 fake")

section("digest and paths")
d = ps.digest12(pdf)
check("digest12 is 12 hex chars from path+size+mtime", len(d) == 12 and all(c in "0123456789abcdef" for c in d))
check("record_path lands under pages/<safe>/<digest>/<page:04d>.json",
      ps.record_path(root, "lec", pdf, 3).endswith(os.path.join("pages", "lec", d, "0003.json")))
os.utime(pdf, (1, 1))
check("a changed mtime is a new directory", ps.digest12(pdf) != d)

section("ensure_records fills slide text once, never touches segments")
n = ps.ensure_records(root, "lec", pdf, ["Slide one text", "", "Slide three"])
check("one record per page, three written", n == 3)
rec = ps.load_record(root, "lec", pdf, 0)
check("slide_text stored, no segments, version 1",
      rec["slide_text"] == "Slide one text" and rec["segments"] == [] and rec["version"] == 1)
ps.append_segment(root, "lec", pdf, 0, 0.0, 30.0, "the lecturer said this")
n2 = ps.ensure_records(root, "lec", pdf, ["Slide one text CHANGED", "", "Slide three"])
rec = ps.load_record(root, "lec", pdf, 0)
check("ensure_records is idempotent for segments and refreshes slide_text",
      rec["slide_text"] == "Slide one text CHANGED" and len(rec["segments"]) == 1)

section("combined_text and text_hash")
check("combined_text is slide text, blank line, segments in time order",
      ps.combined_text(rec) == "Slide one text CHANGED\n\nthe lecturer said this")
h1 = ps.text_hash(rec)
ps.append_segment(root, "lec", pdf, 0, 30.0, 60.0, "and then this")
rec2 = ps.load_record(root, "lec", pdf, 0)
check("a new segment changes the hash; 16 hex chars", ps.text_hash(rec2) != h1 and len(h1) == 16)
check("segments keep time order even when appended out of order",
      ps.combined_text(ps.append_segment(root, "lec", pdf, 0, 10.0, 20.0, "middle")).split("\n\n")[1]
      == "the lecturer said this\nmiddle\nand then this")

section("page_texts for the index")
rows = ps.page_texts(root, "lec", pdf, 3)
check("one row per page, 1-based, (page, hash, text); empty page has empty text",
      [r[0] for r in rows] == [1, 2, 3] and rows[1][2] == "" and rows[0][1] == ps.text_hash(rec2))

section("corrupt record reads as empty, subscribe notifies")
open(ps.record_path(root, "lec", pdf, 2), "w").write("{not json")
check("corrupt → empty record, no exception", ps.load_record(root, "lec", pdf, 2)["slide_text"] == "")
seen = []
unsub = ps.subscribe(lambda safe, page: seen.append((safe, page)))
ps.append_segment(root, "lec", pdf, 1, 0.0, 1.0, "x")
unsub()
ps.append_segment(root, "lec", pdf, 1, 1.0, 2.0, "y")
check("subscriber saw exactly the one append before unsubscribe", seen == [("lec", 1)])
def _boom(*a): raise RuntimeError("boom")
ps.subscribe(_boom)
ps.append_segment(root, "lec", pdf, 1, 2.0, 3.0, "z")
check("a raising subscriber is logged, never breaks the append",
      len(ps.load_record(root, "lec", pdf, 1)["segments"]) == 3)
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_page_store.py` → `ModuleNotFoundError: klausmate.page_store`.

- [ ] **Step 3: Implement `klausmate/page_store.py`.**

```python
"""One record per (PDF, page): the slide's text and what was said on it.

The page is the seam every API-first capability keys on (spec D2): the
index embeds combined_text per page, the pertinence phase judges a card
against one page, the assistant reads one page, the recorder appends
transcript segments to one page. Records live at
user_files/pages/<pdf_safe>/<digest12>/<page:04d>.json; digest12 is over
the file's path, size and mtime, so a replaced PDF gets a fresh directory
rather than another file's stale transcript.

aqt-free above the divider; render_page_png (QtPdf) sits below it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable

VERSION = 1
SUBDIR = "pages"
LONG_EDGE = 1400

_subscribers: list[Callable[[str, int], None]] = []


def digest12(path: str, stat=os.stat) -> str:
    try:
        st = stat(path)
        key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        key = path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def record_dir(user_files: str, pdf_safe: str, path: str) -> str:
    return os.path.join(user_files, SUBDIR, pdf_safe, digest12(path))


def record_path(user_files: str, pdf_safe: str, path: str, page_index: int) -> str:
    return os.path.join(record_dir(user_files, pdf_safe, path), f"{int(page_index):04d}.json")


def _empty() -> dict:
    return {"version": VERSION, "slide_text": "", "segments": [], "updated_at": 0.0}


def load_record(user_files: str, pdf_safe: str, path: str, page_index: int) -> dict:
    p = record_path(user_files, pdf_safe, path, page_index)
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        if not isinstance(rec, dict) or not isinstance(rec.get("segments"), list):
            raise ValueError("not a page record")
        rec.setdefault("slide_text", "")
        rec.setdefault("version", VERSION)
        return rec
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as exc:
        print(f"[klausmate] page record unreadable, treating as empty: {p}: {exc}")
        return _empty()


def _atomic_json(p: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def ensure_records(user_files: str, pdf_safe: str, path: str, pages: list[str]) -> int:
    """Write slide_text for every page; existing segments survive. Idempotent."""
    n = 0
    for i, text in enumerate(pages):
        rec = load_record(user_files, pdf_safe, path, i)
        new_text = str(text or "")
        if rec["slide_text"] == new_text and os.path.exists(record_path(user_files, pdf_safe, path, i)):
            continue
        rec["slide_text"] = new_text
        rec["updated_at"] = time.time()
        _atomic_json(record_path(user_files, pdf_safe, path, i), rec)
        n += 1
    return n


def append_segment(user_files: str, pdf_safe: str, path: str, page_index: int,
                   t0: float, t1: float, text: str) -> dict:
    rec = load_record(user_files, pdf_safe, path, page_index)
    rec["segments"].append({"t0": float(t0), "t1": float(t1), "text": str(text)})
    rec["segments"].sort(key=lambda s: (float(s.get("t0", 0.0)), float(s.get("t1", 0.0))))
    rec["updated_at"] = time.time()
    _atomic_json(record_path(user_files, pdf_safe, path, page_index), rec)
    _notify(pdf_safe, page_index)
    return rec


def combined_text(rec: dict) -> str:
    slide = str(rec.get("slide_text") or "").strip()
    said = "\n".join(str(s.get("text") or "").strip() for s in rec.get("segments") or [] if str(s.get("text") or "").strip())
    if slide and said:
        return f"{slide}\n\n{said}"
    return slide or said


def text_hash(rec: dict) -> str:
    return hashlib.blake2b(combined_text(rec).encode("utf-8"), digest_size=8).hexdigest()


def page_texts(user_files: str, pdf_safe: str, path: str, page_count: int) -> list[tuple[int, str, str]]:
    out = []
    for i in range(int(page_count)):
        rec = load_record(user_files, pdf_safe, path, i)
        out.append((i + 1, text_hash(rec), combined_text(rec)))
    return out


def subscribe(cb: Callable[[str, int], None]) -> Callable[[], None]:
    _subscribers.append(cb)

    def unsubscribe() -> None:
        try:
            _subscribers.remove(cb)
        except ValueError:
            pass
    return unsubscribe


def _notify(pdf_safe: str, page_index: int) -> None:
    for cb in list(_subscribers):
        try:
            cb(pdf_safe, page_index)
        except Exception as exc:
            print(f"[klausmate] page_store subscriber failed: {exc}")


# ---- QtPdf glue -------------------------------------------------------------

def render_page_png(path: str, page_index: int, long_edge: int = LONG_EDGE) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice, QSize
    from PyQt6.QtPdf import QPdfDocument
    doc = QPdfDocument(None)
    doc.load(path)
    if doc.status() != QPdfDocument.Status.Ready or page_index < 0 or page_index >= doc.pageCount():
        raise RuntimeError(f"cannot render page {page_index + 1} of {path}")
    pts = doc.pagePointSize(page_index)
    w, h = max(1.0, pts.width()), max(1.0, pts.height())
    scale = float(long_edge) / max(w, h)
    img = doc.render(page_index, QSize(int(round(w * scale)), int(round(h * scale))))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())
```

- [ ] **Step 4: Run to verify it passes.** Same command → `0 failed`. Then `python3 -m py_compile ~/Library/Application\ Support/Anki2/addons21/klausmate/page_store.py`.

- [ ] **Step 5: Mutate once.** Remove the `sort` in `append_segment` → the time-order pin fails; restore (md5 before/after). Board comment with RED/GREEN and the md5s; card stays in Doing.

---

### Task 2: The OpenAI client; `embeddings.py` keeps one provider

**Files:**
- Create: `klausmate/openai_client.py`
- Modify: `klausmate/embeddings.py` (delete `OllamaEmbeddings`, `VoyageEmbeddings`, `OLLAMA_TIMEOUT_S`, the Voyage clamp in `embed_batches`; `DEFAULT_PROVIDER = "openai"`; `OpenAIEmbeddings.embed` calls `openai_client.embed`; key read from `api_key_openai`)
- Create: `tests/test_openai_client.py`; Modify: the embeddings section of `tests/test_klausmate.py` only if it names Voyage/Ollama (grep first; re-baseline those pins to "openai is the only provider").

**Interfaces:**
- Consumes: `embeddings._post_json` pattern (copied), `embeddings.EmbeddingError`.
- Produces: `openai_client.OpenAIError(Exception)` with `.status`, `.retry_after`, `.user_message()`; `embed(key, texts, model, dims, timeout=60.0) -> list[list[float]]`; `transcribe(key, wav_bytes, model, language="en", prompt="", timeout=120.0) -> str`; module globals `API_BASE = "https://api.openai.com/v1"` (tests monkeypatch it) and `_urlopen = urllib.request.urlopen` (tests monkeypatch it). `embeddings.py` keeps `EmbeddingError`, `index_signature`, `signature_matches`, `provider_from_config`, `embed_batches`, `embedding_model`, `embedding_dimensions`, `DEFAULT_MODELS = {"openai": "text-embedding-3-large"}`.

- [ ] **Step 1: Write the failing tests.** `tests/test_openai_client.py`, with a fake `urlopen` that records the request and returns canned bodies:

```python
oc = importlib.import_module("klausmate.openai_client")
import io, json, urllib.error

class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

calls = []
def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), req.data, timeout))
    if req.full_url.endswith("/embeddings"):
        body = json.loads(req.data)
        n = len(body["input"])
        return _Resp(json.dumps({"data": [{"index": i, "embedding": [0.1, 0.2]} for i in reversed(range(n))]}).encode())
    if req.full_url.endswith("/audio/transcriptions"):
        return _Resp(json.dumps({"text": "  hello lecture  "}).encode())
    raise AssertionError(req.full_url)
oc._urlopen = fake_urlopen

section("embed")
vecs = oc.embed("sk-test", ["a", "b"], "text-embedding-3-large", 1024)
url, headers, data, timeout = calls[-1]
body = json.loads(data)
check("POSTs to /v1/embeddings with bearer auth, model, dimensions",
      url == oc.API_BASE + "/embeddings" and headers.get("Authorization") == "Bearer sk-test"
      and body == {"model": "text-embedding-3-large", "input": ["a", "b"], "dimensions": 1024})
check("vectors come back in INPUT order regardless of response order", vecs == [[0.1, 0.2], [0.1, 0.2]] and len(vecs) == 2)
check("dims=0 omits the dimensions field", (oc.embed("k", ["a"], "m", 0), "dimensions" not in json.loads(calls[-1][2]))[1])
check("empty input → [] and no request", oc.embed("k", [], "m", 0) == [] and calls[-1][0].endswith("/embeddings"))

section("transcribe")
wav = b"RIFF....WAVEfmt fake"
text = oc.transcribe("sk-test", wav, "gpt-4o-mini-transcribe", language="en", prompt="previous words")
url, headers, data, timeout = calls[-1]
ct = headers.get("Content-type") or headers.get("Content-Type")
check("POSTs multipart to /v1/audio/transcriptions", url == oc.API_BASE + "/audio/transcriptions" and ct.startswith("multipart/form-data; boundary="))
boundary = ct.split("boundary=")[1].encode()
check("multipart carries file, model, response_format=json, language, prompt, and the wav bytes",
      data.count(b"--" + boundary) >= 6 and b'name="file"; filename="chunk.wav"' in data and b"Content-Type: audio/wav" in data
      and b'name="model"\r\n\r\ngpt-4o-mini-transcribe' in data and b'name="response_format"\r\n\r\njson' in data
      and b'name="language"\r\n\r\nen' in data and b'name="prompt"\r\n\r\nprevious words' in data and wav in data)
check("returns the stripped text", text == "hello lecture")

section("errors")
def err_urlopen(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {"retry-after": "0"}, io.BytesIO(b'{"error":{"message":"bad key"}}'))
oc._urlopen = err_urlopen
try:
    oc.embed("bad", ["a"], "m", 0); ok = False
except oc.OpenAIError as e:
    ok = e.status == 401 and "key" in e.user_message().lower()
check("401 → OpenAIError with a user_message about the key", ok)
attempts = []
def flaky(req, timeout=None):
    attempts.append(1)
    if len(attempts) == 1:
        raise urllib.error.HTTPError(req.full_url, 429, "rate", {"retry-after": "0"}, io.BytesIO(b"{}"))
    return _Resp(json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode())
oc._urlopen = flaky; oc._SLEEP = lambda s: None
check("429 retries once and succeeds", oc.embed("k", ["a"], "m", 0) == [[1.0]] and len(attempts) == 2)
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `ModuleNotFoundError: klausmate.openai_client`.

- [ ] **Step 3: Implement `klausmate/openai_client.py`.**

```python
"""Klaus's OpenAI client: embeddings and audio transcription, stdlib only.

The official SDK depends on compiled wheels that cannot be vendored into
an AnkiWeb add-on, so this is urllib in the embeddings._post_json house
pattern: one retry on 429/5xx, one on a network blip, errors that carry
a user_message(). The key is passed in by the caller and never logged.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

API_BASE = "https://api.openai.com/v1"
EMBED_TIMEOUT_S = 60.0
TRANSCRIBE_TIMEOUT_S = 120.0
_urlopen = urllib.request.urlopen
_SLEEP = time.sleep


class OpenAIError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    def user_message(self) -> str:
        if self.status in (401, 403):
            return "OpenAI rejected the API key — check it in KlausMate Preferences → API keys & models."
        if self.status == 429:
            wait = f" in {int(self.retry_after)}s" if self.retry_after else " shortly"
            return f"OpenAI rate-limited the request — try again{wait}."
        if self.status is not None and self.status >= 500:
            return "OpenAI is overloaded right now — try again in a minute."
        return str(self)


def _request(url: str, data: bytes, headers: dict[str, str], timeout: float, what: str) -> dict:
    last: OpenAIError | None = None
    for attempt in (0, 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with _urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retry_after: float | None = None
            try:
                ra = e.headers.get("retry-after") if e.headers else None
                if ra:
                    retry_after = float(ra)
            except (TypeError, ValueError):
                pass
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                body = ""
            last = OpenAIError(f"OpenAI {what} failed (HTTP {e.code}): {body or e.reason}", status=e.code, retry_after=retry_after)
            if attempt == 0 and (e.code == 429 or e.code >= 500):
                _SLEEP(min(retry_after or 2.0, 10.0))
                continue
            raise last from e
        except urllib.error.URLError as e:
            last = OpenAIError(f"Could not reach OpenAI {what}: {e.reason}")
            if attempt == 0:
                _SLEEP(2.0)
                continue
            raise last from e
        except json.JSONDecodeError as e:
            raise OpenAIError(f"Invalid JSON from OpenAI {what}") from e
    raise last  # type: ignore[misc]


def embed(key: str, texts: list[str], model: str, dims: int, timeout: float = EMBED_TIMEOUT_S) -> list[list[float]]:
    if not texts:
        return []
    body: dict[str, Any] = {"model": model, "input": list(texts)}
    if dims:
        body["dimensions"] = int(dims)
    resp = _request(f"{API_BASE}/embeddings", json.dumps(body).encode("utf-8"),
                    {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, timeout, "embeddings")
    data = resp.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise OpenAIError(f"OpenAI returned {len(data) if isinstance(data, list) else 'no'} embeddings for {len(texts)} inputs")
    out: list[list[float] | None] = [None] * len(texts)
    for item in data:
        i, vec = item.get("index"), item.get("embedding")
        if not isinstance(i, int) or not (0 <= i < len(texts)) or not isinstance(vec, list):
            raise OpenAIError("Malformed embedding item from OpenAI")
        out[i] = vec
    if any(v is None for v in out):
        raise OpenAIError("OpenAI response is missing embedding indices")
    return out  # type: ignore[return-value]


def _multipart(fields: list[tuple[str, str]], file_field: str, filename: str, content_type: str, blob: bytes) -> tuple[bytes, str]:
    boundary = "klaus" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8"))
    parts.append(blob)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(key: str, wav_bytes: bytes, model: str, language: str = "en", prompt: str = "",
               timeout: float = TRANSCRIBE_TIMEOUT_S) -> str:
    fields = [("model", model), ("response_format", "json"), ("language", language)]
    if prompt:
        fields.append(("prompt", prompt[:800]))
    data, ct = _multipart(fields, "file", "chunk.wav", "audio/wav", wav_bytes)
    resp = _request(f"{API_BASE}/audio/transcriptions", data,
                    {"Content-Type": ct, "Authorization": f"Bearer {key}"}, timeout, "transcription")
    return str(resp.get("text") or "").strip()
```

Then in `klausmate/embeddings.py`: delete `OllamaEmbeddings`, `VoyageEmbeddings`, `OLLAMA_TIMEOUT_S`, the module docstring's Voyage/Ollama bullets, the Voyage clamp in `embed_batches`; set `DEFAULT_MODELS = {"openai": "text-embedding-3-large"}`, `DEFAULT_PROVIDER = "openai"`, `_PROVIDER_CLASSES = {"openai": OpenAIEmbeddings}`; `provider_name(cfg)` returns `"openai"` always (keep the function: callers exist); `OpenAIEmbeddings.embed` becomes:

```python
    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if not texts:
            return []
        cfg = self._get_config()
        key = str(cfg.get("api_key_openai") or "").strip()
        if not key:
            raise EmbeddingError("OpenAI API key is not set — add it in KlausMate Preferences → API keys & models.",
                                 provider="OpenAI", status=401)
        from . import openai_client
        try:
            return openai_client.embed(key, texts, embedding_model(cfg), _dimensions_for(cfg))
        except openai_client.OpenAIError as e:
            raise EmbeddingError(str(e), provider="OpenAI", status=e.status, retry_after=e.retry_after) from e
```

`_post_json` and `_vectors_by_index` become unused: delete them (grep first; `tests/test_klausmate.py` may pin `_post_json` — re-baseline that pin to `openai_client._request`).

- [ ] **Step 4: Run to verify it passes.** `tests/test_openai_client.py` and `tests/test_klausmate.py` → `0 failed`; compile through the symlink.

- [ ] **Step 5: Mutate once.** In `embed` drop the reorder loop (return vectors in response order) → the input-order pin fails; restore with md5s. Board comment; card stays in Doing.

---

### Task 3: The Anthropic Messages client

**Files:**
- Create: `klausmate/anthropic_client.py`
- Create: `tests/test_anthropic_client.py`, `tests/fixtures/anthropic/text_turn.sse`, `tests/fixtures/anthropic/tool_use_turn.sse`, `tests/fixtures/anthropic/dropped_stream.sse`

**Interfaces:**
- Consumes: `git show a494f2d:klausmate/llm_client.py` (the body to revive; drop `HostedBackend`, `HOSTED_API_BASE`, `backend_name`, `backend_from_config`, the `hosted` flag) and `git show a494f2d:tests/test_llm_client.py` (the pins to revive).
- Produces: `API_BASE`, `API_VERSION = "2023-06-01"`, `LLMError` (`.status`, `.error_type`, `.retry_after`, `.user_message()`), `consume_sse(resp, on_text=None, on_block_start=None, cancel=None) -> dict` (`{"content": [...], "stop_reason": str|None}`), `text_of(result) -> str`, `Client(get_config)` with `.stream(payload, on_text=None, on_block_start=None, cancel=None, timeout=DEFAULT_TIMEOUT_S) -> dict` and `.complete(payload, timeout=DEFAULT_TIMEOUT_S) -> dict` (non-streaming: the parsed response body, `content` and `stop_reason` at top level); key read from `cfg["api_key_anthropic"]`; module globals `_urlopen` for tests.

- [ ] **Step 1: Write the fixtures and failing tests.** `tests/fixtures/anthropic/text_turn.sse` (lines exactly as the API sends them):

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_1","role":"assistant","content":[]}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}

event: message_stop
data: {"type":"message_stop"}
```

`tool_use_turn.sse`: a `content_block_start` with `{"type":"tool_use","id":"toolu_1","name":"record_verdicts","input":{}}`, two `input_json_delta` deltas whose `partial_json` halves concatenate to `{"verdicts":[{"nid":7,"pertinent":true,"reason":"same mechanism"}]}`, `content_block_stop`, `message_delta` with `stop_reason: "tool_use"`, `message_stop`. `dropped_stream.sse`: the same without `content_block_stop`, `message_delta`, `message_stop`.

`tests/test_anthropic_client.py`:

```python
ac = importlib.import_module("klausmate.anthropic_client")
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "anthropic")
def stream_of(name):
    return io.BytesIO(open(os.path.join(FIX, name), "rb").read())

section("consume_sse: text")
got = []
r = ac.consume_sse(stream_of("text_turn.sse"), on_text=got.append)
check("text deltas concatenate and stream out in order", r["content"] == [{"type": "text", "text": "Hello"}] and got == ["Hel", "lo"])
check("stop_reason from message_delta", r["stop_reason"] == "end_turn")
check("text_of joins text blocks only", ac.text_of(r) == "Hello")

section("consume_sse: tool_use")
starts = []
r = ac.consume_sse(stream_of("tool_use_turn.sse"), on_block_start=starts.append)
blk = r["content"][0]
check("tool_use input assembled from partial_json at content_block_stop",
      blk["type"] == "tool_use" and blk["name"] == "record_verdicts" and blk["input"] == {"verdicts": [{"nid": 7, "pertinent": True, "reason": "same mechanism"}]})
check("on_block_start saw the tool_use block", starts and starts[0]["type"] == "tool_use")
check("stop_reason tool_use", r["stop_reason"] == "tool_use")

section("consume_sse: dropped stream and cancel")
r = ac.consume_sse(stream_of("dropped_stream.sse"))
check("a dropped stream still finalises tool_use input from the partial JSON", r["content"][0]["input"]["verdicts"][0]["nid"] == 7 and r["stop_reason"] is None)
import threading
ev = threading.Event(); ev.set()
r = ac.consume_sse(stream_of("text_turn.sse"), cancel=ev)
check("cancel set before the first line → stop_reason cancelled, no content", r["stop_reason"] == "cancelled" and r["content"] == [])

section("Client.stream and Client.complete: request shape and key")
calls = []
class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_urlopen(req, timeout=None):
    calls.append((req.full_url, dict(req.headers), json.loads(req.data)))
    if json.loads(req.data).get("stream"):
        return stream_of("text_turn.sse")
    return _Resp(json.dumps({"id": "msg_2", "content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"}).encode())
ac._urlopen = fake_urlopen
c = ac.Client(lambda: {"api_key_anthropic": "sk-ant-test"})
r = c.stream({"model": "claude-sonnet-5", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]})
url, headers, body = calls[-1]
check("stream POSTs /v1/messages with x-api-key, anthropic-version and stream:true",
      url == ac.API_BASE + "/v1/messages" and headers.get("X-api-key") == "sk-ant-test"
      and headers.get("Anthropic-version") == ac.API_VERSION and body["stream"] is True)
r2 = c.complete({"model": "claude-sonnet-5", "max_tokens": 64, "messages": []})
check("complete never sets stream and returns the parsed body", "stream" not in calls[-1][2] and r2["stop_reason"] == "end_turn" and ac.text_of(r2) == "done")
try:
    ac.Client(lambda: {}).complete({"model": "m", "max_tokens": 1, "messages": []}); ok = False
except ac.LLMError as e:
    ok = e.status == 401 and "key" in e.user_message().lower()
check("no key → LLMError 401 with a user message, no request", ok)
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `ModuleNotFoundError: klausmate.anthropic_client`.

- [ ] **Step 3: Implement.** `git show a494f2d:klausmate/llm_client.py > klausmate/anthropic_client.py`, then edit: module docstring (Klaus's Messages client, revived 2026-09-15, stdlib for the same wheel reason); delete `HOSTED_API_BASE`, `HostedBackend`, `_BACKENDS`, `backend_name`, `backend_from_config`, and the `hosted` parameter/attribute everywhere (`_open_stream(url, data, headers, timeout)`, `LLMError(..., hosted=...)` → drop the kwarg and any "sign in to use the hosted assistant" copy); rename `DirectBackend` → `Client`, its key lookup to `cfg.get("api_key_anthropic")` and the 401 message to `"No Anthropic API key set — add it under KlausMate Preferences → API keys & models."`; add `_urlopen = urllib.request.urlopen` and use it in `_open_stream`; add:

```python
    def complete(self, payload: dict, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
        """One non-streaming request; the parsed response body."""
        key = self._key()
        body = dict(payload)
        body.pop("stream", None)
        req_data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": API_VERSION}
        resp = _open_stream(f"{API_BASE}/v1/messages", req_data, headers, float(timeout))
        try:
            raw = resp.read().decode("utf-8")
        finally:
            try:
                resp.close()
            except Exception:
                pass
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMError("Invalid JSON from the Messages API", error_type="protocol") from e
```

with `_key()` factored out of `stream`. Keep `consume_sse`, `text_of`, `_parse_error_body`, `_RETRYABLE_STATUSES`, `_MAX_RETRY_AFTER_S`, `DEFAULT_TIMEOUT_S = 300.0` as they were.

- [ ] **Step 4: Run to verify it passes.** `tests/test_anthropic_client.py` → `0 failed`; compile through the symlink. Also revive the pins from `a494f2d:tests/test_llm_client.py` that still apply (drop hosted/backend ones) into the same test file.

- [ ] **Step 5: Mutate once.** Delete the post-loop finalisation block in `consume_sse` → the dropped-stream pin fails; restore with md5s. Board comment; card stays in Doing.

---

### Task 4: The cost estimator

**Files:**
- Create: `klausmate/cost.py`, `tests/test_cost.py`

**Interfaces:**
- Produces: `Estimate(tokens: int, dollars: float)` (NamedTuple), `PRICES` dict, `estimate_embed(chars: int, model: str = "text-embedding-3-large") -> Estimate`, `estimate_judge(n_cards: int, page_chars_mean: int, card_chars_mean: int = 600, batch: int = 8, model: str = "claude-sonnet-5") -> Estimate`, `estimate_transcribe(seconds: float, model: str = "gpt-4o-mini-transcribe") -> Estimate`, `format_estimate(e: Estimate) -> str`, `add(*estimates) -> Estimate`.

- [ ] **Step 1: Write the failing tests.**

```python
cost = importlib.import_module("klausmate.cost")
section("price table and arithmetic")
check("every price is dated in the source (a comment naming 2026-09-15 sits above PRICES)", "2026-09-15" in open(cost.__file__).read())
e = cost.estimate_embed(4_000_000)
check("embed: chars/4 tokens at the per-million input price", e.tokens == 1_000_000 and abs(e.dollars - cost.PRICES["text-embedding-3-large"][0]) < 1e-9)
j = cost.estimate_judge(n_cards=80, page_chars_mean=1200, card_chars_mean=600, batch=8)
check("judge: 10 batches, each (page + 8 cards + prompt overhead) in and ~40 tokens per verdict out",
      j.tokens > 0 and j.dollars > 0 and cost.estimate_judge(160, 1200).tokens > j.tokens)
t = cost.estimate_transcribe(3600)
check("transcribe: priced per minute, 60 minutes", abs(t.dollars - 60 * cost.PRICES["gpt-4o-mini-transcribe"][0]) < 1e-9)
check("format_estimate reads like '~1,000,000 tokens · about $0.13'", cost.format_estimate(e) == "~1,000,000 tokens · about $0.13")
check("format_estimate floors tiny sums at 'under $0.01'", cost.format_estimate(cost.Estimate(10, 0.000001)).endswith("under $0.01"))
s = cost.add(e, j, t)
check("add sums tokens and dollars", s.tokens == e.tokens + j.tokens + t.tokens and abs(s.dollars - (e.dollars + j.dollars + t.dollars)) < 1e-9)
check("unknown model → a clear error, never a silent zero", (lambda: cost.estimate_embed(1, "no-such-model")).__call__ if False else True)
try:
    cost.estimate_embed(1, "no-such-model"); ok = False
except KeyError:
    ok = True
check("unknown model raises KeyError", ok)
raise SystemExit(report())
```

- [ ] **Step 2: Run to verify it fails.** `ModuleNotFoundError`.

- [ ] **Step 3: Implement `klausmate/cost.py`.**

```python
"""Paid-pass estimates, before Klaus spends anything (spec D8).

Prices are constants you edit; they are dollars per million tokens
(input, output) for text models and dollars per minute (price, None) for
audio. Tokens are estimated at four characters each — an estimate, shown
as one, never a bill.
"""
from __future__ import annotations

from typing import NamedTuple

# Prices as published 2026-09-15; edit when they change.
PRICES: dict[str, tuple[float, float | None]] = {
    "text-embedding-3-large": (0.13, None),
    "text-embedding-3-small": (0.02, None),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "gpt-4o-mini-transcribe": (0.003, None),   # per minute
    "gpt-4o-transcribe": (0.006, None),        # per minute
}
CHARS_PER_TOKEN = 4
JUDGE_PROMPT_OVERHEAD_TOKENS = 350
JUDGE_OUTPUT_TOKENS_PER_CARD = 40


class Estimate(NamedTuple):
    tokens: int
    dollars: float


def _tokens(chars: int) -> int:
    return max(0, int(chars)) // CHARS_PER_TOKEN


def estimate_embed(chars: int, model: str = "text-embedding-3-large") -> Estimate:
    price_in, _ = PRICES[model]
    t = _tokens(chars)
    return Estimate(t, t / 1_000_000 * price_in)


def estimate_judge(n_cards: int, page_chars_mean: int, card_chars_mean: int = 600,
                   batch: int = 8, model: str = "claude-sonnet-5") -> Estimate:
    price_in, price_out = PRICES[model]
    n_batches = -(-max(0, int(n_cards)) // max(1, int(batch)))
    per_batch_in = JUDGE_PROMPT_OVERHEAD_TOKENS + _tokens(page_chars_mean) + batch * _tokens(card_chars_mean)
    tokens_in = n_batches * per_batch_in
    tokens_out = max(0, int(n_cards)) * JUDGE_OUTPUT_TOKENS_PER_CARD
    return Estimate(tokens_in + tokens_out, tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * (price_out or 0.0))


def estimate_transcribe(seconds: float, model: str = "gpt-4o-mini-transcribe") -> Estimate:
    per_minute, _ = PRICES[model]
    minutes = max(0.0, float(seconds)) / 60.0
    return Estimate(0, minutes * per_minute)


def add(*estimates: Estimate) -> Estimate:
    return Estimate(sum(e.tokens for e in estimates), sum(e.dollars for e in estimates))


def format_estimate(e: Estimate) -> str:
    money = "under $0.01" if e.dollars < 0.005 else f"about ${e.dollars:.2f}"
    return f"~{e.tokens:,} tokens · {money}"
```

- [ ] **Step 4: Run to verify it passes.** → `0 failed`. Mutate once: change `CHARS_PER_TOKEN` to 5 → the embed pin fails; restore. Board comment; card stays in Doing.

---

### Task 5: One vector per page

**Files:**
- Modify: `klausmate/pdf_index.py` (`INDEX_VERSION = 2`; `PdfIndex.chunks` → `pages: list[tuple[int, str]]`; delete `stride_sample`, `chunk_pages`, `chunk_text_at`; `load`/`save`/`stats_from_disk` follow; `best_chunk` → `best_page`)
- Modify: `klausmate/retention.py` (`ensure_pdf_index.do_build` embeds from `page_store.page_texts`, hash-only re-embed; delete `DEFAULT_MAX_CHUNKS` and the `pdf_index_max_chunks` read; `match_scores` drops `agg` and records `best page` per note; `save_matches`/`load_matches` gain `"pages"`; `pdf_match_agg` gone)
- Modify: `klausmate/lecture_view.py` (`pdf_index.best_chunk` → `best_page`; page for a row is the tuple's first element still)
- Modify: `klausmate/pdf_handler.py` (`_chunk_text`, `_CHUNK_SIZE`, `_CHUNK_OVERLAP` deleted if no other caller — grep)
- Test: `tests/test_klausmate.py` (its pdf_index/retention sections), `tests/test_lecture_view.py`, `tests/test_retention_history.py` if affected.

**Interfaces:**
- Consumes: `page_store.page_texts(user_files, pdf_safe, path, page_count)`, `page_store.ensure_records`, `pdf_handler.load_pages`, `pdf_handler.pdf_path_for(user_files, base) -> str | None`, `embeddings.embed_batches(provider, texts, cancel, kind)`.
- Produces: `PdfIndex.pages: list[tuple[int, str]]`; `pdf_index.best_page(index, vec) -> tuple[int, float]` (page 1-based or -1); `retention.match_scores(pdf_idx, cidx, floor=MATCH_FLOOR) -> tuple[list[tuple[int, float]], dict[int, int]]` (scores, nid → best page 1-based); `matches.json` gains `"pages": {str(nid): page}`; `retention.load_matches` returns `(matches, pages)`.

- [ ] **Step 1: Write the failing pins** in `tests/test_klausmate.py`'s pdf_index section (replace the chunking pins):

```python
section("pdf_index v2: one row per page, hash-keyed")
idx = pdf_index.PdfIndex(provider="openai", model="m", pdf_name="lec", dims=2, source_sig=(1, 2),
                         pages=[(1, "aaaa"), (2, "bbbb")], embedded_rows=2, vectors=array("f", [1.0, 0.0, 0.0, 1.0]))
d = tempfile.mkdtemp(); pdf_index.save(idx, d); back = pdf_index.load(d)
check("pages round-trip as (page_1based, text_hash)", back.pages == [(1, "aaaa"), (2, "bbbb")] and back.embedded_rows == 2)
open(os.path.join(d, "manifest.json"), "w").write(json.dumps({"version": 1, "chunks": [], "dims": 2, "provider": "x", "model": "y"}))
check("a version-1 (chunk) manifest reads as absent → rebuild", pdf_index.load(d) is None)
check("best_page is the argmax row's page, 1-based", pdf_index.best_page(back, [0.0, 1.0]) == (2, 1.0))
check("a zero vector never wins best_page", pdf_index.best_page(pdf_index.PdfIndex(provider="o", model="m", pdf_name="z", dims=2, pages=[(1, "h")], embedded_rows=1, vectors=array("f", [0.0, 0.0])), [1.0, 0.0]) == (1, 0.0))
check("chunking helpers are gone", not hasattr(pdf_index, "chunk_pages") and not hasattr(pdf_index, "stride_sample") and not hasattr(pdf_handler, "_chunk_text"))
```

and in the retention section:

```python
section("match_scores returns the best page per note")
scores, pages = retention.match_scores(pdf_idx_fixture, cidx_fixture)
check("every scored note has a best page, 1-based", all(nid in pages and pages[nid] >= 1 for nid, _ in scores))
check("pdf_match_agg is gone", not hasattr(retention, "DEFAULT_AGG") and "pdf_match_agg" not in open(retention.__file__).read())
```

(build `pdf_idx_fixture`/`cidx_fixture` from two unit vectors each, as the existing retention pins do.)

- [ ] **Step 2: Run to verify it fails.** `TypeError: __init__() got an unexpected keyword argument 'pages'`.

- [ ] **Step 3: Implement.** `pdf_index.py`: `INDEX_VERSION = 2`; dataclass field `pages: list[tuple[int, str]] = field(default_factory=list)` replacing `chunks`; `load` reads `pages = [(int(p[0]), str(p[1])) for p in m["pages"]]`; `save` writes `"pages": [list(p) for p in index.pages]`; `stats_from_disk` reports `"pages": len(m["pages"])` (rename the key from `chunks`; `_EMPTY_STATS` too; `card_index.read_manifest` unchanged); delete `stride_sample`, `chunk_pages`, `chunk_text_at`; `best_page`:

```python
def best_page(index: PdfIndex, vec) -> tuple[int, float]:
    """Argmax-dot row for one unit query vector; (page_1based, score), or
    (-1, 0.0) when the index is empty or the dims disagree. A zero row
    scores 0.0 and only wins when every row does."""
    dims, rows = index.dims, index.embedded_rows
    if rows <= 0 or dims <= 0:
        return (-1, 0.0)
    try:
        if len(vec) != dims:
            return (-1, 0.0)
    except TypeError:
        return (-1, 0.0)
    mv = memoryview(index.vectors)
    best_i, best = 0, float("-inf")
    for i in range(rows):
        s = _sumprod(mv[i * dims:(i + 1) * dims], vec)
        if s > best:
            best_i, best = i, s
    return (index.pages[best_i][0], float(best))
```

`retention.py` `do_build`: after `src_sig`/`idx` load and the `is_fresh` early return,

```python
        pages = pdf_handler.load_pages(USER_FILES, pdf_name)
        if pages is None:
            base = pdf_handler._safe_basename(pdf_name)
            with open(os.path.join(USER_FILES, "contexts", base + ".txt"), encoding="utf-8") as f:
                pages = [f.read()]
        safe = pdf_handler._safe_basename(pdf_name)
        path = pdf_handler.pdf_path_for(USER_FILES, safe) or ""
        page_store.ensure_records(USER_FILES, safe, path, pages)
        rows = page_store.page_texts(USER_FILES, safe, path, len(pages))   # (page, hash, text)
        if not any(t for _p, _h, t in rows):
            raise RuntimeError(f"“{pdf_name}” has no extractable text to embed.")
        keys = [(p, h) for p, h, _t in rows]
        # Keep every row whose hash is unchanged (same provider/model/dims);
        # embed only the rest. Rows are rebuilt in page order.
        old: dict[int, tuple[str, list[float]]] = {}
        if idx is not None and embeddings.signature_matches(idx.provider, idx.model, idx.dims, sig) and idx.dims > 0:
            mv = memoryview(idx.vectors)
            for i, (p, h) in enumerate(idx.pages[: idx.embedded_rows]):
                old[p] = (h, list(mv[i * idx.dims:(i + 1) * idx.dims]))
        new_idx = pdf_index.PdfIndex(provider=sig[0], model=sig[1], pdf_name=safe, source_sig=src_sig, pages=keys,
                                     dims=(idx.dims if idx is not None and old else 0))
        todo = [(i, t) for i, (p, h, t) in enumerate(rows) if not (p in old and old[p][0] == h)]
        vectors_by_row: dict[int, list[float]] = {i: old[p][1] for i, (p, h, _t) in enumerate(rows) if p in old and old[p][0] == h}
        total = len(rows)
        provider = embeddings.provider_from_config(_cfg)
        done_new = 0
        for offset, vecs in embeddings.embed_batches(provider, [t for _i, t in todo], cancel=cancel, kind="document"):
            for k, vec in enumerate(vecs):
                row_i = todo[offset + k][0]
                if vec is None:
                    if new_idx.dims == 0:
                        raise RuntimeError("First page produced no embedding.")
                    vectors_by_row[row_i] = [0.0] * new_idx.dims
                else:
                    if new_idx.dims == 0:
                        new_idx.dims = len(vec)
                    elif len(vec) != new_idx.dims:
                        raise ValueError("Embedding dims changed mid-index")
                    vectors_by_row[row_i] = vec
            done_new += len(vecs)
            if on_progress:
                mw.taskman.run_on_main(lambda d=len(vectors_by_row): on_progress("Embedding pages…", d, total))
        for i in range(total):
            new_idx.vectors.extend(vectors_by_row.get(i) or [0.0] * new_idx.dims)
            new_idx.embedded_rows += 1
        pdf_index.save(new_idx, dir_path)
        return new_idx
```

(`embed_batches` yields `(offset, vecs)` with `offset` into the list it was given — confirm in `embeddings.py:357-379`; the `todo` index maps it back to the row.) `match_scores` drops `agg`, keeps `floor`, and records the argmax page: in the per-note loop, compute `best = max(range(len(chunk_rows)), key=...)`, `score = scores[best]`, and `pages[nid] = pdf_idx.pages[best][0]`; return `(out, pages)`. `save_matches` adds `"pages": {str(n): p for n, p in pages.items()}`; `load_matches` returns `(matches, {int(k): int(v) for k, v in m.get("pages", {}).items()})`; `ensure_matches` threads the tuple through (`on_done(matches)` stays — pass `matches` only; the `pages` are read back from the cache by Plan 2). Delete `DEFAULT_AGG`, the `pdf_match_agg` read, `DEFAULT_MAX_CHUNKS`, `PDF_FLUSH_EVERY` if now unused. `lecture_view.py`: `pdf_index.best_chunk(idx, vec)` → `pdf_index.best_page(idx, vec)`; the page is the returned first element directly (no `idx.chunks[row][0]` lookup).

- [ ] **Step 4: Run to verify it passes.** `tests/test_klausmate.py`, `tests/test_lecture_view.py`, `tests/test_retention_history.py`, `tests/test_index_queue.py` → `0 failed`; compile through the symlink.

- [ ] **Step 5: Mutate once.** In `do_build`, make the reuse test `old[p][0] != h` → the hash-reuse pin (add one: two builds with one page changed embed exactly one text — count `embed_batches` inputs with a fake provider) fails; restore. Board comment; card stays in Doing.

---

### Task 6: Deletions, config migration, the assistant's page context on the page store

**Files:**
- Delete: `klausmate/ollama_client.py`, `klausmate/ollama_runtime.py`, `klausmate/ollama_setup.py`, `klausmate/page_ocr.py`, `tests/test_page_ocr.py`
- Modify: `klausmate/__init__.py` (drop the `ollama_*` imports at lines ~43–47 and `client()`, `_save_config_on_main`, the readiness autostart at ~216–242; extend `_LEGACY_KEYS_DROPPED`; `_migrate_config` renames two keys and drops the `_embed_default_migrated` Ollama pin block)
- Modify: `klausmate/setup_flow.py` (delete the Ollama branches: `_embedding_ready` becomes "OpenAI key present"; `first_run_check` copy names the two keys; `setup_readiness_check`/`_readiness_after_library_root`/`_readiness_check_body`/`_maybe_offer_runtime_update` lose every Ollama path — what remains is the library-root check and the missing-key nudge)
- Modify: `klausmate/assistant_dock.py` (~382, 404, 421: `page_ocr.context_for` → a `page_store`-backed context: `combined_text` of the current page plus `render_page_png`; the `OcrScheduler` and its `ollama_client` construction go; `text_source` becomes `"page-record"`), `klausmate/agent_host.py` (`build_context_block` docstring/`text_source` labels only)
- Modify: `klausmate/config.json` (remove the gone keys; add `api_key_openai: ""`, `api_key_anthropic: ""`, `reasoning_model: "claude-sonnet-5"`, `transcription_model: "gpt-4o-mini-transcribe"`; `embedding_model: "text-embedding-3-large"`), `klausmate/config.md` (delete "Local AI engine (automatic Ollama)", rewrite "Card embeddings", add the three new keys)
- Test: `tests/test_klausmate.py` (imports/config pins), `tests/test_assistant_dock.py` (the OCR/scheduler pins → page-record pins), `tests/test_dialog_logic.py` (Ollama setup pins), `tests/test_index_queue.py` (`missing_key_provider` pins), `tests/test_agent_host.py` if it names `text_source == "ocr"`.

**Interfaces:**
- Consumes: `page_store.load_record/combined_text/render_page_png` (Task 1); `embeddings.provider_name` (Task 2).
- Produces: `assistant_dock._page_context(view) -> agent_host.PageContext`-shaped dict `{text, text_source: "page-record", png}`; `__init__._migrate_config` mapping `{"embedding_api_key_openai": "api_key_openai", "assistant_model": "reasoning_model"}`; `index_queue.missing_key_provider(cfg) -> "OpenAI" | ""` (reads `api_key_openai`).

- [ ] **Step 1: Write the failing pins.** In `tests/test_klausmate.py`:

```python
section("2026-09-15: the local runtime, OCR and their config are gone")
for name in ("ollama_client", "ollama_runtime", "ollama_setup", "page_ocr"):
    check(f"klausmate/{name}.py is deleted", not os.path.exists(os.path.join(ROOT, "klausmate", f"{name}.py")))
src = open(os.path.join(ROOT, "klausmate", "__init__.py")).read()
check("__init__ imports none of them", not re.search(r"ollama_(client|runtime|setup)|page_ocr", src))
cfg = json.load(open(os.path.join(ROOT, "klausmate", "config.json")))
for k in ("embedding_provider", "embedding_api_key_openai", "embedding_api_key_voyage", "ocr_enabled", "ocr_model", "runtime_auto_setup", "claude_binary", "endpoint", "pdf_index_max_chunks", "pdf_match_agg", "assistant_model"):
    check(f"config.json no longer defines {k}", k not in cfg)
for k, v in (("api_key_openai", ""), ("api_key_anthropic", ""), ("reasoning_model", "claude-sonnet-5"), ("transcription_model", "gpt-4o-mini-transcribe"), ("embedding_model", "text-embedding-3-large")):
    check(f"config.json defines {k} = {v!r}", cfg.get(k) == v)
section("_migrate_config renames the two surviving keys and scrubs the rest")
store = {"embedding_api_key_openai": "sk-old", "assistant_model": "claude-x", "embedding_provider": "voyage", "ocr_model": "glm-ocr", "_embed_default_migrated": True}
K.get_config = lambda: dict(store); written = {}
K.write_config = lambda c: written.update(c)
K._migrate_config()
check("api key and model renamed, old keys gone, nothing else invented",
      written.get("api_key_openai") == "sk-old" and written.get("reasoning_model") == "claude-x"
      and not any(k in written for k in ("embedding_api_key_openai", "assistant_model", "embedding_provider", "ocr_model")))
```

(`K` is the exec'd module the file already uses; `ROOT` the repo root.) In `tests/test_index_queue.py`: `missing_key_provider({"api_key_openai": ""}) == "OpenAI"` and `== ""` with a key. In `tests/test_assistant_dock.py`: replace the OCR-scheduler pins with one that a fake view with a page record yields a context whose `text` is the record's `combined_text` and `text_source == "page-record"`.

- [ ] **Step 2: Run to verify they fail.** The files still exist; `config.json` still has the keys.

- [ ] **Step 3: Implement.** Delete the four modules and their tests (`git rm` is the orchestrator's; workers use `rm` and say so). `__init__.py`: remove the imports and the Ollama autostart block; `_LEGACY_KEYS_DROPPED += ("embedding_provider", "embedding_api_key_voyage", "ocr_enabled", "ocr_model", "runtime_auto_setup", "claude_binary", "endpoint", "pdf_index_max_chunks", "pdf_match_agg", "_embed_default_migrated")` with a dated comment; in `_migrate_config`, before the drop loop:

```python
    for old, new in (("embedding_api_key_openai", "api_key_openai"), ("assistant_model", "reasoning_model")):
        if old in cfg:
            if not str(cfg.get(new) or "").strip():
                cfg[new] = cfg[old]
            cfg.pop(old)
            changed = True
```

and delete the `_embed_default_migrated` block. `setup_flow.py`: `_embedding_ready(cfg)` = `bool(str(cfg.get("api_key_openai") or "").strip())`; delete `_maybe_offer_runtime_update`, the `ollama_reachable` calls, the runtime download copy; `first_run_check`'s message becomes "Semantic search and the assistant use OpenAI and Anthropic through your own API keys. Add them in KlausMate Preferences → API keys & models." with the Open-Preferences button it already has. `index_queue.missing_key_provider(cfg)`: `return "" if str(cfg.get("api_key_openai") or "").strip() else "OpenAI"`; `missing_key_message` → "…add your OpenAI API key in KlausMate Preferences → API keys & models." `assistant_dock.py`: replace the `page_ocr`/`OcrScheduler` use with

```python
    def _page_context(self, view) -> dict:
        """The page in view as text and image, from the page record."""
        from . import page_store
        text, png = "", None
        if view is not None and view.pdf_safe:
            try:
                rec = page_store.load_record(USER_FILES, view.pdf_safe, view.path, view.page_index)
                text = page_store.combined_text(rec)
            except Exception as exc:
                print(f"[klausmate] page record for the assistant failed: {exc}")
            try:
                png = page_store.render_page_png(view.path, view.page_index)
            except Exception as exc:
                print(f"[klausmate] page render for the assistant failed: {exc}")
        return {"text": text, "text_source": "page-record", "png": png}
```

and call it where `context_for` was called; delete the scheduler construction, its `on_view`/`tick` calls and the Ollama client. `agent_host.build_context_block` accepts `text_source="page-record"` (label text "Page text:"). `config.json`/`config.md` per the Files list.

- [ ] **Step 4: Run to verify it passes.** The full loop → every file `0 failed` (`tests/test_page_ocr.py` is gone); compile every `klausmate/*.py` through the symlink; `grep -rn "ollama\|page_ocr" klausmate/*.py` → no code hits (prose in CLAUDE.md is Task 8's).

- [ ] **Step 5: Mutate once.** In `_migrate_config` skip the rename loop → the rename pin fails; restore. Board comment; card stays in Doing.

---

### Task 7: Preferences "API keys & models" and the sweep estimate

**Files:**
- Modify: `klausmate/manage_models.py` (the Semantic Search page → "API keys & models"; delete the provider combo, `embed_fix_btn`, the Ollama page and its `_EMBED_PRESETS`/pull/delete/classify machinery, the Assistant page's OCR rows and the "Claude Code binary" row; add `anthropic_key_edit`, `reasoning_model_edit`, `transcription_model_edit`; `save_embed` writes `api_key_openai`/`embedding_model`, `save_assistant` writes `api_key_anthropic`/`reasoning_model`/`transcription_model`; `_finish_nav` order)
- Modify: `klausmate/index_queue.py` (`sweep_message(n_pdfs, n_notes, model, estimate_text)`; `offer_model_sweep` computes `cost.estimate_embed` over `sum(len(note text))` for the collection — use `mw.col.db.scalar("select sum(length(flds)) from notes")` — plus the page texts of every indexed PDF)
- Test: `tests/test_manage_models_assistant.py` (rename to the surviving rows), `tests/test_dialog_logic.py` (page list and save wiring), `tests/test_index_queue.py` (`sweep_message` carries the estimate).

**Interfaces:**
- Consumes: `cost.estimate_embed/format_estimate/add` (Task 4), `embeddings.index_signature` (Task 2), `page_store.page_texts` (Task 1).
- Produces: `index_queue.sweep_message(n_pdfs: int, n_notes: int, model: str, estimate: str) -> str`; `index_queue.sweep_estimate(names: list[str]) -> cost.Estimate`; Preferences widget names `openai_key_edit`, `anthropic_key_edit`, `embed_model_edit`, `reasoning_model_edit`, `transcription_model_edit`, page title `"API keys & models"`.

- [ ] **Step 1: Write the failing pins.** `tests/test_dialog_logic.py`: the page list contains `"API keys & models"` and not `"Semantic Search"`, `"Local Models"`; `save_embed` source writes `api_key_openai` and never `embedding_provider`; `save_assistant` writes `api_key_anthropic`, `reasoning_model`, `transcription_model` and never `claude_binary`/`ocr_model`. `tests/test_index_queue.py`: `sweep_message(2, 30000, "text-embedding-3-large", "~1,000 tokens · about $0.01")` contains the estimate string and the counts. `tests/test_manage_models_assistant.py`: delete the OCR/classify/pull pins; keep `assistant_reopen`, Clear Sessions; add "the Assistant page has no OCR row and no binary row" source pins.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** In `manage_models.py`, the page:

```python
    keys_layout = _page(
        "API keys & models", "API keys & models",
        "Klaus talks to OpenAI (embeddings, lecture transcription) and "
        "Anthropic (the assistant, and judging which cards a lecture "
        "really covers) with your own keys. Both are stored in this "
        "add-on's config on your machine and never sent anywhere else.",
    )
    openai_key_edit = QLineEdit(); openai_key_edit.setEchoMode(QLineEdit.EchoMode.Password); openai_key_edit.setMinimumWidth(220)
    _row(keys_layout, "OpenAI API key", "Embeddings and lecture transcription.", openai_key_edit)
    anthropic_key_edit = QLineEdit(); anthropic_key_edit.setEchoMode(QLineEdit.EchoMode.Password); anthropic_key_edit.setMinimumWidth(220)
    _row(keys_layout, "Anthropic API key", "The assistant and card pertinence.", anthropic_key_edit)
    embed_model_edit = QLineEdit(); embed_model_edit.setPlaceholderText("text-embedding-3-large")
    _row(keys_layout, "Embedding model", "Changing it re-embeds everything (Klaus asks first, with an estimate).", embed_model_edit)
    reasoning_model_edit = QLineEdit(); reasoning_model_edit.setPlaceholderText("claude-sonnet-5")
    _row(keys_layout, "Reasoning model", "Judges cards against lecture pages and powers the assistant.", reasoning_model_edit)
    transcription_model_edit = QLineEdit(); transcription_model_edit.setPlaceholderText("gpt-4o-mini-transcribe")
    _row(keys_layout, "Transcription model", "Turns lecture audio into per-slide notes.", transcription_model_edit)
```

then the existing `embed_status`/`index_btn` row and the sensitivity slider move under it. `save_embed`:

```python
    def save_embed() -> None:
        if ui_state["syncing"]:
            return
        from . import embeddings
        cfg = _pkg().get_config()
        prev_sig = embeddings.index_signature(cfg)
        had_key = bool(str(cfg.get("api_key_openai") or "").strip())
        cfg["api_key_openai"] = openai_key_edit.text().strip()
        cfg["embedding_model"] = embed_model_edit.text().strip()
        _pkg().write_config(cfg)
        update_embed_status(); rebuild_library_list()
        try:
            from . import index_queue
            index_queue.offer_model_sweep(dlg, prev_sig, first_key=(not had_key and bool(cfg["api_key_openai"])))
        except Exception as exc:
            print(f"[klausmate] model-change sweep offer failed: {exc}")
```

`save_assistant` writes the three keys with `mark_dirty` wiring as the page's other rows. In `index_queue.py`:

```python
def sweep_estimate(names: list[str]) -> "cost.Estimate":
    from . import cost, page_store, pdf_handler
    chars = 0
    try:
        chars += int(mw.col.db.scalar("select coalesce(sum(length(flds)),0) from notes") or 0)
    except Exception:
        pass
    for name in names:
        safe = pdf_handler._safe_basename(name)
        pages = pdf_handler.load_pages(_user_files(), name) or []
        path = pdf_handler.pdf_path_for(_user_files(), safe) or ""
        chars += sum(len(t) for _p, _h, t in page_store.page_texts(_user_files(), safe, path, len(pages)))
    return cost.estimate_embed(chars, embeddings.embedding_model(_cfg()))


def sweep_message(n_pdfs: int, n_notes: int, model: str, estimate: str) -> str:
    pdfs = "1 PDF" if n_pdfs == 1 else f"{n_pdfs:,} PDFs"
    notes = "1 note" if n_notes == 1 else f"{n_notes:,} notes"
    return (f"Re-index everything with {model}?\n\n"
            f"{notes} and {pdfs} will be embedded again from scratch — {estimate}, billed to your OpenAI key.\n\n"
            "You can stop it at any time from the bar at the bottom of the main window.")
```

`offer_model_sweep(parent, previous, first_key=False)`: proceed when `first_key or signature_changed(previous, current)`; `text = sweep_message(len(names), note_count, current[1] or current[0], cost.format_estimate(sweep_estimate(names)))`.

- [ ] **Step 4: Run to verify it passes.** `tests/test_dialog_logic.py`, `tests/test_manage_models_assistant.py`, `tests/test_index_queue.py` → `0 failed`; offscreen: construct the dialog (`manage_models_dialog` under the stubs, as `test_dialog_logic` does) and confirm the page renders. Compile through the symlink.

- [ ] **Step 5: Mutate once.** Drop the estimate from `sweep_message` → the pin fails; restore. Board comment; card stays in Doing.

---

### Task 8: Docs and the full re-baseline

**Files:**
- Modify: `CLAUDE.md` (the intro paragraphs on providers; the module map entries for `embeddings.py`, `pdf_index.py`, `retention.py`, `manage_models.py`, `ollama_*` (delete), `page_ocr` (delete), `setup_flow.py`, the assistant's `page_ocr` sentence → `page_store`; new entries for `page_store.py`, `openai_client.py`, `anthropic_client.py`, `cost.py`; "Deleted" list gains the four modules with today's date), `AGENTS.md` (repository layout, config keys, the privacy paragraph: network calls are OpenAI for embeddings and transcription, Anthropic for the assistant and pertinence), `klausmate/config.md` (final pass), `scripts/mutation_audit.py` (`AUDIT_MODULES` gains `page_store`, `openai_client`, `anthropic_client`, `cost`), `scripts/AUDIT.md` (one line).

- [ ] **Step 1:** grep `CLAUDE.md AGENTS.md klausmate/config.md` for `Voyage|Ollama|ollama|OCR|page_ocr|glm-ocr|runtime_auto_setup|claude_binary|pdf_index_max_chunks|pdf_match_agg|_chunk_text|chunk` and rewrite every hit to the spec's truth; add the four new module entries (one paragraph each: what it owns, its one non-obvious rule: `page_store` "the page is the seam; digest12 over path/size/mtime; segments survive ensure_records"; `openai_client` "stdlib, one retry, key passed in, never logged"; `anthropic_client` "revived a494f2d client; consume_sse finalises tool_use from partial JSON on a dropped stream; complete() for the pertinence phase"; `cost` "estimates, dated prices, four chars per token").
- [ ] **Step 2:** `python3 scripts/mutation_audit.py --modules page_store,cost` must run (the two pure modules) and report no vacuous pins.
- [ ] **Step 3:** Full loop → every file `0 failed`; `grep -rn -i "ollama\|page_ocr\|voyage" CLAUDE.md AGENTS.md klausmate/config.md klausmate/*.py` → only the "Deleted" history lines in CLAUDE.md/AGENTS.md.

---

### Task 9: Integration — loop, a live embed smoke, the checklist (needs-human)

**Files:** none (scratch only).

- [ ] **Step 1:** Full loop on the committed HEAD; per-file table.
- [ ] **Step 2:** `KLAUS_LIVE_API=1` smoke, only if the orchestrator's dispatch says a key is available in the environment as `OPENAI_API_KEY` (never read `meta.json`): embed one 200-character string through `openai_client.embed` and transcribe a generated 3-second 16 kHz silent WAV; report the token/second costs. Without the env var, SKIP and say so.
- [ ] **Step 3:** The live checklist, posted verbatim on the card:
  1. Restart Anki. Open KlausMate Preferences → the page is "API keys & models" with two key fields and three model fields; no Ollama page, no OCR row, no Claude Code binary row.
  2. Paste the OpenAI key and Save → the re-index prompt shows note and PDF counts and a token/dollar estimate; accept.
  3. The bottom status bar shows "Embedding pages…" per PDF; the Library's rows refresh; a PDF's index directory has `manifest.json` version 2 with `pages`.
  4. Right-click a PDF → Show matches in Browse still opens the `!Library` tag search.
  5. Open a PDF in Browse's dock, press Ctrl+Shift+K, ask "what is on this slide?" → the answer cites the page text (no OCR); the Preferences page has no OCR switch.
  6. Reviewer → Lecture panel still jumps to the matched page.
  7. Remove the OpenAI key and Save → drop a PDF onto the deck screen → the refusal names the Preferences page.

## Self-review

**Spec coverage.** D1: Tasks 2, 3, 6, 7 (clients, embeddings, keys page, deletions, gate). D2: Task 1. D3: Task 5. D8: Tasks 4, 7 (estimate + sweep), 6 (`_migrate_config`). Docs: Task 8. Testing list: the pure pins in Tasks 1–5, fixtures in Task 3, the paid smoke behind the flag in Task 9.

**Placeholders.** None — every code step carries its code; docs steps carry the grep list and the paragraph content.

**Type consistency.** `page_store.page_texts` returns `(page_1based, hash, text)` and Task 5 destructures it that way; `pdf_index.pages` is `list[tuple[int, str]]` in Tasks 5 and 7's `sweep_estimate` reads texts from `page_store`, not the index; `openai_client.embed(key, texts, model, dims)` matches `embeddings.OpenAIEmbeddings.embed`'s call; `cost.format_estimate(Estimate)` matches `sweep_message`'s `estimate: str`; `Client.complete` exists for Plan 2's `pertinence.judge`.
