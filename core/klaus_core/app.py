"""FastAPI app for klaus-core (Milestone 1).

Run:  .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863

Auth is a shared-secret header for now: X-Klaus-Token must equal
KLAUS_CORE_TOKEN (default "dev"). The service binds localhost only.
"""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, library, notes

app = FastAPI(title="klaus-core", version=__version__)

# The UI arrives from the Vite dev server or the Tauri webview origin; the
# service itself is localhost-only, so wide-open CORS is acceptable here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _expected_token() -> str:
    return os.environ.get("KLAUS_CORE_TOKEN", "dev")


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


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/library")
def get_library():
    return {"library_dirs": library.library_dirs(), "pdfs": library.list_pdfs()}


@app.get("/pdf/{pdf_id}")
def get_pdf(pdf_id: str):
    path = library.pdf_path(pdf_id)
    if path is None:
        raise HTTPException(status_code=404, detail="unknown pdf id")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


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
