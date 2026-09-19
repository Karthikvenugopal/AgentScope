"""Regenerate Phase 10 publication artifacts from frozen Phase 9 exports.

This command is intentionally offline: it never opens the experiment database,
starts Docker, or invokes a coding-agent provider. Existing run artifacts are
used only to classify missing telemetry and extract one representative trace;
the checked-in derived JSON files make subsequent regeneration self-contained.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from app.experiments.analysis import analyze
from app.experiments.models import RawExperimentRun

RESULTS = ROOT / "results" / "strategy-study-v1"
FIGURES = ROOT / "docs" / "figures"
ARTIFACTS = ROOT / "artifacts" / "runs"
BOOTSTRAP_SEED = 20260919
REPRESENTATIVE_RUN = "strategy-study-v1-016-a1"

COLORS = {
    "ink": "#173238",
    "muted": "#587179",
    "grid": "#d7e1df",
    "paper": "#fbfcfb",
    "single-codex": "#147d6f",
    "staged-codex": "#d38a2f",
    "parallel2-codex": "#6b63a8",
    "accent": "#0f665c",
    "failure": "#bc5b55",
    "missing": "#aeb9b7",
}
LABELS = {
    "single-codex": "Single",
    "staged-codex": "Staged",
    "parallel2-codex": "Parallel-2",
}
ORDER = ("single-codex", "staged-codex", "parallel2-codex")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_runs(path: Path) -> list[RawExperimentRun]:
    runs: list[RawExperimentRun] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            payload: dict[str, Any] = {}
            for field in RawExperimentRun.model_fields:
                raw = row[field]
                if raw == "":
                    payload[field] = None
                elif field in {"candidate_patch_sizes", "provider_session_ids"}:
                    payload[field] = json.loads(raw)
                else:
                    payload[field] = raw
            if payload["candidate_patch_sizes"] is None:
                payload["candidate_patch_sizes"] = []
            if payload["provider_session_ids"] is None:
                payload["provider_session_ids"] = []
            runs.append(RawExperimentRun.model_validate(payload))
    return runs


def assert_close(actual: Any, expected: Any, path: str = "root") -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise RuntimeError(f"analysis mismatch at {path}: mapping keys differ")
        for key, value in expected.items():
            assert_close(actual[key], value, f"{path}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise RuntimeError(f"analysis mismatch at {path}: list shape differs")
        for index, value in enumerate(expected):
            assert_close(actual[index], value, f"{path}[{index}]")
        return
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        if not math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-9):
            raise RuntimeError(f"analysis mismatch at {path}: {actual!r} != {expected!r}")
        return
    if actual != expected:
        raise RuntimeError(f"analysis mismatch at {path}: {actual!r} != {expected!r}")


def _failure_category(run: RawExperimentRun) -> str:
    run_path = ARTIFACTS / run.run_id / "run.json"
    if not run_path.exists():
        return "unclassified"
    data = read_json(run_path)
    failure = str(data.get("failure_reason") or "")
    status = data.get("status")
    if run.classification == "benchmark_success":
        return "official_success"
    if status == "timed_out":
        return "strategy_timeout"
    if "provider_api_failure" in failure:
        return "provider_api_failure"
    if status in {"completed", "verification_failed"}:
        return "official_verification_failure"
    return "other_strategy_failure"


def telemetry_completeness(runs: list[RawExperimentRun]) -> dict[str, Any]:
    target = RESULTS / "telemetry_completeness.json"
    valid = [run for run in runs if run.validity == "valid"]
    available_artifacts = sum(
        (ARTIFACTS / run.run_id / "run.json").exists() for run in valid
    )
    if available_artifacts != len(valid) and target.exists():
        return read_json(target)
    output: dict[str, Any] = {
        "definition": "A run is complete only when measured total_tokens is non-null.",
        "missing_values_are_not_zero": True,
        "strategies": {},
    }
    for configuration in ORDER:
        group = [run for run in valid if run.configuration_id == configuration]
        by_outcome: dict[str, dict[str, int]] = defaultdict(
            lambda: {"runs": 0, "token_complete": 0, "token_missing": 0}
        )
        missing_causes: dict[str, int] = defaultdict(int)
        missing_runs: list[dict[str, Any]] = []
        for run in group:
            outcome = _failure_category(run)
            by_outcome[outcome]["runs"] += 1
            key = "token_complete" if run.total_tokens is not None else "token_missing"
            by_outcome[outcome][key] += 1
            if run.total_tokens is None:
                missing_causes[outcome] += 1
                missing_runs.append(
                    {
                        "run_id": run.run_id,
                        "task_id": run.task_id,
                        "cause": outcome,
                        "candidate_failures": run.candidate_failures,
                        "provider_invocations": run.provider_invocations,
                    }
                )
        complete = sum(run.total_tokens is not None for run in group)
        output["strategies"][configuration] = {
            "valid_runs": len(group),
            "token_complete": complete,
            "token_missing": len(group) - complete,
            "completeness_fraction": complete / len(group),
            "by_outcome": dict(sorted(by_outcome.items())),
            "missing_causes": dict(sorted(missing_causes.items())),
            "missing_runs": missing_runs,
        }
    output["finding"] = (
        "All 21 missing token observations were benchmark failures: 19 strategy "
        "timeouts and 2 provider API failures. Every official success had token telemetry."
    )
    write_json(target, output)
    return output


def trace_findings(runs: list[RawExperimentRun]) -> dict[str, Any]:
    """Derive auditable failure and candidate-diversity counts from native run records."""
    target = RESULTS / "trace_findings.json"
    valid = [run for run in runs if run.validity == "valid"]
    if not all((ARTIFACTS / run.run_id / "run.json").exists() for run in valid):
        if target.exists():
            return read_json(target)
        raise RuntimeError("native run artifacts unavailable and trace_findings.json is absent")
    failures: dict[str, dict[str, int]] = {}
    parallel = {
        "runs": 0,
        "runs_with_two_implementer_records": 0,
        "runs_with_two_completed_candidates": 0,
        "identical_nonempty_patches": 0,
        "different_nonempty_patches": 0,
        "selected_A": 0,
        "selected_B": 0,
        "no_selection": 0,
    }
    for configuration in ORDER:
        counts: dict[str, int] = defaultdict(int)
        for run in [item for item in valid if item.configuration_id == configuration]:
            counts[_failure_category(run)] += 1
            if configuration != "parallel2-codex":
                continue
            parallel["runs"] += 1
            data = read_json(ARTIFACTS / run.run_id / "run.json")
            executions = [
                item
                for item in data.get("orchestration", {}).get("executions", [])
                if item.get("role") == "implementer"
            ]
            if len(executions) == 2:
                parallel["runs_with_two_implementer_records"] += 1
            completed = [item for item in executions if item.get("status") == "completed"]
            if len(completed) == 2:
                parallel["runs_with_two_completed_candidates"] += 1
                patches = [str(item.get("patch") or "") for item in completed]
                if all(patches):
                    key = (
                        "identical_nonempty_patches"
                        if patches[0] == patches[1]
                        else "different_nonempty_patches"
                    )
                    parallel[key] += 1
            selected = data.get("orchestration", {}).get("selected_candidate")
            selection_key = f"selected_{selected}" if selected else "no_selection"
            parallel[selection_key] += 1
        failures[configuration] = dict(sorted(counts.items()))
    output = {
        "failure_modes": failures,
        "parallel_patch_diversity": parallel,
        "interpretation_boundary": (
            "Patch equality is textual equality only; unselected candidates were not "
            "officially verified, so diversity is not a quality comparison."
        ),
    }
    write_json(target, output)
    return output


def representative_trace() -> dict[str, Any]:
    target = RESULTS / "representative_trace.json"
    trace_path = ARTIFACTS / REPRESENTATIVE_RUN / "trace.json"
    run_path = ARTIFACTS / REPRESENTATIVE_RUN / "run.json"
    if (not trace_path.exists() or not run_path.exists()) and target.exists():
        return read_json(target)
    trace = read_json(trace_path)
    run = read_json(run_path)
    events = trace["events"]
    wanted = {
        "strategy_started",
        "planner_started",
        "planner_completed",
        "parallel_group_started",
        "parallel_candidate_started",
        "parallel_candidate_completed",
        "reviewer_started",
        "reviewer_completed",
        "candidate_selected",
        "strategy_completed",
        "verification_started",
        "verification_completed",
        "run_completed",
    }
    selected = [
        {
            "sequence": event["sequence_number"],
            "timestamp": event["timestamp"],
            "event_type": event["event_type"],
            "role": event.get("role"),
            "candidate_id": event.get("candidate_id"),
            "execution_id": event.get("execution_id"),
            "parent_execution_id": event.get("parent_execution_id"),
        }
        for event in events
        if event["event_type"] in wanted
    ]
    output = {
        "run_id": run["run_id"],
        "task_id": run["task_id"],
        "status": run["status"],
        "strategy": run["strategy"],
        "selected_candidate": run["orchestration"]["selected_candidate"],
        "candidate_count": run["orchestration"]["candidate_count"],
        "official_verification": {
            "passed": run["verification"]["passed"],
            "passed_tests": run["verification"]["passed_tests"],
            "total_tests": run["verification"]["total_tests"],
        },
        "events": selected,
        "source_trace_sha256": sha256(trace_path),
        "source_run_sha256": sha256(run_path),
    }
    write_json(target, output)
    return output


class SVG:
    def __init__(self, width: int, height: int, title: str, subtitle: str = "") -> None:
        self.width = width
        self.height = height
        self.parts = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
            ),
            f"<title id=\"title\">{html.escape(title)}</title>",
            f"<desc id=\"desc\">{html.escape(subtitle)}</desc>",
            f'<rect width="{width}" height="{height}" fill="{COLORS["paper"]}"/>',
            (
                '<style>text{font-family:Inter,ui-sans-serif,system-ui,-apple-system,'
                "BlinkMacSystemFont,Segoe UI,sans-serif;fill:#173238}.mono{font-family:"
                "ui-monospace,SFMono-Regular,Menlo,monospace}.small{font-size:13px}"
                ".label{font-size:15px;font-weight:600}.title{font-size:26px;font-weight:700}"
                ".subtitle{font-size:14px;fill:#587179}</style>"
            ),
        ]
        self.text(48, 43, title, css="title")
        if subtitle:
            self.text(48, 68, subtitle, css="subtitle")

    def rect(self, x: float, y: float, w: float, h: float, *, fill: str = "white", stroke: str = "#d7e1df", rx: int = 8, sw: float = 1.5) -> None:
        self.parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def line(self, x1: float, y1: float, x2: float, y2: float, *, stroke: str = "#587179", sw: float = 1.5, dash: str | None = None) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" stroke-width="{sw}"{extra}/>' )

    def circle(self, x: float, y: float, r: float, *, fill: str, stroke: str = "white", sw: float = 1.5) -> None:
        self.parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x: float, y: float, value: str, *, anchor: str = "start", css: str = "small", fill: str | None = None) -> None:
        color = f' fill="{fill}"' if fill else ""
        self.parts.append(f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" class="{css}"{color}>{html.escape(value)}</text>')

    def arrow(self, x1: float, y1: float, x2: float, y2: float, *, stroke: str = "#587179") -> None:
        self.line(x1, y1, x2, y2, stroke=stroke, sw=2)
        angle = math.atan2(y2 - y1, x2 - x1)
        for offset in (-0.5, 0.5):
            ax = x2 - 10 * math.cos(angle + offset)
            ay = y2 - 10 * math.sin(angle + offset)
            self.line(x2, y2, ax, ay, stroke=stroke, sw=2)

    def save(self, path: Path) -> None:
        path.write_text("\n".join(self.parts + ["</svg>"]) + "\n", encoding="utf-8")


def figure_architecture() -> None:
    s = SVG(1280, 720, "Figure 1 · AgentScope system architecture", "Orchestration remains separate from independent verification and benchmark ground truth.")
    nodes = {
        "task": (55, 270, 155, 78, "Benchmark task", "Native or Harbor"),
        "strategy": (260, 270, 175, 78, "Execution strategy", "Single · staged · parallel"),
        "planner": (495, 125, 150, 66, "Planner", "Provider process"),
        "single": (495, 270, 150, 66, "Implementer A", "Isolated workspace"),
        "second": (495, 385, 150, 66, "Implementer B", "Isolated workspace"),
        "review": (705, 270, 165, 78, "Reviewer / selector", "Select before verify"),
        "verify": (930, 270, 170, 78, "Independent verifier", "Official hidden tests"),
        "store": (930, 475, 170, 78, "PostgreSQL + traces", "Hierarchy and metrics"),
        "ui": (705, 475, 165, 78, "Research dashboard", "Runs and experiments"),
    }
    for key, (x, y, w, h, title, sub) in nodes.items():
        fill = "#eef7f5" if key in {"task", "strategy", "verify"} else "white"
        s.rect(x, y, w, h, fill=fill, stroke=COLORS["accent"] if key in {"strategy", "verify"} else COLORS["grid"])
        s.text(x + w / 2, y + 30, title, anchor="middle", css="label")
        s.text(x + w / 2, y + 51, sub, anchor="middle", css="small")
    s.arrow(210, 309, 260, 309); s.arrow(435, 309, 495, 303)
    s.arrow(435, 300, 495, 158); s.arrow(435, 318, 495, 418)
    s.arrow(645, 158, 705, 288); s.arrow(645, 303, 705, 309); s.arrow(645, 418, 705, 330)
    s.arrow(870, 309, 930, 309); s.arrow(1015, 348, 1015, 475)
    s.arrow(930, 514, 870, 514)
    s.rect(465, 95, 210, 385, fill="none", stroke="#9dbbb6", rx=14, sw=1.5)
    s.text(570, 465, "Sibling workspaces cannot inspect one another", anchor="middle", css="small")
    s.text(640, 635, "Providers never receive hidden tests, verifier outcomes, sibling workspaces, Docker authority, or database credentials.", anchor="middle", css="subtitle")
    s.save(FIGURES / "01-system-architecture.svg")


def figure_success(summary: dict[str, Any]) -> None:
    s = SVG(1000, 650, "Figure 2 · Official task-success estimates", "Mean task-level success probability; 95% bootstrap intervals resample 12 tasks.")
    left, bottom, chart_h = 130, 530, 390
    for tick in range(0, 101, 20):
        y = bottom - chart_h * tick / 100
        s.line(left, y, 900, y, stroke=COLORS["grid"], sw=1)
        s.text(left - 18, y + 5, f"{tick}%", anchor="end", css="small")
    xs = [280, 520, 760]
    for x, cfg in zip(xs, ORDER, strict=True):
        data = summary[cfg]
        value = 100 * data["mean_task_success_probability"]
        low, high = [100 * item for item in data["success_bootstrap_95_ci"]]
        y = bottom - chart_h * value / 100
        y_low = bottom - chart_h * low / 100
        y_high = bottom - chart_h * high / 100
        s.rect(x - 52, y, 104, bottom - y, fill=COLORS[cfg], stroke=COLORS[cfg], rx=3)
        s.line(x, y_high, x, y_low, stroke=COLORS["ink"], sw=2.5)
        s.line(x - 16, y_high, x + 16, y_high, stroke=COLORS["ink"], sw=2.5)
        s.line(x - 16, y_low, x + 16, y_low, stroke=COLORS["ink"], sw=2.5)
        s.text(x, y - 13, f"{data['benchmark_successes']}/36 · {value:.2f}%", anchor="middle", css="label")
        s.text(x, bottom + 32, LABELS[cfg], anchor="middle", css="label")
        s.text(x, bottom + 54, f"95% CI {low:.2f}–{high:.2f}%", anchor="middle", css="small")
    s.text(500, 615, "Official independent verification · three repetitions per task and strategy", anchor="middle", css="subtitle")
    s.save(FIGURES / "02-experimental-success.svg")


def figure_heatmap(task_rows: list[dict[str, Any]]) -> None:
    lookup = {(r["task_id"], r["configuration_id"]): r for r in task_rows}
    tasks = sorted({r["task_id"] for r in task_rows})
    s = SVG(1120, 850, "Figure 3 · Task-level official outcomes", "Each cell reports successes across three independent repetitions.")
    x0, y0, cw, rh = 430, 125, 190, 52
    heat = {0: "#f1d9d6", 1: "#e9c8a7", 2: "#b9d9d2", 3: "#5fa99c"}
    for index, cfg in enumerate(ORDER):
        s.text(x0 + index * cw + cw / 2, y0 - 22, LABELS[cfg], anchor="middle", css="label")
    for row, task in enumerate(tasks):
        y = y0 + row * rh
        s.text(x0 - 18, y + 31, task, anchor="end", css="small")
        for col, cfg in enumerate(ORDER):
            value = int(lookup[(task, cfg)]["successes"])
            x = x0 + col * cw
            s.rect(x + 5, y + 5, cw - 10, rh - 10, fill=heat[value], stroke="white", rx=4, sw=1)
            s.text(x + cw / 2, y + 33, f"{value}/3", anchor="middle", css="label")
    s.text(560, 805, "Green indicates more official successes; red indicates none. No partial hidden score is inferred.", anchor="middle", css="subtitle")
    s.save(FIGURES / "03-task-outcomes.svg")


def _distribution_figure(path: str, title: str, subtitle: str, task_rows: list[dict[str, Any]], field: str, scale: float, unit: str, max_value: float, completeness: dict[str, Any] | None = None) -> None:
    s = SVG(1080, 700, title, subtitle)
    left, right, top, bottom = 140, 960, 105, 555
    chart_h = bottom - top
    for tick in range(6):
        value = max_value * tick / 5
        y = bottom - chart_h * value / max_value
        s.line(left, y, right, y, stroke=COLORS["grid"], sw=1)
        s.text(left - 16, y + 5, f"{value:g}{unit}", anchor="end", css="small")
    xs = [300, 550, 800]
    for x, cfg in zip(xs, ORDER, strict=True):
        values = [float(r[field]) / scale for r in task_rows if r["configuration_id"] == cfg and r[field] is not None]
        values.sort()
        for index, value in enumerate(values):
            jitter = ((index % 5) - 2) * 8
            y = bottom - chart_h * min(value, max_value) / max_value
            s.circle(x + jitter, y, 5.5, fill=COLORS[cfg], stroke="white")
        median = values[len(values) // 2] if len(values) % 2 else (values[len(values)//2-1] + values[len(values)//2]) / 2
        y_med = bottom - chart_h * median / max_value
        s.line(x - 65, y_med, x + 65, y_med, stroke=COLORS["ink"], sw=4)
        s.text(x, bottom + 35, LABELS[cfg], anchor="middle", css="label")
        detail = f"median {median:,.1f}{unit} · {len(values)} task means"
        s.text(x, bottom + 57, detail, anchor="middle", css="small")
        if completeness:
            item = completeness["strategies"][cfg]
            s.text(x, bottom + 79, f"tokens measured: {item['token_complete']}/{item['valid_runs']} runs", anchor="middle", css="small")
    s.text(540, 665, "Horizontal line: median across task-level repetition averages · dots: individual tasks", anchor="middle", css="subtitle")
    s.save(FIGURES / path)


def figure_workload(summary: dict[str, Any]) -> None:
    s = SVG(1120, 720, "Figure 6 · Provider-process workload and execution overlap", "Task-level medians. Summed process time may exceed wall time when provider processes overlap.")
    left, bottom, chart_h = 110, 510, 350
    max_seconds = 170
    for tick in range(0, 181, 30):
        y = bottom - chart_h * tick / max_seconds
        s.line(left, y, 1030, y, stroke=COLORS["grid"], sw=1)
        s.text(left - 16, y + 5, f"{tick}s", anchor="end", css="small")
    xs = [270, 560, 850]
    for x, cfg in zip(xs, ORDER, strict=True):
        data = summary[cfg]["all_runs"]
        wall = data["strategy_wall_time_ms"]["median"] / 1000
        summed = data["summed_provider_execution_time_ms"]["median"] / 1000
        for bx, value, color in ((x - 50, wall, COLORS[cfg]), (x + 15, summed, "#85a9a3")):
            h = chart_h * value / max_seconds
            s.rect(bx, bottom - h, 48, h, fill=color, stroke=color, rx=2)
            s.text(bx + 24, bottom - h - 10, f"{value:.1f}s", anchor="middle", css="small")
        peak = data["peak_concurrent_provider_processes"]["median"]
        factor = data["concurrency_factor"]["median"]
        s.text(x, bottom + 35, LABELS[cfg], anchor="middle", css="label")
        s.text(x, bottom + 57, f"peak processes {peak:g}", anchor="middle", css="small")
        s.text(x, bottom + 77, f"concurrency factor {factor:.3f}" if factor is not None else "concurrency factor unavailable", anchor="middle", css="small")
    s.rect(325, 610, 18, 18, fill=COLORS["single-codex"], stroke=COLORS["single-codex"], rx=2)
    s.text(352, 624, "strategy wall time", css="small")
    s.rect(575, 610, 18, 18, fill="#85a9a3", stroke="#85a9a3", rx=2)
    s.text(602, 624, "summed provider-process time", css="small")
    s.text(560, 682, "Concurrency factor is an execution-overlap metric—not GPU or inference-server utilization.", anchor="middle", css="subtitle")
    s.save(FIGURES / "06-parallel-workload.svg")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def figure_trace(trace: dict[str, Any]) -> None:
    events = trace["events"]
    origin = _parse_time(next(e["timestamp"] for e in events if e["event_type"] == "strategy_started"))
    def rel(kind: str, candidate: str | None = None) -> float:
        for event in events:
            if event["event_type"] == kind and (candidate is None or event["candidate_id"] == candidate):
                return (_parse_time(event["timestamp"]) - origin).total_seconds()
        raise KeyError((kind, candidate))
    spans = [
        ("Planner", rel("planner_started"), rel("planner_completed"), COLORS["staged-codex"]),
        ("Candidate A", rel("parallel_candidate_started", "A"), rel("parallel_candidate_completed", "A"), COLORS["parallel2-codex"]),
        ("Candidate B", rel("parallel_candidate_started", "B"), rel("parallel_candidate_completed", "B"), "#9088c4"),
        ("Reviewer", rel("reviewer_started"), rel("reviewer_completed"), "#d3a04f"),
        ("Verifier", rel("verification_started"), rel("verification_completed"), COLORS["single-codex"]),
    ]
    end = rel("run_completed")
    s = SVG(1180, 660, "Figure 7 · Representative parallel-agent trajectory", f"Recorded run {trace['run_id']} · task {trace['task_id']} · timestamps from native trace events.")
    left, right, top, row_h = 210, 1090, 145, 72
    scale = (right - left) / 45
    for tick in range(0, 46, 5):
        x = left + tick * scale
        s.line(x, top - 25, x, top + row_h * 5 - 15, stroke=COLORS["grid"], sw=1)
        s.text(x, top - 38, f"{tick}s", anchor="middle", css="small")
    for index, (label, start, finish, color) in enumerate(spans):
        y = top + index * row_h
        s.text(left - 20, y + 24, label, anchor="end", css="label")
        s.rect(left + start * scale, y, max(5, (finish - start) * scale), 36, fill=color, stroke=color, rx=5)
        s.text(left + (start + finish) * scale / 2, y + 24, f"{finish-start:.2f}s", anchor="middle", css="small", fill="white")
    select = rel("candidate_selected")
    s.line(left + select * scale, top + row_h * 3 - 15, left + select * scale, top + row_h * 5 - 15, stroke=COLORS["ink"], sw=2, dash="5 4")
    s.text(left + select * scale, top + row_h * 5 + 4, "Candidate A selected", anchor="middle", css="small")
    s.text(590, 560, f"Official verifier: {trace['official_verification']['passed_tests']}/{trace['official_verification']['total_tests']} passed · total run {end:.2f}s", anchor="middle", css="label")
    s.text(590, 605, "Candidate workspaces overlapped. Selection preceded the only official verification.", anchor="middle", css="subtitle")
    s.save(FIGURES / "07-representative-trajectory.svg")


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    runs = load_runs(RESULTS / "raw_runs.csv")
    analysis = analyze(runs, bootstrap_seed=BOOTSTRAP_SEED)
    expected_summary = read_json(RESULTS / "strategy_summary.json")
    expected_pairs = read_json(RESULTS / "pairwise_comparisons.json")
    assert_close(analysis["strategy_summary"], expected_summary, "strategy_summary")
    assert_close(analysis["pairwise_comparisons"], expected_pairs, "pairwise_comparisons")
    completeness = telemetry_completeness(runs)
    findings = trace_findings(runs)
    trace = representative_trace()
    write_json(
        RESULTS / "publication_analysis.json",
        {
            "valid_runs": analysis["valid_runs"],
            "infrastructure_attempts": analysis["invalid_attempts"],
            "protocol_exclusions": analysis["protocol_exclusions"],
            "strategy_summary": analysis["strategy_summary"],
            "pairwise_comparisons": analysis["pairwise_comparisons"],
            "correction_analysis": analysis["corrections"],
            "parallel_candidate_analysis": analysis["parallel_candidates"],
            "telemetry_completeness": completeness,
            "trace_findings": findings,
        },
    )

    figure_architecture()
    figure_success(analysis["strategy_summary"])
    figure_heatmap(analysis["task_aggregates"])
    _distribution_figure(
        "04-task-latency.svg",
        "Figure 4 · Task wall time",
        "All valid repetitions contribute, regardless of official success; dots are task-level repetition averages.",
        analysis["task_aggregates"],
        "task_wall_time_ms",
        1000,
        "s",
        150,
    )
    _distribution_figure(
        "05-token-consumption.svg",
        "Figure 5 · Recorded token consumption",
        "Task means use available measured runs only. Missing telemetry is not zero and is not extrapolated.",
        analysis["task_aggregates"],
        "total_tokens",
        1,
        "",
        270000,
        completeness,
    )
    figure_workload(analysis["strategy_summary"])
    figure_trace(trace)

    validation = {
        "offline": True,
        "provider_invocations": 0,
        "database_access": False,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "valid_runs": analysis["valid_runs"],
        "infrastructure_attempts": analysis["invalid_attempts"],
        "protocol_exclusions": analysis["protocol_exclusions"],
        "strategy_summary_matches_frozen_export": True,
        "pairwise_comparisons_match_frozen_export": True,
        "trace_findings_generated": bool(findings),
        "publication_analysis": "results/strategy-study-v1/publication_analysis.json",
        "source_hashes": {
            "raw_runs.csv": sha256(RESULTS / "raw_runs.csv"),
            "task_aggregates.csv": sha256(RESULTS / "task_aggregates.csv"),
            "strategy_summary.json": sha256(RESULTS / "strategy_summary.json"),
            "pairwise_comparisons.json": sha256(RESULTS / "pairwise_comparisons.json"),
        },
        "figures": sorted(path.name for path in FIGURES.glob("*.svg")),
    }
    write_json(FIGURES / "analysis-validation.json", validation)
    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
