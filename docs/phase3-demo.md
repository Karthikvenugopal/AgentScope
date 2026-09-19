# Phase 3 demonstration

Measured locally on September 17, 2026 with the Docker runner and PostgreSQL 16.
These are functional smoke-test measurements, not comparative agent research.

```sh
python -m app.cli run --task incorrect_api_response --agent mock --baseline --run-id phase3-baseline
python -m app.cli run --task incorrect_api_response --agent mock --run-id phase3-fixed
python -m app.cli runs show phase3-fixed
```

The baseline agent makes no edits. It completes its decision loop but the
independent verifier fails all three tests; the CLI returns exit status 1.

| Stored run | Terminal status | Official tests passed | Patch |
| --- | --- | --- | --- |
| `phase3-baseline` | `verification_failed` | 0/3 | unchanged |
| `phase3-fixed` | `completed` | 3/3 | +1 / -1 |

The fixed run's CLI summary:

```text
Run: phase3-fixed
Task: incorrect_api_response
Agent: mock
Status: completed
Agent execution: completed
Verification: PASSED
Official tests: 3/3
Tool calls: 6
Agent turns: 3
Files modified: 1
Lines: +1 / -1
Agent time: 0.34s
Verification time: 0.46s
Total time: 1.11s
Trace: artifacts/runs/phase3-fixed/trace.json
Patch: artifacts/runs/phase3-fixed/patch.diff
Persisted: PostgreSQL
```

The patch changes `return {"state": "healthy"}` to
`return {"status": "ok"}`. The original fixture remains unchanged. The agent
uses list-directory, read, search, edit, visible tests, and diff tools; it never
receives official tests. The agent workspace and verifier container are removed
after execution; the patch and JSON artifacts remain.

## Stored evidence

`runs show phase3-fixed` reads PostgreSQL and returns the completed summary,
27 ordered events, verification (exit 0; 3 passed, 0 failed), aggregate metrics,
and three hashed artifact records. The trace ends with:

```text
24 agent_completed
25 verification_started
26 verification_completed  passed=true, exit_code=0, passed_tests=3
27 run_completed
```

The stored patch is 230 bytes with SHA-256:

```text
e3118d1d2b81eaac6d4b2dcf0d721a909d9e908d9b07fcea21fc5beba91f3b72
```

Metrics contain six successful tool calls, three turns, one modified file,
one agent test run, zero retries/timeouts/truncations, and null inference
measurements. These values were read back from PostgreSQL, not inferred from
the agent's completion summary.

Final validation: 91 tests passed, including Docker/PostgreSQL integration;
Ruff and strict mypy passed; wheel and source distribution built; Compose
validated; Alembic reported `0002_completion_guard (head)` and no schema drift.

For this demonstration only, the dedicated local database uses trust auth on
127.0.0.1:55432 with database `agentscope_test`, user `agentscope`, container
`agentscope-phase3-postgres`, and persistent volume `agentscope-phase3-data`.
It remains available for inspection. Do not use trust authentication for a
shared or production deployment; use the password-configured Compose setup.
