"""HTTP contracts and real application workers with injected test-only storage/runtime."""

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import IsolatedTestRuntime
from pydantic import ValidationError

from app.agents import MockCodingAgent
from app.api.schemas import public_event
from app.config import Settings
from app.experiments.models import load_spec
from app.harness.artifacts import ArtifactStore
from app.harness.single_agent import SingleAgentHarness
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.main import create_app
from app.services.run_service import RunService
from app.storage.jobs import QueueFullError
from app.storage.repository import StoredRun

ROOT = Path(__file__).resolve().parents[2]
TASK = "incorrect_api_response"


async def test_strategy_discovery_validation_and_hierarchical_response(api):
    client, service, _ = api
    capabilities = (await client.get("/api/v1/strategies")).json()
    assert {s["id"] for s in capabilities} == {
        "single",
        "planner_implementer_reviewer",
        "parallel_implementers",
    }
    bad = await client.post(
        "/api/v1/runs",
        json={
            "task_id": TASK,
            "strategy": "parallel_implementers",
            "configuration": {"implementers": {"count": 9}},
        },
    )
    assert bad.status_code == 422
    service.settings = service.settings.model_copy(update={"max_parallel_implementers": 2})
    bad = await client.post(
        "/api/v1/runs",
        json={
            "task_id": TASK,
            "strategy": "parallel_implementers",
            "configuration": {"implementers": {"count": 3}},
        },
    )
    assert bad.status_code == 422
    run_id = await submit(
        client, strategy="parallel_implementers", configuration={"implementers": {"count": 2}}
    )
    for _ in range(150):
        response = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if response["status"] not in ("queued", "running", "verifying"):
            break
        await asyncio.sleep(0.02)
    assert response["status"] == "completed", response
    assert response["orchestration"]["candidate_count"] == 2
    assert len(response["orchestration"]["executions"]) == 4
    assert response["orchestration"]["metrics"]["total_tokens"] is None


class MemoryEngine:
    def dispose(self):
        pass


class MemoryRepository:
    def __init__(self):
        self.engine = MemoryEngine()
        self.runs = {}

    def save(self, run):
        self.runs[run.run_id] = StoredRun(
            summary=run.model_dump(mode="json"),
            events=run.events,
            verification=run.verification,
            metrics=run.metrics,
            artifacts=run.artifact_metadata,
        )

    def get(self, run_id):
        return self.runs.get(run_id)


class MemoryJobs:
    """No production process-local state: this store exists only for unit tests."""

    def __init__(self, repository):
        self.repository = repository
        self.rows = {}
        self.events = {}
        self.healthy = True
        self.lock = threading.Lock()

    def ping(self):
        if not self.healthy:
            raise ConnectionError("postgres://secret-password@private-host")

    def acquire(self):
        pass

    def release(self):
        pass

    def check_lease(self):
        self.ping()

    def recover(self):
        pass

    def submit(
        self, run_id, task_id, configuration, capacity, agent_name="mock", strategy="single"
    ):
        with self.lock:
            if (
                sum(r["status"] in ("queued", "running", "verifying") for r in self.rows.values())
                >= capacity
            ):
                raise QueueFullError
            self.rows[run_id] = dict(
                run_id=run_id,
                task_id=task_id,
                agent_name=agent_name,
                strategy=strategy,
                status="queued",
                configuration=configuration,
                submitted_at=datetime.now(UTC),
                started_at=None,
                finished_at=None,
                failure_reason=None,
            )
            self.events[run_id] = []

    def claim(self):
        with self.lock:
            job = next((r for r in self.rows.values() if r["status"] == "queued"), None)
            if job:
                job.update(status="running", started_at=datetime.now(UTC))
                return job.copy()

    def event(self, event):
        with self.lock:
            self.events[event.run_id].append(event.model_dump(mode="json"))
            if event.event_type == "verification_started":
                self.rows[event.run_id]["status"] = "verifying"

    def finish(self, run_id, status, reason=None):
        self.rows[run_id].update(
            status=status, failure_reason=reason, finished_at=datetime.now(UTC)
        )

    def fail(self, run_id, reason):
        self.finish(run_id, "failed", reason)

    def get(self, run_id):
        return self.rows.get(run_id)

    def trace(self, run_id, after, limit):
        stored = self.repository.get(run_id)
        events = (
            [e.model_dump(mode="json") for e in stored.events] if stored else self.events[run_id]
        )
        return [e for e in events if e["sequence_number"] > after][:limit]

    def listing(self, limit, offset, filters):
        rows = [
            self.repository.get(k).summary if self.repository.get(k) else v
            for k, v in self.rows.items()
        ]
        rows = [r for r in reversed(rows) if all(r[k] == v for k, v in filters.items())]
        return rows[offset : offset + limit]


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://test@localhost/test",
        artifact_root=tmp_path.resolve(),
        environment="test",
    )
    repository = MemoryRepository()
    service = RunService(settings, repository)
    service.jobs = MemoryJobs(repository)
    runtime = IsolatedTestRuntime()

    def factory(limits):
        return SingleAgentHarness(
            catalog=service.catalog,
            limits=limits,
            repository=repository,
            artifact_store=ArtifactStore(tmp_path),
            workspace_factory=DockerWorkspaceFactory(runtime=runtime),
        )

    service._factory = factory
    app = create_app(settings, service=service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client, service, runtime


async def submit(client, **kwargs):
    response = await client.post("/api/v1/runs", json={"task_id": TASK, **kwargs})
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    run_id = response.json()["run_id"]
    assert response.headers["location"] == f"/api/v1/runs/{run_id}"
    return run_id


async def poll(client, run_id, wanted=("completed", "failed", "verification_failed", "timed_out")):
    async with asyncio.timeout(15):
        while True:
            response = await client.get(f"/api/v1/runs/{run_id}")
            assert response.status_code == 200, response.text
            if response.json()["status"] in wanted:
                return response.json()
            await asyncio.sleep(0.02)


async def test_tasks_hide_official_material_and_errors(api):
    client, _, _ = api
    listing = await client.get("/api/v1/tasks")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == TASK
    response = await client.get(f"/api/v1/tasks/{TASK}")
    assert response.json()["test_command"]
    for forbidden in ("verification", "test_official", "hidden_tests", "candidate", "verifier"):
        assert forbidden not in response.text
        assert forbidden not in listing.text


async def test_task_catalog_metadata_and_filters_do_not_expose_hidden_paths(api):
    client, _, _ = api
    native = await client.get(
        "/api/v1/tasks", params={"source": "agentscope", "language": "TypeScript/JavaScript"}
    )
    assert native.status_code == 200
    assert {task["id"] for task in native.json()} == {"js_batch_dedupe", "js_ttl_cache"}
    external = await client.get(
        "/api/v1/tasks", params={"dataset": "terminal-bench/terminal-bench-2-1"}
    )
    assert external.status_code == 200 and len(external.json()) == 4
    item = external.json()[0]
    assert item["source"] == "harbor" and item["dataset_version"] == "2.1@6"
    assert len(item["task_hash"]) == 64
    assert "solution/" not in external.text and "tests/" not in external.text
    missing = await client.get("/api/v1/tasks/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"
    assert (await client.post("/api/v1/runs", json={"task_id": "missing"})).status_code == 404


async def test_experiment_progress_and_analysis_endpoints(api):
    client, service, _ = api
    record = {
        "experiment_id": "strategy-study-v1",
        "name": "Strategy Study v1",
        "research_question": "How does orchestration affect outcomes?",
        "status": "running",
        "benchmark_name": "AgentScope Benchmark",
        "benchmark_version": "0.1",
        "benchmark_manifest_hash": "a" * 64,
        "spec_hash": "b" * 64,
        "created_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "finished_at": None,
        "pause_reason": None,
        "provenance": {"agentscope_commit": None},
        "progress": {
            "planned": 108,
            "completed": 1,
            "benchmark_successes": 1,
            "benchmark_failures": 0,
            "infrastructure_failures": 0,
            "protocol_exclusions": 0,
            "pending": 107,
            "running": 0,
        },
        "configurations": [],
        "schedule": [],
        "attempts": [],
        "spec": load_spec(
            ROOT / "experiments/phase9/strategy-study-v1.yaml"
        ).model_dump(mode="json"),
    }

    class Experiments:
        def list_experiments(self):
            return [record]

        def get(self, experiment_id):
            return record if experiment_id == record["experiment_id"] else None

        def raw_runs(self, experiment_id):
            return []

    service.experiments = Experiments()
    listing = await client.get("/api/v1/experiments")
    assert listing.status_code == 200
    assert listing.json()[0]["progress"]["planned"] == 108
    detail = await client.get("/api/v1/experiments/strategy-study-v1")
    assert detail.status_code == 200
    assert detail.json()["analysis"]["valid_runs"] == 0
    missing = await client.get("/api/v1/experiments/missing")
    assert missing.status_code == 404
    assert "task_hashes" not in detail.text


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"task_id": TASK, "agent": "openhands"}, "unsupported_agent"),
        ({"task_id": TASK, "strategy": "parallel"}, "unsupported_strategy"),
        ({"task_id": TASK, "configuration": {"command": "rm -rf /"}}, "invalid_configuration"),
        ({"task_id": TASK, "configuration": {"max_agent_turns": 0}}, "invalid_configuration"),
        ({"task_id": "../../etc/passwd"}, "invalid_request"),
        ({"task_id": TASK, "secret": "do-not-echo"}, "invalid_request"),
    ],
)
async def test_create_validation(api, payload, code):
    client, service, _ = api
    response = await client.post("/api/v1/runs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert "do-not-echo" not in response.text
    assert not service.jobs.rows


async def test_successful_http_pipeline_and_paged_trace(api):
    client, service, runtime = api
    run_id = await submit(client)
    run = await poll(client, run_id)
    assert run["status"] == "completed"
    assert run["verification"]["passed_tests"] == 3
    assert "host_path" not in str(run) and "verification.source" not in str(run)
    metrics = (await client.get(f"/api/v1/runs/{run_id}/metrics")).json()
    assert metrics["tool_calls"] == 6
    assert all(value is None for key, value in metrics["inference"].items() if key != "provenance")
    first = (await client.get(f"/api/v1/runs/{run_id}/trace?limit=5")).json()
    second = (await client.get(f"/api/v1/runs/{run_id}/trace?after_sequence=5&limit=500")).json()
    events = first["events"] + second["events"]
    assert [e["sequence_number"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["event_type"] == "run_completed"
    assert "stdout" not in events[-2]["payload"]["result"]
    patch = await client.get(f"/api/v1/runs/{run_id}/patch")
    assert patch.status_code == 200 and patch.headers["content-type"].startswith("text/x-diff")
    assert '+    return {"status": "ok"}' in patch.text
    artifacts = (await client.get(f"/api/v1/runs/{run_id}/artifacts")).json()
    assert len(artifacts) == 3 and all(
        set(a) == {"type", "size_bytes", "sha256"} for a in artifacts
    )
    assert not runtime.workspaces
    assert service.repository.get(run_id)


async def test_listing_filters_and_limits(api):
    client, _, _ = api
    ids = [await submit(client), await submit(client)]
    for run_id in ids:
        await poll(client, run_id)
    first = (
        await client.get(
            f"/api/v1/runs?limit=1&task_id={TASK}&agent=mock&strategy=single&status=completed"
        )
    ).json()
    second = (await client.get("/api/v1/runs?limit=1&offset=1")).json()
    assert first["items"][0]["run_id"] == ids[1]
    assert second["items"][0]["run_id"] == ids[0]
    assert (await client.get("/api/v1/runs?agent=unsupported")).json()["items"] == []
    for query in ("limit=101", "offset=-1", "status=imaginary"):
        assert (await client.get(f"/api/v1/runs?{query}")).status_code == 422


async def test_failed_run_and_verification_failure(api):
    client, service, _ = api
    limited = await submit(client, configuration={"max_tool_calls": 1})
    assert (await poll(client, limited))["status"] == "failed"
    original = service._factory

    def baseline(limits):
        harness = original(limits)
        original_run = harness.run

        async def run(task_id, agent, **kwargs):
            return await original_run(task_id, MockCodingAgent(), **kwargs)

        harness.run = run
        return harness

    service._factory = baseline
    run_id = await submit(client)
    run = await poll(client, run_id)
    assert run["status"] == "verification_failed"
    assert run["verification"]["failed_tests"] == 3
    trace = (await client.get(f"/api/v1/runs/{run_id}/trace")).text
    assert "test_official" not in trace and "AssertionError" not in trace


async def test_concurrency_cap_queued_state_and_live_verification(api):
    client, service, _ = api
    release = asyncio.Event()
    original = service._factory

    def blocked(limits):
        harness = original(limits)
        verify = harness.verifier.verify

        async def blocked_verify(task, workspace):
            await release.wait()
            return await verify(task, workspace)

        harness.verifier.verify = blocked_verify
        return harness

    service._factory = blocked
    ids = [await submit(client) for _ in range(5)]
    for run_id in ids[:2]:
        await poll(client, run_id, ("verifying",))
    assert [service.jobs.rows[i]["status"] for i in ids] == [
        "verifying",
        "verifying",
        "queued",
        "queued",
        "queued",
    ]
    live = (await client.get(f"/api/v1/runs/{ids[0]}/trace")).json()["events"]
    assert live[-1]["event_type"] == "verification_started"
    assert (await client.get(f"/api/v1/runs/{ids[2]}/metrics")).json() is None
    assert (await client.get(f"/api/v1/runs/{ids[2]}/patch")).status_code == 404
    release.set()
    for run_id in ids:
        assert (await poll(client, run_id))["status"] == "completed"


async def test_artifact_hash_missing_and_path_protection(api, tmp_path):
    client, service, _ = api
    run_id = await submit(client)
    await poll(client, run_id)
    record = service.repository.get(run_id)
    artifact = next(a for a in record.artifacts if a.artifact_type == "patch")
    path = Path(artifact.path)
    await asyncio.to_thread(path.write_text, "tampered")
    assert (await client.get(f"/api/v1/runs/{run_id}/patch")).status_code == 409
    await asyncio.to_thread(path.unlink)
    assert (await client.get(f"/api/v1/runs/{run_id}/patch")).status_code == 404
    await asyncio.to_thread(path.symlink_to, tmp_path / "outside")
    assert (await client.get(f"/api/v1/runs/{run_id}/patch")).status_code == 404
    evil = artifact.model_copy(update={"path": "/etc/passwd"})
    service.repository.runs[run_id] = record.model_copy(update={"artifacts": (evil,)})
    assert (await client.get(f"/api/v1/runs/{run_id}/patch")).status_code == 404
    assert (await client.get("/api/v1/runs/..%2Fetc%2Fpasswd/patch")).status_code in (404, 422)


async def test_health_errors_request_bounds_and_openapi(api):
    client, service, _ = api
    assert (await client.get("/health")).json() == {"status": "alive"}
    assert (await client.get("/ready")).status_code == 200
    for suffix in ("", "/trace", "/patch", "/metrics", "/artifacts"):
        response = await client.get(f"/api/v1/runs/missing{suffix}")
        assert response.status_code == 404 and response.json()["error"]["code"] == "run_not_found"
    large = await client.post("/api/v1/runs", content=b"x" * 17000)
    assert large.status_code == 413

    async def chunks():
        for _ in range(3):
            yield b"x" * 6000

    assert (await client.post("/api/v1/runs", content=chunks())).status_code == 413
    assert (await client.post("/api/v1/runs", content=b"{broken")).status_code == 422
    schema = (await client.get("/openapi.json")).json()
    assert schema["paths"]["/api/v1/runs"]["post"]["responses"]["202"]
    assert "RunDetail" in schema["components"]["schemas"]
    assert "VerificationSpec" not in schema["components"]["schemas"]
    assert (await client.get("/docs")).status_code == 200
    service.jobs.healthy = False
    assert (await client.get("/ready")).status_code == 503
    assert (await client.get("/health")).status_code == 200
    response = await client.post("/api/v1/runs", json={"task_id": TASK})
    assert response.status_code == 503 and "secret-password" not in response.text


async def test_worker_exception_and_database_finalization_failure(api):
    client, service, _ = api
    original = service._factory

    def crash(limits):
        raise RuntimeError("secret-password /private/host")

    service._factory = crash
    run_id = await submit(client)
    failed = await poll(client, run_id)
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "run_execution_failure"
    assert "secret-password" not in str(failed)
    service._factory = original

    def fail_save(run):
        raise ConnectionError("secret-password")

    service.repository.save = fail_save
    run_id = await submit(client)
    assert (await poll(client, run_id))["status"] == "failed"
    assert service.jobs.get(run_id)["failure_reason"] == "run persistence failed"


async def test_graceful_shutdown_cleans_active_execution_and_admission_cap(api):
    client, service, runtime = api
    service.settings = service.settings.model_copy(
        update={"shutdown_grace_seconds": 0.01, "max_pending_runs": 2}
    )
    original = service._factory
    blocked = asyncio.Event()

    def factory(limits):
        harness = original(limits)

        async def wait_forever(task, workspace):
            await blocked.wait()

        harness.verifier.verify = wait_forever
        return harness

    service._factory = factory
    ids = [await submit(client), await submit(client)]
    for run_id in ids:
        await poll(client, run_id, ("verifying",))
    response = await client.post("/api/v1/runs", json={"task_id": TASK})
    assert response.status_code == 503 and "full" in response.text
    await service.close()
    for run_id in ids:
        assert service.repository.get(run_id).summary["status"] == "failed"
        assert service.repository.get(run_id).events[-1].event_type == "run_failed"
    assert not runtime.workspaces


def test_configuration_and_verifier_error_redaction():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///file")
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://user@localhost/db", max_concurrent_runs=0)
    event = public_event(
        dict(
            event_id="r:1",
            run_id="r",
            sequence_number=1,
            timestamp=datetime.now(UTC),
            event_type="run_failed",
            duration_ms=1,
            failure_reason="secret-password at /private/path",
        )
    )
    assert "secret-password" not in event.model_dump_json()


async def test_provider_discovery_unavailable_and_model_validation(api, monkeypatch):
    from app.providers.models import ProviderAvailability

    client, service, _ = api

    async def probe(provider, **kwargs):
        return ProviderAvailability(
            id=provider.value,
            available=False,
            version="test-version",
            reason="authentication_unavailable",
        )

    monkeypatch.setattr(service.providers, "probe", probe)
    listing = (await client.get("/api/v1/agents")).json()
    assert listing[0]["id"] == "mock" and listing[0]["available"]
    assert listing[1]["id"] == "codex" and not listing[1]["available"]
    unavailable = await client.post("/api/v1/runs", json={"task_id": TASK, "agent": "codex"})
    assert (
        unavailable.status_code == 503
        and unavailable.json()["error"]["code"] == "agent_unavailable"
    )
    unavailable_role = await client.post(
        "/api/v1/runs",
        json={
            "task_id": TASK,
            "strategy": "planner_implementer_reviewer",
            "configuration": {"planner": {"agent": "codex"}},
        },
    )
    assert (
        unavailable_role.status_code == 503
        and unavailable_role.json()["error"]["code"] == "agent_unavailable"
    )
    for model in ("--unsafe-flags", "bad model", "x" * 129):
        response = await client.post(
            "/api/v1/runs",
            json={
                "task_id": TASK,
                "agent": "codex",
                "configuration": {"model": model},
            },
        )
        assert response.status_code == 422
    response = await client.post(
        "/api/v1/runs",
        json={
            "task_id": TASK,
            "configuration": {"model": "a-model"},
        },
    )
    assert response.status_code == 422


def test_provider_auth_diagnostics_are_not_public():
    event = public_event(
        dict(
            event_id="r:1",
            run_id="r",
            sequence_number=1,
            timestamp=datetime.now(UTC),
            event_type="provider_process_failed",
            provider="claude-code",
            native_type="result",
            payload={
                "error_code": "authentication_unavailable",
                "diagnostic": "private-auth-detail",
            },
        )
    )
    assert "private-auth-detail" not in event.model_dump_json()
