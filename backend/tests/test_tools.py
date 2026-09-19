from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import IsolatedTestRuntime

from app.execution import DockerWorkspace
from app.harness.limits import RunLimitExceeded, RunLimits
from app.harness.snapshot import RepositorySnapshot
from app.harness.tools.base import ToolContext
from app.harness.tools.models import (
    CommandToolOutput,
    GitDiffOutput,
    ListDirectoryOutput,
    ReadFileOutput,
    SearchCodeOutput,
    ToolName,
)
from app.harness.tools.registry import ToolRegistry
from app.models.task import Task
from app.telemetry import TraceRecorder


async def _tools(
    source: Path,
    task: Task,
    runtime: IsolatedTestRuntime,
    *,
    limits: RunLimits | None = None,
    run_id: str = "tool-test",
) -> tuple[DockerWorkspace, ToolRegistry, TraceRecorder]:
    workspace = await DockerWorkspace.create(source, run_id=run_id, runtime=runtime)
    recorder = TraceRecorder(run_id)
    context = ToolContext(
        workspace=workspace,
        task=task,
        limits=limits or RunLimits(),
        recorder=recorder,
        snapshot=await RepositorySnapshot.capture(workspace),
    )
    return workspace, ToolRegistry(context), recorder


async def test_filesystem_tools_return_typed_results(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    workspace, tools, _ = await _tools(source_repository, task, isolated_runtime)
    try:
        listing = await tools.execute("list_directory", {"path": "."})
        read = await tools.execute("read_file", {"path": "app.py"})
        search = await tools.execute("search_code", {"query": "VALUE", "glob": "*.py"})
        created = await tools.execute("create_file", {"path": "created.txt", "content": "first\n"})
        edited = await tools.execute(
            "edit_file",
            {"path": "created.txt", "old_text": "first", "new_text": "second"},
        )
        written = await tools.execute("write_file", {"path": "created.txt", "content": "third\n"})

        assert isinstance(listing.output, ListDirectoryOutput)
        assert [entry.path for entry in listing.output.entries] == ["app.py", "nested"]
        assert isinstance(read.output, ReadFileOutput)
        assert "before" in read.output.content
        assert isinstance(search.output, SearchCodeOutput)
        assert search.output.matches[0].path == "app.py"
        assert created.success and edited.success and written.success
        assert await workspace.read_text("created.txt") == "third\n"
    finally:
        await workspace.close()


async def test_registry_exposes_provider_neutral_json_schemas(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    workspace, tools, _ = await _tools(source_repository, task, isolated_runtime)
    try:
        definitions = {definition.name: definition for definition in tools.definitions}

        assert set(definitions) == set(ToolName)
        assert "properties" in definitions[ToolName.EDIT_FILE].input_schema
        assert "old_text" in definitions[ToolName.EDIT_FILE].input_schema["properties"]
    finally:
        await workspace.close()


@pytest.mark.parametrize("tool", ["read_file", "write_file", "create_file"])
async def test_filesystem_tools_reject_path_traversal(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
    tool: str,
) -> None:
    workspace, tools, recorder = await _tools(source_repository, task, isolated_runtime)
    arguments = {"path": "../outside.txt"}
    if tool != "read_file":
        arguments["content"] = "unsafe"
    try:
        result = await tools.execute(tool, arguments)

        assert result.success is False
        assert result.error and "escapes root" in result.error
        assert recorder.events[-1].event_type == "tool_call_failed"
    finally:
        await workspace.close()


async def test_filesystem_tools_reject_symlink_escape(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
    tmp_path: Path,
) -> None:
    workspace, tools, _ = await _tools(source_repository, task, isolated_runtime)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace.host_path / "escape").symlink_to(outside, target_is_directory=True)
    try:
        result = await tools.execute("write_file", {"path": "escape/file.txt", "content": "unsafe"})

        assert result.success is False
        assert not (outside / "file.txt").exists()
    finally:
        await workspace.close()


async def test_run_command_executes_in_isolated_workspace(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    workspace, tools, recorder = await _tools(source_repository, task, isolated_runtime)
    try:
        result = await tools.execute(
            "run_command",
            {"command": [sys.executable, "-c", "import os; print(os.path.basename(os.getcwd()))"]},
        )

        assert result.success is True
        assert isinstance(result.output, CommandToolOutput)
        assert result.output.stdout.strip() == "workspace"
        assert any(event.event_type == "command_executed" for event in recorder.events)
    finally:
        await workspace.close()


async def test_command_timeout_is_structured_and_stops_container(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    limits = RunLimits(command_timeout_seconds=0.02)
    workspace, tools, recorder = await _tools(
        source_repository, task, isolated_runtime, limits=limits, run_id="command-timeout"
    )
    result = await tools.execute(
        "run_command",
        {"command": [sys.executable, "-c", "import time; time.sleep(2)"]},
    )

    assert result.success is False
    assert isinstance(result.output, CommandToolOutput)
    assert result.output.timed_out is True
    assert [event.event_type for event in recorder.events][-2:] == [
        "command_executed",
        "tool_call_failed",
    ]
    assert isolated_runtime.stop_calls == ["agentscope-command-timeout"]
    await workspace.close()


async def test_command_output_limit_records_truncation(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    limits = RunLimits(max_captured_output_bytes=10)
    workspace, tools, recorder = await _tools(
        source_repository, task, isolated_runtime, limits=limits
    )
    try:
        result = await tools.execute(
            "run_command",
            {"command": [sys.executable, "-c", "print('x' * 100)"]},
        )

        assert isinstance(result.output, CommandToolOutput)
        assert len(result.output.stdout.encode()) == 10
        assert result.output.stdout_truncated is True
        command_event = next(
            event for event in recorder.events if event.event_type == "command_executed"
        )
        assert command_event.stdout_truncated is True
    finally:
        await workspace.close()


async def test_file_write_limit_fails_without_modifying_file(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    limits = RunLimits(max_file_write_bytes=4)
    workspace, tools, _ = await _tools(source_repository, task, isolated_runtime, limits=limits)
    try:
        result = await tools.execute("write_file", {"path": "too-large.txt", "content": "12345"})

        assert result.success is False
        assert not (workspace.host_path / "too-large.txt").exists()
    finally:
        await workspace.close()


async def test_tool_call_limit_emits_failure_and_raises(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    workspace, tools, recorder = await _tools(
        source_repository,
        task,
        isolated_runtime,
        limits=RunLimits(max_tool_calls=1),
    )
    try:
        assert (await tools.execute("read_file", {"path": "app.py"})).success
        with pytest.raises(RunLimitExceeded, match="maximum tool call"):
            await tools.execute("read_file", {"path": "app.py"})

        assert tools.tool_calls == 1
        assert recorder.events[-1].event_type == "tool_call_failed"
    finally:
        await workspace.close()


async def test_git_diff_is_based_on_harness_owned_snapshot(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    original = (source_repository / "app.py").read_text()
    workspace, tools, _ = await _tools(source_repository, task, isolated_runtime)
    try:
        await tools.execute(
            "edit_file",
            {"path": "app.py", "old_text": "before", "new_text": "after"},
        )
        result = await tools.execute(ToolName.GIT_DIFF)

        assert isinstance(result.output, GitDiffOutput)
        assert result.output.files_changed == ("app.py",)
        assert "diff --git a/app.py b/app.py" in result.output.diff
        assert "-VALUE = 'before'" in result.output.diff
        assert "+VALUE = 'after'" in result.output.diff
        assert (source_repository / "app.py").read_text() == original
    finally:
        await workspace.close()


async def test_unknown_tool_produces_failed_trace_event(
    source_repository: Path,
    task: Task,
    isolated_runtime: IsolatedTestRuntime,
) -> None:
    workspace, tools, recorder = await _tools(source_repository, task, isolated_runtime)
    try:
        result = await tools.execute("not_a_tool")

        assert result.success is False
        assert [event.event_type for event in recorder.events] == [
            "tool_call_started",
            "tool_call_failed",
        ]
    finally:
        await workspace.close()
