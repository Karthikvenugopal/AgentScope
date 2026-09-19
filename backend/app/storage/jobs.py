"""PostgreSQL-backed submission ledger; no process-local run state."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, exists, func, select, text, union_all
from sqlalchemy.dialects.postgresql import insert

from app.storage import schema as s
from app.telemetry.events import AnyTraceEvent, RunFailedEvent


class QueueFullError(RuntimeError):
    pass


class JobStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lease: Connection | None = None

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(select(s.jobs.c.run_id).limit(1))

    def acquire(self) -> None:
        conn = self.engine.connect()
        try:
            if not conn.execute(text("SELECT pg_try_advisory_lock(74201940)")).scalar_one():
                raise RuntimeError("only one API coordinator may run per database")
            conn.commit()
            self._lease = conn
        except BaseException:
            conn.close()
            raise

    def release(self) -> None:
        if self._lease is not None:
            try:
                self._lease.execute(text("SELECT pg_advisory_unlock(74201940)"))
            finally:
                self._lease.close()
                self._lease = None

    def check_lease(self) -> None:
        if self._lease is None:
            raise RuntimeError("coordinator is not active")
        self._lease.execute(text("SELECT 1"))
        self._lease.commit()

    def submit(
        self,
        run_id: str,
        task_id: str,
        configuration: dict[str, Any],
        capacity: int,
        agent_name: str = "mock",
        strategy: str = "single",
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(74201941)"))
            count = conn.execute(
                select(func.count())
                .select_from(s.jobs)
                .where(
                    s.jobs.c.status.in_(("queued", "running", "verifying")),
                    ~exists(select(s.runs.c.run_id).where(s.runs.c.run_id == s.jobs.c.run_id)),
                )
            ).scalar_one()
            if count >= capacity:
                raise QueueFullError
            conn.execute(
                s.jobs.insert().values(
                    run_id=run_id,
                    task_id=task_id,
                    agent_name=agent_name,
                    strategy=strategy,
                    status="queued",
                    submitted_at=datetime.now(UTC),
                    configuration=configuration,
                )
            )

    def claim(self) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(s.jobs)
                    .where(
                        s.jobs.c.status == "queued",
                    )
                    .order_by(s.jobs.c.submitted_at, s.jobs.c.run_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            conn.execute(
                s.jobs.update()
                .where(s.jobs.c.run_id == row["run_id"])
                .values(
                    status="running",
                    started_at=datetime.now(UTC),
                )
            )
            return dict(row)

    def event(self, event: AnyTraceEvent) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(s.job_events)
                .values(
                    run_id=event.run_id,
                    sequence_number=event.sequence_number,
                    payload=event.model_dump(mode="json"),
                )
                .on_conflict_do_nothing()
            )
            if event.event_type == "verification_started":
                conn.execute(
                    s.jobs.update()
                    .where(s.jobs.c.run_id == event.run_id)
                    .values(status="verifying")
                )

    def finish(self, run_id: str, status: str, reason: str | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                s.jobs.update()
                .where(s.jobs.c.run_id == run_id)
                .values(
                    status=status,
                    finished_at=datetime.now(UTC),
                    failure_reason=reason,
                )
            )

    def fail(self, run_id: str, reason: str) -> None:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(s.jobs).where(s.jobs.c.run_id == run_id).with_for_update())
                .mappings()
                .one()
            )
            if row["status"] not in ("queued", "running", "verifying"):
                return
            seq = (
                conn.execute(
                    select(func.coalesce(func.max(s.job_events.c.sequence_number), 0)).where(
                        s.job_events.c.run_id == run_id,
                    )
                ).scalar_one()
                + 1
            )
            now = datetime.now(UTC)
            event = RunFailedEvent(
                run_id=run_id,
                event_id=f"{run_id}:{seq:06d}",
                sequence_number=seq,
                timestamp=now,
                duration_ms=max(0, (now - row["submitted_at"]).total_seconds() * 1000),
                failure_reason=reason,
            )
            conn.execute(
                s.job_events.insert().values(
                    run_id=run_id,
                    sequence_number=seq,
                    payload=event.model_dump(mode="json"),
                )
            )
            conn.execute(
                s.jobs.update()
                .where(s.jobs.c.run_id == run_id)
                .values(
                    status="failed",
                    failure_reason=reason,
                    finished_at=now,
                )
            )

    def recover(self) -> None:
        with self.engine.connect() as conn:
            ids = (
                conn.execute(
                    select(s.jobs.c.run_id).where(s.jobs.c.status.in_(("running", "verifying")))
                )
                .scalars()
                .all()
            )
        for run_id in ids:
            with self.engine.connect() as conn:
                final = conn.execute(
                    select(s.runs.c.status, s.runs.c.failure_reason).where(
                        s.runs.c.run_id == run_id,
                    )
                ).first()
            if final:
                self.finish(run_id, final.status, final.failure_reason)
            else:
                self.fail(run_id, "service interrupted before finalization")

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(s.jobs).where(s.jobs.c.run_id == run_id)).mappings().first()
            return dict(row) if row else None

    def listing(self, limit: int, offset: int, filters: dict[str, str]) -> list[dict[str, Any]]:
        columns = (
            "run_id",
            "task_id",
            "agent_name",
            "strategy",
            "status",
            "started_at",
            "finished_at",
            "failure_reason",
        )
        final = select(
            *(s.runs.c[c] for c in columns),
            func.coalesce(s.jobs.c.submitted_at, s.runs.c.started_at).label("sort_at"),
        ).select_from(s.runs.outerjoin(s.jobs, s.jobs.c.run_id == s.runs.c.run_id))
        jobs = select(
            *(s.jobs.c[c] for c in columns), s.jobs.c.submitted_at.label("sort_at")
        ).where(
            ~exists(select(s.runs.c.run_id).where(s.runs.c.run_id == s.jobs.c.run_id)),
        )
        combined = union_all(final, jobs).subquery()
        query = select(combined)
        for key, value in filters.items():
            query = query.where(combined.c[key] == value)
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    query.order_by(combined.c.sort_at.desc(), combined.c.run_id)
                    .limit(limit)
                    .offset(offset)
                ).mappings()
            ]

    def trace(self, run_id: str, after: int, limit: int) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            finalized = conn.execute(
                select(s.runs.c.run_id).where(s.runs.c.run_id == run_id)
            ).scalar_one_or_none()
            table = s.events if finalized else s.job_events
            rows = conn.execute(
                select(table.c.payload)
                .where(
                    table.c.run_id == run_id,
                    table.c.sequence_number > after,
                )
                .order_by(table.c.sequence_number)
                .limit(limit)
            ).scalars()
            return [dict(r) for r in rows]
