#!/usr/bin/env python3
"""Destructive LOCAL checks: separate processes, persistent PostgreSQL, safe logs.

Requires an explicitly supplied migrated *_test database; uses only local HTTP servers.
No failure-injection HTTP endpoints are added to the deployed service.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def server(env, logs):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryFile(mode='w+b') as output:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'traceai.main:create_app',
                                    '--factory', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=ROOT, env={**env, 'TRACEAI_PUBLIC_URL':base}, stdout=output, stderr=output)
        try:
            with httpx.Client(base_url=base, timeout=10, trust_env=False) as http:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Local server exited')
                    try:
                        if http.get('/openapi.json').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('Local server startup timed out')
                yield http
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            output.seek(0)
            logs.append(output.read().decode('utf-8', errors='replace'))


def require(condition):
    if not condition:
        raise AssertionError('Local reliability check failed')


def run(url):
    token, reset, canary = [secrets.token_urlsafe(32) for _ in range(3)]
    env = {**os.environ, 'TRACEAI_DATABASE_URL':url.render_as_string(hide_password=False),
           'TRACEAI_API_TOKEN':token, 'TRACEAI_RESET_TOKEN':reset, 'TRACEAI_TEST_RESET_ENABLED':'true'}
    api_headers, reset_headers = {'Authorization':'Bearer '+token}, {'Authorization':'Bearer '+reset}
    logs, results = [], []
    events = json.loads((ROOT / 'tests/fixtures/valid-events.json').read_text())
    events[0]['data'] = {'syntheticCanary':canary}
    before = {}
    with server(env, logs) as http:
        require(http.post('/api/v1/test/reset', headers=reset_headers, json={'confirm':True}).status_code == 200)
        for item in events:
            require(http.post('/api/v1/events', headers=api_headers, json=item).status_code == 201)
        for identifier in sorted({item['interactionId'] for item in events}):
            response = http.get('/api/v1/interactions/'+identifier+'/report', headers=api_headers)
            require(response.status_code == 200)
            before[identifier] = response.json()
        response = http.get('/api/v1/interactions/'+canary+'?token='+canary)
        require(response.status_code == 401 and canary not in response.text)
        response = http.post('/api/v1/events', headers={**api_headers,'Content-Type':'application/json'},
                             content='{"private":"'+canary+'",}')
        require(response.status_code == 400 and canary not in response.text)
        results.append({'test_id':'local-safe-client-errors','outcome':'pass'})
    # An entirely new Uvicorn process and SQLAlchemy pool reads the same database.
    with server(env, logs) as http:
        for identifier, expected in before.items():
            response = http.get('/api/v1/interactions/'+identifier+'/report', headers=api_headers)
            require(response.status_code == 200 and response.json() == expected)
        for item in events:
            response = http.post('/api/v1/events', headers=api_headers, json=item)
            require(response.status_code == 200 and response.json()['duplicate'] is True)
        results.append({'test_id':'local-process-restart-preserves-history','outcome':'pass'})
        # Reset is opt-in and affects only the explicitly named test DB.
        require(http.post('/api/v1/test/reset', headers=reset_headers, json={'confirm':True}).status_code == 200)
    # Independently unreachable storage: API remains reachable but cannot acknowledge writes.
    down = {**env, 'TRACEAI_DATABASE_URL':url.set(host='127.0.0.1',port=1).render_as_string(hide_password=False)}
    with server(down, logs) as http:
        health = http.get('/health')
        require(health.status_code == 503 and health.json()['storage'] == 'unavailable')
        for method, path, body, headers in [
            ('POST','/api/v1/events',events[0],api_headers),
            ('GET','/api/v1/interactions/int-a',None,api_headers),
            ('GET','/api/v1/interactions/int-a/report',None,api_headers),
            ('POST','/api/v1/test/reset',{'confirm':True},reset_headers),
        ]:
            response = http.request(method,path,json=body,headers=headers)
            require(response.status_code == 503 and response.json()['error']['code'] == 'STORAGE_UNAVAILABLE')
        results.append({'test_id':'local-storage-unavailable-no-success','outcome':'pass'})
    startup = subprocess.run([sys.executable, '-m', 'traceai.startup'], cwd=ROOT, env=down,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    require(startup.returncode == 1)
    logs.append((startup.stdout + startup.stderr).decode('utf-8', errors='replace'))
    results.append({'test_id':'local-startup-failure-safe-exit','outcome':'pass'})
    combined = '\n'.join(logs)
    forbidden = [token,reset,canary,env['TRACEAI_DATABASE_URL'],'Traceback (most recent call last)']
    if url.password and len(url.password) >= 8:
        forbidden.append(url.password)
    require(all(value not in combined for value in forbidden))
    results.append({'test_id':'local-process-log-canaries','outcome':'pass'})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-test-reset', action='store_true')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/local-reliability.json')
    args = parser.parse_args()
    try:
        url = make_url(os.environ.get('TRACEAI_TEST_DATABASE_URL',''))
        require(args.allow_test_reset and bool(url.database) and url.database.endswith('_test'))
        require(url.drivername in ('postgresql+psycopg','postgresql'))
    except Exception:
        print('Requires --allow-test-reset and TRACEAI_TEST_DATABASE_URL for an isolated migrated *_test PostgreSQL DB.', file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc).isoformat()
    try:
        results = run(url)
    except Exception:
        # Never dump a subprocess log, request body, URL or raw exception.
        print('FAIL: local reliability checks did not complete; investigate locally without publishing secrets.', file=sys.stderr)
        return 1
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps({'started_at':started,
                                      'scope':'local-only; not pod or deployed-target coverage',
                                      'results':results},indent=2)+'\n')
    print(f'PASS: {len(results)} local reliability groups (process restart, storage failure, safe errors/logs).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
