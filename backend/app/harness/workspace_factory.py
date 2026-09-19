"""Injectable creation boundary for isolated run workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.execution.container import ContainerRuntime
from app.execution.workspace import DockerWorkspace, Workspace


class WorkspaceFactory(Protocol):
    @property
    def runtime_name(self) -> str: ...

    @property
    def image(self) -> str | None: ...

    async def create(
        self,
        repository: Path,
        *,
        run_id: str,
        keep_workspace: bool,
    ) -> Workspace: ...


@dataclass(frozen=True, slots=True)
class DockerWorkspaceFactory:
    image: str = "agentscope-runner:py312"
    runtime: ContainerRuntime | None = None
    workspace_base: Path | None = None
    runtime_name: str = "docker"

    def __post_init__(self) -> None:
        # Establish the owned root eagerly so even a timeout during catalog/hash
        # loading has a deterministic, inspectable cleanup location.
        if self.workspace_base is not None:
            self.workspace_base.mkdir(parents=True, exist_ok=True)

    async def create(
        self,
        repository: Path,
        *,
        run_id: str,
        keep_workspace: bool,
    ) -> Workspace:
        return await DockerWorkspace.create(
            repository,
            run_id=run_id,
            workspace_base=self.workspace_base,
            keep_workspace=keep_workspace,
            image=self.image,
            runtime=self.runtime,
        )
