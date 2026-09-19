"""Real coding agents use one controlled native-session capability, never a host shell."""

from typing import Any

from app.agents.base import AgentContext, AgentTurnResult, AgentTurnStatus, CodingAgent
from app.harness.tools.registry import ToolRegistry
from app.models.task import Task
from app.providers.models import ProviderName, ProviderOptions


class ExternalCodingAgent(CodingAgent):
    provider: ProviderName

    def __init__(self, model: str | None = None) -> None:
        self.options = ProviderOptions(model=model)

    @property
    def name(self) -> str:
        return self.provider.value

    def configuration(self) -> dict[str, Any]:
        return {"name": self.name, **self.options.model_dump()}

    async def run_turn(
        self, task: Task, tools: ToolRegistry, context: AgentContext
    ) -> AgentTurnResult:
        del task, context
        await tools.run_provider(self.provider, self.options.model)
        return AgentTurnResult(
            status=AgentTurnStatus.COMPLETED, summary="Provider session completed"
        )


class CodexAgent(ExternalCodingAgent):
    provider = ProviderName.CODEX


class ClaudeCodeAgent(ExternalCodingAgent):
    provider = ProviderName.CLAUDE
