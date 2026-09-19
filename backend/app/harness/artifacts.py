"""Atomic local JSON/patch export for Phase 2 runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.run import ArtifactMetadata, ArtifactPaths, RunResult
from app.telemetry.events import AnyTraceEvent

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class TraceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    task_id: str
    agent_name: str
    events: tuple[AnyTraceEvent, ...]


class ArtifactStore:
    def __init__(self, root: Path | str = "artifacts") -> None:
        self.root = Path(root).expanduser().resolve()

    def paths(self, run_id: str) -> ArtifactPaths:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("unsafe run id for artifact path")
        run_directory = self.root / "runs" / run_id
        return ArtifactPaths(
            run_directory=str(run_directory),
            trace=str(run_directory / "trace.json"),
            patch=str(run_directory / "patch.diff"),
            run=str(run_directory / "run.json"),
        )

    async def write(
        self,
        result: RunResult,
        *,
        replace: bool = False,
    ) -> tuple[ArtifactMetadata, ...]:
        if result.artifacts is None:
            raise ValueError("run result has no artifact paths")
        await asyncio.to_thread(self._write_sync, result, replace=replace)
        return await asyncio.to_thread(self._metadata, result.artifacts)

    @staticmethod
    def _metadata(paths: ArtifactPaths) -> tuple[ArtifactMetadata, ...]:
        records = []
        for kind, name in (("trace", paths.trace), ("patch", paths.patch), ("run", paths.run)):
            content = Path(name).read_bytes()
            records.append(
                ArtifactMetadata(
                    artifact_type=kind,
                    path=name,
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
        return tuple(records)

    def _write_sync(self, result: RunResult, *, replace: bool = False) -> None:
        assert result.artifacts is not None
        run_directory = Path(result.artifacts.run_directory)
        run_directory.mkdir(parents=True, exist_ok=replace)
        trace = TraceDocument(
            run_id=result.run_id,
            task_id=result.task_id,
            agent_name=result.agent_name,
            events=result.events,
        )
        summary = result.model_dump(
            mode="json",
            exclude={"events", "git_diff", "artifact_metadata"},
        )
        _atomic_write(Path(result.artifacts.trace), _json(trace.model_dump(mode="json")))
        _atomic_write(Path(result.artifacts.patch), result.git_diff)
        _atomic_write(Path(result.artifacts.run), _json(summary))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
