# Phase 4 chunk 3 — audit reports

`GET /api/v1/interactions/{interactionId}/report` requires the API bearer token.
The provisional Team 106 format is defined by `AuditReport` in OpenAPI 0.4.0;
pod agreement and cross-team compatibility remain outstanding.

The response contains interaction ID/status, event count and first/last occurrence
times, sorted unique model/application versions, ordered original events,
timeline warnings, review actions, and correction links. All sections use one
interaction snapshot. Corrections never replace original records or review actions;
`linkValid` distinguishes valid links from invalid historical links. Legacy accepted
review fields remain readable. Incomplete interactions return reports with warnings.

Unchanged history produces identical JSON: there is no generated report timestamp.
Late events recompute the report, and reset removes it. Responses use
`Cache-Control: no-store`. Unknown IDs return 404, missing/invalid credentials 401,
and unavailable storage 503. The disclaimer says the report supports review of
submitted records and does not certify legal compliance or evaluate decisions.

## Validation

The 27-step `tests/fixtures/phase-4-reports-scenario.json` checks full and incomplete
reports, repeatability, version separation, authentication, unknown IDs, correction
chains, duplicate submissions, late events, invalid corrections, and reset.
Unit/integration tests also check legacy records, exact numeric payloads, read-only
behavior, schema conformance, and storage failure.

```sh
.venv/bin/python tools/run_phase3_api_tests.py --base-url "$BASE_URL" \
  --allow-test-reset --phase4-reports --report reports/audit-api.json
```

Use only an authorized synthetic test system: this suite resets its data.
The reports profile includes timeline and record profiles (126 checks total).
Baseline, timeline, and records profiles retain 42, 68, and 99 checks respectively.
Set `TRACEAI_TEST_REPORTS_ENABLED=true` to opt the hosted tester into this profile;
the default stays at 42 checks. No registry URLs or setup/run/report fields change.
Coverage measures exercised requirements, not completion of all Phase 4 work.
Reliability/security, frontend presentation, and pod compatibility remain later chunks.
No database migration is needed.
