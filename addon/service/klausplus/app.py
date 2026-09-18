"""create_app(): the one place routers, state and logging are wired."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, billing, pages, proxy
from .config import Settings, _truthy
from .db import Store, connect
from .upstream import FakeUpstream, Upstream


PURGE_INTERVAL_S = 24 * 3600


def purge_once(app: FastAPI) -> None:
    """One retention pass, logged. K-263: this is how `/privacy`'s promise is kept
    without a scheduler — one Fly Machine, no cron (see README), so the app runs it.
    It never raises: a broken purge must not take the service down."""
    try:
        s = app.state.settings
        c = app.state.store.purge_expired(app.state.now(), usage_days=s.retention_usage_days,
                                          customer_grace_days=s.retention_customer_grace_days)
        app.state.log.info("purge usage=%d daily_audio=%d events=%d customers=%d",
                           c["usage"], c["daily_audio"], c["events"], c["customers"])
    except Exception as exc:
        app.state.log.warning("purge failed: %s", exc.__class__.__name__)


async def _purge_loop(app: FastAPI) -> None:
    while True:
        # ponytail: on the event loop -- a handful of DELETEs on one machine's SQLite
        # file, once a day. asyncio.to_thread it if that ever stops being true.
        purge_once(app)
        await asyncio.sleep(PURGE_INTERVAL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_purge_loop(app))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task  # let it process the cancellation, or the closing loop warns
        # K-271: `Upstream` owns a pooled httpx.AsyncClient — leave it open and its
        # connections leak and warn on the way out. An injected fake (or the bare
        # `object()` half the suite passes) has no aclose, and must still shut down.
        closer = getattr(app.state.upstream, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception as exc:  # a failing close must not turn shutdown into a crash
                print(f"[klausplus] upstream close failed: {type(exc).__name__}")


def create_app(settings: Settings | None = None, upstream: Any = None, now: Callable[[], float] = time.time) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Klaus Plus", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
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
    app.include_router(auth.router)
    app.include_router(pages.router)
    return app
