from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.task import RepositoryType, Task


def test_task_accepts_complete_manifest(task_data: dict[str, Any]) -> None:
    task = Task.model_validate(task_data)

    assert task.id == "fix_api"
    assert task.version == "1"
    assert task.repository.type is RepositoryType.LOCAL


def test_string_repository_is_normalized_as_local(task_data: dict[str, Any]) -> None:
    task_data["repository"] = "fixtures/fix_api"

    task = Task.model_validate(task_data)

    assert task.repository.source == "fixtures/fix_api"
    assert task.repository.type is RepositoryType.LOCAL


@pytest.mark.parametrize("source", ["https://example.test/repo.git", "git@example.test:r.git"])
def test_remote_string_repository_is_normalized_as_git(
    task_data: dict[str, Any], source: str
) -> None:
    task_data["repository"] = source

    task = Task.model_validate(task_data)

    assert task.repository.type is RepositoryType.GIT


@pytest.mark.parametrize("task_id", ["UPPERCASE", "spaces are bad", "../escape", ""])
def test_task_id_rejects_unsafe_values(task_data: dict[str, Any], task_id: str) -> None:
    task_data["id"] = task_id

    with pytest.raises(ValidationError):
        Task.model_validate(task_data)


def test_unknown_fields_are_rejected(task_data: dict[str, Any]) -> None:
    task_data["typo_timeout"] = 20

    with pytest.raises(ValidationError, match="typo_timeout"):
        Task.model_validate(task_data)


@pytest.mark.parametrize("timeout", [0, -1, 86_401])
def test_timeout_has_explicit_bounds(task_data: dict[str, Any], timeout: int) -> None:
    task_data["timeout_seconds"] = timeout

    with pytest.raises(ValidationError):
        Task.model_validate(task_data)


def test_blank_setup_command_becomes_none(task_data: dict[str, Any]) -> None:
    task_data["setup_command"] = "  "

    assert Task.model_validate(task_data).setup_command is None


@pytest.mark.parametrize("subdirectory", ["../secret", "/absolute", "nested/../../secret"])
def test_repository_subdirectory_must_be_safe(task_data: dict[str, Any], subdirectory: str) -> None:
    task_data["repository"]["subdirectory"] = subdirectory

    with pytest.raises(ValidationError, match="safe relative path"):
        Task.model_validate(task_data)


def test_duplicate_tags_are_rejected(task_data: dict[str, Any]) -> None:
    task_data["tags"] = ["api", "api"]

    with pytest.raises(ValidationError, match="unique"):
        Task.model_validate(task_data)
