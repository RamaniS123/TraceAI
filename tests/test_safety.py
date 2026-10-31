"""Failure responses and logs must not copy request/exception contents."""
import logging

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.exc import OperationalError
from uvicorn.logging import AccessFormatter

from traceai.config import Settings
from traceai.main import create_app
from traceai.safety import SafeAccessLog

CANARY = 'synthetic-sensitive-canary-4d8b'
SETTINGS = dict(database_url=f'postgresql+psycopg://user:{CANARY}@127.0.0.1:1/unavailable',
                api_token='api-'+CANARY, reset_token='reset-'+CANARY,
                test_reset_enabled=True, _env_file=None)
pytestmark = pytest.mark.phase4


def test_unexpected_errors_are_safe_in_api_responses_and_logs(monkeypatch, caplog):
    def broken(*args):
        raise RuntimeError(f'{CANARY} postgresql://user:password@db/private /srv/private.py')
    monkeypatch.setattr('traceai.main.get_audit_report', broken)
    with TestClient(create_app(Settings(**SETTINGS))) as client:
        response = client.get('/api/v1/interactions/'+CANARY+'/report?token='+CANARY,
                              headers={'Authorization': 'Bearer '+SETTINGS['api_token']})
    assert response.status_code == 500
    assert response.json() == {'error': {'code': 'INTERNAL_ERROR', 'message': 'Request could not be completed.'}}
    assert CANARY not in response.text + caplog.text
    assert 'Traceback' not in caplog.text
    assert 'INTERNAL_ERROR' in caplog.text


def test_database_errors_do_not_expose_statement_parameters_or_exception(monkeypatch, caplog):
    def broken(*args):
        raise OperationalError('SELECT '+CANARY, {'password': CANARY}, RuntimeError('/srv/'+CANARY))
    monkeypatch.setattr('traceai.main.get_interaction', broken)
    with TestClient(create_app(Settings(**SETTINGS))) as client:
        response = client.get('/api/v1/interactions/'+CANARY,
                              headers={'Authorization': 'Bearer '+SETTINGS['api_token']})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'
    assert CANARY not in response.text + caplog.text


@pytest.mark.parametrize('source,path', [('system','/test/setup'), ('tester','/tester/test/setup')])
def test_interface_unexpected_failures_keep_course_error_shape_and_allow_retry(monkeypatch, caplog, source, path):
    def broken(*args):
        raise RuntimeError(CANARY)
    name = 'reset_events' if source == 'system' else 'prepare_target'
    monkeypatch.setattr('traceai.testing_interface.'+name, broken)
    app = create_app(Settings(**SETTINGS))
    with TestClient(app) as client:
        body = {'session_id': 'retry-me', 'setup': {}} if source == 'system' else {'target_url':'https://target.test'}
        response = client.post(path, json=body, headers={'Authorization':'Bearer '+SETTINGS['reset_token']})
        assert response.status_code == 500
        assert response.json()['source'] == source
        assert CANARY not in response.text + caplog.text
        assert app.state.system_sessions == {} and app.state.tester_sessions == {}


@pytest.mark.parametrize('content', [
    b'{"token":"'+CANARY.encode()+b'",}', b'\xff', b'{"x":NaN}',
    b'{"x":1,"x":2}', b'['*1100+b']'*1100, b' '*65537,
])
def test_invalid_bodies_never_echo_input(content, caplog):
    app = create_app(Settings(**SETTINGS))
    with TestClient(app) as client:
        for path, token in [('/api/v1/events', SETTINGS['api_token']),
                            ('/api/v1/test/reset', SETTINGS['reset_token']),
                            ('/test/setup', SETTINGS['reset_token']),
                            ('/tester/test/setup', SETTINGS['api_token'])]:
            response = client.post(path, content=content, headers={'Content-Type':'application/json',
                                                                  'Authorization':'Bearer '+token})
            assert 400 <= response.status_code < 500
            assert CANARY not in response.text + caplog.text


def test_remote_error_is_not_reflected_by_tester(caplog):
    app = create_app(Settings(**SETTINGS))
    app.state.tester_transport = httpx.MockTransport(lambda request: httpx.Response(
        403, json={'message': CANARY+' /srv/private.py Traceback', 'source': 'system'}))
    with TestClient(app) as client:
        response = client.post('/tester/test/setup', json={'target_url':'https://target.test'})
    assert response.status_code == 403
    assert response.json() == {'message':'Target system setup returned HTTP 403.', 'source':'system'}
    assert CANARY not in response.text + caplog.text


def test_uvicorn_access_log_omits_request_path_query_and_credentials():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s - "%s %s HTTP/%s" %d',
                               (CANARY, CANARY, '/'+CANARY+'?token='+CANARY, '1.1', 401), None)
    SafeAccessLog().filter(record)
    formatted = AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert CANARY not in formatted
    assert '401' in formatted


def test_startup_migration_failure_exits_without_launching_server_or_leaking(monkeypatch, capsys):
    from traceai import startup
    def broken(*args):
        raise RuntimeError(CANARY+' postgresql://user:password@db /srv/private.py')
    monkeypatch.setattr(startup.command, 'upgrade', broken)
    def unexpected_exec(*args):
        pytest.fail('Server must not start after a failed migration')
    monkeypatch.setattr(startup.os, 'execv', unexpected_exec)
    assert startup.main() == 1
    output = capsys.readouterr()
    assert output.err == 'Startup failed: database migration could not be completed.\n'
    assert CANARY not in output.out + output.err


@pytest.mark.parametrize('revision', ['a'*40, 'not-a-revision-private-canary'])
def test_health_identifies_release_without_exposing_arbitrary_environment_values(monkeypatch,revision):
    monkeypatch.setenv('RENDER_GIT_COMMIT',revision)
    with TestClient(create_app(Settings(**SETTINGS))) as client:
        response=client.get('/health')
        assert response.status_code==503
        assert response.headers['x-traceai-contract']==client.get('/openapi.json').json()['info']['version']
        assert response.headers.get('x-traceai-revision')==(revision if len(revision)==40 else None)
        assert 'private-canary' not in response.text+str(response.headers)
