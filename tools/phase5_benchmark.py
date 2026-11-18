#!/usr/bin/env python3
"""Fixed local Phase 5 benchmark: 1000 retrievals, ten clients, no writes/retries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys
import threading
from time import perf_counter

import httpx
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capacity_orchestration', ROOT/'tools/check_phase5_capacity.py')
isolation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolation)
capacity = isolation.capacity
TOTAL = 1000
CLIENTS = 10
THRESHOLD_SECONDS = 1.0
REQUIRED_FAST = 950


def server_seconds(header):
    """Accept one unambiguous, finite, nonnegative application duration in ms."""
    metrics = [part.strip() for part in (header or '').split(',')
               if part.split(';', 1)[0].strip() == 'traceai_app']
    if len(metrics) != 1:
        return None
    match = re.fullmatch(r'traceai_app\s*;\s*dur\s*=\s*([0-9]+(?:\.[0-9]+)?)', metrics[0])
    if not match:
        return None
    try:
        value = float(Decimal(match[1]) / Decimal(1000))
        return value if math.isfinite(value) and value >= 0 else None
    except (InvalidOperation, OverflowError):
        return None


def percentiles(values):
    ordered = sorted(values)
    if not ordered:
        return {'count': 0, 'p50': None, 'p95': None, 'p99': None, 'max': None}
    return {'count': len(ordered), **{name: ordered[math.ceil(p * len(ordered)) - 1]
            for name, p in (('p50', .50), ('p95', .95), ('p99', .99))}, 'max': ordered[-1]}


def workload(data):
    jobs = []
    for round_number in range(5):
        for index, entry in enumerate(data['interactions']):
            for operation, suffix in (('history', ''), ('report', '/report')):
                jobs.append({'sequence': len(jobs), 'round': round_number + 1, 'interaction_index': index,
                             'interaction_id': entry['interaction_id'], 'operation': operation,
                             'path': '/api/v1/interactions/' + entry['interaction_id'] + suffix})
    return jobs


class Inflight:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def begin(self):
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def end(self):
        with self.lock:
            self.active -= 1


def timed_request(http, job, data, schemas, inflight):
    result = {key: value for key, value in job.items() if key not in ('path', 'interaction_index')}
    result.update(http_status=None, correct=False, server_seconds=None, timing_error=None, problem=None)
    inflight.begin()
    started = perf_counter()
    try:
        response = http.get(job['path'])  # Buffered full body; no retry loop or redirect following.
    except httpx.HTTPError:
        result['problem'] = 'HTTP communication failure; not retried.'
        result['timing_error'] = 'No response timing available.'
        return result
    finally:
        result['client_seconds'] = perf_counter() - started
        inflight.end()
    result['http_status'] = response.status_code
    duration = server_seconds(response.headers.get('Server-Timing'))
    if duration is None:
        result['timing_error'] = 'Missing, malformed or ambiguous application timing.'
    elif duration > result['client_seconds'] + .001:
        result['timing_error'] = 'Application timing exceeds client duration beyond 1 ms tolerance.'
    else:
        result['server_seconds'] = duration
    try:
        body = capacity.checked_body(response, 200, schemas[job['operation']])
        observed = capacity.digest(body)
        result['response_sha256'] = observed
        expected = data['interactions'][job['interaction_index']][job['operation'] + '_sha256']
        if observed != expected:
            raise capacity.CapacityError('Response differs from the manifest snapshot.')
        result['correct'] = True
    except capacity.CapacityError as exc:
        result['problem'] = str(exc)
    return result


def run_workload(http, jobs, data, contract):
    schemas = {name: capacity.validator(contract, path, 'get', 200) for name, path in (
        ('history', '/api/v1/interactions/{interactionId}'),
        ('report', '/api/v1/interactions/{interactionId}/report'))}
    inflight = Inflight()
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        results = list(pool.map(lambda job: timed_request(http, job, data, schemas, inflight), jobs))
    return results, {'worker_limit': CLIENTS, 'maximum_observed_inflight_http_requests': inflight.maximum,
                     'wall_seconds_including_client_validation': perf_counter() - started}


def summarize(rows, execution, integrity):
    plan_complete = (len(rows) == TOTAL and {row['sequence'] for row in rows} == set(range(TOTAL))
                     and sum(row['operation'] == 'history' for row in rows) == 500
                     and sum(row['operation'] == 'report' for row in rows) == 500
                     and 0 < execution['maximum_observed_inflight_http_requests'] <= CLIENTS
                     and execution['worker_limit'] == CLIENTS)
    valid = [row['server_seconds'] for row in rows if row['server_seconds'] is not None]
    client = [row['client_seconds'] for row in rows]
    correct = sum(row['correct'] for row in rows)
    fast = sum(row['correct'] and row['server_seconds'] is not None and row['server_seconds'] <= THRESHOLD_SECONDS for row in rows)
    measurement_complete = plan_complete and len(valid) == TOTAL
    if not measurement_complete:
        verdict = 'measurement_incomplete'
    elif not integrity or correct != TOTAL or fast < REQUIRED_FAST:
        verdict = 'failed'
    else:
        verdict = 'passed_for_this_isolated_profile'
    return {'denominator': TOTAL, 'scheduled_results': len(rows), 'plan_complete': plan_complete,
            'measurement_complete': measurement_complete, 'valid_server_measurements': len(valid),
            'missing_or_invalid_server_measurements': TOTAL - len(valid),
            'correct_responses': correct, 'incorrect_or_missing_responses': TOTAL - correct,
            'fast_correct_responses': fast, 'required_fast_correct_responses': REQUIRED_FAST,
            'fast_correct_fraction': fast / TOTAL,
            'server_durations_over_one_second': sum(value > THRESHOLD_SECONDS for value in valid),
            'integrity_before_and_after': integrity, 'performance_verdict': verdict,
            'seconds': {'application': percentiles(valid), 'client_end_to_end': percentiles(client)},
            'by_operation': {name: {'application_seconds': percentiles([row['server_seconds'] for row in rows
                if row['operation'] == name and row['server_seconds'] is not None]),
                'client_end_to_end_seconds': percentiles([row['client_seconds'] for row in rows if row['operation'] == name])}
                for name in ('history', 'report')}}


class ObservedReads:
    """Retain unscored readiness/integrity timings separately from the 1000 requests."""
    def __init__(self, http):
        self.http = http
        self.observations = []

    def get(self, path):
        started = perf_counter()
        response = self.http.get(path)
        self.observations.append({'path': path, 'http_status': response.status_code,
                                  'client_seconds': perf_counter() - started,
                                  'server_seconds': server_seconds(response.headers.get('Server-Timing'))})
        return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-isolated-benchmark', action='store_true')
    parser.add_argument('--manifest', type=Path, default=ROOT/'docs/phase-5-capacity-manifest.json')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/phase5-performance.json')
    args = parser.parse_args(argv)
    if args.manifest.resolve() in (args.report.resolve(), args.report.with_name(args.report.name + '.tmp').resolve()):
        parser.error('Report must not overwrite the seed manifest.')
    evidence = {'schema_version': 1, 'started_at': capacity.now(), 'status': 'blocked', 'scope': 'local isolated retained capacity dataset',
                'capacity_verdict': 'not_verified', 'performance_verdict': 'not_measured', 'reset_or_seed_performed': False, 'problems': []}
    engine = None
    try:
        if not args.allow_isolated_benchmark:
            raise capacity.CapacityError('Confirm the dedicated local database with --allow-isolated-benchmark.')
        database = os.environ.get('TRACEAI_DATABASE_URL', '')
        if not database or database != os.environ.get('TRACEAI_TEST_DATABASE_URL'):
            raise capacity.CapacityError('Supply matching explicit benchmark database URLs.')
        url = make_url(database)
        if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', '::1', 'localhost')
                or not url.database or not url.database.endswith('_test')):
            raise capacity.CapacityError('Benchmark requires a local PostgreSQL database ending in _test.')
        data = capacity.load_manifest(args.manifest)
        jobs = workload(data)
        if len(jobs) != TOTAL:
            raise capacity.CapacityError('Manifest must provide the complete 1000-request plan.')
        engine = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 3, 'options': '-c statement_timeout=5000'})
        before = isolation.database_snapshot(engine)
        groups = {entry['interaction_id']: 100 for entry in data['interactions']}
        if before['migration'] != '0001_events' or before['events_by_interaction'] != groups:
            raise capacity.CapacityError('Retained database inventory differs from the capacity manifest; no reset or seed was attempted.')
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        env = {**os.environ, 'TRACEAI_API_TOKEN': secrets.token_urlsafe(32), 'TRACEAI_RESET_TOKEN': secrets.token_urlsafe(32),
               'TRACEAI_TEST_RESET_ENABLED': 'false', 'RENDER_GIT_COMMIT': revision}
        evidence.update(status='running', code_revision=revision, benchmark_sha256=capacity.file_digest(__file__),
                        profile_sha256=capacity.file_digest(capacity.PROFILE), manifest_sha256=capacity.file_digest(args.manifest),
                        run_id=data['run_id'], database={'name': url.database, 'host': url.host, 'port': url.port or 5432},
                        before=before, runtime={'python': platform.python_version(), 'platform': platform.platform(),
                            'cpu_count': os.cpu_count(), 'application_workers': 1, 'sqlalchemy_pool_size': 5,
                            'sqlalchemy_max_overflow': 10, 'clients': CLIENTS, 'response_cache': 'none',
                            'topology': 'client threads, application process and local PostgreSQL container share this machine'})
        contract = json.loads(capacity.CONTRACT.read_text())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with isolation.server(env, args.report.with_suffix('.server.log')) as base:
            evidence['base_url'] = base
            with httpx.Client(base_url=base, headers={'Authorization': 'Bearer ' + env['TRACEAI_API_TOKEN']},
                              limits=httpx.Limits(max_connections=CLIENTS, max_keepalive_connections=CLIENTS),
                              timeout=30, follow_redirects=False) as http:
                observed = ObservedReads(http)
                health = observed.get('/health')
                if health.status_code != 200 or health.headers.get('X-TraceAI-Revision') != revision:
                    raise capacity.CapacityError('Readiness did not confirm the benchmark code revision.')
                evidence['warmup_integrity'] = capacity.verify(observed, data, contract)
                evidence['warmup_observations'] = observed.observations
                if evidence['warmup_integrity']['status'] != 'passed':
                    raise capacity.CapacityError('Pre-benchmark full-record verification failed.')
                evidence['capacity_verdict'] = 'passed_for_this_isolated_dataset'
                print('Warmup: all 10000 retained records verified; starting 1000 requests with ten clients.', flush=True)
                evidence['timed_started_at'] = capacity.now()
                rows, execution = run_workload(http, jobs, data, contract)
                evidence.update(requests=rows, execution=execution, timed_finished_at=capacity.now())
                observed_after = ObservedReads(http)
                evidence['after_integrity'] = capacity.verify(observed_after, data, contract)
                evidence['after_observations'] = observed_after.observations
        after = isolation.database_snapshot(engine)
        evidence['after'] = after
        integrity = evidence['after_integrity']['status'] == 'passed' and after == before
        evidence['summary'] = summarize(rows, execution, integrity)
        evidence['performance_verdict'] = evidence['summary']['performance_verdict']
        evidence['status'] = 'passed' if evidence['performance_verdict'] == 'passed_for_this_isolated_profile' else 'failed'
        if not integrity:
            evidence['capacity_verdict'] = 'failed_after_benchmark'
    except Exception as exc:
        evidence['status'] = 'failed' if evidence['status'] == 'running' else 'blocked'
        evidence['problems'].append(str(exc) if isinstance(exc, capacity.CapacityError) else
                                    'Local benchmark failed; inspect saved stage evidence.')
    finally:
        if engine is not None:
            engine.dispose()
    evidence['finished_at'] = capacity.now()
    capacity.write_json(args.report, evidence)
    print(f'Performance: {evidence["performance_verdict"]}. Evidence: {args.report}')
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
