from __future__ import annotations

from pathlib import Path

import pytest
from conftest import IsolatedTestRuntime
from test_single_agent_harness import _harness

from app.agents import AgentContext, AgentTurnResult, MockCodingAgent
from app.evaluation.models import VerificationErrorCode, VerificationResult
from app.evaluation.verifier import PytestBenchmarkVerifier, copy_candidate, parse_junit
from app.execution import Workspace
from app.harness.task_catalog import TaskCatalog, TaskCatalogError
from app.harness.tools.registry import ToolRegistry
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.models.run import RunStatus
from app.models.task import Task, VerificationSpec

ROOT = Path(__file__).resolve().parents[2]


class InspectingMock(MockCodingAgent):
    async def run_turn(
        self,
        task: Task,
        tools: ToolRegistry,
        context: AgentContext,
    ) -> AgentTurnResult:
        assert task.verification is None
        inventory = await tools.execute("list_directory", {"recursive": True})
        assert "test_official" not in inventory.model_dump_json()
        denied = await tools.execute("read_file", {"path": "../official/test_official.py"})
        assert not denied.success
        return await super().run_turn(task, tools, context)


async def test_baseline_fails_and_fixed_code_passes_independent_tests(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(tmp_path, isolated_runtime)
    baseline = await harness.run("incorrect_api_response", MockCodingAgent(), run_id="bad")
    agent = InspectingMock(script=MockCodingAgent.for_incorrect_api_response().script)
    fixed = await harness.run("incorrect_api_response", agent, run_id="fixed")
    assert baseline.status is RunStatus.VERIFICATION_FAILED
    assert baseline.verification and baseline.verification.failed_tests == 3
    assert fixed.status is RunStatus.COMPLETED
    assert fixed.verification and fixed.verification.passed_tests == 3
    assert fixed.verification.total_tests == 3
    events = [e.event_type for e in fixed.events]
    assert events.index("agent_completed") < events.index("verification_started")
    assert events.index("verification_completed") < events.index("run_completed")
    assert isolated_runtime.workspaces == {}


async def test_visible_test_tampering_cannot_make_baseline_pass(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    run = await _harness(tmp_path, isolated_runtime).run(
        "incorrect_api_response",
        MockCodingAgent(edits={"tests/test_app.py": "def test_fake(): assert True\n"}),
        run_id="visible-tampering",
    )
    assert run.status is RunStatus.VERIFICATION_FAILED
    assert run.verification and run.verification.failed_tests == 3


class CrashingVerifier:
    async def verify(self, task: Task, workspace: Workspace) -> VerificationResult:
        raise RuntimeError("verifier crashed")


async def test_verifier_crash_is_not_agent_failure(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    harness = _harness(tmp_path, isolated_runtime)
    harness.verifier = CrashingVerifier()
    run = await harness.run("incorrect_api_response", MockCodingAgent(), run_id="crash-verifier")
    assert run.status is RunStatus.VERIFICATION_FAILED
    assert run.verification and run.verification.error_code is VerificationErrorCode.INFRASTRUCTURE
    assert any(e.event_type == "agent_completed" for e in run.events)
    assert any(e.event_type == "verification_failed" for e in run.events)
    assert isolated_runtime.workspaces == {}


async def test_verifier_timeout_is_typed_and_cleans_both_workspaces(
    tmp_path: Path,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    catalog = TaskCatalog(ROOT / "benchmarks")
    factory = DockerWorkspaceFactory(runtime=isolated_runtime, workspace_base=tmp_path)
    task = catalog.get("incorrect_api_response")
    assert task.verification
    task = task.model_copy(
        update={
            "verification": task.verification.model_copy(
                update={"timeout_seconds": 0.05},
            )
        }
    )
    workspace = await factory.create(
        catalog.resolve_repository(task), run_id="timeout", keep_workspace=False
    )
    try:
        await workspace.write_text("app.py", "import time\ntime.sleep(5)\n")
        result = await PytestBenchmarkVerifier(catalog, factory).verify(task, workspace)
        assert result.timed_out and not result.passed
        assert result.error_code is VerificationErrorCode.TIMEOUT
        assert result.total_tests is None
    finally:
        await workspace.close()
    assert isolated_runtime.workspaces == {}


def test_junit_counts_are_structured_and_include_errors_and_skips() -> None:
    report = (
        "<testsuites><testsuite><testcase/><testcase><error/></testcase>"
        "<testcase><skipped/></testcase></testsuite></testsuites>"
    )
    assert parse_junit(report) == (1, 1, 1, 3)
    with pytest.raises(ValueError):
        parse_junit("<not-junit/>")


def test_catalog_rejects_hidden_tests_inside_agent_repository() -> None:
    catalog = TaskCatalog(ROOT / "benchmarks")
    task = catalog.get("incorrect_api_response").model_copy(
        update={
            "verification": VerificationSpec(source="fixtures/incorrect_api_response/tests"),
        }
    )
    with pytest.raises(TaskCatalogError, match="disjoint"):
        catalog.resolve_repository(task)


def test_candidate_symlink_cannot_exfiltrate_host_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="unsupported file"):
        copy_candidate(source, tmp_path / "candidate")
