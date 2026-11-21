"""The public interface loads independently of database/auth availability."""
from fastapi.testclient import TestClient

from traceai.config import Settings
from traceai.main import create_app


def test_homepage_assets_are_public_without_database_or_credential_exposure():
    settings = Settings(database_url='postgresql+psycopg://unavailable@127.0.0.1:1/unavailable',
                        api_token='synthetic-private-api-token', reset_token='synthetic-private-reset-token', _env_file=None)
    with TestClient(create_app(settings)) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert page.headers['content-type'].startswith('text/html')
        assert page.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert 'synthetic-private-api-token' not in page.text
        assert 'synthetic-private-reset-token' not in page.text
        for path, content_type in [('/assets/app.css', 'text/css'), ('/assets/app.js', 'javascript')]:
            response = client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers['content-type']
        assert client.get('/health').status_code == 503
        assert client.get('/api/v1/interactions/private').status_code == 401
        assert client.get('/assets/missing.js').status_code == 404
        assert '/' not in client.get('/openapi.json').json()['paths']



def test_head_probes_preserve_headers_and_unhealthy_storage_status():
    settings = Settings(database_url='postgresql+psycopg://unavailable@127.0.0.1:1/unavailable', _env_file=None)
    with TestClient(create_app(settings)) as client:
        page = client.get('/')
        head = client.head('/')
        assert head.status_code == 200 and head.content == b''
        for name in ('content-type', 'content-length', 'cache-control', 'content-security-policy'):
            assert head.headers[name] == page.headers[name]
        health = client.get('/health')
        probe = client.head('/health')
        assert health.status_code == probe.status_code == 503
        assert probe.content == b''
        assert probe.headers['content-length'] == health.headers['content-length']
        assert probe.headers['x-traceai-contract'] == health.headers['x-traceai-contract'] == '0.4.2'
