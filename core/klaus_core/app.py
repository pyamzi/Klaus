"""FastAPI app for klaus-core (Milestone 1).

Run:  .venv/bin/uvicorn klaus_core.app:app --host 127.0.0.1 --port 7863

Auth is a shared-secret header for now: X-Klaus-Token must equal
KLAUS_CORE_TOKEN (default "dev"). The service binds localhost only.
"""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, library

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
        if request.headers.get("X-Klaus-Token") != _expected_token():
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
