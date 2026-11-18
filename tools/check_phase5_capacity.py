#!/usr/bin/env python3
"""Exercise Phase 5 capacity on an explicitly supplied, empty local *_test database.

Starts separate loopback application processes, loads via HTTP and verifies again
following an application restart. No reset or schema/data deletion is performed.
"""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import time

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('phase5_capacity', ROOT / 'tools/phase5_capacity.py')
capacity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capacity)


@contextmanager
def server(env, log_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with log_path.open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'traceai.main:create_app', '--factory',
                                    '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT,
                                   env={**env, 'TRACEAI_PUBLIC_URL': base}, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise capacity.CapacityError('Local application exited before readiness.')
                try:
                    if httpx.get(base + '/health', timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise capacity.CapacityError('Local application did not become healthy.')
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def database_snapshot(engine):
    with engine.connect() as connection:
        groups = dict(connection.execute(text('SELECT interaction_id, count(*) FROM events GROUP BY interaction_id')).all())
        return {'event_count': sum(groups.values()), 'interaction_count': len(groups),
                'events_by_interaction': groups,
                'migration': connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-isolated-load', action='store_true')
    parser.add_argument('--manifest', type=Path, default=ROOT/'reports/phase5-capacity-manifest.json')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/phase5-capacity.json')
    args = parser.parse_args(argv)
    if args.manifest.resolve() == args.report.resolve():
        parser.error('Manifest and report paths must differ.')
    result = {'schema_version': 1, 'started_at': capacity.now(), 'status': 'blocked',
              'scope': 'isolated local PostgreSQL and loopback HTTP only', 'reset_performed': False,
              'capacity_verdict': 'not_verified', 'performance_verdict': 'not_measured', 'problems': []}
    engine = None
    try:
        if not args.allow_isolated_load:
            raise capacity.CapacityError('Confirm the dedicated empty database with --allow-isolated-load.')
        # Do not read the normal .env: isolation must be explicitly supplied to this process.
        database = os.environ.get('TRACEAI_DATABASE_URL', '')
        if not database or database != os.environ.get('TRACEAI_TEST_DATABASE_URL'):
            raise capacity.CapacityError('Supply matching explicit TRACEAI_DATABASE_URL and TRACEAI_TEST_DATABASE_URL.')
        url = make_url(database)
        if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', '::1', 'localhost')
                or not url.database or not url.database.endswith('_test')):
            raise capacity.CapacityError('An explicit local PostgreSQL database ending in _test is required.')
        if args.manifest.exists():
            raise capacity.CapacityError('Manifest already exists; use phase5_capacity.py verify for retained data.')
        engine = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 3, 'options': '-c statement_timeout=5000'})
        before = database_snapshot(engine)
        if before['event_count'] != 0 or before['migration'] != '0001_events':
            raise capacity.CapacityError('Capacity loading requires an empty, correctly migrated isolated database; no reset was attempted.')
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        result.update(status='running', code_revision=revision, profile_sha256=capacity.file_digest(capacity.PROFILE),
                      generator_sha256=capacity.file_digest(capacity.__file__),
                      orchestrator_sha256=capacity.file_digest(__file__),
                      database={'name': url.database, 'host': url.host, 'port': url.port or 5432},
                      before=before, runtime={'python': platform.python_version(), 'platform': platform.platform(),
                                             'cpu_count': os.cpu_count(), 'application_workers': 1,
                                             'sqlalchemy_pool_size': 5, 'sqlalchemy_max_overflow': 10,
                                             'loader_clients': 1, 'response_cache': 'none'})
        with engine.connect() as connection:
            result['database'].update(server_version=connection.execute(text('SHOW server_version')).scalar_one(),
                                      shared_buffers=connection.execute(text('SHOW shared_buffers')).scalar_one(),
                                      max_connections=connection.execute(text('SHOW max_connections')).scalar_one())
        env = {**os.environ, 'TRACEAI_API_TOKEN': secrets.token_urlsafe(32), 'TRACEAI_RESET_TOKEN': secrets.token_urlsafe(32),
               'TRACEAI_TEST_RESET_ENABLED': 'false', 'RENDER_GIT_COMMIT': revision}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        seed_report = args.report.with_name(args.report.stem + '-seed.json')
        restart_report = args.report.with_name(args.report.stem + '-after-restart.json')
        with server(env, args.report.with_suffix('.seed-server.log')) as base:
            subprocess.run([sys.executable, str(ROOT/'tools/phase5_capacity.py'), 'seed', '--base-url', base,
                            '--manifest', str(args.manifest), '--report', str(seed_report), '--allow-isolated-load'],
                           cwd=ROOT, env=env, check=True)
        data = capacity.load_manifest(args.manifest)
        after_seed = database_snapshot(engine)
        expected_groups = {entry['interaction_id']: 100 for entry in data['interactions']}
        if after_seed['events_by_interaction'] != expected_groups:
            raise capacity.CapacityError('Database inventory differs from the seed manifest.')
        result['after_seed'] = after_seed
        with server(env, args.report.with_suffix('.restart-server.log')) as base:
            subprocess.run([sys.executable, str(ROOT/'tools/phase5_capacity.py'), 'verify', '--base-url', base,
                            '--manifest', str(args.manifest), '--report', str(restart_report)], cwd=ROOT, env=env, check=True)
        after_restart = database_snapshot(engine)
        if after_restart != after_seed:
            raise capacity.CapacityError('Database inventory changed across the application restart.')
        result.update(after_restart=after_restart, status='passed', capacity_verdict='passed_for_this_isolated_dataset',
                      seed=json.loads(seed_report.read_text()), after_application_restart=json.loads(restart_report.read_text()),
                      retained_for_chunk4=True, artifacts_sha256={str(path): capacity.file_digest(path) for path in
                          (args.manifest, args.manifest.with_suffix('.receipts.jsonl'), seed_report, restart_report)})
    except Exception as exc:
        result['status'] = 'failed' if result['status'] == 'running' else 'blocked'
        result['problems'].append(str(exc) if isinstance(exc, capacity.CapacityError) else
                                  'Local capacity orchestration failed; inspect the saved stage evidence.')
    finally:
        if engine is not None:
            engine.dispose()
    result['finished_at'] = capacity.now()
    capacity.write_json(args.report, result)
    print(f'Isolated capacity: {result["status"]}; performance not measured. Evidence: {args.report}')
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
