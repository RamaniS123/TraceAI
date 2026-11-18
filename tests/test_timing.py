"""Timing must cover response production and exclude send/network/body delays."""
import asyncio

from fastapi.testclient import TestClient
import pytest

from traceai.config import Settings
from traceai.main import create_app
from traceai.timing import ApplicationTiming


def test_response_ready_boundary_and_no_threshold_rounding(monkeypatch):
    clock = [100]
    monkeypatch.setattr('traceai.timing.perf_counter_ns', lambda: clock[0])
    messages = []
    async def app(scope, receive, send):
        # Simulate auth/wait/database/assembly/serialization before sending headers.
        clock[0] += 1_000_000_001
        await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'x-kept', b'yes')]})
        clock[0] += 9_000_000_000  # Later streamed body work is outside this boundary.
        await send({'type': 'http.response.body', 'body': b'{}'})
    async def send(message):
        messages.append(message)
        clock[0] += 5_000_000_000  # Outbound send/network wait must not count.
    asyncio.run(ApplicationTiming(app)({'type': 'http'}, None, send))
    assert dict(messages[0]['headers']) == {b'x-kept': b'yes', b'server-timing': b'traceai_app;dur=1000.000001'}
    assert messages[1] == {'type': 'http.response.body', 'body': b'{}'}


def test_non_http_scope_passes_through_without_clock_or_header(monkeypatch):
    def unexpected():
        pytest.fail('Do not time lifespan/websocket scopes')
    monkeypatch.setattr('traceai.timing.perf_counter_ns', unexpected)
    seen = []
    async def app(scope, receive, send):
        seen.append(scope)
    asyncio.run(ApplicationTiming(app)({'type': 'lifespan'}, None, None))
    assert seen == [{'type': 'lifespan'}]


@pytest.mark.parametrize('failure', ['auth', 'unexpected'])
def test_errors_remain_safe_and_receive_timing(monkeypatch, failure):
    def broken(*args):
        raise RuntimeError('synthetic-private-canary')
    monkeypatch.setattr('traceai.main.get_audit_report', broken)
    settings = Settings(database_url='postgresql+psycopg://unavailable@127.0.0.1:1/unavailable',
                        api_token='synthetic-api', reset_token='synthetic-reset', _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get('/api/v1/interactions/test/report',
                              headers={'Authorization': 'Bearer synthetic-api'} if failure == 'unexpected' else {})
    assert response.status_code == (500 if failure == 'unexpected' else 401)
    value = response.headers['server-timing'].removeprefix('traceai_app;dur=')
    assert float(value) >= 0
    assert 'synthetic-private-canary' not in response.text
