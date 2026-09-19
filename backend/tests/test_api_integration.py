"""Real HTTP application, Docker harness, and migrated PostgreSQL together."""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import create_engine
from test_api import TASK, poll, submit
from test_postgres_integration import repository  # noqa: F401

from app.config import Settings
from app.main import create_app
from app.services.run_service import RunService
from app.storage.jobs import JobStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="requires TEST_DATABASE_URL and Docker",
    ),
]


async def test_real_api_docker_postgres_and_concurrency(repository, tmp_path):  # noqa: F811
    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        artifact_root=tmp_path.resolve(),
        environment="test",
        max_concurrent_runs=2,
    )
    service = RunService(settings, repository)
    original = service._factory
    release = asyncio.Event()

    def gated(limits):
        harness = original(limits)
        verify = harness.verifier.verify

        async def blocked(task, workspace):
            await release.wait()
            return await verify(task, workspace)

        harness.verifier.verify = blocked
        return harness

    service._factory = gated
    app = create_app(settings, service=service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/ready")).status_code == 200
            ids = [await submit(client) for _ in range(5)]
            try:
                for run_id in ids[:2]:
                    await poll(client, run_id, ("verifying",))
                assert [service.jobs.get(i)["status"] for i in ids] == [
                    "verifying",
                    "verifying",
                    "queued",
                    "queued",
                    "queued",
                ]
                trace = (await client.get(f"/api/v1/runs/{ids[0]}/trace")).json()
                assert trace["events"][-1]["event_type"] == "verification_started"
            finally:
                release.set()
            for run_id in ids:
                run = await poll(client, run_id)
                assert run["status"] == "completed", run
                assert run["verification"]["passed_tests"] == 3
            run_id = ids[0]
            trace = (await client.get(f"/api/v1/runs/{run_id}/trace?after_sequence=20")).json()
            assert trace["events"][0]["sequence_number"] == 21
            assert trace["events"][-1]["event_type"] == "run_completed"
            metrics = (await client.get(f"/api/v1/runs/{run_id}/metrics")).json()
            assert metrics["tool_calls"] == 6 and metrics["inference"]["input_tokens"] is None
            patch = await client.get(f"/api/v1/runs/{run_id}/patch")
            assert patch.status_code == 200 and '"status": "ok"' in patch.text
            listing = (
                await client.get(f"/api/v1/runs?task_id={TASK}&status=completed&limit=100")
            ).json()
            assert set(ids) <= {r["run_id"] for r in listing["items"]}
            assert len(repository.get(run_id).artifacts) == 3
            assert len(repository.get(run_id).events) == 27
            # Exercise actual connection refusal, not a mocked readiness flag.
            unavailable = create_engine(
                "postgresql+psycopg://agentscope@127.0.0.1:1/agentscope_test",
                connect_args={"connect_timeout": 1},
            )
            service.jobs.engine = unavailable
            try:
                readiness = await client.get("/ready")
                assert readiness.status_code == 503
                assert readiness.json()["database"] == "unavailable"
                assert (await client.get("/health")).status_code == 200
                response = await client.get("/api/v1/runs")
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "service_unavailable"
                assert "psycopg" not in response.text
            finally:
                service.jobs.engine = repository.engine
                unavailable.dispose()


def test_database_claims_recovery_and_single_coordinator(repository):  # noqa: F811
    store = JobStore(repository.engine)
    ids = [uuid.uuid4().hex for _ in range(2)]
    store.acquire()
    try:
        other = JobStore(repository.engine)
        with pytest.raises(RuntimeError, match="one API coordinator"):
            other.acquire()
        for run_id in ids:
            store.submit(run_id, TASK, {}, 100)
        claimed = store.claim()
        assert claimed["run_id"] == ids[0]
        assert store.get(ids[0])["status"] == "running"
        store.recover()
        assert store.get(ids[0])["status"] == "failed"
        assert store.trace(ids[0], 0, 10)[-1]["event_type"] == "run_failed"
        assert store.get(ids[1])["status"] == "queued"
        assert store.claim()["run_id"] == ids[1]
        assert store.claim() is None
    finally:
        for run_id in ids:
            store.fail(run_id, "test cleanup")
        store.release()
