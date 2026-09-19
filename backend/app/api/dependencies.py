from typing import Annotated, cast

from fastapi import Depends, Request

from app.services.run_service import RunService


def get_service(request: Request) -> RunService:
    return cast(RunService, request.app.state.run_service)


Service = Annotated[RunService, Depends(get_service)]
