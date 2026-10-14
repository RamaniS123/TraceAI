"""Ensure the external evaluator fails for broken services without leaking data."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location('api_runner', Path(__file__).parents[1] / 'tools/run_phase3_api_tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture(autouse=True)
def tokens(monkeypatch):
    monkeypatch.setenv('TRACEAI_API_TOKEN', 'synthetic-api-secret')
    monkeypatch.setenv('TRACEAI_RESET_TOKEN', 'synthetic-reset-secret')


def health():
    return {'status': 'healthy', 'api': 'available', 'storage': 'available'}


def reset():
    return {'reset': True, 'remainingEvents': 0, 'remainingInteractions': 0}


def test_no_reset_consent_means_no_network(capsys):
    def unexpected(request):
        pytest.fail('Network must not be used without explicit reset consent')
    assert runner.main(['--base-url', 'https://example.test'], transport=httpx.MockTransport(unexpected)) == 2
    assert 'Configuration error' in capsys.readouterr().err


@pytest.mark.parametrize('url', ['http://example.test', 'https://user:password@example.test',
                                 'https://example.test/api/v1', 'https://example.test?token=secret',
                                 'https://example.test/#fragment', 'file:///tmp/test',
                                 'https://example.test:not-a-port'])
def test_bad_destination_is_rejected_before_network(url):
    def unexpected(request):
        pytest.fail('Unsafe or ambiguous destination must not receive credentials')
    assert runner.main(['--base-url', url, '--allow-test-reset'], transport=httpx.MockTransport(unexpected)) == 2


def test_unhealthy_service_is_not_reset_and_old_report_is_replaced(tmp_path):
    report = tmp_path / 'result.json'
    report.write_text('{"status":"passed","runId":"old-run"}')
    requests = []
    def unavailable(request):
        requests.append(request)
        return httpx.Response(503, json={'status': 'unhealthy', 'api': 'available', 'storage': 'unavailable'})
    code = runner.main(['--base-url', 'https://example.test', '--allow-test-reset', '--report', str(report)],
                       transport=httpx.MockTransport(unavailable))
    assert code == 1
    assert len(requests) == 1
    assert requests[0].url.path == '/health'
    assert 'Authorization' not in requests[0].headers
    data = json.loads(report.read_text())
    assert data['runId'] != 'old-run'
    assert data['status'] == 'failed'
    assert data['passed'] == 0
    assert data['failed'] == 1
    assert data['unrun'] == data['total'] - 1


def test_redirect_is_not_followed(tmp_path):
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'https://another.example/health'})
    assert runner.main(['--base-url', 'https://example.test', '--allow-test-reset'],
                       transport=httpx.MockTransport(redirect)) == 1
    assert len(requests) == 1


def test_wrong_response_content_fails_and_cleanup_runs(tmp_path, capsys):
    requests = []
    def broken(request):
        requests.append(request)
        if request.url.path == '/health':
            return httpx.Response(200, json=health())
        if request.url.path == '/api/v1/test/reset':
            return httpx.Response(200, json=reset())
        # Schema-valid receipt with wrong content must still fail the fixture.
        return httpx.Response(201, json={'eventId': 'wrong-id', 'interactionId': 'int-a', 'stored': True, 'duplicate': False})
    report = tmp_path / 'result.json'
    assert runner.main(['--base-url', 'https://example.test', '--allow-test-reset', '--report', str(report)],
                       transport=httpx.MockTransport(broken)) == 1
    data = json.loads(report.read_text())
    assert data['checks'][2]['status'] == 'failed'
    assert data['checks'][-1] == {'name': 'final-cleanup', 'status': 'passed'}
    assert [request.url.path for request in requests].count('/api/v1/test/reset') == 2
    assert 'wrong-id' not in report.read_text()


def test_schema_failure_and_sensitive_response_are_not_logged(tmp_path, capsys):
    def broken(request):
        if request.url.path == '/health':
            return httpx.Response(200, json=health())
        if request.url.path == '/api/v1/test/reset':
            return httpx.Response(200, json=reset())
        return httpx.Response(201, json={'credential': 'synthetic-api-secret', 'localPath': '/private/database'})
    report = tmp_path / 'result.json'
    assert runner.main(['--base-url', 'https://example.test', '--allow-test-reset', '--report', str(report)],
                       transport=httpx.MockTransport(broken)) == 1
    output = capsys.readouterr()
    combined = output.out + output.err + report.read_text()
    assert 'synthetic-api-secret' not in combined
    assert 'synthetic-reset-secret' not in combined
    assert '/private/database' not in combined
    assert 'does not match the API contract schema' in combined


def test_network_failure_is_reported_without_exception_url(tmp_path, capsys):
    def offline(request):
        raise httpx.ConnectError('sensitive diagnostic: synthetic-api-secret', request=request)
    assert runner.main(['--base-url', 'https://example.test', '--allow-test-reset'],
                       transport=httpx.MockTransport(offline)) == 1
    text = capsys.readouterr().out
    assert 'ConnectError' in text
    assert 'synthetic-api-secret' not in text


def test_configuration_failure_does_not_leave_a_stale_pass_report(tmp_path):
    report = tmp_path / 'result.json'
    report.write_text('{"status":"passed","runId":"stale"}')
    assert runner.main(['--base-url', 'https://example.test', '--report', str(report)]) == 2
    data = json.loads(report.read_text())
    assert data['status'] == 'failed'
    assert data['runId'] != 'stale'
    assert data['checks'][0]['name'] == 'configuration'
