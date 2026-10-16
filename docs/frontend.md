# Using the TraceAI frontend

The homepage at `/` is now a small browser interface for the existing Phase 3
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
7. To add an output to this interaction, keep the interaction ID, choose a new
   event ID, change the type to **Model output generated**, update the UTC time,
   and submit again. Find the interaction again to see both events.

An exact repeat reports that the event already exists; changing its content
without changing its event ID reports a conflict. Reloading does not delete
stored events, but clears the browser's token and displayed history. Reconnect
and search the same interaction ID to retrieve its records again.

## Authentication and limitations

Tokens are held only in JavaScript memory, never localStorage, sessionStorage,
cookies, or URLs. The password input is cleared after connecting. Disconnect and
page navigation clear the token and displayed records. Requests already sent to
the API may still finish after disconnect; disconnect does not undo accepted events.

Only synthetic data should be submitted. All six event types can be recorded;
review/correction types require their contract-defined data fields. Warnings,
audit reports, correction application, accounts, and a global interaction search
are not implemented. JSON data display uses browser numeric precision; use raw
API responses when inspecting numbers that exceed JavaScript numeric precision.
Submitted JSON numbers are sent in their original text without browser rounding.

Test reset remains in `/docs`, protected by the separate reset token and the
explicit reset-enable setting. There is no delete/reset control on the homepage.
The shared OpenAPI paths, schemas, and API behavior are unchanged.

## Checks

`pytest -q` includes loading the homepage/assets without a working database,
checking that credentials are not exposed, and verifying API protection and
OpenAPI separation. The full existing API test suite still runs.

A reusable Playwright smoke test is at `tests/browser/frontend.cjs`. It submits a
unique synthetic record and verifies retrieval, duplicates, authentication,
not-found messages, safe HTML rendering, token clearing, and mobile overflow.
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
Browser testing is optional developer tooling; the deployed frontend needs only
the Python application. The browser smoke test was exercised locally with system
Chromium against the real API and PostgreSQL, including desktop/mobile screenshots.
