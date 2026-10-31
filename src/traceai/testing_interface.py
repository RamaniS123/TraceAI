"""Course cross-team testing interface: system /test endpoints and the deployed tester.

The tester wraps tools/run_phase3_api_tests.py, so the CLI, CI and this service run the
same checks. Tester and system test endpoints use {"message", "source"} error bodies, as
the course testing-interface specification requires.
"""
import importlib.util
from importlib.resources import files
import json
import os
from pathlib import Path
from secrets import compare_digest
import threading
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from traceai.events import reset_events
from traceai.requests import MAX_BODY_BYTES, unique_object

SOURCES = ('tester', 'system', 'communication', 'unknown')
CODE_BASIS = 'Source lines; coverage instrumentation is not enabled in the deployed service'
SETUP_TIMEOUT = 90  # Covers a free-tier cold start of the target system.
RUN_TIMEOUT = 240  # Check budget; final coverage lookup adds at most CHECK_TIMEOUT.
CHECK_TIMEOUT = 30
CLEANUP = {'name': 'final-cleanup', 'method': 'POST', 'path': '/api/v1/test/reset', 'auth': 'reset',
           'body': {'confirm': True}, 'expectedStatus': 200,
           'expectedBody': {'reset': True, 'remainingEvents': 0, 'remainingInteractions': 0}}

system_router = APIRouter()
tester_router = APIRouter()


def problem(status, message, source):
    return JSONResponse(status_code=status, content={'message': message, 'source': source})


async def json_object(request):
    try:
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BODY_BYTES:
                return None
            raw.extend(chunk)
        def reject_constant(value):
            raise ValueError('Non-finite JSON number')
        body = json.loads(bytes(raw).decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except Exception:  # Malformed JSON, wrong encoding or an empty body.
        return None
    return body if isinstance(body, dict) else None


def init_state(app):
    app.state.system_sessions = {}
    app.state.tester_sessions = {}
    app.state.tester_lock = threading.Lock()
    app.state.tester_transport = None  # Tests inject an httpx.MockTransport here.


# ---------------------------------------------------------------- system

@system_router.post('/test/setup', include_in_schema=False)
async def system_setup(request: Request):
    settings = request.app.state.settings
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    reset = settings.reset_token.get_secret_value() if settings.reset_token else ''
    if not (scheme.lower() == 'bearer' and token and reset and compare_digest(token.encode(), reset.encode())):
        return problem(401, 'System setup requires the reset bearer token.', 'system')
    body = await json_object(request)
    session_id = body.get('session_id') if body else None
    if not isinstance(session_id, str) or not session_id or not isinstance(body.get('setup', {}), dict):
        return problem(400, 'Body must be {"session_id": "<nonempty string>", "setup": {}}.', 'system')
    if not settings.test_reset_enabled:
        return problem(403, 'Test setup is disabled in this environment.', 'system')
    sessions = request.app.state.system_sessions
    if session_id in sessions:
        return problem(409, 'This session ID already exists; use a new ID.', 'system')
    sessions[session_id] = 'preparing'
    try:
        # Each session starts from the empty test dataset defined by the pod's reset operation.
        await run_in_threadpool(reset_events, request.app.state.engine)
    except SQLAlchemyError:
        del sessions[session_id]
        return problem(500, 'Could not reset the test dataset.', 'system')
    except Exception:
        del sessions[session_id]
        raise
    sessions[session_id] = 'ready'
    return JSONResponse(status_code=201, content={'session_id': session_id})


@system_router.get('/test/report', include_in_schema=False)
def system_report(request: Request):
    session_id = request.query_params.get('session_id')
    if not session_id:
        return problem(400, 'The session_id query parameter is required.', 'system')
    state = request.app.state.system_sessions.get(session_id)
    if state is None:
        return problem(404, 'Unknown session.', 'system')
    if state != 'ready':
        return problem(409, 'Session preparation is still in progress.', 'system')
    return {'session_id': session_id, 'coverage': {'code': {'covered': None, 'total': None, 'basis': CODE_BASIS}}}


# ---------------------------------------------------------------- tester

def asset_root():
    return Path(os.environ.get('TRACEAI_ASSET_ROOT') or Path.cwd())


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, asset_root() / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def origin(url):
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}'.lower()


def valid_target(url):
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return False
    return (parts.scheme in ('http', 'https') and bool(parts.hostname) and not parts.username
            and not parts.password and not parts.query and not parts.fragment)


def target_tokens(app, target_url):
    """Credentials are only ever sent to an origin they were configured for."""
    try:
        configured = json.loads(os.environ.get('TRACEAI_TESTER_TARGET_TOKENS') or '{}')
        configured = {origin(key): value for key, value in configured.items() if isinstance(value, dict)}
    except (ValueError, AttributeError):
        configured = {}
    if origin(target_url) in configured:
        return configured[origin(target_url)]
    own = os.environ.get('TRACEAI_PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL')
    settings = app.state.settings
    if own and origin(own) == origin(target_url):
        return {name: secret.get_secret_value() for name, secret in
                (('api', settings.api_token), ('reset', settings.reset_token)) if secret}
    return {}


def client(app, timeout):
    return httpx.Client(timeout=timeout, follow_redirects=False, transport=app.state.tester_transport)


def forwarded_error(response):
    try:
        body = response.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    # Remote error text is untrusted and can contain credentials or tracebacks.
    message = f'Target system setup returned HTTP {response.status_code}.'
    source = body.get('source') if body.get('source') in SOURCES else 'system'
    return problem(response.status_code, message, source)


def prepare_target(app, target_url):
    session_id = str(uuid4())
    tokens = target_tokens(app, target_url)
    headers = {'Authorization': 'Bearer ' + tokens['reset']} if tokens.get('reset') else {}
    try:
        with client(app, SETUP_TIMEOUT) as http:
            response = http.post(target_url + '/test/setup', json={'session_id': session_id, 'setup': {}}, headers=headers)
    except httpx.HTTPError as exc:
        return problem(500, f'Could not reach the target system setup ({type(exc).__name__}).', 'communication')
    if response.status_code not in (200, 201):
        return forwarded_error(response)
    try:
        confirmed = response.json().get('session_id')
    except (ValueError, AttributeError):
        confirmed = None
    if confirmed != session_id:
        return problem(500, 'Target system setup did not return the supplied session ID.', 'system')
    with app.state.tester_lock:
        app.state.tester_sessions[session_id] = {'target_url': target_url, 'status': 'ready', 'report': None}
    return JSONResponse(status_code=201, content={'session_id': session_id})


@tester_router.post('/test/setup', include_in_schema=False)
async def tester_setup(request: Request):
    body = await json_object(request)
    target = body.get('target_url') if body else None
    if not isinstance(target, str) or not valid_target(target):
        return problem(400, 'Body must be {"target_url": "<http(s) base URL without query, fragment or credentials>"}.', 'tester')
    return await run_in_threadpool(prepare_target, request.app, target.rstrip('/'))


def invalid_token(tokens):
    value = 'invalid-synthetic-token'
    while value in tokens.values():
        value += '-invalid'
    return value


def evaluate(runner, http, target_url, tokens, check, contract):
    headers = {}
    if check['auth'] == 'invalid':
        headers['Authorization'] = 'Bearer ' + invalid_token(tokens)
    elif check['auth'] in ('api', 'reset') and tokens.get(check['auth']):
        headers['Authorization'] = 'Bearer ' + tokens[check['auth']]
    kwargs = {'headers': headers}
    if 'body' in check:
        kwargs['json'] = check['body']
    if 'rawBody' in check or 'rawBytes' in check:
        kwargs['content'] = check.get('rawBytes', check.get('rawBody'))
        headers['Content-Type'] = 'application/json'
    call = f"{check['method']} {check['path']}"
    expected = check['expectedStatus']
    try:
        response = http.request(check['method'], target_url + check['path'], **kwargs)
    except httpx.TimeoutException:
        return {'outcome': 'error', 'source': 'communication',
                'message': f'The {call} request timed out. No response was available to evaluate.'}
    except httpx.HTTPError as exc:
        return {'outcome': 'error', 'source': 'communication',
                'message': f'The {call} request failed ({type(exc).__name__}). No response was available to evaluate.'}
    if response.status_code >= 500 and expected < 500:
        return {'outcome': 'error', 'source': 'system',
                'message': f'{call}: expected HTTP {expected}; the target reported an internal failure (HTTP {response.status_code}).'}
    try:
        runner.check_response(response, check, contract)
    except runner.CheckFailure as exc:
        return {'outcome': 'fail', 'message': f'{call}: {exc}'}
    detail = ' and the expected body' if 'expectedBody' in check else ' with a contract-conforming body'
    return {'outcome': 'pass', 'message': f'{call}: expected HTTP {expected}; received HTTP {expected}{detail}.'}


def code_coverage(http, target_url, session_id):
    try:
        response = http.get(target_url + '/test/report', params={'session_id': session_id})
        code = response.json()['coverage']['code'] if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        code = None
    if isinstance(code, dict) and isinstance(code.get('basis'), str) and code['basis'].strip():
        covered, total = code.get('covered'), code.get('total')
        unknown = covered is None and total is None
        measured = (all(isinstance(value,int) and not isinstance(value,bool) and value>=0
                        for value in (covered,total)) and covered<=total)
        if unknown or measured:
            return {'covered':covered,'total':total,'basis':code['basis']}
    return {'covered': None, 'total': None, 'basis': 'Source lines; the target system report was unavailable or malformed'}


def coverage(status_tool, data, checks, results, code):
    executed = {row['test_id'] for row in results if row['outcome'] != 'skip'}
    operations = [op for op in data['operations']
                  if any(check['name'] in executed and check['method'] == op['method']
                         and status_tool.operation_path(check['path']) == op['path'] for check in checks)]
    criteria = [ac for ac, criterion in data['acceptanceCriteria'].items()
                if any(name in executed for name in status_tool.criterion_checks(criterion, checks))]
    return {'code': code,
            'component': {'covered': len(operations), 'total': len(data['operations']),
                          'basis': "Operations of the pod's common interface (Phase 2 Section 5.1) exercised by at least one executed test"},
            'system': {'covered': len(criteria), 'total': len(data['acceptanceCriteria']),
                       'basis': 'Acceptance criteria AC-01 to AC-11 (Phase 2 Section 4.1) exercised by at least one executed test'}}


def suite_plan():
    runner = load_tool('run_phase3_api_tests')
    enabled = lambda name: os.environ.get(name,'false').lower() in ('true','1')
    timeline = enabled('TRACEAI_TEST_TIMELINE_ENABLED')
    records = enabled('TRACEAI_TEST_RECORDS_ENABLED')
    reports = enabled('TRACEAI_TEST_REPORTS_ENABLED')
    profile = 'phase4-reports' if reports else 'phase4-records' if records else 'phase4-timeline' if timeline else 'phase3'
    return runner, runner.planned_checks(runner.ROOT,include_timeline=timeline,include_records=records,include_reports=reports)+[CLEANUP], profile


@tester_router.get('', include_in_schema=False)
@tester_router.get('/', include_in_schema=False)
def tester_info():
    _, checks, profile = suite_plan()
    return {'service':'TraceAI hosted tester','profile':profile,'planned_checks':len(checks),
            'message':'Use the POST setup/run endpoints and GET report endpoint; this base URL describes the tester.',
            'resets_target_data':True,'check_budget_seconds':RUN_TIMEOUT,
            'documentation':'https://github.com/RamaniS123/TraceAI/blob/main/docs/testing-interface.md'}


def execute(app, session_id, session):
    target_url = session['target_url']
    report = {'session_id': session_id, 'target_url': target_url, 'results': [],
              'coverage': {name: {'covered': None, 'total': None, 'basis': 'Not measured because the tester aborted'}
                           for name in ('code', 'component', 'system')}}
    checks = []
    try:
        runner, checks, _ = suite_plan()
        status_tool = load_tool('phase_status')
        contract = json.loads(files('traceai').joinpath('openapi.json').read_text())
        data = json.loads((runner.ROOT / 'docs/requirements.json').read_text(encoding='utf-8'))
        tokens = target_tokens(app, target_url)
        deadline = monotonic() + RUN_TIMEOUT
        with client(app, CHECK_TIMEOUT) as http:
            for check in checks:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("Tester check budget exhausted")
                http.timeout = httpx.Timeout(min(CHECK_TIMEOUT,remaining))
                report['results'].append({'test_id': check['name'],
                                          **evaluate(runner, http, target_url, tokens, check, contract)})
            code = code_coverage(http, target_url, session_id)
        report['coverage'] = coverage(status_tool, data, checks, report['results'], code)
    except Exception as exc:  # Keep recorded outcomes and account for every planned test.
        done = {row['test_id'] for row in report['results']}
        remaining = [check['name'] for check in checks if check['name'] not in done]
        if remaining:
            report['results'].append({'test_id': remaining[0], 'outcome': 'error', 'source': 'tester',
                                      'message': f'The tester aborted before evaluating this test ({type(exc).__name__}).'})
            report['results'] += [{'test_id': name, 'outcome': 'skip', 'message': 'Not executed because the tester aborted.'}
                                  for name in remaining[1:]]
        elif not checks:
            report['results'].append({'test_id': 'tester-start', 'outcome': 'error', 'source': 'tester',
                                      'message': f'The tester could not load its test plan ({type(exc).__name__}).'})
        with app.state.tester_lock:
            session.update(status='aborted', report=report)
        return problem(500, 'The tester aborted; retrieve the stored report with /test/report.', 'tester')
    with app.state.tester_lock:
        session.update(status='done', report=report)
    return JSONResponse(status_code=200, content=report)


@tester_router.post('/test/run', include_in_schema=False)
async def tester_run(request: Request):
    body = await json_object(request)
    session_id = body.get('session_id') if body else None
    if not isinstance(session_id, str) or not session_id:
        return problem(400, 'Body must be {"session_id": "<id from /test/setup>"}.', 'tester')
    with request.app.state.tester_lock:
        session = request.app.state.tester_sessions.get(session_id)
        if session is None:
            return problem(404, 'Unknown tester session.', 'tester')
        if session['status'] != 'ready':
            return problem(409, 'This session has already run; create a new session to repeat the suite.', 'tester')
        session['status'] = 'running'
    return await run_in_threadpool(execute, request.app, session_id, session)


@tester_router.get('/test/report', include_in_schema=False)
def tester_report(request: Request):
    session_id = request.query_params.get('session_id')
    if not session_id:
        return problem(400, 'The session_id query parameter is required.', 'tester')
    with request.app.state.tester_lock:
        session = request.app.state.tester_sessions.get(session_id)
        if session is None:
            return problem(404, 'Unknown tester session.', 'tester')
        if session['report'] is None:
            return problem(409, 'The suite has not ended; retry the lookup later.', 'tester')
        return JSONResponse(status_code=200, content=session['report'])
