# Phase 3 contract and decisions

Historical Phase 3 notes. Phase 4 chunk 1 supersedes the empty-warning assumption;
see [the implemented warning profile](phase-4-timeline.md). Other unresolved pod
decisions remain provisional.

Source: Phase 2 submission, agreed specification v1.1 dated September 22, 2026,
Sections 5.1–5.3 and 6.1. `contracts/openapi.json` is the proposed machine-readable
Phase 3 profile; `contracts/event.schema.json` is its standalone JSON Schema
(Draft 2020-12). These files have not yet been approved by the other team.
The earlier project-context summary is secondary where its field or event names differ.

## Scope

Implement submission, retrieval, isolated test reset, and public health.
Use occurredAt, not timestamp, and the six dotted event types from Section 5.2.
All six types can be validated and stored now; audit reports, warning detection,
and correction application are Phase 4. No report endpoint is promised in this
Phase 3 profile. Review/correction records remain ordinary immutable events.
Database uniqueness and transactional writes support basic duplicate/conflict handling.

## Provisional decisions for pod review

- Return events sorted by timestamp instant, then eventId in case-sensitive
  Unicode code-point order. Status is in_progress until a terminal event exists;
  the last terminal event in that ordering sets completed or stopped.
- Return warnings as an empty array in Phase 3, even for incomplete interactions.
  This is an explicit milestone limitation, not a claim that integrity checks passed.
- API and reset tokens are distinct opaque environment secrets. The reset token
  authorizes every protected operation; the ordinary token cannot reset. Missing
  or invalid tokens yield 401; a valid ordinary token on reset yields 403.
  Health requires no authentication. Never put tokens in fixture files or logs.
- Accept uppercase T and Z RFC 3339 timestamps with seconds and optional fractions;
  also accept +00:00. Reject nonzero offsets and invalid calendar dates. Preserve
  the submitted timestamp text in responses; normalize only for ordering and
  duplicate comparison. Leap seconds are outside this prototype's timestamp profile.
- Duplicate equality compares every event field as parsed JSON, with timestamp
  instants normalized. Object key order and whitespace are immaterial; array order
  matters. JSON numbers compare by numeric value; booleans remain distinct from
  numbers. A change to any other field, including data, causes 409.
- Reject unknown top-level fields. Allow additional keys inside data. A correction
  uses data.reason (1–500 characters) and data.correctsEventId (1–64 characters).
  Enforcing target existence and correction semantics is deferred to Phase 4.
  Reviewer ID is a string as specified in the PDF; no extra length rule is imposed.
- The size limit is 65,536 raw UTF-8 request-body bytes, inclusive. Check before
  JSON parsing; do not rely solely on Content-Length. Compression is outside the
  prototype profile. JSON requests use application/json. Other media types use
  422 INVALID_EVENT rather than an undocumented 415 in this proposed profile.
- Event validation errors use 422 INVALID_EVENT; malformed JSON uses 400
  MALFORMED_JSON; oversize uses 413 REQUEST_TOO_LARGE; conflicts use 409
  EVENT_CONFLICT; unknown interactions use 404 INTERACTION_NOT_FOUND.
  Authentication uses 401 UNAUTHORIZED and 403 FORBIDDEN. Storage errors use
  503 STORAGE_UNAVAILABLE. Reset validation uses 400 INVALID_RESET.
  All use ErrorResponse. Messages and optional details are safe human-readable
  text, not exact strings required for conformance.
- Authenticate protected requests before processing their content. Reset requires
  exactly {"confirm": true}; missing, false, wrong-type, or extra fields yield 400.
  Reset clears only the isolated test dataset atomically and is idempotent.
- Health returns API available when it can answer, with healthy/available storage
  and 200, or unhealthy/unavailable storage and 503. Health 503 uses HealthResponse,
  resolving the generic error-envelope wording in favor of the health schema.
- PostgreSQL provides persistence from the start; full restart/failure simulation
  remains Phase 4. Capacity targets are not implemented as hard rejection limits.

These decisions permit local implementation. Both teams must review observable
choices before treating this profile as their common cross-team specification.

## Fixture use

All data is synthetic. `tests/fixtures/phase-3-scenario.json` is an ordered
scenario: start with healthy empty storage, submit interleaved interactions and
out-of-order timestamps, check exact responses, rejection paths, no unintended
writes, and repeated reset. `auth` is a symbolic selector (api/reset/none/invalid),
never a token. A future HTTP runner must inject credentials securely and must run
only against an explicitly selected isolated test service.

`valid-events.json` includes review and correction shape examples.
`invalid-events.json` pairs each invalid body with expected status 422.
`malformed.json.txt` is deliberately invalid JSON.
`event-65536-bytes.json` must return 201 after reset; the 65,537-byte body must
return 413 and leave int-size absent after a separate reset. Do not pretty-print
or append newlines to these byte fixtures. Validate this behavior in the later
HTTP runner; schema validation alone cannot enforce body size or persistence.

Run `python tools/validate_contract.py` with jsonschema and
openapi-spec-validator installed. This checks contract structure, schema parity,
valid/invalid fixtures, expected response shapes, and byte boundaries. It does
not start an application or establish that HTTP behavior works. The actual API,
database, HTTP tests, CI and deployment belong to subsequent chunks.

## Chunk 3 implementation notes

The four operations are implemented; the authored contract is unchanged. A bundled
copy at `src/traceai/openapi.json` is included in distributions so `/docs` and
`/openapi.json` expose the authored contract outside the source checkout.
`tools/validate_contract.py` enforces exact parity between the two copies.

Additional local operational choices:

- `TRACEAI_TEST_RESET_ENABLED` defaults to false. A valid reset token receives 403
  unless this flag is true. Enable it only for an explicitly isolated classroom or
  development dataset. This adds an opt-in guard without changing the HTTP schema.
- Missing token configuration fails closed: health remains available, but no
  protected request is authorized by an absent or empty credential. Configured
  tokens must be nonempty and distinct. Full deployment configuration is still
  required before public use.
- Repeated JSON object keys, non-finite numbers, invalid UTF-8, and malformed JSON
  receive 400 MALFORMED_JSON. Media types other than application/json and compressed
  event bodies receive 422 INVALID_EVENT. Invalid or oversized reset content uses
  400, consistent with reset's documented statuses.
- JSON numbers are parsed and stored without conversion through binary floats.
  Duplicate comparison distinguishes booleans from numbers and compares object
  contents independently of key order. Sub-microsecond timestamps use original
  text for exact ordering and equality, while PostgreSQL also stores an indexed
  microsecond-resolution timestamp.
- PostgreSQL JSONB cannot represent every syntactically valid JSON value (notably
  escaped U+0000 and numbers outside PostgreSQL numeric limits). Storage-level
  invalid data receives 422 without a partial write. This is a known prototype
  limitation for pod review; the shared event schema has not been narrowed.

Later-phase warning generation, report generation, linked-correction processing,
full security analysis, and capacity/performance validation remain unimplemented.
