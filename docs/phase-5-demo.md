# Repeatable Phase 5 demonstration

Allow approximately 6–8 minutes. Use synthetic data and the regression/demo
service; retain the benchmark database separately. The script appends uniquely
named records and never resets or deletes a dataset. Browser instructions and
token handling are in [frontend.md](frontend.md).

## Prepare

Start the dedicated database if stopped, then start a demo API in one terminal:

```sh
.venv/bin/python -m uvicorn traceai.main:create_app --factory \
  --env-file .env.phase5-regression --host 127.0.0.1 --port 8016
```

In a second terminal, populate and verify the three demo interactions:

```sh
.venv/bin/python tools/run_phase5_demo.py \
  --base-url http://127.0.0.1:8016 --env-file .env.phase5-regression \
  --allow-synthetic-writes --report reports/classroom-demo.json
```

Do not export an unrelated API token into this terminal: process environment takes
precedence over the private credential file. The script prints three interaction
IDs and saves their audit JSON plus the optional late-event payload. Each run uses
new IDs, so rerunning requires no reset. The checked-in
[fixture](../demo/phase5-demo.json) defines the examples. Do not run regression
reset suites concurrently with the demonstration.

Open `http://127.0.0.1:8016/`, privately connect the API token from
`.env.phase5-regression`, and use the printed IDs with **Find events**.

## Walkthrough

| Time | Action | Expected observation / evidence |
|---|---|---|
| 0–1 min | Show health, interface and architecture | Connected PostgreSQL; five shared operations; no external AI model |
| 1–3 min | Find the `main` interaction; expand all events; load report | Five original events, completed status, one review, one valid correction, `CORRECTED_EVENT`; original review reason retained |
| 3–4 min | Download report JSON | Exact API snapshot; all events and annotations; disclaimer; no bearer token |
| 4–5 min | Find `late`; inspect warnings | Start and completion only; output missing; completed status can have warnings |
| 5–6 min | Submit the saved `late_event` through the form, preserving its earlier occurrence time; find `late` again | Three chronological events; missing-output warning removed without editing prior events |
| 6–7 min | Find `order` | Output occurred before start; deterministic order and `OUT_OF_ORDER_EVENT` |
| 7–8 min | Show evidence/limits and disconnect | 10,000/100 capacity, 1,000-request local measurements, 262-test regression, pending fresh reverse validation and hosted performance; disconnect clears token/display |

The saved late-event object is under `late_event` in `reports/classroom-demo.json`.
Copy its `eventId`, `interactionId`, type, timestamp, versions and `data` into the
form; do not copy report metadata into EventInput. Preserve the timestamp that
falls between the original start and completion. The fixture's past timestamps
are deliberate synthetic values, not the time the script ran.

The script already verifies HTTP 200 on exact repeat and HTTP 409 on changed
content with the same ID, then confirms the original history remained unchanged.
To demonstrate those visibly, store a new event through the form, repeat it, then
change only its data and submit with the same ID. Use a separate demo interaction
so the prepared examples retain their exact counts.

## Automated rehearsal

```sh
.venv/bin/python tools/run_phase5_demo.py \
  --base-url http://127.0.0.1:8016 --env-file .env.phase5-regression \
  --allow-synthetic-writes --include-late-event \
  --report reports/phase5-demo-rehearsal.json
```

This additionally submits the late output and verifies warning removal. In that
run the final `late` interaction is already repaired; its pre-repair downloaded
snapshot remains in the evidence directory. A default run leaves the warning
present for the live walkthrough. No reset token is required.

For a hosted classroom demonstration, use the same manual sequence only in the
owner's coordinated synthetic window. This local helper intentionally refuses a
remote base URL. Do not call a demo result a new benchmark or a new reciprocal
cross-team test.
