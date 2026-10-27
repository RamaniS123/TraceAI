#!/usr/bin/env python3
"""Exercise a deployed tester and system the way course staff grade them.

Usage: python tools/check_testing_interface.py --tester https://host/tester --target https://host
Calls tester setup with the target, runs the suite once, re-reads the stored report, and reads
the system report. Exits 0 when every response is well formed (and, with --require-pass, when
every test passed). Needs no credentials: the tester holds its own access to the target.
"""
import argparse
import sys

import httpx

OUTCOMES = {'pass', 'fail', 'error', 'skip'}
SOURCES = {'tester', 'system', 'communication', 'unknown'}


def measure_problems(name, measure):
    if not isinstance(measure, dict) or not isinstance(measure.get('basis'), str) or not measure['basis']:
        return [f'coverage.{name} needs a nonempty basis']
    covered, total = measure.get('covered'), measure.get('total')
    if covered is None and total is None:
        return []
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (covered, total)) or covered > total:
        return [f'coverage.{name} counts must be nonnegative integers with covered <= total, or both null']
    return []


def report_problems(report, session_id, target):
    found = []
    if report.get('session_id') != session_id:
        found.append('report session_id does not match')
    if report.get('target_url') not in (target, target.rstrip('/')):
        found.append('report target_url does not match')
    results = report.get('results')
    if not isinstance(results, list) or not results:
        return found + ['report has no results']
    ids = [row.get('test_id') for row in results]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        found.append('test_id values must be unique and nonempty')
    for row in results:
        if row.get('outcome') not in OUTCOMES or not row.get('message'):
            found.append(f"{row.get('test_id')}: needs a valid outcome and nonempty message")
        if row.get('outcome') == 'error' and row.get('source') not in SOURCES:
            found.append(f"{row.get('test_id')}: error results need a valid source")
    coverage = report.get('coverage') or {}
    for name in ('code', 'component', 'system'):
        found += measure_problems(name, coverage.get(name))
    return found


def main(argv=None, *, transport=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tester', required=True, help='Tester base URL, e.g. https://host/tester')
    parser.add_argument('--target', required=True, help='Target system base URL')
    parser.add_argument('--timeout', type=float, default=600, help='Seconds to wait for setup and for the run')
    parser.add_argument('--require-pass', action='store_true', help='Also fail unless every test passed')
    args = parser.parse_args(argv)
    tester, target = args.tester.rstrip('/'), args.target.rstrip('/')
    with httpx.Client(timeout=args.timeout, transport=transport) as http:
        setup = http.post(tester + '/test/setup', json={'target_url': target})
        print(f'tester setup -> HTTP {setup.status_code}: {setup.text[:300]}')
        if setup.status_code != 201:
            return 1
        session_id = setup.json()['session_id']
        run = http.post(tester + '/test/run', json={'session_id': session_id})
        print(f'tester run -> HTTP {run.status_code}')
        stored = http.get(tester + '/test/report', params={'session_id': session_id})
        print(f'tester report -> HTTP {stored.status_code}')
        system = http.get(target + '/test/report', params={'session_id': session_id})
        print(f'system report -> HTTP {system.status_code}: {system.text[:300]}')
    if stored.status_code != 200:
        return 1
    report = stored.json()
    problems = report_problems(report, session_id, target)
    if run.status_code == 200 and run.json() != report:
        problems.append('stored report differs from the run response')
    if system.status_code != 200 or 'code' not in (system.json().get('coverage') or {}):
        problems.append('system report is missing coverage.code')
    counts = {o: sum(row.get('outcome') == o for row in report.get('results', [])) for o in sorted(OUTCOMES)}
    print('outcomes: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print('coverage: ' + ', '.join(f"{k} {v.get('covered')}/{v.get('total')}" for k, v in (report.get('coverage') or {}).items()))
    for row in report.get('results', []):
        if row.get('outcome') != 'pass':
            print(f"  {row.get('test_id')}: {row.get('outcome')} ({row.get('source', '-')}) {row.get('message')}")
    for problem in problems:
        print('FORMAT PROBLEM: ' + problem)
    if problems or (args.require_pass and counts['pass'] != len(report.get('results', []))):
        return 1
    print('OK: well-formed report' + (' and every test passed' if args.require_pass else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
