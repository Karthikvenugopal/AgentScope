"""Bounded, single-process workers backed by a PostgreSQL submission ledger."""

import asyncio
import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from app.agents import CodingAgent, MockCodingAgent
from app.agents.external import ClaudeCodeAgent, CodexAgent
from app.config import Settings
from app.experiments.analysis import analyze
from app.experiments.models import ExperimentSpec
from app.experiments.repository import ExperimentRepository
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.providers.models import ProviderAvailability, ProviderName
from app.providers.runtime import ProviderRuntime
from app.services.errors import ServiceError
from app.services.logging import log
from app.storage.jobs import JobStore, QueueFullError
from app.storage.repository import PostgresRunRepository, StoredRun
from app.strategies.models import StrategyConfiguration, StrategyName
from app.telemetry.events import AnyTraceEvent


class RunService:
    def __init__(
        self,
        settings: Settings,
        repository: PostgresRunRepository,
        *,
        harness_factory: Callable[[RunLimits], SingleAgentHarness] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.experiments = ExperimentRepository(repository.engine)
        self.jobs = JobStore(repository.engine)
        self.catalog = TaskCatalog(settings.benchmark_root)
        self._factory = harness_factory or self._harness
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._lease_lock = asyncio.Lock()
        self.providers = ProviderRuntime(
            image=settings.provider_image,
            codex_auth_file=settings.codex_auth_file,
            claude_auth_file=settings.claude_auth_file,
        )

    def _harness(self, limits: RunLimits) -> SingleAgentHarness:
        return SingleAgentHarness(
            catalog=self.catalog,
            workspace_factory=DockerWorkspaceFactory(image=self.settings.runner_image),
            artifact_store=ArtifactStore(self.settings.artifact_root),
            repository=self.repository,
            limits=limits,
            provider_runtime=self.providers,
        )

    async def start(self) -> None:
        await asyncio.to_thread(self.catalog.list_tasks)
        await asyncio.to_thread(self.jobs.ping)
        await asyncio.to_thread(self.jobs.acquire)
        try:
            await asyncio.to_thread(self.jobs.recover)
            self._workers = [
                asyncio.create_task(self._worker())
                for _ in range(self.settings.max_concurrent_runs)
            ]
        except BaseException:
            await asyncio.to_thread(self.jobs.release)
            raise
        log("api_started", concurrency=self.settings.max_concurrent_runs)

    async def ready(self) -> bool:
        try:
            await asyncio.to_thread(self.jobs.ping)
            async with self._lease_lock:
                try:
                    await asyncio.to_thread(self.jobs.check_lease)
                except Exception:
                    self._stopping.set()
                    raise
            return (
                bool(self._workers)
                and all(not w.done() for w in self._workers)
                and not self._stopping.is_set()
            )
        except Exception:
            return False

    async def database_ready(self) -> bool:
        try:
            await asyncio.to_thread(self.jobs.ping)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        self._stopping.set()
        if self._workers:
            _, pending = await asyncio.wait(
                self._workers, timeout=self.settings.shutdown_grace_seconds
            )
            for worker in pending:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
        try:
            await asyncio.to_thread(self.jobs.release)
        finally:
            await asyncio.to_thread(self.repository.engine.dispose)
        log("api_stopped")

    async def agents(self) -> list[ProviderAvailability]:
        return [
            ProviderAvailability(id="mock", available=True),
            *await asyncio.gather(*(self.providers.probe(p) for p in ProviderName)),
        ]

    async def submit(
        self,
        task_id: str,
        agent: str,
        strategy: str,
        limits: RunLimits,
        model: str | None = None,
        roles: StrategyConfiguration | None = None,
    ) -> str:
        if agent not in ("mock", "codex", "claude-code"):
            raise ServiceError("unsupported_agent", "Unsupported coding agent", 422)
        if agent == "mock" and model is not None:
            raise ServiceError("invalid_configuration", "Mock does not accept a model", 422)
        if strategy not in ("single", "planner_implementer_reviewer", "parallel_implementers"):
            raise ServiceError("unsupported_strategy", "Unsupported strategy", 422)
        if strategy == "single" and roles is not None:
            raise ServiceError(
                "invalid_configuration", "Single strategy does not accept role configuration", 422
            )
        if strategy != "single":
            if model is not None:
                raise ServiceError("invalid_configuration", "Configure models per role", 422)
            roles = roles or StrategyConfiguration()
            if (
                roles.implementers.count > self.settings.max_parallel_implementers
                and strategy == "parallel_implementers"
            ):
                raise ServiceError(
                    "invalid_configuration", "Worker count exceeds configured maximum", 422
                )
            selected_roles = [
                roles.planner,
                roles.reviewer,
                roles.implementers if strategy == "parallel_implementers" else roles.implementer,
            ]
            for role in selected_roles:
                if role.agent == "mock" and role.model is not None:
                    raise ServiceError("invalid_configuration", "Mock does not accept a model", 422)
                if (
                    role.agent != "mock"
                    and not (await self.providers.probe(ProviderName(role.agent))).available
                ):
                    raise ServiceError("agent_unavailable", "A role provider is unavailable", 503)
        await self.task(task_id)
        if agent != "mock" and strategy == "single":
            availability = await self.providers.probe(ProviderName(agent))
            if not availability.available:
                raise ServiceError(
                    "agent_unavailable", "Provider runtime or authentication is unavailable", 503
                )
        if not await self.ready():
            raise ServiceError("service_unavailable", "Execution service is unavailable", 503)
        run_id = uuid.uuid4().hex
        try:
            await asyncio.to_thread(
                self.jobs.submit,
                run_id,
                task_id,
                {
                    **limits.model_dump(mode="json"),
                    **({"model": model} if model else {}),
                    **({"roles": roles.model_dump(mode="json")} if roles else {}),
                },
                self.settings.max_pending_runs,
                agent_name=agent,
                strategy=strategy,
            )
        except QueueFullError:
            raise ServiceError("service_unavailable", "Run queue is full", 503) from None
        log("run_submitted", run_id=run_id)
        return run_id

    async def task(self, task_id: str) -> dict[str, Any]:
        try:
            task = await asyncio.to_thread(self.catalog.get, task_id)
        except KeyError:
            raise ServiceError("task_not_found", "Task was not found", 404) from None
        # Explicit allowlist: never serialize VerificationSpec.
        return {
            k: v
            for k, v in task.model_dump(mode="json").items()
            if k
            in {
                "id",
                "title",
                "description",
                "repository",
                "test_command",
                "setup_command",
                "timeout_seconds",
                "expected_behavior",
                "version",
                "tags",
                "language",
                "difficulty",
            }
        } | {
            "source": task.provenance.source.value,
            "dataset": task.provenance.dataset,
            "dataset_version": task.provenance.dataset_version,
            "task_hash": task.provenance.task_hash,
        }

    async def tasks(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        tasks = await asyncio.to_thread(self.catalog.list_tasks)
        filters = filters or {}
        tasks = [
            task
            for task in tasks
            if all(
                {
                    "source": task.provenance.source.value,
                    "dataset": task.provenance.dataset,
                    "language": task.language,
                    "difficulty": task.difficulty.value,
                }.get(key, "").lower()
                == value.lower()
                if key != "tag"
                else value.lower() in {tag.lower() for tag in task.tags}
                for key, value in filters.items()
            )
        ]
        # Keep the long-standing smoke task first while the rest remain catalog ordered.
        tasks.sort(key=lambda task: (task.id != "incorrect_api_response", task.id))
        return [
            dict(
                id=t.id,
                title=t.title,
                description=t.description,
                version=t.version,
                tags=t.tags,
                language=t.language,
                difficulty=t.difficulty.value,
                source=t.provenance.source.value,
                dataset=t.provenance.dataset,
                dataset_version=t.provenance.dataset_version,
                task_hash=t.provenance.task_hash,
            )
            for t in tasks
        ]

    async def experiment_list(self) -> list[dict[str, Any]]:
        records = await asyncio.to_thread(self.experiments.list_experiments)
        return [
            {
                key: record[key]
                for key in (
                    "experiment_id",
                    "name",
                    "status",
                    "benchmark_name",
                    "benchmark_version",
                    "spec_hash",
                    "created_at",
                    "progress",
                )
            }
            for record in records
        ]

    async def experiment(self, experiment_id: str) -> dict[str, Any]:
        record = await asyncio.to_thread(self.experiments.get, experiment_id)
        if record is None:
            raise ServiceError("experiment_not_found", "Experiment was not found", 404)
        spec = ExperimentSpec.model_validate(record["spec"])
        raw = await asyncio.to_thread(self.experiments.raw_runs, experiment_id)
        statistics = await asyncio.to_thread(analyze, raw, bootstrap_seed=spec.bootstrap_seed)
        return {
            key: record[key]
            for key in (
                "experiment_id",
                "name",
                "research_question",
                "status",
                "benchmark_name",
                "benchmark_version",
                "benchmark_manifest_hash",
                "spec_hash",
                "created_at",
                "started_at",
                "finished_at",
                "pause_reason",
                "provenance",
                "progress",
                "configurations",
                "schedule",
                "attempts",
            )
        } | {"analysis": statistics}

    async def _worker(self) -> None:
        while not self._stopping.is_set():
            try:
                async with self._lease_lock:
                    await asyncio.to_thread(self.jobs.check_lease)
                claim = asyncio.create_task(asyncio.to_thread(self.jobs.claim))
                try:
                    job = await asyncio.shield(claim)
                except asyncio.CancelledError:
                    # A thread may already have committed the claim.
                    job = await claim
                    if job is not None:
                        await asyncio.to_thread(
                            self.jobs.fail, job["run_id"], "service shutdown before execution"
                        )
                    return
                if job is not None:
                    if self._stopping.is_set():
                        await asyncio.to_thread(
                            self.jobs.fail, job["run_id"], "service shutdown before execution"
                        )
                        return
                    await self._execute(job)
                    continue
            except asyncio.CancelledError:
                return
            except Exception:
                # Stop admission and further claims if ownership/storage is lost.
                log("persistence_failure")
                self._stopping.set()
                return
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=0.25)
            except TimeoutError:
                pass

    async def _execute(self, job: dict[str, Any]) -> None:
        run_id: str = job["run_id"]
        log("run_started", run_id=run_id)

        async def observe(event: AnyTraceEvent) -> None:
            # Finalization may replace the last terminal event after export/storage
            # errors. Publish that event only from the committed final trace.
            if event.event_type in ("run_completed", "run_failed", "run_timed_out"):
                return
            await asyncio.to_thread(self.jobs.event, event)

        try:
            configuration = dict(job["configuration"])
            model = configuration.pop("model", None)
            roles = configuration.pop("roles", None)
            harness = self._factory(RunLimits.model_validate(configuration))
            agent: CodingAgent
            if job["agent_name"] == "codex":
                agent = CodexAgent(model)
            elif job["agent_name"] == "claude-code":
                agent = ClaudeCodeAgent(model)
            else:
                agent = MockCodingAgent.for_incorrect_api_response()
            result = await harness.run(
                job["task_id"],
                agent,
                run_id=run_id,
                event_observer=observe,
                strategy=cast(StrategyName, job["strategy"]),
                strategy_configuration=StrategyConfiguration.model_validate(roles)
                if roles
                else None,
            )
            if result.persistence_error:
                log("persistence_failure", run_id=run_id)
                await asyncio.to_thread(self.jobs.fail, run_id, "run persistence failed")
            else:
                await asyncio.to_thread(
                    self.jobs.finish, run_id, result.status.value, result.failure_reason
                )
            if result.verification:
                log("verification_result", run_id=run_id, passed=result.verification.passed)
            if result.failure_reason == "run cancelled":
                log("cancellation", run_id=run_id)
            log(
                "run_completed" if result.status.value == "completed" else "run_failed",
                run_id=run_id,
            )
        except asyncio.CancelledError:
            log("cancellation", run_id=run_id)
            await asyncio.to_thread(
                self.jobs.fail, run_id, "service shutdown interrupted execution"
            )
        except Exception:
            log("run_execution_failure", run_id=run_id)
            await asyncio.to_thread(self.jobs.fail, run_id, "run execution failed")

    async def get(self, run_id: str) -> StoredRun | dict[str, Any]:
        stored = await asyncio.to_thread(self.repository.get, run_id)
        if stored is not None:
            return stored
        job = await asyncio.to_thread(self.jobs.get, run_id)
        if job is None:
            raise ServiceError("run_not_found", "Run was not found", 404)
        return job

    async def listing(
        self, limit: int, offset: int, filters: dict[str, str]
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.jobs.listing, limit, offset, filters)

    async def trace(self, run_id: str, after: int, limit: int) -> list[dict[str, Any]]:
        await self.get(run_id)
        return await asyncio.to_thread(self.jobs.trace, run_id, after, limit)

    async def patch(self, run_id: str) -> str:
        run = await self.get(run_id)
        if not isinstance(run, StoredRun):
            raise ServiceError("artifact_not_found", "Patch is not available", 404)
        artifact = next((a for a in run.artifacts if a.artifact_type == "patch"), None)
        if artifact is None:
            raise ServiceError("artifact_not_found", "Patch is not available", 404)

        def read() -> str:
            root = self.settings.artifact_root.resolve()
            path = Path(artifact.path)
            expected = root / "runs" / run_id / "patch.diff"
            # A DB record cannot grant arbitrary host filesystem access.
            if path != expected or any(p.is_symlink() for p in (path, *path.parents)):
                raise ServiceError("artifact_not_found", "Patch is not available", 404)
            try:
                if not path.resolve().is_relative_to(root):
                    raise OSError
                with path.open("rb") as handle:
                    data = handle.read(min(artifact.size_bytes + 1, 20_000_001))
            except OSError:
                raise ServiceError("artifact_not_found", "Patch is not available", 404) from None
            if (
                len(data) > 20_000_000
                or len(data) != artifact.size_bytes
                or hashlib.sha256(data).hexdigest() != artifact.sha256
            ):
                raise ServiceError(
                    "artifact_integrity_failure", "Patch integrity check failed", 409
                )
            try:
                return data.decode("utf-8")
            except UnicodeError:
                raise ServiceError(
                    "artifact_integrity_failure", "Patch encoding is invalid", 409
                ) from None

        return await asyncio.to_thread(read)
