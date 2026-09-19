"""Provider-neutral, harness-driven coding-agent contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.harness.tools.registry import ToolRegistry
from app.models.task import Task


class AgentTurnStatus(StrEnum):
    CONTINUE = "continue"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentContext(BaseModel):
    """Immutable run/turn metadata supplied by harness orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    role: str = "implementer"
    model: str | None = None
    turn_number: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AgentTurnStatus
    summary: str


class CodingAgent(ABC):
    """One harness-controlled turn at a time.

    Keeping the loop in the harness makes turn limits enforceable even when a
    future provider adapter is faulty. Provider adapters map one model/agent
    interaction onto ``run_turn`` and can invoke only the supplied registry.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable implementation name used in run configuration."""

    async def start(self, task: Task, context: AgentContext) -> None:
        """Reset per-run state before the first turn."""

        del task, context

    def configuration(self) -> dict[str, Any]:
        """Non-secret configuration recorded for reproducibility."""
        return {"name": self.name, "model": None}

    @abstractmethod
    async def run_turn(
        self,
        task: Task,
        tools: ToolRegistry,
        context: AgentContext,
    ) -> AgentTurnResult:
        """Perform one bounded agent turn through controlled tools."""
