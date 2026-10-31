"""Deploy without publishing migration/configuration exception contents."""
import os
import sys

from alembic import command
from alembic.config import Config


def main():
    try:
        command.upgrade(Config('alembic.ini'), 'head')
    except Exception:
        # Database connection/config errors can include host names and file paths.
        # Fail deployment rather than start against an unknown schema.
        print('Startup failed: database migration could not be completed.', file=sys.stderr)
        return 1
    print('Database migrations completed.', flush=True)
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'traceai.main:create_app',
                             '--factory', '--host', '0.0.0.0', '--port', os.environ.get('PORT', '8000')])


if __name__ == '__main__':
    raise SystemExit(main())
