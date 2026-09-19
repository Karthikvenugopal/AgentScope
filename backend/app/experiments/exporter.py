"""Portable raw and aggregate result artifacts independent of database lifetime."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.experiments.analysis import analyze
from app.experiments.models import ExperimentSpec, RawExperimentRun
from app.experiments.repository import ExperimentRepository


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def export_results(
    repository: ExperimentRepository,
    experiment_id: str,
    output_root: Path,
) -> Path:
    record = repository.get(experiment_id)
    if record is None:
        raise KeyError(experiment_id)
    spec = ExperimentSpec.model_validate(record["spec"])
    runs = repository.raw_runs(experiment_id)
    analysis = analyze(runs, bootstrap_seed=spec.bootstrap_seed)
    target = output_root / experiment_id
    target.mkdir(parents=True, exist_ok=True)

    _write_json(
        target / "experiment.json",
        {
            key: value
            for key, value in record.items()
            if key not in {"schedule", "attempts", "configurations"}
        }
        | {
            "spec": spec.model_dump(mode="json"),
            "configurations": record["configurations"],
        },
    )
    _write_csv(
        target / "schedule.csv",
        record["schedule"],
        (
            "scheduled_order",
            "task_id",
            "configuration_id",
            "repetition",
            "status",
            "valid_run_id",
            "attempt_count",
        ),
    )
    raw_rows = [run.model_dump(mode="json") for run in runs]
    _write_csv(target / "raw_runs.csv", raw_rows, tuple(RawExperimentRun.model_fields))
    task_rows = analysis["task_aggregates"]
    task_fields = tuple(task_rows[0]) if task_rows else ("task_id", "configuration_id")
    _write_csv(target / "task_aggregates.csv", task_rows, task_fields)
    _write_json(target / "strategy_summary.json", analysis["strategy_summary"])
    _write_json(target / "pairwise_comparisons.json", analysis["pairwise_comparisons"])
    replacements = {
        attempt["replacement_for_run_id"]: attempt["run_id"]
        for attempt in record["attempts"]
        if attempt.get("replacement_for_run_id")
    }
    _write_json(
        target / "exclusions.json",
        [
            {
                "attempt_id": attempt["attempt_id"],
                "scheduled_order": attempt["scheduled_order"],
                "attempt_number": attempt["attempt_number"],
                "run_id": attempt["run_id"],
                "failure_reason": attempt["failure_reason"],
                "classification_note": attempt.get("classification_note"),
                "replacement_run_id": replacements.get(attempt["run_id"]),
                "started_at": attempt["started_at"],
                "finished_at": attempt["finished_at"],
                "raw_run": attempt["payload"],
            }
            for attempt in record["attempts"]
            if attempt["validity"] != "valid"
        ],
    )
    _write_json(target / "correction_analysis.json", analysis["corrections"])
    _write_json(target / "parallel_candidate_analysis.json", analysis["parallel_candidates"])
    (target / "experiment_summary.md").write_text(
        _summary_markdown(record, spec, analysis), encoding="utf-8"
    )
    return target


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for field, value in row.items()
                }
            )


def _summary_markdown(
    record: dict[str, Any], spec: ExperimentSpec, analysis: dict[str, Any]
) -> str:
    provider_versions = json.dumps(
        record.get("provenance", {}).get("provider_versions", {}), sort_keys=True
    )
    lines = [
        f"# {spec.name}",
        "",
        "> Technical experiment output, not a leaderboard or overall ranking.",
        "",
        "## Research question",
        "",
        spec.research_question,
        "",
        "## Design",
        "",
        f"- Benchmark: {spec.benchmark_name} v{spec.benchmark_version}",
        f"- Manifest SHA-256: `{spec.benchmark_manifest_hash}`",
        f"- Tasks: {len(spec.task_ids)}",
        f"- Configurations: {len(spec.configurations)}",
        f"- Repetitions per task/configuration: {spec.repetitions}",
        f"- Random schedule seed: {spec.random_seed}",
        f"- Task-cluster bootstrap seed: {spec.bootstrap_seed}",
        "- Cross-run concurrency: 1; internal parallel strategy concurrency remains treatment.",
        f"- Provider versions: `{provider_versions}`",
        "",
        "## Completion",
        "",
        f"- Status: {record['status']}",
        f"- Valid runs: {analysis['valid_runs']} / {spec.run_count}",
        f"- Invalid infrastructure attempts: {analysis['invalid_attempts']}",
        f"- Protocol-excluded replacement attempts: {analysis['protocol_exclusions']}",
        "",
        "## Strategy summaries",
        "",
        "| Configuration | Successes | Mean task success | Bootstrap 95% CI "
        "| Median wall ms | Median tokens | Median tools | Median concurrency factor |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for configuration_id, summary in analysis["strategy_summary"].items():
        ci = summary["success_bootstrap_95_ci"]
        wall = summary["all_runs"]["task_wall_time_ms"]["median"]
        tokens = summary["all_runs"]["total_tokens"]["median"]
        tools = summary["all_runs"]["provider_tool_calls"]["median"]
        concurrency = summary["all_runs"]["concurrency_factor"]["median"]
        lines.append(
            f"| {configuration_id} | {summary['benchmark_successes']}/{summary['valid_runs']} "
            f"| {_number(summary['mean_task_success_probability'])} "
            f"| [{_number(ci[0])}, {_number(ci[1])}] | {_number(wall)} "
            f"| {_number(tokens)} | {_number(tools)} | {_number(concurrency)} |"
        )
    lines.extend(
        [
            "",
            "## Paired task differences",
            "",
            "Positive values mean the left-named configuration has the larger metric.",
            "",
            "| Pair | Metric | Mean difference | Median difference "
            "| Bootstrap 95% CI | Paired tasks |",
            "| --- | --- | ---: | ---: | --- | ---: |",
        ]
    )
    for pair, metrics in analysis["pairwise_comparisons"].items():
        for metric, result in metrics.items():
            ci = result["bootstrap_95_ci"]
            lines.append(
                f"| {pair} | {metric} | {_number(result['mean_difference'])} "
                f"| {_number(result['median_difference'])} "
                f"| [{_number(ci[0])}, {_number(ci[1])}] "
                f"| {result['paired_task_count']} |"
            )
    corrections = analysis["corrections"]
    parallel = analysis["parallel_candidates"]
    correction_requested = _number(corrections["correction_requested_fraction"])
    correction_changed = _number(corrections["changed_patch_fraction_among_corrections"])
    visible_improved = _number(
        corrections["visible_test_improved_fraction_among_corrections"]
    )
    selections = json.dumps(parallel["selection_distribution"], sort_keys=True)
    lines.extend(
        [
            "",
            "Confidence intervals are descriptive task-cluster bootstrap intervals, not "
            "automatic significance claims.",
            "",
            "## Corrections and parallel candidates",
            "",
            f"- Staged correction requests: {correction_requested} "
            f"of {corrections['eligible_runs']} eligible runs.",
            f"- Patch changed among corrections: {correction_changed}.",
            f"- Visible-test improvement among corrections: {visible_improved}.",
            "- Pre-correction hidden verification: unavailable by design.",
            f"- Parallel runs: {parallel['runs']}; mean completed candidate count: "
            f"{_number(parallel['mean_candidate_count'])}; candidate failures: "
            f"{parallel['candidate_failures']}.",
            f"- Selection distribution: `{selections}`.",
            "- Unselected candidates were never officially verified.",
            "",
            "## Integrity and limitations",
            "",
            "Official independent verification is the binary correctness outcome. Repetitions "
            "are averaged within task × configuration before aggregation, so repeated runs are "
            "not treated as independent task samples. Resource summaries include all valid runs; "
            "successful-only summaries are separately labeled. Unselected parallel candidates "
            "were never officially verified.",
            "",
            "This study has 12 project-authored tasks and three repetitions, heuristic difficulty "
            "labels, version-dependent provider behavior, and local-environment latency. It has no "
            "GPU telemetry and does not infer TTFT, ITL, or generation throughput when "
            "unavailable. "
            "Results do not generalize to all coding workloads.",
            "",
        ]
    )
    return "\n".join(lines)


def _number(value: Any) -> str:
    return "undefined" if value is None else f"{float(value):.4g}"
