# Local development

Run commands from the repository root. Requires Python 3.11+ and Docker Compose
v2. The checked-in dependency lock was validated on Python 3.12/Linux. The
PostgreSQL service uses version 16. No public deployment is configured yet.

## Install and configure

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
```

Copy the example only if `.env` does not already exist. Replace its password and
token placeholders with locally generated random secrets. Database password and
both connection URLs must agree; URL-encode reserved characters in passwords.
Use two distinct API and reset tokens. `.env` is ignored; never commit it or
print its contents in logs. Shell environment values override `.env` settings.
Only `TRACEAI_DATABASE_URL` is required to start this foundation. Tokens authorize protected endpoints. Reset also requires an explicit
`TRACEAI_TEST_RESET_ENABLED=true` setting for the isolated test dataset.

The onboarding workspace already has a private `.env` with generated local
credentials, an installed `.venv`, and migrated development/test databases.
These are local setup state, not committed credentials.

## Start database and migrate

```sh
docker compose up -d --wait db
.venv/bin/alembic upgrade head
.venv/bin/alembic check
```

Compose binds PostgreSQL to loopback and retains data in its named volume.
Changing the password in `.env` does not update an already initialized database;
rotate it explicitly instead of deleting the volume. Do not use `down -v` unless
you intentionally want to destroy all local data. Ordinary `docker compose stop`
and `docker compose up -d --wait db` retain data.

Migrations are explicit, not run on application startup. `alembic upgrade head`
is repeatable. Downgrading to base deletes the events table and is only for a
disposable test database. Do not use automatic `create_all` in place of migrations.

## Start the application

```sh
.venv/bin/uvicorn traceai.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Make an internal request to `GET /health`. Expected response after migration:

```json
{"status":"healthy","api":"available","storage":"available"}
```

The endpoint checks the events table and migration revision. An unavailable,
unmigrated, or mismatched database yields HTTP 503 and the same safe shape with
status unhealthy and storage unavailable. This does not yet test write access
or implement complete Phase 4 storage-failure analysis.

All four Phase 3 operations are available. `/docs` and `/openapi.json` serve the
authored contract in `contracts/openapi.json`; warning analysis and reports are
deferred as documented in the Phase 3 profile.

## Database design

The `events` table has a globally unique event ID primary key, interaction ID,
event type, UTC timestamp instant, original timestamp text, application/model
versions, JSONB data, and a server-generated receipt timestamp. A composite index
on interaction ID, timestamp, and event ID supports separate ordered histories.
C collation provides deterministic ID ordering. Interaction identity is derived
from events; a second interaction table is unnecessary for this increment.

Database constraints enforce ID/version lengths, allowed event types, and object
payloads. Event-specific validation is performed at the API boundary.
The database does not currently enforce append-only access: The submission API only inserts records and never updates accepted events.
Reset is the explicit test-only deletion exception.
PostgreSQL stores timestamp instants at microsecond precision; the original text
is retained for responses and exact higher-precision timestamp ordering.

## Integration tests

Create a separate empty test database once:

```sh
docker compose exec -T db createdb -U traceai traceai_test
```

Set `TRACEAI_TEST_DATABASE_URL` in `.env` to its URL. Migrate it explicitly using a
secure environment override; this snippet reads the local value without printing it:

```sh
.venv/bin/python - <<'PY'
import os
import subprocess
from dotenv import dotenv_values
url = os.environ.get('TRACEAI_TEST_DATABASE_URL') or dotenv_values('.env')['TRACEAI_TEST_DATABASE_URL']
subprocess.run(['.venv/bin/alembic', 'upgrade', 'head'],
               env={**os.environ, 'TRACEAI_DATABASE_URL': url}, check=True)
PY
.venv/bin/pytest -q
.venv/bin/python tools/validate_contract.py
```

Without a test database URL, database-dependent tests are explicitly skipped.
A zero-test or skipped run does not establish readiness. Tests use random IDs
and clean up their records; use only an isolated test database. Never point
integration tests at production or a shared dataset.

## Verified foundation and API

- PostgreSQL container readiness and repeatable development database migration.
- Upgrade/downgrade/upgrade cycle on the separate disposable test database.
- Alembic metadata check detects no pending model changes.
- All 34 integration checks pass against real PostgreSQL, including the shared
  31-step HTTP scenario and request-size boundaries.
- Uvicorn starts and a real HTTP health request succeeds.
- Existing contract-artifact validation still passes.

The installed FastAPI/Starlette version emits one deprecation warning for the
HTTPX-backed TestClient; tests still execute and pass. CI and the independent
HTTP evaluator are described in [testing instructions](testing.md).

## Chunk 3: working API

The four Phase 3 endpoints are now implemented and `/docs` serves the authored
contract. Restart Uvicorn after updating the checkout if not using `--reload`.

- Set `TRACEAI_API_TOKEN` and a distinct `TRACEAI_RESET_TOKEN` securely.
- Ordinary operations accept either token; reset requires the reset token.
- Enable `TRACEAI_TEST_RESET_ENABLED=true` only for an isolated test dataset.
  The default is false, which makes reset return 403 even for its valid token.
- Health is public. Missing token configuration grants no protected access.
- The same database migration remains current; chunk 3 requires no migration.

For a manual request, read your local secrets without printing them:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from dotenv import dotenv_values
import httpx
values = dotenv_values('.env')
headers = {'Authorization': 'Bearer ' + values['TRACEAI_API_TOKEN']}
event = json.loads(Path('tests/fixtures/valid-events.json').read_text())[0]
response = httpx.post('http://127.0.0.1:8000/api/v1/events', headers=headers, json=event)
print(response.status_code, response.json())
response = httpx.get('http://127.0.0.1:8000/api/v1/interactions/int-a', headers=headers)
print(response.status_code, response.json())
PY
```

The first submission returns 201, an exact repeat returns 200 with duplicate true,
and different content reusing its event ID returns 409. Retrieval preserves the
original timestamp text and returns ordered records and empty warnings.

`pytest -q` now includes the full 31-step shared scenario against real PostgreSQL,
body-size boundaries over a streamed request, authentication and reset controls,
concurrent identical submissions, numeric/timestamp precision, and storage errors.
API tests exercise destructive reset and refuse database names not ending in
`_test`. Do not enable these tests on any important or shared dataset.

The standalone API evaluator and GitHub Actions workflow are now included; see
[testing instructions](testing.md). Public deployment is chunk 5; local passing
tests do not establish deployment.
