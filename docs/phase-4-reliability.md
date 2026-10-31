# Phase 4 chunk 4 — reliability and safe errors

This increment addresses REQ-08 / AC-06 (storage failure), REQ-09 / AC-07
(persistence), and REQ-12 / AC-09 (safe errors/logs). OpenAPI 0.4.1 documents
an unexpected 500 response; successful API and course tester formats are unchanged.
No database migration or registry URL change is required.

## Delivered behavior

- Event receipts and successful reset results are returned only after their
  PostgreSQL transactions commit. Failed statements or commits return safe 503
  errors and roll back. Tests reject real COMMITs using deferred PostgreSQL triggers,
  and check that previous events survive failed writes and failed resets.
- Connections use pre-ping and a three-second connect timeout. PostgreSQL statements,
  including waits for locks, have a five-second timeout by default. Configure
  `TRACEAI_STORAGE_TIMEOUT_MS` between 100 and 60000 if needed. A canceled operation
  returns 503 and the connection transaction rolls back; a later retry can succeed.
- Unexpected buffered request failures return a fixed JSON 500 without logging
  the exception, SQL, submitted payload, path, or bearer headers. The course
  `/test/*` and `/tester/test/*` endpoints retain their `{message, source}` shape.
- Deployment startup exits with a fixed diagnostic if migration/configuration fails;
  it does not publish raw connection exceptions or serve against an unknown schema.
- Normal Uvicorn access logs retain HTTP status but redact request targets and
  methods, since a user could put a secret in a URL. Application failure diagnostics
  retain a fixed `INTERNAL_ERROR` code, with no raw traceback.
- Tester setup does not reflect a target's arbitrary error message. It preserves
  the HTTP status and recognized source and supplies a fixed message. Testing
  request JSON is bounded to 65536 bytes and rejects duplicate keys, non-finite
  numbers, malformed encoding, and excessive nesting.
- Failed system preparation removes its temporary session reservation so retry
  is possible. Test sessions remain memory-only; a restart requires new sessions.

## Evidence and execution

`tests/integration/test_api.py` covers statement and commit failures for inserts
and resets, deferred PostgreSQL COMMIT rejection, a blocked write canceled by
statement timeout, and recovery after PostgreSQL terminates a pooled connection.
It checks retained data, safe responses, and idempotent retries. `tests/test_safety.py`
checks unexpected exceptions, database exception details, malformed/oversized
bodies, remote tester errors, course error shapes, and access-log canaries.

`tools/check_local_reliability.py` starts independent Uvicorn processes against
one explicitly supplied migrated `*_test` PostgreSQL database. It verifies exact
reports, reviews and correction records across an app-process restart, duplicate
retries, unavailable-storage responses, failed-startup exit, and actual process logs containing no
synthetic secret canaries or tracebacks. CI runs it separately from the ordinary
HTTP evaluator. It resets its target, uses only local HTTP servers, and refuses to run
without an explicit isolated database and reset authorization:

```sh
# Set TRACEAI_TEST_DATABASE_URL securely in the process environment first.
.venv/bin/python tools/check_local_reliability.py --allow-test-reset \
  --report reports/local-reliability.json
```

These are local integration and process checks, not new cross-team API checks.
Hosted evaluator counts remain 42 / 68 / 99 / 126; AC-06 is not counted in remote
coverage because there is no public endpoint for breaking a target's database.
Performance acceptance remains Phase 5. Pod compatibility remains unresolved.

## Practical limits

A lost connection during COMMIT can leave its outcome uncertain to the client.
A 503 therefore does not guarantee that an event was absent: retry the identical
event ID/content to discover whether it was committed, rather than assigning a
new ID. A response timeout must never be treated as a successful submission.
Health checks read availability and migration revision, not future write success.
Process restart checks do not establish disaster recovery, backups or capacity.
These checks cover application-controlled errors/logs under the normal deployment
configuration; independently enabling verbose SQL/HTTP logging or infrastructure
request logging needs its own review. Authorized event/report responses intentionally
contain submitted records, so use synthetic data and keep credentials out of records.

## Workspace validation (2026-10-31)

- 163 pytest checks passed against isolated PostgreSQL; contract/migration checks passed.
- Five local reliability groups passed, including independent app processes and startup failure.
- Deployment-image evaluator and hosted setup/run/report each passed 126/126 checks.
- In private Docker containers, stopping PostgreSQL produced safe 503 responses;
  restarting PostgreSQL and then the app preserved all three fixture reports and
  duplicate-ID behavior. Secret-canary/traceback checks passed on container logs.

This is Team 106 local evidence, not a Team 103 compatibility result or a public
Render outage test. The ordinary test-client deprecation warning remains non-failing.
