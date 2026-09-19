"""Application factory. Run with uvicorn app.main:create_app --factory --workers 1."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.body_limit import BodyLimitMiddleware
from app.api.errors import ERROR_RESPONSES, SafeErrorBoundary, install_errors
from app.api.routes import agents, experiments, health, metrics, runs, tasks
from app.config import Settings
from app.services.logging import configure_logging
from app.services.run_service import RunService
from app.storage.repository import PostgresRunRepository


def create_app(settings: Settings | None = None, *, service: RunService | None = None) -> FastAPI:
    configuration = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        runtime = service or RunService(
            configuration,
            PostgresRunRepository.from_url(configuration.database_url.get_secret_value()),
        )
        app.state.run_service = runtime
        try:
            try:
                await runtime.start()
            except Exception:
                raise RuntimeError(
                    "API initialization failed; check database, migrations, "
                    "and coordinator ownership"
                ) from None
            yield
        finally:
            try:
                await runtime.close()
            except Exception:
                raise RuntimeError(
                    "API shutdown failed; check database and container cleanup"
                ) from None

    app = FastAPI(
        title="AgentScope Run Management API",
        version="1.0.0",
        lifespan=lifespan,
        description=(
            "Isolated coding-agent strategies with independent verification. "
            "Local trusted use only; no authentication."
        ),
        responses=ERROR_RESPONSES,
    )
    app.add_middleware(BodyLimitMiddleware, maximum=configuration.max_request_bytes)
    app.add_middleware(SafeErrorBoundary)
    install_errors(app)
    for router in (
        health.router,
        tasks.router,
        runs.router,
        metrics.router,
        agents.router,
        agents.strategy_router,
        experiments.router,
    ):
        app.include_router(router)
    return app
