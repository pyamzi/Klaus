# Impress-Style PDF Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scrolling PDF viewer with a PowerPoint-style editor — filmstrip left, one slide on a center stage, and a right sidebar of per-slide Markdown notes with pasted images, persisted by klaus-core.

**Architecture:** klaus-core (FastAPI, port 7863) gains a notes/assets storage module and four endpoints writing to KlausBook's own data dir. The `klaus-pdf` extension's webview is restructured: the existing lazy page renderer is extracted into a reusable `PdfPage` component used by both the filmstrip thumbnails and the stage; a `NotesSidebar` edits per-slide Markdown with debounced autosave and image paste/drop.

**Tech Stack:** Python 3.9 stdlib + FastAPI (existing venv), React 19 + pdfjs-dist v6 + esbuild (existing), `marked` (new, MIT) for Markdown preview.

**Spec:** `docs/superpowers/plans/2026-09-17-impress-editor-spec.md`

## Global Constraints

- Repo: `/Users/pyamzi/Documents/Github/KlausBook-Context`. The VS Code fork (`../KlausBook-Code`) is NOT touched by this plan.
- System Python is 3.9: every new Python module starts with `from __future__ import annotations`. Tests are stdlib-only, run as `python3 tests/test_notes.py`.
- No new Python dependencies. `marked` is the ONLY new JS dependency.
- Never write to `~/Documents/Github/Addons/klausmate/user_files/` or any klausmate library dir — klaus-core reads it read-only. All new writes go under `KLAUS_DATA_DIR` (tests: a `mktemp -d` dir; default: `~/Library/Application Support/Klausbook/`).
- Do NOT edit `core/klaus_core/library.py` or the repo README's run commands — a parallel session (task_0a771180) is fixing stale paths there. Rebase/pull before starting; Task 6 only APPENDS a README section.
- Webview CSP: no external resources; workers via `blob:` only; scripts by nonce. Extension build/typecheck: `npm run build` and `npx tsc --noEmit` from `extensions/klaus-pdf/`.
- Commits: plain `git add <paths>` + message ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

- Create: `core/klaus_core/notes.py` — notes + asset storage (validation, atomic writes)
- Create: `tests/test_notes.py` — storage suite (scratch dir via `KLAUS_DATA_DIR`)
- Modify: `core/klaus_core/app.py` — 4 endpoints + token middleware query-param case
- Create: `extensions/klaus-pdf/webview-src/PdfPage.tsx` — one rendered page (extracted from PdfViewer)
- Create: `extensions/klaus-pdf/webview-src/ImpressView.tsx` — filmstrip + stage + sidebar layout
- Create: `extensions/klaus-pdf/webview-src/NotesSidebar.tsx` — Markdown notes editor
- Modify: `extensions/klaus-pdf/webview-src/core.ts` — notes/asset client functions
- Modify: `extensions/klaus-pdf/webview-src/index.tsx` — render ImpressView
- Modify: `extensions/klaus-pdf/webview-src/viewer.css` — impress layout styles
- Modify: `extensions/klaus-pdf/src/extension.ts` — CSP `img-src` gains the core URL
- Delete: `extensions/klaus-pdf/webview-src/PdfViewer.tsx` (absorbed by PdfPage + ImpressView)

---

### Task 1: Notes storage module (klaus-core)

**Files:**
- Create: `core/klaus_core/notes.py`
- Test: `tests/test_notes.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces (used by Task 2): `notes.load_notes(pdf_id: str) -> dict`, `notes.save_notes(pdf_id: str, doc: dict) -> None`, `notes.save_asset(pdf_id: str, data: bytes, ext: str) -> str`, `notes.asset_path(pdf_id: str, name: str) -> Optional[Path]`, `notes.data_dir() -> Path`. Bad ids/shapes raise `ValueError`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_notes.py`:

```python
"""klaus-core notes/assets storage suite.

Runs against a scratch data dir via KLAUS_DATA_DIR so the real one is
never touched. Run: python3 tests/test_notes.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["KLAUS_DATA_DIR"] = tempfile.mkdtemp(prefix="klaus-notes-test-")
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from klaus_core import notes  # noqa: E402

PDF_ID = "0123456789abcdef"
failures = 0


def check(label, ok, detail=""):
    global failures
    if ok:
        print("  ok  " + label)
    else:
        failures += 1
        print(" FAIL " + label + ((" " + str(detail)) if detail else ""))


def raises_value_error(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


print("== notes round trip ==")
check("missing notes load as empty doc",
      notes.load_notes(PDF_ID) == {"version": 1, "pages": {}})
doc = {"version": 1, "pages": {"3": {"md": "renal **stuff**"}}}
notes.save_notes(PDF_ID, doc)
check("saved notes round-trip", notes.load_notes(PDF_ID) == doc)
notes.save_notes(PDF_ID, {"version": 1, "pages": {}})
check("overwrite works", notes.load_notes(PDF_ID) == {"version": 1, "pages": {}})

print("== validation ==")
for bad_id in ("../../etc", "0123456789ABCDEF", "0123", ""):
    check("bad pdf id rejected: %r" % bad_id,
          raises_value_error(lambda b=bad_id: notes.load_notes(b)))
check("bad doc shape rejected",
      raises_value_error(lambda: notes.save_notes(PDF_ID, {"pages": "nope"})))
check("non-dict doc rejected",
      raises_value_error(lambda: notes.save_notes(PDF_ID, ["x"])))

print("== assets ==")
name = notes.save_asset(PDF_ID, b"\x89PNGfake", "png")
check("asset name is content-addressed",
      name == notes.save_asset(PDF_ID, b"\x89PNGfake", "png"), name)
p = notes.asset_path(PDF_ID, name)
check("asset readable back", p is not None and p.read_bytes() == b"\x89PNGfake")
check("different bytes, different name",
      notes.save_asset(PDF_ID, b"other", "png") != name)
check("traversal name refused", notes.asset_path(PDF_ID, "../x.png") is None)
check("unknown asset 404s", notes.asset_path(PDF_ID, "f" * 16 + ".png") is None)
check("bad extension rejected",
      raises_value_error(lambda: notes.save_asset(PDF_ID, b"x", "svg")))

print("\n%d failures" % failures)
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/pyamzi/Documents/Github/KlausBook-Context && python3 tests/test_notes.py`
Expected: FAIL with `ImportError`/`ModuleNotFoundError: ... notes`

- [ ] **Step 3: Write the implementation**

Create `core/klaus_core/notes.py`:

```python
"""Per-PDF notes and pasted-image assets, in KlausBook's own data dir.

Notes are one JSON document per PDF (keyed by the library's pdf id) with
per-page markdown. Assets are content-addressed image files. Nothing here
touches the klausmate library — that stays read-only. Ids and asset names
are regex-validated so a crafted id can never escape the data dir.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ASSET_RE = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")
_ASSET_EXTS = ("png", "jpg", "gif", "webp")


def data_dir() -> Path:
    override = os.environ.get("KLAUS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library/Application Support/Klausbook"


def _require_id(pdf_id: str) -> str:
    if not _ID_RE.match(pdf_id or ""):
        raise ValueError("bad pdf id: %r" % (pdf_id,))
    return pdf_id


def _notes_path(pdf_id: str) -> Path:
    return data_dir() / "notes" / (_require_id(pdf_id) + ".json")


def load_notes(pdf_id: str) -> dict:
    try:
        with open(_notes_path(pdf_id), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"version": 1, "pages": {}}


def save_notes(pdf_id: str, doc: dict) -> None:
    if not isinstance(doc, dict) or not isinstance(doc.get("pages"), dict):
        raise ValueError("notes doc must be a dict with a 'pages' dict")
    path = _notes_path(pdf_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_asset(pdf_id: str, data: bytes, ext: str) -> str:
    if ext not in _ASSET_EXTS:
        raise ValueError("bad asset extension: %r" % (ext,))
    name = hashlib.sha1(data).hexdigest()[:16] + "." + ext
    root = data_dir() / "assets" / _require_id(pdf_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if not path.exists():
        path.write_bytes(data)
    return name


def asset_path(pdf_id: str, name: str) -> Optional[Path]:
    if not _ASSET_RE.match(name or ""):
        return None
    path = data_dir() / "assets" / _require_id(pdf_id) / name
    return path if path.is_file() else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_notes.py`
Expected: all `ok`, exit 0, `0 failures`

- [ ] **Step 5: Commit**

```bash
git add core/klaus_core/notes.py tests/test_notes.py
git commit -m "klaus-core: notes + image asset storage (KLAUS_DATA_DIR)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Notes and asset HTTP endpoints

**Files:**
- Modify: `core/klaus_core/app.py`

**Interfaces:**
- Consumes: Task 1's `notes` module.
- Produces (used by Tasks 4–5): `GET /notes/{pdf_id}` → notes doc JSON; `PUT /notes/{pdf_id}` (JSON body) → `{"ok": true}`; `POST /assets/{pdf_id}` (raw image body, Content-Type png/jpeg/gif/webp, ≤8 MB) → `{"name": "..."}`; `GET /assets/{pdf_id}/{name}` → image bytes, accepting `?token=` in place of the `X-Klaus-Token` header (only on asset GETs — `<img>` cannot send headers).

- [ ] **Step 1: Extend the token middleware and imports**

In `core/klaus_core/app.py`, change the import line `from . import __version__, library` to:

```python
from . import __version__, library, notes
```

Replace the body of the `require_token` middleware function with:

```python
@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.method != "OPTIONS" and request.url.path != "/health":
        supplied = request.headers.get("X-Klaus-Token")
        if (supplied is None and request.method == "GET"
                and request.url.path.startswith("/assets/")):
            # <img> tags cannot send headers; allow ?token= on asset reads.
            supplied = request.query_params.get("token")
        if supplied != _expected_token():
            return JSONResponse({"detail": "invalid or missing X-Klaus-Token"}, status_code=401)
    return await call_next(request)
```

- [ ] **Step 2: Add the four endpoints**

Append to `core/klaus_core/app.py`:

```python
_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg",
              "image/gif": "gif", "image/webp": "webp"}
MAX_ASSET_BYTES = 8 * 1024 * 1024


@app.get("/notes/{pdf_id}")
def get_notes(pdf_id: str):
    try:
        return notes.load_notes(pdf_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/notes/{pdf_id}")
async def put_notes(pdf_id: str, request: Request):
    try:
        notes.save_notes(pdf_id, await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/assets/{pdf_id}")
async def post_asset(pdf_id: str, request: Request):
    ext = _IMAGE_EXT.get(request.headers.get("content-type", ""))
    if ext is None:
        raise HTTPException(status_code=415, detail="content-type must be png/jpeg/gif/webp")
    data = await request.body()
    if not data or len(data) > MAX_ASSET_BYTES:
        raise HTTPException(status_code=413, detail="empty or oversized image")
    try:
        return {"name": notes.save_asset(pdf_id, data, ext)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/assets/{pdf_id}/{name}")
def get_asset(pdf_id: str, name: str):
    try:
        path = notes.asset_path(pdf_id, name)
    except ValueError:
        path = None
    if path is None:
        raise HTTPException(status_code=404, detail="unknown asset")
    return FileResponse(path)
```

- [ ] **Step 3: Verify end to end with curl**

```bash
cd /Users/pyamzi/Documents/Github/KlausBook-Context/core
export KLAUS_DATA_DIR=$(mktemp -d)
.venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7899 &
SERVER=$!; sleep 2
ID=0123456789abcdef
curl -sf -X PUT -H "X-Klaus-Token: dev" -H "Content-Type: application/json" \
  -d '{"version":1,"pages":{"2":{"md":"hi"}}}' localhost:7899/notes/$ID
curl -sf -H "X-Klaus-Token: dev" localhost:7899/notes/$ID | grep '"hi"'
printf '\x89PNGfake' > /tmp/klaus-fake.png
NAME=$(curl -sf -X POST -H "X-Klaus-Token: dev" -H "Content-Type: image/png" \
  --data-binary @/tmp/klaus-fake.png localhost:7899/assets/$ID | python3 -c "import json,sys;print(json.load(sys.stdin)['name'])")
curl -sf "localhost:7899/assets/$ID/$NAME?token=dev" -o /dev/null && echo "asset via query token OK"
curl -s -o /dev/null -w "%{http_code}\n" "localhost:7899/assets/$ID/$NAME"   # expect 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Klaus-Token: dev" "localhost:7899/notes/../etc" # expect 400 or 404
kill $SERVER; rm /tmp/klaus-fake.png
```

Expected: both `-sf` chains succeed, "asset via query token OK" prints, the no-token asset GET prints `401`.

- [ ] **Step 4: Run the storage suite again (regression)**

Run: `cd .. && python3 tests/test_notes.py && python3 tests/test_board.py`
Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add core/klaus_core/app.py
git commit -m "klaus-core: /notes and /assets endpoints (query-token for asset GETs)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Impress layout — PdfPage, filmstrip, stage

**Files:**
- Create: `extensions/klaus-pdf/webview-src/PdfPage.tsx`
- Create: `extensions/klaus-pdf/webview-src/ImpressView.tsx`
- Modify: `extensions/klaus-pdf/webview-src/index.tsx`
- Modify: `extensions/klaus-pdf/webview-src/viewer.css`
- Delete: `extensions/klaus-pdf/webview-src/PdfViewer.tsx`

**Interfaces:**
- Consumes: `fetchPdfBytes(id)` from `core.ts` (existing); pdfjs (`GlobalWorkerOptions.workerSrc` is already set by `index.tsx` before render).
- Produces: `PdfPage` component `{ doc: PDFDocumentProxy; pageNumber: number; scale: number; baseWidth: number; baseHeight: number; textLayer?: boolean }` (used by Task 3's own filmstrip/stage); `ImpressView` `{ pdfId: string; name: string }` root component. ImpressView renders `<div className="impress-sidebar-slot" />` where Task 4 mounts the sidebar.

- [ ] **Step 1: Create PdfPage.tsx (extraction of the `Page` component from PdfViewer.tsx)**

The render machinery (fresh-canvas swap, IntersectionObserver laziness, cancellation) is proven — move it verbatim, adding only the `textLayer` flag:

```tsx
import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";

interface PdfPageProps {
  doc: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
  baseWidth: number;
  baseHeight: number;
  textLayer?: boolean;
}

function isCancelled(e: unknown): boolean {
  return e instanceof Error && e.name === "RenderingCancelledException";
}

export default function PdfPage({ doc, pageNumber, scale, baseWidth, baseHeight, textLayer = true }: PdfPageProps) {
  const holderRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return;
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
      { rootMargin: "800px 0px" },
    );
    observer.observe(holder);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let renderTask: ReturnType<
      Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]
    > | null = null;

    (async () => {
      try {
        const page = await doc.getPage(pageNumber);
        if (cancelled) return;
        const host = canvasHostRef.current;
        const textDiv = textRef.current;
        if (!host || !textDiv) return;

        // Render into a fresh canvas and swap it in when done: no
        // canvas-reuse conflicts (StrictMode, rapid zoom) and no flicker.
        const viewport = page.getViewport({ scale });
        const dpr = window.devicePixelRatio || 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        renderTask = page.render({
          canvas,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        await renderTask.promise;
        if (cancelled) return;
        host.replaceChildren(canvas);

        textDiv.replaceChildren();
        if (textLayer) {
          textDiv.style.setProperty("--scale-factor", String(viewport.scale));
          textDiv.style.width = `${viewport.width}px`;
          textDiv.style.height = `${viewport.height}px`;
          await new pdfjs.TextLayer({
            textContentSource: page.streamTextContent(),
            container: textDiv,
            viewport,
          }).render();
        }
      } catch (e) {
        if (!cancelled && !isCancelled(e)) {
          console.error(`[klaus] page ${pageNumber} render failed:`, e);
        }
      }
    })();

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [doc, pageNumber, scale, visible, textLayer]);

  return (
    <div
      ref={holderRef}
      className="pdf-page"
      style={{ width: baseWidth * scale, height: baseHeight * scale }}
      data-page={pageNumber}
    >
      <div ref={canvasHostRef} className="pdf-page-canvas" />
      <div ref={textRef} className="textLayer" />
    </div>
  );
}
```

- [ ] **Step 2: Create ImpressView.tsx**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import PdfPage from "./PdfPage";
import { fetchPdfBytes } from "./core";

const THUMB_WIDTH = 140;
const STAGE_PADDING = 32;

interface ImpressViewProps {
  pdfId: string;
  name: string;
}

export default function ImpressView({ pdfId, name }: ImpressViewProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [baseSize, setBaseSize] = useState<{ w: number; h: number } | null>(null);
  const [current, setCurrent] = useState(1);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const fitScale = useCallback((size: { w: number; h: number }) => {
    const stage = stageRef.current;
    if (!stage) return 1;
    return Math.max(
      0.1,
      Math.min(
        (stage.clientWidth - STAGE_PADDING * 2) / size.w,
        (stage.clientHeight - STAGE_PADDING * 2) / size.h,
      ),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    setDoc(null);
    setBaseSize(null);
    setError(null);
    setCurrent(1);

    (async () => {
      try {
        const data = await fetchPdfBytes(pdfId);
        task = pdfjs.getDocument({ data });
        const loaded = await task.promise;
        if (cancelled) return;
        const first = await loaded.getPage(1);
        const viewport = first.getViewport({ scale: 1 });
        if (cancelled) return;
        const size = { w: viewport.width, h: viewport.height };
        setBaseSize(size);
        setScale(fitScale(size));
        setDoc(loaded);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      task?.destroy();
    };
  }, [pdfId, fitScale]);

  // Refit when the panel resizes.
  useEffect(() => {
    if (!baseSize) return;
    const onResize = () => setScale(fitScale(baseSize));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [baseSize, fitScale]);

  // Keep a ref of `current` so the keydown handler need not re-bind per slide.
  const currentRef = useRef(current);
  currentRef.current = current;

  // Keyboard slide navigation, unless typing in the notes sidebar.
  useEffect(() => {
    if (!doc) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable) return;
      const last = doc.numPages;
      const go = (n: number) => {
        setCurrent(Math.min(Math.max(n, 1), last));
        e.preventDefault();
      };
      if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "PageDown") go(currentRef.current + 1);
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp" || e.key === "PageUp") go(currentRef.current - 1);
      else if (e.key === "Home") go(1);
      else if (e.key === "End") go(last);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc]);

  const zoom = (factor: number) =>
    setScale((s) => Math.min(6, Math.max(0.1, s * factor)));

  if (error) {
    return <div className="viewer-message">Could not open {name}: {error}</div>;
  }
  if (!doc || !baseSize) {
    return <div className="viewer-message">Opening {name}…</div>;
  }

  const thumbScale = THUMB_WIDTH / baseSize.w;
  return (
    <div className="impress">
      <div className="filmstrip">
        {Array.from({ length: doc.numPages }, (_, i) => {
          const n = i + 1;
          return (
            <button
              key={n}
              className={n === current ? "thumb selected" : "thumb"}
              onClick={() => setCurrent(n)}
            >
              <PdfPage
                doc={doc}
                pageNumber={n}
                scale={thumbScale}
                baseWidth={baseSize.w}
                baseHeight={baseSize.h}
                textLayer={false}
              />
              <span className="thumb-num">{n}</span>
            </button>
          );
        })}
      </div>
      <div className="stage-column">
        <div className="viewer-toolbar">
          <span className="viewer-title" title={name}>{name}</span>
          <span className="viewer-pages">{current} / {doc.numPages}</span>
          <div className="viewer-zoom">
            <button onClick={() => zoom(1 / 1.2)} title="Zoom out">−</button>
            <span>{Math.round(scale * 100)}%</span>
            <button onClick={() => zoom(1.2)} title="Zoom in">+</button>
            <button onClick={() => setScale(fitScale(baseSize))} title="Fit slide">Fit</button>
          </div>
        </div>
        <div className="stage" ref={stageRef}>
          <PdfPage
            key={`stage-${current}`}
            doc={doc}
            pageNumber={current}
            scale={scale}
            baseWidth={baseSize.w}
            baseHeight={baseSize.h}
            textLayer
          />
        </div>
      </div>
      <div className="impress-sidebar-slot" data-pdf-id={pdfId} data-page={current} />
    </div>
  );
}
```


- [ ] **Step 3: Point index.tsx at ImpressView and delete PdfViewer.tsx**

In `index.tsx`, replace `import PdfViewer from "./PdfViewer";` with `import ImpressView from "./ImpressView";` and the render call with:

```tsx
  createRoot(document.getElementById("root")!).render(
    <ImpressView pdfId={cfg.pdfId} name={cfg.name} />,
  );
```

Then `git rm extensions/klaus-pdf/webview-src/PdfViewer.tsx`.

- [ ] **Step 4: Replace the layout section of viewer.css**

Keep `* { box-sizing }`, the `html/body/#root` block, `.viewer-toolbar/.viewer-title/.viewer-pages/.viewer-zoom` blocks, `.viewer-message`, `.pdf-page`, `.pdf-page-canvas canvas`, and the whole `.textLayer` section. Delete `.viewer`, `.viewer-scroll`, `.viewer-pages-column`. Change the `#root` rule's `flex-direction` to `row`, and add:

```css
.impress {
  display: flex;
  flex: 1;
  min-width: 0;
  height: 100%;
}

.filmstrip {
  width: 168px;
  flex-shrink: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #35373d;
}

.thumb {
  position: relative;
  padding: 3px;
  border: 2px solid transparent;
  border-radius: 6px;
  background: none;
  cursor: pointer;
}

.thumb.selected {
  border-color: #5b8def;
}

.thumb .pdf-page {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}

.thumb-num {
  position: absolute;
  left: 6px;
  bottom: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.55);
  color: #d7d8dd;
  font-size: 11px;
}

.stage-column {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.stage {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: auto;
  padding: 32px;
}

.impress-sidebar-slot {
  flex-shrink: 0;
}
```

- [ ] **Step 5: Build, typecheck**

Run: `cd extensions/klaus-pdf && npm run build && npx tsc --noEmit`
Expected: `[klaus-pdf] built`, tsc silent.

- [ ] **Step 6: Commit**

```bash
git add -A extensions/klaus-pdf/webview-src
git commit -m "klaus-pdf: Impress layout — filmstrip + slide stage (PdfPage extraction)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(`-A` on that path also stages the PdfViewer.tsx deletion; `out/` is gitignored.)

---

### Task 4: NotesSidebar — per-slide Markdown with autosave

**Files:**
- Create: `extensions/klaus-pdf/webview-src/NotesSidebar.tsx`
- Modify: `extensions/klaus-pdf/webview-src/core.ts`
- Modify: `extensions/klaus-pdf/webview-src/ImpressView.tsx` (mount sidebar in the slot)
- Modify: `extensions/klaus-pdf/webview-src/viewer.css`
- Modify: `extensions/klaus-pdf/package.json` (add `marked`)

**Interfaces:**
- Consumes: Task 2's `GET/PUT /notes/{pdf_id}`; Task 3's `impress-sidebar-slot` position in ImpressView.
- Produces: `NotesSidebar` component `{ pdfId: string; page: number }`; `core.ts` gains `fetchNotes(id: string): Promise<NotesDoc>`, `saveNotes(id: string, doc: NotesDoc): Promise<void>`, and `export interface NotesDoc { version: number; pages: Record<string, { md: string }> }` (Task 5 adds the asset functions).

- [ ] **Step 1: Install marked**

Run: `cd extensions/klaus-pdf && npm install --no-fund --no-audit marked`

- [ ] **Step 2: Add the notes client to core.ts**

Append to `core.ts`:

```ts
export interface NotesDoc {
  version: number;
  pages: Record<string, { md: string }>;
}

export async function fetchNotes(id: string): Promise<NotesDoc> {
  const res = await request(`/notes/${id}`);
  return res.json();
}

export async function saveNotes(id: string, doc: NotesDoc): Promise<void> {
  const res = await fetch(`${BASE}/notes/${id}`, {
    method: "PUT",
    headers: { "X-Klaus-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(doc),
  });
  if (!res.ok) {
    throw new Error(`klaus-core PUT /notes/${id} failed: ${res.status}`);
  }
}
```

- [ ] **Step 3: Create NotesSidebar.tsx**

```tsx
import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import { fetchNotes, saveNotes, type NotesDoc } from "./core";

const SAVE_DEBOUNCE_MS = 800;

interface NotesSidebarProps {
  pdfId: string;
  page: number;
}

type SaveState = "saved" | "saving" | "error";

export default function NotesSidebar({ pdfId, page }: NotesSidebarProps) {
  const [doc, setDoc] = useState<NotesDoc | null>(null);
  const [preview, setPreview] = useState(false);
  const [status, setStatus] = useState<SaveState>("saved");
  const [loadError, setLoadError] = useState<string | null>(null);
  const docRef = useRef<NotesDoc | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchNotes(pdfId)
      .then((d) => {
        if (cancelled) return;
        docRef.current = d;
        setDoc(d);
      })
      .catch((e) => !cancelled && setLoadError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [pdfId]);

  const flush = async () => {
    timerRef.current = undefined;
    const d = docRef.current;
    if (!d) return;
    try {
      await saveNotes(pdfId, d);
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  };

  // Flush a pending edit when the panel goes away.
  useEffect(() => {
    return () => {
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
        void flush();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const md = doc?.pages[String(page)]?.md ?? "";

  const update = (text: string) => {
    if (!docRef.current) return;
    const next: NotesDoc = {
      ...docRef.current,
      pages: { ...docRef.current.pages, [String(page)]: { md: text } },
    };
    docRef.current = next;
    setDoc(next);
    setStatus("saving");
    if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => void flush(), SAVE_DEBOUNCE_MS);
  };

  if (loadError) {
    return (
      <aside className="notes-sidebar">
        <div className="notes-header">Slide {page}</div>
        <div className="notes-error">Notes unavailable: {loadError}</div>
      </aside>
    );
  }

  return (
    <aside className="notes-sidebar">
      <div className="notes-header">
        <span>Slide {page}</span>
        <span className={`notes-status notes-status-${status}`}>
          {status === "saving" ? "Saving…" : status === "error" ? "Save failed" : "Saved"}
        </span>
        <button className="notes-toggle" onClick={() => setPreview((p) => !p)}>
          {preview ? "Edit" : "Preview"}
        </button>
      </div>
      {preview ? (
        <div
          className="notes-preview"
          // Scripts injected via note HTML cannot run: the webview CSP only
          // allows nonce'd scripts. This is the user's own local content.
          dangerouslySetInnerHTML={{ __html: marked.parse(md, { async: false }) as string }}
        />
      ) : (
        <textarea
          ref={textRef}
          className="notes-input"
          placeholder="Notes for this slide… (Markdown)"
          value={md}
          disabled={doc === null}
          onChange={(e) => update(e.target.value)}
        />
      )}
    </aside>
  );
}
```

- [ ] **Step 4: Mount it in ImpressView**

In `ImpressView.tsx`, add `import NotesSidebar from "./NotesSidebar";` and replace the slot div with:

```tsx
      <NotesSidebar pdfId={pdfId} page={current} />
```

(Also remove the now-unused `.impress-sidebar-slot` CSS rule; the sidebar itself is the third column.)

- [ ] **Step 5: Sidebar styles**

Append to `viewer.css`:

```css
.notes-sidebar {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #2a2b31;
  border-left: 1px solid #4a4c55;
}

.notes-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: #d7d8dd;
  font-size: 13px;
}

.notes-header > span:first-child {
  flex: 1;
  font-weight: 600;
}

.notes-status {
  font-size: 11px;
  color: #8b8d98;
}

.notes-status-error {
  color: #f2b8bd;
}

.notes-toggle {
  padding: 2px 10px;
  border: 1px solid #4a4c55;
  border-radius: 6px;
  background: #34353c;
  color: #d7d8dd;
  font-size: 12px;
  cursor: pointer;
}

.notes-input {
  flex: 1;
  margin: 0 10px 10px;
  padding: 10px;
  border: 1px solid #4a4c55;
  border-radius: 8px;
  background: #1e1f24;
  color: #e8e8ea;
  font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  resize: none;
}

.notes-preview {
  flex: 1;
  overflow-y: auto;
  margin: 0 10px 10px;
  padding: 10px;
  border-radius: 8px;
  background: #1e1f24;
  color: #e8e8ea;
  font-size: 13px;
  line-height: 1.5;
}

.notes-preview img {
  max-width: 100%;
  border-radius: 4px;
}

.notes-error {
  margin: 10px;
  padding: 10px;
  border-radius: 8px;
  background: #3a2326;
  color: #f2b8bd;
  font-size: 12.5px;
}
```

- [ ] **Step 6: Build, typecheck, and verify persistence with curl**

```bash
cd extensions/klaus-pdf && npm run build && npx tsc --noEmit
```

Expected: built + silent tsc. Persistence path was proven by Task 2's curl; the UI wiring is verified by the human checklist in Task 6.

- [ ] **Step 7: Commit**

```bash
git add extensions/klaus-pdf/webview-src extensions/klaus-pdf/package.json extensions/klaus-pdf/package-lock.json
git commit -m "klaus-pdf: per-slide Markdown notes sidebar with debounced autosave

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Image paste/drop into notes

**Files:**
- Modify: `extensions/klaus-pdf/webview-src/core.ts`
- Modify: `extensions/klaus-pdf/webview-src/NotesSidebar.tsx`
- Modify: `extensions/klaus-pdf/src/extension.ts`

**Interfaces:**
- Consumes: Task 2's `POST /assets/{pdf_id}` and query-token asset GET; Task 4's `NotesSidebar` and `update()`.
- Produces: `core.ts` gains `uploadAsset(id: string, blob: Blob): Promise<string>` (returns the asset name) and `assetUrl(id: string, name: string): string`.

- [ ] **Step 1: Add the asset client to core.ts**

Append:

```ts
export async function uploadAsset(id: string, blob: Blob): Promise<string> {
  const res = await fetch(`${BASE}/assets/${id}`, {
    method: "POST",
    headers: { "X-Klaus-Token": TOKEN, "Content-Type": blob.type },
    body: blob,
  });
  if (!res.ok) {
    throw new Error(`klaus-core POST /assets/${id} failed: ${res.status}`);
  }
  return (await res.json()).name as string;
}

export function assetUrl(id: string, name: string): string {
  // <img> tags cannot send headers, so asset GETs carry the token in the query.
  return `${BASE}/assets/${id}/${name}?token=${encodeURIComponent(TOKEN)}`;
}
```

- [ ] **Step 2: Wire paste and drop in NotesSidebar.tsx**

Add to the imports: `import { assetUrl, uploadAsset } from "./core";` (merge into the existing `./core` import). Inside the component add:

```tsx
  const insertImage = async (file: Blob) => {
    if (!file.type.startsWith("image/")) return;
    setStatus("saving");
    try {
      const name = await uploadAsset(pdfId, file);
      const ref = `![](${assetUrl(pdfId, name)})`;
      const el = textRef.current;
      const at = el ? el.selectionStart : md.length;
      update(md.slice(0, at) + ref + md.slice(at));
    } catch {
      setStatus("error");
    }
  };
```

And give the `<textarea>` the two handlers:

```tsx
          onPaste={(e) => {
            const file = Array.from(e.clipboardData.items)
              .find((i) => i.type.startsWith("image/"))?.getAsFile();
            if (file) {
              e.preventDefault();
              void insertImage(file);
            }
          }}
          onDrop={(e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith("image/")) {
              e.preventDefault();
              void insertImage(file);
            }
          }}
```

- [ ] **Step 3: Let the webview load images from klaus-core**

In `src/extension.ts`, in `pdfPanelHtml`'s `csp` array, change the img-src line to:

```ts
    `img-src ${webview.cspSource} ${CORE_URL} blob: data:`,
```

- [ ] **Step 4: Build and typecheck**

Run: `cd extensions/klaus-pdf && npm run build && npx tsc --noEmit`
Expected: built + silent.

- [ ] **Step 5: Commit**

```bash
git add extensions/klaus-pdf/webview-src/core.ts extensions/klaus-pdf/webview-src/NotesSidebar.tsx extensions/klaus-pdf/src/extension.ts
git commit -m "klaus-pdf: paste/drop images into slide notes (assets via klaus-core)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Integration — docs and the human verification pass

**Files:**
- Modify: `README.md` (append a section only — a parallel session may be editing its run commands)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing downstream; this is the ship gate.

- [ ] **Step 1: Append to README.md, after the "Run (dev)" section**

```markdown
## The PDF editor

Opening a PDF from the Library shows an Impress-style editor: a filmstrip
of slide thumbnails (click or Arrow/PageUp/PageDown/Home/End to navigate),
the current slide on the stage (zoom −/+/Fit), and a notes sidebar on the
right. Notes are per-slide Markdown with an Edit/Preview toggle; paste or
drop an image to embed it. Everything autosaves to klaus-core under
`~/Library/Application Support/Klausbook/` (`KLAUS_DATA_DIR` overrides;
tests use a scratch dir). The klausmate library itself is never written.
```

- [ ] **Step 2: Full automated regression**

```bash
cd /Users/pyamzi/Documents/Github/KlausBook-Context
for t in tests/test_*.py; do python3 "$t" || break; done
cd extensions/klaus-pdf && npm run build && npx tsc --noEmit
```

Expected: every suite exits 0; build + typecheck clean.

- [ ] **Step 3: Human verification checklist (requires the app)**

Start core (`cd core && .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863`), launch KlausBook (`cd ../KlausBook-Code && fnm exec --using=v24.18.0 ./scripts/code.sh --extensionDevelopmentPath="$HOME/Documents/Github/KlausBook-Context/extensions/klaus-pdf"`), then confirm:

- [ ] Opening a PDF shows filmstrip + stage + notes sidebar; no scroll viewer.
- [ ] Clicking thumbnails and pressing arrows/PageUp/PageDown/Home/End changes the slide; the filmstrip highlight follows.
- [ ] Arrow keys while typing in the notes textarea move the text cursor, not the slide.
- [ ] Zoom −/+/Fit work; resizing the panel refits the slide.
- [ ] Text on the stage slide is selectable.
- [ ] Type notes on slides 1 and 3 → indicator shows Saving… then Saved; Preview renders the Markdown.
- [ ] Paste a screenshot into a note → `![](…)` appears; Preview shows the image.
- [ ] Quit the window entirely, relaunch → notes and image are still there on the right slides.
- [ ] `ls "$HOME/Library/Application Support/Klausbook/notes"` shows one JSON per annotated PDF; the klausmate library dir's mtimes are unchanged.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "README: document the Impress-style PDF editor

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Board sync (orchestrator, optional)**

This plan delivers the layout half of KB-003 and the notes-storage
foundation KB-002 will bake from. Record it so the board reflects reality:

```bash
python3 board/board.py comment KB-003 --author orchestrator --text "Impress layout + per-slide notes sidebar shipped via docs/superpowers/plans/2026-09-17-impress-editor.md; remaining scope of this card is highlights/overlay objects on the canvas."
python3 board/board.py comment KB-002 --author orchestrator --text "Notes/assets storage + endpoints now exist in klaus-core (notes.py); this card's bake work should read from that store."
```
