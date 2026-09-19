"""Run against a dedicated PostgreSQL database; migrations, never create_all."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_single_agent_harness import CrashAgent

from app.agents import MockCodingAgent
from app.experiments.models import RawExperimentRun, load_spec
from app.experiments.planner import build_schedule, validate_frozen_inputs
from app.experiments.repository import ExperimentConflictError, ExperimentRepository
from app.harness.artifacts import ArtifactStore
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.models.run import RunResult, RunStatus
from app.storage import schema
from app.storage.repository import PostgresRunRepository, RunConflictError
from app.strategies.models import StrategyConfiguration

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL"),
]


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> PostgresRunRepository:
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
    command.check(Config(str(ROOT / "backend" / "alembic.ini")))
    return PostgresRunRepository.from_url(url)


async def test_real_docker_postgres_verified_run_and_idempotency(
    repository: PostgresRunRepository,
    tmp_path: Path,
) -> None:
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        artifact_store=ArtifactStore(tmp_path),
        repository=repository,
    )
    run = await harness.run("incorrect_api_response", MockCodingAgent.for_incorrect_api_response())
    assert run.status is RunStatus.COMPLETED, run.failure_reason
    repository.save(run)
    stored = repository.get(run.run_id)
    assert stored is not None
    assert stored.summary["status"] == "completed"
    assert stored.verification and stored.verification.passed_tests == 3
    assert stored.metrics.tool_calls == 6
    assert stored.metrics.lines_added == stored.metrics.lines_removed == 1
    assert stored.events == run.events
    assert all(
        v is None for v in stored.metrics.inference.model_dump(exclude={"provenance"}).values()
    )
    for artifact in stored.artifacts:
        data = await asyncio.to_thread(Path(artifact.path).read_bytes)
        assert artifact.sha256 == hashlib.sha256(data).hexdigest()
        assert artifact.size_bytes == len(data)
    assert stored.summary["provenance"]["source_sha256"]
    assert repository.list_runs()[0]["run_id"] == run.run_id
    with pytest.raises(RunConflictError):
        repository.save(run.model_copy(update={"agent_name": "changed"}))


async def test_parallel_docker_candidates_persist_queryable_hierarchy(repository, tmp_path):
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        artifact_store=ArtifactStore(tmp_path),
        repository=repository,
    )
    run = await harness.run(
        "incorrect_api_response",
        MockCodingAgent(),
        strategy="parallel_implementers",
        strategy_configuration=StrategyConfiguration.model_validate(
            {
                "planner": {"agent": "mock"},
                "implementers": {"agent": "mock", "count": 3},
                "reviewer": {"agent": "mock"},
            }
        ),
    )
    assert run.status == "completed", run.failure_reason
    repository.save(run)
    with repository.engine.connect() as connection:
        rows = (
            connection.execute(
                select(schema.executions).where(schema.executions.c.run_id == run.run_id)
            )
            .mappings()
            .all()
        )
        strategy = (
            connection.execute(
                select(schema.strategy_results).where(
                    schema.strategy_results.c.run_id == run.run_id
                )
            )
            .mappings()
            .one()
        )
        configuration = connection.execute(
            select(schema.runs.c.configuration).where(schema.runs.c.run_id == run.run_id)
        ).scalar_one()
    assert len(rows) == 5
    assert {r["parent_execution_id"] for r in rows} == {run.run_id}
    assert {r["candidate_id"] for r in rows if r["role"] == "implementer"} == {"A", "B", "C"}
    assert sum(r["selected"] for r in rows) == 1
    assert strategy["selected_candidate"] == "A"
    assert strategy["candidate_count"] == 3
    assert configuration["roles"]["implementers"] == {
        "agent": "mock",
        "model": None,
        "count": 3,
    }
    assert all("inference" in row["payload"] and "tool_calls" in row["payload"] for row in rows)
    stored = repository.get(run.run_id)
    assert stored.verification.passed_tests == 3
    assert sum(e.event_type == "verification_started" for e in stored.events) == 1


async def test_failed_verification_persists_and_child_insert_failure_rolls_back(
    repository: PostgresRunRepository,
    tmp_path: Path,
) -> None:
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        artifact_store=ArtifactStore(tmp_path),
        repository=repository,
    )
    baseline = await harness.run("incorrect_api_response", MockCodingAgent())
    stored = repository.get(baseline.run_id)
    assert stored and stored.summary["status"] == "verification_failed"
    assert stored.verification and stored.verification.failed_tests == 3
    assert stored.metrics.verification_passed is False
    # Even a direct SQL update cannot mark a failed official result completed.
    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                schema.runs.update()
                .where(
                    schema.runs.c.run_id == baseline.run_id,
                )
                .values(status="completed")
            )
    new_id = uuid.uuid4().hex
    # Duplicate global event IDs force an actual SQL constraint failure after
    # the new parent run was inserted; the transaction must roll it all back.
    invalid: RunResult = baseline.model_copy(
        update={
            "run_id": new_id,
            "events": tuple(e.model_copy(update={"run_id": new_id}) for e in baseline.events),
        }
    )
    with pytest.raises(IntegrityError):
        repository.save(invalid)
    assert repository.get(new_id) is None
    assert repository.get(baseline.run_id) is not None
    crashed = await harness.run("incorrect_api_response", CrashAgent())
    stored_crash = repository.get(crashed.run_id)
    assert stored_crash and stored_crash.summary["status"] == "failed"
    assert stored_crash.verification is None


def test_experiment_schedule_resumption_replacements_and_duplicate_prevention(repository):
    original = load_spec(ROOT / "experiments/phase9/strategy-study-pilot-v1.yaml")
    experiment_id = f"test-{uuid.uuid4().hex[:16]}"
    spec = original.model_copy(update={"experiment_id": experiment_id})
    experiments = ExperimentRepository(repository.engine)
    provenance = validate_frozen_inputs(spec, ROOT / "benchmarks")
    schedule = build_schedule(spec)
    assert experiments.create(spec, provenance, schedule)
    assert not experiments.create(spec, provenance, schedule)
    conflicting = spec.model_copy(update={"random_seed": spec.random_seed + 1})
    with pytest.raises(ExperimentConflictError):
        experiments.create(conflicting, provenance, build_schedule(conflicting))

    first = experiments.claim(experiment_id)
    assert first and first["attempt_number"] == 1
    invalid = RawExperimentRun(
        experiment_id=experiment_id,
        scheduled_order=1,
        task_id=first["task_id"],
        configuration_id=first["configuration_id"],
        repetition=first["repetition"],
        run_id=f"{experiment_id}-invalid",
        validity="infrastructure_failure",
        classification="infrastructure_failure",
    )
    now = datetime.now(UTC)
    experiments.record_attempt(
        experiment_id=experiment_id,
        scheduled_order=1,
        attempt_number=1,
        run_id=invalid.run_id,
        validity=invalid.validity,
        classification=invalid.classification,
        replacement_for_run_id=None,
        started_at=now,
        finished_at=now,
        failure_reason="provider outage",
        payload=invalid.model_dump(mode="json"),
    )
    replacement = experiments.claim(experiment_id)
    assert replacement and replacement["scheduled_order"] == 1
    assert replacement["attempt_number"] == 2
    assert replacement["replacement_for_run_id"] == invalid.run_id
    valid = invalid.model_copy(
        update={
            "run_id": f"{experiment_id}-valid",
            "validity": "valid",
            "classification": "benchmark_failure",
            "official_success": False,
        }
    )
    experiments.record_attempt(
        experiment_id=experiment_id,
        scheduled_order=1,
        attempt_number=2,
        run_id=valid.run_id,
        validity=valid.validity,
        classification=valid.classification,
        replacement_for_run_id=invalid.run_id,
        started_at=now,
        finished_at=now,
        failure_reason="official verification failed",
        payload=valid.model_dump(mode="json"),
    )
    record = experiments.get(experiment_id)
    assert record and record["progress"]["completed"] == 1
    assert record["progress"]["benchmark_failures"] == 1
    assert record["progress"]["infrastructure_failures"] == 1
    assert len(record["attempts"]) == 2
    experiments.recover(experiment_id)
    assert experiments.claim(experiment_id)["scheduled_order"] == 2


def test_experiment_timeout_audit_is_idempotent_and_preserves_replacement(repository):
    original = load_spec(ROOT / "experiments/phase9/strategy-study-pilot-v1.yaml")
    experiment_id = f"test-{uuid.uuid4().hex[:16]}"
    spec = original.model_copy(update={"experiment_id": experiment_id})
    experiments = ExperimentRepository(repository.engine)
    experiments.create(
        spec,
        validate_frozen_inputs(spec, ROOT / "benchmarks"),
        build_schedule(spec),
    )
    claimed = experiments.claim(experiment_id)
    assert claimed
    now = datetime.now(UTC)
    timed_out = RawExperimentRun(
        experiment_id=experiment_id,
        scheduled_order=1,
        task_id=claimed["task_id"],
        configuration_id=claimed["configuration_id"],
        repetition=claimed["repetition"],
        run_id=f"{experiment_id}-timeout",
        validity="infrastructure_failure",
        classification="infrastructure_failure",
    )
    experiments.record_attempt(
        experiment_id=experiment_id,
        scheduled_order=1,
        attempt_number=1,
        run_id=timed_out.run_id,
        validity=timed_out.validity,
        classification=timed_out.classification,
        replacement_for_run_id=None,
        started_at=now,
        finished_at=now,
        failure_reason="overall run timeout exceeded: 120s",
        payload=timed_out.model_dump(mode="json"),
    )
    replacement_claim = experiments.claim(experiment_id)
    assert replacement_claim and replacement_claim["attempt_number"] == 2
    replacement = timed_out.model_copy(
        update={
            "run_id": f"{experiment_id}-replacement",
            "validity": "valid",
            "classification": "benchmark_failure",
        }
    )
    experiments.record_attempt(
        experiment_id=experiment_id,
        scheduled_order=1,
        attempt_number=2,
        run_id=replacement.run_id,
        validity=replacement.validity,
        classification=replacement.classification,
        replacement_for_run_id=timed_out.run_id,
        started_at=now,
        finished_at=now,
        failure_reason="overall run timeout exceeded: 120s",
        payload=replacement.model_dump(mode="json"),
    )
    assert experiments.audit_timeout_replacements(experiment_id) == 1
    assert experiments.audit_timeout_replacements(experiment_id) == 0
    record = experiments.get(experiment_id)
    assert record and record["progress"]["benchmark_failures"] == 1
    assert record["progress"]["protocol_exclusions"] == 1
    assert record["progress"]["infrastructure_failures"] == 0
    assert record["schedule"][0]["valid_run_id"] == timed_out.run_id
    assert [run.validity for run in experiments.raw_runs(experiment_id)] == [
        "valid",
        "protocol_excluded",
    ]
