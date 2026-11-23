# TraceAI

TraceAI records synthetic AI-interaction events through a shared HTTP API.
It supports event history and audit evidence; it does not generate AI outputs or
certify legal compliance.

## Current progress: Phase 5 chunk 6 — technical handoff and demo prepared

- [Phase 5 delivery status and known limitations](docs/phase-5-delivery.md)
- [Repeatable Phase 5 demo](docs/phase-5-demo.md)
- [Updated engineering models and Phase 2 reconciliation](docs/phase-5-models.md)
- [Architecture, deployment and dependency models](docs/architecture.md)
- [Latest November 22 cross-team results: 126/126 forward and 130/130 peer report](docs/phase-5-cross-team-latest.json)
- [Phase 5 regression and cross-team status](docs/phase-5-regression.md)
- [Phase 5 timing, benchmark and measured results](docs/phase-5-performance.md)
- [Phase 5 capacity loader, verification and results](docs/phase-5-capacity.md)
- [Phase 5 threat model and security review](docs/phase-5-security-review.md)
- [Phase 5 targets, measurement and dataset-isolation plan](docs/phase-5-plan.md)
- [Confirmed Phase 4 functional results](docs/phase-4-confirmed-results.json)
- [Historical Phase 4 delivery](docs/phase-4-delivery.md)
- [Pod specification for cross-team testing](docs/pod-specification.md)
- [Browser warnings and audit reports](docs/phase-4-frontend.md)
- [Reliability, safe errors and restart evidence](docs/phase-4-reliability.md)
- [Audit reports](docs/phase-4-reports.md)
- [Correction links and human-review records](docs/phase-4-records.md)
- [Timeline warnings and provisional Phase 4 rules](docs/phase-4-timeline.md)
- [Frontend demonstration instructions](docs/frontend.md)
- [Shared OpenAPI 3.1 contract, project version 0.4.2](contracts/openapi.json)
- [Standalone event JSON Schema](contracts/event.schema.json)
- [Scope, assumptions, and fixture instructions](docs/phase-3-contract.md)
- [Synthetic fixtures and ordered API scenario](tests/fixtures)
- [Independent API test runner](tools/run_phase3_api_tests.py)
- [GitHub Actions workflow](.github/workflows/ci.yml)
- [Testing commands, coverage, and reports](docs/testing.md)
- [Render deployment and operations](docs/deployment.md)

The project API follows the adopted 0.4.2 functional baseline. Proposed Phase 5
workload/timing interpretation, hosted performance and fresh reciprocal validation
remain separate outstanding items, documented in the delivery status.

The homepage provides event submission, interaction history, service health,
timeline warnings, and downloadable audit reports.
[Start with a browser demonstration](docs/frontend.md).

The four Phase 3 endpoints are implemented with PostgreSQL storage, bearer
authentication, event validation, duplicate/conflict handling, and opt-in test
reset. Timeline ordering and missing/sequence warnings are now implemented in
the API. Corrections are validated as new linked records and review details are
checked and retained. Audit reports expose those records through the API and
browser, with review/correction summaries and an exact JSON download.
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

## Deployment and validation baseline

The deployed system at https://traceai-zm1t.onrender.com is healthy as of the
read-only Phase 5 baseline check. Phase 4 functional validation completed against
our public service (126/126), our tester against Team 103 (126/126), and their
tester against us (130/130). See [recorded results](docs/phase-4-confirmed-results.json).
These are historical functional results, not Phase 5 load-test results.

Phase 5 targets are 10,000 stored events, 100 events in one interaction and 1,000
ordinary requests from up to ten clients, with at least 95% completing within one
second excluding external network delay. The [profile](contracts/phase-5-capacity-profile.json)
and [plan](docs/phase-5-plan.md) define the proposed measurement/isolation approach.
Local capacity and performance runs passed: 10,000 records retained and 1,000/1,000
correct requests at most one second, with ten observed in flight. See the
[measurements and limits](docs/phase-5-performance.md). Hosted/peer load testing
and pod confirmation of the proposed profile remain outstanding.
Database expiration is not exposed by health and remains unverified.

Use synthetic data only. Keep credentials in environment secrets and never
commit or log them. The reset operation is for an isolated test dataset only.
