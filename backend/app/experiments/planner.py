"""Frozen input validation and reproducibly randomized schedules."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.experiments.models import ExperimentSpec, ScheduleEntry
from app.harness.task_catalog import TaskCatalog


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_frozen_inputs(
    spec: ExperimentSpec,
    benchmark_root: Path,
) -> dict[str, Any]:
    manifest_path = benchmark_root / "manifest.json"
    actual_hash = file_sha256(manifest_path)
    if actual_hash != spec.benchmark_manifest_hash:
        raise ValueError(
            f"benchmark manifest hash differs: expected {spec.benchmark_manifest_hash}, "
            f"found {actual_hash}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "frozen": True,
        "name": spec.benchmark_name,
        "version": spec.benchmark_version,
    }
    if manifest.get("benchmark") != expected:
        raise ValueError("experiment requires the frozen AgentScope Benchmark v0.1")
    native = {task["id"]: task for task in manifest.get("tasks", [])}
    if len(native) != 12 or manifest.get("task_count") != 12:
        raise ValueError("AgentScope Benchmark v0.1 must contain exactly 12 native tasks")
    if set(spec.task_ids) - native.keys():
        raise ValueError("experiment references a task outside the frozen native benchmark")
    catalog = TaskCatalog(benchmark_root)
    catalog_tasks = {task.id: task for task in catalog.list_tasks()}
    for task_id in spec.task_ids:
        task = catalog_tasks[task_id]
        if task.provenance.source.value != "agentscope":
            raise ValueError("primary experiment cannot mix external Harbor tasks")
        if task.provenance.task_hash != native[task_id]["task_hash"]:
            raise ValueError(f"task hash differs for {task_id}")
    strategy_sources = [
        benchmark_root.parent / "backend/app/strategies/runtime.py",
        benchmark_root.parent / "backend/app/strategies/single.py",
        benchmark_root.parent / "backend/app/strategies/parsing.py",
    ]
    strategy_hash = hashlib.sha256(
        b"".join(path.read_bytes() for path in strategy_sources)
    ).hexdigest()
    return {
        "benchmark_name": spec.benchmark_name,
        "benchmark_version": spec.benchmark_version,
        "benchmark_manifest_hash": actual_hash,
        "task_count": 12,
        "task_hashes": {task_id: native[task_id]["task_hash"] for task_id in spec.task_ids},
        "strategy_implementation_hash": strategy_hash,
    }


def build_schedule(spec: ExperimentSpec) -> tuple[ScheduleEntry, ...]:
    randomizer = random.Random(spec.random_seed)
    planned: list[tuple[str, str, int]] = []
    for repetition in range(1, spec.repetitions + 1):
        tasks = list(spec.task_ids)
        randomizer.shuffle(tasks)
        for task_id in tasks:
            configurations = [configuration.id for configuration in spec.configurations]
            randomizer.shuffle(configurations)
            planned.extend(
                (task_id, configuration_id, repetition)
                for configuration_id in configurations
            )
    return tuple(
        ScheduleEntry(
            scheduled_order=index,
            task_id=task_id,
            configuration_id=configuration_id,
            repetition=repetition,
        )
        for index, (task_id, configuration_id, repetition) in enumerate(planned, 1)
    )


def plan_summary(spec: ExperimentSpec) -> dict[str, Any]:
    estimated_cost = None
    if spec.pricing is not None and spec.budget.max_tokens is not None:
        highest_rate = max(
            max(price.input_usd_per_million_tokens, price.output_usd_per_million_tokens)
            for price in spec.pricing.providers.values()
        )
        estimated_cost = spec.budget.max_tokens * highest_rate / 1_000_000
    return {
        "experiment_id": spec.experiment_id,
        "tasks": len(spec.task_ids),
        "configurations": len(spec.configurations),
        "repetitions": spec.repetitions,
        "total_planned_runs": spec.run_count,
        "estimated_maximum_provider_invocations": spec.estimated_provider_invocations,
        "estimated_upper_bound_concurrency": spec.maximum_internal_concurrency,
        "experiment_run_concurrency": spec.experiment_run_concurrency,
        "providers_required": sorted(spec.provider_requirements),
        "estimated_cost": estimated_cost,
        "estimated_cost_basis": (
            "configured max_tokens multiplied by the highest configured token rate"
            if estimated_cost is not None
            else None
        ),
        "pricing_version": spec.pricing.version if spec.pricing else None,
        "pricing_source": spec.pricing.source if spec.pricing else None,
        "spec_hash": spec.spec_hash,
    }
