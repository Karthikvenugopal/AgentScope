"""Isolated repository copies and their execution lifecycle."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from app.execution.container import ContainerRuntime, DockerCliRuntime, _run_process
from app.execution.results import CommandResult

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class WorkspaceError(RuntimeError):
    """Workspace preparation, access, or cleanup failed."""


def resolve_workspace_path(
    workspace_root: Path,
    relative_path: str,
    *,
    allow_root: bool = False,
) -> Path:
    """Resolve one workspace-relative path without following an escape symlink."""

    raw = Path(relative_path)
    if raw.is_absolute() or (not raw.parts and not allow_root):
        raise ValueError("workspace path must be relative")
    root = workspace_root.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"workspace path escapes root: {relative_path}") from exc
    return candidate


class Workspace(ABC):
    """The only filesystem/process surface supplied to a coding agent."""

    @property
    @abstractmethod
    def run_id(self) -> str: ...

    @property
    @abstractmethod
    def host_path(self) -> Path: ...

    @abstractmethod
    async def read_text(self, relative_path: str, *, max_bytes: int = 2_000_000) -> str: ...

    @abstractmethod
    async def write_text(self, relative_path: str, content: str) -> None: ...

    @abstractmethod
    async def execute(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = 1_000_000,
    ) -> CommandResult: ...

    @property
    @abstractmethod
    def execution_is_isolated(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...

    async def freeze(self) -> None:
        """Stop all writers before the harness snapshots the candidate."""
        raise WorkspaceError("runtime does not support freezing")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            await self.close()
        except Exception:
            if exc is None:
                raise


class _FileWorkspace(Workspace):
    def __init__(
        self,
        *,
        run_id: str,
        sandbox_path: Path,
        keep_workspace: bool,
    ) -> None:
        self._run_id = run_id
        self._sandbox_path = sandbox_path
        self._host_path = sandbox_path / "workspace"
        self._keep_workspace = keep_workspace
        self._closed = False

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def host_path(self) -> Path:
        return self._host_path

    @property
    def execution_is_isolated(self) -> bool:
        return False

    async def read_text(self, relative_path: str, *, max_bytes: int = 2_000_000) -> str:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        path = self._safe_path(relative_path)

        def read() -> str:
            if path.stat().st_size > max_bytes:
                raise WorkspaceError(f"file exceeds {max_bytes} byte read limit: {relative_path}")
            return path.read_text(encoding="utf-8")

        return await asyncio.to_thread(read)

    async def write_text(self, relative_path: str, content: str) -> None:
        path = self._safe_path(relative_path)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Resolve again after creating parents so a concurrent symlink cannot
            # redirect the final write beyond the workspace.
            checked = self._safe_path(relative_path)
            temporary = checked.parent / f".{checked.name}.{uuid.uuid4().hex}.tmp"
            try:
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, checked)
            finally:
                temporary.unlink(missing_ok=True)

        await asyncio.to_thread(write)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._keep_workspace:
            await asyncio.to_thread(shutil.rmtree, self._sandbox_path, True)

    def _safe_path(self, relative_path: str) -> Path:
        if self._closed:
            raise WorkspaceError("workspace is closed")
        return resolve_workspace_path(self._host_path, relative_path)

    @classmethod
    async def _prepare_repository(
        cls,
        source_path: Path | str,
        *,
        run_id: str | None,
        workspace_base: Path | str | None,
    ) -> tuple[str, Path]:
        def prepare() -> tuple[str, Path]:
            source = Path(source_path).expanduser().resolve()
            if not source.is_dir():
                raise WorkspaceError(f"repository source does not exist: {source}")
            base = Path(workspace_base).expanduser().resolve() if workspace_base else None
            resolved_run_id = run_id or uuid.uuid4().hex
            if not _RUN_ID_PATTERN.fullmatch(resolved_run_id):
                raise ValueError(
                    "run_id must be 1-64 characters containing only letters, numbers, '.', "
                    "'_', or '-'"
                )
            if base is not None:
                base.mkdir(parents=True, exist_ok=True)
            sandbox = Path(
                tempfile.mkdtemp(
                    prefix=f"agentscope-{resolved_run_id}-",
                    dir=base,
                )
            )
            try:
                shutil.copytree(source, sandbox / "workspace")
            except BaseException:
                shutil.rmtree(sandbox, True)
                raise
            return resolved_run_id, sandbox

        # File copies run in a thread. If the enclosing run times out, wait for that
        # thread to finish before removing its result; otherwise it can recreate files
        # after the harness has reported successful cleanup.
        preparation = asyncio.create_task(asyncio.to_thread(prepare))
        try:
            return await asyncio.shield(preparation)
        except asyncio.CancelledError:
            try:
                _, sandbox = await preparation
            except BaseException:
                pass
            else:
                await asyncio.to_thread(shutil.rmtree, sandbox, True)
            raise
        except Exception as exc:
            if isinstance(exc, (ValueError, WorkspaceError)):
                raise
            raise WorkspaceError(f"could not copy repository: {exc}") from exc


class LocalWorkspace(_FileWorkspace):
    """Repository copy for fast tests/development; benchmark runs use Docker."""

    @classmethod
    async def create(
        cls,
        source_path: Path | str,
        *,
        run_id: str | None = None,
        workspace_base: Path | str | None = None,
        keep_workspace: bool = False,
    ) -> LocalWorkspace:
        resolved_run_id, sandbox = await cls._prepare_repository(
            source_path,
            run_id=run_id,
            workspace_base=workspace_base,
        )
        return cls(
            run_id=resolved_run_id,
            sandbox_path=sandbox,
            keep_workspace=keep_workspace,
        )

    async def execute(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = 1_000_000,
    ) -> CommandResult:
        if self._closed:
            raise WorkspaceError("workspace is closed")
        if not command:
            raise ValueError("command must not be empty")
        return await _run_process(
            tuple(command),
            timeout_seconds=timeout_seconds,
            cwd=self.host_path,
            max_output_bytes=max_output_bytes,
        )


class DockerWorkspace(_FileWorkspace):
    """A copied repository mounted into a hardened, ephemeral Docker container."""

    def __init__(
        self,
        *,
        run_id: str,
        sandbox_path: Path,
        keep_workspace: bool,
        runtime: ContainerRuntime,
        image: str,
    ) -> None:
        super().__init__(
            run_id=run_id,
            sandbox_path=sandbox_path,
            keep_workspace=keep_workspace,
        )
        self._runtime = runtime
        self.image = image
        self.container_name = f"agentscope-{run_id}"
        self.container_id: str | None = None

    @classmethod
    async def create(
        cls,
        source_path: Path | str,
        *,
        run_id: str | None = None,
        workspace_base: Path | str | None = None,
        keep_workspace: bool = False,
        image: str = "agentscope-runner:py312",
        runtime: ContainerRuntime | None = None,
    ) -> DockerWorkspace:
        resolved_run_id, sandbox = await cls._prepare_repository(
            source_path,
            run_id=run_id,
            workspace_base=workspace_base,
        )
        workspace = cls(
            run_id=resolved_run_id,
            sandbox_path=sandbox,
            keep_workspace=keep_workspace,
            runtime=runtime or DockerCliRuntime(),
            image=image,
        )
        try:
            workspace.container_id = await workspace._runtime.start(
                name=workspace.container_name,
                image=image,
                host_path=workspace.host_path,
                run_id=workspace.run_id,
            )
        except BaseException:
            try:
                await workspace._runtime.stop(name=workspace.container_name)
            except BaseException:
                pass
            await _FileWorkspace.close(workspace)
            raise
        return workspace

    async def execute(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = 1_000_000,
    ) -> CommandResult:
        if self._closed or self.container_id is None:
            raise WorkspaceError("Docker workspace is not running")
        if not command:
            raise ValueError("command must not be empty")
        result = await self._runtime.execute(
            name=self.container_name,
            command=tuple(command),
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        if result.timed_out:
            # Killing only the local `docker exec` client can leave the command
            # alive in the container. Stop the entire ephemeral container.
            await self._runtime.stop(name=self.container_name)
            self.container_id = None
        return result

    @property
    def execution_is_isolated(self) -> bool:
        return True

    async def freeze(self) -> None:
        if self.container_id is not None:
            await self._runtime.stop(name=self.container_name)
            self.container_id = None

    async def close(self) -> None:
        if self._closed:
            return
        cleanup_error: Exception | None = None
        if self.container_id is not None:
            try:
                await self._runtime.stop(name=self.container_name)
            except Exception as exc:
                cleanup_error = exc
            finally:
                self.container_id = None
        await super().close()
        if cleanup_error is not None:
            raise WorkspaceError(
                f"workspace files were cleaned, but container cleanup failed: {cleanup_error}"
            ) from cleanup_error
