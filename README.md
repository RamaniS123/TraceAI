# TraceAI

TraceAI records synthetic AI-interaction events through a shared HTTP API.
It supports event history and audit evidence; it does not generate AI outputs or
certify legal compliance.

## Current progress: Phase 3, chunks 1–3

- [Proposed OpenAPI 3.1 contract](contracts/openapi.json)
- [Standalone event JSON Schema](contracts/event.schema.json)
- [Scope, assumptions, and fixture instructions](docs/phase-3-contract.md)
- [Synthetic fixtures and ordered API scenario](tests/fixtures)

These artifacts follow Sections 5–6 of the Phase 2 submission. Provisional
choices are documented for pod review.

The four Phase 3 endpoints are implemented with PostgreSQL storage, bearer
authentication, event validation, duplicate/conflict handling, and opt-in test
reset. Timelines are sorted; warning analysis and reports remain Phase 4 work.
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

## Next chunks

4. HTTP tests and GitHub Actions.
5. Deployment and deployed-service tests.
6. Operating instructions and Phase 3 demonstration checklist.

Use synthetic data only. Keep credentials in environment secrets and never
commit or log them. The reset operation is for an isolated test dataset only.
