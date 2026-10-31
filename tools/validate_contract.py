"""Validate proposed contract artifacts; this is not an HTTP acceptance runner."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def main():
    contract = load('contracts/openapi.json')
    validate_spec(contract)
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


if __name__ == '__main__':
    main()
