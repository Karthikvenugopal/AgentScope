from __future__ import annotations

import asyncio
import json
from pathlib import Path

from conftest import IsolatedTestRuntime

from app.agents import (
    AgentContext,
    AgentTurnResult,
    AgentTurnStatus,
    CodingAgent,
    MockCodingAgent,
    MockToolCall,
    MockTurn,
)
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.tools.models import ToolName
from app.harness.tools.registry import ToolRegistry
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.models.run import RunStatus
from app.models.task import Task

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ContinueAgent(CodingAgent):
    @property
    def name(self) -> str:
        return "continue"

    async def run_turn(
        self, task: Task, tools: ToolRegistry, context: AgentContext
    ) -> AgentTurnResult:
        del task, tools, context
        return AgentTurnResult(status=AgentTurnStatus.CONTINUE, summary="more")


class SlowAgent(CodingAgent):
    @property
    def name(self) -> str:
        return "slow"

    async def run_turn(
        self, task: Task, tools: ToolRegistry, context: AgentContext
    ) -> AgentTurnResult:
        del task, tools, context
        await asyncio.sleep(5)
        return AgentTurnResult(status=AgentTurnStatus.COMPLETED, summary="done")


class CrashAgent(CodingAgent):
    @property
    def name(self) -> str:
        return "crash"

    async def run_turn(
        self, task: Task, tools: ToolRegistry, context: AgentContext
    ) -> AgentTurnResult:
        del task, tools, context
        raise RuntimeError("agent process crashed")


def _harness(
    tmp_path: Path,
    runtime: IsolatedTestRuntime,
    *,
    limits: RunLimits | None = None,
) -> SingleAgentHarness:
    return SingleAgentHarness(
        catalog=TaskCatalog(_REPOSITORY_ROOT / "benchmarks"),
        workspace_factory=DockerWorkspaceFactory(
            runtime=runtime,
            workspace_base=tmp_path / "workspaces",
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        limits=limits,
    )


async def test_single_agent_harness_completes_full_mock_lifecycle(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    fixture = _REPOSITORY_ROOT / "benchmarks" / "fixtures" / "incorrect_api_response" / "app.py"
    original = await asyncio.to_thread(fixture.read_text)
    harness = _harness(tmp_path, isolated_runtime)

    result = await harness.run(
        "incorrect_api_response",
        MockCodingAgent.for_incorrect_api_response(),
        run_id="phase2-e2e",
    )

    assert result.status is RunStatus.COMPLETED
    assert result.agent_turns == 3
    assert result.tool_calls == 6
    assert result.files_modified == ("app.py",)
    assert 'return {"status": "ok"}' in result.git_diff
    assert result.events[0].event_type == "run_started"
    assert result.events[-1].event_type == "run_completed"
    assert [event.tool for event in result.events if event.event_type == "tool_call_started"] == [
        "list_directory",
        "read_file",
        "search_code",
        "edit_file",
        "run_tests",
        "git_diff",
    ]
    assert "test_executed" in [event.event_type for event in result.events]
    assert [event.sequence_number for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    assert await asyncio.to_thread(fixture.read_text) == original
    assert result.workspace is not None
    assert not await asyncio.to_thread(Path(result.workspace.host_path).exists)


async def test_completed_run_exports_trace_patch_and_summary(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    result = await _harness(tmp_path, isolated_runtime).run(
        "incorrect_api_response",
        MockCodingAgent.for_incorrect_api_response(),
        run_id="artifact-export",
    )

    assert result.artifacts is not None
    trace_text, summary_text, patch = await asyncio.gather(
        asyncio.to_thread(Path(result.artifacts.trace).read_text),
        asyncio.to_thread(Path(result.artifacts.run).read_text),
        asyncio.to_thread(Path(result.artifacts.patch).read_text),
    )
    trace = json.loads(trace_text)
    summary = json.loads(summary_text)
    assert trace["run_id"] == "artifact-export"
    assert trace["events"][-1]["event_type"] == "run_completed"
    assert summary["status"] == "completed"
    assert "events" not in summary
    assert patch == result.git_diff


async def test_keep_workspace_retains_fixed_copy_but_stops_runtime(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    result = await _harness(tmp_path, isolated_runtime).run(
        "incorrect_api_response",
        MockCodingAgent.for_incorrect_api_response(),
        run_id="retained-workspace",
        keep_workspace=True,
    )

    assert result.workspace is not None
    retained_file = Path(result.workspace.host_path) / "app.py"
    assert 'return {"status": "ok"}' in retained_file.read_text()
    assert isolated_runtime.workspaces == {}
    assert result.workspace.retained is True


async def test_agent_turn_limit_fails_run_and_cleans_workspace(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(
        tmp_path,
        isolated_runtime,
        limits=RunLimits(max_agent_turns=2),
    )

    result = await harness.run("incorrect_api_response", ContinueAgent(), run_id="turn-limit")

    assert result.status is RunStatus.FAILED
    assert result.agent_turns == 2
    assert result.failure_reason and "maximum agent turn limit" in result.failure_reason
    assert result.events[-1].event_type == "run_failed"
    assert list((tmp_path / "workspaces").iterdir()) == []


async def test_tool_call_limit_terminates_run(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    agent = MockCodingAgent(
        script=(
            MockTurn(
                calls=(
                    MockToolCall(tool=ToolName.READ_FILE, arguments={"path": "app.py"}),
                    MockToolCall(tool=ToolName.READ_FILE, arguments={"path": "app.py"}),
                ),
                complete=True,
            ),
        )
    )
    harness = _harness(
        tmp_path,
        isolated_runtime,
        limits=RunLimits(max_tool_calls=1),
    )

    result = await harness.run("incorrect_api_response", agent, run_id="tool-limit")

    assert result.status is RunStatus.FAILED
    assert result.tool_calls == 1
    assert result.failure_reason and "maximum tool call limit" in result.failure_reason
    assert "tool_call_failed" in [event.event_type for event in result.events]


async def test_overall_timeout_returns_terminal_state_and_cleans_up(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(
        tmp_path,
        isolated_runtime,
        limits=RunLimits(overall_timeout_seconds=0.02),
    )

    result = await harness.run("incorrect_api_response", SlowAgent(), run_id="overall-timeout")

    assert result.status is RunStatus.TIMED_OUT
    assert result.events[-1].event_type == "run_timed_out"
    assert result.failure_reason and "overall run timeout" in result.failure_reason
    assert isolated_runtime.workspaces == {}
    assert list((tmp_path / "workspaces").iterdir()) == []


async def test_agent_exception_returns_failure_and_cleans_up(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    result = await _harness(tmp_path, isolated_runtime).run(
        "incorrect_api_response", CrashAgent(), run_id="agent-crash"
    )

    assert result.status is RunStatus.FAILED
    assert result.failure_reason == "RuntimeError: agent process crashed"
    assert result.events[-1].event_type == "run_failed"
    assert isolated_runtime.workspaces == {}
    assert list((tmp_path / "workspaces").iterdir()) == []


async def test_failed_tool_call_causes_deterministic_mock_failure(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    agent = MockCodingAgent(
        script=(
            MockTurn(
                calls=(MockToolCall(tool="missing_tool"),),
                complete=True,
            ),
        )
    )

    result = await _harness(tmp_path, isolated_runtime).run(
        "incorrect_api_response", agent, run_id="failed-tool"
    )

    event_types = [event.event_type for event in result.events]
    assert result.status is RunStatus.FAILED
    assert "tool_call_failed" in event_types
    assert event_types[-1] == "run_failed"
    assert "agent_turn_completed" in event_types
