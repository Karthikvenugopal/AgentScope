"""Deterministic strategy contracts: no paid calls or hidden-ground-truth selection."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents import MockCodingAgent
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.providers.models import ProviderMetadata
from app.strategies.engine import OrchestratedStrategy, StrategyContext
from app.strategies.models import Plan, StrategyConfiguration, StrategyResult, SubExecution
from app.strategies.parsing import structured_output
from app.telemetry.events import ProviderTraceEvent

ROOT = Path(__file__).resolve().parents[2]


class CorrectiveProvider:
    def __init__(self):
        self.paths = []
        self.initial = []

    async def execute(self, provider, model, task, workspace, limits, recorder, *, role=None):
        assert task.verification is None
        self.paths.append(workspace.host_path)
        self.initial.append(await workspace.read_text("app.py"))
        assert not list(workspace.host_path.rglob("*hidden*"))
        if role == "planner":
            text = '{"analysis":"inspect","steps":["fix response"]}'
        elif role == "reviewer":
            text = json.dumps(
                {
                    "decision": "revise",
                    "issues": ["wrong response"],
                    "suggested_changes": ["fix response"],
                    "selected_candidate": "A",
                }
            )
        elif role == "correction":
            await workspace.write_text(
                "app.py", 'def status_response():\n    return {"status": "ok"}\n'
            )
            text = "Corrected after review."
        else:
            text = "Deliberately unchanged candidate."
        await recorder.emit(
            ProviderTraceEvent,
            provider=provider.value,
            native_type="item.completed",
            payload={
                "native": {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": text},
                }
            },
        )
        return ProviderMetadata(
            provider=provider, version="test-fixture", image="test", image_id="test"
        )


async def test_corrective_invocation_clones_candidate_and_verifies_only_after_correction(
    tmp_path, isolated_runtime
):
    provider = CorrectiveProvider()
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        workspace_factory=DockerWorkspaceFactory(
            runtime=isolated_runtime, workspace_base=tmp_path / "ws"
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_runtime=provider,
    )
    config = StrategyConfiguration.model_validate(
        {role: {"agent": "codex"} for role in ("planner", "implementer", "reviewer")}
    )
    result = await harness.run(
        "incorrect_api_response",
        MockCodingAgent(),
        strategy="planner_implementer_reviewer",
        strategy_configuration=config,
    )
    assert result.status == "completed", result.failure_reason
    assert len(provider.paths) == len(set(provider.paths)) == 4
    assert result.orchestration.corrections == 1
    assert result.orchestration.correction_changed_patch
    assert result.orchestration.correction_improved_visible_tests
    assert result.orchestration.correction_changed_official_result is None
    assert result.metrics.inference.input_tokens is None
    assert result.metrics.provider_tool_calls == 0
    assert sum(e.event_type == "verification_started" for e in result.events) == 1
    assert not isolated_runtime.workspaces


async def test_good_unselected_candidate_cannot_rescue_selected_bad_patch(
    tmp_path, isolated_runtime
):
    class ChoosingProvider(CorrectiveProvider):
        async def execute(self, provider, model, task, workspace, limits, recorder, *, role=None):
            if role == "implementer":
                self.paths.append(workspace.host_path)
                assert '"state": "healthy"' in await workspace.read_text("app.py")
                if recorder.scope["candidate_id"] == "B":
                    await workspace.write_text(
                        "app.py", 'def status_response():\n    return {"status": "ok"}\n'
                    )
                text = "Candidate complete."
            elif role == "reviewer":
                text = '{"decision":"approve","selected_candidate":"A"}'
            else:
                return await super().execute(
                    provider, model, task, workspace, limits, recorder, role=role
                )
            await recorder.emit(
                ProviderTraceEvent,
                provider=provider.value,
                native_type="item.completed",
                payload={
                    "native": {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": text},
                    }
                },
            )
            return ProviderMetadata(
                provider=provider, version="test", image="test", image_id="test"
            )

    provider = ChoosingProvider()
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        workspace_factory=DockerWorkspaceFactory(
            runtime=isolated_runtime, workspace_base=tmp_path / "ws"
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_runtime=provider,
    )
    config = StrategyConfiguration.model_validate(
        {
            "planner": {"agent": "codex"},
            "implementers": {"agent": "codex", "count": 2},
            "reviewer": {"agent": "codex"},
        }
    )
    result = await harness.run(
        "incorrect_api_response",
        MockCodingAgent(),
        strategy="parallel_implementers",
        strategy_configuration=config,
    )
    assert result.status == "verification_failed"
    assert result.orchestration.selected_candidate == "A"
    assert result.git_diff == ""
    assert (
        next(
            e for e in result.orchestration.executions if e.candidate_id == "B"
        ).visible_test_exit_code
        == 0
    )
    assert sum(e.event_type == "verification_started" for e in result.events) == 1
    assert len(provider.paths) == len(set(provider.paths)) == 3
    assert not isolated_runtime.workspaces


async def test_role_timeout_retains_hierarchy_and_cleans_workspaces(tmp_path, isolated_runtime):
    class HangingProvider:
        async def execute(self, *args, **kwargs):
            await asyncio.sleep(10)

    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        workspace_factory=DockerWorkspaceFactory(
            runtime=isolated_runtime, workspace_base=tmp_path / "ws"
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_runtime=HangingProvider(),
        limits=RunLimits(overall_timeout_seconds=0.2),
    )
    result = await harness.run(
        "incorrect_api_response",
        MockCodingAgent(),
        strategy="planner_implementer_reviewer",
        strategy_configuration=StrategyConfiguration.model_validate(
            {"planner": {"agent": "codex"}}
        ),
    )
    assert result.status == "timed_out"
    assert result.orchestration.executions[0].status == "timed_out"
    assert result.verification is None
    assert not isolated_runtime.workspaces


def test_structured_output_accepts_fences_and_prose_not_guessed_decisions():
    plan = structured_output('Here is a plan:\n```json\n{"analysis":"a","steps":["b"]}\n```', Plan)
    assert plan.steps == ["b"]
    with pytest.raises(ValueError, match="No valid"):
        structured_output("I think this is fine", Plan)
    rich = structured_output(
        '{"analysis":{"risk":"tenant escape"},"steps":["fix"]}', Plan
    )
    assert json.loads(rich.analysis) == {"risk": "tenant escape"}


class ScriptedRoles:
    def __init__(self, *, failures=(), revise=False, malformed=None):
        self.failures, self.revise, self.malformed = failures, revise, malformed
        self.active = self.peak = 0
        self.calls = []

    async def __call__(
        self, role, configuration, candidate_id, instructions, source_execution_id=None
    ):
        self.calls.append((role, candidate_id, source_execution_id, instructions))
        self.active += 1
        self.peak = max(self.peak, self.active)
        start = datetime.now(UTC)
        await asyncio.sleep(0.01)
        self.active -= 1
        output = (
            {"analysis": "plan", "steps": ["read", "fix"]}
            if role == "planner"
            else {
                "decision": "revise" if self.revise else "approve",
                "selected_candidate": "B"
                if candidate_id is None and '"B"' in instructions
                else "A",
            }
        )
        return SubExecution(
            execution_id=f"run-{role}-{candidate_id}",
            parent_execution_id="run",
            role=role,
            provider="mock",
            candidate_id=candidate_id,
            status="failed"
            if (role in self.failures or candidate_id in self.failures)
            else "completed",
            started_at=start,
            finished_at=datetime.now(UTC),
            duration_ms=10,
            output="malformed" if self.malformed == role else json.dumps(output),
            failure_reason="scripted failure"
            if role in self.failures or candidate_id in self.failures
            else None,
            patch="corrected" if role == "correction" else "patch",
            visible_test_exit_code=0 if role == "correction" or not self.revise else 1,
        )


async def execute(name, runner, count=3):
    events = []

    async def emit(name, details):
        events.append((name, details))

    result = StrategyResult(strategy=name)
    config = StrategyConfiguration.model_validate({"implementers": {"count": count}})
    await OrchestratedStrategy(name).execute(StrategyContext(runner, emit, config, result))
    return result, events


@pytest.mark.parametrize("count", [2, 3])
async def test_parallel_overlaps_and_selects_before_any_verification(count):
    runner = ScriptedRoles()
    result, events = await execute("parallel_implementers", runner, count)
    assert runner.peak == count
    assert result.selected_candidate == "B" and result.candidate_count == count
    assert result.metrics.peak_concurrent_agents == count
    assert result.metrics.input_tokens is None
    assert result.metrics.concurrency_factor is None  # Mock is not a provider process.
    assert all("verif" not in name for name, _ in events)
    prompts = [call[3] for call in runner.calls if call[0] == "implementer"]
    assert len(set(prompts)) == 1


async def test_correction_is_exactly_once_and_hidden_counterfactual_unmeasured():
    runner = ScriptedRoles(revise=True)
    result, _ = await execute("planner_implementer_reviewer", runner)
    assert [c[0] for c in runner.calls] == ["planner", "implementer", "reviewer", "correction"]
    assert result.corrections == 1 and result.correction_changed_patch
    assert result.correction_improved_visible_tests
    assert result.correction_changed_official_result is None
    assert runner.calls[-1][2] == "run-implementer-A"


async def test_one_failed_candidate_does_not_abort_other_candidates():
    result, _ = await execute("parallel_implementers", ScriptedRoles(failures=("A",)))
    assert result.selected_candidate == "B"
    assert len(result.executions) == 5


async def test_all_parallel_candidates_failed_stops_before_reviewer():
    runner = ScriptedRoles(failures=("A", "B", "C"))
    with pytest.raises(RuntimeError, match="all implementation candidates failed"):
        await execute("parallel_implementers", runner)
    assert [call[0] for call in runner.calls] == [
        "planner",
        "implementer",
        "implementer",
        "implementer",
    ]


@pytest.mark.parametrize(
    "failures,malformed",
    [
        (("planner",), None),
        (("implementer",), None),
        (("reviewer",), None),
        ((), "planner"),
        ((), "reviewer"),
        (("correction",), None),
    ],
)
async def test_role_failure_or_unparseable_decision_fails_closed(failures, malformed):
    with pytest.raises((RuntimeError, ValueError)):
        await execute(
            "planner_implementer_reviewer",
            ScriptedRoles(failures=failures, malformed=malformed, revise=True),
        )


@pytest.mark.parametrize("strategy", ["planner_implementer_reviewer", "parallel_implementers"])
async def test_mock_strategy_integrates_harness_and_verifies_once(
    tmp_path, isolated_runtime, strategy
):
    root = ROOT
    fixture = root / "benchmarks/fixtures/incorrect_api_response/app.py"
    before = fixture.read_bytes()
    harness = SingleAgentHarness(
        catalog=TaskCatalog(root / "benchmarks"),
        workspace_factory=DockerWorkspaceFactory(
            runtime=isolated_runtime, workspace_base=tmp_path / "ws"
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )
    result = await harness.run("incorrect_api_response", MockCodingAgent(), strategy=strategy)
    assert result.status == "completed", result.failure_reason
    assert result.verification.passed
    assert sum(e.event_type == "verification_started" for e in result.events) == 1
    assert result.orchestration.selected_candidate == "A"
    assert all(e.parent_execution_id == result.run_id for e in result.orchestration.executions)
    assert not isolated_runtime.workspaces
    assert fixture.read_bytes() == before
    selection = next(
        e.sequence_number for e in result.events if e.event_type == "candidate_selected"
    )
    verification = next(
        e.sequence_number for e in result.events if e.event_type == "verification_started"
    )
    assert selection < verification
    if strategy == "parallel_implementers":
        starts = [e for e in result.events if e.event_type == "parallel_candidate_started"]
        completions = [
            e for e in result.events if e.event_type == "parallel_candidate_completed"
        ]
        assert {e.candidate_id for e in starts} == {"A", "B", "C"}
        assert {e.candidate_id for e in completions} == {"A", "B", "C"}
