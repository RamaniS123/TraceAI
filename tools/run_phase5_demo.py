#!/usr/bin/env python3
"""Append unique synthetic demo records to an explicitly authorized loopback app.

Uses the normal API; no reset or delete operation. Keep benchmark data separate.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capacity_helpers', ROOT/'tools/phase5_capacity.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def require(condition, message):
    if not condition:
        raise helpers.CapacityError(message)


def check_snapshot(http, events, codes, contract):
    identifier = events[0]['interactionId']
    history = helpers.checked_body(http.get('/api/v1/interactions/'+identifier), 200,
        helpers.validator(contract, '/api/v1/interactions/{interactionId}', 'get', 200))
    response = http.get('/api/v1/interactions/'+identifier+'/report')
    report = helpers.checked_body(response, 200,
        helpers.validator(contract, '/api/v1/interactions/{interactionId}/report', 'get', 200))
    ordered = sorted(events, key=lambda event: (event['occurredAt'], event['eventId']))
    for view in (history, report):
        require(view['status'] == 'completed', 'Demo status differs from the expected completed record.')
        require(helpers.canonical(view['events']) == helpers.canonical(ordered), 'Demo records changed or were reordered incorrectly.')
        require([w['code'] for w in view['warnings']] == codes, 'Demo warnings differ from the expected profile.')
    require(report['metadata']['eventCount'] == len(events), 'Demo report count differs.')
    require(report['metadata']['firstOccurredAt'] == ordered[0]['occurredAt'] and
            report['metadata']['lastOccurredAt'] == ordered[-1]['occurredAt'], 'Demo report timestamps differ.')
    reviews = [e for e in events if e['eventType'] == 'review.completed']
    corrections = [e for e in events if e['eventType'] == 'record.corrected']
    require(len(report['reviewActions']) == len(reviews) and len(report['corrections']) == len(corrections),
            'Demo review/correction count differs.')
    for review, projected in zip(reviews, report['reviewActions']):
        require(projected['eventId'] == review['eventId'] and all(projected[key] == review['data'][key]
                for key in ('reviewerId', 'action', 'reason')), 'Original review was not preserved.')
    for correction, projected in zip(corrections, report['corrections']):
        require(projected['linkValid'] is True and projected['correctsEventId'] == correction['data']['correctsEventId'],
                'Demo correction link differs.')
    return {'history_sha256': helpers.digest(history), 'report_sha256': helpers.digest(report),
            'event_count': len(events), 'warnings': codes}, response.content


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--env-file', type=Path, required=True, help='Private local API credential file')
    parser.add_argument('--allow-synthetic-writes', action='store_true')
    parser.add_argument('--include-late-event', action='store_true', help='Also verify that late output removes the missing warning')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/phase5-demo.json')
    args = parser.parse_args(argv)
    outputs = [args.report, args.report.with_name(args.report.name+'.tmp')] + [
        args.report.with_name(args.report.stem+'-'+name+'-report.json') for name in ('main', 'late', 'order', 'after-late')]
    if args.env_file.resolve() in {path.resolve() for path in outputs}:
        parser.error('Evidence paths must not overwrite the private credential file.')
    result = {'status': 'blocked', 'reset_performed': False, 'problems': [], 'started_at': helpers.now()}
    try:
        require(args.allow_synthetic_writes, 'Confirm the isolated demo dataset with --allow-synthetic-writes.')
        base = helpers.local_base_url(args.base_url)
        values = dotenv_values(args.env_file)
        token = os.getenv('TRACEAI_API_TOKEN') or values.get('TRACEAI_API_TOKEN')
        require(isinstance(token, str) and bool(token) and token.isascii() and not any(c.isspace() for c in token),
                'A valid local API token is required.')
        source = json.loads((ROOT/'demo/phase5-demo.json').read_text())
        prefix = 'demo-' + uuid4().hex[:12]
        def remap(event):
            event = json.loads(json.dumps(event))
            for key in ('eventId', 'interactionId'):
                event[key] = event[key].replace('demo-', prefix+'-', 1)
            if 'correctsEventId' in event['data']:
                event['data']['correctsEventId'] = event['data']['correctsEventId'].replace('demo-', prefix+'-', 1)
            return event
        cases = [{**case, 'events': [remap(event) for event in case['events']]} for case in source['cases']]
        late = remap(source['late_event'])
        result.update(status='running', run_prefix=prefix, cases={}, late_event=late, posted_events=0)
        contract = json.loads(helpers.CONTRACT.read_text())
        receipts = helpers.validator(contract, '/api/v1/events', 'post', 201)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(base_url=base, headers={'Authorization':'Bearer '+token}, timeout=15,
                          follow_redirects=False, transport=httpx.HTTPTransport(retries=0)) as http:
            for case in cases:
                for event in case['events']:
                    body = helpers.checked_body(http.post('/api/v1/events', json=event), 201, receipts)
                    require(body['stored'] is True and body['duplicate'] is False and body['eventId'] == event['eventId'] and
                            body['interactionId'] == event['interactionId'], 'Demo receipt was not the expected new stored record.')
                    result['posted_events'] += 1
                checked, raw = check_snapshot(http, case['events'], case['warnings'], contract)
                path = args.report.with_name(args.report.stem+'-'+case['name']+'-report.json')
                path.write_bytes(raw)
                result['cases'][case['name']] = {'interaction_id':case['events'][0]['interactionId'], **checked,
                                                'downloadable_report':str(path)}
            original = cases[0]['events'][0]
            duplicate = http.post('/api/v1/events', json=original)
            require(duplicate.status_code == 200 and duplicate.json().get('duplicate') is True, 'Exact-repeat demo did not return duplicate.')
            conflict = http.post('/api/v1/events', json={**original, 'data':{'changed':'synthetic conflict'}})
            require(conflict.status_code == 409, 'Changed-content demo did not return conflict.')
            # Verify that duplicate/conflict attempts changed no main records.
            check_snapshot(http, cases[0]['events'], cases[0]['warnings'], contract)
            result.update(duplicate_status=200, conflict_status=409)
            if args.include_late_event:
                helpers.checked_body(http.post('/api/v1/events', json=late), 201, receipts)
                checked, raw = check_snapshot(http, cases[1]['events']+[late], [], contract)
                path = args.report.with_name(args.report.stem+'-after-late-report.json');path.write_bytes(raw)
                result['late_arrival'] = {**checked, 'downloadable_report':str(path)}
                result['posted_events'] += 1
            result['status'] = 'passed'
    except (helpers.CapacityError, httpx.HTTPError, OSError, ValueError) as exc:
        result['status'] = 'failed' if result['status'] == 'running' else 'blocked'
        result['problems'].append(str(exc) if isinstance(exc, helpers.CapacityError) else 'Local demo request or evidence operation failed.')
    result['finished_at'] = helpers.now()
    helpers.write_json(args.report, result)
    print('Demo: '+result['status']+'. Evidence: '+str(args.report))
    if result['status'] == 'passed':
        for name, case in result['cases'].items():print(name+': '+case['interaction_id'])
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
