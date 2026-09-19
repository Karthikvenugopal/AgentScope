"""Deterministic, offline agent that exercises the real controlled tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import AgentContext, AgentTurnResult, AgentTurnStatus, CodingAgent
from app.harness.tools.models import ToolExecutionResult, ToolName
from app.harness.tools.registry import ToolRegistry
from app.models.task import Task


class MockToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName | str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MockTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calls: tuple[MockToolCall, ...] = ()
    complete: bool = False
    summary: str = "Completed scripted mock turn."
    stop_on_tool_failure: bool = True


class MockCodingAgent(CodingAgent):
    """Replay explicit tool calls without pretending to invoke a model."""

    def __init__(
        self,
        script: Sequence[MockTurn] | None = None,
        *,
        edits: Mapping[str, str] | None = None,
    ) -> None:
        if script is not None and edits is not None:
            raise ValueError("configure either script or edits, not both")
        if edits is not None:
            script = (
                MockTurn(
                    calls=tuple(
                        MockToolCall(
                            tool=ToolName.WRITE_FILE,
                            arguments={"path": path, "content": content},
                        )
                        for path, content in sorted(edits.items())
                    ),
                    complete=True,
                    summary="Applied deterministic mock edits.",
                ),
            )
        self._script = tuple(script or (MockTurn(complete=True),))
        self._turn_index = 0
        self._results: list[ToolExecutionResult] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def tool_results(self) -> tuple[ToolExecutionResult, ...]:
        return tuple(self._results)

    @property
    def script(self) -> tuple[MockTurn, ...]:
        return self._script

    def configuration(self) -> dict[str, Any]:
        return {
            **super().configuration(),
            "script": [t.model_dump(mode="json") for t in self._script],
        }

    async def start(self, task: Task, context: AgentContext) -> None:
        del task, context
        self._turn_index = 0
        self._results.clear()

    async def run_turn(
        self,
        task: Task,
        tools: ToolRegistry,
        context: AgentContext,
    ) -> AgentTurnResult:
        del task, context
        if self._turn_index >= len(self._script):
            return AgentTurnResult(
                status=AgentTurnStatus.COMPLETED,
                summary="Mock script exhausted.",
            )

        turn = self._script[self._turn_index]
        self._turn_index += 1
        for call in turn.calls:
            result = await tools.execute(call.tool, call.arguments)
            self._results.append(result)
            if not result.success and turn.stop_on_tool_failure:
                return AgentTurnResult(
                    status=AgentTurnStatus.FAILED,
                    summary=f"Mock tool {result.tool} failed: {result.error}",
                )

        return AgentTurnResult(
            status=(AgentTurnStatus.COMPLETED if turn.complete else AgentTurnStatus.CONTINUE),
            summary=turn.summary,
        )

    @classmethod
    def for_incorrect_api_response(cls) -> MockCodingAgent:
        """Exercise discovery, editing, tests, and patch inspection deterministically."""

        return cls(
            script=(
                MockTurn(
                    calls=(
                        MockToolCall(
                            tool=ToolName.LIST_DIRECTORY,
                            arguments={"path": "."},
                        ),
                        MockToolCall(
                            tool=ToolName.READ_FILE,
                            arguments={"path": "app.py"},
                        ),
                        MockToolCall(
                            tool=ToolName.SEARCH_CODE,
                            arguments={
                                "query": "status_response",
                                "path": ".",
                                "glob": "*.py",
                            },
                        ),
                    ),
                    summary="Inspected the failing API implementation.",
                ),
                MockTurn(
                    calls=(
                        MockToolCall(
                            tool=ToolName.EDIT_FILE,
                            arguments={
                                "path": "app.py",
                                "old_text": 'return {"state": "healthy"}',
                                "new_text": 'return {"status": "ok"}',
                            },
                        ),
                        MockToolCall(tool=ToolName.RUN_TESTS),
                    ),
                    summary="Corrected the payload and ran task tests.",
                ),
                MockTurn(
                    calls=(MockToolCall(tool=ToolName.GIT_DIFF),),
                    complete=True,
                    summary="Inspected the resulting patch.",
                ),
            )
        )
