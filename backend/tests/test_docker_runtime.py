from __future__ import annotations

from pathlib import Path

import pytest

import app.execution.container as container_module
from app.execution.container import ContainerRuntimeError, DockerCliRuntime
from app.execution.results import CommandResult


def test_runtime_rejects_invalid_resource_limits() -> None:
    with pytest.raises(ValueError, match="positive"):
        DockerCliRuntime(cpu_limit=0)


async def test_runtime_reports_missing_docker_binary(tmp_path: Path) -> None:
    runtime = DockerCliRuntime(binary="definitely-not-a-real-docker-binary")

    with pytest.raises(ContainerRuntimeError, match="was not found"):
        await runtime.start(
            name="agentscope-test",
            image="runner:test",
            host_path=tmp_path,
            run_id="test",
        )


async def test_start_command_applies_isolation_and_resource_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[tuple[str, ...]] = []

    async def fake_run_process(
        command: tuple[str, ...], *, timeout_seconds: float, cwd: Path | None = None
    ) -> CommandResult:
        del timeout_seconds, cwd
        captured.append(tuple(command))
        return CommandResult(
            command=tuple(command),
            exit_code=0,
            stdout="abc123\n",
            stderr="",
            duration_ms=1.0,
        )

    monkeypatch.setattr(container_module.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(container_module, "_run_process", fake_run_process)
    runtime = DockerCliRuntime(cpu_limit=1.5, memory_limit="768m", pids_limit=64)

    container_id = await runtime.start(
        name="agentscope-safe",
        image="runner:test",
        host_path=tmp_path,
        run_id="safe",
    )

    command = captured[0]
    assert container_id == "abc123"
    assert ("--network", "none") == command[command.index("--network") :][:2]
    assert ("--cap-drop", "ALL") == command[command.index("--cap-drop") :][:2]
    assert ("--pids-limit", "64") == command[command.index("--pids-limit") :][:2]
    assert ("--memory", "768m") == command[command.index("--memory") :][:2]
    assert "--user" in command
    assert "dev.agentscope.run_id=safe" in command


async def test_start_surfaces_docker_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_run_process(
        command: tuple[str, ...], *, timeout_seconds: float, cwd: Path | None = None
    ) -> CommandResult:
        del timeout_seconds, cwd
        return CommandResult(
            command=tuple(command),
            exit_code=125,
            stdout="",
            stderr="daemon unavailable",
            duration_ms=1.0,
        )

    monkeypatch.setattr(container_module.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(container_module, "_run_process", fake_run_process)

    with pytest.raises(ContainerRuntimeError, match="daemon unavailable"):
        await DockerCliRuntime().start(
            name="agentscope-fail",
            image="runner:test",
            host_path=tmp_path,
            run_id="fail",
        )
