"""Transactional PostgreSQL ledger for immutable, resumable experiments."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.experiments.models import ExperimentSpec, RawExperimentRun, ScheduleEntry
from app.storage import schema


class ExperimentConflictError(ValueError):
    """An experiment ID was reused for a different immutable specification."""


class ExperimentRepository:
    def __init__(self, engine: Engine) -> None:
        dialect = getattr(engine, "dialect", None)
        if dialect is not None and dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required")
        self.engine = engine

    def create(
        self,
        spec: ExperimentSpec,
        provenance: dict[str, Any],
        schedule: tuple[ScheduleEntry, ...],
    ) -> bool:
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(schema.experiments.c.spec_hash).where(
                    schema.experiments.c.experiment_id == spec.experiment_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing != spec.spec_hash:
                    raise ExperimentConflictError(
                        "experiment ID already exists with a different spec hash"
                    )
                return False
            connection.execute(
                schema.experiments.insert().values(
                    experiment_id=spec.experiment_id,
                    spec_hash=spec.spec_hash,
                    name=spec.name,
                    research_question=spec.research_question,
                    benchmark_name=spec.benchmark_name,
                    benchmark_version=spec.benchmark_version,
                    benchmark_manifest_hash=spec.benchmark_manifest_hash,
                    random_seed=spec.random_seed,
                    status="planned",
                    spec=spec.model_dump(mode="json"),
                    provenance=provenance,
                    created_at=spec.created_at,
                )
            )
            connection.execute(
                schema.experiment_configs.insert(),
                [
                    {
                        "experiment_id": spec.experiment_id,
                        "configuration_id": configuration.id,
                        "strategy": configuration.strategy,
                        "provider": configuration.provider,
                        "configuration": configuration.model_dump(mode="json"),
                    }
                    for configuration in spec.configurations
                ],
            )
            connection.execute(
                schema.experiment_schedule.insert(),
                [
                    {
                        "experiment_id": spec.experiment_id,
                        **entry.model_dump(mode="json"),
                        "status": "pending",
                        "attempt_count": 0,
                    }
                    for entry in schedule
                ],
            )
            return True

    def recover(self, experiment_id: str) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(schema.experiment_schedule)
                .where(
                    schema.experiment_schedule.c.experiment_id == experiment_id,
                    schema.experiment_schedule.c.status == "running",
                )
                .values(status="pending", started_at=None)
            )
            return result.rowcount

    def claim(self, experiment_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(schema.experiment_schedule)
                    .where(
                        schema.experiment_schedule.c.experiment_id == experiment_id,
                        schema.experiment_schedule.c.status == "pending",
                    )
                    .order_by(schema.experiment_schedule.c.scheduled_order)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            now = datetime.now(UTC)
            connection.execute(
                update(schema.experiment_schedule)
                .where(
                    schema.experiment_schedule.c.experiment_id == experiment_id,
                    schema.experiment_schedule.c.scheduled_order == row["scheduled_order"],
                )
                .values(status="running", started_at=now)
            )
            connection.execute(
                update(schema.experiments)
                .where(schema.experiments.c.experiment_id == experiment_id)
                .values(
                    status="running",
                    started_at=func.coalesce(schema.experiments.c.started_at, now),
                    pause_reason=None,
                )
            )
            previous = connection.execute(
                select(schema.experiment_runs.c.run_id)
                .where(
                    schema.experiment_runs.c.experiment_id == experiment_id,
                    schema.experiment_runs.c.scheduled_order == row["scheduled_order"],
                )
                .order_by(schema.experiment_runs.c.attempt_number.desc())
                .limit(1)
            ).scalar_one_or_none()
            return {
                **dict(row),
                "attempt_number": int(row["attempt_count"]) + 1,
                "replacement_for_run_id": previous,
            }

    def record_attempt(
        self,
        *,
        experiment_id: str,
        scheduled_order: int,
        attempt_number: int,
        run_id: str,
        validity: str,
        classification: str,
        replacement_for_run_id: str | None,
        started_at: datetime,
        finished_at: datetime,
        failure_reason: str | None,
        payload: dict[str, Any],
        classification_note: str | None = None,
    ) -> None:
        attempt_id = f"{experiment_id}:{scheduled_order}:{attempt_number}"
        with self.engine.begin() as connection:
            connection.execute(
                insert(schema.experiment_runs)
                .values(
                    attempt_id=attempt_id,
                    experiment_id=experiment_id,
                    scheduled_order=scheduled_order,
                    attempt_number=attempt_number,
                    run_id=run_id,
                    validity=validity,
                    classification=classification,
                    replacement_for_run_id=replacement_for_run_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    failure_reason=failure_reason,
                    classification_note=classification_note,
                    payload=payload,
                )
                .on_conflict_do_nothing(index_elements=["attempt_id"])
            )
            values: dict[str, Any] = {
                "attempt_count": attempt_number,
                "status": "completed" if validity == "valid" else "pending",
                "finished_at": finished_at if validity == "valid" else None,
                "valid_run_id": run_id if validity == "valid" else None,
            }
            connection.execute(
                update(schema.experiment_schedule)
                .where(
                    schema.experiment_schedule.c.experiment_id == experiment_id,
                    schema.experiment_schedule.c.scheduled_order == scheduled_order,
                )
                .values(**values)
            )

    def pause(self, experiment_id: str, reason: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(schema.experiment_schedule)
                .where(
                    schema.experiment_schedule.c.experiment_id == experiment_id,
                    schema.experiment_schedule.c.status == "running",
                )
                .values(status="pending", started_at=None)
            )
            connection.execute(
                update(schema.experiments)
                .where(schema.experiments.c.experiment_id == experiment_id)
                .values(status="paused", pause_reason=reason)
            )

    def finish_if_complete(self, experiment_id: str) -> bool:
        with self.engine.begin() as connection:
            pending = connection.execute(
                select(func.count())
                .select_from(schema.experiment_schedule)
                .where(
                    schema.experiment_schedule.c.experiment_id == experiment_id,
                    schema.experiment_schedule.c.status != "completed",
                )
            ).scalar_one()
            if pending:
                return False
            connection.execute(
                update(schema.experiments)
                .where(schema.experiments.c.experiment_id == experiment_id)
                .values(status="completed", finished_at=datetime.now(UTC), pause_reason=None)
            )
            return True

    def get(self, experiment_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            experiment = (
                connection.execute(
                    select(schema.experiments).where(
                        schema.experiments.c.experiment_id == experiment_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if experiment is None:
                return None
            configurations = (
                connection.execute(
                    select(schema.experiment_configs)
                    .where(schema.experiment_configs.c.experiment_id == experiment_id)
                    .order_by(schema.experiment_configs.c.configuration_id)
                )
                .mappings()
                .all()
            )
            schedule = (
                connection.execute(
                    select(schema.experiment_schedule)
                    .where(schema.experiment_schedule.c.experiment_id == experiment_id)
                    .order_by(schema.experiment_schedule.c.scheduled_order)
                )
                .mappings()
                .all()
            )
            attempts = (
                connection.execute(
                    select(schema.experiment_runs)
                    .where(schema.experiment_runs.c.experiment_id == experiment_id)
                    .order_by(
                        schema.experiment_runs.c.scheduled_order,
                        schema.experiment_runs.c.attempt_number,
                    )
                )
                .mappings()
                .all()
            )
            return {
                **dict(experiment),
                "configurations": [dict(row) for row in configurations],
                "schedule": [dict(row) for row in schedule],
                "attempts": [dict(row) for row in attempts],
                "progress": self._progress(schedule, attempts),
            }

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(schema.experiments)
                    .order_by(schema.experiments.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self.get(row["experiment_id"]) for row in rows if row is not None]  # type: ignore[misc]

    def raw_runs(self, experiment_id: str) -> list[RawExperimentRun]:
        record = self.get(experiment_id)
        if record is None:
            raise KeyError(experiment_id)
        strategies = {
            row["configuration_id"]: row["strategy"]
            for row in record["configurations"]
        }
        return [
            RawExperimentRun.model_validate(
                attempt["payload"]
                | {
                    "strategy": attempt["payload"].get("strategy")
                    or strategies.get(attempt["payload"]["configuration_id"])
                }
            )
            for attempt in record["attempts"]
        ]

    def audit_timeout_replacements(self, experiment_id: str) -> int:
        """Repair legacy timeout classification without deleting replacement attempts."""
        repaired = 0
        with self.engine.begin() as connection:
            schedules = connection.execute(
                select(schema.experiment_schedule).where(
                    schema.experiment_schedule.c.experiment_id == experiment_id
                )
            ).mappings().all()
            for schedule in schedules:
                attempts = connection.execute(
                    select(schema.experiment_runs)
                    .where(
                        schema.experiment_runs.c.experiment_id == experiment_id,
                        schema.experiment_runs.c.scheduled_order
                        == schedule["scheduled_order"],
                    )
                    .order_by(schema.experiment_runs.c.attempt_number)
                ).mappings().all()
                if len(attempts) < 2:
                    continue
                first = attempts[0]
                reason = str(first["failure_reason"] or "").lower()
                if not (
                    first["validity"] == "infrastructure_failure"
                    and reason.startswith("overall run timeout exceeded")
                ):
                    continue
                first_payload = dict(first["payload"])
                first_payload.update(
                    validity="valid", classification="benchmark_failure"
                )
                connection.execute(
                    update(schema.experiment_runs)
                    .where(schema.experiment_runs.c.attempt_id == first["attempt_id"])
                    .values(
                        validity="valid",
                        classification="benchmark_failure",
                        classification_note=(
                            "audited: configured agent timeout is a benchmark failure"
                        ),
                        payload=first_payload,
                    )
                )
                for replacement in attempts[1:]:
                    payload = dict(replacement["payload"])
                    payload.update(
                        validity="protocol_excluded",
                        classification="protocol_excluded",
                    )
                    connection.execute(
                        update(schema.experiment_runs)
                        .where(
                            schema.experiment_runs.c.attempt_id
                            == replacement["attempt_id"]
                        )
                        .values(
                            validity="protocol_excluded",
                            classification="protocol_excluded",
                            classification_note=(
                                "excluded: replacement launched after an agent timeout "
                                f"that is valid benchmark data ({first['run_id']})"
                            ),
                            payload=payload,
                        )
                    )
                connection.execute(
                    update(schema.experiment_schedule)
                    .where(
                        schema.experiment_schedule.c.experiment_id == experiment_id,
                        schema.experiment_schedule.c.scheduled_order
                        == schedule["scheduled_order"],
                    )
                    .values(
                        valid_run_id=first["run_id"],
                        finished_at=first["finished_at"],
                    )
                )
                repaired += 1
        return repaired

    @staticmethod
    def _progress(schedule: Any, attempts: Any) -> dict[str, int]:
        classifications = CounterLike(
            str(attempt["classification"])
            for attempt in attempts
            if attempt["validity"] == "valid"
        )
        return {
            "planned": len(schedule),
            "completed": sum(row["status"] == "completed" for row in schedule),
            "benchmark_successes": classifications["benchmark_success"],
            "benchmark_failures": classifications["benchmark_failure"],
            "infrastructure_failures": sum(
                attempt["validity"] == "infrastructure_failure" for attempt in attempts
            ),
            "protocol_exclusions": sum(
                attempt["validity"] == "protocol_excluded" for attempt in attempts
            ),
            "pending": sum(row["status"] == "pending" for row in schedule),
            "running": sum(row["status"] == "running" for row in schedule),
        }


class CounterLike(dict[str, int]):
    def __init__(self, values: Any) -> None:
        super().__init__()
        for value in values:
            self[value] = self.get(value, 0) + 1

    def __missing__(self, key: str) -> int:
        return 0
