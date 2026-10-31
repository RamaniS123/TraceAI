# Course testing interface

TraceAI exposes the course's cross-team testing interface from the same Render
service as the project API:

| Service | Base URL | Endpoints |
| --- | --- | --- |
| System | `https://traceai-zm1t.onrender.com` | `POST /test/setup`, `GET /test/report`, plus the pod project API (`/api/v1/...`, `/health`) |
| Tester | `https://traceai-zm1t.onrender.com/tester` | `POST /test/setup`, `POST /test/run`, `GET /test/report` |

Both are implemented in `src/traceai/testing_interface.py` and described in
[testing-interface.openapi.yaml](testing-interface.openapi.yaml). Tester and
system test endpoints return errors as `{"message": ..., "source": ...}`; the
project API keeps the pod's `ErrorResponse` format.

## System

- `POST /test/setup` with `{"session_id": "...", "setup": {}}` requires the
  **reset bearer token**, resets the isolated test dataset (the pod's reset
  operation) and returns `201 {"session_id": ...}`. A reused ID returns 409; an
  unavailable database returns `500 {"source": "system"}`; reset disabled by
  configuration returns 403.
- `GET /test/report?session_id=...` needs no token and returns code coverage.
  Line instrumentation is not enabled in the deployed service, so `covered` and
  `total` are `null` with an explanatory `basis`.
- Project requests do not carry a session ID. Every session starts from the empty
  dataset, so run one session at a time: a new setup clears the previous session's
  data. Session IDs are held in memory and are lost when the free-tier service restarts.

## Tester

- `POST /test/setup` with `{"target_url": "<system base URL>"}` creates a UUID
  session, calls the target's `/test/setup`, and returns `201` only after the
  target confirms the same ID. Target errors are returned with the target's
  status and recognized source, with a fixed safe message.
- `POST /test/run` with `{"session_id": ...}` runs the selected evaluator profile
  in order, reads the target's `/test/report`, and returns a suite report. The
  code default is 42 checks; the Render blueprint selects the 126-check Phase 4
  profile. Each session runs once; later runs return 409. Every planned check is
  accounted for: `fail` for contract differences, `error` with `source: system`
  for unexpected 5xx, and `error` with `source: communication` for timeouts.
  An overall-budget abort preserves partial results and accounts for remaining
  checks without marking them passed.
- `GET /test/report?session_id=...` returns the stored report, or 409 before the
  suite ends. Reports are kept in memory until the service restarts.
- Coverage: `component` counts the five operations of the pod interface (Phase 2
  Section 5.1) exercised by an executed test; `system` counts acceptance criteria
  AC-01 to AC-11 (from `docs/requirements.json`) exercised by an executed test;
  `code` is copied from the target's system report.

## Credentials

The tester sends bearer tokens only to origins it holds tokens for. For this
deployment it uses its own tokens when the target origin matches
`TRACEAI_PUBLIC_URL` (or Render's `RENDER_EXTERNAL_URL`). To test another team's
protected system, set `TRACEAI_TESTER_TARGET_TOKENS` in Render to
`{"https://their-host": {"api": "...", "reset": "..."}}`. Never put tokens in URLs,
the registry, or the repository.

## Check it like the graders do

```sh
python tools/check_testing_interface.py --tester https://traceai-zm1t.onrender.com/tester --target https://traceai-zm1t.onrender.com --allow-test-reset
```

This needs no credentials. It prints the outcome counts, coverage and any
non-passing tests, and exits 1 if a response is not in the required format.
This suite resets synthetic target data. Use `--preflight` instead of
`--allow-test-reset` for read-only readiness. CI runs the suite against a local
server with `--require-pass`. See [delivery instructions](phase-4-delivery.md)
for private JSON artifacts, blocked/partial-run handling and both cross-team directions.

## Registry entry

- System base URL: `https://traceai-zm1t.onrender.com`
- Tester base URL: `https://traceai-zm1t.onrender.com/tester`
- Access / run notes: Tester needs no credentials and holds its own access to our
  system. System `/test/setup` and the project API need bearer tokens (reset token
  for setup); request them privately from Team 106. Run one session at a time;
  setup resets the test dataset. Max times: tester setup 120 s (includes a
  free-tier cold start), tester run 300 s, system setup 90 s.


## Optional Phase 4 timeline profile

The HTTP setup/run/report formats above are unchanged. The code default remains
42 checks; the Phase 4 Render blueprint selects 126. `TRACEAI_TEST_TIMELINE_ENABLED=true` selects 68 checks, adding the
warning and late-arrival scenario; the CLI selects it with `--phase4-timeline`.
AC-03 is then counted as exercised, with rule-alignment limitations documented in
[phase-4-timeline.md](phase-4-timeline.md). Reports still distinguish pass/fail/error/skip.


## Phase 4 review and correction profile

`--phase4-records` runs the 99-check profile (42 baseline + 26 timeline + 31
review/correction checks). The hosted tester selects it with
`TRACEAI_TEST_RECORDS_ENABLED=true`. Default 42-check behavior and HTTP control
formats are unchanged. See [record-link rules and evidence](phase-4-records.md).
Review/audit and persistence/correction criteria are only partially exercised;
this profile is not a claim that audit reporting or all Phase 4 work is complete.

## Phase 4 audit-report profile

See [phase-4-reports.md](phase-4-reports.md) for the optional 126-check
`--phase4-reports` profile (including earlier timeline/record checks). Set
`TRACEAI_TEST_REPORTS_ENABLED=true` on the web service to select it for hosted
tester runs. The code default remains 42 checks; the Phase 4 Render blueprint enables this profile; registry base URLs and HTTP request
fields stay unchanged. Test runs reset the authorized synthetic target data.

## Active tester and release metadata

`GET /tester` (also `/tester/`) describes the active profile and planned check
count without creating a session or resetting records. It now provides a useful
response when a person opens the registered tester base URL. The Render blueprint
sets `TRACEAI_TEST_REPORTS_ENABLED=true` for the 126-check Phase 4 suite; `/tester`
confirms whether that environment setting is actually active after Blueprint sync.

Hosted checks have a 240-second overall budget, with individual requests bounded
by the remaining budget (at most 30 seconds). The final code-coverage lookup can
add at most 30 seconds. A budget abort returns 500 with a stored partial report;
remaining checks are accounted for as errors/skips, not successes. Cleanup may be
unrun after an abort; a subsequent authorized setup resets the target dataset.

`GET /health` identifies the project contract in `X-TraceAI-Contract`; Render's
Git SHA is included in `X-TraceAI-Revision` when available and valid. No secret
configuration values are exposed.
