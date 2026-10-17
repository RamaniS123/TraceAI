# Phase 3 automated testing

## CI on GitHub

`.github/workflows/ci.yml` runs on pushes to main, pull requests, and manual
workflow dispatch. It uses Python 3.12 and a new PostgreSQL 16 service for each
job. No hosting account or repository secrets are required for these local CI
checks. The database password in the workflow is a disposable CI-only value;
API and reset tokens are generated for that job and masked in its logs.

The job installs the pinned dependencies, checks package compatibility, validates
the contract/fixtures, applies migrations twice, checks ORM/schema agreement,
runs pytest, starts Uvicorn, and runs the independent HTTP evaluator. It also builds and
evaluates the Docker deployment image. It preserves
the evaluator's exit status and stops the server on completion. JUnit and JSON
results are uploaded as the `phase-3-test-results` artifact even on test failure.
Reports exclude raw response bodies, request authorization headers, and tokens.

There are currently 52 pytest cases: 34 application/database integration cases,
14 runner validation/failure cases, three hosted database configuration cases, and one public frontend case. The independent evaluator has 42 checks.
A passing pytest count is distinct from a passing deployed-service evaluation.

## Run the independent evaluator against either team

Use a checkout of this repository for its shared contract and fixtures. The
runner imports no application or database code and does not need PostgreSQL,
Docker, FastAPI, or access to a team's internals. Install only its dependencies:

```sh
python -m venv /tmp/traceai-api-tests
/tmp/traceai-api-tests/bin/python -m pip install -r requirements-api-tests.txt
```

Supply the selected team's credentials securely through process environment
variables `TRACEAI_API_TOKEN` and `TRACEAI_RESET_TOKEN`. Alternatively create a
private local file containing those two names and use `--env-file`; process
environment takes precedence. Keep credential files ignored by Git, for example
`.env.team103` and `.env.team106`. Do not put tokens in command-line arguments.

**This suite deletes the selected service's test dataset.** Use only an isolated
classroom/test deployment whose owner has authorized reset, with reset enabled.
It refuses to send requests until `--allow-test-reset` is provided. The URL must
be the service origin, without `/api/v1`; remote requests require HTTPS. HTTP is
supported only for loopback development. TLS verification remains enabled, and
redirects are not followed, so credentials stay on the selected origin.

Example (replace the illustrative URL and use that team's credential file):

```sh
/tmp/traceai-api-tests/bin/python tools/run_phase3_api_tests.py \
  --base-url https://team103.example.com \
  --env-file .env.team103 \
  --allow-test-reset \
  --report reports/team103.json
```

Repeat with the other team's base URL and credentials. The evaluator uses the
same fixed inputs and expected outputs for both teams. These results validate
this provisional Phase 3 profile; full cross-team equivalence remains Phase 5.

For a local running service, using its isolated test dataset:

```sh
.venv/bin/python tools/run_phase3_api_tests.py \
  --base-url http://127.0.0.1:8000 \
  --env-file .env \
  --allow-test-reset \
  --report reports/local-api.json
```

`--wait-seconds 20` optionally polls health before testing a newly started
service. `--timeout 5` controls each HTTP request. Missing credentials, an invalid
URL, or missing reset consent yields exit 2 without making network requests.
Do not use the local example against a database whose contents you need to keep.

## Coverage and results

The 42 checks consist of:

- The 31-step shared scenario: health, reset, valid and invalid submissions,
  interaction separation, deterministic ordering/status, duplicate/conflict
  handling, authentication, reset permissions/confirmation, and reset repeatability.
- Four additional missing/invalid-authentication checks for write/reset operations.
- Six size-boundary checks: reset, submit, and verify storage for both the exact
  65,536-byte body and the rejected 65,537-byte body.
- One final cleanup reset, attempted after the first write even if a check fails.

Every response must have the documented status, JSON content type, and schema.
Where a shared expected body exists, contents must also match. Later checks in
the dependent scenario are marked unrun after a failure; they are never counted
as passes. An unhealthy service is not reset. Cleanup failures make the run fail
and may require authorized manual cleanup before another run.

Exit codes: 0 = all checks passed, 1 = service/test failure, 2 = runner
configuration or report-writing error. Reports contain a fresh run ID and UTC
start/finish timestamps, separate passed/failed/unrun counts, and sanitized check
messages. A configuration failure replaces an old report with a failed result
when the report path is writable. Unwritable reports cause exit 2; always inspect
the exit code and run ID rather than trusting an old result file.

## Requirement and operation status from a report

`tools/phase_status.py` turns an evaluator report into the phase report's
requirement entries (Q1.1) and operation table (Q3.1). Requirement names,
acceptance-criterion mappings and known gaps live in `docs/requirements.json`;
pass/fail evidence comes only from the report. It needs no extra dependencies:

```sh
python tools/phase_status.py reports/render-api.json --label "Team 106 on Render" --output reports/render-status.txt
```

A requirement is complete only when every mapped check passed and no gap is
recorded; failed or unrun checks make it partial and are named. Operations not
in the Phase 3 contract are listed as not implemented. Update `docs/requirements.json`
when scope changes; `tests/test_phase_status.py` fails if it names a check the
evaluator no longer has.

## Validation performed for chunk 4

The workflow passed actionlint 1.7.7. Its commands were exercised locally from a
fresh Python environment and a newly created disposable PostgreSQL database.
All pytest and contract checks passed; all 42 external checks passed twice on a
running Uvicorn server. The evaluator was also exercised from an environment
containing only `requirements-api-tests.txt`.

This is local evidence. The GitHub API denied workflow-status access from the
cloud workspace; a hosted Actions result must be checked separately in GitHub.
No public deployment or evaluation of the other team's service has occurred yet.
The Render launch is described in [deployment instructions](deployment.md).
The existing HTTPX/Starlette TestClient deprecation warning remains non-failing.
