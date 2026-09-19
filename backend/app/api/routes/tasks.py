from fastapi import APIRouter, Query

from app.api.dependencies import Service
from app.api.schemas import TaskDetail, TaskMetadata
from app.models.task import TaskId

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", summary="List benchmark metadata without verifier material")
async def tasks(
    service: Service,
    source: str | None = None,
    dataset: str | None = None,
    language: str | None = None,
    difficulty: str | None = None,
    tag: str | None = Query(default=None),
) -> list[TaskMetadata]:
    filters = {
        key: value
        for key, value in {
            "source": source,
            "dataset": dataset,
            "language": language,
            "difficulty": difficulty,
            "tag": tag,
        }.items()
        if value is not None
    }
    return [TaskMetadata.model_validate(t) for t in await service.tasks(filters)]


@router.get("/{task_id}", summary="Get agent-visible benchmark configuration")
async def task(task_id: TaskId, service: Service) -> TaskDetail:
    return TaskDetail.model_validate(await service.task(task_id))
