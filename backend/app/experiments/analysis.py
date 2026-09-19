"""Cluster-aware experiment analysis; tasks, not repetitions, are analysis units."""

from __future__ import annotations

import hashlib
import statistics
from collections import Counter, defaultdict
from typing import Any, cast

from app.experiments.bootstrap import bootstrap_interval, percentile
from app.experiments.models import RawExperimentRun

RESOURCE_METRICS = (
    "task_wall_time_ms",
    "strategy_wall_time_ms",
    "summed_provider_execution_time_ms",
    "provider_invocations",
    "provider_tool_calls",
    "total_tokens",
    "peak_concurrent_provider_processes",
    "concurrency_factor",
)
PAIRWISE_METRICS = ("official_success", "task_wall_time_ms", "total_tokens", "provider_tool_calls")


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def task_aggregates(runs: list[RawExperimentRun]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[RawExperimentRun]] = defaultdict(list)
    for run in runs:
        if run.validity == "valid":
            grouped[(run.task_id, run.configuration_id)].append(run)
    records: list[dict[str, Any]] = []
    for (task_id, configuration_id), group in sorted(grouped.items()):
        successes = sum(run.official_success is True for run in group)
        record: dict[str, Any] = {
            "task_id": task_id,
            "configuration_id": configuration_id,
            "valid_repetitions": len(group),
            "successes": successes,
            "success_probability": successes / len(group),
            "official_test_fraction": _mean(_test_fractions(group)),
        }
        for metric in RESOURCE_METRICS:
            record[metric] = _mean(
                [
                    float(value)
                    for run in group
                    if (value := _metric_value(run, metric)) is not None
                ]
            )
        records.append(record)
    return records


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": _mean(values),
        "median": statistics.median(values) if values else None,
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
    }


def strategy_summary(
    runs: list[RawExperimentRun], *, bootstrap_seed: int
) -> dict[str, dict[str, Any]]:
    aggregates = task_aggregates(runs)
    by_configuration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for aggregate in aggregates:
        by_configuration[aggregate["configuration_id"]].append(aggregate)
    output: dict[str, dict[str, Any]] = {}
    for index, (configuration_id, tasks) in enumerate(sorted(by_configuration.items())):
        success_values = [float(task["success_probability"]) for task in tasks]
        low, high = bootstrap_interval(success_values, seed=bootstrap_seed + index)
        valid_runs = [
            run
            for run in runs
            if run.validity == "valid" and run.configuration_id == configuration_id
        ]
        successful_runs = [run for run in valid_runs if run.official_success]
        total_successes = len(successful_runs)
        summary: dict[str, Any] = {
            "task_count": len(tasks),
            "valid_runs": len(valid_runs),
            "benchmark_successes": total_successes,
            "mean_task_success_probability": _mean(success_values),
            "success_bootstrap_95_ci": [low, high],
            "all_runs": {},
            "successful_runs_only": {},
            "telemetry_totals": {},
            "efficiency": {
                "tokens_per_success": (
                    sum(run.total_tokens or 0 for run in valid_runs) / total_successes
                    if total_successes
                    and all(run.total_tokens is not None for run in valid_runs)
                    else None
                ),
                "wall_time_ms_per_success": (
                    sum(run.task_wall_time_ms or 0 for run in valid_runs) / total_successes
                    if total_successes
                    and all(run.task_wall_time_ms is not None for run in valid_runs)
                    else None
                ),
                "provider_invocations_per_success": (
                    sum(run.provider_invocations or 0 for run in valid_runs) / total_successes
                    if total_successes
                    and all(run.provider_invocations is not None for run in valid_runs)
                    else None
                ),
            },
        }
        for metric in RESOURCE_METRICS:
            summary["all_runs"][metric] = _distribution(
                [float(task[metric]) for task in tasks if task.get(metric) is not None]
            )
            successful_task_means: list[float] = []
            success_groups: dict[str, list[float]] = defaultdict(list)
            for run in successful_runs:
                value = _metric_value(run, metric)
                if value is not None:
                    success_groups[run.task_id].append(float(value))
            successful_task_means.extend(
                statistics.fmean(values) for values in success_groups.values()
            )
            summary["successful_runs_only"][metric] = _distribution(successful_task_means)
        for metric in (
            "task_wall_time_ms",
            "strategy_wall_time_ms",
            "summed_provider_execution_time_ms",
            "provider_invocations",
            "provider_tool_calls",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            available = [
                float(value)
                for run in valid_runs
                if (value := _metric_value(run, metric)) is not None
            ]
            summary["telemetry_totals"][metric] = {
                "value": sum(available) if len(available) == len(valid_runs) else None,
                "observed_subtotal": sum(available) if available else None,
                "available_runs": len(available),
                "valid_runs": len(valid_runs),
            }
        output[configuration_id] = summary
    return output


def pairwise_comparisons(
    runs: list[RawExperimentRun], *, bootstrap_seed: int
) -> dict[str, dict[str, Any]]:
    aggregates = task_aggregates(runs)
    lookup = {
        (aggregate["task_id"], aggregate["configuration_id"]): aggregate
        for aggregate in aggregates
    }
    configurations = sorted({aggregate["configuration_id"] for aggregate in aggregates})
    tasks = sorted({aggregate["task_id"] for aggregate in aggregates})
    output: dict[str, dict[str, Any]] = {}
    for left_index, left in enumerate(configurations):
        for right in configurations[left_index + 1 :]:
            pair_name = f"{left}_minus_{right}"
            metrics: dict[str, Any] = {}
            for metric in PAIRWISE_METRICS:
                field = "success_probability" if metric == "official_success" else metric
                differences = [
                    float(lookup[(task, left)][field]) - float(lookup[(task, right)][field])
                    for task in tasks
                    if (task, left) in lookup
                    and (task, right) in lookup
                    and lookup[(task, left)].get(field) is not None
                    and lookup[(task, right)].get(field) is not None
                ]
                salt = int(hashlib.sha256(f"{pair_name}:{metric}".encode()).hexdigest()[:8], 16)
                low, high = bootstrap_interval(
                    differences, seed=bootstrap_seed + salt
                )
                metrics[metric] = {
                    "paired_task_count": len(differences),
                    "mean_difference": _mean(differences),
                    "median_difference": statistics.median(differences) if differences else None,
                    "bootstrap_95_ci": [low, high],
                }
            output[pair_name] = metrics
    return output


def correction_analysis(runs: list[RawExperimentRun]) -> dict[str, Any]:
    staged = [
        run
        for run in runs
        if run.validity == "valid"
        and run.strategy == "planner_implementer_reviewer"
        and run.corrections is not None
    ]
    corrected = [run for run in staged if (run.corrections or 0) > 0]
    return {
        "eligible_runs": len(staged),
        "correction_requested_fraction": len(corrected) / len(staged) if staged else None,
        "changed_patch_fraction_among_corrections": (
            sum(run.correction_changed_patch is True for run in corrected) / len(corrected)
            if corrected
            else None
        ),
        "visible_test_improved_fraction_among_corrections": (
            sum(run.correction_improved_visible_tests is True for run in corrected)
            / len(corrected)
            if corrected
            else None
        ),
        "official_success_fraction_after_correction": (
            sum(run.official_success is True for run in corrected) / len(corrected)
            if corrected
            else None
        ),
        "pre_correction_hidden_verification": None,
    }


def parallel_candidate_analysis(runs: list[RawExperimentRun]) -> dict[str, Any]:
    parallel = [
        run
        for run in runs
        if run.validity == "valid"
        and run.strategy == "parallel_implementers"
        and run.candidate_count is not None
    ]
    selections = Counter(run.selected_candidate for run in parallel if run.selected_candidate)
    patch_sizes = [size for run in parallel for size in run.candidate_patch_sizes]
    return {
        "runs": len(parallel),
        "mean_candidate_count": _mean([float(run.candidate_count or 0) for run in parallel]),
        "candidate_failures": sum(run.candidate_failures or 0 for run in parallel),
        "selection_distribution": dict(sorted(selections.items())),
        "candidate_patch_bytes": _distribution([float(size) for size in patch_sizes]),
        "unselected_official_verification": None,
        "limitation": "Unselected candidates are never officially verified.",
    }


def analyze(runs: list[RawExperimentRun], *, bootstrap_seed: int) -> dict[str, Any]:
    valid = [run for run in runs if run.validity == "valid"]
    invalid = [run for run in runs if run.validity == "infrastructure_failure"]
    protocol_excluded = [run for run in runs if run.validity == "protocol_excluded"]
    return {
        "valid_runs": len(valid),
        "invalid_attempts": len(invalid),
        "protocol_exclusions": len(protocol_excluded),
        "task_aggregates": task_aggregates(runs),
        "strategy_summary": strategy_summary(runs, bootstrap_seed=bootstrap_seed),
        "pairwise_comparisons": pairwise_comparisons(runs, bootstrap_seed=bootstrap_seed),
        "corrections": correction_analysis(runs),
        "parallel_candidates": parallel_candidate_analysis(runs),
    }


def _test_fraction(run: RawExperimentRun) -> float | None:
    if run.official_tests_passed is None or not run.official_tests_total:
        return None
    return run.official_tests_passed / run.official_tests_total


def _metric_value(run: RawExperimentRun, metric: str) -> float | int | None:
    value = cast(float | int | None, getattr(run, metric))
    # A strategy segment cannot exceed its containing task wall time. Preserve
    # impossible source telemetry in raw_runs.csv, but exclude it from derived
    # summaries instead of silently treating it as a real duration.
    if (
        metric == "strategy_wall_time_ms"
        and value is not None
        and run.task_wall_time_ms is not None
        and value > run.task_wall_time_ms
    ):
        return None
    return value


def _test_fractions(runs: list[RawExperimentRun]) -> list[float]:
    values: list[float] = []
    for run in runs:
        value = _test_fraction(run)
        if value is not None:
            values.append(value)
    return values
