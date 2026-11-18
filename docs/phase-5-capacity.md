# Phase 5 chunk 3: capacity loading and verification

## Recorded result — November 18, 2026

Local capacity passed at source revision `62b0ff9b87a9aaeb21781fdb5faa035d5e2a8c24`.
The [committed results](phase-5-capacity-results.json) record the evidence hashes;
the [seed manifest](phase-5-capacity-manifest.json) can be regenerated from its run ID.

| Observation | Result |
|---|---|
| Starting global event count | 0 |
| New HTTP 201 acknowledgements | 10,000 |
| PostgreSQL inventory | 100 interactions, exactly 100 events each |
| Initial full history and audit verification | 100/100 interactions; all 10,000 events match |
| Verification after application restart | 100/100 interactions; all 10,000 events still match |
| Lost, changed or unexpected records | 0 |
| Repeat seed against nonempty DB | Blocked; all 10,000 records retained |
| Regression before loading | 230 tests passed; 0 skipped |
| Contract/schema/fixture/plan validation | Passed |
| Public or peer writes/resets | None |
| Performance acceptance | Not measured |

The database is local PostgreSQL 16.15 with 128MB shared buffers and 100 maximum
connections. The application used Python 3.12.14, one Uvicorn worker, the default
SQLAlchemy pool of five with ten overflow connections, and one sequential loader
client. The Compose database has persistent storage and no configured CPU/memory
limits; these resources do not represent the Render free tier. Individual
synthetic event request bodies are between 285 and 387 bytes, depending on event
kind; exact byte totals are recorded in the results summary.

## What this checks

REQ-13 / AC-10 require at least 10,000 stored events and at least 100 events in
one interaction. The fixed capacity dataset exercises **100 interactions with
100 events each**, totaling 10,000 records. Each interaction contains one start,
96 model-output references, one human-review record, one correction linked to that
review, and one completion. IDs have a unique run prefix; timestamps are fixed,
increasing UTC values. All content is synthetic.

The [capacity profile](../contracts/phase-5-capacity-profile.json) describes the
workload separately from performance measurement. The capacity tool makes 10,000
sequential authenticated HTTP submissions through the normal application API;
it does not insert directly into storage, reset any dataset, or retry requests.
Every new-record receipt must be HTTP 201 with the expected IDs, `stored: true`
and `duplicate: false`. A duplicate receipt is not counted as new capacity.

The independently generated oracle then retrieves both history and audit report
for every interaction (200 GETs per verification). It validates the common
OpenAPI response schema and compares every response field with the expected
snapshot: all original event values and IDs, ordering, completed status, the
single correction warning, version inventories, review details, correction link
and `linkValid`, report metadata and disclaimer. Missing, modified, duplicated or
unexpected records fail verification. No production timeline or report helper is
imported by the oracle.

The orchestrator independently checks PostgreSQL's global row count and per-
interaction counts, stops the application, starts a new process using the same
persistent database, repeats the 200 retrievals, and checks the database inventory
again. Restarting the application does not restart or replace PostgreSQL.

## Isolation and evidence

[`tools/check_phase5_capacity.py`](../tools/check_phase5_capacity.py) requires an
explicit, matching pair of `TRACEAI_DATABASE_URL` and `TRACEAI_TEST_DATABASE_URL`,
a local PostgreSQL host, a database name ending in `_test`, the correct migration,
an empty starting database and `--allow-isolated-load`. It reads no default `.env`
file for this decision and refuses to clear an existing dataset. The application
runs only on loopback with temporary API/reset credentials and reset disabled.

[`tools/phase5_capacity.py`](../tools/phase5_capacity.py) can also seed or verify a
separately started local application. It refuses remote URLs, embedded credentials,
queries, path prefixes and implicit ports; redirects are disabled. Loading requires
explicit isolation confirmation. A loopback address alone cannot prove database
isolation, so the orchestrator's explicit DB checks and a separate benchmark
configuration are important. Do not run another resetting suite against that DB.

Evidence includes a deterministic manifest, canonical seed-content SHA-256,
per-interaction expected history/report hashes, all accepted receipt lines,
observed response hashes, inventories before/after restart, code revision,
profile/contract/generator hashes, runtime configuration and explicit capacity/
performance verdicts. Raw evidence lives under ignored `reports/`; the committed
results summary links its paths and hashes. Generator, dataset or contract changes
invalidate the manifest. Timing-only profile updates can retain the same seed;
both the original profile hash and current profile hash remain in the evidence.

## Repeat or verify

The dedicated private `.env.phase5` created in chunk 1 remains outside version
control. To run on a **new empty** benchmark database after the regression suite,
start its Compose service as documented in [the plan](phase-5-plan.md), then:

```sh
.venv/bin/python - <<'PY'
import os, subprocess
from dotenv import dotenv_values
values = {k: v for k, v in dotenv_values('.env.phase5').items() if v is not None}
subprocess.run([
    '.venv/bin/python', 'tools/check_phase5_capacity.py', '--allow-isolated-load',
    '--manifest', 'reports/phase5-capacity-manifest.json',
    '--report', 'reports/phase5-capacity.json',
], env={**os.environ, **values}, check=True)
PY
```

A second seed against the retained dataset is blocked; a new ID prefix does not
make it isolated. To verify the retained chunk 3 dataset without writes, start a
local app using the existing benchmark settings in one terminal:

```sh
.venv/bin/python -m uvicorn traceai.main:create_app --factory \
  --env-file .env.phase5 --host 127.0.0.1 --port 8015
```

In another terminal, use the same private configuration for the verifier:

```sh
.venv/bin/python - <<'PY'
import os, subprocess
from dotenv import dotenv_values
values = {k: v for k, v in dotenv_values('.env.phase5').items() if v is not None}
subprocess.run([
    '.venv/bin/python', 'tools/phase5_capacity.py', 'verify',
    '--base-url', 'http://127.0.0.1:8015',
    '--manifest', 'reports/phase5-chunk3-manifest.json',
    '--report', 'reports/phase5-chunk3-reverification.json',
], env={**os.environ, **values}, check=True)
PY
```

Keep the database and manifest for chunk 4. Full integration tests and functional
reset suites must run on a different database while these capacity records are
retained. The manifest's random IDs are identifiers, not credentials.

## Limits of the result

This is a controlled local capacity result for small synthetic reference payloads,
not a supported maximum capacity, a hosted Render capacity result, a peer capacity
result, or proof for all payload sizes. Sequential ingestion does not measure ten-
client behavior. Chunk 3 performed no 1,000-request benchmark or validated
application timing. The subsequent [chunk 4 run](phase-5-performance.md) passed
the local numerical performance targets; hosted/peer validation and pod agreement
on workload/timing remain pending before comparative load testing. No public or
peer load/reset is part of either local chunk.
