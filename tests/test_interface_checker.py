"""Cross-team evidence distinguishes failed checks, incomplete runs and no run."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location('interface_checker',Path(__file__).parents[1]/'tools/check_testing_interface.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
TARGET = 'https://system.test'
TESTER = 'https://tester.test'


def measure():
    return {'covered':None,'total':None,'basis':'Not instrumented'}


def report(outcome='pass'):
    return {'session_id':'s1','target_url':TARGET,'results':[{'test_id':'health','outcome':outcome,'message':'Checked health.'}],
            'coverage':{name:measure() for name in ('code','component','system')}}


def run(tmp_path, handler, *extra):
    path = tmp_path/'evidence.json'
    code = checker.main(['--tester',TESTER,'--target',TARGET,'--allow-test-reset','--report',str(path),*extra],transport=httpx.MockTransport(handler))
    return code,json.loads(path.read_text())


def exchange(stored=None, run_status=200, run_body=None, system=None):
    stored = report() if stored is None else stored
    def handler(request):
        assert 'authorization' not in request.headers
        if request.method=='POST' and request.url.path=='/test/setup':
            return httpx.Response(201,json={'session_id':'s1'})
        if request.method=='POST':
            return httpx.Response(run_status,json=stored if run_body is None else run_body)
        if request.url.host=='tester.test':
            return httpx.Response(200,json=stored)
        return httpx.Response(200,json=system if system is not None else {'session_id':'s1','coverage':{'code':measure()}})
    return handler


def test_reset_requires_consent_and_replaces_stale_pass(tmp_path):
    path=tmp_path/'evidence.json';path.write_text('{"completed":true}')
    def unexpected(request):
        pytest.fail('No HTTP requests without authorization')
    assert checker.main(['--tester',TESTER,'--target',TARGET,'--report',str(path)],transport=httpx.MockTransport(unexpected))==2
    data=json.loads(path.read_text())
    assert data['status']=='blocked' and data['completed'] is False and data['counts'] is None


def test_preflight_is_read_only_and_not_a_completed_suite(tmp_path):
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path=='/health':return httpx.Response(200,json={'status':'ok'})
        if request.url.path=='/openapi.json':return httpx.Response(200,json={'openapi':'3.1.0','paths':{}})
        return httpx.Response(404,json={'message':'Unknown session.','source':'system'})
    code,data=run(tmp_path,handler,'--preflight')
    assert code==0 and data['status']=='ready' and data['completed'] is False and data['counts'] is None
    assert len(seen)==4 and all(r.method=='GET' for r in seen)


@pytest.mark.parametrize('failure',['http','offline','redirect'])
def test_failed_setup_never_counts_as_a_completed_test_and_never_echoes_body(tmp_path,capsys,failure):
    seen=[]
    def handler(request):
        seen.append(request)
        if failure=='offline':raise httpx.ConnectError('secret-key /private/database')
        return httpx.Response(401 if failure=='http' else 302,headers={'Location':'https://other.test'},json={'message':'secret-key /private/database'})
    code,data=run(tmp_path,handler)
    assert code==1 and data['status']=='blocked' and data['counts'] is None and data['completed'] is False
    assert len(seen)==1
    text=json.dumps(data)+capsys.readouterr().out
    assert 'secret-key' not in text and '/private/database' not in text


@pytest.mark.parametrize('outcome,require_pass,code',[('pass',False,0),('fail',False,0),('fail',True,1)])
def test_valid_report_is_saved_with_honest_outcomes(tmp_path,outcome,require_pass,code):
    expected=report(outcome)
    result,data=run(tmp_path,exchange(expected),*(['--require-pass'] if require_pass else []))
    assert result==code and data['completed'] is True
    assert data['suite_report']==expected and data['counts'][outcome]==1
    raw=tmp_path/data['suite_report_file']
    assert json.loads(raw.read_text())==expected
    assert data['status']==('passed' if outcome=='pass' else 'completed_with_failures')
    assert (tmp_path/'evidence.json').stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('change',[
    {'results':[123]}, {'results':[{'test_id':{},'outcome':[],'message':'x'}]},
    {'coverage':[]}, {'results':[]}, {'session_id':'different'},
    {'results':[{'test_id':'x','outcome':'error','source':{},'message':'x'}]},
])
def test_malformed_peer_report_is_invalid_not_a_crash_or_pass(tmp_path,change):
    code,data=run(tmp_path,exchange({**report(),**change}))
    assert code==1 and data['completed'] is False and data['counts'] is None
    assert data['status']=='invalid'


def test_aborted_runner_preserves_partial_report_but_is_not_complete(tmp_path):
    partial=report('skip')
    code,data=run(tmp_path,exchange(partial,run_status=500,run_body={'message':'aborted','source':'tester'}))
    assert code==1 and data['status']=='incomplete' and data['completed'] is False
    assert data['suite_report']==partial and data['counts']['skip']==1


def test_run_and_stored_report_must_match(tmp_path):
    code,data=run(tmp_path,exchange(report(),run_body=report('fail')))
    assert code==1 and data['completed'] is False
    assert 'Stored report differs from the run response.' in data['problems']


@pytest.mark.parametrize('covered,total',[(True,1),(None,4),(5,None),(4,2),(-1,4)])
def test_inconsistent_coverage_is_rejected(covered,total):
    assert checker.measure_problems('code',{'covered':covered,'total':total,'basis':'Lines'})
