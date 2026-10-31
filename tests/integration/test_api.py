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


@pytest.mark.parametrize('scenario_file', ['phase-3-scenario.json', pytest.param('phase-4-timeline-scenario.json', marks=pytest.mark.phase4), pytest.param('phase-4-records-scenario.json', marks=pytest.mark.phase4), pytest.param('phase-4-reports-scenario.json', marks=pytest.mark.phase4)])
def test_complete_shared_scenario(client, scenario_file):
    scenario = json.loads((FIXTURES / scenario_file).read_text())
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
        path = ('/api/v1/interactions/{interactionId}' + ('/report' if step['path'].endswith('/report') else '')) if step['path'].startswith('/api/v1/interactions/') else step['path']
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
    assert result['warnings'] == [{'code': 'MISSING_EVENT', 'message': 'Finalized interaction is missing interaction.started.', 'eventType': 'interaction.started'}]


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
            ('GET', '/api/v1/interactions/int-a/report', None, settings.api_token),
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


@pytest.mark.phase4
@pytest.mark.parametrize('action', ['accept', 'override', 'reject', 'escalate'])
def test_review_preserves_reviewer_action_reason_and_exact_timestamp(client, action):
    body = event(eventId='review-full', eventType='review.completed',
                 occurredAt='2026-10-30T14:30:00.123456789+00:00',
                 data={'reviewerId': 'reviewer-1', 'action': action, 'reason': '  Synthetic review reason.  '})
    assert submit(client, body).status_code == 201
    assert retrieve(client).json()['events'] == [body]
    assert submit(client, body).status_code == 200


@pytest.mark.phase4
@pytest.mark.parametrize('data', [
    {'reviewerId': '', 'action': 'accept', 'reason': 'Synthetic'},
    {'reviewerId': ' \t\n', 'action': 'accept', 'reason': 'Synthetic'},
    {'reviewerId': 'x' * 65, 'action': 'accept', 'reason': 'Synthetic'},
    {'reviewerId': 123, 'action': 'accept', 'reason': 'Synthetic'},
    {'reviewerId': 'reviewer', 'action': 'approve', 'reason': 'Synthetic'},
    {'reviewerId': 'reviewer', 'action': True, 'reason': 'Synthetic'},
    {'reviewerId': 'reviewer', 'action': 'accept', 'reason': ' \n\t'},
    {'reviewerId': 'reviewer', 'action': 'accept', 'reason': 'x' * 501},
    {'reviewerId': 'reviewer', 'action': 'accept'},
])
def test_incomplete_reviews_are_rejected_without_storage(client, data):
    assert submit(client, event(eventId='invalid-review', eventType='review.completed', data=data)).status_code == 422
    assert retrieve(client).status_code == 404


@pytest.mark.phase4
def test_correction_preserves_original_receipt_and_exposes_link(client):
    from sqlalchemy import select
    from traceai.models import Event
    original = event(data={'outputReference': 'original-synthetic-output'})
    assert submit(client, original).status_code == 201
    with client.app.state.engine.connect() as connection:
        before = dict(connection.execute(select(Event.__table__).where(Event.event_id == original['eventId'])).mappings().one())
    correction = event(eventId='correction-1', eventType='record.corrected',
                       data={'correctsEventId': original['eventId'], 'reason': 'Synthetic explanation', 'note': 'Original remains unchanged'})
    assert submit(client, correction).status_code == 201
    response = retrieve(client)
    validate_response(response, '/api/v1/interactions/{interactionId}', 'get')
    assert response.json()['events'] == sorted([original, correction], key=lambda item: item['eventId'])
    assert response.json()['warnings'] == [{'code': 'CORRECTED_EVENT', 'message': 'A linked correction is recorded; the original event is retained.', 'eventId': 'correction-1', 'eventType': 'record.corrected', 'correctsEventId': original['eventId']}]
    with client.app.state.engine.connect() as connection:
        after = dict(connection.execute(select(Event.__table__).where(Event.event_id == original['eventId'])).mappings().one())
    assert before == after  # Includes original payload, original timestamp and received_at.
    assert submit(client, correction).status_code == 200
    assert len(retrieve(client).json()['events']) == 2
    assert len(retrieve(client).json()['warnings']) == 1


@pytest.mark.phase4
def test_missing_self_and_cross_interaction_targets_fail_atomically_with_same_safe_error(client):
    other = event(eventId='other-record', interactionId='other-interaction')
    assert submit(client, other).status_code == 201
    errors = []
    for identifier, target in [('new-missing', 'absent'), ('new-self', 'new-self'), ('new-cross', other['eventId'])]:
        body = event(eventId=identifier, eventType='record.corrected', data={'correctsEventId': target, 'reason': 'Synthetic'})
        response = submit(client, body)
        assert response.status_code == 422
        errors.append(response.json())
        assert retrieve(client).status_code == 404
    assert errors[0] == errors[1] == errors[2]
    assert errors[0]['error']['code'] == 'INVALID_CORRECTION'
    assert retrieve(client, other['interactionId']).json()['events'] == [other]


@pytest.mark.phase4
def test_correction_can_be_retried_after_its_missing_target_is_accepted(client):
    original = event()
    correction = event(eventId='late-correction', eventType='record.corrected', data={'correctsEventId': original['eventId'], 'reason': 'Synthetic'})
    assert submit(client, correction).status_code == 422
    assert submit(client, original).status_code == 201
    assert submit(client, correction).status_code == 201
    assert len(retrieve(client).json()['events']) == 2


@pytest.mark.phase4
def test_multiple_corrections_and_chains_are_kept_as_separate_records(client):
    original = event()
    first = event(eventId='c1', eventType='record.corrected', occurredAt='2026-10-15T14:29:00Z', data={'correctsEventId': original['eventId'], 'reason': 'Explains a synthetic clock issue'})
    second = event(eventId='c2', eventType='record.corrected', data={'correctsEventId': 'c1', 'reason': 'Further explanation'})
    sibling = event(eventId='c3', eventType='record.corrected', data={'correctsEventId': original['eventId'], 'reason': 'Another explanation'})
    for body in [original, first, second, sibling]:
        assert submit(client, body).status_code == 201
    result = retrieve(client).json()
    assert len(result['events']) == 4
    assert [w['correctsEventId'] for w in result['warnings']] == [original['eventId'], 'c1', original['eventId']]
    assert original in result['events']
    assert result['status'] == 'in_progress'


@pytest.mark.phase4
def test_changed_correction_id_conflicts_without_retargeting_or_rewriting(client):
    a, b = event(), event(eventId='original-b')
    for original in (a, b):
        assert submit(client, original).status_code == 201
    correction = event(eventId='c1', eventType='record.corrected', data={'correctsEventId': a['eventId'], 'reason': 'Synthetic'})
    assert submit(client, correction).status_code == 201
    changed = {**correction, 'data': {**correction['data'], 'correctsEventId': b['eventId']}}
    assert submit(client, changed).status_code == 409
    result = retrieve(client).json()
    assert correction in result['events'] and changed not in result['events']
    assert result['warnings'][0]['correctsEventId'] == a['eventId']


@pytest.mark.phase4
def test_invalid_legacy_correction_chain_cannot_receive_a_new_correction(client):
    from sqlalchemy import insert
    from datetime import datetime
    from traceai.models import Event
    with client.app.state.engine.begin() as connection:
        for identifier, target in [('legacy-a', 'legacy-b'), ('legacy-b', 'legacy-a')]:
            connection.execute(insert(Event).values(event_id=identifier, interaction_id='int-a', event_type='record.corrected', occurred_at=datetime.fromisoformat('2026-10-15T14:30:00+00:00'), occurred_at_text='2026-10-15T14:30:00Z', model_version='model-1', application_version='app-1', data={'correctsEventId': target, 'reason': 'Legacy synthetic record'}))
    new = event(eventId='new-correction', eventType='record.corrected', data={'correctsEventId': 'legacy-a', 'reason': 'Synthetic'})
    assert submit(client, new).status_code == 422
    result = retrieve(client).json()
    assert len(result['events']) == 2
    assert result['warnings'] == []
    report = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    assert report.status_code == 200
    validate_response(report, '/api/v1/interactions/{interactionId}/report', 'get')
    assert report.json()['metadata']['eventCount'] == 2
    assert all(not correction['linkValid'] for correction in report.json()['corrections'])


@pytest.mark.phase4
def test_concurrent_identical_corrections_store_one_copy(client):
    original = event()
    assert submit(client, original).status_code == 201
    correction = event(eventId='concurrent-correction', eventType='record.corrected', data={'correctsEventId': original['eventId'], 'reason': 'Synthetic'})
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: submit(client, correction), range(5)))
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 200, 201]
    assert len(retrieve(client).json()['events']) == 2


@pytest.mark.phase4
def test_review_identifier_and_reason_limits_accept_the_exact_boundaries(client):
    body = event(eventId='review-boundary', eventType='review.completed',
                 data={'reviewerId': 'é' * 64, 'action': 'escalate', 'reason': 'r' * 500})
    assert submit(client, body).status_code == 201
    assert retrieve(client).json()['events'] == [body]


@pytest.mark.phase4
def test_correction_target_uses_the_existing_event_id_domain_without_normalization(client):
    original = event(eventId='   ')
    assert submit(client, original).status_code == 201
    correction = event(eventId='space-id-correction', eventType='record.corrected', data={'correctsEventId': original['eventId'], 'reason': 'Synthetic clarification'})
    assert submit(client, correction).status_code == 201
    assert retrieve(client).json()['warnings'][0]['correctsEventId'] == '   '


@pytest.mark.phase4
def test_previously_accepted_review_details_remain_readable_without_rewrite(client):
    from sqlalchemy import insert
    from datetime import datetime
    from traceai.models import Event
    legacy_data = {'reviewerId': '', 'action': 'accept', 'reason': '   '}
    with client.app.state.engine.begin() as connection:
        connection.execute(insert(Event).values(event_id='legacy-review', interaction_id='int-a', event_type='review.completed', occurred_at=datetime.fromisoformat('2026-10-15T14:30:00+00:00'), occurred_at_text='2026-10-15T14:30:00Z', model_version='model-1', application_version='app-1', data=legacy_data))
    response = retrieve(client)
    assert response.status_code == 200
    validate_response(response, '/api/v1/interactions/{interactionId}', 'get')
    stored = response.json()['events'][0]
    assert stored['data'] == legacy_data
    assert submit(client, stored).status_code == 422  # Stronger rules apply to new input only.
    assert retrieve(client).json()['events'] == [stored]
    report = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    assert report.status_code == 200
    validate_response(report, '/api/v1/interactions/{interactionId}/report', 'get')
    assert report.json()['reviewActions'][0]['reviewerId'] == ''
    assert report.json()['reviewActions'][0]['reason'] == '   '


@pytest.mark.phase4
def test_audit_report_contains_one_interaction_versions_reviews_corrections_and_metadata(client):
    start = event(eventId='report-start', modelVersion='model-z', applicationVersion='app-z')
    output = event(eventId='report-output', eventType='model.output_generated', occurredAt='2026-10-15T14:31:00Z', modelVersion='model-a', applicationVersion='app-a')
    review = event(eventId='report-review', eventType='review.completed', occurredAt='2026-10-15T14:32:00.123456789+00:00', data={'reviewerId':'reviewer-1','action':'override','reason':'  Synthetic review  '})
    correction = event(eventId='report-correction', eventType='record.corrected', occurredAt='2026-10-15T14:33:00Z', data={'correctsEventId':review['eventId'],'reason':'Synthetic clarification','suggestedAction':'reject'})
    end = event(eventId='report-end', eventType='interaction.completed', occurredAt='2026-10-15T14:34:00Z')
    foreign = event(eventId='foreign', interactionId='another-interaction', modelVersion='foreign-model')
    for body in [end, start, output, review, correction, foreign]:
        assert submit(client, body).status_code == 201
    response = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    validate_response(response, '/api/v1/interactions/{interactionId}/report', 'get')
    report = response.json()
    assert report['events'] == [start, output, review, correction, end]
    assert report['modelVersions'] == ['model-2.1', 'model-a', 'model-z']
    assert report['applicationVersions'] == ['app-1.4', 'app-a', 'app-z']
    assert report['metadata'] == {'eventCount':5, 'firstOccurredAt':start['occurredAt'], 'lastOccurredAt':end['occurredAt']}
    assert report['reviewActions'] == [{'eventId':review['eventId'],'reviewerId':'reviewer-1','action':'override','reason':'  Synthetic review  ','occurredAt':review['occurredAt']}]
    assert report['corrections'] == [{'eventId':correction['eventId'],'correctsEventId':review['eventId'],'reason':'Synthetic clarification','occurredAt':correction['occurredAt'],'linkValid':True}]
    assert report['warnings'] == retrieve(client).json()['warnings']
    assert 'does not certify legal compliance' in report['disclaimer']


@pytest.mark.phase4
@pytest.mark.parametrize('auth', ['none', 'invalid'])
def test_audit_report_authentication_precedes_interaction_lookup(client, auth):
    headers = {} if auth == 'none' else {'Authorization':'Bearer invalid-synthetic-token'}
    response = client.get('/api/v1/interactions/unknown/report', headers=headers)
    assert response.status_code == 401
    validate_response(response, '/api/v1/interactions/{interactionId}/report', 'get')
    assert response.headers['www-authenticate'] == 'Bearer'


@pytest.mark.phase4
def test_unknown_report_is_404_and_creates_no_interaction(client):
    response = client.get('/api/v1/interactions/unknown/report', headers=client.api_headers)
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'INTERACTION_NOT_FOUND'
    assert retrieve(client, 'unknown').status_code == 404


@pytest.mark.phase4
def test_audit_report_is_repeatable_read_only_and_not_cached_after_reset(client):
    from sqlalchemy import select
    from traceai.models import Event
    assert submit(client, event()).status_code == 201
    with client.app.state.engine.connect() as connection:
        before = [dict(row) for row in connection.execute(select(Event.__table__).order_by(Event.event_id)).mappings()]
    first = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    second = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    with client.app.state.engine.connect() as connection:
        after = [dict(row) for row in connection.execute(select(Event.__table__).order_by(Event.event_id)).mappings()]
    assert before == after
    assert client.post('/api/v1/test/reset', headers=client.reset_headers, json={'confirm':True}).status_code == 200
    assert client.get('/api/v1/interactions/int-a/report', headers=client.api_headers).status_code == 404


@pytest.mark.phase4
def test_report_recomputes_incomplete_interaction_when_late_events_arrive(client):
    end = event(eventId='end', eventType='interaction.completed', occurredAt='2026-10-15T14:32:00Z')
    assert submit(client, end).status_code == 201
    first = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers).json()
    assert first['metadata']['eventCount'] == 1 and len(first['warnings']) == 2
    for body in [event(), event(eventId='output', eventType='model.output_generated', occurredAt='2026-10-15T14:31:00Z')]:
        assert submit(client, body).status_code == 201
    second = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers).json()
    assert second['metadata']['eventCount'] == 3 and second['warnings'] == []
    assert first['metadata']['eventCount'] == 1 and len(first['warnings']) == 2


@pytest.mark.phase4
def test_audit_report_preserves_exact_numeric_payloads(client):
    body = event(data={'score': Decimal('0.12345678901234567890123456789')})
    response = client.post('/api/v1/events', content=simplejson.dumps(body, use_decimal=True), headers={**client.api_headers,'Content-Type':'application/json'})
    assert response.status_code == 201
    report = client.get('/api/v1/interactions/int-a/report', headers=client.api_headers)
    assert simplejson.loads(report.text, use_decimal=True)['events'] == [body]
