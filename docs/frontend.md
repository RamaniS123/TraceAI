# Using the TraceAI frontend

The homepage at `/` is now a small browser interface for the Phase 4
API. It uses the same PostgreSQL database as the API; it does not create another
database. No new production framework or dependency is required.

## First demonstration

1. Open the deployed service's main address after Render deploys this commit.
   The page shows API/database health.
2. In Render, open the **traceai web service → Environment**, locate
   `TRACEAI_API_TOKEN`, and copy its value privately. Use the API token, not the
   database password or reset token. The person demonstrating the service needs
   this credential; the homepage does not expose it.
3. Paste it into **API token** and select **Use token**. This sets the token for
   the page; it is validated when a protected request is made.
4. Select **Fill example**. This fills a unique synthetic interaction-started
   event and the corresponding search ID. It does not send anything yet.
5. Select **Store event**. The confirmation identifies the accepted event and
   interaction. PostgreSQL stores the event through the existing API.
6. Select **Find events**. The saved event appears in the interaction history.
   Expand **View event details** to inspect its model/application versions and data.
   Timeline warnings appear above the events, including missing events, out-of-order
   events and correction notices.
7. To add an output to this interaction, keep the interaction ID, choose a new
   event ID, change the type to **Model output generated**, update the UTC time,
   and submit again. Find the interaction again to see both events.

An exact repeat reports that the event already exists; changing its content
without changing its event ID reports a conflict. Reloading does not delete
stored events, but clears the browser's token and displayed history. Reconnect
and search the same interaction ID to retrieve its records again.

## Audit reports

After **Find events**, select **Load audit report** below the timeline. The report
shows event count, first/last timestamps, model/application versions, human reviews
and correction links. Loading it also refreshes the events and warnings from that
same report snapshot. Empty review/correction lists and histories with no warnings
have explicit messages. The report supports reviewing records; it does not certify
legal compliance or evaluate decisions.

**Download report JSON** saves the exact API response, including events and warnings.
The file preserves high-precision JSON numbers even though browser display uses
JavaScript numeric precision. It contains submitted records, never the bearer token.
A saved file remains on your device after disconnecting.

Submitting an event, finding another interaction, changing tokens or disconnecting
clears the old displayed report and its download. A delayed request cannot redisplay
records after disconnect. Failed report loads show a retryable error and disable
download of the previous report. Report loading always uses the displayed interaction,
not an unsent search-field edit. There is no automatic refresh after another client's
writes; select Find events or Load audit report to retrieve the current snapshot.

## Authentication and limitations

Tokens are held only in JavaScript memory, never localStorage, sessionStorage,
cookies, or URLs. The password input is cleared after connecting. Disconnect and
page navigation clear the token and displayed records. Requests already sent to
the API may still finish after disconnect; disconnect does not undo accepted events.

Only synthetic data should be submitted. All six event types can be recorded;
review/correction types require their contract-defined data fields. Timeline warnings, correction-link validation, and audit reports are available in the API and frontend.
Automatic correction replacement, accounts, and global interaction search are not implemented. JSON data display uses browser numeric precision; use raw
API responses when inspecting numbers that exceed JavaScript numeric precision.
Submitted JSON numbers are sent in their original text without browser rounding.

Test reset remains in `/docs`, protected by the separate reset token and the
explicit reset-enable setting. There is no delete/reset control on the homepage.
This frontend increment leaves shared OpenAPI paths, schemas, and API behavior unchanged.

## Checks

`pytest -q` includes loading the homepage/assets without a working database,
checking that credentials are not exposed, and verifying API protection and
OpenAPI separation. The full existing API test suite still runs.

A reusable Playwright smoke test is at `tests/browser/frontend.cjs`. It submits a
unique synthetic record and verifies retrieval, duplicates, authentication,
not-found messages, warning/review/correction presentation, empty report sections,
exact-number downloads, safe HTML rendering, report failures/retry, token clearing,
delayed responses after disconnect, and mobile overflow.
Run only on an isolated synthetic test service. It leaves its synthetic record
in that dataset; it does not reset any data.

For optional browser testing, install Playwright separately from the application:

```sh
npm install --prefix /tmp/traceai-browser-tools playwright@1.62.1
node /tmp/traceai-browser-tools/node_modules/playwright/cli.js install chromium
NODE_PATH=/tmp/traceai-browser-tools/node_modules node tests/browser/frontend.cjs
```

Supply `TRACEAI_UI_BASE_URL` and `TRACEAI_UI_API_TOKEN` securely in the process
environment first. `TRACEAI_CHROMIUM_PATH` optionally selects an existing Chromium
executable. Screenshots are generated under ignored `reports/browser/`.
GitHub Actions installs these separate browser tools and runs the browser smoke test.
For local development the same test is available on demand; the deployed frontend needs only
the Python application. The browser smoke test was exercised locally with system
Chromium against the real API and PostgreSQL, including desktop/mobile screenshots.

## Review and correction demonstration

Keep one interaction ID and use a new event ID for every step, with increasing
UTC occurrence times. After the started event, submit a **Model output generated**
event with `{}`. Submit **Human review completed** with data such as:

```json
{"reviewerId":"classroom-reviewer","action":"override","reason":"Synthetic review for the demo"}
```

Record that review event's ID. Submit **Record corrected** with data such as:

```json
{"correctsEventId":"your-review-event-id","reason":"Synthetic clarification; original review retained"}
```

Replace `your-review-event-id` with the ID actually stored above. Finally submit
**Interaction completed** with `{}`. Find the interaction again and load its
report: the review and correction appear separately, and the timeline shows a
correction notice. To explore missing-event warnings, use a different interaction
and submit only a completion event. To explore ordering warnings, use an output
with a timestamp earlier than its interaction-started event.
