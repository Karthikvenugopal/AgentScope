from fastapi import APIRouter, Response

from app.api.dependencies import Service
from app.api.schemas import Health, Readiness

router = APIRouter(tags=["health"])


@router.get("/health", summary="Process liveness")
async def health() -> Health:
    return Health()


@router.get(
    "/ready", summary="Database and coordinator readiness", responses={503: {"model": Readiness}}
)
async def ready(service: Service, response: Response) -> Readiness:
    healthy = await service.ready()
    database_healthy = await service.database_ready()
    response.status_code = 200 if healthy else 503
    return Readiness(
        status="ready" if healthy else "not_ready",
        database="healthy" if database_healthy else "unavailable",
    )
