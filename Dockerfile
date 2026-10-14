# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements-runtime.lock requirements-build.lock ./
# Optional BuildKit secrets support this workspace's verified HTTPS proxy.
# Normal Render builds need no secrets; proxy credentials never enter an image layer.
RUN --mount=type=secret,id=https_proxy --mount=type=secret,id=http_proxy --mount=type=secret,id=ca_bundle python - <<'PY'
import os
from pathlib import Path
import subprocess
import sys
environment = os.environ.copy()
for name in ('https_proxy', 'http_proxy'):
    secret = Path('/run/secrets') / name
    if secret.is_file():
        environment[name] = environment[name.upper()] = secret.read_text().strip()
certificate = Path('/run/secrets/ca_bundle')
if certificate.is_file():
    environment['PIP_CERT'] = str(certificate)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-runtime.lock', '-r', 'requirements-build.lock'], env=environment, check=True)
PY
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-build-isolation --no-deps . \
    && python -m pip check
COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy ./deploy
RUN useradd --create-home --uid 10001 traceai \
    && chmod -R a+rX /app \
    && chmod +x deploy/start.sh
USER traceai
EXPOSE 8000
CMD ["./deploy/start.sh"]
