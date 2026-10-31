# Phase 4 chunk 6 — cross-team preparation and delivery

## Completion status

Chunks 1–5 are implemented: warnings, review/correction validation, deterministic
audit reports, reliability/security checks and browser presentation. Chunk 6's
local delivery/tooling is implemented, but **live cross-team compatibility and
both Team 103 runs remain blocked**. No new pod contract approval is claimed.
Performance/capacity acceptance (REQ-13 / AC-10) remains Phase 5.

The current implemented contract is OpenAPI 0.4.2. `GET /health` keeps its original
body and adds `X-TraceAI-Contract`; when Render supplies a valid Git SHA it also
adds `X-TraceAI-Revision`, allowing the tested deployment to be identified without
exposing configuration secrets. No data migration or registry URL change is needed. The Render blueprint now
selects the 126-check Phase 4 tester; read-only `GET /tester` exposes the actual
active profile/count, so a configured flag is distinguishable from a synced deployment.
The hosted check budget is 240 seconds plus a bounded final coverage lookup.

## Compatibility work and remaining decisions

[pod-compatibility.json](pod-compatibility.json) records seven unresolved contract
issues, owners, known access blockers and the historical email results. Those
results stay historical: the reported Phase 3 run was 0 passed, 1 failed and 41
unrun. Team 103's reported inability to run its hosted tester against us is not a
completed run. Neither is our local two-instance validation below.

The current Team 103 contract and test access must be confirmed before writing a
compatibility adapter. Route/field aliases alone cannot translate different event
lifecycles, review/correction semantics or duplicate rules. Keep our existing API
stable while the pod settles a canonical contract and either team implements the
needed adapters/changes. Use the exact OpenAPI file, examples, AC inventory and
component list for that agreement; identical AC numbers do not imply identical
criteria. Do not silently relax tests until they pass or invent missing peer fields.

The offline comparison tool reports missing/additional operations and differences
in parameters, request shapes, responses and authentication. It resolves local
component references and ignores documentation text; it is not a business-rule
proof and rejects unsupported external/cyclic references rather than fetching them.
After obtaining a current peer JSON document:

```sh
python tools/compare_contracts.py --left contracts/openapi.json \
  --right /path/to/team103-openapi.json --report reports/pod-contract-diff.json
```

Exit 0 means matching authored shapes, 1 means differences for review, 2 means
comparison blocked. Matching files do not establish live compatibility.

## Cross-team readiness and exact reports

Readiness probes make only GET requests and do not create a testing session:

```sh
python tools/check_testing_interface.py \
  --tester https://traceai-zm1t.onrender.com/tester \
  --target https://traceai-zm1t.onrender.com --preflight \
  --report reports/our-readiness.json
```

After the target owner confirms isolated data, reset permission, current keys and
tester access, run one direction at a time. The hosted tester holds target keys;
this client sends none. A suite requires explicit reset authorization:

```sh
python tools/check_testing_interface.py \
  --tester https://traceai-zm1t.onrender.com/tester \
  --target http://3.134.49.218:8000 --allow-test-reset \
  --report reports/106-tests-103-evidence.json
python tools/check_testing_interface.py \
  --tester http://3.134.49.218:8001 \
  --target https://traceai-zm1t.onrender.com --allow-test-reset \
  --report reports/103-tests-106-evidence.json
```

These are the previously reported peer URLs, not newly verified current endpoints.
For the first direction, our Render tester needs the peer's key configured in
`TRACEAI_TESTER_TARGET_TOKENS` for the exact target origin. For the second, Team
103 must allow our system and configure our current keys in its tester. Use private
credential exchange and confirm transport/access arrangements with the peer; do
not put keys in the registry, URLs or command lines.

The checker saves a private JSON evidence envelope even for blocked setup,
unreachable services, malformed reports or aborted runs. `counts: null` means
no verified results; `completed: false` is never presented as a full run. If a
validated report is retrieved, a uniquely named sibling `.suite_report.json` file
contains the exact course-format report, and `.system_report.json` contains its
system report. Attach those current files, identified by the envelope, when the
course asks for raw reports. A valid failure report remains a failure; `--require-pass`
requires every test to pass. Exit 0 without that flag checks a complete protocol
exchange, not business conformance. Preflight readiness is also not a suite run.

Our hosted tester now normalizes inconsistent peer code-coverage measures to a
valid unknown measure (`null` / `null` with a reason), instead of emitting mixed
null/integer, boolean or reversed counts. It does not fabricate covered lines.

## Local evidence versus live evidence

The workspace's local two-instance check uses separate migrated PostgreSQL
databases, different tokens and explicitly configured target origins. Each instance
runs its hosted 126-check profile against the other, sequentially, with exact stored
reports and system coverage measures checked. This validates our credential routing
and HTTP testing exchange, **not Team 103's implementation**.

Local report paths are `reports/chunk6-local-0-to-1.json` and
`reports/chunk6-local-1-to-0.json`. Actual shared-team report paths remain absent
until those runs occur. `tools/phase_status.py` can generate requirement/operation
status from the independent evaluator report, without hiding pending pod agreement:

```sh
python tools/phase_status.py reports/chunk6-container.json \
  --label 'Team 106 local deployment image' --output reports/phase4-status.txt
```

## Submission and demonstration

- Registry: system `https://traceai-zm1t.onrender.com`; tester
  `https://traceai-zm1t.onrender.com/tester`. Keep both base URLs free of `/test` suffixes.
- Specification: link the [pod implementation profile](pod-specification.md) and
  [OpenAPI contract](../contracts/openapi.json); identify agreement as pending.
- Access notes: API bearer token for project operations; reset token for system
  setup; our hosted tester needs no caller token. One session at a time; setup
  clears synthetic data. Free-tier cold starts and memory-only reports remain limits.
- Models: the [delivered architecture/data-flow model](architecture.md) reflects
  the actual browser, API modules, hosted tester and separate managed PostgreSQL.
- Demo: follow the [review/correction walkthrough](frontend.md#review-and-correction-demonstration),
  load a report, inspect warnings and original records, then download JSON.
- Results: attach actual test/CI artifacts for the reported code version. Keep
  local, own-deployment and cross-team results separate. No grader result, percentage,
  peer agreement or successful cross-team run is claimed without its evidence.

## Cloud workspace blocker

The active workspace currently permits `traceai-zm1t.onrender.com` but not the
peer IP. The supported configuration save failed twice with `draft_not_editable`;
**saving or applying network access was not confirmed**. The proposed exact change
is preserved in [cross-team-network-proposal.json](cross-team-network-proposal.json)
for environment setup/review. Existing source changes are committed/pushed before
any environment recovery. The runtime [SKILL.md](skill://plugin_connector_1p_c5b7d5df5d7081918f2c4be5a633ed5d/cloud-environment-runtime/SKILL.md)
says: “Configuration changes require the environment configuration workflow and
its user review.” Neither proxy bypass nor a fabricated live failure substitutes
for access. No Team 103 credentials were found in the configured workspace bindings.

## Workspace validation (2026-10-31)

- 198 pytest checks passed; five local process/reliability groups passed.
- Both OpenAPI documents, bundled project-contract parity and database migrations validated.
- Two independent Team 106 instances each passed 126/126 against the other.
- The deployment image passed 126/126 independent API checks, 126/126 hosted
  checks, the exact-report checker, and desktop/mobile browser scenarios.
- The hosted local profile exercised 5/5 project operations and 9/11 ACs. Storage
  failure is verified separately with local fault tests; performance remains deferred.
- Live Render readiness was checked read-only. No public dataset was reset to
  obtain these results, and no Team 103 suite was run.
