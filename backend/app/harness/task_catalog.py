"""Filesystem-backed discovery and validation of benchmark manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.models.task import RepositoryType, Task, TaskSource


class TaskCatalogError(ValueError):
    """A benchmark catalog is malformed, ambiguous, or unsafe."""


class TaskCatalog:
    """Load task manifests and resolve local repositories under one root."""

    def __init__(self, benchmark_root: Path | str, *, validate_hashes: bool = True) -> None:
        self.root = Path(benchmark_root).expanduser().resolve()
        self.tasks_root = self.root / "tasks"
        self.validate_hashes = validate_hashes

    def list_tasks(self) -> list[Task]:
        if not self.tasks_root.is_dir():
            raise TaskCatalogError(f"task directory does not exist: {self.tasks_root}")

        tasks: dict[str, Task] = {}
        for manifest_path in sorted(self.tasks_root.glob("*/task.yaml")):
            task = self._load_manifest(manifest_path)
            if task.id in tasks:
                raise TaskCatalogError(f"duplicate task id: {task.id}")
            if self.validate_hashes:
                self._validate_frozen_content(task)
            tasks[task.id] = task
        return [tasks[task_id] for task_id in sorted(tasks)]

    def get(self, task_id: str) -> Task:
        for task in self.list_tasks():
            if task.id == task_id:
                return task
        raise KeyError(f"unknown task id: {task_id}")

    def resolve_repository(self, task: Task) -> Path:
        """Resolve a local source while preventing catalog path traversal."""

        if task.repository.type is not RepositoryType.LOCAL:
            raise TaskCatalogError(
                "git repository materialization is deferred; only local sources "
                "are supported in Phase 3"
            )

        source_path = Path(task.repository.source)
        if source_path.is_absolute():
            raise TaskCatalogError("local repository source must be relative to benchmark root")

        resolved = (self.root / source_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise TaskCatalogError("local repository escapes benchmark root") from exc

        if task.repository.subdirectory:
            resolved = (resolved / task.repository.subdirectory).resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise TaskCatalogError("repository subdirectory escapes benchmark root") from exc

        if not resolved.is_dir():
            raise TaskCatalogError(f"local repository does not exist: {resolved}")
        if task.verification is not None:
            hidden = self.resolve_verification(task)
            if hidden.is_relative_to(resolved) or resolved.is_relative_to(hidden):
                raise TaskCatalogError("agent repository and verification source must be disjoint")
            for path in resolved.rglob("*"):
                if path.is_symlink():
                    raise TaskCatalogError("agent source must not contain symlinks")
        return resolved

    def resolve_verification(self, task: Task) -> Path:
        if task.verification is None:
            raise TaskCatalogError("task has no official verification specification")
        source = Path(task.verification.source)
        resolved = (self.root / source).resolve()
        if source.is_absolute() or not resolved.is_relative_to(self.root):
            raise TaskCatalogError("verification source escapes benchmark root")
        if not resolved.is_dir():
            raise TaskCatalogError("verification source does not exist")
        if any(path.is_symlink() for path in resolved.rglob("*")):
            raise TaskCatalogError("verification source must not contain symlinks")
        return resolved

    @staticmethod
    def _load_manifest(path: Path) -> Task:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise TaskCatalogError(f"could not read task manifest {path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise TaskCatalogError(f"task manifest must contain a mapping: {path}")
        try:
            return Task.model_validate(raw)
        except ValidationError as exc:
            raise TaskCatalogError(f"invalid task manifest {path}: {exc}") from exc

    def _validate_frozen_content(self, task: Task) -> None:
        provenance = task.provenance
        hashes = (provenance.task_hash, provenance.environment_hash, provenance.verifier_hash)
        if not any(hashes):
            return
        if not all(hashes):
            raise TaskCatalogError(f"task is not frozen with content hashes: {task.id}")
        repository = self.resolve_repository(task)
        verification = self.resolve_verification(task)
        environment_hash = _source_digest(repository)
        verifier_hash = _source_digest(verification)
        if environment_hash != provenance.environment_hash:
            raise TaskCatalogError(f"environment hash mismatch for frozen task: {task.id}")
        if verifier_hash != provenance.verifier_hash:
            raise TaskCatalogError(f"verifier hash mismatch for frozen task: {task.id}")
        if provenance.source is TaskSource.HARBOR:
            expected = _source_digest(verification.parent)
        else:
            expected = hashlib.sha256(
                json.dumps(
                    [task.id, task.version, environment_hash, verifier_hash],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        if expected != provenance.task_hash:
            raise TaskCatalogError(f"task hash mismatch for frozen task: {task.id}")


def _source_digest(root: Path) -> str:
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ignored.intersection(relative.parts):
            continue
        if path.is_symlink():
            raise TaskCatalogError("frozen task trees must not contain symbolic links")
        if path.is_file():
            entries.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
