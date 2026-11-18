# Phase 5 plan — chunk 1

## Baseline and scope

The Phase 2 submission is the authority for the hard REQ-13 / AC-10 targets:
PDF page 12 defines capacity/latency, pages 20–21 define the evaluation, and page 34
specifies hardening, threat/security review, regression, cross-team validation,
documentation and known limitations. This chunk establishes the plan; it does
not load 10,000 records, execute a benchmark, reset shared data or claim AC-10 passes.

The starting code revision is `e558c96010e76f12882607e9958a82087ed3c437`, project
contract 0.4.2. Read-only checks on November 18, 2026 confirmed healthy API/storage,
the same deployed revision and the 126-check `phase4-reports` hosted profile.
See [phase-5-baseline.json](phase-5-baseline.json) for exact observations.
The initial health call took about 26.29 seconds end-to-end; subsequent tester and
contract calls took about 0.37 and 0.11 seconds. These three lightweight readiness
calls do not measure audit/history performance or isolate network delay, and the
reason for the initial delay was not independently established.

Phase 4 functional results are now reconciled in
[phase-4-confirmed-results.json](phase-4-confirmed-results.json): our full deployed
suite passed 126/126; our tester against Team 103 passed 126/126; their uploaded
report against us passed 130/130, all on November 1. The peer report has 130 unique
case IDs, no failed/error/skipped results and the correct target URL. These results
establish the historical functional baseline, not capacity/performance acceptance.
Earlier per-chunk delivery notes describe the pre-alignment state at delivery.

## Required targets

| Item | Required value | Planned evidence |
|---|---|---|
| Stored events | At least 10,000 | Verified seed manifest and full retrieval audit |
| Events in one interaction | At least 100 | Every seeded interaction has exactly 100 |
| Measured ordinary requests | 1,000 | Every scheduled request retained in result denominator |
| Clients | No more than 10 | Ten workers; at most ten requests in flight |
| Processing time | At least 95% at most one second, excluding client network delay | At least 950 correct successful requests with valid application duration <= 1.0 s |
| Data integrity | No lost records; correct retrieved data | Exact expected IDs/content/order/reviews/corrections before and after load |

[The machine-readable profile](../contracts/phase-5-capacity-profile.json) captures
these fixed targets, the proposed workload and the acceptance/evidence rules.
Only the target numbers come directly from Phase 2. The mix, detailed fixture,
warmup and timing boundary below are explicit working assumptions to confirm
with the pod before comparative performance runs; they are not a scope reduction.

## Proposed reproducible fixture and requests

Load a dedicated empty benchmark database with 100 interactions, each containing
100 events: one start, 96 outputs, one review, one correction of that review, and
one completion. This produces 10,000 total events, valid original/correction links,
completed interactions and one correction notice per interaction. Assign increasing
fixed UTC times, deterministic content and unique run-prefixed IDs. Each ID stays
within 64 characters. Keep submitted payload sizes fixed and report those sizes.

For the timed workload, issue 500 history GETs and 500 report GETs, covering both
operations five times per interaction. Use a fixed queue with ten workers and no
think-time/retries that hide failed samples. This interpretation follows AC-10's
retrieval action. The measured set excludes loading, reset/setup, health and tester
control requests. Do not inflate the fast percentage with inexpensive health calls.

Before timing, complete declared unscored readiness and seed verification. Save
warmup/startup observations separately. Keep every request scheduled in the scored
1,000 in the denominator, including slow responses, timeouts and errors. Do not
silently remove bad samples. A run that does not account for all 1,000 is incomplete.

After the workload, verify all 10,000 events remain and compare every interaction's
original content/order/status and review/correction projections against the seed
manifest, outside the scored request count. Unexpected HTTP/schema/content errors
or record loss fail correctness regardless of latency. This makes the ordinary
latency test a correctness test too, rather than accepting fast error responses.

## Timing design: exclude external network honestly

The current 0.4.2 application has no per-request processing metric. This chunk
adds no timing instrumentation; chunk 4 must implement and verify it before a
network-excluded performance verdict is possible.

Planned primary metric: `Server-Timing: traceai_app;dur=<milliseconds>`, measured
with a monotonic clock from ASGI HTTP application entry until response-start,
after a buffered history/report response has been assembled and serialized.
Include routing/authentication, thread-pool scheduling, database-pool wait,
PostgreSQL access (including dependency I/O), warning/report work and serialization.
Exclude the client-service network hop, TLS handshake, edge waiting before ASGI
entry and response-body network transfer. This is specifically **application
response-ready duration**, not an infrastructure-wide queue/streaming metric.
Its adequacy as the shared interpretation must be confirmed with the pod.

Independently record client end-to-end duration for every timed request. Never
subtract a guessed ping/RTT or a constant "network allowance." Missing, invalid,
negative or mismatched server metrics produce **measurement incomplete**, not a
pass. A loopback HTTP run is useful supporting evidence but is not a substitute
for identifying the tested deployment/resources and timing boundary.

Report exact fast-success numerator/denominator, errors/timeouts, p50/p95/p99/max
and both timing series. Use nearest-rank percentiles; for 1,000 complete valid
samples p95 is the 950th sorted sample. Correctness, capacity and measurement
completeness are separate gates. A functional 126-check pass, a quick health
response, or a timer header alone cannot satisfy AC-10.

## Dataset isolation and execution gates

A dedicated local PostgreSQL 16 stack has been created with `compose.phase5.yaml`,
a unique Compose project/volume and a private ignored `.env.phase5` file. Its new
`*_test` database is migrated to `0001_events`, initially empty and healthy.
No shared/deployed database or existing local database was reset. Later runs use
this isolated database and a separate application process. Keep benchmark keys local
and ephemeral. A unique ID prefix prevents collisions but **does not isolate a
dataset from reset**: the current reset operation deletes the entire events table.
Existing 42/126-check functional scenarios reset their target. Run them before
capacity loading or against a different database; they are not safe warmup for a
loaded benchmark dataset. Do not run overlapping suites against one database; loading through a deployed
shared tester would also affect users of that dataset.

A deployed capacity run therefore needs a separate benchmark database/deployment
or an explicitly approved exclusive window, with records exported as appropriate
and a recovery/cleanup plan. Do not create paid Render resources or change the
shared production database merely to begin this phase. Coordinate the exact
profile and owner permission before loading a peer's service. The November 1
functional runs do not authorize a new load test.

Record the revision before/after, profile hash, actual resource plan, database
version, topology, pool/timeout settings, seed manifest, warmup observations and
all request outcomes. Preserve raw evidence privately, excluding credentials and
raw sensitive payloads from logs. Functional cross-team comparison should use
identical synthetic fixtures; compare target-reported timings only when both
implementations use the agreed boundary and disclose their resource differences.

### Local environment reuse

The private `.env.phase5` holds local-only connection settings and separate ephemeral
API/reset tokens; it is ignored by Git and has owner-only permissions. Preserve it
while reusing the database volume. Do not share or regenerate credentials over an
existing volume. Record non-secret setup status in `phase-5-baseline.json`.

```sh
docker compose --env-file .env.phase5 -f compose.phase5.yaml up -d --wait db
# Start a local benchmark app only when the next chunk needs it:
.venv/bin/python -m uvicorn traceai.main:create_app --factory \
  --env-file .env.phase5 --host 127.0.0.1 --port 8015
```

Use `stop` to pause that Compose stack while retaining its volume. Any destructive
volume cleanup must apply only to this explicitly identified benchmark project;
never use the normal deployed service's reset as a shortcut for isolation.

## Hosting and database status

The checked-in Blueprint requests one free Docker web service and separate free
PostgreSQL 16. Public health verifies current read/migration availability; it does
not expose the real database plan, billing/expiration or future write success.
The owner could not locate the expiration date, so it remains **unverified**.
Do not infer a specific expiry date from an old screenshot or assume free hosting
will last through grading. Confirm retention/expiry with Render's database owner
before relying on a long-term benchmark deployment; keep existing records intact.

## Remaining chunk sequence

1. **This chunk:** baseline, fixed targets, proposed workload/oracles, timing and isolation plan.
2. **Security:** threat model and review; remediate verified issues.
3. **Capacity:** implement repeatable loader/manifest and verify 10,000/100 capacity.
4. **Performance:** implement validated timing, run 1,000 requests with ten clients,
   investigate bottlenecks and save actual measurements.
5. **Regression/cross-team:** rerun functional/security cases after changes and
   repeat agreed comparative checks on both deployments, with coordinated load windows.
6. **Delivery:** updated models, threat/security review, measured results, operating
   documentation, limitations and final demo/report.

Chunk 1 is complete as a planning/baseline increment. AC-10 remains incomplete;
no performance or capacity acceptance is asserted.

## Chunk 1 validation

All 198 existing regression cases passed against the new isolated local database.
Contract/fixture and Phase 5 plan-invariant validation passed, as did dependency
compatibility. No new capacity or latency result is claimed. The database is still
empty after baseline regression cleanup, ready for the later controlled loader.

## Chunk 2 follow-up

Threat modeling, the verified tester target restriction and security regression
evidence are recorded in [the security review](phase-5-security-review.md).
Capacity and performance execution remain pending.

## Chunk 3 result

[Local capacity verification](phase-5-capacity.md) passed: 10,000 new HTTP events,
100 interactions of 100 events each, exact history/audit verification before and
after application restart, and no lost or changed records. The separately
migrated local benchmark database and manifest are retained for chunk 4. Full
regression/reset suites must now use a different database. This result supersedes
the chunk 1 empty-database observation; it is not a performance or hosted-capacity
verdict. REQ-13 / AC-10 remain incomplete pending the 1000-request performance run.
