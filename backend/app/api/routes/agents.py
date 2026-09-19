from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import Service
from app.providers.models import ProviderAvailability

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", summary="Discover configured provider runtimes and capabilities")
async def agents(service: Service) -> list[ProviderAvailability]:
    return await service.agents()


class StrategyCapability(BaseModel):
    id: str
    name: str
    supported_roles: list[str]
    worker_counts: list[int]
    available: bool


strategy_router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@strategy_router.get("", summary="Discover bounded orchestration architectures")
async def strategies(service: Service) -> list[StrategyCapability]:
    return [
        StrategyCapability(
            id="single",
            name="Single Agent",
            supported_roles=["implementer"],
            worker_counts=[1],
            available=True,
        ),
        StrategyCapability(
            id="planner_implementer_reviewer",
            name="Planner → Implementer → Reviewer",
            supported_roles=["planner", "implementer", "reviewer"],
            worker_counts=[1],
            available=True,
        ),
        StrategyCapability(
            id="parallel_implementers",
            name="Parallel Implementers",
            supported_roles=["planner", "implementers", "reviewer"],
            worker_counts=list(range(2, service.settings.max_parallel_implementers + 1)),
            available=True,
        ),
    ]
