"""Phase 8 interoperability, isolation, provenance, and validation contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents import AgentContext, AgentTurnResult, AgentTurnStatus, CodingAgent, MockCodingAgent
from app.benchmark.validation import BenchmarkValidator
from app.evaluation.models import VerificationResult
from app.harbor import ATIFError, HarborImportError, HarborTaskAdapter
from app.harbor.trajectory import export_atif, import_agentscope_events
from app.harness.artifacts import ArtifactStore
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.providers.models import ProviderMetadata
from app.strategies.models import StrategyConfiguration
from app.telemetry.events import RunStartedEvent

ROOT = Path(__file__).resolve().parents[2]


def harbor_task(tmp_path: Path, *, schema: str = "1.4") -> Path:
    task = tmp_path / "source-task"
    (task / "environment").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "solution").mkdir()
    (task / "instruction.md").write_text(
        "# benchmark canary\n\nCreate /app/run.py.", encoding="utf-8"
    )
    (task / "environment/Dockerfile").write_text(
        "FROM python:3.12\nWORKDIR /app\n", encoding="utf-8"
    )
    (task / "environment/public.py").write_text("VALUE = 1\n", encoding="utf-8")
    (task / "tests/test.sh").write_text("#!/bin/bash\necho 1 > /logs/verifier/reward.txt\n")
    (task / "tests/secret.txt").write_text("hidden assertion\n")
    (task / "solution/solve.sh").write_text("echo reference > run.py\n")
    (task / "task.toml").write_text(
        f'''schema_version = "{schema}"
future_top_level = "preserved by source package"
[task]
name = "example/async-fix"
description = "Fix async cleanup"
keywords = ["python", "concurrency"]
[metadata]
difficulty = "hard"
owner = "benchmark-team"
[environment]
docker_image = "python:3.12"
network_mode = "no-network"
[verifier]
timeout_sec = 30
[agent]
timeout_sec = 60
''',
        encoding="utf-8",
    )
    return task


def test_harbor_import_maps_current_schema_and_preserves_source(tmp_path):
    source = harbor_task(tmp_path)
    adapter = HarborTaskAdapter(
        source, dataset="example/current", dataset_version="7", imported_at="fixed"
    )
    task = adapter.load(repository_source="fixtures/example.async-fix", verification_source="x")
    assert task.id == "example.async-fix"
    assert task.environment.kind == "harbor"
    assert task.environment.workdir == "/app"
    assert task.provenance.harbor_version == "0.23.0"
    assert task.provenance.harbor_schema_version == "1.4"
    assert task.provenance.source_metadata["owner"] == "benchmark-team"
    assert "/workspace/run.py" in task.description
    assert "canary" not in task.description
    assert "future_top_level" in (source / "task.toml").read_text()


def test_harbor_materialization_excludes_solution_tests_and_dockerfile(tmp_path):
    source = harbor_task(tmp_path)
    target = tmp_path / "agent-visible"
    HarborTaskAdapter(source, dataset="x/y", dataset_version="1").materialize_repository(
        target
    )
    assert (target / "public.py").is_file()
    assert not (target / "Dockerfile").exists()
    assert not (target / "tests").exists()
    assert not (target / "solution").exists()
    assert "hidden assertion" not in "".join(
        path.read_text(errors="ignore") for path in target.rglob("*") if path.is_file()
    )


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda root: (root / "environment").rename(root / "gone"), "environment"),
        (lambda root: (root / "tests").rename(root / "gone-tests"), "verifier"),
    ],
)
def test_harbor_import_rejects_missing_required_material(tmp_path, mutation, message):
    source = harbor_task(tmp_path)
    mutation(source)
    with pytest.raises(HarborImportError, match=message):
        HarborTaskAdapter(source, dataset="x/y", dataset_version="1").load(
            repository_source="fixtures/x", verification_source="verification/x"
        )


def test_harbor_import_rejects_unknown_schema_but_tolerates_unknown_fields(tmp_path):
    source = harbor_task(tmp_path, schema="9.0")
    with pytest.raises(HarborImportError, match="unsupported Harbor task schema"):
        HarborTaskAdapter(source, dataset="x/y", dataset_version="1").load(
            repository_source="fixtures/x", verification_source="verification/x"
        )


def test_frozen_manifest_provenance_and_hidden_separation():
    manifest = json.loads((ROOT / "benchmarks/manifest.json").read_text())
    assert manifest["benchmark"] == {
        "frozen": True,
        "name": "AgentScope Benchmark",
        "version": "0.1",
    }
    assert manifest["task_count"] == 12
    assert {task["language"] for task in manifest["tasks"]} == {
        "Python",
        "TypeScript/JavaScript",
    }
    catalog = TaskCatalog(ROOT / "benchmarks")
    imported = catalog.get("terminal-bench.cancel-async-tasks")
    repository = catalog.resolve_repository(imported)
    assert not any(
        part in {"tests", "solution"}
        for path in repository.rglob("*")
        for part in path.parts
    )
    assert imported.provenance.dataset_version == "2.1@6"
    assert imported.provenance.task_hash


async def test_reference_validation_detects_baseline_failure_and_determinism(
    tmp_path, isolated_runtime
):
    catalog = TaskCatalog(ROOT / "benchmarks")
    validator = BenchmarkValidator(
        catalog,
        DockerWorkspaceFactory(runtime=isolated_runtime, workspace_base=tmp_path / "work"),
    )
    task = catalog.get("request_validation")
    result = await validator._task(task, 2)
    assert result.valid, result.errors
    assert result.baseline_passed is False
    assert result.reference_passed is True
    assert result.deterministic is True
    assert result.isolation_passed


def test_atif_v18_round_trip_preserves_native_event_and_hierarchy():
    now = datetime.now(UTC)
    root = RunStartedEvent(
        event_id="r:1",
        run_id="r",
        sequence_number=1,
        timestamp=now,
        task_id="t",
        agent_name="codex",
        limits={},
    )
    child = root.model_copy(
        update={
            "event_id": "r:2",
            "sequence_number": 2,
            "execution_id": "child-a",
            "parent_execution_id": "r",
            "role": "implementer",
        }
    )
    document = export_atif((root, child), run_id="r", agent_name="AgentScope")
    assert document["schema_version"] == "ATIF-v1.8"
    assert document["subagent_trajectories"][0]["trajectory_id"] == "child-a"
    recovered = import_agentscope_events(document)
    assert [event["sequence_number"] for event in recovered] == [1, 2]
    with pytest.raises(ATIFError):
        import_agentscope_events({"schema_version": "ATIF-v1.8", "steps": []})


async def test_imported_task_runs_single_staged_and_parallel_without_hidden_access(
    tmp_path, isolated_runtime
):
    class Writer(CodingAgent):
        @property
        def name(self):
            return "writer"

        async def run_turn(self, task, tools, context: AgentContext):
            result = await tools.execute(
                "create_file", {"path": "run.py", "content": "async def run_tasks(*a): pass\n"}
            )
            assert result.success
            return AgentTurnResult(status=AgentTurnStatus.COMPLETED, summary="written")

    class Roles:
        def __init__(self):
            self.initial: list[set[str]] = []

        async def execute(self, provider, model, task, workspace, limits, recorder, *, role=None):
            del model, limits
            assert task.verification is None
            self.initial.append({path.name for path in workspace.host_path.rglob("*")})
            assert "solution" not in self.initial[-1] and "tests" not in self.initial[-1]
            if role == "planner":
                text = '{"analysis":"inspect","steps":["implement"]}'
            elif role == "reviewer":
                text = '{"decision":"approve","selected_candidate":"A"}'
            else:
                await workspace.write_text("run.py", "async def run_tasks(*a): pass\n")
                text = "implemented"
            from app.telemetry.events import ProviderTraceEvent

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

    class SelectedOnlyVerifier:
        def __init__(self):
            self.calls = 0

        async def verify(self, task, workspace):
            self.calls += 1
            assert task.verification and task.verification.kind == "harbor"
            assert (workspace.host_path / "run.py").is_file()
            assert not (workspace.host_path / "solution").exists()
            assert not (workspace.host_path / "tests").exists()
            return VerificationResult(passed=True, exit_code=0, duration_ms=1)

    catalog = TaskCatalog(ROOT / "benchmarks")
    roles, verifier = Roles(), SelectedOnlyVerifier()
    harness = SingleAgentHarness(
        catalog=catalog,
        workspace_factory=DockerWorkspaceFactory(
            runtime=isolated_runtime, workspace_base=tmp_path / "work"
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        provider_runtime=roles,
        verifier=verifier,
    )
    task_id = "terminal-bench.cancel-async-tasks"
    single = await harness.run(task_id, Writer())
    assert single.status == "completed"
    staged = await harness.run(
        task_id,
        MockCodingAgent(),
        strategy="planner_implementer_reviewer",
        strategy_configuration=StrategyConfiguration.model_validate(
            {role: {"agent": "codex"} for role in ("planner", "implementer", "reviewer")}
        ),
    )
    assert staged.status == "completed"
    parallel = await harness.run(
        task_id,
        MockCodingAgent(),
        strategy="parallel_implementers",
        strategy_configuration=StrategyConfiguration.model_validate(
            {
                "planner": {"agent": "codex"},
                "implementers": {"agent": "codex", "count": 2},
                "reviewer": {"agent": "codex"},
            }
        ),
    )
    assert parallel.status == "completed"
    assert parallel.orchestration.selected_candidate == "A"
    assert verifier.calls == 3
