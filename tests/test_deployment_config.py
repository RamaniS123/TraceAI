"""Managed PostgreSQL URL compatibility without changing connection security."""
import pytest
from sqlalchemy.engine import make_url

from traceai.config import Settings


@pytest.mark.parametrize('scheme', ['postgres', 'postgresql', 'postgresql+psycopg'])
def test_hosted_database_urls_preserve_password_and_tls_options(scheme):
    settings = Settings(database_url=f'{scheme}://traceai:synthetic%40password@db.example:5432/traceai?sslmode=verify-full&sslrootcert=%2Fcerts%2Froot.pem', _env_file=None)
    url = make_url(settings.database_url.get_secret_value())
    assert url.drivername == 'postgresql+psycopg'
    assert url.password == 'synthetic@password'
    assert url.query['sslmode'] == 'verify-full'
    assert url.query['sslrootcert'] == '/certs/root.pem'
    assert 'synthetic' not in repr(settings)
