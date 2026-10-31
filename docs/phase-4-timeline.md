# Phase 4 chunk 1 — timelines and warnings

## Status and scope

Historical chunk 1 profile: OpenAPI **0.2.0**. Chunk 2 advances the implemented
profile to **0.3.0**; see [correction and review rules](phase-4-records.md). The existing
camelCase fields, dotted event types, authentication, endpoints, submission
receipts, and interaction statuses are retained. `InteractionView.warnings` now
contains warning objects rather than being constrained to an empty array.

These lifecycle rules are **provisional Team 106 implementation decisions**.
Phase 2's model attachment and report Section 5 specify different vocabularies;
Team 103 also implements different types and warning codes. This increment does
not establish a jointly approved contract or cross-team compatibility. It uses
the current six event types and records the assumptions so they can be reconciled.

No migration or rewriting of accepted records is required. Analysis is performed
on each retrieval, so late events are automatically reflected on the next read.

## Ordering and status

- Return events by their exact UTC `occurredAt` instant, then case-sensitive
  `eventId` string order. This preserves fractions beyond PostgreSQL microseconds.
- HTTP arrival/receipt order does not cause warnings.
- Equal timestamps use event ID for display only, not to infer a sequence violation.
- Status remains `in_progress` until a terminal event exists; the last terminal
  event in sorted order determines `completed` or `stopped`. No warning-based
  status is added. Warning presence and status are independent.

## Missing-event rules

Do not emit missing-event warnings before finalization.

- Every finalized interaction needs `interaction.started`.
- If any `interaction.completed` event is recorded, `model.output_generated`
  is required. A late stopped event does not erase a previously recorded completion.
- `review.completed` is optional, but if present in a finalized interaction it
  also requires an output to review.
- A stopped interaction without a completion or review can legitimately end
  before an output is produced.
- Emit one `MISSING_EVENT` per absent required type, in start-then-output order.

Example: an interaction containing only a completion returns two missing-event
warnings. Adding a start and output with appropriate earlier timestamps removes
both warnings on the next retrieval. A newly supplied output timestamped after
completion resolves the missing warning but produces a sequence warning.

## Sequence rules

The lifecycle stages are: start → output → optional review → completed/stopped.
For each event, emit `OUT_OF_ORDER_EVENT` for each lower-stage type recorded at
a strictly later timestamp. This detects output before start, review before
output/start, and termination before later start/output/review records. One warning
per event/prerequisite-type pair is returned, even when that prerequisite type
appears multiple times. All detectable inversions are reported, not only the first.

Sequence checks also run on open interactions when the relevant events exist;
absence of a prerequisite is not reported until finalization. Warnings are ordered
by the affected event's timeline position, then prerequisite stage. Missing-event
warnings follow sequence warnings. Retrieval and repeated reads are deterministic.

## Warning shape

```json
{
  "code": "OUT_OF_ORDER_EVENT",
  "message": "model.output_generated occurred before interaction.started.",
  "eventId": "evt-output",
  "eventType": "model.output_generated"
}
```

Missing warnings name the absent `eventType` and omit `eventId`. Chunk 1 reserved `CORRECTED_EVENT`; chunk 2 now emits it for structurally valid
correction links. Corrections remain separate records without overwriting the
original lifecycle history. See [chunk 2](phase-4-records.md) for annotation details.

Conflicting finalizations, unexpected event-type multiplicity, automatic replacement
semantics, audit reports, and frontend warning rendering are not implemented by
this chunk. No legal-compliance determination is made.

## Validation and evaluator profiles

- `pytest -q` runs Phase 3 regression and Phase 4 tests; `pytest -m phase4` selects
  increment checks (database-dependent tests still need an isolated migrated DB).
- `tools/validate_contract.py` validates both source and packaged OpenAPI documents,
  event schemas, and both fixed scenario files.
- The default CLI/hosted tester remains the existing **42-check** profile.
- CLI `--phase4-timeline` adds the 26-step fixed timeline scenario, for **68 checks**
  including final cleanup. Like the default profile, it requires explicit reset
  consent and clears only the selected synthetic test dataset.
- Set `TRACEAI_TEST_TIMELINE_ENABLED=true` on the hosted tester to use that same
  extended profile. It defaults to false; no new public request fields are required.
- Phase-status and coverage mapping use the optional AC-03 profile checks only
  when they belong to the executed profile. Default coverage remains 6/11;
  executing the extended profile exercises AC-03 as well (7/11). These are
  exercised-scope counts, not measured source coverage or proof all Phase 4 is done.

From the repository root, with credentials supplied securely in environment:

```sh
.venv/bin/python tools/run_phase3_api_tests.py \
  --base-url http://127.0.0.1:8000 --allow-test-reset \
  --phase4-timeline --report reports/timeline-api.json
.venv/bin/python tools/phase_status.py reports/timeline-api.json
```

The increment was checked against an isolated PostgreSQL database and actual
Uvicorn HTTP, including the hosted setup/run/report flow. Public evaluation and
cross-team runs remain separate activities and must not be inferred from local
passing results. Full Phase 4 functionality is not complete.
