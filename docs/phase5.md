# Phase 5: coding-agent research dashboard

Choose a task, launch the mock agent, follow its controlled tools, read the
independent verdict, and inspect measured work and the resulting patch.
No backend application code or API contract changed in this phase.

## Architecture and routes

| Route | Purpose |
| --- | --- |
| `/` | Latest-20-run snapshot, status distribution, verification outcomes, task activity |
| `/runs/new` | Task brief, supported mock/single configuration, asynchronous submission |
| `/runs` | Newest-first history with server pagination and status/task/agent/strategy filters |
| `/runs/:runId` | Lifecycle, official verification, metrics, trajectory, diff, artifact hashes |

```text
frontend/src/
  api/generated/schema.ts     generated OpenAPI contracts
  api/client.ts               typed transport and API errors
  api/queries.ts              query keys and polling policies
  components/                shell, badges, tables, feedback
  features/trace/             incremental queries and expandable events
  features/metrics/           measured values and nullable inference
  features/runs/              independent verification
  features/artifacts/         hash-validated unified diff
  pages/                     four route pages
  router/                    React Router route tree
  lib/                       formatting and status labels
  styles.module.css          lightweight responsive CSS Modules
frontend/tests/              Vitest + React Testing Library
frontend/scripts/            API generation and real-browser capture
```

React, TypeScript, Vite, React Router, and TanStack Query provide the framework.
There is no large component library, chart package, or embedded code editor.
Tables, labeled controls, native expandable details, visible keyboard focus,
and text status labels provide basic accessibility. Tables scroll inside their
panels. The browser demo checks an 820-pixel tablet viewport as well as desktop.

## API generation

`npm run generate-api` runs `scripts/export_openapi.py` and passes the application
schema to `openapi-typescript`. Export instantiates FastAPI without entering
lifespan: no database, server, or Docker is required. The installed backend and
Python environment are required; set `PYTHON=python` to override `.venv/bin/python`.

```sh
cd frontend
npm ci
npm run generate-api
npm run check-api
```

Generated types contain no deployment URL. Backend defaults stay optional in
request schemas. `openapi-fetch` derives paths, parameters, payloads, and responses
from the generated contracts; handwritten aliases reference schemas rather than
copying interfaces. CI detects contract drift. See the official
[openapi-typescript generation documentation](https://openapi-ts.dev/cli).

The client defaults to the browser's origin. Vite proxies `/api`, `/health`,
`/ready`, and `/openapi.json` to `API_PROXY_TARGET`; browsers never need the
Compose backend hostname. `VITE_API_BASE_URL` is an optional build-time override.
Cross-origin hosting would require a deliberate CORS/security design, deferred here.

## Queries and live polling

- Readiness: every 30 seconds, without retries or focus-triggered requests.
- Tasks: one-minute cache. Dashboard/history: five-second refresh.
- Active run status and trace: every second; terminal status stops polling.
- Trace requests use the largest received sequence number as `after_sequence`.
  Events merge by sequence and render in order without duplicates.
- Full 100-event pages trigger short follow-up fetches to drain backlog. Terminal
  status forces a final trace refresh, closing the status/trace polling race.
- Queries use separate run keys and AbortSignals. TanStack Query pauses interval
  polling in hidden windows by default.
- Mutations are not automatically retried. A synchronous submission guard and
  disabled button prevent duplicate clicks. After a lost POST response, check
  history before retrying: the backend does not have POST idempotency keys.

## Honest visualization

Dashboard statistics explicitly cover at most the latest 20 runs, not global
success rates or experimental comparisons. A completed run implies passing
official verification under the database invariant. Run-list elapsed time is
derived from persisted timestamps and labeled accordingly; detail metrics carry
the measured harness durations and official counts.

Official verification is visually separate from agent-invoked tests. A failed
run retains its available metrics, trace, and patch. Inference fields appear only
when non-null; measured zero remains zero and unmeasured stays unmeasured.

Trajectory labels represent actual API event types and sequences, not guessed
agent reasoning. Expanded events show tool arguments/results, command exit code,
stdout/stderr, duration, and timeout/truncation flags. Text displays start at
2,000 characters and expand up to 20,000. Downloading event JSON retains the full
public API payload, including backend truncation flags. The viewer initially
renders 100 events, with further batches available. Hidden verifier diagnostics
remain redacted by the backend.

The patch is fetched from the integrity-checked `text/x-diff` endpoint, rendered
as escaped text, and initially limited to 300 lines with more available. No agent
HTML executes. Artifact metadata shows type, bytes, and SHA-256, never host paths.

## Complete local development

Prepare Docker Engine/Desktop and Compose. Copy `.env.example` to ignored `.env`,
set `POSTGRES_PASSWORD`, host `DATABASE_URL`, and matching `COMPOSE_DATABASE_URL`.
URL-encode the password in URLs. Compose's URL uses hostname `postgres`.

```sh
make dev
# Dashboard: http://127.0.0.1:5173
```

This builds the runner/API/frontend images, starts PostgreSQL, explicitly runs
the migration service, and starts API/UI. Migrations are not in API lifespan.
After setup, `docker compose up -d` starts the existing stack. Frontend `src/` and
`index.html` are mounted for hot reload; dependency/config changes require an
image rebuild. Compose uses Vite's development server, not a cloud production
deployment. `npm run build` creates static assets in `dist/`.

### Docker socket and workspace paths

The backend controls the host Docker daemon through its socket. Agent/verifier
containers are siblings, not Docker-in-Docker. Socket access is effectively
host-administrator access: use this stack only with trusted local callers. All
published ports bind to loopback; there is no authentication. Task containers
themselves never receive the Docker socket.

`AGENTSCOPE_WORKSPACE_ROOT` defaults to `/tmp/agentscope-workspaces`. It must be
an absolute dedicated directory, mounted at the **same path** in the backend
and on the daemon host. `TMPDIR` makes agent and verifier staging use this mount,
so paths passed to the daemon resolve to the correct copied workspaces. Docker
Desktop may require allowing that directory in file sharing settings. Remote
Docker contexts are not supported by this layout.

Artifacts are mounted at `/app/artifacts`. Records made by a host-running API
can have different absolute artifact roots; those patches will be safely refused
instead of permitting arbitrary path access. Use a consistent deployment/root
for a database. PostgreSQL volumes and artifacts survive `docker compose stop`.
Do not delete volumes just to stop the application. `API_CPUS` defaults to 2 and
limits the coordinator, not the existing agent container limits.

### Host development

With Python 3.12, migrated PostgreSQL, and the runner image prepared:

```sh
# Terminal 1; export DATABASE_URL and backend settings first
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1

# Terminal 2
cd frontend
npm ci
npm run dev
```

Do not run two coordinators against one database. Set `API_PROXY_TARGET` for a
non-default backend port. Host/Compose runtime configurations preserve the
existing controlled-tool and hidden-test boundaries.

## Real demonstration

Captured run: `5b05da796f2d4ed0ba4084bc2feb8f29`. Chromium used the real Compose
dashboard at port 5175, FastAPI, PostgreSQL, and sibling Docker containers. It
navigated dashboard → New Run → mock/single submission → **Queued → Running →
Verifying → Completed**, inspected 3/3 official tests, metrics and the +1/−1
patch, filtered history, and checked tablet layout without browser errors.

The normal benchmark took about one second, allowing one-second polling to skip
sub-second stages. For visible screenshot capture, the API container was limited
to **0.1 CPU** with Docker's real resource control. Task code, agent, verifier,
responses, and polling were unchanged. No fake responses or synthetic delays
were introduced. Multiple real runs were submitted until all stages were visible;
the evidence file records all six attempts in the successful capture invocation.
The resource limit was restored afterward.
These are smoke-test measurements, not comparative research results.

The final run has 3 turns, 6 tools, 27 events, 3/3 official tests, one changed file,
+1/−1 lines, 230 patch bytes, and null inference measurements. Trace cursors were
`0, 0, 15, 25`; repeated zero preceded the first available event batch.

- [New Run screenshot](images/new-run.png)
- [Active trace screenshot](images/active-trace.png)
- [Completed verification screenshot](images/completed-run.png)
- [Metrics + patch, trace collapsed through the UI](images/metrics-patch.png)
- [Machine-readable evidence](images/demo-evidence.json)

Reproduce against a running real stack:

```sh
cd frontend
npx playwright install chromium
DEMO_URL=http://127.0.0.1:5173 npm run demo
```

The script fails if it cannot observe both active stages or the task fails.
Fast tasks can legitimately skip a polling stage; for stage-by-stage capture,
set a documented low `API_CPUS` and restart the API. `DEMO_NOTE` records that
environment constraint. The script never intercepts network responses or edits
page data, and it checks browser errors and tablet overflow.

## Quality gates

```sh
cd frontend
npm run check-api
npm run typecheck
npm run lint
npm test
npm run build
```

Frontend tests cover typed client responses/errors, nullable metrics, task
loading, guarded submission/navigation, all lifecycle states, failures, trace
ordering/deduplication/incremental polling, terminal stop, patches, filters,
pagination, navigation, and empty states. Real browser validation complements
these isolated tests. CI also preserves pytest, Ruff, strict mypy, package build,
Docker/PostgreSQL integration, Compose, Alembic, and OpenAPI checks.

Validated results: **21 frontend tests** and **109 backend tests** passed.
Generated API drift check, TypeScript, ESLint, production Vite build, Ruff,
strict mypy, backend wheel/sdist, Compose configuration, and Alembic schema
checks passed. `make dev` was exercised end-to-end. The final CSS Modules UI
also launched a second successful 3/3 real run at the restored 2-CPU API limit:
`af7174fbecfc40acadb7360688d1f3c9`, with no browser errors or tablet overflow.

## Limitations and deferred work

Polling can skip intermediate statuses on short runs, but persisted traces stay
complete. Generated types are compile-time contracts rather than a second runtime
schema validator. Cancellation, model integrations, Harbor, multi-agent strategies,
experiment comparison, new benchmarks, research reports, WebSockets/SSE,
authentication, cloud deployment, and distributed workers remain deferred.
