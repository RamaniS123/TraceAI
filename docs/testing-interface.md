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
  status, message and source.
- `POST /test/run` with `{"session_id": ...}` runs the same 42 checks as
  `tools/run_phase3_api_tests.py` (the shared 31-step scenario, authentication
  checks, 64 KiB boundaries and a final cleanup reset), in order, then reads the
  target's `/test/report` and returns one suite report. Each session runs once;
  later runs return 409. Every check is executed and reported: `fail` when the
  response differs from the contract, `error` with `source: system` for an
  unexpected 5xx, `error` with `source: communication` for timeouts.
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
python tools/check_testing_interface.py --tester https://traceai-zm1t.onrender.com/tester --target https://traceai-zm1t.onrender.com
```

This needs no credentials. It prints the outcome counts, coverage and any
non-passing tests, and exits 1 if a response is not in the required format.
CI runs the same check against a local server with `--require-pass`.

## Registry entry

- System base URL: `https://traceai-zm1t.onrender.com`
- Tester base URL: `https://traceai-zm1t.onrender.com/tester`
- Access / run notes: Tester needs no credentials and holds its own access to our
  system. System `/test/setup` and the project API need bearer tokens (reset token
  for setup); request them privately from Team 106. Run one session at a time;
  setup resets the test dataset. Max times: tester setup 120 s (includes a
  free-tier cold start), tester run 300 s, system setup 90 s.
