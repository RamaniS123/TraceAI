# Delivered architecture — Phase 4

This updates the Phase 2 architecture/data-flow model to reflect the implemented
browser, API analysis and hosted tester. Boxes name actual modules/services.

```mermaid
flowchart TD
    U[User / automated API client] -->|HTTPS JSON + bearer token| A[FastAPI routes: main.py]
    U -->|HTTPS| F[Browser: static HTML / CSS / JavaScript]
    F -->|Health, events, history and audit report requests| A
    A --> V[auth.py / requests.py / schemas.py]
    V --> E[events.py: transactional storage and retrieval]
    E -->|SQLAlchemy / psycopg| D[(Separate Render PostgreSQL service)]
    E --> T[timeline.py / corrections.py: ordering and warnings]
    T --> R[reports.py: deterministic audit projection]
    R --> A
    T --> A
    X[Course staff / pod tester client] -->|setup / run / report| C[testing_interface.py hosted tester at /tester]
    C -->|HTTP to configured target| S[Target system /test endpoints and project API]
    X -->|system setup / report| Y[testing_interface.py system endpoints]
    Y --> E
```

The Python service runs in a Docker container on Render; PostgreSQL is a separate
managed service. Accepted records are never replaced by correction events.
`SafeErrorBoundary` wraps HTTP handling, and `startup.py` migrates before serving.
The hosted tester reuses the independent evaluator and fixtures; its HTTP target
may be our service or an authorized peer. Test sessions/reports remain in memory.
No external AI model, queue, account system or separate report database is present.
