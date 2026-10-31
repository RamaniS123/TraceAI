# Phase 4 chunk 2 — correction links and human-review records

## Delivered behavior and contract status

OpenAPI implementation profile **0.3.0** adds correction-link validation and
stronger human-review validation to chunk 1's timelines. These are provisional
Team 106 decisions pending reconciliation with Team 103, not a newly ratified
shared contract. The existing endpoints, authentication, receipt fields,
duplicate behavior, and event vocabulary remain in place.

## Human review

A `review.completed` event must include:

- `data.reviewerId`: a nonblank string, 1–64 characters.
- `data.action`: `accept`, `override`, `reject`, or `escalate`.
- `data.reason`: a nonblank string, 1–500 characters.
- The ordinary required event timestamp (`occurredAt`), model/application versions,
  event ID and interaction ID. No separate review timestamp is invented.

Reviewers are recorded identifiers, not authenticated individual accounts. The
bearer token authorizes submission; TraceAI does not verify the identity or
correctness of a reviewer. Review remains optional and does not gate completion.

Nonblank checks reject whitespace-only input but do not trim or normalize accepted
strings. Retrieval preserves the exact reviewer/action/reason and original UTC
timestamp text, including fractions beyond database microsecond precision.
These stronger checks apply to new submissions, not a rewrite of stored history.
A formerly accepted review that fails the new shape rules cannot be replayed as
valid input, but its existing record remains retrievable. The response uses a
`StoredEvent` schema that retains historical acceptance rules, while the submission
schema `EventInput` enforces the new constraints. This avoids invalidating the
response schema for immutable legacy records.

## Corrections

`record.corrected` requires `data.correctsEventId` (the existing event-ID domain,
1–64 characters) and a nonblank `data.reason` of 1–500 characters. The target must
already be accepted in the same interaction. Self-links, missing targets,
cross-interaction targets, and cycles or broken ancestry in correction chains
receive **422 INVALID_CORRECTION** with the same safe message. Shape errors use
the existing **422 INVALID_EVENT** response.

Validation and insertion share one transaction. Referenced rows are held with
PostgreSQL key-share locks, so reset cannot break links before commit. Failure
rolls back the new correction completely; clients may retry its ID after the
missing target has been accepted. Conflicting reuse of an existing event ID
still returns 409, and an identical retry still returns 200 without another copy.
Existing identical corrections are not revalidated on retry.

Multiple corrections and correction-of-correction chains are permitted. Each
new link must lead through an existing, same-interaction, acyclic history to a
non-correction event. IDs, payloads, timestamps, and receipt times of all previous
records remain unchanged. There is no last-writer-wins replacement, update, or
silent deletion. The authorized test reset remains the explicit deletion exception.

A correction's event timestamp may precede its target (for example, a clock
error is being explained); acceptance of the target, not its timestamp, establishes
whether it exists. Normal timeline ordering and lifecycle warnings are unchanged.
Corrections do not automatically rewrite payloads, timestamps, status, or warnings
of original events. Audit presentation of both records is chunk 3.

## Retrieval annotations and legacy data

Structurally valid correction links add this annotation to the existing warnings
array, in the correction event's timeline position before missing-event warnings:

```json
{
  "code": "CORRECTED_EVENT",
  "message": "A linked correction is recorded; the original event is retained.",
  "eventId": "correction-1",
  "eventType": "record.corrected",
  "correctsEventId": "original-1"
}
```

This annotation records the link; it is not proof that a replacement was applied.
No stored records are removed from the returned history. Historical dangling,
cross-interaction, self-referential, and cyclic corrections remain visible but
are not labelled as valid correction links. A new correction cannot extend one
of those invalid histories. No database migration or automatic cleanup is required.

## Tests and evaluator profiles

The new fixed `phase-4-records-scenario.json` contains **31** HTTP steps covering
reviews, rejection paths, immutable originals, duplicate/conflict behavior,
correction chains, and coexistence with late-event warning analysis.

- Default CLI/hosted profile: **42 checks**, unchanged.
- `--phase4-timeline`: **68 checks**, unchanged.
- `--phase4-records`: **99 checks**, including the prior timeline profile.
- Hosted `TRACEAI_TEST_RECORDS_ENABLED=true` selects the same 99-check profile;
  no setup/run/report request fields or registry URLs change.

The profile covers the review-record portion of AC-05 and correction-link portion
of AC-07. It does not complete either criterion: audit reporting, full restart
acceptance, and broader reliability/security work remain later chunks. Coverage
counts exercised scope, not full requirement completion. The extended profile
exercises 9/11 criteria; source coverage remains unmeasured.

With credentials securely configured for an isolated migrated test dataset:

```sh
.venv/bin/python tools/run_phase3_api_tests.py \
  --base-url http://127.0.0.1:8000 --allow-test-reset \
  --phase4-records --report reports/records-api.json
.venv/bin/python tools/phase_status.py reports/records-api.json
```

CI runs the new profile alongside earlier regression profiles. Integration tests
also compare original database rows before/after corrections, reject unsafe links
without partial storage, exercise concurrent retries, and preserve exact review
fields. Pure tests cover cyclic/dangling historical graphs and iterative long-chain
validation. Validation uses local PostgreSQL, actual Uvicorn HTTP, and the built
Docker image; public/cross-team runs are separate evidence.

The frontend already shows correction payloads as ordinary event details, but
warning presentation and audit reports remain later chunks. Do not interpret
this increment as finished Phase 4 or established cross-team compatibility.
