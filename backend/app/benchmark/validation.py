"""Deterministic baseline/reference validation for frozen benchmark tasks."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.models import VerificationResult
from app.evaluation.verifier import AdaptiveBenchmarkVerifier, source_digest
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory, WorkspaceFactory
from app.models.task import Task, TaskSource


class TaskValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    valid: bool
    baseline_passed: bool | None = None
    reference_passed: bool | None = None
    deterministic: bool | None = None
    isolation_passed: bool = False
    errors: list[str] = Field(default_factory=list)


class BenchmarkValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str
    results: list[TaskValidation]

    @property
    def valid(self) -> bool:
        return bool(self.results) and all(result.valid for result in self.results)


@dataclass
class BenchmarkValidator:
    catalog: TaskCatalog
    factory: WorkspaceFactory

    async def validate(
        self,
        *,
        include_external: bool = False,
        repeat_count: int = 2,
        task_ids: set[str] | None = None,
    ) -> BenchmarkValidationReport:
        if repeat_count < 2:
            raise ValueError("determinism validation requires at least two repetitions")
        tasks = self.catalog.list_tasks()
        if not include_external:
            tasks = [task for task in tasks if task.provenance.source is TaskSource.AGENTSCOPE]
        if task_ids is not None:
            tasks = [task for task in tasks if task.id in task_ids]
            missing = task_ids - {task.id for task in tasks}
            if missing:
                raise ValueError(f"unknown or excluded task IDs: {', '.join(sorted(missing))}")
        results = [await self._task(task, repeat_count) for task in tasks]
        return BenchmarkValidationReport(suite="AgentScope Benchmark v0.1", results=results)

    async def _task(self, task: Task, repeat_count: int) -> TaskValidation:
        result = TaskValidation(task_id=task.id, valid=False)
        try:
            repository = self.catalog.resolve_repository(task)
            hidden = self.catalog.resolve_verification(task)
            reference = self.catalog.root / "reference" / task.id
            if not reference.is_dir() and task.provenance.source is TaskSource.AGENTSCOPE:
                raise ValueError("reference solution is missing")
            visible_names = {part.lower() for path in repository.rglob("*") for part in path.parts}
            if "solution" in visible_names or "verification" in visible_names:
                raise ValueError("agent repository contains reserved hidden material")
            if hidden.is_relative_to(repository) or reference.is_relative_to(repository):
                raise ValueError("hidden material overlaps the agent repository")
            result.isolation_passed = True
            if task.provenance.environment_hash != source_digest(repository):
                raise ValueError("environment hash does not match frozen content")
            if task.provenance.verifier_hash != source_digest(hidden):
                raise ValueError("verifier hash does not match frozen content")

            baseline = await self._verify_copy(task, repository)
            result.baseline_passed = baseline.passed
            if baseline.passed:
                raise ValueError("baseline unexpectedly passes")
            references = [
                await self._verify_reference(task, repository, reference)
                for _ in range(repeat_count)
            ]
            result.reference_passed = all(item.passed for item in references)
            if not result.reference_passed:
                failed = next(item for item in references if not item.passed)
                detail = " | ".join(
                    value
                    for value in (
                        failed.failure_reason,
                        failed.stderr[-500:].strip(),
                        failed.stdout[-500:].strip(),
                    )
                    if value
                )
                raise ValueError(f"reference solution fails: {detail}")
            signatures = {
                (item.passed, item.passed_tests, item.failed_tests, item.total_tests)
                for item in references
            }
            result.deterministic = len(signatures) == 1
            if not result.deterministic:
                raise ValueError("official verifier is nondeterministic")
            result.valid = True
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        return result

    def _factory(self, task: Task) -> WorkspaceFactory:
        if task.environment.image and isinstance(self.factory, DockerWorkspaceFactory):
            return replace(self.factory, image=task.environment.image)
        return self.factory

    async def _verify_copy(self, task: Task, source: Path) -> VerificationResult:
        factory = self._factory(task)
        workspace = await factory.create(
            source, run_id=f"validate-{uuid.uuid4().hex}", keep_workspace=False
        )
        try:
            verifier = AdaptiveBenchmarkVerifier(self.catalog, factory)
            return await verifier.verify(task, workspace)
        finally:
            await workspace.close()

    async def _verify_reference(
        self, task: Task, repository: Path, reference: Path
    ) -> VerificationResult:
        staging = Path(tempfile.mkdtemp(prefix="agentscope-reference-"))
        try:
            source = staging / "source"
            shutil.copytree(repository, source)
            if task.provenance.source is TaskSource.AGENTSCOPE:
                self._overlay(reference, source)
            else:
                package = self.catalog.resolve_verification(task).parent
                solution = package / "solution"
                if not solution.is_dir():
                    raise ValueError("Harbor reference solution is missing")
                shutil.copytree(solution, source / ".agentscope-solution")
            factory = self._factory(task)
            workspace = await factory.create(
                source, run_id=f"reference-{uuid.uuid4().hex}", keep_workspace=False
            )
            try:
                if task.provenance.source is not TaskSource.AGENTSCOPE:
                    solve = source / ".agentscope-solution" / "solve.sh"
                    if not solve.is_file():
                        raise ValueError("unsupported Harbor solution entrypoint")
                    execution = await workspace.execute(
                        ("bash", ".agentscope-solution/solve.sh"),
                        timeout_seconds=task.verification.timeout_seconds
                        if task.verification
                        else 600,
                    )
                    if execution.exit_code != 0:
                        raise ValueError("Harbor reference solution script failed")
                    shutil.rmtree(workspace.host_path / ".agentscope-solution")
                verifier = AdaptiveBenchmarkVerifier(self.catalog, factory)
                return await verifier.verify(task, workspace)
            finally:
                await workspace.close()
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _overlay(reference: Path, target: Path) -> None:
        for source in sorted(reference.rglob("*")):
            if source.is_symlink():
                raise ValueError("reference solution contains a symlink")
            relative = source.relative_to(reference)
            destination = target / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
