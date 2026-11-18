#!/usr/bin/env python3
"""Local-only Phase 5 HTTP capacity seed and independent retrieval oracle.

No application/storage imports, reset endpoint, hidden retries or latency verdicts.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker
import simplejson

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'contracts/phase-5-capacity-profile.json'
CONTRACT = ROOT / 'contracts/openapi.json'
GENERATOR_VERSION = 1
INTERACTIONS = 100
EVENTS_PER_INTERACTION = 100
DISCLAIMER = ('This report supports review of submitted event records. '
              'It does not certify legal compliance or evaluate AI outputs or human decisions.')


class CapacityError(Exception):
    """Only fixed, non-sensitive diagnostics may cross this boundary."""


def canonical(value):
    return simplejson.dumps(value, use_decimal=True, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_run_id(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z0-9]{8,24}', value) is not None


def interaction_events(run_id, index):
    """One complete synthetic history: 1 start, 96 outputs, review, correction, end."""
    if not valid_run_id(run_id) or not 0 <= index < INTERACTIONS:
        raise CapacityError('Invalid dataset identifier or interaction index.')
    interaction = f'p5-{run_id}-i{index:03d}'
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index * 2)
    events = []
    for number in range(EVENTS_PER_INTERACTION):
        kind = ('interaction.started' if number == 0 else
                'model.output_generated' if number <= 96 else
                'review.completed' if number == 97 else
                'record.corrected' if number == 98 else 'interaction.completed')
        data = {'synthetic': True, 'reference': f'p5-reference-{index:03d}-{number:03d}'}
        if number == 97:
            data.update(reviewerId='synthetic-reviewer', action='accept', reason='Synthetic capacity review.')
        elif number == 98:
            data.update(correctsEventId=f'{interaction}-e097', reason='Synthetic linked correction; original retained.')
        events.append({'eventId': f'{interaction}-e{number:03d}', 'interactionId': interaction,
                       'eventType': kind, 'occurredAt': (start + timedelta(seconds=number)).isoformat().replace('+00:00', 'Z'),
                       'modelVersion': 'synthetic-model-v1', 'applicationVersion': 'synthetic-app-v1', 'data': data})
    return events


def expected_views(events):
    """Fixed-profile oracle; deliberately does not call production timeline/report code."""
    review, correction = events[97], events[98]
    history = {'interactionId': events[0]['interactionId'], 'status': 'completed', 'events': events,
               'warnings': [{'code': 'CORRECTED_EVENT',
                             'message': 'A linked correction is recorded; the original event is retained.',
                             'eventId': correction['eventId'], 'eventType': 'record.corrected',
                             'correctsEventId': review['eventId']}]}
    report = {**history,
              'metadata': {'eventCount': len(events), 'firstOccurredAt': events[0]['occurredAt'],
                           'lastOccurredAt': events[-1]['occurredAt']},
              'modelVersions': ['synthetic-model-v1'], 'applicationVersions': ['synthetic-app-v1'],
              'reviewActions': [{key: review[key] for key in ('eventId', 'occurredAt')} |
                                {key: review['data'][key] for key in ('reviewerId', 'action', 'reason')}],
              'corrections': [{key: correction[key] for key in ('eventId', 'occurredAt')} |
                              {key: correction['data'][key] for key in ('correctsEventId', 'reason')} |
                              {'linkValid': True}], 'disclaimer': DISCLAIMER}
    return history, report


def manifest(run_id):
    entries = []
    seed_hash = hashlib.sha256()
    counts = Counter()
    for index in range(INTERACTIONS):
        events = interaction_events(run_id, index)
        history, report = expected_views(events)
        entries.append({'interaction_id': events[0]['interactionId'], 'event_count': len(events),
                        'history_sha256': digest(history), 'report_sha256': digest(report)})
        for event in events:
            seed_hash.update(canonical(event) + b'\n')
            counts[event['eventType']] += 1
    return {'schema_version': 1, 'generator_version': GENERATOR_VERSION, 'run_id': run_id,
            'generator_sha256': file_digest(__file__), 'profile_sha256': file_digest(PROFILE),
            'dataset_profile_sha256': digest(json.loads(PROFILE.read_text())['dataset']), 'contract_sha256': file_digest(CONTRACT),
            'event_count': INTERACTIONS * EVENTS_PER_INTERACTION, 'interaction_count': INTERACTIONS,
            'events_per_interaction': EVENTS_PER_INTERACTION, 'event_type_counts': dict(counts),
            'seed_jsonl_sha256': seed_hash.hexdigest(), 'interactions': entries}


def load_manifest(path):
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or not valid_run_id(data.get('run_id')):
            raise ValueError
        expected = manifest(data['run_id'])
        # Timing-only profile revisions must not invalidate unchanged retained seed data.
        original_profile = data.get('profile_sha256')
        if not isinstance(original_profile, str) or not re.fullmatch(r'[0-9a-f]{64}', original_profile):
            raise ValueError
        expected['profile_sha256'] = original_profile
        if data != expected:
            raise ValueError
        return data
    except (OSError, ValueError, TypeError):
        raise CapacityError('Manifest is invalid or differs from the current generator/profile/contract.') from None


def local_base_url(value):
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', '::1', 'localhost')
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ('', '/') or not parts.port):
            raise ValueError
        return value.rstrip('/')
    except ValueError:
        raise CapacityError('Capacity tool requires an explicit loopback HTTP URL and port.') from None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def response_body(response):
    try:
        return simplejson.loads(response.content, use_decimal=True, allow_nan=False, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise CapacityError('Response is not valid unambiguous JSON.') from None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def validator(contract, path, method, status):
    schema = contract['paths'][path][method]['responses'][str(status)]['content']['application/json']['schema']
    return Draft202012Validator({**schema, 'components': contract['components']}, format_checker=FormatChecker())


def checked_body(response, expected_status, schema):
    if response.status_code != expected_status:
        raise CapacityError(f'Unexpected HTTP status {response.status_code}; expected {expected_status}.')
    body = response_body(response)
    if not schema.is_valid(body):
        raise CapacityError('Response does not match the common OpenAPI schema.')
    return body


def verify(http, data, contract):
    results = []
    total_verified = 0
    for index, entry in enumerate(data['interactions']):
        events = interaction_events(data['run_id'], index)
        expectations = expected_views(events)
        outcome = {'interaction_id': entry['interaction_id'], 'event_count': len(events)}
        for name, suffix, path, expected in zip(
                ('history', 'report'), ('', '/report'),
                ('/api/v1/interactions/{interactionId}', '/api/v1/interactions/{interactionId}/report'), expectations):
            try:
                response = http.get('/api/v1/interactions/' + entry['interaction_id'] + suffix)
                body = checked_body(response, 200, validator(contract, path, 'get', 200))
                # Compare every field, original record, order, annotation and report section.
                if canonical(body) != canonical(expected):
                    raise CapacityError('Retrieved content differs from the complete expected snapshot.')
                outcome[name] = {'status': 'passed', 'sha256': digest(body)}
            except (CapacityError, httpx.HTTPError) as exc:
                outcome[name] = {'status': 'failed', 'problem': str(exc) if isinstance(exc, CapacityError) else 'HTTP communication failure.'}
        if all(outcome[name]['status'] == 'passed' for name in ('history', 'report')):
            total_verified += len(events)
        results.append(outcome)
    return {'status': 'passed' if total_verified == data['event_count'] else 'failed',
            'verified_events_in_both_views': total_verified, 'verified_interactions': total_verified // EVENTS_PER_INTERACTION,
            'verification_requests': INTERACTIONS * 2, 'interactions': results}


def seed(http, data, contract, receipt_path, evidence):
    schema = validator(contract, '/api/v1/events', 'post', 201)
    acknowledged = 0
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open('x') as receipts:
        for index in range(INTERACTIONS):
            for event in interaction_events(data['run_id'], index):
                body = checked_body(http.post('/api/v1/events', content=canonical(event),
                                             headers={'Content-Type': 'application/json'}), 201, schema)
                expected = {'eventId': event['eventId'], 'interactionId': event['interactionId'], 'stored': True, 'duplicate': False}
                if canonical(body) != canonical(expected):
                    raise CapacityError('Seed receipt differs from the expected new-record acknowledgement.')
                receipts.write(canonical({'status': 201, **body}).decode() + '\n')
                acknowledged += 1
                evidence['acknowledged_new_events'] = acknowledged
            if (index + 1) % 10 == 0:
                receipts.flush()
                print(f'Loaded {acknowledged}/{data["event_count"]} events.', flush=True)
    return acknowledged


def main(argv=None, *, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('seed', 'verify'))
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--run-id', help='Optional new dataset ID, 8–24 lowercase letters/digits')
    parser.add_argument('--allow-isolated-load', action='store_true', help='Confirm this loopback app uses a dedicated Phase 5 database')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args(argv)
    receipts = args.manifest.with_suffix('.receipts.jsonl')
    paths = (args.manifest, args.report, receipts,
             args.report.with_name(args.report.name + '.tmp'),
             args.manifest.with_name(args.manifest.name + '.tmp'))
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error('Manifest, receipts, report and temporary files must have distinct paths.')
    evidence = {'schema_version': 1, 'started_at': now(), 'mode': args.mode, 'status': 'blocked',
                'capacity_verdict': 'not_verified', 'performance_verdict': 'not_measured',
                'reset_performed': False, 'problems': []}
    code = 1
    try:
        base = local_base_url(args.base_url)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise CapacityError('Timeout must be a positive finite number.')
        token = os.environ.get('TRACEAI_API_TOKEN', '')
        if not token or not token.isascii() or any(char.isspace() for char in token):
            raise CapacityError('Set a nonempty ASCII TRACEAI_API_TOKEN without whitespace.')
        if args.mode == 'seed':
            if not args.allow_isolated_load:
                raise CapacityError('Seed requires --allow-isolated-load for a dedicated benchmark database.')
            if args.manifest.exists():
                raise CapacityError('Seed manifest already exists; use verify or a new manifest for a new run.')
            data = manifest(args.run_id or uuid4().hex[:12])
            write_json(args.manifest, data)
        else:
            if args.run_id or args.allow_isolated_load:
                raise CapacityError('Verify accepts the saved manifest and performs no writes.')
            data = load_manifest(args.manifest)
        evidence.update(run_id=data['run_id'], base_url=base, manifest_sha256=file_digest(args.manifest),
                        expected_events=data['event_count'], expected_interactions=data['interaction_count'],
                        events_per_interaction=data['events_per_interaction'], current_profile_sha256=file_digest(PROFILE))
        contract = json.loads(CONTRACT.read_text())
        with httpx.Client(base_url=base, headers={'Authorization': 'Bearer ' + token},
                          timeout=args.timeout, follow_redirects=False, transport=transport) as http:
            health = http.get('/health')
            if health.status_code != 200 or health.headers.get('X-TraceAI-Contract') != contract['info']['version']:
                raise CapacityError('Target is unhealthy or does not identify the expected project contract.')
            evidence['deployed_revision'] = health.headers.get('X-TraceAI-Revision')
            evidence['status'] = 'running'
            if args.mode == 'seed':
                evidence['acknowledged_new_events'] = 0
                evidence['acknowledged_new_events'] = seed(http, data, contract, receipts, evidence)
                evidence['receipts_sha256'] = file_digest(receipts)
            evidence['verification'] = verify(http, data, contract)
            evidence['status'] = evidence['verification']['status']
            if evidence['status'] == 'passed':
                evidence['capacity_verdict'] = 'passed_for_this_isolated_dataset'
                code = 0
    except (CapacityError, httpx.HTTPError, OSError) as exc:
        evidence['problems'].append(str(exc) if isinstance(exc, CapacityError) else
                                    'HTTP communication failure.' if isinstance(exc, httpx.HTTPError) else 'Local evidence file operation failed.')
        evidence['status'] = 'failed' if evidence['status'] == 'running' else 'blocked'
    evidence['finished_at'] = now()
    write_json(args.report, evidence)
    print(f'Capacity {args.mode}: {evidence["status"]}; performance not measured. Evidence: {args.report}')
    return code


if __name__ == '__main__':
    sys.exit(main())
