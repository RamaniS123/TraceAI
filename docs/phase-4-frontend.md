# Phase 4 chunk 5 — browser warnings and audit reports

The homepage now presents the warning/report API behavior from chunks 1–4.
After connecting an API token and finding an interaction, users can inspect timeline
notices, load the audit report, and download its exact JSON. The report shows
metadata, versions, human-review decisions and correction links alongside the same
ordered event snapshot. Original events remain unchanged.

See [frontend.md](frontend.md) for demonstration and access instructions. Only
synthetic data is appropriate; credentials remain in page memory. Report values
are rendered as text, not HTML, and no API token is added to downloads. Empty
lists, request errors/retries and disconnects clear or explain the displayed state.
Old in-flight responses cannot restore cleared records. The JSON download preserves
original numeric precision; browser display retains normal JavaScript limits.

The existing API contract remains OpenAPI 0.4.1, with no migration, new runtime
frontend dependency or registry URL change. This implements presentation for
REQ-03, REQ-05, REQ-06 and REQ-09; it does not resolve Team 103 contract differences.

The Playwright browser scenario in `tests/browser/frontend.cjs` runs against a
real isolated API/PostgreSQL service and checks warnings, reviews, corrections,
empty report lists, exact JSON downloads, safe rendering, report errors/retry,
clearing after writes, disconnect races and mobile layout. CI now runs that
scenario and uploads screenshots with the other reports. This browser test is
separate from the shared evaluator; hosted check/coverage counts stay unchanged.

Workspace validation on 2026-10-31: 163 pytest checks and five reliability groups
passed. The deployed-image browser scenario passed on desktop/mobile, as did
126/126 standalone API and 126/126 hosted-tester checks. No public Render data
was reset or populated for these tests.
