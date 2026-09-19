"""Service logging is separate from benchmark traces."""

import json
import logging

logger = logging.getLogger("agentscope.service")


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log(event: str, *, run_id: str | None = None, **fields: str | bool | int) -> None:
    logger.info(json.dumps({"event": event, "run_id": run_id, **fields}, sort_keys=True))
