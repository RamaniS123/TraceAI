"""Application lifecycle and the Phase 3 HTTP interface."""
from contextlib import asynccontextmanager
from importlib.resources import files
import json

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DataError, SQLAlchemyError
import simplejson

from traceai.auth import require_access, require_reset
from traceai.config import Settings
from traceai.db import create_database_engine, session_factory
from traceai.errors import APIError
from traceai.events import get_interaction, reset_events, store_event
from traceai.requests import parse_body
from traceai.schemas import EventInput, ResetRequest
from traceai.testing_interface import init_state, system_router, tester_router


def json_response(body, status=200):
    # Preserve JSON numeric precision when reading JSONB Decimal values.
    return Response(simplejson.dumps(body, use_decimal=True, allow_nan=False), status_code=status, media_type="application/json")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="TraceAI", version="0.1.0", lifespan=lifespan)
    assets = files("traceai").joinpath("static")
    app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def homepage():
        return HTMLResponse(assets.joinpath("index.html").read_text(), headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        })

    app.state.engine = engine
    app.state.settings = settings
    app.state.sessions = session_factory(engine)
    # Course cross-team testing interface: the system's /test endpoints at the root and
    # the deployed tester under /tester (see docs/testing-interface.md).
    init_state(app)
    app.include_router(system_router)
    app.include_router(tester_router, prefix="/tester")
    # Serve the reviewed contract in /docs, including conditional payload rules.
    # tools/validate_contract.py checks this wheel-bundled copy for exact parity.
    app.openapi = lambda: json.loads(files("traceai").joinpath("openapi.json").read_text())

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(status_code=exc.status, content=exc.body(), headers=headers)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        message = {404: "Route was not found.", 405: "Method is not allowed."}.get(exc.status_code, "Request could not be processed.")
        return JSONResponse(status_code=exc.status_code, content=APIError(exc.status_code, code, message).body(), headers=exc.headers)

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request, exc):
        # Intentionally omit database URLs, statements, parameters, and stack traces.
        return JSONResponse(status_code=503, content=APIError(503, "STORAGE_UNAVAILABLE", "Required storage is unavailable.").body())

    @app.get("/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT event_id FROM events LIMIT 0"))
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                if revision != "0001_events":
                    raise RuntimeError("Storage migration mismatch")
        except (SQLAlchemyError, RuntimeError):
            return JSONResponse(status_code=503, content={"status": "unhealthy", "api": "available", "storage": "unavailable"})
        return {"status": "healthy", "api": "available", "storage": "available"}

    @app.post("/api/v1/events", dependencies=[Depends(require_access)])
    async def submit_event(request: Request):
        event = await parse_body(request, EventInput)
        try:
            receipt = await run_in_threadpool(store_event, engine, event)
        except DataError:
            raise APIError(422, "INVALID_EVENT", "The submitted event contains an unsupported storage value.") from None
        return json_response(receipt, 200 if receipt["duplicate"] else 201)

    @app.get("/api/v1/interactions/{interactionId}", dependencies=[Depends(require_access)])
    def retrieve_interaction(interactionId: str):
        return json_response(get_interaction(engine, interactionId))

    @app.post("/api/v1/test/reset", dependencies=[Depends(require_reset)])
    async def reset_test_data(request: Request):
        if not settings.test_reset_enabled:
            raise APIError(403, "FORBIDDEN", "Test reset is disabled in this environment.")
        await parse_body(request, ResetRequest, reset=True)
        return json_response(await run_in_threadpool(reset_events, engine))

    return app
