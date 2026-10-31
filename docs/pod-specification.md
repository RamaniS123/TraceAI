# TraceAI specification and implementation profile

**Phase 4 status:** Team 106's warning, correction-link, and review increments
are implemented under provisional rules in [phase-4-timeline.md](phase-4-timeline.md)
and [phase-4-records.md](phase-4-records.md). This page is our registered
implementation profile; it is not evidence that Team 103 approved the new rules.
The Phase 2 model attachment and report Section 5 also differ, so their authority
and lifecycle details still need reconciliation.

This page is the specification registered for cross-team testing. It
covers the shared project API, test preparation, resets, cleanup, acceptance
criteria and coverage counting. The authority is the **Phase 2 specification
v1.1, agreed by Teams 103 and 106 on 2026-09-22** (Phase 2 Sections 3–5). The
machine-readable files below implement that agreement for Phase 3.

| Part | Definition |
| --- | --- |
| Project API | [contracts/openapi.json](../contracts/openapi.json), OpenAPI 3.1 (decisions in [phase-3-contract.md](phase-3-contract.md)) |
| System testing interface (`/test/setup`, `/test/report`) and tester | [testing-interface.openapi.yaml](testing-interface.openapi.yaml), behaviour in [testing-interface.md](testing-interface.md) |
| Acceptance criteria and test mapping | Section 4 below; machine-readable in [requirements.json](requirements.json) |

All data is synthetic. TraceAI supports record-keeping under EU AI Act Art. 12(1);
nothing it returns certifies compliance.

## 1. Project API (Phase 2 Section 5.1)

Base path `/api/v1`, UTF-8 JSON, RFC 3339 UTC timestamps (`Z` or `+00:00`).
Protected operations require `Authorization: Bearer <token>`.

| Operation | Requirements | Success | Errors | Phase |
| --- | --- | --- | --- | --- |
| `POST /api/v1/events` | REQ-01, 04, 05, 07, 08, 11, 12 | 201 receipt; identical duplicate 200 | 400, 401, 409, 413 (> 65,536 bytes), 422, 503 | 3 |
| `GET /api/v1/interactions/{interactionId}` | REQ-02, 03, 05, 09, 11, 14 | 200 events ordered by `occurredAt`, then `eventId` | 401, 404, 503 | 3–4 (timeline warnings; provisional rules linked above) |
| `GET /api/v1/interactions/{interactionId}/report` | REQ-05, 06, 09, 11, 14 | 200 audit report | 401, 404, 503 | 4 |
| `POST /api/v1/test/reset` with `{"confirm": true}` | REQ-10, 11, 14 | 200 `{reset, remainingEvents: 0, remainingInteractions: 0}` | 400, 401, 403, 503 | 3 |
| `GET /health` (no auth) | REQ-08, 14 | 200 `{status, api, storage}` | 503 | 3 |

Events (`EventInput`) require `eventId`, `interactionId`, `eventType`, `occurredAt`,
`modelVersion`, `applicationVersion` and `data`. The six event types are
`interaction.started`, `model.output_generated`, `review.completed`,
`interaction.completed`, `interaction.stopped` and `record.corrected`. Status is
`in_progress` until a terminal event, then `completed` or `stopped`. Errors use
`{"error": {"code", "message", "details"?}}`.

## 2. Preparation, resets and cleanup

- **Preparation.** System `POST /test/setup` with `{"session_id", "setup": {}}`
  and the reset bearer token resets the isolated test dataset and returns
  `201 {"session_id"}`. A reused session ID returns 409. No starting data is
  loaded; each test creates the events it needs.
- **Session identification.** Project requests carry no session ID. Each session
  starts from the empty dataset, so sessions run one at a time: a new setup ends
  the previous session's isolation.
- **Resets between tests.** The shared scenario resets with
  `POST /api/v1/test/reset` where it needs an empty baseline (steps 2, 29 and 31,
  and before each byte-boundary check).
- **Cleanup.** The suite ends with a final reset, attempted even after a failure.
- **Code coverage.** System `GET /test/report?session_id=...` returns
  `coverage.code`; `null` counts with a `basis` when instrumentation is unavailable.
- **Access.** Bearer tokens are distributed privately, never in URLs, the
  registry or the repository. Testers need the target's reset token for system
  setup and its API token for protected project operations.

## 3. Shared test suite

The pod suite is the 31-step ordered scenario in
[tests/fixtures/phase-3-scenario.json](../tests/fixtures/phase-3-scenario.json),
plus four authentication checks, six 64 KiB boundary checks and a final cleanup:
42 checks, run by [tools/run_phase3_api_tests.py](../tools/run_phase3_api_tests.py)
and the deployed tester. Expected outputs come from this specification, not from
either implementation.

## 4. Acceptance criteria (Phase 2 Section 4.1)

| AC | Name | Requirements | Phase | Automated checks |
| --- | --- | --- | --- | --- |
| AC-01 | Event submission and validation | REQ-01, REQ-07 | 3 | scenario 3–6, 11–22; boundary checks |
| AC-02 | Interaction grouping | REQ-02 | 3 | scenario 7, 8, 27, 28 |
| AC-03 | Timeline and warning detection | REQ-03 | 4 | opt-in 26-step timeline scenario plus unit/integration tests |
| AC-04 | Duplicate and conflicting events | REQ-04 | 4 (delivered early) | scenario 9, 10 |
| AC-05 | Human review and audit report | REQ-05, REQ-06 | 4 | review-record checks in records profile; audit report deferred |
| AC-06 | Storage failure | REQ-08 | 4 | integration tests only (cannot be triggered through the API) |
| AC-07 | Record persistence and corrections | REQ-09 | 4 | correction-link checks in records profile; full persistence acceptance deferred |
| AC-08 | Test reset | REQ-10 | 3 | scenario 2, 25, 26, 29–31 |
| AC-09 | Security | REQ-11, REQ-12 | 3 (authentication) | scenario 1, 23–25; authentication checks |
| AC-10 | Capacity and performance | REQ-13 | 5 | not yet |
| AC-11 | Cross-team conformance | REQ-14 | 3 (basic) | every check validates responses against the contract |

## 5. Coverage counting rules

Tester reports count coverage as follows:

- **Component coverage:** the 5 operations in Section 1. An operation is covered
  when at least one executed test calls it. Total = 5.
- **System coverage:** the 11 acceptance criteria in Section 4. A criterion is
  covered when at least one of its mapped checks is executed. Total = 11.
- **Code coverage:** copied from the target's system `/test/report`; `null`
  counts with an explanatory `basis` when the target does not measure it.

Covered means exercised, not passed; pass and fail are reported in `results`.

## 6. Known differences between the two implementations

As of 2026-10-27, Team 103's published contract
(`http://3.134.49.218:8000/openapi.json`) differs from Phase 2 v1.1 in these
observable ways:

| Topic | Phase 2 v1.1 / Team 106 | Team 103 |
| --- | --- | --- |
| Base path | `/api/v1/...` | none (`/events`, `/interactions/{interaction_id}`) |
| Event fields | `eventId`, `interactionId`, `eventType`, `occurredAt`, `modelVersion` (required), `applicationVersion`, `data` | `event_id`, `interaction_id`, `event_type`, `timestamp`, `model_version` (optional), `application_version`, `actor_id`, `payload` |
| Event types | `interaction.started`, `model.output_generated`, `review.completed`, `interaction.completed`, `interaction.stopped`, `record.corrected` | `interaction_started`, `user_input`, `ai_output`, `human_review`, `final_decision`, `interaction_ended` |
| Interaction status | `in_progress`, `completed`, `stopped` | `open`, `complete` |
| Authentication | bearer token on events, interactions and reset | bearer token on test operations only |
| Reset success | 200 with counts | 204, no body |
| Health body | `{status, api, storage}` | `{status: "ok"}` |
| Body limit | 65,536 bytes per request | 32 KB per event, 1 MB per request |
| Additional operations | none | `POST /events/batch`; audit report implemented |
| Acceptance criteria counted | AC-01 to AC-11 (Phase 2) | AC-01 to AC-15 |
| Components counted | 5 operations | 7 routes |

**Effect.** Once each tester holds the other team's credentials and approves its
URL, the testers can run against each other's systems, but most checks are
expected to fail on paths, field names and status values. As of 2026-10-27 the
cross-team runs are blocked on that access setup (401 from Team 103's system
setup; Team 103's tester has not yet approved Team 106's URL).

**Resolution plan.** For Phase 3, both teams record these differences and run the
cross-team check for well-formed reports, which is the Phase 3 goal. Early in
Phase 4 the pod agrees on one API, one acceptance-criteria list and one component
list, with instructor sign-off for any change to the Phase 2 shared scope, and
both implementations and testers are aligned to it.
