"""Capacity evaluator must detect loss/corruption and refuse unsafe targets."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker
import pytest

spec = importlib.util.spec_from_file_location('capacity', Path(__file__).parents[1] / 'tools/phase5_capacity.py')
capacity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capacity)
RUN = 'synthetic123'
BASE = 'http://127.0.0.1:8015'


def test_full_dataset_matches_phase2_plan_and_input_schema():
    counts, identifiers = Counter(), set()
    schema = json.loads((capacity.ROOT / 'contracts/event.schema.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for index in range(100):
        events = capacity.interaction_events(RUN, index)
        assert len(events) == 100
        assert events[0]['eventType'] == 'interaction.started'
        assert events[97]['data']['action'] == 'accept'
        assert events[98]['data']['correctsEventId'] == events[97]['eventId']
        assert events[99]['eventType'] == 'interaction.completed'
        assert [e['occurredAt'] for e in events] == sorted(e['occurredAt'] for e in events)
        for event in events:
            validator.validate(event)
            assert len(event['eventId']) <= 64 and len(event['interactionId']) <= 64
            assert event['eventId'] not in identifiers
            identifiers.add(event['eventId'])
            counts[event['eventType']] += 1
    assert len(identifiers) == 10000
    assert counts == {'interaction.started': 100, 'model.output_generated': 9600,
                      'review.completed': 100, 'record.corrected': 100, 'interaction.completed': 100}


@pytest.fixture
def small_dataset(monkeypatch):
    monkeypatch.setattr(capacity, 'INTERACTIONS', 1)
    monkeypatch.setenv('TRACEAI_API_TOKEN', 'synthetic-local-token')
    return capacity.manifest(RUN)


def exchange(corrupt=None, post_status=201):
    seen = []
    events = capacity.interaction_events(RUN, 0)
    history, report = capacity.expected_views(events)
    if corrupt:
        corrupt(history, report)
    def handler(request):
        seen.append(request)
        assert request.headers['Authorization'] == 'Bearer synthetic-local-token'
        if request.url.path == '/health':
            return httpx.Response(200, headers={'X-TraceAI-Contract': '0.4.2'})
        if request.method == 'POST':
            body = json.loads(request.content)
            return httpx.Response(post_status, json={'eventId': body['eventId'], 'interactionId': body['interactionId'],
                                                     'stored': True, 'duplicate': post_status == 200})
        return httpx.Response(200, json=report if request.url.path.endswith('/report') else history)
    return handler, seen


def invoke(tmp_path, mode, handler, *extra):
    report = tmp_path / f'{mode}-results.json'
    code = capacity.main([mode, '--base-url', BASE, '--manifest', str(tmp_path/'manifest.json'),
                          '--report', str(report), *extra], transport=httpx.MockTransport(handler))
    return code, json.loads(report.read_text())


def test_seed_then_read_only_verify(small_dataset, tmp_path):
    handler, seen = exchange()
    code, result = invoke(tmp_path, 'seed', handler, '--run-id', RUN, '--allow-isolated-load')
    assert code == 0 and result['acknowledged_new_events'] == 100
    assert result['verification']['verified_events_in_both_views'] == 100
    assert result['performance_verdict'] == 'not_measured' and result['reset_performed'] is False
    assert len([r for r in seen if r.method == 'POST']) == 100
    assert all(r.url.path != '/api/v1/test/reset' for r in seen)
    seen.clear()
    code, result = invoke(tmp_path, 'verify', handler)
    assert code == 0 and all(r.method == 'GET' for r in seen)
    assert capacity.load_manifest(tmp_path/'manifest.json') == small_dataset


@pytest.mark.parametrize('target', ['https://traceai-zm1t.onrender.com', 'http://peer.test:8000',
    'http://127.0.0.1:8000?token=private', 'http://user:password@127.0.0.1:8000',
    'http://127.0.0.1:8000/path', 'http://127.0.0.1'])
def test_remote_or_ambiguous_targets_blocked_without_network(tmp_path, monkeypatch, target):
    monkeypatch.setenv('TRACEAI_API_TOKEN', 'synthetic-local-token')
    def unexpected(request):
        pytest.fail('Rejected target must not receive any HTTP request')
    report = tmp_path/'report.json'
    assert capacity.main(['seed', '--base-url', target, '--manifest', str(tmp_path/'manifest.json'),
                          '--report', str(report), '--allow-isolated-load'], transport=httpx.MockTransport(unexpected)) == 1
    result = json.loads(report.read_text())
    assert result['status'] == 'blocked' and result['capacity_verdict'] == 'not_verified'
    assert 'password' not in json.dumps(result)


def test_load_requires_explicit_isolated_database_confirmation(small_dataset, tmp_path):
    handler, seen = exchange()
    code, result = invoke(tmp_path, 'seed', handler)
    assert code == 1 and result['status'] == 'blocked' and seen == []


@pytest.mark.parametrize('corruption', ['missing', 'changed', 'order', 'review', 'link', 'warning', 'metadata', 'boolean'])
def test_verifier_detects_each_kind_of_corruption(small_dataset, tmp_path, corruption):
    def corrupt(history, report):
        if corruption == 'missing': history['events'].pop(4)
        if corruption == 'changed': history['events'][5]['data']['reference'] = 'changed'
        if corruption == 'order': history['events'][4:6] = history['events'][4:6][::-1]
        if corruption == 'review': report['reviewActions'][0]['reason'] = 'overwritten'
        if corruption == 'link': report['corrections'][0]['linkValid'] = False
        if corruption == 'warning': history['warnings'] = []
        if corruption == 'metadata': report['metadata']['eventCount'] = 99
        if corruption == 'boolean': history['events'][5]['data']['synthetic'] = 1
    capacity.write_json(tmp_path/'manifest.json', small_dataset)
    handler, _ = exchange(corrupt)
    code, result = invoke(tmp_path, 'verify', handler)
    assert code == 1 and result['status'] == 'failed'
    assert result['verification']['verified_events_in_both_views'] == 0
    assert result['capacity_verdict'] == 'not_verified'


def test_manifest_tampering_is_rejected_before_network(small_dataset, tmp_path):
    small_dataset['event_count'] -= 1
    capacity.write_json(tmp_path/'manifest.json', small_dataset)
    handler, seen = exchange()
    code, result = invoke(tmp_path, 'verify', handler)
    assert code == 1 and result['status'] == 'blocked' and seen == []


def test_duplicate_receipt_is_not_a_new_capacity_load(small_dataset, tmp_path):
    handler, seen = exchange(post_status=200)
    code, result = invoke(tmp_path, 'seed', handler, '--run-id', RUN, '--allow-isolated-load')
    assert code == 1 and result['status'] == 'failed'
    assert result['acknowledged_new_events'] == 0 and result['capacity_verdict'] == 'not_verified'
    assert len(seen) == 2


def test_timeout_is_not_retried_or_reflected(small_dataset, tmp_path):
    seen = []
    def offline(request):
        seen.append(request)
        raise httpx.ReadTimeout('synthetic-local-token private traceback')
    code, result = invoke(tmp_path, 'seed', offline, '--run-id', RUN, '--allow-isolated-load')
    assert code == 1 and len(seen) == 1
    assert 'synthetic-local-token' not in json.dumps(result)
    assert result['capacity_verdict'] == 'not_verified'


def test_existing_manifest_is_not_overwritten_or_reseeded(small_dataset, tmp_path):
    capacity.write_json(tmp_path/'manifest.json', small_dataset)
    handler, seen = exchange()
    code, result = invoke(tmp_path, 'seed', handler, '--allow-isolated-load')
    assert code == 1 and seen == []
    assert capacity.load_manifest(tmp_path/'manifest.json') == small_dataset



def test_partial_load_preserves_acknowledgements_without_claiming_capacity(small_dataset, tmp_path):
    handler, seen = exchange()
    def fail_second(request):
        if request.method == 'POST' and len(seen) == 2:
            seen.append(request)
            return httpx.Response(503, json={'private': 'synthetic-local-token'})
        return handler(request)
    code, result = invoke(tmp_path, 'seed', fail_second, '--run-id', RUN, '--allow-isolated-load')
    assert code == 1 and result['acknowledged_new_events'] == 1
    assert result['capacity_verdict'] == 'not_verified'
    assert 'synthetic-local-token' not in json.dumps(result)
    assert len((tmp_path/'manifest.receipts.jsonl').read_text().splitlines()) == 1


def test_redirects_are_not_followed(small_dataset, tmp_path):
    seen = []
    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={'Location': 'https://unapproved.test'})
    code, result = invoke(tmp_path, 'seed', redirect, '--run-id', RUN, '--allow-isolated-load')
    assert code == 1 and len(seen) == 1 and result['capacity_verdict'] == 'not_verified'



def test_colliding_report_cannot_destroy_manifest(small_dataset, tmp_path):
    path = tmp_path/'manifest.json'
    capacity.write_json(path, small_dataset)
    with pytest.raises(SystemExit) as exc:
        capacity.main(['verify', '--base-url', BASE, '--manifest', str(path), '--report', str(path)])
    assert exc.value.code == 2
    assert capacity.load_manifest(path) == small_dataset
