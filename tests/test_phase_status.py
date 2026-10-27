"""Status tables printed from evaluator reports stay accurate and in sync with the evaluator."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('phase_status', ROOT / 'tools/phase_status.py')
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

CHECKS = status.evaluator_checks()
DATA = json.loads((ROOT / 'docs/requirements.json').read_text(encoding='utf-8'))


def report(tmp_path, **overrides):
    rows = [{'name': check['name'], 'status': overrides.get(check['name'], 'passed')} for check in CHECKS]
    counts = {s: sum(row['status'] == s for row in rows) for s in ('passed', 'failed', 'unrun')}
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'runId': 'synthetic-run', 'startedAt': '2026-10-17T00:00:00+00:00',
                                'status': 'failed' if counts['failed'] or counts['unrun'] else 'passed',
                                'total': len(rows), **counts, 'checks': rows}))
    return path


def run(tmp_path, capsys, **overrides):
    assert status.main([str(report(tmp_path, **overrides))]) == 0
    return capsys.readouterr().out


def line(text, prefix):
    return next(row for row in text.splitlines() if row.startswith(prefix))


def test_requirement_data_matches_evaluator_checks():
    assert status.problems(DATA, CHECKS) == []


def test_unknown_check_name_is_reported():
    broken = json.loads(json.dumps(DATA))
    broken['acceptanceCriteria']['AC-02']['checks'].append('scenario-99')
    assert status.problems(broken, CHECKS) == ['AC-02 refers to unknown check scenario-99']


def test_passing_run_marks_planned_requirements_complete(tmp_path, capsys):
    out = run(tmp_path, capsys)
    assert 'REQ-01 - Validate, store and confirm events | Status: complete' in out
    assert 'AC-01 (20/20 checks passed)' in out
    assert 'Status: partial' in line(out, 'REQ-03')  # Warnings are documented as Phase 4.
    assert not any(row.startswith('REQ-06') for row in out.splitlines())  # Not worked on this phase.
    assert 'Implemented: no (planned for Phase 4)' in line(out, '[GET /api/v1/interactions/{interactionId}/report]')
    assert 'Implemented: partial' in line(out, '[GET /api/v1/interactions/{interactionId}]')


def test_operation_counts_split_success_and_error_checks(tmp_path, capsys):
    out = run(tmp_path, capsys)
    lines = out.splitlines()
    events = lines[lines.index(line(out, '[POST /api/v1/events]')) + 1]
    assert events == 'Success responses conform: yes (6/6 checks) | Error responses conform: yes (16/16 checks)'


def test_failed_check_makes_requirement_partial_and_operation_nonconforming(tmp_path, capsys):
    out = run(tmp_path, capsys, **{'scenario-10': 'failed'})
    assert 'failing checks: scenario-10' in out
    assert 'REQ-04 - Store duplicates once, reject conflicting event IDs | Status: partial' in out
    assert 'Error responses conform: no (1 of 16 checks failed: scenario-10)' in out


def test_unrun_checks_are_never_counted_as_conforming(tmp_path, capsys):
    out = run(tmp_path, capsys, **{name: 'unrun' for name in ('scenario-30', 'scenario-31', 'final-cleanup')})
    assert 'Status: partial' in line(out, 'REQ-10')
    lines = out.splitlines()
    reset = lines[lines.index(line(out, '[POST /api/v1/test/reset]')) + 1]
    assert reset.startswith('Success responses conform: not verified')


def test_unreadable_report_exits_with_configuration_error(tmp_path, capsys):
    assert status.main([str(tmp_path / 'missing.json')]) == 2
    assert 'Could not read input' in capsys.readouterr().err
