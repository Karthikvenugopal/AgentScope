from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.dependencies import Service
from app.api.schemas import (
    ArtifactSummary,
    CreateRunRequest,
    QueuedRun,
    ResourceId,
    RunDetail,
    RunPage,
    TracePage,
    detail,
    public_event,
    summary,
)
from app.harness.limits import RunLimits
from app.models.run import RunStatus
from app.strategies.models import StrategyConfiguration

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.post("", status_code=202, summary="Queue an available benchmark strategy run")
async def create_run(body: CreateRunRequest, service: Service, response: Response) -> QueuedRun:
    roles = {"planner", "implementer", "implementers", "reviewer"}
    limits = RunLimits.model_validate(body.configuration.model_dump(exclude={"model", *roles}))
    role_data = body.configuration.model_dump(include=roles, exclude_none=True)
    run_id = await service.submit(
        body.task_id,
        body.agent,
        body.strategy,
        limits,
        model=body.configuration.model,
        roles=StrategyConfiguration.model_validate(role_data) if role_data else None,
    )
    response.headers["Location"] = f"/api/v1/runs/{run_id}"
    return QueuedRun(run_id=run_id)


@router.get("", summary="List newest runs with bounded pagination and filters")
async def runs(
    service: Service,
    limit: PageLimit = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    task_id: Annotated[str | None, Query(max_length=80)] = None,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    strategy: Annotated[str | None, Query(max_length=50)] = None,
    status: RunStatus | None = None,
) -> RunPage:
    filters = {
        k: v
        for k, v in {
            "task_id": task_id,
            "agent_name": agent,
            "strategy": strategy,
            "status": status.value if status else None,
        }.items()
        if v is not None
    }
    rows = await service.listing(limit, offset, filters)
    return RunPage(items=[summary(r) for r in rows], limit=limit, offset=offset)


@router.get("/{run_id}", summary="Get persisted lifecycle, verification, and metrics")
async def run(run_id: ResourceId, service: Service) -> RunDetail:
    return detail(await service.get(run_id))


@router.get("/{run_id}/trace", summary="Poll ordered trace events after a sequence number")
async def trace(
    run_id: ResourceId,
    service: Service,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TracePage:
    events = [public_event(e) for e in await service.trace(run_id, after_sequence, limit)]
    return TracePage(
        events=events, next_after_sequence=events[-1].sequence_number if events else after_sequence
    )


@router.get(
    "/{run_id}/patch",
    summary="Get a hash-validated patch",
    response_class=Response,
    responses={200: {"content": {"text/x-diff": {"schema": {"type": "string"}}}}},
)
async def patch(run_id: ResourceId, service: Service) -> Response:
    return Response(
        await service.patch(run_id),
        media_type="text/x-diff",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{run_id}/artifacts", summary="Get artifact sizes and hashes without host paths")
async def artifacts(run_id: ResourceId, service: Service) -> list[ArtifactSummary]:
    return detail(await service.get(run_id)).artifacts
