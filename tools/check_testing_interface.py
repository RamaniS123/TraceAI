#!/usr/bin/env python3
"""Check course tester/system endpoints and save evidence, including blocked runs.

Use --preflight for read-only readiness, or --allow-test-reset to run a suite.
No credentials are sent by this tool: the hosted tester must hold target access.
Exit 0 means a complete well-formed exchange; --require-pass also requires all pass.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

OUTCOMES = {'pass', 'fail', 'error', 'skip'}
SOURCES = {'tester', 'system', 'communication', 'unknown'}


def measure_problems(name, measure):
    if not isinstance(measure, dict) or not isinstance(measure.get('basis'), str) or not measure['basis'].strip():
        return [f'coverage.{name} needs a nonempty basis']
    covered, total = measure.get('covered'), measure.get('total')
    if covered is None and total is None:
        return []
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (covered, total)) or covered > total:
        return [f'coverage.{name} counts must be nonnegative integers with covered <= total, or both null']
    return []


def report_problems(report, session_id, target):
    if not isinstance(report, dict):
        return ['report must be a JSON object']
    found = []
    if report.get('session_id') != session_id:
        found.append('report session_id does not match')
    if report.get('target_url') not in (target, target.rstrip('/')):
        found.append('report target_url does not match')
    results = report.get('results')
    if not isinstance(results, list) or not results:
        return found + ['report has no results']
    if not all(isinstance(row, dict) for row in results):
        return found + ['results must contain JSON objects']
    ids = [row.get('test_id') for row in results]
    if not all(isinstance(i, str) and i for i in ids) or len(ids) != len(set(i for i in ids if isinstance(i, str))):
        found.append('test_id values must be unique and nonempty strings')
    for row in results:
        if not isinstance(row.get('outcome'),str) or row['outcome'] not in OUTCOMES:
            found.append('a result has an invalid outcome')
        if not isinstance(row.get('message'), str) or not row['message'].strip():
            found.append('a result needs a nonempty message')
        if row.get('outcome') == 'error' and (not isinstance(row.get('source'), str) or row['source'] not in SOURCES):
            found.append('error results need a valid source')
    coverage = report.get('coverage')
    if not isinstance(coverage, dict):
        return found + ['report coverage must be an object']
    for name in ('code', 'component', 'system'):
        found += measure_problems(name, coverage.get(name))
    return found


def base_url(value):
    if any(character.isspace() for character in value):
        raise ValueError('Invalid base URL')
    parts = urlsplit(value)
    if (parts.scheme not in ('https', 'http') or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or (parts.port is not None and parts.port == 0)):
        raise ValueError('Invalid base URL')
    return value.rstrip('/')


def object_body(response):
    if response.headers.get('content-type','').split(';',1)[0].strip().lower() != 'application/json':
        return None
    try:
        def reject_constant(value):
            raise ValueError('Non-finite number')
        value = json.loads(response.content.decode('utf-8'),parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def request(http, evidence, stage, method, url, **kwargs):
    try:
        response = http.request(method, url, **kwargs)
    except httpx.HTTPError:
        evidence['stages'].append({'name':stage, 'source':'communication', 'problem':'No HTTP response received.'})
        return None
    evidence['stages'].append({'name':stage, 'http_status':response.status_code})
    return response


def preflight(http, tester, target, evidence):
    for name, url, kind in [
        ('system_health',target+'/health','health'),
        ('system_contract',target+'/openapi.json','contract'),
        ('system_report_route',target+'/test/report','report'),
        ('tester_report_route',tester+'/test/report','report'),
    ]:
        response = request(http,evidence,name,'GET',url,
                           **({'params':{'session_id':'preflight-'+str(uuid4())}} if kind=='report' else {}))
        body = object_body(response) if response is not None else None
        ready = response is not None and body is not None
        if kind == 'report':
            ready = ready and response.status_code == 404 and isinstance(body.get('message'), str) and body.get('source') in ('system','tester')
        elif kind == 'contract':
            ready = ready and response.status_code == 200 and isinstance(body.get('paths'),dict) and isinstance(body.get('openapi'),str)
        else:
            # This checks reachability, not a particular team's health-body schema.
            ready = ready and response.status_code == 200
        if not ready:
            evidence['problems'].append(name+' did not satisfy the readiness check.')
    evidence['status'] = 'ready' if not evidence['problems'] else 'not_ready'
    return 0 if evidence['status']=='ready' else 1


def execute(http, tester, target, evidence, require_pass):
    setup = request(http,evidence,'tester_setup','POST',tester+'/test/setup',json={'target_url':target})
    body = object_body(setup) if setup is not None else None
    sid = body.get('session_id') if body else None
    if setup is None or setup.status_code != 201 or not isinstance(sid,str) or not sid:
        evidence['problems'].append('Tester setup did not establish a session; no test run was requested.')
        return 1
    evidence['session_id'] = sid
    run = request(http,evidence,'tester_run','POST',tester+'/test/run',json={'session_id':sid})
    stored = request(http,evidence,'tester_report','GET',tester+'/test/report',params={'session_id':sid})
    system = request(http,evidence,'system_report','GET',target+'/test/report',params={'session_id':sid})
    report = object_body(stored) if stored is not None and stored.status_code == 200 else None
    found = report_problems(report,sid,target)
    if not found:
        # Keep the actual validated report in a private, ignored artifact; never print its text.
        evidence['suite_report'] = report
        evidence['counts'] = {name:sum(row['outcome']==name for row in report['results']) for name in sorted(OUTCOMES)}
    evidence['problems'] += found
    system_body = object_body(system) if system is not None and system.status_code == 200 else None
    code = system_body.get('coverage',{}).get('code') if isinstance(system_body,dict) and isinstance(system_body.get('coverage'),dict) else None
    if system_body is None or system_body.get('session_id') != sid or measure_problems('code',code):
        evidence['problems'].append('System report did not return matching session and valid code coverage.')
    else:
        evidence['system_report'] = system_body
    if run is None or run.status_code != 200:
        evidence['problems'].append('Tester run did not return HTTP 200; any stored results are partial evidence.')
    elif report is not None and object_body(run) != report:
        evidence['problems'].append('Stored report differs from the run response.')
    if evidence['problems']:
        evidence['status'] = 'invalid' if evidence.get('suite_report') is None else 'incomplete'
        return 1
    counts = evidence['counts']
    if counts['skip']:
        evidence['status'] = 'incomplete'
        evidence['problems'].append('Some tests were not executed.')
        return 1
    evidence['completed'] = True
    evidence['status'] = 'passed' if counts['pass']==len(report['results']) else 'completed_with_failures'
    return 1 if require_pass and evidence['status']!='passed' else 0


def save(path, evidence):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.testing-report-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(evidence,output,indent=2,allow_nan=False)
            output.write('\n')
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None, *, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tester', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--preflight', action='store_true',help='Read-only route/readiness probes; no setup or run')
    parser.add_argument('--allow-test-reset', action='store_true',help='Authorize setup/run resetting the target test data')
    parser.add_argument('--timeout', type=float,default=600)
    parser.add_argument('--require-pass', action='store_true')
    parser.add_argument('--report',type=Path,default=Path('reports/testing-interface.json'))
    args = parser.parse_args(argv)
    evidence = {'schema_version':1,'run_id':str(uuid4()),'started_at':datetime.now(timezone.utc).isoformat(),
                'mode':'preflight' if args.preflight else 'suite','status':'blocked','completed':False,
                'counts':None,'stages':[],'problems':[]}
    try:
        tester,target = base_url(args.tester),base_url(args.target)
        if tester==target or not math.isfinite(args.timeout) or args.timeout<=0:
            raise ValueError('Invalid configuration')
        if not args.preflight and not args.allow_test_reset:
            raise ValueError('Reset authorization is required')
        evidence.update(tester_url=tester,target_url=target)
    except ValueError:
        evidence['problems'].append('Use distinct valid base URLs, a finite positive timeout, and --preflight or --allow-test-reset.')
        code = 2
    else:
        with httpx.Client(timeout=args.timeout,transport=transport,follow_redirects=False) as http:
            code = preflight(http,tester,target,evidence) if args.preflight else execute(http,tester,target,evidence,args.require_pass)
    evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
    try:
        for key in ('suite_report','system_report'):
            if key in evidence:
                destination=args.report.with_name(args.report.stem+'-'+evidence['run_id']+'.'+key+'.json')
                save(destination,evidence[key])
                evidence[key+'_file']=destination.name
        save(args.report,evidence)
    except (OSError,ValueError):
        print('Could not save the testing evidence.',file=sys.stderr)
        return 2
    print('Testing interface: '+evidence['status']+'; '+('no suite results' if evidence['counts'] is None else ', '.join(f'{k}={v}' for k,v in evidence['counts'].items())))
    for problem in evidence['problems']:
        print('CHECK: '+problem)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
