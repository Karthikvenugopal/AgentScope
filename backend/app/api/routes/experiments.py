"""Read-only experiment progress and cluster-aware result inspection."""

from typing import Any

from fastapi import APIRouter

from app.api.dependencies import Service

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@router.get("", summary="List controlled experiments and progress")
async def experiments(service: Service) -> list[dict[str, Any]]:
    return await service.experiment_list()


@router.get("/{experiment_id}", summary="Inspect schedule, runs, and task-level analysis")
async def experiment(experiment_id: str, service: Service) -> dict[str, Any]:
    return await service.experiment(experiment_id)
