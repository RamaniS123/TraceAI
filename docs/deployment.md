# Render deployment — Phase 3, chunk 5

## Status

Deployment configuration is prepared and the container has been validated
locally. No Render service/database has been created by this workspace: no
Render account binding or API credential is available. Public health and API
testing remain pending until the account owner launches the Blueprint.

## Launch on Render

1. Sign in to Render and connect the GitHub account that can access
   `RamaniS123/TraceAI`.
2. Select **New → Blueprint**, choose this repository and its main branch, and
   let Render read the root `render.yaml`. A deployment shortcut is
   `https://render.com/deploy?repo=https://github.com/RamaniS123/TraceAI`.
3. Review and apply the Blueprint. It requests a free Docker web service named
   `traceai` and free managed PostgreSQL named `traceai-db`. Render controls current
   plan availability, quotas, and expiration. If free database hosting is not
   available, choose a hosting/budget alternative before creating paid resources.
4. Wait for the database and web service to become available. The Docker startup
   script applies migrations before starting Uvicorn; Render checks `/health`.
5. Record the actual service origin shown by Render, typically an HTTPS
   `onrender.com` address. The final name is assigned by Render; no public URL is
   claimed in this repository until that deployment exists.

No local database password needs to be reused. Render injects its database
connection string and generates two distinct API credentials. The database is
reachable through Render's private network; external database access is disabled
by the Blueprint. The public API remains available over HTTPS.

## Configuration

| Setting | Blueprint source / purpose |
| --- | --- |
| `TRACEAI_DATABASE_URL` | Managed database connection string, injected by Render |
| `TRACEAI_API_TOKEN` | Generated secret for ordinary protected API access |
| `TRACEAI_RESET_TOKEN` | Separately generated secret with reset permission |
| `TRACEAI_TEST_RESET_ENABLED` | `true` for this isolated synthetic classroom/test deployment |
| `PORT` | Assigned by Render and read by `deploy/start.sh` |

The application accepts `postgres://`, `postgresql://`, and
`postgresql+psycopg://` URLs and selects psycopg automatically. Password encoding
and supplied TLS options are preserved. Do not disable TLS verification to fix
connectivity. Do not commit any hosted connection string or token.

The service intentionally supports authorized test reset because cross-team
Phase 3 tests require it. Do not place important or real sensitive data in this
dataset. Disable reset for any separate non-test deployment.

## Deployment implementation

- Docker uses Python 3.12 and pinned runtime/build dependencies, without pytest or
  the API evaluator dependencies in its installed runtime dependency set.
- The application runs as the unprivileged `traceai` user.
- `.dockerignore` allows only build/runtime inputs, excluding local credentials,
  reports, the Git checkout, and development caches.
- `deploy/start.sh` runs `alembic upgrade head` and then replaces itself with
  Uvicorn bound to `0.0.0.0:$PORT`. Migration failure prevents API startup.
- One instance is configured. A multi-instance production rollout would need a
  separate coordinated migration step; that is outside this classroom deployment.
- Managed PostgreSQL holds records independently of the web container's lifetime.
  Retention still depends on the selected Render database plan and its lifetime.
- Keep the web service and database in the same Render region. If the dashboard
  requires a region selection, use the same region for both.

Build locally using `docker build -t traceai:local .`. This cloud workspace uses
an egress proxy; its build was verified with optional BuildKit proxy/CA secrets
and a host-resolution override. Proxy credentials and certificates are mounted
only for the dependency-installation step, never saved into image layers. Normal
Render builds do not require those optional secrets.

## Validate the public deployment

First request public `/health`; expect HTTP 200 with healthy API and storage.
Then follow [the independent runner instructions](testing.md) against the actual
HTTPS service origin. Obtain tokens from Render's environment settings and place
them in secure environment bindings or an ignored local credentials file; do not
paste them into chat. Use a file containing only the selected service's tokens:

```sh
.venv/bin/python tools/run_phase3_api_tests.py \
  --base-url https://YOUR-ACTUAL-SERVICE.onrender.com \
  --env-file .env.render \
  --allow-test-reset \
  --wait-seconds 60 \
  --report reports/render-api.json
```

This explicitly clears synthetic test data. All 42 checks must pass, with zero
failed and zero unrun. Free-tier cold starts may take longer than a readiness
wait; if so, inspect the service status before rerunning. Do not classify the
service as deployed-and-validated until the real HTTPS request and suite pass.

## Troubleshooting

- Build fails: check Render's build output and confirm the root Dockerfile and
  pinned requirements files are present on main.
- Migration fails: check the database is available and the injected URL points to
  the managed database. Do not print the URL or post database credentials.
- Health returns 503: storage is unavailable or the migration revision differs;
  inspect Render's service/database status and deployment output.
- Protected requests return 401: use this deployment's token, not the local token.
- Reset returns 403: use the separate reset credential and check reset is enabled
  for the isolated test deployment.

## Verified locally

51 pytest checks pass, contract validation passes, and Alembic detects no model
changes. The built Docker image runs as a nonroot user, applies migrations to an
empty PostgreSQL database, respects a custom PORT, preserves a submitted event
across container restart, and passes the 42-check HTTP evaluator twice. These
checks are local container evidence, not evidence of an existing Render service.
GitHub CI also builds and evaluates the deployment image on future runs.
