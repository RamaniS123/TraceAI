"""Shared setup for the black-box TraceAI test suite.

pytest loads this file automatically for tests in this folder. Every fixture
defined here can be used by any test just by naming it as a function argument.

The tests are black-box: they only talk to the service over HTTP, so the same
tests can run against our local server, our deployment, or Team 103's.
They are skipped unless TRACEAI_BASE_URL is set, e.g. from PowerShell:
    $env:TRACEAI_BASE_URL = "http://localhost:8000"
    $env:TRACEAI_API_TOKEN = "<api token>"
    $env:TRACEAI_RESET_TOKEN = "<reset token>"
    python -m pytest tests/blackbox -v
"""
import os

from dotenv import dotenv_values
import httpx
import pytest

# Token values fall back to .env so a local run uses the same secrets as the app.
_dotenv = dotenv_values(".env")
BASE_URL = os.getenv("TRACEAI_BASE_URL")
API_TOKEN = os.getenv("TRACEAI_API_TOKEN") or _dotenv.get("TRACEAI_API_TOKEN")
# Reset needs its own token; the ordinary API token gets 403 on reset.
RESET_TOKEN = os.getenv("TRACEAI_RESET_TOKEN") or _dotenv.get("TRACEAI_RESET_TOKEN")


def pytest_collection_modifyitems(config, items):
    """Mark every test in this folder as blackbox, and skip them all without a base URL."""
    skip = pytest.mark.skip(reason="Set TRACEAI_BASE_URL to run black-box HTTP tests")
    for item in items:
        if "blackbox" in item.path.parts:
            item.add_marker(pytest.mark.blackbox)
            if not BASE_URL:
                item.add_marker(skip)


@pytest.fixture
def client():
    """An HTTP client pointed at the service. Closed automatically after each test."""
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture
def auth_headers():
    """Headers for ordinary protected endpoints (submit, retrieve)."""
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def reset_headers():
    """Headers for POST /api/v1/test/reset."""
    return {"Authorization": f"Bearer {RESET_TOKEN}"}


@pytest.fixture(autouse=True)
def reset_data(request, client, reset_headers):
    """Wipe all events before every test so tests can't affect each other.

    autouse=True means this runs for every test without being named.
    Tests marked @pytest.mark.no_reset skip it (e.g. /health tests).
    """
    if request.node.get_closest_marker("no_reset"):
        return
    response = client.post("/api/v1/test/reset", json={"confirm": True}, headers=reset_headers)
    assert response.status_code == 200, f"Reset failed: {response.status_code} {response.text}"


def make_event(**overrides):
    """Build a valid EventInput dict. Pass keyword arguments to change fields.

    Example: make_event(eventId="e2", eventType="interaction.completed")
    """
    event = {
        "eventId": "evt-001",
        "interactionId": "int-001",
        "eventType": "interaction.started",
        "occurredAt": "2026-10-15T14:30:00Z",
        "modelVersion": "model-1.0",
        "applicationVersion": "app-1.0",
        "data": {},
    }
    event.update(overrides)
    return event
