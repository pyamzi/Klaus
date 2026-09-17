"""create_app(): the one place routers, state and logging are wired."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import billing, pages, proxy
from .config import Settings, _truthy
from .db import Store, connect
from .upstream import FakeUpstream, Upstream


def create_app(settings: Settings | None = None, upstream: Any = None, now: Callable[[], float] = time.time) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Klaus Plus", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.store = Store(connect(settings.database_path))
    # K-249: KLAUS_PLUS_FAKE_UPSTREAM=1 runs the whole service with no
    # provider key — local dev and the offline end-to-end. Only when
    # nothing was injected: a test (or a future caller) handing its own
    # upstream must always win over the environment.
    if upstream is not None:
        app.state.upstream = upstream
    elif _truthy(os.environ.get("KLAUS_PLUS_FAKE_UPSTREAM")):
        app.state.upstream = FakeUpstream()
    else:
        app.state.upstream = Upstream(settings)
    app.state.now = now
    app.state.limiter = proxy.RateLimiter(settings.rate_per_minute)
    app.state.log = logging.getLogger("klausplus")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"type": "klaus_plus", "message": str(exc.detail)}
        row = getattr(request.state, "customer", None)
        prefix = (row["key_hash"] or "")[:8] if row is not None else "-"
        app.state.log.info("%s %s %d key=%s", request.method, request.url.path, exc.status_code, prefix)
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    app.include_router(proxy.router)
    app.include_router(billing.router)
    app.include_router(pages.router)
    return app
