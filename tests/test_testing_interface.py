"""Course testing interface: tester and system /test endpoints, without a database or network."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from traceai.config import Settings
from traceai.main import create_app

TARGET = 'https://target.test/system'
OUTCOMES = {'pass', 'fail', 'error', 'skip'}


def settings(**changes):
    values = dict(database_url='postgresql+psycopg://unavailable@127.0.0.1:1/unavailable',
                  api_token='synthetic-api-secret', reset_token='synthetic-reset-secret',
                  test_reset_enabled=True, _env_file=None)
    return Settings(**{**values, **changes})


@pytest.fixture(autouse=True)
def no_public_url(monkeypatch):
    for name in ('TRACEAI_PUBLIC_URL', 'RENDER_EXTERNAL_URL', 'TRACEAI_TESTER_TARGET_TOKENS'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(seen):
    """Tester wired to a fake target whose setup works and whose project API is down."""
    def target(request):
        seen.append(request)
        if request.url.path == '/system/test/setup':
            return httpx.Response(201, json={'session_id': json.loads(request.content)['session_id']})
        if request.url.path == '/system/test/report':
            return httpx.Response(200, json={'session_id': request.url.params['session_id'], 'coverage': {
                'code': {'covered': 12, 'total': 40, 'basis': 'Source lines in the synthetic target'}}})
        return httpx.Response(503, json={'error': {'code': 'STORAGE_UNAVAILABLE', 'message': 'Down.'}})
    app = create_app(settings())
    app.state.tester_transport = httpx.MockTransport(target)
    with TestClient(app) as test_client:
        yield test_client


def setup_session(client):
    response = client.post('/tester/test/setup', json={'target_url': TARGET})
    assert response.status_code == 201, response.text
    return response.json()['session_id']


def assert_error_body(response, status, source):
    assert response.status_code == status
    body = response.json()
    assert body['source'] == source and isinstance(body['message'], str) and body['message']


@pytest.mark.parametrize('body', [None, {}, {'target_url': ''}, {'target_url': 'ftp://x.test'},
                                  {'target_url': 'https://x.test/?a=1'}, {'target_url': 'https://u:p@x.test'}])
def test_tester_setup_rejects_invalid_requests(client, body):
    response = client.post('/tester/test/setup', json=body) if body is not None else \
        client.post('/tester/test/setup', content=b'not json', headers={'Content-Type': 'application/json'})
    assert_error_body(response, 400, 'tester')


def test_full_session_returns_well_formed_report(client):
    session_id = setup_session(client)
    assert client.get('/tester/test/report', params={'session_id': session_id}).status_code == 409
    response = client.post('/tester/test/run', json={'session_id': session_id})
    assert response.status_code == 200
    report = response.json()
    assert report['session_id'] == session_id and report['target_url'] == TARGET
    ids = [row['test_id'] for row in report['results']]
    assert len(ids) == len(set(ids)) == 42 and all(ids)
    for row in report['results']:
        assert row['outcome'] in OUTCOMES and row['message']
        if row['outcome'] == 'error':
            assert row['source'] in {'tester', 'system', 'communication', 'unknown'}
    assert any(row['outcome'] == 'error' and row['source'] == 'system' for row in report['results'])
    assert report['coverage']['code'] == {'covered': 12, 'total': 40, 'basis': 'Source lines in the synthetic target'}
    for name in ('component', 'system'):
        measure = report['coverage'][name]
        assert 0 <= measure['covered'] <= measure['total'] and measure['basis']
    assert report['coverage']['component'] == {**report['coverage']['component'], 'covered': 4, 'total': 5}
    assert client.get('/tester/test/report', params={'session_id': session_id}).json() == report


def test_session_runs_once_and_unknown_sessions_are_404(client):
    session_id = setup_session(client)
    assert client.post('/tester/test/run', json={'session_id': session_id}).status_code == 200
    assert_error_body(client.post('/tester/test/run', json={'session_id': session_id}), 409, 'tester')
    assert_error_body(client.post('/tester/test/run', json={'session_id': 'missing'}), 404, 'tester')
    assert_error_body(client.get('/tester/test/report', params={'session_id': 'missing'}), 404, 'tester')
    assert_error_body(client.post('/tester/test/run', json={}), 400, 'tester')


def test_system_setup_error_is_forwarded_and_no_session_is_created():
    def target(request):
        return httpx.Response(409, json={'message': 'Session exists.', 'source': 'system'})
    app = create_app(settings())
    app.state.tester_transport = httpx.MockTransport(target)
    with TestClient(app) as client:
        response = client.post('/tester/test/setup', json={'target_url': TARGET})
        assert response.json() == {'message': 'Session exists.', 'source': 'system'}
        assert response.status_code == 409
        assert app.state.tester_sessions == {}


def test_unreachable_target_is_a_communication_error():
    def target(request):
        raise httpx.ConnectError('refused')
    app = create_app(settings())
    app.state.tester_transport = httpx.MockTransport(target)
    with TestClient(app) as client:
        assert_error_body(client.post('/tester/test/setup', json={'target_url': TARGET}), 500, 'communication')


def test_tokens_are_sent_only_to_the_configured_own_origin(client, seen, monkeypatch):
    setup_session(client)
    assert all('authorization' not in request.headers for request in seen)
    monkeypatch.setenv('TRACEAI_PUBLIC_URL', 'https://target.test')
    seen.clear()
    setup_session(client)
    assert seen[0].headers['authorization'] == 'Bearer synthetic-reset-secret'


def test_system_setup_requires_reset_token_and_valid_body():
    with TestClient(create_app(settings())) as client:
        body = {'session_id': 'run-1', 'setup': {}}
        assert_error_body(client.post('/test/setup', json=body), 401, 'system')
        assert_error_body(client.post('/test/setup', json=body, headers={'Authorization': 'Bearer synthetic-api-secret'}), 401, 'system')
        reset = {'Authorization': 'Bearer synthetic-reset-secret'}
        assert_error_body(client.post('/test/setup', json={'setup': {}}, headers=reset), 400, 'system')
        # Storage is unreachable here, so preparation fails safely and no session is kept.
        assert_error_body(client.post('/test/setup', json=body, headers=reset), 500, 'system')
        assert_error_body(client.get('/test/report', params={'session_id': 'run-1'}), 404, 'system')
        assert_error_body(client.get('/test/report'), 400, 'system')


def test_system_setup_respects_disabled_reset():
    with TestClient(create_app(settings(test_reset_enabled=False))) as client:
        response = client.post('/test/setup', json={'session_id': 'run-1', 'setup': {}},
                               headers={'Authorization': 'Bearer synthetic-reset-secret'})
        assert_error_body(response, 403, 'system')
