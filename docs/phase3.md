# Phase 3: verified, persistent runs

Agent-reported completion is not benchmark success. The single-agent harness
stops the agent container before collecting the final patch and copying the
candidate into a separate verifier workspace. Only independent verification can
produce `completed`; failing official tests produce `verification_failed`.
Execution exceptions and overall deadlines remain `failed` and `timed_out`.

## Verification boundary

`BenchmarkVerifier` is provider-neutral. `PytestBenchmarkVerifier` receives the
trusted task definition and a frozen workspace, not an agent tool session.
The catalog requires disjoint fixture and verification source trees and rejects
symlinks. The agent receives a task view without verification configuration.
Only the candidate fixture is mounted during agent execution. Official tests
are copied into a fresh container after that container has stopped.

The verifier disables automatic pytest plugins, candidate conftest discovery,
and candidate pytest configuration. Official tests explicitly import candidate
code. Counts come from a bounded JUnit XML report, never guessed from console
output. Missing/invalid reports, crashes, and timeouts have typed failure
results; unavailable counts stay null. All tests must pass, without skips.

This separates tests from the agent's tools and decision loop. It is not a
claim that importing arbitrary hostile Python into a test process is a
tamper-proof grading oracle. Stronger adversarial evaluation is future work.

## Metrics

`RunMetricsAggregator` derives tool attempts, completions, failures, turns,
command/test durations, truncations, and timeout counts from ordered events.
Added/removed lines are counted from actual unified-diff hunks. Patch bytes are
UTF-8 bytes. Official counts come exclusively from verification results.

Total wall time covers execution, verification, and workspace cleanup, but
excludes artifact export and database commit. Agent time uses the agent event
boundaries. Verification result duration covers the verifier operation; lifecycle
overhead can therefore differ from individual test command duration.
Retries are zero because this phase has no execution retry loop. Inference
fields are null: no model calls, token counts, TTFT, ITL, or throughput are
invented. Null means unmeasured, not measured zero.

## Database schema and migrations

SQLAlchemy 2 Core and psycopg implement the narrow `RunRepository` interface.
The harness does not depend on SQLAlchemy. PostgreSQL stores:

| Table | Contents |
| --- | --- |
| `runs` | Terminal status, identity, timestamps, configuration, source hashes, summary and content fingerprint |
| `trace_events` | Run/sequence primary key, unique event ID, indexed event type, timestamp, JSONB payload |
| `verifications` | One official result per run, queryable counts/status/duration and full JSONB result |
| `run_metrics` | One aggregate per run, queryable durations/tool count, JSONB breakdown and nullable inference fields |
| `artifacts` | Run/type primary key, unique run/path, size and SHA-256 |

`0001_verified_runs` creates the schema. `0002_completion_guard` adds a deferred
constraint trigger requiring a passing, non-timeout verification and metrics
when a completed run is inserted or updated. Foreign keys, unique event IDs,
positive sequence numbers, and terminal-status constraints protect storage.
Finalized records are immutable through the repository interface.

```sh
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/agentscope'
alembic -c backend/alembic.ini upgrade head
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini check
```

Production schema management uses migrations, never `create_all()`.

## Finalization and failure behavior

Each terminal run and its events, verification, metrics, and artifact metadata
are saved in one database transaction. A failed child insert rolls back the
parent. Identical finalized saves are idempotent; conflicting reuse of a run ID
is rejected. Event sequences must be contiguous and belong to the run.

Local artifacts are exported before the database transaction so their hashes
are known. `run.json` excludes its own hash metadata to avoid self-reference.
Files are replaced atomically individually, not as a distributed disk/database
transaction. Export failures are recorded as failed runs where the database is
available. Database failure is reported explicitly and local artifacts are
updated to reflect it; the CLI does not claim successful persistence.
Finalization is shielded against cooperative cancellation once started.

There is no durable in-progress job queue in this phase: only finalized runs
are persisted. A hard process kill can leave artifacts without a database row
or require container recovery. There is no claim of atomicity across process
death, filesystem writes, and PostgreSQL commits.

Configuration records include limits, mock script, image tag, task version,
and source/candidate/verification hashes. A local fixture without a Git revision
records null rather than inventing a commit. Image tags are not immutable image
digests; pin images for reproducibility across machines.

## Validation

Unit tests use explicitly injected test runtimes; production commands execute
only in Docker. Real integration tests use a dedicated PostgreSQL database and
Docker, apply migrations, check drift, and read complete runs back.

```sh
pytest backend/tests
ruff check backend
mypy --config-file backend/pyproject.toml backend/app
AGENTSCOPE_RUN_DOCKER_TESTS=1 TEST_DATABASE_URL="$DATABASE_URL" pytest backend/tests
uv build backend
docker compose config --quiet
```

Use a disposable test database: integration tests insert test records.
Compose requires a user-supplied password; `.env.example` contains placeholders.
APIs, dashboards, external agents, multi-agent strategies, and experiments remain
out of scope.
