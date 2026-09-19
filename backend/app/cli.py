"""Verified run execution and PostgreSQL inspection commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.agents import CodingAgent, MockCodingAgent
from app.agents.external import ClaudeCodeAgent, CodexAgent
from app.benchmark.manifest import freeze_manifest
from app.benchmark.validation import BenchmarkValidator
from app.experiments.exporter import export_results
from app.experiments.models import load_spec
from app.experiments.planner import build_schedule, plan_summary, validate_frozen_inputs
from app.experiments.repository import ExperimentRepository
from app.experiments.runner import ExperimentRunner
from app.harbor import HarborTaskAdapter
from app.harbor.trajectory import export_atif
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import DockerWorkspaceFactory
from app.models.run import RunStatus
from app.providers.models import ProviderName
from app.providers.runtime import ProviderRuntime
from app.storage.repository import PostgresRunRepository
from app.strategies.models import StrategyConfiguration

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _display_path(path: str) -> str:
    try:
        return str(Path(path).relative_to(_REPOSITORY_ROOT))
    except ValueError:
        return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentscope",
        description="AgentScope coding-agent harness",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one agent against one benchmark task")
    run.add_argument("--task", required=True)
    run.add_argument("--agent", choices=("mock", "codex", "claude-code"), default="mock")
    run.add_argument(
        "--strategy",
        choices=("single", "planner_implementer_reviewer", "parallel_implementers"),
        default="single",
    )
    run.add_argument("--planner-agent", choices=("mock", "codex", "claude-code"), default="mock")
    run.add_argument(
        "--implementer-agent",
        choices=("mock", "codex", "claude-code"),
        default="mock",
    )
    run.add_argument("--reviewer-agent", choices=("mock", "codex", "claude-code"), default="mock")
    run.add_argument("--workers", type=int, choices=(2, 3), default=3)
    run.add_argument("--model")
    run.add_argument("--image", default="agentscope-runner:py312")
    run.add_argument("--run-id")
    run.add_argument("--keep-workspace", action="store_true")
    run.add_argument(
        "--baseline", action="store_true", help="verify unchanged code with a no-op mock"
    )
    run.add_argument("--max-turns", type=int, default=20)
    run.add_argument("--max-tool-calls", type=int, default=100)
    run.add_argument("--command-timeout", type=float, default=60.0)
    run.add_argument("--overall-timeout", type=float, default=600.0)
    runs = commands.add_parser("runs", help="inspect persisted runs")
    inspection = runs.add_subparsers(dest="inspection", required=True)
    listing = inspection.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    show = inspection.add_parser("show")
    show.add_argument("run_id")
    export = inspection.add_parser("export-atif")
    export.add_argument("run_id")
    export.add_argument("--output", type=Path, required=True)
    benchmark = commands.add_parser("benchmark", help="import and validate benchmark tasks")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    validate = benchmark_commands.add_parser("validate", help="validate baseline/reference pairs")
    validate.add_argument("--include-external", action="store_true")
    validate.add_argument("--task", action="append", dest="tasks")
    validate.add_argument("--image", default="agentscope-runner:py312")
    importing = benchmark_commands.add_parser(
        "import-harbor", help="import an immutable local Harbor task package"
    )
    importing.add_argument("path", type=Path)
    importing.add_argument("--dataset", required=True)
    importing.add_argument("--dataset-version", required=True)
    importing.add_argument("--imported-at")
    benchmark_commands.add_parser("freeze", help="write hashes and benchmark manifest")
    experiments = commands.add_parser("experiments", help="plan and run controlled experiments")
    experiment_commands = experiments.add_subparsers(dest="experiment_command", required=True)
    for name in ("validate", "plan", "run"):
        command = experiment_commands.add_parser(name)
        command.add_argument("spec", type=Path)
        if name == "run":
            command.add_argument("--max-new-runs", type=int)
    status = experiment_commands.add_parser("status")
    status.add_argument("experiment_id")
    audit = experiment_commands.add_parser("audit")
    audit.add_argument("experiment_id")
    summarize = experiment_commands.add_parser("summarize")
    summarize.add_argument("experiment_id")
    summarize.add_argument("--output-root", type=Path, default=_REPOSITORY_ROOT / "results")
    return parser


async def _run_command(args: argparse.Namespace) -> int:
    repository = _repository()
    catalog = TaskCatalog(_REPOSITORY_ROOT / "benchmarks")
    limits = RunLimits(
        max_agent_turns=args.max_turns,
        max_tool_calls=args.max_tool_calls,
        command_timeout_seconds=args.command_timeout,
        overall_timeout_seconds=args.overall_timeout,
    )
    harness = SingleAgentHarness(
        catalog=catalog,
        workspace_factory=DockerWorkspaceFactory(image=args.image),
        artifact_store=ArtifactStore(_REPOSITORY_ROOT / "artifacts"),
        limits=limits,
        repository=repository,
        provider_runtime=ProviderRuntime(
            codex_auth_file=Path(os.environ["CODEX_AUTH_FILE"])
            if os.environ.get("CODEX_AUTH_FILE")
            else None,
            claude_auth_file=Path(os.environ["CLAUDE_AUTH_FILE"])
            if os.environ.get("CLAUDE_AUTH_FILE")
            else None,
        ),
    )
    agent: CodingAgent = (
        MockCodingAgent.for_incorrect_api_response()
        if args.task == "incorrect_api_response" and not args.baseline
        else MockCodingAgent()
    )
    if args.agent != "mock":
        if args.baseline:
            raise ValueError("--baseline is only valid for mock")
        agent = CodexAgent(args.model) if args.agent == "codex" else ClaudeCodeAgent(args.model)
    role_configuration = None
    if args.strategy != "single":
        role_configuration = StrategyConfiguration.model_validate(
            {
                "planner": {"agent": args.planner_agent},
                "implementer": {"agent": args.implementer_agent},
                "implementers": {
                    "agent": args.implementer_agent,
                    "count": args.workers,
                },
                "reviewer": {"agent": args.reviewer_agent},
            }
        )
    result = await harness.run(
        args.task,
        agent,
        run_id=args.run_id,
        keep_workspace=args.keep_workspace,
        strategy=args.strategy,
        strategy_configuration=role_configuration,
    )
    trace_path = _display_path(result.artifacts.trace) if result.artifacts else "not written"
    print(f"Run: {result.run_id}")
    print(f"Task: {result.task_id}")
    print(f"Agent: {result.agent_name}")
    print(f"Status: {result.status.value}")
    agent_completed = any(e.event_type == "agent_completed" for e in result.events)
    print(f"Agent execution: {'completed' if agent_completed else 'failed'}")
    verification = result.verification
    verdict = "NOT RUN" if verification is None else "PASSED" if verification.passed else "FAILED"
    print(f"Verification: {verdict}")
    if verification and verification.total_tests is not None:
        print(f"Official tests: {verification.passed_tests}/{verification.total_tests}")
    else:
        print("Official tests: unmeasured")
    print(f"Tool calls: {result.metrics.tool_calls if result.metrics else result.tool_calls}")
    print(f"Agent turns: {result.agent_turns}")
    print(f"Files modified: {len(result.files_modified)}")
    if result.metrics:
        if result.provenance.get("provider"):
            provider = result.provenance["provider"]
            print(f"Provider version: {provider['version']}")
            print(f"Model: {provider['model'] or 'not exposed'}")
            for name, value in result.metrics.inference.model_dump(exclude={"provenance"}).items():
                print(f"{name}: {value if value is not None else 'not measured'}")
        print(f"Lines: +{result.metrics.lines_added} / -{result.metrics.lines_removed}")
        print(f"Agent time: {result.metrics.agent_execution_time_ms / 1000:.2f}s")
        print(f"Verification time: {result.metrics.verification_time_ms / 1000:.2f}s")
    print(f"Total time: {result.duration_ms / 1000:.2f}s")
    print(f"Trace: {trace_path}")
    if result.artifacts:
        print(f"Patch: {_display_path(result.artifacts.patch)}")
    print(f"Persisted: {'FAILED' if result.persistence_error else 'PostgreSQL'}")
    if result.failure_reason:
        print(f"Failure: {result.failure_reason}")
    if result.workspace and result.workspace.retained:
        print(f"Workspace: {result.workspace.host_path}")
    return 0 if result.status is RunStatus.COMPLETED else 1


def _repository() -> PostgresRunRepository:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("export DATABASE_URL and run Alembic upgrade head first")
    return PostgresRunRepository.from_url(url)


def _provider_runtime() -> ProviderRuntime:
    return ProviderRuntime(
        codex_auth_file=Path(os.environ["CODEX_AUTH_FILE"])
        if os.environ.get("CODEX_AUTH_FILE")
        else None,
        claude_auth_file=Path(os.environ["CLAUDE_AUTH_FILE"])
        if os.environ.get("CLAUDE_AUTH_FILE")
        else None,
    )


async def _experiment_validate(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    frozen = validate_frozen_inputs(spec, _REPOSITORY_ROOT / "benchmarks")
    runtime = _provider_runtime()
    providers = {}
    for provider in spec.provider_requirements:
        availability = await runtime.probe(ProviderName(provider), refresh=True)
        providers[provider] = availability.model_dump(mode="json")
        if not availability.available:
            raise ValueError(f"required provider unavailable: {provider} ({availability.reason})")
    print(
        json.dumps(
            {"valid": True, "spec_hash": spec.spec_hash, **frozen, "providers": providers},
            indent=2,
        )
    )
    return 0


def _experiment_runner(repository: PostgresRunRepository) -> ExperimentRunner:
    return ExperimentRunner(
        root=_REPOSITORY_ROOT,
        run_repository=repository,
        experiment_repository=ExperimentRepository(repository.engine),
        provider_runtime=_provider_runtime(),
    )


async def _experiment_plan(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    repository = _repository()
    runner = _experiment_runner(repository)
    provenance = await runner.initialize(spec)
    print(json.dumps({**plan_summary(spec), "provenance": provenance}, indent=2))
    print("Schedule:")
    for entry in build_schedule(spec):
        print(
            f"{entry.scheduled_order:03d}  {entry.task_id}  "
            f"{entry.configuration_id}  repetition {entry.repetition}"
        )
    return 0


async def _experiment_run(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    repository = _repository()
    status = await _experiment_runner(repository).run(spec, max_new_runs=args.max_new_runs)
    print(json.dumps(status["progress"], indent=2))
    print(f"Status: {status['status']}")
    if status.get("pause_reason"):
        print(f"Paused: {status['pause_reason']}")
    return 0 if status["status"] in {"running", "completed"} else 3


def _experiment_status(args: argparse.Namespace) -> int:
    repository = _repository()
    record = ExperimentRepository(repository.engine).get(args.experiment_id)
    if record is None:
        raise ValueError(f"unknown experiment: {args.experiment_id}")
    fields = ("experiment_id", "name", "status", "spec_hash", "progress", "pause_reason")
    print(
        json.dumps(
            {key: record[key] for key in fields}, indent=2, default=str
        )
    )
    return 0


def _experiment_summarize(args: argparse.Namespace) -> int:
    repository = _repository()
    target = export_results(
        ExperimentRepository(repository.engine), args.experiment_id, args.output_root
    )
    print(f"Exported results to {target}")
    return 0


def _experiment_audit(args: argparse.Namespace) -> int:
    repository = _repository()
    repaired = ExperimentRepository(repository.engine).audit_timeout_replacements(
        args.experiment_id
    )
    print(
        json.dumps(
            {
                "experiment_id": args.experiment_id,
                "timeout_replacements_reclassified": repaired,
            },
            indent=2,
        )
    )
    return 0


async def _benchmark_validate(args: argparse.Namespace) -> int:
    catalog = TaskCatalog(_REPOSITORY_ROOT / "benchmarks")
    report = await BenchmarkValidator(
        catalog, DockerWorkspaceFactory(image=args.image)
    ).validate(
        include_external=args.include_external,
        task_ids=set(args.tasks) if args.tasks else None,
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.valid else 1


def _benchmark_import(args: argparse.Namespace) -> int:
    task = HarborTaskAdapter(
        args.path,
        dataset=args.dataset,
        dataset_version=args.dataset_version,
        imported_at=args.imported_at,
        agentscope_commit=None,
    ).import_to_catalog(_REPOSITORY_ROOT / "benchmarks")
    print(f"Imported {task.id} from {task.provenance.source_task_id}")
    print(f"Task hash: {task.provenance.task_hash}")
    return 0


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "run":
            raise SystemExit(asyncio.run(_run_command(args)))
        if args.command == "benchmark":
            if args.benchmark_command == "validate":
                raise SystemExit(asyncio.run(_benchmark_validate(args)))
            if args.benchmark_command == "import-harbor":
                raise SystemExit(_benchmark_import(args))
            manifest = freeze_manifest(_REPOSITORY_ROOT / "benchmarks")
            print(json.dumps(manifest, indent=2, sort_keys=True))
            raise SystemExit(0)
        if args.command == "experiments":
            if args.experiment_command == "validate":
                raise SystemExit(asyncio.run(_experiment_validate(args)))
            if args.experiment_command == "plan":
                raise SystemExit(asyncio.run(_experiment_plan(args)))
            if args.experiment_command == "run":
                raise SystemExit(asyncio.run(_experiment_run(args)))
            if args.experiment_command == "status":
                raise SystemExit(_experiment_status(args))
            if args.experiment_command == "audit":
                raise SystemExit(_experiment_audit(args))
            raise SystemExit(_experiment_summarize(args))
        repository = _repository()
        if args.inspection == "list":
            for run in repository.list_runs(args.limit):
                print(f"{run['run_id']}  {run['task_id']}  {run['status']}  {run['started_at']}")
        else:
            stored = repository.get(args.run_id)
            if stored is None:
                print(f"Run not found: {args.run_id}")
                raise SystemExit(1)
            if args.inspection == "export-atif":
                inference = stored.metrics.inference
                document = export_atif(
                    stored.events,
                    run_id=args.run_id,
                    agent_name=str(stored.summary.get("agent_name", "AgentScope")),
                    input_tokens=inference.input_tokens,
                    output_tokens=inference.output_tokens,
                )
                args.output.write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                print(f"Exported ATIF-v1.8 trajectory to {args.output}")
            else:
                print(json.dumps(stored.model_dump(mode="json"), indent=2, sort_keys=True))
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        raise SystemExit(2) from None
    except Exception as exc:
        print(f"Operation failed: {type(exc).__name__}; check database connectivity and migrations")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
