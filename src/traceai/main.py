"""Application factory. Business endpoints are added in chunk 3."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from traceai.config import Settings
from traceai.db import create_database_engine, session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="TraceAI", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = session_factory(engine)

    @app.get("/health")
    def health():
        try:
            with engine.connect() as connection:
                # Detect missing/unmigrated storage as well as lost connections.
                connection.execute(text("SELECT event_id FROM events LIMIT 0"))
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                if revision != "0001_events":
                    raise RuntimeError("Storage migration mismatch")
        except (SQLAlchemyError, RuntimeError):
            return JSONResponse(status_code=503, content={"status": "unhealthy", "api": "available", "storage": "unavailable"})
        return {"status": "healthy", "api": "available", "storage": "available"}

    return app
