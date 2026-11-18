"""Validate proposed contract artifacts; this is not an HTTP acceptance runner."""
import json
import yaml
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def validate_phase5_plan(contract):
    """Check the declared plan, never score capacity/performance as executed."""
    profile = load('contracts/phase-5-capacity-profile.json')
    targets = profile['required_targets']
    assert profile['status'] == 'capacity_and_performance_tooling_implemented'
    assert profile['source']['project_contract_version'] == contract['info']['version']
    assert targets == {
        'minimum_stored_events': 10000, 'minimum_events_in_one_interaction': 100,
        'measured_requests': 1000, 'maximum_concurrent_clients': 10,
        'maximum_processing_seconds': 1.0, 'minimum_fast_success_fraction': 0.95,
        'minimum_fast_success_count': 950, 'maximum_slow_request_count': 50,
        'network_delay_excluded': True, 'record_loss_allowed': False,
    }, 'Phase 5 targets differ from the Phase 2 REQ-13 / AC-10 plan'
    dataset, workload = profile['dataset'], profile['workload']
    assert dataset['total_events'] == dataset['interactions'] * dataset['events_per_interaction'] == 10000
    assert sum(dataset['event_types_per_interaction'].values()) == dataset['events_per_interaction'] == 100
    assert set(dataset['event_types_per_interaction']) <= set(contract['components']['schemas']['EventInput']['properties']['eventType']['enum'])
    assert sum(item['count'] for item in workload['request_mix']) == workload['total_requests'] == 1000
    assert workload['clients'] == 10 and workload['timed_request_retries'] is False
    assert dataset['interactions'] * workload['rounds_per_operation_per_interaction'] == 500
    for item in workload['request_mix']:
        assert item['method'] == 'GET' and item['count'] == 500
        assert str(item['expected_status']) in contract['paths'][item['path']]['get']['responses']
    assert profile['isolation']['independent_database_required'] is True
    assert profile['isolation']['id_prefix_is_sufficient_isolation'] is False
    assert profile['isolation']['public_shared_reset_or_load_in_chunk1'] is False
    assert profile['measurement']['current_baseline_has_server_metric'] is False  # Historical chunk 1 baseline
    assert profile['measurement']['runtime_has_server_metric'] is True
    assert profile['measurement']['metric'] == 'Server-Timing: traceai_app;dur=<milliseconds>'


def main():
    contract = load('contracts/openapi.json')
    validate_spec(contract)
    validate_phase5_plan(contract)
    validate_spec(yaml.safe_load((ROOT / 'docs/testing-interface.openapi.yaml').read_text()))
    assert contract == load('src/traceai/openapi.json'), 'Bundled API contract differs from authored contract'
    schema = load('contracts/event.schema.json')
    Draft202012Validator.check_schema(schema)
    assert {k: v for k, v in schema.items() if k != '$schema'} == contract['components']['schemas']['EventInput']
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = load('tests/fixtures/valid-events.json')
    for event in valid:
        validator.validate(event)
    invalid = load('tests/fixtures/invalid-events.json')
    for case in invalid:
        assert list(validator.iter_errors(case['event'])), case['name']
    for size in (65536, 65537):
        path = ROOT / f'tests/fixtures/event-{size}-bytes.json'
        assert len(path.read_bytes()) == size
        validator.validate(json.loads(path.read_bytes()))
    try:
        load('tests/fixtures/malformed.json.txt')
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError('Malformed fixture unexpectedly parsed')
    scenario = load('tests/fixtures/phase-3-scenario.json')['steps'] + load('tests/fixtures/phase-4-timeline-scenario.json')['steps'] + load('tests/fixtures/phase-4-records-scenario.json')['steps'] + load('tests/fixtures/phase-4-reports-scenario.json')['steps']
    for step in scenario:
        path = step['path']
        if path.startswith('/api/v1/interactions/'):
            path = '/api/v1/interactions/{interactionId}' + ('/report' if path.endswith('/report') else '')
        operation = contract['paths'][path][step['method'].lower()]
        response = operation['responses'][str(step['expectedStatus'])]
        if 'expectedBody' in step:
            response_schema = response['content']['application/json']['schema']
            # Root the reference in a local document, without network resolution.
            document = {'$ref': response_schema['$ref'], 'components': contract['components']}
            Draft202012Validator(document, format_checker=FormatChecker()).validate(step['expectedBody'])
    print(f'PASS: OpenAPI, schema parity, {len(valid)} valid events, '
          f'{len(invalid)} invalid events, malformed JSON, 2 byte boundaries, '
          f'{len(scenario)} scenario steps and expected response schemas.')
    print('PASS: Phase 5 plan invariants only; no capacity/performance benchmark executed.')


if __name__ == '__main__':
    main()
