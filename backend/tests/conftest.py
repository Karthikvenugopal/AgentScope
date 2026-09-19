from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.execution.container import _run_process
from app.execution.results import CommandResult
from app.models.task import Task


@pytest.fixture
def task_data() -> dict[str, Any]:
    return {
        "id": "fix_api",
        "title": "Fix API",
        "description": "Correct the API response.",
        "repository": {"type": "local", "source": "fixtures/fix_api"},
        "setup_command": None,
        "test_command": "python -m pytest -q",
        "timeout_seconds": 120,
        "expected_behavior": "The endpoint returns the documented payload.",
    }


@pytest.fixture
def task(task_data: dict[str, Any]) -> Task:
    return Task.model_validate(task_data)


@pytest.fixture
def source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 'before'\n", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_text("data\n", encoding="utf-8")
    return source


def write_manifest(root: Path, directory: str, data: dict[str, Any]) -> Path:
    manifest = root / "tasks" / directory / "task.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return manifest


class IsolatedTestRuntime:
    """Test-only container protocol implementation using a temporary cwd."""

    def __init__(self) -> None:
        self.workspaces: dict[str, Path] = {}
        self.stop_calls: list[str] = []

    async def start(
        self,
        *,
        name: str,
        image: str,
        host_path: Path,
        run_id: str,
    ) -> str:
        del image, run_id
        self.workspaces[name] = host_path
        return f"test-{name}"

    async def execute(
        self,
        *,
        name: str,
        command: Sequence[str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        return await _run_process(
            tuple(command),
            timeout_seconds=timeout_seconds,
            cwd=self.workspaces[name],
            max_output_bytes=max_output_bytes,
        )

    async def stop(self, *, name: str) -> None:
        self.stop_calls.append(name)
        self.workspaces.pop(name, None)


@pytest.fixture
def isolated_runtime() -> IsolatedTestRuntime:
    return IsolatedTestRuntime()
