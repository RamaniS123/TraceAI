# Phase 5 chunk 5: regression and cross-team validation

## November 22 follow-up

The [latest evidence](phase-5-cross-team-latest.json) now includes a new 126/126
forward suite against the peer-confirmed v0.5.0 system and a validated peer-supplied
130/130 reverse JSON report. The run below remains the historical November 21
record. Fresh reverse evidence is no longer missing. The independent workspace
system-report fetch is still blocked by HTTP 403, and no separate independent
audit export or hosted performance comparison was performed.

## Current result — November 21, 2026

Regression passed at source revision
`cb9542ed9f20bbb287f49073d91f39fe12012729`. The new forward suite against Team
103 also passed all 126 checks. **Fresh cross-team validation is incomplete:**
the workspace proxy blocks the independent peer system report and Team 103's
tester, so no new reverse run was requested. The November 1 reverse result is
historical and is not substituted for fresh Phase 5 evidence.

The [committed summary](phase-5-regression-results.json) records stage outcomes,
session IDs, timestamps, coverage bases, release metadata and evidence hashes.
No runtime code or contract change was needed to pass regression.

| Check | Fresh result |
|---|---|
| Full pytest suite, separate regression DB | 262 passed; 0 failed/errors/skipped |
| Dependency compatibility / migration schema / contract fixtures | Passed |
| HTTP foundation / timeline / records / reports profiles | 42/42; 68/68; 99/99; 126/126 |
| Hosted tester against local service | 126/126 |
| Recovery and safe-error/log groups | 5/5 |
| Headless desktop/mobile browser flows | Passed |
| Built deployment image against regression DB | 126/126; timing header present; non-root user `traceai` |
| Our deployed tester against our deployed service | 126/126; complete four-stage exchange |
| Our deployed tester against Team 103 | 126/126; tester setup/run/report successful |
| Independent workspace fetch of Team 103 system report | Blocked: proxy HTTP 403 `Domain forbidden` |
| Team 103 tester against our current service | Not run: tester blocked by the same proxy rule |
| Retained benchmark data | All 10,000 records and full report projections match the manifest |

## What regression covered

The full suite exercises validation, authentication/reset permissions, duplicates
and conflicts, precise timestamps/numbers, timeline warnings, review records,
correction links, deterministic audit reports, storage rollback/reconnect/timeouts,
safe failures/logs, target approval, timing boundaries and benchmark scoring.

Five independent local reliability groups also passed: safe client errors,
records surviving a new application process, unavailable storage never yielding
success, safe startup failure, and process-log canaries. Browser automation
covered actual submission/retrieval, duplicate notices, warnings/reviews/links,
precise downloaded JSON, safe text rendering, report errors/retry, disconnect
races and mobile layout. The packaged deployment image passed the full HTTP
profile against the separate regression database.

The restored workspace lacked a loopback entry in its proxy bypass configuration.
An initial local server probe therefore never reached the app. Local-only harnesses
used explicit `httpx.HTTPTransport(retries=0)` instances for their owned loopback
connections, including the local tester's injectable target transport. Proxy
environment variables were unchanged; external URLs retained the configured proxy.
This was a local test-harness transport adjustment, not a bypass of the peer-host
policy or a production application change. Playwright 1.62.1 ran headlessly with
the installed system Chromium. Docker used the managed socket and existing
proxy/CA BuildKit support; no runtime dependencies or lockfiles changed.

The database containers were stopped after environment restoration and restarted
with the existing dedicated Compose volume. The benchmark database still held
10,000 records. All resetting functional/recovery/browser/container suites used
`.env.phase5-regression`; the benchmark database was only read, with reset disabled.
Its complete history/report comparison passed again after the regression work.
These are integrity checks, not a new capacity/performance benchmark.

## Fresh deployed and cross-team evidence

Our service was healthy on project OpenAPI 0.4.2 at the revision above, with the
126-check `phase4-reports` tester profile and the application timing header.
The deployed self-test completed setup, run, tester report and system report with
126 passes, zero errors/failures/skips and final cleanup passing.
[The complete public suite report](evidence/phase5-regression-public-suite.json)
is committed. Coverage is five shared operations out of five and nine acceptance
criteria out of eleven exercised by that functional profile; own source-code
counts remain null with the instrumentation explanation. This is exercised
functional coverage, not proof that every acceptance criterion was validated.

The user confirmed Team 103's current service/tester URLs and a coordinated
reset-based functional window. Our hosted tester then tested
`http://3.134.49.218:8000` from **12:39:03 PM to 12:39:12 PM EST**:
126 passes, zero failures/errors/skips, including final cleanup. Run and stored
reports matched. [The full peer suite report](evidence/phase5-regression-team103-suite.json)
is committed. Its peer-reported source coverage is **506/767 statements**;
functional coverage is 5/5 operations and 9/11 mapped criteria.

The checker then independently requested the peer system report from this
workspace. The proxy returned 403 before the destination was reached. Therefore
the evidence envelope correctly records `status: incomplete`, `completed: false`
while retaining the 126 passing suite outcomes. The hosted tester had already
retrieved peer code counts, but this does not replace the checker's independent
system-report exchange. Do not rewrite the envelope as a completed exchange.

The same policy blocks read-only readiness of `http://3.134.49.218:8001`, so no
reverse setup or run was sent. Its check count is **unavailable**, not zero and
not 130. The 130/130 reverse result from November 1 remains in
[the historical baseline](phase-4-confirmed-results.json).

## Network blocker and concrete remaining work

The active workspace HTTP allowlist includes our Render host and package-manager
presets, but not `3.134.49.218`. The configuration API rejected the narrow proposed
addition with `draft_not_editable`; no network change was confirmed or applied.
The exact [transferable network proposal](cross-team-network-proposal.json)
preserves our host and existing unrelated settings and contains no credentials.
This belongs in **Codex workspace/environment network settings**, not Render.

If the client offers live environment editing, add the peer IP and apply the
change. If only reusable-environment setup is available, the owner must edit/save
and, when offered, publish that environment and resume with the updated access.
A saved draft alone does not grant live access. Confirm the observed policy and
use a fresh read-only connection before attempting the remaining steps.

1. Fetch the existing peer system report for session
   `adb4ad76-026c-46f8-9b9a-3802eb3b6709` and verify its session ID and coverage
   shape. This can complete the independent check without resetting Team 103 again.
2. In the still-agreed exclusive window, run Team 103's tester against our service
   and save a fresh well-formed report, all counts/coverage and our target revision.
   If access changes require a later window, reconfirm the timing with the peer.
3. Only after that evidence exists, record fresh equivalence in both directions.
   A fresh JSON report produced by Team 103 can provide reverse evidence if this
   workspace cannot reach its tester; validate its provenance and current target.

No peer performance load was authorized or attempted. Workload/timing agreement
and hosted/peer performance remain separate outstanding items. The November 18
[local numerical result](phase-5-performance.md) is unchanged. Chunk 6 can prepare
final documentation and demonstration, but cannot claim these blocked checks pass.
