import asyncio
from pathlib import Path

from conftest import IsolatedTestRuntime
from test_single_agent_harness import _harness

from app.agents import MockCodingAgent
from app.harness.artifacts import ArtifactStore
from app.models.run import ArtifactMetadata, RunResult, RunStatus


class MemoryRepository:
    def __init__(self) -> None:
        self.saved: list[RunResult] = []

    def save(self, run: RunResult) -> None:
        self.saved.append(run)

    def get(self, run_id: str):
        return None

    def list_runs(self, limit: int = 20):
        return []


class UnavailableRepository(MemoryRepository):
    def save(self, run: RunResult) -> None:
        raise ConnectionError("database unavailable")


class BrokenArtifacts(ArtifactStore):
    async def write(
        self, result: RunResult, *, replace: bool = False
    ) -> tuple[ArtifactMetadata, ...]:
        raise OSError("disk full")


async def test_artifact_failure_persists_terminal_failure(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(tmp_path, isolated_runtime)
    repository = MemoryRepository()
    harness.repository = repository
    harness.artifact_store = BrokenArtifacts(tmp_path / "artifacts")
    run = await harness.run("incorrect_api_response", MockCodingAgent.for_incorrect_api_response())
    assert run.status is RunStatus.FAILED
    assert run.verification and run.verification.passed
    assert run.failure_reason and "artifact export failed" in run.failure_reason
    assert repository.saved == [run]
    assert run.artifact_metadata == ()
    assert isolated_runtime.workspaces == {}


async def test_database_failure_keeps_verified_local_artifacts_but_reports_failure(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(tmp_path, isolated_runtime)
    harness.repository = UnavailableRepository()
    run = await harness.run("incorrect_api_response", MockCodingAgent.for_incorrect_api_response())
    assert run.status is RunStatus.FAILED and run.persistence_error
    assert run.verification and run.verification.passed
    assert len(run.artifact_metadata) == 3
    assert run.events[-1].event_type == "run_failed"
    assert not any(e.event_type == "run_completed" for e in run.events)
    assert isolated_runtime.workspaces == {}


async def test_cancellation_during_finalization_finishes_the_same_save(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class PausedArtifacts(ArtifactStore):
        async def write(
            self,
            result: RunResult,
            *,
            replace: bool = False,
        ) -> tuple[ArtifactMetadata, ...]:
            entered.set()
            await release.wait()
            return await super().write(result, replace=replace)

    harness = _harness(tmp_path, isolated_runtime)
    repository = MemoryRepository()
    harness.repository = repository
    harness.artifact_store = PausedArtifacts(tmp_path / "artifacts")
    task = asyncio.create_task(
        harness.run(
            "incorrect_api_response",
            MockCodingAgent.for_incorrect_api_response(),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=10)
    task.cancel()
    release.set()
    run = await task
    assert run.status is RunStatus.COMPLETED
    assert repository.saved == [run]
    assert len(run.artifact_metadata) == 3
