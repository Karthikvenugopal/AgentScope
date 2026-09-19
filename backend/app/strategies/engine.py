"""Bounded strategy decisions, independent of providers, Docker, and verification."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from app.strategies.models import (
    Plan,
    Review,
    Role,
    RoleConfiguration,
    RoleMetrics,
    StrategyConfiguration,
    StrategyMetrics,
    StrategyName,
    StrategyResult,
    SubExecution,
)
from app.strategies.parsing import structured_output


class RoleExecutor(Protocol):
    async def __call__(
        self,
        role: Role,
        configuration: RoleConfiguration,
        candidate_id: str | None,
        instructions: str,
        source_execution_id: str | None = None,
    ) -> SubExecution: ...


@dataclass
class StrategyContext:
    invoke: RoleExecutor
    emit: Callable[[str, dict[str, object]], Awaitable[None]]
    configuration: StrategyConfiguration
    result: StrategyResult


class ExecutionStrategy[ContextT, ResultT](Protocol):
    async def execute(self, context: ContextT) -> ResultT: ...


def _sum_known(executions: list[SubExecution], field: str) -> int | None:
    values = [getattr(e.inference, field) for e in executions]
    return sum(values) if values and all(type(v) is int for v in values) else None


def aggregate_strategy(result: StrategyResult, elapsed_ms: float) -> StrategyMetrics:
    executions = result.executions
    provider = [e for e in executions if e.provider != "mock"]

    # Timestamp boundaries are for overlap only; durations are monotonic measurements.
    def peak(items: list[SubExecution]) -> int:
        edges = [(e.started_at, 1) for e in items] + [(e.finished_at, -1) for e in items]
        active = maximum = 0
        for _, change in sorted(edges, key=lambda pair: (pair[0], pair[1])):
            active += change
            maximum = max(maximum, active)
        return maximum

    process_metadata = [e.provider_metadata for e in provider if e.provider_metadata is not None]
    edges = sorted(
        [(m.process_started_at, 1) for m in process_metadata if m.process_started_at]
        + [(m.process_finished_at, -1) for m in process_metadata if m.process_finished_at],
        key=lambda edge: (edge[0], edge[1]),
    )
    active = process_peak = 0
    provider_wall = 0.0
    previous = None
    for timestamp, change in edges:
        if active > 0 and previous is not None:
            provider_wall += max(0, (timestamp - previous).total_seconds() * 1000)
        active += change
        process_peak = max(process_peak, active)
        previous = timestamp
    summed = sum(m.process_duration_ms or 0 for m in process_metadata)
    complete_process_metrics = len(process_metadata) == len(provider) and all(
        m.process_duration_ms is not None
        and m.process_started_at is not None
        and m.process_finished_at is not None
        for m in process_metadata
    )
    return StrategyMetrics(
        strategy_wall_time_ms=elapsed_ms,
        summed_execution_time_ms=sum(e.duration_ms for e in executions),
        summed_provider_execution_time_ms=summed if complete_process_metrics else None,
        wall_clock_provider_execution_time_ms=provider_wall if complete_process_metrics else None,
        peak_concurrent_agents=peak(executions),
        peak_concurrent_provider_processes=process_peak if complete_process_metrics else None,
        concurrency_factor=summed / elapsed_ms
        if provider and complete_process_metrics and elapsed_ms > 0
        else None,
        provider_invocations=len(provider),
        provider_tool_calls=sum(e.tool_calls for e in provider),
        input_tokens=_sum_known(executions, "input_tokens"),
        output_tokens=_sum_known(executions, "output_tokens"),
        total_tokens=_sum_known(executions, "total_tokens"),
        per_role={
            role: RoleMetrics(
                invocations=len(group),
                duration_ms=sum(e.duration_ms for e in group),
                tool_calls=sum(e.tool_calls for e in group),
                input_tokens=_sum_known(group, "input_tokens"),
                output_tokens=_sum_known(group, "output_tokens"),
                total_tokens=_sum_known(group, "total_tokens"),
            )
            for role in {e.role for e in executions}
            if (group := [e for e in executions if e.role == role])
        },
    )


class OrchestratedStrategy:
    def __init__(self, name: StrategyName) -> None:
        self.name = name

    async def execute(self, context: StrategyContext) -> StrategyResult:
        result, config = context.result, context.configuration
        started = monotonic()
        completed = False
        await context.emit("strategy_started", {"strategy": self.name})

        async def invoke(
            role: Role,
            cfg: RoleConfiguration,
            candidate: str | None,
            prompt: str,
            source: str | None = None,
        ) -> SubExecution:
            execution = await context.invoke(role, cfg, candidate, prompt, source)
            result.executions.append(execution)
            return execution

        def require(execution: SubExecution) -> SubExecution:
            if execution.status != "completed":
                raise RuntimeError(f"{execution.role} execution failed: {execution.failure_reason}")
            return execution

        try:
            if self.name == "single":
                candidate = require(await invoke("implementer", config.implementer, "A", ""))
                result.selected_candidate = candidate.candidate_id
                result.candidate_count = 1
                completed = True
                return result
            planner = require(
                await invoke(
                    "planner",
                    config.planner,
                    None,
                    "Inspect repository context. Do not implement. Return JSON with analysis, "
                    "steps (nonempty list), files_likely_relevant (list).",
                )
            )
            result.plan = structured_output(planner.output, Plan)
            plan = result.plan.model_dump_json()
            prompt = f"Implement the original task using this plan: {plan}"
            if self.name == "parallel_implementers":
                await context.emit("parallel_group_started", {"count": config.implementers.count})
                tasks = [
                    asyncio.create_task(
                        invoke("implementer", config.implementers, chr(65 + i), prompt)
                    )
                    for i in range(config.implementers.count)
                ]
                try:
                    candidates = await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                candidates = [await invoke("implementer", config.implementer, "A", prompt)]
            result.candidate_count = len(candidates)
            eligible = [e for e in candidates if e.status == "completed"]
            if not eligible:
                raise RuntimeError("all implementation candidates failed")
            summaries = [
                {
                    "candidate_id": e.candidate_id,
                    "patch": e.patch,
                    "files_changed": e.files_changed,
                    "visible_test_exit_code": e.visible_test_exit_code,
                    "visible_test_output": e.visible_test_output,
                    "tool_calls": e.tool_calls,
                    "summary": e.output,
                }
                for e in eligible
            ]
            review = require(
                await invoke(
                    "reviewer",
                    config.reviewer,
                    None,
                    f"Original plan: {plan}\nCandidates: {json.dumps(summaries)}\n"
                    "Review requirements, patch complexity and visible tests. Return JSON with "
                    "decision (approve or revise), issues, suggested_changes, selected_candidate "
                    "(one listed candidate ID), rationale. Do not implement. "
                    "No hidden results exist.",
                )
            )
            result.review = structured_output(review.output, Review)
            selected_id = result.review.selected_candidate
            if selected_id is None and len(eligible) == 1:
                selected_id = eligible[0].candidate_id
            selected = next((e for e in eligible if e.candidate_id == selected_id), None)
            if selected is None:
                raise RuntimeError("reviewer selected an ineligible candidate")
            result.selected_candidate = selected.candidate_id
            await context.emit(
                "candidate_selected",
                {"candidate_id": selected.candidate_id, "rationale": result.review.rationale},
            )
            if self.name == "planner_implementer_reviewer" and result.review.decision == "revise":
                result.corrections = 1
                await context.emit("correction_requested", {"candidate_id": selected.candidate_id})
                correction = require(
                    await invoke(
                        "correction",
                        config.implementer,
                        selected.candidate_id,
                        f"Plan: {plan}\nCurrent patch: {selected.patch}\n"
                        f"Apply this reviewer feedback once: {result.review.model_dump_json()}",
                        selected.execution_id,
                    )
                )
                result.correction_changed_patch = correction.patch != selected.patch
                if (
                    selected.visible_test_exit_code is not None
                    and correction.visible_test_exit_code is not None
                ):
                    result.correction_improved_visible_tests = (
                        selected.visible_test_exit_code != 0
                        and correction.visible_test_exit_code == 0
                    )
            completed = True
            return result
        finally:
            result.metrics = aggregate_strategy(result, (monotonic() - started) * 1000)
            await context.emit(
                "strategy_completed",
                {
                    "selected_candidate": result.selected_candidate,
                    "status": "completed" if completed else "failed",
                },
            )
