from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import write_manifest

from app.harness.task_catalog import TaskCatalog, TaskCatalogError
from app.models.task import Task


def _with_id(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    return {**data, "id": task_id, "title": task_id}


def test_catalog_lists_tasks_in_stable_id_order(tmp_path: Path, task_data: dict[str, Any]) -> None:
    write_manifest(tmp_path, "z-directory", _with_id(task_data, "alpha"))
    write_manifest(tmp_path, "a-directory", _with_id(task_data, "zeta"))

    tasks = TaskCatalog(tmp_path).list_tasks()

    assert [task.id for task in tasks] == ["alpha", "zeta"]


def test_catalog_get_returns_typed_task(tmp_path: Path, task_data: dict[str, Any]) -> None:
    write_manifest(tmp_path, "fix_api", task_data)

    task = TaskCatalog(tmp_path).get("fix_api")

    assert isinstance(task, Task)


def test_catalog_get_rejects_unknown_id(tmp_path: Path, task_data: dict[str, Any]) -> None:
    write_manifest(tmp_path, "fix_api", task_data)

    with pytest.raises(KeyError, match="unknown task id"):
        TaskCatalog(tmp_path).get("missing")


def test_catalog_reports_invalid_yaml(tmp_path: Path) -> None:
    manifest = tmp_path / "tasks" / "bad" / "task.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("id: [unterminated", encoding="utf-8")

    with pytest.raises(TaskCatalogError, match="could not read"):
        TaskCatalog(tmp_path).list_tasks()


def test_catalog_rejects_duplicate_task_ids(tmp_path: Path, task_data: dict[str, Any]) -> None:
    write_manifest(tmp_path, "one", task_data)
    write_manifest(tmp_path, "two", task_data)

    with pytest.raises(TaskCatalogError, match="duplicate task id"):
        TaskCatalog(tmp_path).list_tasks()


def test_catalog_resolves_local_repository(tmp_path: Path, task_data: dict[str, Any]) -> None:
    repository = tmp_path / "fixtures" / "fix_api"
    repository.mkdir(parents=True)
    write_manifest(tmp_path, "fix_api", task_data)
    catalog = TaskCatalog(tmp_path)

    resolved = catalog.resolve_repository(catalog.get("fix_api"))

    assert resolved == repository.resolve()


def test_catalog_rejects_repository_traversal(tmp_path: Path, task_data: dict[str, Any]) -> None:
    task_data["repository"] = {"type": "local", "source": "../outside"}
    task = Task.model_validate(task_data)

    with pytest.raises(TaskCatalogError, match="escapes benchmark root"):
        TaskCatalog(tmp_path).resolve_repository(task)


def test_catalog_rejects_absolute_local_repository(
    tmp_path: Path, task_data: dict[str, Any]
) -> None:
    task_data["repository"] = {"type": "local", "source": str(tmp_path)}
    task = Task.model_validate(task_data)

    with pytest.raises(TaskCatalogError, match="must be relative"):
        TaskCatalog(tmp_path).resolve_repository(task)


def test_catalog_explicitly_defers_git_materialization(
    tmp_path: Path, task_data: dict[str, Any]
) -> None:
    task_data["repository"] = "https://example.test/repository.git"
    task = Task.model_validate(task_data)

    with pytest.raises(TaskCatalogError, match="deferred"):
        TaskCatalog(tmp_path).resolve_repository(task)


def test_checked_in_sample_manifest_and_repository_are_valid() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    catalog = TaskCatalog(repository_root / "benchmarks")

    task = catalog.get("incorrect_api_response")

    assert task.test_command == "python -m pytest -q"
    assert (catalog.resolve_repository(task) / "app.py").is_file()
