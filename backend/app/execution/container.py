"""Real Docker CLI process adapter with no shell interpolation."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from time import monotonic
from typing import Protocol

from app.execution.results import CommandResult


class ContainerRuntimeError(RuntimeError):
    """The container runtime could not complete a lifecycle operation."""


class ContainerRuntime(Protocol):
    """Small boundary used by DockerWorkspace and lifecycle tests."""

    async def start(
        self,
        *,
        name: str,
        image: str,
        host_path: Path,
        run_id: str,
    ) -> str: ...

    async def execute(
        self,
        *,
        name: str,
        command: Sequence[str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult: ...

    async def stop(self, *, name: str) -> None: ...


class DockerCliRuntime:
    """Invoke Docker as an argument vector and apply conservative isolation."""

    def __init__(
        self,
        *,
        binary: str = "docker",
        cpu_limit: float = 2.0,
        memory_limit: str = "2g",
        pids_limit: int = 256,
        startup_timeout_seconds: float = 30.0,
    ) -> None:
        if cpu_limit <= 0 or pids_limit <= 0 or startup_timeout_seconds <= 0:
            raise ValueError("Docker resource limits and timeout must be positive")
        self.binary = binary
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.pids_limit = pids_limit
        self.startup_timeout_seconds = startup_timeout_seconds

    async def start(
        self,
        *,
        name: str,
        image: str,
        host_path: Path,
        run_id: str,
    ) -> str:
        self._require_binary()
        command = (
            self.binary,
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--label",
            f"dev.agentscope.run_id={run_id}",
            "--network",
            "none",
            "--cpus",
            str(self.cpu_limit),
            "--memory",
            self.memory_limit,
            "--pids-limit",
            str(self.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{host_path}:/workspace:rw",
            "--workdir",
            "/workspace",
            image,
            "sleep",
            "infinity",
        )
        result = await _run_process(command, timeout_seconds=self.startup_timeout_seconds)
        if result.timed_out:
            raise ContainerRuntimeError(
                f"Docker timed out while starting workspace container {name}"
            )
        if result.return_code != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown Docker error"
            raise ContainerRuntimeError(f"Docker could not start {name}: {detail}")
        container_id = result.stdout.strip()
        if not container_id:
            raise ContainerRuntimeError(f"Docker returned no container id for {name}")
        return container_id

    async def execute(
        self,
        *,
        name: str,
        command: Sequence[str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        self._require_binary()
        if not command:
            raise ValueError("command must not be empty")
        return await _run_process(
            (self.binary, "exec", name, *command),
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    async def stop(self, *, name: str) -> None:
        self._require_binary()
        result = await _run_process(
            (self.binary, "rm", "--force", name),
            timeout_seconds=self.startup_timeout_seconds,
        )
        if result.timed_out:
            raise ContainerRuntimeError(f"Docker timed out while removing {name}")
        if result.return_code != 0 and "No such container" not in result.stderr:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown Docker error"
            raise ContainerRuntimeError(f"Docker could not remove {name}: {detail}")

    def _require_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise ContainerRuntimeError(f"Docker executable {self.binary!r} was not found on PATH")


async def _run_process(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
    max_output_bytes: int = 1_000_000,
) -> CommandResult:
    """Run a process without a shell and return timeout as structured state."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    started = monotonic()
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:  # pragma: no cover - asyncio contract
        raise RuntimeError("subprocess output pipes were not created")
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, max_output_bytes))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, max_output_bytes))
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        timed_out = False
    except TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        timed_out = True
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task)
        raise

    (stdout_bytes, stdout_truncated), (stderr_bytes, stderr_truncated) = await asyncio.gather(
        stdout_task, stderr_task
    )

    return CommandResult(
        command=tuple(command),
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_ms=(monotonic() - started) * 1000,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


async def _read_bounded(
    stream: asyncio.StreamReader,
    max_output_bytes: int,
) -> tuple[bytes, bool]:
    """Drain a stream while retaining at most the configured number of bytes."""

    captured = bytearray()
    truncated = False
    while chunk := await stream.read(64 * 1024):
        remaining = max_output_bytes - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(captured), truncated
