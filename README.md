# TraceAI

TraceAI records synthetic AI-interaction events through a shared HTTP API.
It supports event history and audit evidence; it does not generate AI outputs or
certify legal compliance.

## Current progress: Phase 4, chunks 1–2

- [Pod specification for cross-team testing](docs/pod-specification.md)
- [Correction links and human-review records](docs/phase-4-records.md)
- [Timeline warnings and provisional Phase 4 rules](docs/phase-4-timeline.md)
- [Frontend demonstration instructions](docs/frontend.md)
- [Proposed OpenAPI 3.1 contract](contracts/openapi.json)
- [Standalone event JSON Schema](contracts/event.schema.json)
- [Scope, assumptions, and fixture instructions](docs/phase-3-contract.md)
- [Synthetic fixtures and ordered API scenario](tests/fixtures)
- [Independent API test runner](tools/run_phase3_api_tests.py)
- [GitHub Actions workflow](.github/workflows/ci.yml)
- [Testing commands, coverage, and reports](docs/testing.md)
- [Render deployment and remaining launch step](docs/deployment.md)

These artifacts follow Sections 5–6 of the Phase 2 submission. Provisional
choices are documented for pod review.

The homepage now provides an event submission form, interaction viewer, and
service health status. [Start with a browser demonstration](docs/frontend.md).

The four Phase 3 endpoints are implemented with PostgreSQL storage, bearer
authentication, event validation, duplicate/conflict handling, and opt-in test
reset. Timeline ordering and missing/sequence warnings are now implemented in
the API. Corrections are validated as new linked records and review details are
checked and retained. Audit reports and frontend warning rendering remain later chunks.
See [development instructions](docs/development.md)
for installation, database startup, migrations, and integration tests.

## Validate the contract artifacts

Use Python 3.11 or later. From the repository root:

```sh
python -m venv /tmp/traceai-contract-venv
/tmp/traceai-contract-venv/bin/python -m pip install jsonschema==4.26.0 openapi-spec-validator==0.7.2
/tmp/traceai-contract-venv/bin/python tools/validate_contract.py
```

This checks OpenAPI structure, JSON Schema consistency, fixtures, expected
response shapes, and exact byte-boundary files. Dependencies are for artifact
validation only; the application dependencies are defined in `pyproject.toml` and pinned in
`requirements-dev.lock`.

## Deployment status

The account owner has launched the service at https://traceai-zm1t.onrender.com.
A browser health check confirmed API/database availability. Full authenticated
public evaluation remains pending; local and container tests have passed.
The frontend appears at the main address after Render deploys this update.
See [deployment instructions](docs/deployment.md).

## Remaining work

5. Complete authenticated testing against the public Render service.
6. Operating instructions and Phase 3 demonstration checklist.

Use synthetic data only. Keep credentials in environment secrets and never
commit or log them. The reset operation is for an isolated test dataset only.
