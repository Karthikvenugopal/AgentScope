from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.execution.results import CommandResult
from app.execution.workspace import DockerWorkspace, WorkspaceError


class FakeRuntime:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []
        self.executions: list[tuple[str, tuple[str, ...], float]] = []
        self.stops: list[str] = []
        self.result = CommandResult(
            command=("python",),
            exit_code=0,
            stdout="Python 3.12.9\n",
            stderr="",
            duration_ms=1.0,
        )
        self.fail_start = False
        self.fail_stop = False

    async def start(
        self,
        *,
        name: str,
        image: str,
        host_path: Path,
        run_id: str,
    ) -> str:
        self.starts.append({"name": name, "image": image, "host_path": host_path, "run_id": run_id})
        if self.fail_start:
            raise RuntimeError("start failed")
        return "container-id"

    async def execute(
        self,
        *,
        name: str,
        command: Sequence[str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        del max_output_bytes
        self.executions.append((name, tuple(command), timeout_seconds))
        return self.result

    async def stop(self, *, name: str) -> None:
        self.stops.append(name)
        if self.fail_stop:
            raise RuntimeError("stop failed")


async def test_docker_workspace_starts_executes_and_stops(
    source_repository: Path,
) -> None:
    runtime = FakeRuntime()
    workspace = await DockerWorkspace.create(
        source_repository,
        run_id="docker-lifecycle",
        runtime=runtime,
        image="runner:test",
    )
    sandbox = workspace.host_path.parent

    result = await workspace.execute(("python", "--version"), timeout_seconds=4)
    await workspace.close()

    assert runtime.starts[0]["name"] == "agentscope-docker-lifecycle"
    assert runtime.starts[0]["image"] == "runner:test"
    assert runtime.starts[0]["host_path"] == sandbox / "workspace"
    assert runtime.executions == [("agentscope-docker-lifecycle", ("python", "--version"), 4)]
    assert runtime.stops == ["agentscope-docker-lifecycle"]
    assert result.stdout.startswith("Python 3.12")
    assert not sandbox.exists()


async def test_docker_start_failure_removes_copied_workspace(
    source_repository: Path, tmp_path: Path
) -> None:
    runtime = FakeRuntime()
    runtime.fail_start = True
    workspace_base = tmp_path / "workspaces"

    with pytest.raises(RuntimeError, match="start failed"):
        await DockerWorkspace.create(
            source_repository,
            run_id="failed-start",
            runtime=runtime,
            workspace_base=workspace_base,
        )

    assert list(workspace_base.iterdir()) == []
    assert runtime.stops == ["agentscope-failed-start"]


async def test_timed_out_container_command_stops_container(
    source_repository: Path,
) -> None:
    runtime = FakeRuntime()
    runtime.result = CommandResult(
        command=("slow",),
        exit_code=-9,
        stdout="",
        stderr="",
        duration_ms=10.0,
        timed_out=True,
    )
    workspace = await DockerWorkspace.create(
        source_repository, run_id="timeout-run", runtime=runtime
    )

    result = await workspace.execute(("slow",), timeout_seconds=0.01)

    assert result.timed_out is True
    assert runtime.stops == ["agentscope-timeout-run"]
    with pytest.raises(WorkspaceError, match="not running"):
        await workspace.execute(("again",))
    await workspace.close()
    assert runtime.stops == ["agentscope-timeout-run"]


async def test_cleanup_failure_still_removes_workspace(source_repository: Path) -> None:
    runtime = FakeRuntime()
    workspace = await DockerWorkspace.create(
        source_repository, run_id="cleanup-failure", runtime=runtime
    )
    sandbox = workspace.host_path.parent
    runtime.fail_stop = True

    with pytest.raises(WorkspaceError, match="container cleanup failed"):
        await workspace.close()

    assert not sandbox.exists()
