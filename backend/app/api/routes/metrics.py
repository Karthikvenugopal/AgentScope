from fastapi import APIRouter

from app.api.dependencies import Service
from app.api.schemas import ResourceId, detail
from app.telemetry.metrics import RunMetrics

router = APIRouter(prefix="/api/v1/runs", tags=["metrics"])


@router.get("/{run_id}/metrics", summary="Get measured run aggregates; null until available")
async def metrics(run_id: ResourceId, service: Service) -> RunMetrics | None:
    return detail(await service.get(run_id)).metrics
