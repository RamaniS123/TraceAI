#!/bin/sh
set -eu

# One application instance for this semester deployment; migrate before serving.
python -m alembic upgrade head
exec python -m uvicorn traceai.main:create_app --factory \
    --host 0.0.0.0 --port "${PORT:-8000}"
