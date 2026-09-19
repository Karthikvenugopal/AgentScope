"""Harness-owned isolated role invocations. No verifier or database capability."""

import asyncio
import json
import shlex
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Literal, cast

from app.agents import AgentContext, AgentTurnResult, AgentTurnStatus, CodingAgent, MockCodingAgent
from app.execution import Workspace
from app.harness.limits import RunLimits
from app.harness.snapshot import RepositorySnapshot
from app.harness.tools.base import ToolContext
from app.harness.tools.registry import ToolRegistry
from app.harness.workspace_factory import WorkspaceFactory
from app.models.task import Task
from app.providers.models import ProviderName
from app.providers.runtime import ProviderRuntime
from app.strategies.engine import OrchestratedStrategy, StrategyContext
from app.strategies.models import (
    Role,
    RoleConfiguration,
    StrategyConfiguration,
    StrategyResult,
    SubExecution,
)
from app.telemetry.events import AnyTraceEvent, ProviderTraceEvent, StrategyTraceEvent
from app.telemetry.provider_metrics import provider_metrics
from app.telemetry.recorder import EventT, TraceRecorder


class ScopedRecorder(TraceRecorder):
    def __init__(
        self, root: TraceRecorder, execution_id: str, role: Role, candidate_id: str | None
    ) -> None:
        super().__init__(root.run_id)
        self.root = root
        self.scope = dict(
            execution_id=execution_id,
            parent_execution_id=root.run_id,
            role=role,
            candidate_id=candidate_id,
        )

    @property
    def events(self) -> tuple[AnyTraceEvent, ...]:
        return tuple(e for e in self.root.events if e.execution_id == self.scope["execution_id"])

    async def emit(self, event_class: type[EventT], **fields: Any) -> EventT:
        return await self.root.emit(event_class, **{**self.scope, **fields})


def assistant_output(events: tuple[AnyTraceEvent, ...]) -> str:
    messages: list[str] = []
    for event in events:
        if not isinstance(event, ProviderTraceEvent):
            continue
        native = event.payload.get("native", {})
        if (
            native.get("type") == "item.completed"
            and native.get("item", {}).get("type") == "agent_message"
        ):
            messages.append(str(native["item"].get("text", "")))
        elif native.get("type") == "assistant":
            messages.extend(
                str(b.get("text", ""))
                for b in native.get("message", {}).get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            )
        elif native.get("type") == "result" and isinstance(native.get("result"), str):
            messages.append(native["result"])
    output = "\n".join(messages)
    if len(output.encode()) > 65536:
        raise ValueError("role response exceeds structured-output budget")
    return output


class StrategyAgent(CodingAgent):
    """One harness turn orchestrates bounded, independently isolated role sessions."""

    def __init__(
        self,
        *,
        result: StrategyResult,
        configuration: StrategyConfiguration,
        baseline: Workspace,
        factory: WorkspaceFactory,
        providers: ProviderRuntime | None,
        limits: RunLimits,
        recorder: TraceRecorder,
    ) -> None:
        self.result, self.config = result, configuration
        self.baseline, self.factory, self.providers = baseline, factory, providers
        self.limits, self.recorder = limits, recorder
        self.workspaces: dict[str, Workspace] = {}
        self.task: Task | None = None
        self.snapshot: RepositorySnapshot | None = None

    @property
    def name(self) -> str:
        return "orchestrated"

    async def emit(self, name: str, details: dict[str, object]) -> None:
        await self.recorder.emit(StrategyTraceEvent, event_type=name, details=details)

    async def run_turn(
        self, task: Task, tools: ToolRegistry, context: AgentContext
    ) -> AgentTurnResult:
        del tools, context
        self.task = task
        self.snapshot = await RepositorySnapshot.capture(self.baseline)
        try:
            await OrchestratedStrategy(self.result.strategy).execute(
                StrategyContext(self.invoke, self.emit, self.config, self.result)
            )
            selected = next(
                e
                for e in reversed(self.result.executions)
                if e.candidate_id == self.result.selected_candidate
                and e.role in ("implementer", "correction")
                and e.status == "completed"
            )
            installation = asyncio.create_task(
                asyncio.to_thread(
                    _install,
                    self.workspaces[selected.execution_id].host_path,
                    self.baseline.host_path,
                )
            )
            try:
                await asyncio.shield(installation)
            except asyncio.CancelledError:
                await installation
                raise
            return AgentTurnResult(
                status=AgentTurnStatus.COMPLETED,
                summary="Selected candidate installed; awaiting independent verification.",
            )
        finally:
            errors = await asyncio.gather(
                *(w.close() for w in self.workspaces.values()), return_exceptions=True
            )
            if any(isinstance(error, BaseException) for error in errors):
                raise RuntimeError("strategy workspace cleanup failed")

    async def invoke(
        self,
        role: Role,
        configuration: RoleConfiguration,
        candidate_id: str | None,
        instructions: str,
        source_execution_id: str | None = None,
    ) -> SubExecution:
        assert self.task is not None and self.snapshot is not None
        execution_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"agentscope:{self.recorder.run_id}:{role}:{candidate_id}"
        ).hex
        recorder = ScopedRecorder(self.recorder, execution_id, role, candidate_id)
        started_at, started = datetime.now(UTC), monotonic()
        metadata = None
        status: str = "completed"
        output, failure, patch, visible_output = "", None, "", ""
        files: tuple[str, ...] = ()
        visible_exit = None
        visible_timeout = visible_truncated = cancelled = False
        parallel_candidate = (
            self.result.strategy == "parallel_implementers" and role == "implementer"
        )
        if parallel_candidate:
            await recorder.emit(
                StrategyTraceEvent,
                event_type="parallel_candidate_started",
                provider=configuration.agent,
            )
        await recorder.emit(
            StrategyTraceEvent, event_type=f"{role}_started", provider=configuration.agent
        )
        workspace = None
        try:
            source = self.workspaces[source_execution_id] if source_execution_id else self.baseline
            workspace = await self.factory.create(
                source.host_path, run_id=execution_id, keep_workspace=False
            )
            self.workspaces[execution_id] = workspace
            if not workspace.execution_is_isolated:
                raise RuntimeError("strategy requires isolated workspaces")
            role_task = self.task.model_copy(
                update={
                    "description": self.task.description
                    + "\n\n"
                    + f"Role: {role}. "
                    + instructions,
                    "verification": None,
                }
            )
            if configuration.agent != "mock":
                if self.providers is None:
                    raise RuntimeError("provider runtime unavailable")
                metadata = await self.providers.execute(
                    ProviderName(configuration.agent),
                    configuration.model,
                    role_task,
                    workspace,
                    self.limits,
                    recorder,
                    role=role,
                )
                output = assistant_output(recorder.events)
            else:
                registry = ToolRegistry(
                    ToolContext(
                        workspace=workspace,
                        task=role_task,
                        limits=self.limits,
                        recorder=recorder,
                        snapshot=self.snapshot,
                    )
                )
                if role == "planner":
                    await registry.execute("list_directory", {"path": "."})
                    output = json.dumps(
                        {
                            "analysis": "Inspect the visible API contract.",
                            "steps": [
                                "Read source and visible tests",
                                "Correct response",
                                "Run visible tests",
                            ],
                            "files_likely_relevant": ["app.py"],
                        }
                    )
                elif role == "reviewer":
                    # Deterministic mock selection is explicitly not a model judgement.
                    candidates = [
                        e
                        for e in self.result.executions
                        if e.role == "implementer" and e.status == "completed"
                    ]
                    selected = min(
                        candidates,
                        key=lambda e: (
                            e.visible_test_exit_code != 0,
                            len(e.patch),
                            e.candidate_id or "",
                        ),
                    )
                    output = json.dumps(
                        {
                            "decision": "approve",
                            "selected_candidate": selected.candidate_id,
                            "issues": [],
                            "suggested_changes": [],
                            "rationale": "Deterministic visible-test/patch-size selection.",
                        }
                    )
                else:
                    agent = MockCodingAgent.for_incorrect_api_response()
                    await agent.start(role_task, AgentContext(run_id=execution_id))
                    for turn in range(1, self.limits.max_agent_turns + 1):
                        reply = await agent.run_turn(
                            role_task, registry, AgentContext(run_id=execution_id, turn_number=turn)
                        )
                        output = reply.summary
                        if reply.status == AgentTurnStatus.FAILED:
                            raise RuntimeError("mock implementation failed")
                        if reply.status == AgentTurnStatus.COMPLETED:
                            break
                    else:
                        raise RuntimeError("mock turn limit exceeded")
            if role in ("implementer", "correction"):
                # Visible diagnostics only; counts are not inferred from terminal output.
                test = await workspace.execute(
                    shlex.split(self.task.test_command),
                    timeout_seconds=self.limits.command_timeout_seconds,
                    max_output_bytes=min(16000, self.limits.max_captured_output_bytes),
                )
                visible_exit, visible_output = test.exit_code, test.stdout + test.stderr
                visible_timeout = test.timed_out
                visible_truncated = test.stdout_truncated or test.stderr_truncated
                await recorder.emit(
                    StrategyTraceEvent,
                    event_type="candidate_tests_completed",
                    details={
                        "exit_code": test.exit_code,
                        "duration_ms": test.duration_ms,
                        "timed_out": test.timed_out,
                        "output_truncated": visible_truncated,
                    },
                )
            await workspace.freeze()
            patch, files = await self.snapshot.diff(workspace)
            if len(patch.encode()) > 65536:
                raise RuntimeError("candidate patch exceeds review context budget")
        except asyncio.CancelledError:
            status, failure, cancelled = "timed_out", "role cancelled by enclosing run", True
        except Exception as exc:
            status = "timed_out" if isinstance(exc, TimeoutError) else "failed"
            failure = f"{type(exc).__name__}: {exc}"
        inference, tools, _, _ = provider_metrics(recorder.events)
        if metadata is None:
            metadata = next(
                (
                    e.metadata
                    for e in reversed(recorder.events)
                    if isinstance(e, ProviderTraceEvent) and e.metadata is not None
                ),
                None,
            )
        execution = SubExecution(
            execution_id=execution_id,
            parent_execution_id=self.recorder.run_id,
            role=role,
            provider=configuration.agent,
            candidate_id=candidate_id,
            status=cast("Literal['completed', 'failed', 'timed_out']", status),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=(monotonic() - started) * 1000,
            provider_metadata=metadata,
            inference=inference,
            tool_calls=sum(tools.values())
            + sum(e.event_type == "tool_call_started" for e in recorder.events),
            output=output,
            failure_reason=failure,
            patch=patch,
            files_changed=files,
            visible_test_exit_code=visible_exit,
            visible_test_output=visible_output,
            visible_test_timed_out=visible_timeout,
            visible_test_output_truncated=visible_truncated,
        )
        await recorder.emit(
            StrategyTraceEvent,
            event_type=f"{role}_completed",
            provider=configuration.agent,
            details={"status": status},
        )
        if parallel_candidate:
            await recorder.emit(
                StrategyTraceEvent,
                event_type="parallel_candidate_completed",
                provider=configuration.agent,
                details={"status": status},
            )
        if cancelled:
            self.result.executions.append(execution)
            raise asyncio.CancelledError
        return execution


def _install(source: Path, target: Path) -> None:
    """Copy a frozen, bounded candidate; no symlinks or external paths are followed."""
    source_files: dict[Path, bytes] = {}
    for path in source.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ValueError("unsafe candidate entry")
        if path.is_file():
            if path.stat().st_nlink != 1 or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("unsafe candidate link")
            if path.stat().st_size > 20_000_000:
                raise ValueError("candidate installation size limit")
            source_files[path.relative_to(source)] = path.read_bytes()
            if len(source_files) > 4096 or sum(map(len, source_files.values())) > 20_000_000:
                raise ValueError("candidate installation size limit")
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError("unsafe destination entry")
        if path.is_file():
            path.unlink()
    for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            path.rmdir()
    for relative, data in source_files.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
