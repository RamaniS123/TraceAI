# Phase 5 chunk 4: application timing and local performance result

## Recorded result — November 18, 2026

The isolated local run passed the planned numerical REQ-13 / AC-10 targets at
source revision `0e84aed8d6a0649285f23c071d801cf0406c113e`, using profile 1.2.0.
The timed portion began at **4:08:09 PM EST** and ended at **4:08:19 PM EST**.
See the [results summary](phase-5-performance-results.json) and
[all 1,000 request measurements](evidence/phase5-performance-requests.jsonl).

| Acceptance observation | Result |
|---|---|
| Stored dataset | 10,000 events; 100 interactions of 100 events |
| Measured requests | 1,000: 500 history GETs and 500 audit-report GETs |
| Worker limit / observed maximum in-flight HTTP requests | 10 / 10 |
| Correct HTTP 200 responses matching the manifest | 1,000/1,000 |
| Valid application measurements | 1,000/1,000 |
| Correct responses at most 1 second | 1,000/1,000 (required: at least 950) |
| Application durations over 1 second | 0 |
| Missing/invalid timing or unexpected responses | 0 |
| Full-record integrity before and after | Passed; all 10,000 original records unchanged |
| Regression on separate database | 262 passed, 0 skipped |
| Local hosted-tester functional regression | 126/126 passed |

| Duration series | Median | 95th percentile | 99th percentile | Maximum |
|---|---:|---:|---:|---:|
| Application response-ready | 6.53 ms | 20.51 ms | 35.92 ms | 68.63 ms |
| Client end-to-end | 85.22 ms | 153.92 ms | 196.74 ms | 258.57 ms |

Percentiles use nearest rank; exact values in seconds remain in the results.
The two series measure different boundaries. Their difference is not a measured
network delay and is never subtracted to produce the acceptance metric.

## Timing boundary

[`ApplicationTiming`](../src/traceai/timing.py) is a pure ASGI middleware outside
the safe error boundary. It records `perf_counter_ns()` at HTTP application entry
and immediately before response-start. It adds:

```http
Server-Timing: traceai_app;dur=20.513153
```

The `dur` value is in **milliseconds**. Integer formatting preserves nanosecond
precision without rounding a duration just above one second onto the threshold.
The metric includes authentication, routing/threadpool waits, database-pool waits,
PostgreSQL I/O, timeline/report assembly and JSON serialization. The measured
history and report routes build buffered bodies before starting the response.

It excludes network/TLS, edge or Uvicorn queuing before ASGI entry, sending the
response headers/body, and client-side validation. It is response-ready timing,
not a streaming-response completion metric. Other streamed/static routes must not
be evaluated as if their bodies completed at response-start. The application
contract remains 0.4.2: project operations and JSON schemas are unchanged; the
additional diagnostic response header does not change response bodies.

Client end-to-end time uses a separate monotonic interval around each buffered
HTTP request and includes receiving the full body. Schema/content validation
happens afterward. It can include client scheduling, connection-pool and network
costs that the application timer excludes. No guessed RTT is removed.

## Workload, correctness and verdict

[`tools/phase5_benchmark.py`](../tools/phase5_benchmark.py) builds a fixed queue:
five rounds, each retrieving history and audit report for all 100 interactions.
Ten worker threads and an HTTP connection limit of ten bound concurrency; an
instrumented counter records the observed maximum while HTTP calls are active.
Each client validates its response before taking another job. Client validation
cost is part of workload pacing and wall time, not application or HTTP duration.

Every response must satisfy the common schema and the full canonical response
hash in the chunk 3 manifest. This compares all record fields and IDs, order,
status, warning, versions, metadata, human-review details and valid correction
links. A full 200-GET integrity verification runs before timing and again after it;
readiness and warmup observations are saved separately. Independent PostgreSQL
inventories before/after must also agree. The benchmark never seeds or resets.

All 1,000 scheduled requests stay in the denominator. There are no timed retries
or redirects. Missing/negative/nonfinite/ambiguous timing is invalid; a server
duration exceeding client elapsed time by more than 1 ms is also invalid rather
than silently corrected. At least 950 responses must be both correct and at most
one second, with all 1,000 measurements valid, all responses correct and integrity
intact. Otherwise the tool reports a failure or incomplete measurement. Errors
and timeouts remain visible, including when most other requests are fast.

Unit checks cover the exact 950/1000 boundary, one-nanosecond threshold crossing,
missing timing/requests, incorrect responses, lost records, excessive concurrency,
malformed metrics, sanitized communication errors and the response-ready boundary.
The real regression and HTTP functional suites ran sequentially against a new
local regression database; they did not touch the retained capacity records.

## Environment and limits

This was one recorded run on local PostgreSQL 16.15 and Python 3.12.14, with one
Uvicorn worker, SQLAlchemy pool size five and maximum overflow ten. The client,
application and PostgreSQL container share the machine (five CPUs reported).
The persistent Compose database has no configured CPU/memory limits; its prior
capacity evidence records 128MB shared buffers and 100 maximum connections.
Application reset was disabled, and no application response cache was added.
The complete pre-run record verification warmed the database/OS caches.

These measurements establish the numerical targets for this small synthetic,
warm local profile. They do not establish Render free-tier or peer performance,
cold-start latency, sustained maximum throughput or performance at larger payload
sizes. The proposed request mix and timing interpretation still need pod
confirmation before comparative runs. REQ-13 / AC-10 therefore retain a documented
hosted/shared-validation gap. No performance tuning was needed for this local run;
there was no repeat-until-pass selection or change to the acceptance threshold.

## Repeat without changing records

Use the private `.env.phase5` benchmark settings and retained chunk 3 dataset.
The tool requires explicit matching local `*_test` database URLs, the saved
manifest and `--allow-isolated-benchmark`; it refuses a different inventory and
never resets or loads replacement data.

```sh
.venv/bin/python - <<'PY'
import os, subprocess
from dotenv import dotenv_values
values = {k: v for k, v in dotenv_values('.env.phase5').items() if v is not None}
subprocess.run([
    '.venv/bin/python', 'tools/phase5_benchmark.py', '--allow-isolated-benchmark',
    '--manifest', 'docs/phase-5-capacity-manifest.json',
    '--report', 'reports/phase5-performance-repeat.json',
], env={**os.environ, **values}, check=True)
PY
```

Keep each result under a distinct report name. Full regression/reset suites use
`.env.phase5-regression`, not `.env.phase5`. Keep both private files out of Git.
To test hosted or peer resources, first arrange the separate database/exclusive
window and pod agreement described in [the plan](phase-5-plan.md). The local
runner intentionally has no remote-load override.
