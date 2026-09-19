from __future__ import annotations

from pathlib import Path

import pytest
from conftest import IsolatedTestRuntime

from app.agents import (
    AgentContext,
    AgentTurnStatus,
    CodingAgent,
    MockCodingAgent,
    MockToolCall,
    MockTurn,
)
from app.execution import DockerWorkspace
from app.harness.limits import RunLimits
from app.harness.snapshot import RepositorySnapshot
from app.harness.tools.base import ToolContext
from app.harness.tools.models import ToolName
from app.harness.tools.registry import ToolRegistry
from app.models.task import Task
from app.telemetry import TraceRecorder


def test_coding_agent_is_abstract() -> None:
    with pytest.raises(TypeError):
        CodingAgent()  # type: ignore[abstract]


async def _registry(
    source_repository: Path,
    task: Task,
    runtime: IsolatedTestRuntime,
) -> tuple[DockerWorkspace, ToolRegistry]:
    workspace = await DockerWorkspace.create(
        source_repository,
        run_id="mock-agent-test",
        runtime=runtime,
    )
    context = ToolContext(
        workspace=workspace,
        task=task,
        limits=RunLimits(),
        recorder=TraceRecorder(workspace.run_id),
        snapshot=await RepositorySnapshot.capture(workspace),
    )
    return workspace, ToolRegistry(context)


async def test_mock_agent_applies_scripted_edits_through_tools(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    agent = MockCodingAgent(edits={"app.py": "VALUE = 'fixed'\n", "new.txt": "new\n"})
    workspace, tools = await _registry(source_repository, task, isolated_runtime)
    try:
        context = AgentContext(run_id=workspace.run_id, turn_number=1)
        await agent.start(task, context)
        result = await agent.run_turn(task, tools, context)

        assert result.status is AgentTurnStatus.COMPLETED
        assert [item.tool for item in agent.tool_results] == ["write_file", "write_file"]
        assert await workspace.read_text("app.py") == "VALUE = 'fixed'\n"
    finally:
        await workspace.close()


async def test_mock_agent_stops_on_failed_tool(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    agent = MockCodingAgent(edits={"../escape.py": "bad"})
    workspace, tools = await _registry(source_repository, task, isolated_runtime)
    try:
        context = AgentContext(run_id=workspace.run_id, turn_number=1)
        await agent.start(task, context)
        result = await agent.run_turn(task, tools, context)

        assert result.status is AgentTurnStatus.FAILED
        assert "escapes root" in result.summary
    finally:
        await workspace.close()


async def test_mock_agent_can_continue_after_expected_tool_failure(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    agent = MockCodingAgent(
        script=(
            MockTurn(
                calls=(MockToolCall(tool="unknown_tool"),),
                complete=True,
                stop_on_tool_failure=False,
            ),
        )
    )
    workspace, tools = await _registry(source_repository, task, isolated_runtime)
    try:
        context = AgentContext(run_id=workspace.run_id, turn_number=1)
        await agent.start(task, context)
        result = await agent.run_turn(task, tools, context)

        assert result.status is AgentTurnStatus.COMPLETED
        assert agent.tool_results[0].success is False
    finally:
        await workspace.close()


def test_incorrect_api_mock_script_covers_expected_tools() -> None:
    agent = MockCodingAgent.for_incorrect_api_response()

    assert agent.name == "mock"
    assert [call.tool for turn in agent.script for call in turn.calls] == [
        ToolName.LIST_DIRECTORY,
        ToolName.READ_FILE,
        ToolName.SEARCH_CODE,
        ToolName.EDIT_FILE,
        ToolName.RUN_TESTS,
        ToolName.GIT_DIFF,
    ]
    assert agent.script[-1].complete is True


def test_mock_rejects_two_script_sources() -> None:
    with pytest.raises(ValueError, match="either script or edits"):
        MockCodingAgent(
            script=(MockTurn(complete=True),),
            edits={"file": "content"},
        )


def test_mock_tool_call_accepts_provider_neutral_tool_name() -> None:
    call = MockToolCall(tool=ToolName.READ_FILE, arguments={"path": "app.py"})

    assert call.tool == ToolName.READ_FILE
