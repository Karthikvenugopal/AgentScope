"""Execution result values shared by local and container runtimes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CommandResult(BaseModel):
    """Bounded, JSON-serializable output from one process execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = Field(ge=0)
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    @property
    def return_code(self) -> int:
        """Compatibility alias for the Phase 1 process API."""

        return self.exit_code
