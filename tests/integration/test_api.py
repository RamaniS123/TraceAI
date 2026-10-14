"""HTTP behavior against the isolated migrated PostgreSQL test database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import httpx
from jsonschema import Draft202012Validator, FormatChecker
import pytest
import simplejson
from sqlalchemy.engine import make_url

from traceai.config import Settings
from traceai.main import create_app

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures'
CONTRACT = json.loads((ROOT / 'contracts/openapi.json').read_text())
pytestmark = pytest.mark.integration


@pytest.fixture
def app_settings():
    url = os.getenv('TRACEAI_TEST_DATABASE_URL') or dotenv_values('.env').get('TRACEAI_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TRACEAI_TEST_DATABASE_URL to an isolated migrated test database')
    # These tests exercise reset, so explicitly refuse an ordinary development DB.
    assert make_url(url).database.endswith('_test'), 'API tests require a database name ending in _test'
    return Settings(database_url=url, api_token=secrets.token_urlsafe(32),
                    reset_token=secrets.token_urlsafe(32), test_reset_enabled=True, _env_file=None)


@pytest.fixture
def client(app_settings):
    with TestClient(create_app(app_settings)) as client:
        client.api_headers = {'Authorization': 'Bearer ' + app_settings.api_token.get_secret_value()}
        client.reset_headers = {'Authorization': 'Bearer ' + app_settings.reset_token.get_secret_value()}
        response = client.post('/api/v1/test/reset', headers=client.reset_headers, json={'confirm': True})
        assert response.status_code == 200, 'Test database must be migrated and reachable'
        yield client
        response = client.post('/api/v1/test/reset', headers=client.reset_headers, json={'confirm': True})
        assert response.status_code == 200


def event(**changes):
    return {**json.loads((FIXTURES / 'valid-events.json').read_text())[0], **changes}


def submit(client, body):
    return client.post('/api/v1/events', headers=client.api_headers, json=body)


def retrieve(client, interaction='int-a'):
    return client.get('/api/v1/interactions/' + interaction, headers=client.api_headers)


def validate_response(response, path, method):
    response_spec = CONTRACT['paths'][path][method.lower()]['responses'][str(response.status_code)]
    schema = response_spec['content']['application/json']['schema']
    document = {**schema, 'components': CONTRACT['components']}
    Draft202012Validator(document, format_checker=FormatChecker()).validate(response.json())


def test_complete_shared_scenario(client):
    scenario = json.loads((FIXTURES / 'phase-3-scenario.json').read_text())
    for index, step in enumerate(scenario['steps']):
        headers = {'api': client.api_headers, 'reset': client.reset_headers,
                   'none': {}, 'invalid': {'Authorization': 'Bearer invalid-synthetic-token'}}[step['auth']]
        kwargs = {'headers': dict(headers)}
        if 'body' in step:
            kwargs['json'] = step['body']
        if 'rawBody' in step:
            kwargs['content'] = step['rawBody']
            kwargs['headers']['Content-Type'] = 'application/json'
        response = client.request(step['method'], step['path'], **kwargs)
        assert response.status_code == step['expectedStatus'], f'Scenario step {index}: {response.text}'
        if 'expectedBody' in step:
            assert response.json() == step['expectedBody'], f'Scenario step {index}'
        path = '/api/v1/interactions/{interactionId}' if step['path'].startswith('/api/v1/interactions/') else step['path']
        validate_response(response, path, step['method'])


def test_six_event_types_can_be_recorded(client):
    samples = json.loads((FIXTURES / 'valid-events.json').read_text())
    samples.append(event(eventId='evt-stopped', interactionId='int-stop', eventType='interaction.stopped'))
    for body in samples:
        assert submit(client, body).status_code == 201
        response = retrieve(client, body['interactionId'])
        assert body in response.json()['events']


@pytest.mark.parametrize('size,status', [(65536, 201), (65537, 413)])
def test_exact_body_boundaries_without_content_length(client, size, status):
    body = (FIXTURES / f'event-{size}-bytes.json').read_bytes()
    async def run():
        async def stream():
            for start in range(0, len(body), 4096):
                yield body[start:start+4096]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url='http://test') as http:
            response = await http.post('/api/v1/events', content=stream(),
                                       headers={**client.api_headers, 'Content-Type': 'application/json'})
        assert 'content-length' not in response.request.headers
        return response
    response = asyncio.run(run())
    assert response.status_code == status
    validate_response(response, '/api/v1/events', 'post')
    found = retrieve(client, 'int-size')
    assert found.status_code == (200 if status == 201 else 404)


def test_oversize_uses_utf8_bytes_not_character_count(client):
    body = event(data={'padding': 'é' * 33000})
    raw = json.dumps(body, ensure_ascii=False).encode()
    assert len(raw) > 65536
    response = client.post('/api/v1/events', content=raw, headers={**client.api_headers, 'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert retrieve(client).status_code == 404


def test_normalized_timestamp_and_numeric_duplicate_equality(client):
    original = event(data={'nested': [1, {'flag': True}], 'number': 1})
    assert submit(client, original).status_code == 201
    equivalent = {**original, 'occurredAt': '2026-10-15T14:30:00.000+00:00',
                  'data': {'number': 1.0, 'nested': [1.0, {'flag': True}]}}
    response = submit(client, equivalent)
    assert response.status_code == 200
    assert response.json()['duplicate'] is True
    assert submit(client, {**original, 'data': {'nested': [1, {'flag': 1}], 'number': 1}}).status_code == 409
    assert retrieve(client).json()['events'] == [original]


def test_numeric_precision_is_not_lost_in_storage_or_duplicate_check(client):
    original = event(data={'number': Decimal('0.123456789012345678901234567890')})
    def send(value):
        return client.post('/api/v1/events', content=simplejson.dumps(value, use_decimal=True),
                           headers={**client.api_headers, 'Content-Type': 'application/json'})
    assert send(original).status_code == 201
    assert send(original).status_code == 200
    different = {**original, 'data': {'number': Decimal('0.123456789012345678901234567891')}}
    assert send(different).status_code == 409
    result = simplejson.loads(retrieve(client).text, use_decimal=True)
    assert result['events'] == [original]


def test_full_timestamp_precision_ties_and_terminal_status(client):
    samples = [event(eventId='evt-z', eventType='interaction.stopped', occurredAt='2026-10-15T14:30:00.0000002Z'),
               event(eventId='evt-b', eventType='interaction.completed', occurredAt='2026-10-15T14:30:00.0000001Z'),
               event(eventId='evt-a', eventType='model.output_generated', occurredAt='2026-10-15T14:30:00.0000001+00:00')]
    for sample in samples:
        assert submit(client, sample).status_code == 201
    result = retrieve(client).json()
    assert [e['eventId'] for e in result['events']] == ['evt-a', 'evt-b', 'evt-z']
    assert result['status'] == 'stopped'
    assert result['warnings'] == []


def test_concurrent_identical_submissions_store_once(client):
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: submit(client, event()), range(5)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 201]
    assert retrieve(client).json()['events'] == [event()]


@pytest.mark.parametrize('payload', [{}, {'confirm': False}, {'confirm': 'true'}, {'confirm': 1},
                                    {'confirm': True, 'unexpected': True}, None])
def test_bad_reset_preserves_records(client, payload):
    assert submit(client, event()).status_code == 201
    response = client.post('/api/v1/test/reset', headers=client.reset_headers, json=payload)
    assert response.status_code == 400
    assert retrieve(client).json()['events'] == [event()]


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'{"eventId":"a","eventId":"b"}', b'NaN', b'Infinity'])
def test_malformed_json_is_rejected_without_records(client, raw):
    response = client.post('/api/v1/events', content=raw, headers={**client.api_headers, 'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'MALFORMED_JSON'
    assert retrieve(client).status_code == 404


def test_authentication_precedes_parsing_and_missing_credentials_fail_closed(client, app_settings):
    for token in (None, 'Basic invalid', 'Bearer invalid', 'Bearer'):
        headers = {'Authorization': token} if token else {}
        for method, path in [('POST', '/api/v1/events'), ('GET', '/api/v1/interactions/int-a'), ('POST', '/api/v1/test/reset')]:
            response = client.request(method, path, headers=headers, content=b'{' * 70000)
            assert response.status_code == 401
            assert response.headers['www-authenticate'] == 'Bearer'
    assert client.get('/health').status_code == 200
    with TestClient(create_app(Settings(database_url=app_settings.database_url, _env_file=None))) as unauthenticated:
        response = unauthenticated.post('/api/v1/events', headers=client.api_headers, json=event())
        assert response.status_code == 401


def test_reset_disabled_by_default_and_reset_role_can_submit(client, app_settings):
    assert client.post('/api/v1/events', headers=client.reset_headers, json=event()).status_code == 201
    settings = app_settings.model_copy(update={'test_reset_enabled': False})
    with TestClient(create_app(settings)) as disabled:
        response = disabled.post('/api/v1/test/reset', headers=client.reset_headers, json={'confirm': True})
        assert response.status_code == 403
    assert retrieve(client).json()['events'] == [event()]


def test_storage_failure_never_confirms_write_or_reset():
    settings = Settings(database_url='postgresql+psycopg://unavailable@127.0.0.1:1/unavailable',
                        api_token=secrets.token_urlsafe(32), reset_token=secrets.token_urlsafe(32),
                        test_reset_enabled=True, _env_file=None)
    with TestClient(create_app(settings)) as client:
        for method, path, body, token in [
            ('POST', '/api/v1/events', event(), settings.api_token),
            ('GET', '/api/v1/interactions/int-a', None, settings.api_token),
            ('POST', '/api/v1/test/reset', {'confirm': True}, settings.reset_token),
        ]:
            response = client.request(method, path, json=body, headers={'Authorization': 'Bearer '+token.get_secret_value()})
            assert response.status_code == 503
            assert response.json() == {'error': {'code': 'STORAGE_UNAVAILABLE', 'message': 'Required storage is unavailable.'}}


def test_documented_contract_is_served_in_docs(client):
    assert client.get('/openapi.json').json() == CONTRACT
    assert client.get('/docs').status_code == 200


def test_rejected_media_types_and_routes_use_safe_error_shape(client):
    for headers in ({'Content-Type': 'text/plain'},
                    {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}):
        response = client.post('/api/v1/events', content='{}', headers={**client.api_headers, **headers})
        assert response.status_code == 422
        validate_response(response, '/api/v1/events', 'post')
    for method, path, status in [('GET', '/not-a-route', 404), ('DELETE', '/health', 405)]:
        response = client.request(method, path)
        assert response.status_code == status
        assert set(response.json()) == {'error'}
        assert set(response.json()['error']) == {'code', 'message'}
    assert retrieve(client).status_code == 404
