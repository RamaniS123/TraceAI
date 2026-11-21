# Phase 5 delivery record — November 21, 2026

The implementation, security review, local capacity/performance evidence, regression,
models, documentation and repeatable demo are delivered. **Fresh reciprocal
cross-team validation and hosted/peer performance remain incomplete.** This is a technical handoff package; the external validation gaps remain open.

## Review the package

| Artifact | Purpose |
|---|---|
| [Architecture](architecture.md) | Components, trust boundaries, deployment, dependencies and isolated validation topology |
| [Engineering models](phase-5-models.md) | Workflow, computed state, data model, warning/report models, fault tree and Phase 2 reconciliation |
| [Security review](phase-5-security-review.md) | Threats, fixed arbitrary-target issue, verified controls and residual risks |
| [Capacity](phase-5-capacity.md) | 10,000 events / 100 per interaction; complete snapshots and restart verification |
| [Performance](phase-5-performance.md) | 1,000 requests, ten clients, exact timing boundaries, raw measurements and limits |
| [Regression/cross-team](phase-5-regression.md) | 262 cases, browser/recovery/image/public checks and precise peer blocker |
| [Demo](phase-5-demo.md) | Rehearsable synthetic walkthrough; unique IDs and no reset |

Recorded runtime regression revision: `cb9542ed9f20bbb287f49073d91f39fe12012729`.
Local capacity source: `62b0ff9b87a9aaeb21781fdb5faa035d5e2a8c24`; performance source:
`0e84aed8d6a0649285f23c071d801cf0406c113e`. Later documentation commits do not turn
those earlier measurements into new benchmark or reciprocal results.

## Evidence and readiness

| Item | Result / scope |
|---|---|
| Common project interface | OpenAPI 0.4.2; five operations; JSON schemas unchanged |
| Security hardening | Tester origin approval fixed; controlled destinations and credential scoping verified |
| Local capacity | 10,000 original events; 100 interactions of 100 events; no record loss/changes |
| Local performance | 1,000/1,000 correct and <=1 s application response-ready; p95 20.51 ms; maximum 68.63 ms |
| Regression | 262 pytest cases, four HTTP profiles, five recovery groups, browser and 126-check deployment image passed |
| Fresh deployed self-test | 126/126; complete exchange on November 21 |
| Fresh forward peer suite | 126/126; independent workspace system-report fetch blocked |
| Fresh reverse peer run | Not run; no new count/coverage asserted |
| Historical reciprocal result | November 1, 130/130; labeled historical |
| Hosted/peer performance | Unmeasured; proposed shared workload/timing needs pod confirmation |
| Demo | Two local runs passed: 12 events with late repair and 11 events prepared for the live walkthrough; no resets |

The [delivery checks](phase-5-delivery-checks.json) record the actual demo IDs,
warning/report checks, HTTP 200 duplicate, HTTP 409 conflict, late-event repair,
remote-load refusal and artifact hashes. Benchmark storage still contains exactly
10,000 events. No new runtime regression count or benchmark result is claimed.

## Known limitations and next actions

| ID | Limitation / affected capability | Severity | Workaround or next action |
|---|---|---|---|
| LIM-01 | Hosting inactivity/startup may delay first response; REQ-14 availability | Medium | Check health before a scheduled demo and allow startup time; no fixed cold-start SLA measured |
| LIM-02 | Reset clears the shared synthetic dataset; concurrent runs interfere; REQ-10/14 | Medium | Coordinate one resetting session at a time; save required reports first |
| LIM-03 | Tester sessions/reports disappear on web-process restart; REQ-14 | Medium | Download JSON promptly; create a new session after restart |
| LIM-04 | Render/peer workload performance remains unmeasured; REQ-13 | Medium | Retain the passing local profile as supporting evidence; agree profile/resources/exclusive window before hosted comparison |
| LIM-05 | Browser numeric display may round beyond JavaScript precision; REQ-06 | Low | Use exact downloaded JSON/raw API for precision inspection |
| LIM-06 | Own deployed source-code coverage is uninstrumented; system report uses null | Low | Report unmeasured, not zero or a fabricated percentage |
| LIM-07 | Actual hosted DB expiration/retention is unknown; REQ-09 | High | Owner checks provider dashboard and exports needed records; arrange continued hosting if required |
| LIM-08 | Public tester can invoke approved resets; no global admission/rate or retention limit | High | Synthetic classroom use only; restrict ingress for private use and agree caller-auth/resource controls before production |
| LIM-09 | Approved peer uses plaintext HTTP; credential/record confidentiality risk | High | Coordinate HTTPS/private transport; target allowlisting does not encrypt traffic |
| LIM-10 | No accounts/tenant-scoped authorization/global interaction search | Medium | Treat bearer holders as authorized for the entire synthetic dataset; do not use as a multi-tenant service |
| LIM-11 | Fresh reverse exchange blocked by workspace proxy; REQ-14 evidence | Medium | Apply the narrow host grant or obtain a fresh peer-produced JSON report; November 1 report remains historical |

These are open follow-up actions, not claims of fixes scheduled or approved by the
pod. Credential rotation, paid resources, new peer load and provider configuration
changes were not performed in this delivery work. No external audit or legal
compliance certification is claimed.

## Resume the remaining checks

The [network proposal](cross-team-network-proposal.json) adds only the confirmed
peer IP while retaining existing access. The attempted save returned
`draft_not_editable`; no live grant was applied. Verify access before requesting a
new reset. The existing forward session ID is in the regression summary and can
be used for an independent report fetch if the peer still retains it. Run the
reverse test in a confirmed coordinated window and record the actual target
revision, timestamps, well-formed report, counts and coverage. A later uploaded
report must be validated as fresh rather than silently replacing historical data.

Do not run resetting suites against the retained benchmark database. Preserve its
manifest and all 1,000 measured outcomes. No course report or form submission
is part of this technical delivery.
