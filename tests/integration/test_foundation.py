"""Integration checks against an explicitly selected disposable PostgreSQL database."""
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from traceai.config import Settings
from traceai.db import create_database_engine, session_factory
from traceai.main import create_app
from traceai.models import Event

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    from dotenv import dotenv_values
    url = os.getenv("TRACEAI_TEST_DATABASE_URL") or dotenv_values(".env").get("TRACEAI_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TRACEAI_TEST_DATABASE_URL to a migrated isolated test database")
    return Settings(database_url=url, _env_file=None)


@pytest.fixture
def engine(settings):
    engine = create_database_engine(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def transaction(engine):
    with engine.connect() as connection:
        tx = connection.begin()
        yield connection
        tx.rollback()


def event(identifier, interaction):
    return dict(event_id=identifier, interaction_id=interaction,
                event_type="interaction.started",
                occurred_at=datetime.fromisoformat("2026-10-15T14:30:00+00:00"),
                occurred_at_text="2026-10-15T14:30:00Z", model_version="model-2.1",
                application_version="app-1.4", data={"synthetic": True})


def test_public_health_and_startup(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "api": "available", "storage": "available"}
        # Match the authored contract rather than FastAPI's inferred response schema.
        from jsonschema import Draft202012Validator
        contract = json.loads((Path(__file__).parents[2] / "contracts/openapi.json").read_text())
        Draft202012Validator(contract['components']['schemas']['HealthResponse']).validate(response.json())


def test_unreachable_storage_is_safe():
    settings = Settings(database_url="postgresql+psycopg://unavailable@127.0.0.1:1/unavailable", _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unhealthy", "api": "available", "storage": "unavailable"}
        assert "postgresql" not in response.text


def test_grouping_and_json_round_trip(transaction):
    first, second = uuid4().hex, uuid4().hex
    transaction.execute(Event.__table__.insert(), [event(first, first), event(second, second)])
    rows = transaction.execute(select(Event.__table__).where(Event.interaction_id == first)).mappings().all()
    assert len(rows) == 1
    assert rows[0]['event_id'] == first
    assert rows[0]['data'] == {"synthetic": True}
    assert rows[0]['occurred_at'].utcoffset().total_seconds() == 0
    assert rows[0]['occurred_at_text'] == "2026-10-15T14:30:00Z"


def test_duplicate_primary_key_rejected_without_partial_write(transaction):
    identifier = uuid4().hex
    transaction.execute(Event.__table__.insert(), event(identifier, identifier))
    with pytest.raises(IntegrityError):
        with transaction.begin_nested():
            transaction.execute(Event.__table__.insert(), event(identifier, "other"))
    assert transaction.execute(select(Event.event_id).where(Event.event_id == identifier)).all() == [(identifier,)]


@pytest.mark.parametrize("changes", [{"data": []}, {"event_type": "unknown"}, {"model_version": ""}])
def test_database_constraints(transaction, changes):
    identifier = uuid4().hex
    with pytest.raises(IntegrityError):
        with transaction.begin_nested():
            transaction.execute(Event.__table__.insert(), {**event(identifier, identifier), **changes})
    assert transaction.execute(select(Event.event_id).where(Event.event_id == identifier)).first() is None


def test_session_commit_and_rollback(engine):
    factory = session_factory(engine)
    identifier = uuid4().hex
    try:
        with factory.begin() as session:
            session.add(Event(**event(identifier, identifier)))
        # A new connection sees the committed record.
        with engine.connect() as connection:
            assert connection.execute(select(Event.event_id).where(Event.event_id == identifier)).scalar_one() == identifier
        with pytest.raises(RuntimeError):
            with factory.begin() as session:
                session.execute(delete(Event).where(Event.event_id == identifier))
                raise RuntimeError("Synthetic transaction failure")
        with engine.connect() as connection:
            assert connection.execute(select(Event.event_id).where(Event.event_id == identifier)).scalar_one() == identifier
    finally:
        with factory.begin() as session:
            session.execute(delete(Event).where(Event.event_id == identifier))


def test_missing_schema_is_unhealthy(settings):
    app = create_app(settings)
    # Force a schema with no events table only for this application's connections.
    from sqlalchemy import event as sa_event
    @sa_event.listens_for(app.state.engine, "connect")
    def empty_schema(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET search_path TO pg_catalog")
        connection.commit()
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json()['storage'] == 'unavailable'
