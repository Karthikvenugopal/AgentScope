"""Harness package with cycle-safe lazy exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.harness.task_catalog import TaskCatalog, TaskCatalogError

if TYPE_CHECKING:
    from app.harness.artifacts import ArtifactStore
    from app.harness.limits import RunLimitExceeded, RunLimits
    from app.harness.single_agent import SingleAgentHarness
    from app.harness.workspace_factory import DockerWorkspaceFactory, WorkspaceFactory

__all__ = [
    "ArtifactStore",
    "DockerWorkspaceFactory",
    "RunLimitExceeded",
    "RunLimits",
    "SingleAgentHarness",
    "TaskCatalog",
    "TaskCatalogError",
    "WorkspaceFactory",
]


def __getattr__(name: str) -> Any:
    if name == "ArtifactStore":
        from app.harness.artifacts import ArtifactStore

        return ArtifactStore
    if name in {"RunLimitExceeded", "RunLimits"}:
        from app.harness.limits import RunLimitExceeded, RunLimits

        return {"RunLimitExceeded": RunLimitExceeded, "RunLimits": RunLimits}[name]
    if name == "SingleAgentHarness":
        from app.harness.single_agent import SingleAgentHarness

        return SingleAgentHarness
    if name in {"DockerWorkspaceFactory", "WorkspaceFactory"}:
        from app.harness.workspace_factory import DockerWorkspaceFactory, WorkspaceFactory

        return {
            "DockerWorkspaceFactory": DockerWorkspaceFactory,
            "WorkspaceFactory": WorkspaceFactory,
        }[name]
    raise AttributeError(name)
