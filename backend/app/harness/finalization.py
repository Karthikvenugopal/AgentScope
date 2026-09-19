"""Filesystem first, then one atomic database commit with artifact hashes."""

import asyncio

from app.harness.artifacts import ArtifactStore
from app.models.run import RunResult, RunStatus
from app.storage.repository import RunRepository
from app.telemetry.aggregation import RunMetricsAggregator
from app.telemetry.events import RunFailedEvent


def failed_finalization(run: RunResult, reason: str) -> RunResult:
    terminal = run.events[-1]
    event = RunFailedEvent(
        event_id=terminal.event_id,
        run_id=run.run_id,
        sequence_number=terminal.sequence_number,
        timestamp=terminal.timestamp,
        duration_ms=run.duration_ms,
        failure_reason=reason,
    )
    failed = run.model_copy(
        update={
            "status": RunStatus.FAILED,
            "failure_reason": reason,
            "events": (*run.events[:-1], event),
            "artifact_metadata": (),
        }
    )
    return failed.model_copy(update={"metrics": RunMetricsAggregator().aggregate(failed)})


async def finalize(
    run: RunResult,
    artifacts: ArtifactStore,
    repository: RunRepository | None,
) -> RunResult:
    try:
        metadata = await artifacts.write(run)
        run = run.model_copy(update={"artifact_metadata": metadata})
    except Exception as exc:
        run = failed_finalization(run, f"artifact export failed: {type(exc).__name__}: {exc}")
    if repository is not None:
        try:
            await asyncio.to_thread(repository.save, run)
        except Exception as exc:
            reason = f"PostgreSQL persistence failed: {type(exc).__name__}"
            # Connection exceptions may embed credentials; retain only the type.
            had_artifacts = bool(run.artifact_metadata)
            run = failed_finalization(run, reason).model_copy(update={"persistence_error": reason})
            if had_artifacts:
                try:
                    metadata = await artifacts.write(run, replace=True)
                    run = run.model_copy(update={"artifact_metadata": metadata})
                except Exception:
                    pass
    return run
