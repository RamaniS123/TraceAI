"""Never infer network-excluded acceptance from absent timing or missing requests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import threading

import httpx
import pytest

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).parents[1]/'tools/phase5_benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
capacity = benchmark.capacity
EXECUTION = {'worker_limit': 10, 'maximum_observed_inflight_http_requests': 10}


@pytest.mark.parametrize('header,expected', [
    (None, None), ('', None), ('db;dur=1', None), ('traceai_app;dur=0', 0),
    ('traceai_app;dur=1000.000001', 1.000000001),
    ('db;dur=2, traceai_app;dur=1.250000', .00125),
    ('traceai_app;dur=-1', None), ('traceai_app;dur=NaN', None),
    ('traceai_app;dur=Infinity', None), ('traceai_app;dur=1e3', None),
    ('traceai_app;dur=1, traceai_app;dur=2', None), ('traceai_app;dur=1;dur=2', None),
    ('traceai_app;dur=wrong', None), ('traceai_app;dur=' + '9'*400, None),
])
def test_application_timing_parser(header, expected):
    assert benchmark.server_seconds(header) == expected


def rows():
    return [{'sequence': i, 'operation': 'history' if i % 2 == 0 else 'report',
             'correct': True, 'server_seconds': .1, 'client_seconds': .2} for i in range(1000)]


def test_workload_uses_every_interaction_and_both_operations_five_times():
    data = capacity.manifest('synthetic123')
    jobs = benchmark.workload(data)
    assert len(jobs) == 1000
    assert [j['sequence'] for j in jobs] == list(range(1000))
    assert {j['round'] for j in jobs} == {1, 2, 3, 4, 5}
    for entry in data['interactions']:
        selected = [j for j in jobs if j['interaction_id'] == entry['interaction_id']]
        assert len(selected) == 10
        assert sum(j['operation'] == 'report' for j in selected) == 5
        assert sum(j['operation'] == 'history' for j in selected) == 5


@pytest.mark.parametrize('fast,verdict', [(950, 'passed_for_this_isolated_profile'), (949, 'failed')])
def test_exact_950_of_1000_threshold(fast, verdict):
    data = rows()
    for row in data[fast:]:
        row['server_seconds'] = 1.000000001
    result = benchmark.summarize(data, EXECUTION, True)
    assert result['performance_verdict'] == verdict
    assert result['denominator'] == 1000 and result['fast_correct_responses'] == fast


@pytest.mark.parametrize('problem', ['missing_metric', 'missing_request', 'wrong_response', 'lost_record', 'excess_clients'])
def test_missing_or_incorrect_evidence_cannot_pass(problem):
    data, execution, integrity = rows(), dict(EXECUTION), True
    if problem == 'missing_metric': data[0]['server_seconds'] = None
    if problem == 'missing_request': data.pop()
    if problem == 'wrong_response': data[0]['correct'] = False
    if problem == 'lost_record': integrity = False
    if problem == 'excess_clients': execution['maximum_observed_inflight_http_requests'] = 11
    result = benchmark.summarize(data, execution, integrity)
    assert result['performance_verdict'] != 'passed_for_this_isolated_profile'
    assert result['denominator'] == 1000
    if problem in ('missing_metric', 'missing_request', 'excess_clients'):
        assert result['measurement_complete'] is False


def test_nearest_rank_percentiles_and_empty_series():
    assert benchmark.percentiles(list(range(1, 1001))) == {'count': 1000, 'p50': 500, 'p95': 950, 'p99': 990, 'max': 1000}
    assert benchmark.percentiles([])['p95'] is None


@pytest.fixture
def small_plan(monkeypatch):
    monkeypatch.setattr(capacity, 'INTERACTIONS', 2)
    data = capacity.manifest('synthetic123')
    return data, benchmark.workload(data), json.loads(capacity.CONTRACT.read_text())


def test_real_worker_pool_caps_requests_at_ten_without_retries(small_plan):
    data, jobs, contract = small_plan
    barrier = threading.Barrier(10)
    lock = threading.Lock()
    calls = []
    views = {}
    for index in range(2):
        history, report = capacity.expected_views(capacity.interaction_events(data['run_id'], index))
        path = '/api/v1/interactions/' + data['interactions'][index]['interaction_id']
        views[path], views[path+'/report'] = history, report
    def handler(request):
        with lock:
            calls.append(request)
            number = len(calls)
        if number <= 10: barrier.wait(timeout=5)
        return httpx.Response(200, json=views[request.url.path], headers={'Server-Timing':'traceai_app;dur=0.000001'})
    with httpx.Client(base_url='http://127.0.0.1:8015', transport=httpx.MockTransport(handler), follow_redirects=False) as http:
        results, execution = benchmark.run_workload(http, jobs, data, contract)
    assert len(calls) == len(jobs) == len(results) == 20
    assert all(r['correct'] and r['server_seconds'] is not None for r in results)
    assert execution['maximum_observed_inflight_http_requests'] == 10
    assert all(r.method == 'GET' for r in calls)


@pytest.mark.parametrize('problem', ['content', 'timeout', 'http', 'implausible_timing'])
def test_request_failure_retains_safe_evidence(small_plan, problem):
    data, jobs, contract = small_plan
    schemas = {name: capacity.validator(contract, path, 'get', 200) for name, path in (
        ('history', '/api/v1/interactions/{interactionId}'), ('report', '/api/v1/interactions/{interactionId}/report'))}
    def handler(request):
        if problem == 'timeout': raise httpx.ReadTimeout('synthetic-secret /srv/private.py')
        if problem == 'http': return httpx.Response(503, json={'private':'synthetic-secret'})
        history = deepcopy(capacity.expected_views(capacity.interaction_events(data['run_id'], 0))[0])
        if problem == 'content': history['events'][0]['data']['reference'] = 'changed'
        timing = 'traceai_app;dur=1000000' if problem == 'implausible_timing' else 'traceai_app;dur=0.000001'
        return httpx.Response(200, json=history, headers={'Server-Timing': timing})
    inflight = benchmark.Inflight()
    with httpx.Client(base_url='http://127.0.0.1:8015', transport=httpx.MockTransport(handler)) as http:
        result = benchmark.timed_request(http, jobs[0], data, schemas, inflight)
    assert result['sequence'] == 0 and result['client_seconds'] >= 0 and inflight.active == 0
    assert 'synthetic-secret' not in json.dumps(result)
    if problem == 'implausible_timing':
        assert result['correct'] is True and result['server_seconds'] is None
    else:
        assert result['correct'] is False
