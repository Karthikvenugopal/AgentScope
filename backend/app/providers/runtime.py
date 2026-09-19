"""Bounded streaming execution in a dedicated, disposable provider container."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from app.execution.container import _run_process
from app.execution.workspace import Workspace
from app.harness.limits import RunLimits
from app.models.task import Task
from app.providers.events import EventParser, Observation
from app.providers.models import (
    ProviderAvailability,
    ProviderCapabilities,
    ProviderFailure,
    ProviderMetadata,
    ProviderName,
)
from app.providers.security import load_credentials
from app.telemetry.events import ProviderTraceEvent
from app.telemetry.recorder import TraceRecorder

DEFAULT_IMAGE = "agentscope-providers:codex-0.154.0-claude-2.1.220"
MAX_EVENT_BYTES = 65536
MAX_EVENTS = 2000


def provider_argv(provider: ProviderName, prompt: str, model: str | None) -> list[str]:
    if provider == ProviderName.CODEX:
        argv = [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "multi_agent",
            "--disable",
            "multi_agent_v2",
            "--disable",
            "apps",
            "--disable",
            "plugins",
            "--disable",
            "hooks",
            "--disable",
            "remote_plugin",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--dangerously-bypass-approvals-and-sandbox",
            "--cd",
            "/workspace",
        ]
    else:
        argv = [
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--safe-mode",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "Bash,Read,Edit,Write,Grep,Glob",
            "--allowedTools",
            "Bash,Read,Edit,Write,Grep,Glob",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-chrome",
            "--max-budget-usd",
            "1",
        ]
    if model:
        argv += ["--model", model]
    return [*argv, prompt]


def isolation_flags(uid: int, gid: int) -> list[str]:
    return [
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        "--pids-limit",
        "256",
        "--user",
        f"{uid}:{gid}",
        "--tmpfs",
        f"/home/agent:rw,nosuid,nodev,size=64m,uid={uid},gid={gid},mode=700",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
    ]


class ProviderRuntime:
    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        codex_auth_file: Path | None = None,
        claude_auth_file: Path | None = None,
    ) -> None:
        self.image = image
        self.paths = {ProviderName.CODEX: codex_auth_file, ProviderName.CLAUDE: claude_auth_file}
        self._probes: dict[ProviderName, tuple[float, ProviderAvailability]] = {}

    async def probe(self, provider: ProviderName, *, refresh: bool = False) -> ProviderAvailability:
        cached = self._probes.get(provider)
        if not refresh and cached and monotonic() - cached[0] < 30:
            return cached[1]
        version: str | None = None
        reason: str | None = None
        probe_name = f"agentscope-probe-{uuid.uuid4().hex}"
        try:
            binary = "codex" if provider == ProviderName.CODEX else "claude"
            result = await _run_process(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    probe_name,
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    *isolation_flags(10001, 10001),
                    self.image,
                    binary,
                    "--version",
                ],
                timeout_seconds=20,
                max_output_bytes=4096,
            )
            if result.timed_out or result.exit_code:
                raise ProviderFailure("provider_runtime_unavailable")
            version = result.stdout.strip()[:100]
            expected = (
                "codex-cli 0.154.0" if provider == ProviderName.CODEX else "2.1.220 (Claude Code)"
            )
            if expected != version:
                raise ProviderFailure("unsupported_provider_version")
            load_credentials(provider, self.paths[provider])
        except ProviderFailure as exc:
            reason = exc.code
        except (OSError, RuntimeError):
            reason = "provider_runtime_unavailable"
        finally:
            with suppress(OSError, RuntimeError):
                await _run_process(
                    ["docker", "rm", "--force", probe_name],
                    timeout_seconds=10,
                    max_output_bytes=1024,
                )
        availability = ProviderAvailability(
            id=provider.value,
            available=reason is None,
            version=version,
            reason=reason,
            capabilities=ProviderCapabilities(per_request_usage=provider == ProviderName.CLAUDE),
        )
        self._probes[provider] = (monotonic(), availability)
        return availability

    async def execute(
        self,
        provider: ProviderName,
        model: str | None,
        task: Task,
        workspace: Workspace,
        limits: RunLimits,
        recorder: TraceRecorder,
        *,
        role: str | None = None,
    ) -> ProviderMetadata:
        available = await self.probe(provider)
        if not available.available:
            raise ProviderFailure(available.reason or "provider_unavailable")
        credentials = load_credentials(provider, self.paths[provider])
        redactor = credentials.redactor()
        parser = EventParser(provider, redactor)
        name = f"agentscope-provider-{uuid.uuid4().hex}"
        uid, gid = os.getuid() or 10001, os.getgid() or 10001
        if os.getuid() == 0:
            await asyncio.to_thread(_give_workspace_to_agent, workspace.host_path, uid, gid)
        image_result = await _run_process(
            ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
            timeout_seconds=10,
        )
        if image_result.exit_code:
            raise ProviderFailure("provider_runtime_unavailable")
        metadata = ProviderMetadata(
            provider=provider,
            version=available.version or "unknown",
            image=self.image,
            image_id=image_result.stdout.strip(),
            model=model,
        )
        process: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task[Any]] = []
        launched = monotonic()
        process_started_at = None
        first_output: float | None = None
        total_bytes = 0
        retained = 0
        tool_ids: set[str] = set()
        message_ids: set[str] = set()
        active_tools: dict[str, float] = {}
        turns = 0
        failed: str | None = None
        container_exit_code: int | None = None
        stderr_capture = bytearray()
        stderr_truncated = False

        async def emit(observation: Observation) -> None:
            nonlocal retained, turns
            retained += 1
            if retained > MAX_EVENTS:
                raise ProviderFailure("provider_event_limit")
            payload = observation.payload
            tool_id = payload.get("tool_id")
            if isinstance(tool_id, str) and "tool" in payload:
                tool_ids.add(tool_id)
                if len(tool_ids) > limits.max_tool_calls:
                    raise ProviderFailure("provider_tool_limit")
            if observation.event_type == "provider_tool_call_started" and tool_id:
                active_tools[tool_id] = monotonic()
            elif observation.event_type == "provider_tool_call_completed" and isinstance(
                tool_id, str
            ):
                active_tools.pop(tool_id, None)
            # These are CLI conversational turns, not model request boundaries.
            message_id = payload.get("native_message_id")
            new_message = isinstance(message_id, str) and message_id not in message_ids
            if new_message and isinstance(message_id, str):
                message_ids.add(message_id)
            if observation.native_type == "turn.started" or new_message:
                turns += 1
                if turns > limits.max_agent_turns:
                    raise ProviderFailure("provider_turn_limit")
            await recorder.emit(
                ProviderTraceEvent,
                event_type=observation.event_type,
                provider=provider.value,
                native_type=observation.native_type,
                payload=payload,
            )

        async def consume(stream: asyncio.StreamReader, *, structured: bool) -> None:
            nonlocal first_output, total_bytes, stderr_truncated
            buffer = bytearray()
            while chunk := await stream.read(8192):
                if first_output is None and structured:
                    first_output = (monotonic() - launched) * 1000
                total_bytes += len(chunk)
                if total_bytes > limits.max_captured_output_bytes:
                    raise ProviderFailure("provider_output_limit")
                if not structured:
                    stderr_truncated |= len(chunk) > max(0, 4096 - len(stderr_capture))
                    stderr_capture.extend(chunk[: max(0, 4096 - len(stderr_capture))])
                    continue
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if len(line) > MAX_EVENT_BYTES:
                        raise ProviderFailure("provider_event_size_limit")
                    if line.strip():
                        for observation in parser.parse(bytes(line)):
                            await emit(observation)
                if len(buffer) > MAX_EVENT_BYTES:
                    raise ProviderFailure("provider_event_size_limit")
            if structured and buffer.strip():
                for observation in parser.parse(bytes(buffer)):
                    await emit(observation)

        async def watchdog() -> None:
            while process is not None and process.returncode is None:
                await asyncio.to_thread(
                    _check_candidate_sizes, workspace.host_path, limits.max_file_write_bytes
                )
                if any(
                    monotonic() - start > limits.command_timeout_seconds
                    for start in active_tools.values()
                ):
                    raise ProviderFailure("provider_tool_timeout")
                await asyncio.sleep(0.1)

        try:
            result = await _run_process(
                [
                    "docker",
                    "create",
                    "--interactive",
                    "--name",
                    name,
                    "--label",
                    f"dev.agentscope.run_id={workspace.run_id}",
                    "--network",
                    "bridge",
                    *isolation_flags(uid, gid),
                    "--mount",
                    f"type=bind,src={workspace.host_path},dst=/workspace",
                    "--workdir",
                    "/workspace",
                    metadata.image_id,
                    "python",
                    "/opt/agentscope/provider_entry.py",
                ],
                timeout_seconds=30,
                max_output_bytes=4096,
            )
            if result.exit_code or result.timed_out:
                raise ProviderFailure("provider_container_start_failed")
            prompt = (
                f"{task.title}\n{task.description}\nExpected behavior: {task.expected_behavior}\n"
                f"Work only in /workspace. Inspect the source, implement the minimal fix, "
                f"and run the visible tests: {task.test_command}. Do not create commits or "
                "modify tests. Do not use subagents. Finish with a short summary."
            )
            if role is not None:
                prompt = (
                    f"{task.title}\n{task.description}\n"
                    f"Expected behavior: {task.expected_behavior}\n"
                    f"Visible test command: {task.test_command}. Work only in /workspace. "
                    "Follow the role instructions above. Planner/reviewer must not implement. "
                    "Do not modify tests, create commits, or delegate to subagents. "
                    "For planner/reviewer, finish with the requested JSON object."
                )
            launched = monotonic()
            process_started_at = datetime.now(UTC)
            process = await asyncio.create_subprocess_exec(
                "docker",
                "start",
                "--attach",
                "--interactive",
                name,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert (
                process.stdin is not None
                and process.stdout is not None
                and process.stderr is not None
            )
            wire = {
                "credentials": credentials.wire(),
                "argv": provider_argv(provider, prompt, model),
            }
            process.stdin.write((json.dumps(wire) + "\n").encode())
            await process.stdin.drain()
            tasks = [
                asyncio.create_task(consume(process.stdout, structured=True)),
                asyncio.create_task(consume(process.stderr, structured=False)),
                asyncio.create_task(process.wait()),
                asyncio.create_task(watchdog()),
            ]
            async with asyncio.timeout(limits.overall_timeout_seconds):
                await asyncio.gather(*tasks)
            state = await _run_process(
                ["docker", "inspect", "--format", "{{json .State}}", name],
                timeout_seconds=10,
            )
            if state.exit_code == 0:
                container_state = json.loads(state.stdout)
                container_exit_code = container_state.get("ExitCode")
                if container_state.get("Running") is not False:
                    raise ProviderFailure("provider_attachment_lost")
                if container_state.get("OOMKilled"):
                    raise ProviderFailure("provider_memory_limit")
                stderr_capture.extend(
                    json.dumps(
                        {
                            k: container_state.get(k)
                            for k in ("ExitCode", "OOMKilled", "Error", "Running")
                        }
                    ).encode()
                )
            else:
                raise ProviderFailure("provider_container_state_unavailable")
            if process.returncode != 0 or container_exit_code != 0:
                raise ProviderFailure(parser.failure or "provider_process_crash")
            if parser.failure or not parser.completed:
                raise ProviderFailure(parser.failure or "missing_provider_completion")
        except ProviderFailure as exc:
            failed = exc.code
        except (TimeoutError, asyncio.CancelledError):
            failed = "provider_timeout_or_cancelled"
            raise
        except Exception:
            failed = "provider_execution_failure"
        finally:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            if process is not None and process.returncode is None:
                process.kill()
            if process is not None:
                await process.wait()
            process_finished_at = datetime.now(UTC) if process is not None else None
            process_duration_ms = (monotonic() - launched) * 1000 if process is not None else None
            await asyncio.gather(*tasks, return_exceptions=True)
            cleanup = await asyncio.shield(
                _run_process(
                    ["docker", "rm", "--force", name],
                    timeout_seconds=30,
                    max_output_bytes=4096,
                )
            )
            if cleanup.timed_out or (
                cleanup.exit_code and "No such container" not in cleanup.stderr
            ):
                failed = "provider_cleanup_failed"
            metadata = metadata.model_copy(
                update={
                    "model": parser.model or model,
                    "session_id": parser.session_id,
                    "exit_code": container_exit_code
                    if container_exit_code is not None
                    else process.returncode
                    if process
                    else None,
                    "duration_ms": (monotonic() - launched) * 1000,
                    "time_to_first_provider_output_ms": first_output,
                    "process_started_at": process_started_at,
                    "process_finished_at": process_finished_at,
                    "process_duration_ms": process_duration_ms,
                }
            )
            if failed in {
                "provider_event_limit",
                "provider_output_limit",
                "provider_event_size_limit",
            }:
                await recorder.emit(
                    ProviderTraceEvent,
                    event_type="provider_output_truncated",
                    provider=provider.value,
                    native_type="harness.limit",
                    payload={"reason": failed, "execution_terminated": True},
                )
            if stderr_truncated:
                await recorder.emit(
                    ProviderTraceEvent,
                    event_type="provider_output_truncated",
                    provider=provider.value,
                    native_type="harness.diagnostics",
                    payload={"reason": "stderr_diagnostic_limit", "execution_terminated": False},
                )
            await recorder.emit(
                ProviderTraceEvent,
                event_type="provider_process_failed" if failed else "provider_session_completed",
                provider=provider.value,
                native_type="harness.process",
                payload={
                    "error_code": failed,
                    "diagnostic": redactor.text(stderr_capture.decode("utf-8", errors="replace")),
                }
                if failed
                else {},
                metadata=metadata,
            )
        if failed:
            if failed == "provider_tool_timeout":
                raise TimeoutError
            raise ProviderFailure(failed)
        # Reject credential contamination before snapshot, verifier, artifacts, or DB.
        await asyncio.to_thread(
            _audit_candidate, workspace.host_path, redactor.secrets, limits.max_file_write_bytes
        )
        return metadata


def _give_workspace_to_agent(root: Path, uid: int, gid: int) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            raise ProviderFailure("unsafe_candidate_path")
        os.chown(path, uid, gid, follow_symlinks=False)


def _audit_candidate(root: Path, secrets: tuple[str, ...], max_file_bytes: int) -> None:
    total = 0
    for path in root.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProviderFailure("unsafe_candidate_path")
        total += info.st_size
        if info.st_size > max_file_bytes or total > 20_000_000:
            raise ProviderFailure("candidate_size_limit")
        data = path.read_bytes()
        if any(secret.encode() in data for secret in secrets):
            raise ProviderFailure("credential_contamination")


def _check_candidate_sizes(root: Path, max_file_bytes: int) -> None:
    """Observe metadata only while the untrusted process runs; audit bytes after stop.

    Native CLIs cannot enforce our per-write tool contract. A 100ms watchdog
    terminates oversize candidates; final audit prevents acceptance between polls.
    HOME and temporary CLI state have separate kernel-enforced tmpfs bounds.
    """
    total = count = 0
    for path in root.rglob("*"):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue  # A normal atomic edit may replace a file between enumerations.
        if stat.S_ISREG(info.st_mode):
            count += 1
            total += info.st_size
            if info.st_size > max_file_bytes or total > 20_000_000 or count > 4096:
                raise ProviderFailure("candidate_size_limit")
