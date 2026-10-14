#!/usr/bin/env python3
"""Black-box Phase 3 checks. No application or database imports are used."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import httpx
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


class CheckFailure(Exception):
    pass


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def configuration(args):
    if not args.allow_test_reset:
        raise ValueError('Pass --allow-test-reset only for an isolated test dataset; this suite deletes its data.')
    try:
        parsed = urlsplit(args.base_url)
        _ = parsed.port  # Validate malformed ports without exposing the supplied URL.
        valid = (parsed.scheme in ('http', 'https') and parsed.hostname and
                 not parsed.username and not parsed.password and not parsed.query and
                 not parsed.fragment and parsed.path in ('', '/'))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Base URL must be an HTTP(S) service origin without credentials, path, query, or fragment.')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Remote services require HTTPS; plain HTTP is supported only on loopback.')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('--timeout must be a positive finite number.')
    if not math.isfinite(args.wait_seconds) or not 0 <= args.wait_seconds <= 60:
        raise ValueError('--wait-seconds must be between 0 and 60.')
    values = {}
    if args.env_file:
        path = Path(args.env_file)
        if not path.is_file():
            raise ValueError('The requested environment file is unavailable.')
        values.update(dotenv_values(path))
    values.update(os.environ)
    tokens = {name: values.get(key) for name, key in
              [('api', 'TRACEAI_API_TOKEN'), ('reset', 'TRACEAI_RESET_TOKEN')]}
    if any(not value or not value.isascii() or any(c.isspace() for c in value) for value in tokens.values()):
        raise ValueError('Set nonempty ASCII TRACEAI_API_TOKEN and TRACEAI_RESET_TOKEN without whitespace.')
    if tokens['api'] == tokens['reset']:
        raise ValueError('API and reset tokens must be distinct.')
    invalid = 'invalid-synthetic-token'
    while invalid in tokens.values():
        invalid += '-invalid'
    tokens['invalid'] = invalid
    return args.base_url.rstrip('/'), tokens


def planned_checks(root):
    steps = read_json(root / 'tests/fixtures/phase-3-scenario.json')['steps']
    checks = [{'name': f'scenario-{index:02d}', **step} for index, step in enumerate(steps, 1)]
    for path in ('/api/v1/events', '/api/v1/test/reset'):
        for auth in ('none', 'invalid'):
            checks.append(dict(name=f'authentication-{path.rsplit("/", 1)[-1]}-{auth}',
                               method='POST', path=path, auth=auth, rawBody='{', expectedStatus=401))
    for size, status in ((65536, 201), (65537, 413)):
        checks.append(dict(name=f'boundary-{size}-reset', method='POST', path='/api/v1/test/reset',
                           auth='reset', body={'confirm': True}, expectedStatus=200,
                           expectedBody={'reset': True, 'remainingEvents': 0, 'remainingInteractions': 0}))
        raw = (root / f'tests/fixtures/event-{size}-bytes.json').read_bytes()
        if len(raw) != size:
            raise ValueError('A byte-boundary fixture has been modified; restore its exact contents.')
        checks.append(dict(name=f'boundary-{size}-submit', method='POST', path='/api/v1/events',
                           auth='api', rawBytes=raw, expectedStatus=status))
        lookup = dict(name=f'boundary-{size}-storage', method='GET', path='/api/v1/interactions/int-size',
                      auth='api', expectedStatus=200 if status == 201 else 404)
        if status == 201:
            lookup['expectedBody'] = {'interactionId': 'int-size', 'status': 'in_progress',
                                      'events': [json.loads(raw)], 'warnings': []}
        checks.append(lookup)
    return checks


def check_response(response, check, contract):
    if response.status_code != check['expectedStatus']:
        raise CheckFailure(f"Expected HTTP {check['expectedStatus']}; received {response.status_code}.")
    if response.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise CheckFailure('Expected an application/json response.')
    try:
        body = json.loads(response.content.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise CheckFailure('Response is not valid UTF-8 JSON.') from None
    path = check['path']
    if path.startswith('/api/v1/interactions/'):
        path = '/api/v1/interactions/{interactionId}'
    schema = contract['paths'][path][check['method'].lower()]['responses'][str(response.status_code)]['content']['application/json']['schema']
    validator = Draft202012Validator({**schema, 'components': contract['components']}, format_checker=FormatChecker())
    if next(validator.iter_errors(body), None) is not None:
        raise CheckFailure('Response does not match the API contract schema.')
    if 'expectedBody' in check and body != check['expectedBody']:
        raise CheckFailure('Response content differs from the shared fixture.')


def send(client, origin, tokens, check, contract):
    headers = {}
    if check['auth'] != 'none':
        headers['Authorization'] = 'Bearer ' + tokens[check['auth']]
    kwargs = {'headers': headers}
    if 'body' in check:
        kwargs['json'] = check['body']
    if 'rawBody' in check or 'rawBytes' in check:
        kwargs['content'] = check.get('rawBytes', check.get('rawBody'))
        headers['Content-Type'] = 'application/json'
    try:
        response = client.request(check['method'], origin + check['path'], **kwargs)
    except httpx.HTTPError as exc:
        raise CheckFailure(f'HTTP request failed ({type(exc).__name__}).') from None
    check_response(response, check, contract)


def run_suite(client, origin, tokens, checks, contract, wait_seconds=0):
    # Readiness polling is read-only; do not send any reset before health passes.
    if wait_seconds:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                send(client, origin, tokens, checks[0], contract)
                break
            except CheckFailure:
                if time.monotonic() >= deadline:
                    break  # The first named check records the actual failure.
                time.sleep(min(.2, max(0, deadline - time.monotonic())))
    results = []
    stopped = False
    attempted_write = False
    for check in checks:
        result = {'name': check['name'], 'status': 'unrun' if stopped else 'passed'}
        if not stopped:
            attempted_write |= check['method'] == 'POST'
            try:
                send(client, origin, tokens, check, contract)
            except CheckFailure as exc:
                result.update(status='failed', message=str(exc))
                stopped = True
        results.append(result)
    cleanup = {'name': 'final-cleanup', 'status': 'unrun'}
    if attempted_write:
        try:
            send(client, origin, tokens, dict(method='POST', path='/api/v1/test/reset', auth='reset',
                 body={'confirm': True}, expectedStatus=200,
                 expectedBody={'reset': True, 'remainingEvents': 0, 'remainingInteractions': 0}), contract)
            cleanup['status'] = 'passed'
        except CheckFailure as exc:
            cleanup.update(status='failed', message=str(exc))
    results.append(cleanup)
    return results



def finish(results, started, report_path):
    counts = {status: sum(row['status'] == status for row in results) for status in ('passed', 'failed', 'unrun')}
    report = dict(runId=str(uuid4()), startedAt=started, finishedAt=datetime.now(timezone.utc).isoformat(),
                  status='passed' if not counts['failed'] and not counts['unrun'] else 'failed',
                  total=len(results), **counts, checks=results)
    if report_path:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        except OSError:
            print('Could not write the requested report.', file=sys.stderr)
            return 2
    print(f"{report['status'].upper()}: {counts['passed']} passed, {counts['failed']} failed, {counts['unrun']} unrun ({len(results)} checks)")
    for result in results:
        if result['status'] == 'failed':
            print(f"  {result['name']}: {result['message']}")
    return 0 if report['status'] == 'passed' else 1


def main(argv=None, *, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='Service origin, without /api/v1')
    parser.add_argument('--allow-test-reset', action='store_true', help='Explicitly authorize deletion of this isolated test dataset')
    parser.add_argument('--env-file', help='Optional local credentials file; process environment takes precedence')
    parser.add_argument('--timeout', type=float, default=5, help='Per-request timeout in seconds')
    parser.add_argument('--wait-seconds', type=float, default=0, help='Read-only readiness wait, at most 60 seconds')
    parser.add_argument('--report', type=Path, help='Write a sanitized JSON result file')
    args = parser.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    try:
        origin, tokens = configuration(args)
        checks = planned_checks(ROOT)
        contract = read_json(ROOT / 'contracts/openapi.json')
    except (ValueError, OSError):
        # Keep credential values, file paths, and raw exception strings out of logs.
        print('Configuration error: supply a valid service origin, distinct tokens, intact fixtures, and --allow-test-reset. See --help.', file=sys.stderr)
        if args.report:
            finish([{'name': 'configuration', 'status': 'failed', 'message': 'Invalid runner configuration.'}], started, args.report)
        return 2
    with httpx.Client(timeout=args.timeout, follow_redirects=False, transport=transport) as client:
        results = run_suite(client, origin, tokens, checks, contract, args.wait_seconds)
    return finish(results, started, args.report)


if __name__ == '__main__':
    raise SystemExit(main())
