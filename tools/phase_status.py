#!/usr/bin/env python3
"""Print requirement (Q1.1) and operation (Q3.1) status from an evaluator report.

Usage: python tools/phase_status.py reports/render-api.json --label "Team 106 on Render"
The report comes from tools/run_phase3_api_tests.py; requirement data comes from docs/requirements.json.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CLEANUP = {'name': 'final-cleanup', 'method': 'POST', 'path': '/api/v1/test/reset', 'expectedStatus': 200}


def evaluator_checks(include_timeline=False, include_records=False):
    """The evaluator's own plan, so check names and endpoints never need copying by hand."""
    spec = importlib.util.spec_from_file_location('api_runner', ROOT / 'tools/run_phase3_api_tests.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner.planned_checks(ROOT, include_timeline=include_timeline, include_records=include_records) + [CLEANUP]


def operation_path(path):
    if path.startswith('/api/v1/interactions/'):
        return '/api/v1/interactions/{interactionId}' + ('/report' if path.endswith('/report') else '')
    return path


def problems(data, checks):
    """Names in the data file that no longer match the evaluator or each other."""
    known = {check['name'] for check in checks}
    found = []
    profile_known = {check['name'] for check in evaluator_checks(include_timeline=True, include_records=True)}
    for ac, criterion in data['acceptanceCriteria'].items():
        if criterion['checks'] != 'all':
            found += [f'{ac} refers to unknown check {name}' for name in criterion['checks'] if name not in known]
        for names in criterion.get('profileChecks', {}).values():
            found += [f'{ac} refers to unknown profile check {name}' for name in names if name not in profile_known]
    requirement_ids = {req['id'] for req in data['requirements']}
    for req in data['requirements']:
        found += [f"{req['id']} refers to unknown check {name}" for name in req.get('checks', []) if name not in known]
        found += [f"{req['id']} refers to unknown {ac}" for ac in req['acceptanceCriteria'] if ac not in data['acceptanceCriteria']]
    for op in data['operations']:
        found += [f"{op['method']} {op['path']} refers to unknown {req}" for req in op['requirements'] if req not in requirement_ids]
    return found


def tally(names, results):
    statuses = [results.get(name, 'unrun') for name in names]
    return {'total': len(names), 'passed': statuses.count('passed'),
            'failed': [name for name in names if results.get(name) == 'failed'],
            'unrun': [name for name in names if results.get(name, 'unrun') == 'unrun']}


def criterion_checks(criterion, checks):
    if criterion['checks'] == 'all':
        return [check['name'] for check in checks]
    known = {check['name'] for check in checks}
    extra = [name for names in criterion.get('profileChecks', {}).values() for name in names if name in known]
    return list(dict.fromkeys(criterion['checks'] + extra))


def requirement_entry(req, data, checks, results):
    names, evidence = [], []
    for ac in req['acceptanceCriteria']:
        criterion = data['acceptanceCriteria'][ac]
        ac_names = criterion_checks(criterion, checks)
        names += ac_names
        if ac_names:
            counts = tally(ac_names, results)
            evidence.append(f"{ac} ({counts['passed']}/{counts['total']} checks passed)")
        elif criterion.get('otherEvidence'):
            evidence.append(f"{ac} ({criterion['otherEvidence']}; not part of this run)")
        else:
            evidence.append(f'{ac} (not automated yet)')
    if req.get('checks'):
        names += req['checks']
        counts = tally(req['checks'], results)
        evidence.append(f"{counts['passed']}/{counts['total']} related checks passed")
    counts = tally(list(dict.fromkeys(names)), results)
    gaps = []
    if counts['failed']:
        gaps.append('failing checks: ' + ', '.join(counts['failed']) + '.')
    if counts['unrun']:
        gaps.append(f"{len(counts['unrun'])} check(s) did not run.")
    if req['missing']:
        gaps.append(req['missing'])
    status = 'partial' if gaps else 'complete'
    lines = [f"{req['id']} - {req['name']} | Status: {status} | Demonstrated by: {'; '.join(evidence)}"]
    if gaps:
        lines.append('  If partial: ' + ' '.join(gaps))
    return lines


def conformance(names, results):
    if not names:
        return 'not exercised by this run'
    counts = tally(names, results)
    if counts['failed']:
        return f"no ({len(counts['failed'])} of {counts['total']} checks failed: {', '.join(counts['failed'])})"
    if counts['unrun']:
        return f"not verified ({len(counts['unrun'])} of {counts['total']} checks did not run)"
    return f"yes ({counts['passed']}/{counts['total']} checks)"


def operation_entry(op, contract_paths, checks, results):
    in_contract = op['method'].lower() in contract_paths.get(op['path'], {})
    reqs = ', '.join(op['requirements'])
    if not in_contract:
        return [f"[{op['method']} {op['path']}] | Requirement(s): {reqs} | Implemented: no (planned for Phase {op['plannedPhase']})",
                'Success responses conform: n/a | Error responses conform: n/a']
    mine = [check for check in checks
            if check['method'] == op['method'] and operation_path(check['path']) == op['path']]
    success = [check['name'] for check in mine if check['expectedStatus'] < 400]
    errors = [check['name'] for check in mine if check['expectedStatus'] >= 400]
    tested = tally(success + errors, results)
    if tested['total'] and tested['passed'] == 0:
        implemented = 'not verified by this run'
    elif op['limitation']:
        implemented = f"partial ({op['limitation']})"
    else:
        implemented = 'yes'
    return [f"[{op['method']} {op['path']}] | Requirement(s): {reqs} | Implemented: {implemented}",
            f'Success responses conform: {conformance(success, results)} | Error responses conform: {conformance(errors, results)}']


def render(report, data, contract, checks, label):
    results = {row['name']: row['status'] for row in report['checks']}
    lines = [f"Evaluator run {report.get('runId', 'unknown')} started {report.get('startedAt', 'unknown')}"
             + (f' against {label}' if label else ''),
             f"Result: {report.get('status', 'unknown')} ({report.get('passed', 0)} passed, {report.get('failed', 0)} failed, "
             f"{report.get('unrun', 0)} unrun of {report.get('total', 0)} checks)", '',
             '=== Q1.1 Increment description ===',
             f"Delivered capability: {data['increment']['capability']}",
             f"Users/stakeholders: {data['increment']['users']}    Regulatory provision(s): {data['increment']['provisions']}", '']
    for req in data['requirements']:
        if req['workedOn']:
            lines += requirement_entry(req, data, checks, results)
    lines += ['', '=== Q3.1 Operation status ===']
    for op in data['operations']:
        lines += operation_entry(op, contract['paths'], checks, results) + ['']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('report', type=Path, help='JSON report written by run_phase3_api_tests.py --report')
    parser.add_argument('--requirements', type=Path, default=ROOT / 'docs/requirements.json')
    parser.add_argument('--label', help='Which service was tested, e.g. "Team 106 on Render"')
    parser.add_argument('--output', type=Path, help='Also write the text to this UTF-8 file')
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding='utf-8'))
        data = json.loads(args.requirements.read_text(encoding='utf-8'))
        contract = json.loads((ROOT / 'contracts/openapi.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'Could not read input: {type(exc).__name__}', file=sys.stderr)
        return 2
    checks = evaluator_checks(include_timeline=any(row.get('name', '').startswith('phase4-timeline-') for row in report.get('checks', [])), include_records=any(row.get('name', '').startswith('phase4-records-') for row in report.get('checks', [])))
    found = problems(data, checks)
    if found:
        print('docs/requirements.json is out of date:\n  ' + '\n  '.join(found), file=sys.stderr)
        return 2
    text = render(report, data, contract, checks, args.label)
    print(text)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
