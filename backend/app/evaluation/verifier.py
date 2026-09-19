"""Independent pytest verification in a fresh execution environment."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from time import monotonic
from typing import Protocol

from app.evaluation.models import VerificationErrorCode, VerificationResult
from app.execution import Workspace
from app.execution.container import _run_process
from app.harness.task_catalog import TaskCatalog
from app.harness.workspace_factory import WorkspaceFactory
from app.models.task import Task

IGNORED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def source_digest(root: Path) -> str:
    """Hash relative names and content, independent of host paths and mtimes."""
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if IGNORED.intersection(relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("source trees must not contain symbolic links")
        if path.is_file():
            entries.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def copy_candidate(source: Path, target: Path) -> None:
    """Copy only regular files; never dereference agent-created links or devices."""
    target.mkdir()
    for directory, directories, files in os.walk(source, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in IGNORED)
        relative = Path(directory).relative_to(source)
        for name in directories + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f"candidate contains unsupported file: {relative / name}")
        for name in directories:
            (target / relative / name).mkdir()
        for name in files:
            if Path(name).suffix not in {".pyc", ".pyo"}:
                shutil.copyfile(Path(directory) / name, target / relative / name)


class BenchmarkVerifier(Protocol):
    async def verify(self, task: Task, workspace: Workspace) -> VerificationResult: ...


class AdaptiveBenchmarkVerifier:
    """Dispatch verification by task semantics, never by agent output."""

    def __init__(
        self, catalog: TaskCatalog, factory: WorkspaceFactory, *, max_output_bytes: int = 1_000_000
    ) -> None:
        self.pytest = PytestBenchmarkVerifier(
            catalog, factory, max_output_bytes=max_output_bytes
        )
        self.harbor = HarborBenchmarkVerifier(
            catalog, max_output_bytes=max_output_bytes
        )

    async def verify(self, task: Task, workspace: Workspace) -> VerificationResult:
        if task.verification is not None and task.verification.kind == "harbor":
            return await self.harbor.verify(task, workspace)
        return await self.pytest.verify(task, workspace)


class HarborBenchmarkVerifier:
    """Run a Harbor task's official test entrypoint after candidate freeze.

    The candidate is copied before tests are mounted. The container receives no
    host credentials, database socket, solution directory, or AgentScope source.
    """

    def __init__(self, catalog: TaskCatalog, *, max_output_bytes: int = 1_000_000) -> None:
        self.catalog = catalog
        self.max_output_bytes = max_output_bytes

    async def verify(self, task: Task, workspace: Workspace) -> VerificationResult:
        started = monotonic()
        try:
            if task.verification is None or task.verification.kind != "harbor":
                raise ValueError("Harbor verification is not configured")
            async with asyncio.timeout(task.verification.timeout_seconds):
                return await self._verify(task, workspace, started)
        except TimeoutError:
            return VerificationResult(
                passed=False,
                duration_ms=(monotonic() - started) * 1000,
                timed_out=True,
                error_code=VerificationErrorCode.TIMEOUT,
                failure_reason="official Harbor verifier exceeded its time budget",
            )
        except Exception as exc:
            return VerificationResult(
                passed=False,
                duration_ms=(monotonic() - started) * 1000,
                error_code=VerificationErrorCode.INFRASTRUCTURE,
                failure_reason=f"Harbor verifier error: {type(exc).__name__}: {exc}",
            )

    async def _verify(
        self, task: Task, workspace: Workspace, started: float
    ) -> VerificationResult:
        assert task.verification is not None
        if not task.environment.image:
            raise ValueError("Harbor Dockerfile builds must be materialized before execution")
        tests = await asyncio.to_thread(self.catalog.resolve_verification, task)
        await workspace.freeze()
        staging = Path(tempfile.mkdtemp(prefix="agentscope-harbor-verification-"))
        name = f"agentscope-harbor-verify-{uuid.uuid4().hex[:16]}"
        try:
            candidate = staging / "candidate"
            official = staging / "tests"
            logs = staging / "logs"
            await asyncio.to_thread(copy_candidate, workspace.host_path, candidate)
            await asyncio.to_thread(shutil.copytree, tests, official)
            logs.mkdir()
            network = "none" if task.environment.network_mode == "no-network" else "bridge"
            command = (
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--label",
                f"dev.agentscope.run_id={workspace.run_id}",
                "--network",
                network,
                "--cpus",
                "2",
                "--memory",
                "2g",
                "--pids-limit",
                "256",
                "--security-opt",
                "no-new-privileges",
                "--volume",
                f"{candidate}:{task.environment.workdir}:rw",
                "--volume",
                f"{official}:/tests:ro",
                "--volume",
                f"{logs}:/logs/verifier:rw",
                "--workdir",
                task.environment.workdir,
                task.environment.image,
                "bash",
                f"/tests/{task.verification.command or 'test.sh'}",
            )
            result = await _run_process(
                command,
                timeout_seconds=task.verification.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
            reward = self._reward(logs)
            passed = result.exit_code == 0 and reward == 1.0 and not result.timed_out
            counts = self._ctrf_counts(logs / "ctrf.json")
            return VerificationResult(
                passed=passed,
                exit_code=0 if passed else result.exit_code,
                passed_tests=counts[0] if counts else None,
                failed_tests=counts[1] if counts else None,
                skipped_tests=counts[2] if counts else None,
                total_tests=counts[3] if counts else None,
                duration_ms=(monotonic() - started) * 1000,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=result.timed_out,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                failure_reason=None if passed else "official Harbor verifier did not award 1",
                error_code=None if passed else VerificationErrorCode.TEST_FAILURE,
            )
        finally:
            with contextlib.suppress(Exception):
                await _run_process(
                    ("docker", "rm", "--force", name),
                    timeout_seconds=15,
                    max_output_bytes=4096,
                )
            await asyncio.to_thread(shutil.rmtree, staging, True)

    @staticmethod
    def _reward(logs: Path) -> float | None:
        json_path = logs / "reward.json"
        if json_path.is_file():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                value = payload.get("reward")
                return float(value) if isinstance(value, int | float) else None
        text_path = logs / "reward.txt"
        if text_path.is_file():
            try:
                return float(text_path.read_text(encoding="utf-8").strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _ctrf_counts(path: Path) -> tuple[int, int, int, int] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            summary = payload["results"]["summary"]
            return (
                int(summary.get("passed", 0)),
                int(summary.get("failed", 0)),
                int(summary.get("skipped", 0)),
                int(summary.get("tests", 0)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


class PytestBenchmarkVerifier:
    """Official tests use a fresh container and trusted pytest configuration.

    The agent container must be stopped first. Hidden tests are staged outside
    its mount and are never added to its repository copy.
    """

    def __init__(
        self, catalog: TaskCatalog, factory: WorkspaceFactory, *, max_output_bytes: int = 1_000_000
    ) -> None:
        self.catalog = catalog
        self.factory = factory
        self.max_output_bytes = max_output_bytes

    async def verify(self, task: Task, workspace: Workspace) -> VerificationResult:
        started = monotonic()
        try:
            if task.verification is None:
                raise ValueError("official verification is not configured")
            async with asyncio.timeout(task.verification.timeout_seconds):
                return await self._verify(task, workspace, started)
        except TimeoutError:
            return VerificationResult(
                passed=False,
                duration_ms=(monotonic() - started) * 1000,
                timed_out=True,
                error_code=VerificationErrorCode.TIMEOUT,
                failure_reason="official verifier exceeded its time budget",
            )
        except Exception as exc:
            return VerificationResult(
                passed=False,
                duration_ms=(monotonic() - started) * 1000,
                error_code=VerificationErrorCode.INFRASTRUCTURE,
                failure_reason=f"verifier error: {type(exc).__name__}: {exc}",
            )

    async def _verify(
        self, task: Task, agent_workspace: Workspace, started: float
    ) -> VerificationResult:
        assert task.verification is not None
        hidden = await asyncio.to_thread(self.catalog.resolve_verification, task)
        # Stopping the runtime also kills detached agent processes before copying.
        await agent_workspace.freeze()
        staging = Path(tempfile.mkdtemp(prefix="agentscope-verification-"))
        verifier_workspace: Workspace | None = None
        try:
            await asyncio.to_thread(
                copy_candidate, agent_workspace.host_path, staging / "candidate"
            )
            await asyncio.to_thread(shutil.copytree, hidden, staging / "official")
            verifier_workspace = await self.factory.create(
                staging,
                run_id=f"verify-{uuid.uuid4().hex}",
                keep_workspace=False,
            )
            if not verifier_workspace.execution_is_isolated:
                raise ValueError("official verifier requires an isolated runtime")
            command = (
                "env",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "PYTHONDONTWRITEBYTECODE=1",
                "python",
                "-I",
                "-m",
                "pytest",
                "official",
                "-q",
                "--noconftest",
                "-c",
                "/dev/null",
                "-p",
                "no:cacheprovider",
                "--junitxml=report.xml",
            )
            result = await verifier_workspace.execute(
                command,
                timeout_seconds=task.verification.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
            counts: tuple[int, int, int, int] | None = None
            report_error: str | None = None
            if not result.timed_out:
                try:
                    report = await verifier_workspace.read_text("report.xml", max_bytes=2_000_000)
                    counts = parse_junit(report)
                except (OSError, ValueError, RuntimeError, ET.ParseError) as exc:
                    report_error = f"invalid or missing official JUnit report: {exc}"
            passed = result.exit_code == 0 and counts is not None and counts[0] == counts[3]
            passed = passed and counts is not None and counts[3] > 0 and not result.timed_out
            error = None
            reason = None
            if not passed:
                error = VerificationErrorCode.TEST_FAILURE
                reason = f"official tests did not pass (exit {result.exit_code})"
                if result.timed_out:
                    error, reason = VerificationErrorCode.TIMEOUT, "official tests timed out"
                elif report_error:
                    error, reason = VerificationErrorCode.INVALID_REPORT, report_error
            return VerificationResult(
                passed=passed,
                exit_code=result.exit_code,
                passed_tests=counts[0] if counts else None,
                failed_tests=counts[1] if counts else None,
                skipped_tests=counts[2] if counts else None,
                total_tests=counts[3] if counts else None,
                duration_ms=(monotonic() - started) * 1000,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=result.timed_out,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                failure_reason=reason,
                error_code=error,
            )
        finally:
            try:
                if verifier_workspace is not None:
                    await verifier_workspace.close()
            finally:
                await asyncio.to_thread(shutil.rmtree, staging)


def parse_junit(document: str) -> tuple[int, int, int, int]:
    """Count actual JUnit testcase nodes, including errors and skipped cases."""
    root = ET.fromstring(document)
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("expected JUnit test suites")
    cases = list(root.iter("testcase"))
    failed = sum(
        case.find("failure") is not None or case.find("error") is not None for case in cases
    )
    skipped = sum(case.find("skipped") is not None for case in cases)
    return len(cases) - failed - skipped, failed, skipped, len(cases)
