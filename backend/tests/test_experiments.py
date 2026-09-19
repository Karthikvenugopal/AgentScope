"""Deterministic Phase 9 planning, analysis, and failure-policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.experiments.analysis import (
    analyze,
    correction_analysis,
    pairwise_comparisons,
    parallel_candidate_analysis,
    task_aggregates,
)
from app.experiments.bootstrap import bootstrap_interval, percentile
from app.experiments.exporter import export_results
from app.experiments.models import ExperimentSpec, RawExperimentRun, load_spec
from app.experiments.planner import build_schedule, plan_summary, validate_frozen_inputs
from app.experiments.runner import classify_result
from app.models.run import RunResult, RunStatus

ROOT = Path(__file__).resolve().parents[2]
SPEC_ROOT = ROOT / "experiments/phase9"


def raw(
    task: str,
    configuration: str,
    repetition: int,
    success: bool,
    *,
    validity: str = "valid",
    wall: float | None = 100,
    tokens: int | None = 1000,
    strategy: str | None = None,
) -> RawExperimentRun:
    return RawExperimentRun.model_validate(
        {
            "experiment_id": "fixture",
            "scheduled_order": repetition,
            "task_id": task,
            "configuration_id": configuration,
            "strategy": strategy,
            "repetition": repetition,
            "run_id": f"{task}-{configuration}-{repetition}",
            "validity": validity,
            "classification": (
                "infrastructure_failure"
                if validity != "valid"
                else "benchmark_success" if success else "benchmark_failure"
            ),
            "official_success": success if validity == "valid" else None,
            "task_wall_time_ms": wall,
            "strategy_wall_time_ms": wall,
            "summed_provider_execution_time_ms": wall,
            "provider_invocations": 1,
            "provider_tool_calls": 2,
            "total_tokens": tokens,
            "peak_concurrent_provider_processes": 1,
            "concurrency_factor": 1,
        }
    )


def test_primary_spec_is_frozen_complete_and_budgeted():
    spec = load_spec(SPEC_ROOT / "strategy-study-v1.yaml")
    frozen = validate_frozen_inputs(spec, ROOT / "benchmarks")
    assert spec.run_count == 108
    assert spec.repetitions == 3
    assert spec.experiment_run_concurrency == 1
    assert spec.estimated_provider_invocations == 324
    assert spec.maximum_internal_concurrency == 2
    assert frozen["task_count"] == 12
    assert len(frozen["task_hashes"]) == 12
    assert plan_summary(spec)["estimated_cost"] is None
    assert spec.spec_hash == "bd84864140363cb6431f73118cf20f18f7ca6d4dbeccad3e05e310e1d826bf56"


def test_cost_budget_requires_explicit_versioned_pricing():
    spec = load_spec(SPEC_ROOT / "strategy-study-v1.yaml")
    payload = spec.model_dump(mode="python")
    payload["budget"]["max_estimated_cost"] = 200
    with pytest.raises(ValueError, match="requires explicit pricing"):
        ExperimentSpec.model_validate(payload)

    payload["pricing"] = {
        "version": "fixture-2026-09-18",
        "source": "test configuration",
        "providers": {
            "codex": {
                "input_usd_per_million_tokens": 2,
                "output_usd_per_million_tokens": 3,
            }
        },
    }
    priced = ExperimentSpec.model_validate(payload)
    plan = plan_summary(priced)
    assert plan["estimated_cost"] == 150
    assert plan["pricing_version"] == "fixture-2026-09-18"
    assert priced.spec_hash != spec.spec_hash


def test_agent_timeout_is_benchmark_failure_but_persistence_failure_is_infrastructure():
    now = datetime.now(UTC)
    timeout = RunResult(
        run_id="timeout",
        task_id="task",
        agent_name="codex",
        status=RunStatus.TIMED_OUT,
        started_at=now,
        finished_at=now,
        duration_ms=120_000,
        workspace=None,
        events=(),
        agent_turns=1,
        tool_calls=0,
        files_modified=(),
        git_diff="",
        failure_reason="overall run timeout exceeded: 120s",
    )
    assert classify_result(timeout) == ("valid", "benchmark_failure")
    assert classify_result(
        timeout.model_copy(update={"persistence_error": "PostgreSQL persistence failed"})
    ) == ("infrastructure_failure", "infrastructure_failure")


def test_schedule_is_reproducible_randomized_and_duplicate_free():
    spec = load_spec(SPEC_ROOT / "strategy-study-v1.yaml")
    first = build_schedule(spec)
    second = build_schedule(spec)
    assert first == second
    assert len(first) == len({(e.task_id, e.configuration_id, e.repetition) for e in first})
    assert [entry.scheduled_order for entry in first] == list(range(1, 109))
    assert len({entry.configuration_id for entry in first[:6]}) > 1
    changed = spec.model_copy(update={"random_seed": spec.random_seed + 1})
    assert build_schedule(changed) != first


def test_spec_rejects_duplicates_and_changed_manifest():
    spec = load_spec(SPEC_ROOT / "strategy-study-v1.yaml")
    with pytest.raises(ValueError, match="task IDs must be unique"):
        ExperimentSpec.model_validate(
            spec.model_dump(mode="python") | {"task_ids": [spec.task_ids[0]] * 2}
        )
    changed = spec.model_copy(update={"benchmark_manifest_hash": "0" * 64})
    with pytest.raises(ValueError, match="manifest hash differs"):
        validate_frozen_inputs(changed, ROOT / "benchmarks")


def test_task_aggregation_uses_repetition_mean_and_excludes_invalid_attempts():
    runs = [
        raw("a", "single", 1, True),
        raw("a", "single", 2, False),
        raw("a", "single", 3, False, validity="infrastructure_failure"),
        raw("b", "single", 1, True, tokens=None),
    ]
    aggregates = task_aggregates(runs)
    assert aggregates[0]["valid_repetitions"] == 2
    assert aggregates[0]["success_probability"] == 0.5
    assert aggregates[1]["success_probability"] == 1
    assert aggregates[1]["total_tokens"] is None


def test_bootstrap_and_quantiles_are_reproducible():
    values = [0.0, 0.5, 1.0, 1.0]
    assert bootstrap_interval(values, seed=42, samples=500) == bootstrap_interval(
        values, seed=42, samples=500
    )
    assert percentile([1, 2, 3, 4], 0.25) == 1.75
    assert percentile([], 0.5) is None


def test_paired_analysis_uses_matched_tasks_and_known_differences():
    runs = []
    outcomes = (("a", [True, True], [False, True]), ("b", [False, False], [True, True]))
    for task, left, right in outcomes:
        for index, success in enumerate(left, 1):
            runs.append(raw(task, "left", index, success, wall=10 + index, tokens=100))
        for index, success in enumerate(right, 1):
            runs.append(raw(task, "right", index, success, wall=20 + index, tokens=200))
    comparison = pairwise_comparisons(runs, bootstrap_seed=7)["left_minus_right"]
    assert comparison["official_success"]["paired_task_count"] == 2
    assert comparison["official_success"]["mean_difference"] == -0.25
    assert comparison["task_wall_time_ms"]["mean_difference"] == -10
    assert comparison["total_tokens"]["median_difference"] == -100


def test_zero_success_efficiency_is_undefined_and_nullable_metrics_survive():
    runs = [raw("a", "single", 1, False, wall=None, tokens=None)]
    result = analyze(runs, bootstrap_seed=9)
    summary = result["strategy_summary"]["single"]
    assert summary["efficiency"] == {
        "tokens_per_success": None,
        "wall_time_ms_per_success": None,
        "provider_invocations_per_success": None,
    }
    assert summary["all_runs"]["task_wall_time_ms"]["median"] is None


def test_role_specific_analyses_do_not_pool_multi_agent_strategies():
    staged = raw(
        "a",
        "staged",
        1,
        False,
        strategy="planner_implementer_reviewer",
    ).model_copy(
        update={
            "corrections": 1,
            "correction_changed_patch": True,
            "correction_improved_visible_tests": False,
            "candidate_count": 1,
        }
    )
    parallel = raw(
        "a",
        "parallel",
        1,
        True,
        strategy="parallel_implementers",
    ).model_copy(
        update={
            "corrections": 0,
            "candidate_count": 2,
            "candidate_failures": 1,
            "candidate_patch_sizes": (10, 20),
            "selected_candidate": "B",
        }
    )
    corrections = correction_analysis([staged, parallel])
    candidates = parallel_candidate_analysis([staged, parallel])
    assert corrections["eligible_runs"] == 1
    assert corrections["correction_requested_fraction"] == 1
    assert candidates["runs"] == 1
    assert candidates["mean_candidate_count"] == 2
    assert candidates["selection_distribution"] == {"B": 1}


def test_impossible_strategy_duration_is_excluded_from_derived_summary():
    run = raw("a", "single", 1, True, strategy="single").model_copy(
        update={"strategy_wall_time_ms": 1000, "task_wall_time_ms": 100}
    )
    result = analyze([run], bootstrap_seed=3)
    assert result["task_aggregates"][0]["strategy_wall_time_ms"] is None
    assert result["strategy_summary"]["single"]["all_runs"][
        "strategy_wall_time_ms"
    ]["median"] is None


def test_pilot_and_provider_studies_are_separate_specs():
    pilot = load_spec(SPEC_ROOT / "strategy-study-pilot-v1.yaml")
    provider = load_spec(SPEC_ROOT / "provider-study-v1.yaml")
    assert pilot.run_count == 6
    assert provider.run_count == 72
    assert provider.provider_requirements == ("codex", "claude-code")
    assert pilot.spec_hash != provider.spec_hash


def test_result_export_is_complete_and_machine_readable(tmp_path):
    spec = load_spec(SPEC_ROOT / "strategy-study-pilot-v1.yaml")
    runs = [raw("incorrect_api_response", "single-codex", 1, True)]

    class Repository:
        def get(self, experiment_id):
            return {
                "experiment_id": experiment_id,
                "name": spec.name,
                "status": "running",
                "spec": spec.model_dump(mode="json"),
                "configurations": [],
                "schedule": [
                    {
                        "scheduled_order": 1,
                        "task_id": runs[0].task_id,
                        "configuration_id": runs[0].configuration_id,
                        "repetition": 1,
                        "status": "completed",
                        "valid_run_id": runs[0].run_id,
                        "attempt_count": 1,
                    }
                ],
                "attempts": [],
            }

        def raw_runs(self, experiment_id):
            return runs

    target = export_results(Repository(), spec.experiment_id, tmp_path)  # type: ignore[arg-type]
    expected = {
        "experiment.json",
        "schedule.csv",
        "raw_runs.csv",
        "task_aggregates.csv",
        "strategy_summary.json",
        "pairwise_comparisons.json",
        "exclusions.json",
        "correction_analysis.json",
        "parallel_candidate_analysis.json",
        "experiment_summary.md",
    }
    assert {path.name for path in target.iterdir()} == expected
    assert "not a leaderboard" in (target / "experiment_summary.md").read_text()
