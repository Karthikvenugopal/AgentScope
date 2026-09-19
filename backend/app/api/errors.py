"""Consistent errors; never include validation input or exception repr."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.schemas import ErrorResponse
from app.services.errors import ServiceError
from app.services.logging import log

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        404: "Task, run, or artifact not found",
        409: "Artifact integrity failure",
        413: "Request body too large",
        422: "Invalid request, configuration, or unsupported agent/strategy",
        503: "Required dependency unavailable or queue full",
    }.items()
}


def error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_errors(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error(exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        configuration = any("configuration" in e["loc"] for e in exc.errors())
        return error(
            "invalid_configuration" if configuration else "invalid_request",
            "Request validation failed",
            422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error("invalid_request", "Request could not be processed", exc.status_code)

    @app.exception_handler(Exception)
    async def unavailable(request: Request, exc: Exception) -> JSONResponse:
        log("service_unavailable", exception_type=type(exc).__name__)
        return error("service_unavailable", "Service is temporarily unavailable", 503)


class SafeErrorBoundary:
    """Avoid ASGI server traceback logs containing SQL parameters or credentials."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            log("service_unavailable", exception_type=type(exc).__name__)
            if not started:
                await error("service_unavailable", "Service is temporarily unavailable", 503)(
                    scope, receive, send
                )
