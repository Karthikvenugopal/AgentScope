"""Controlled filesystem, command, test, and patch tools."""

from __future__ import annotations

import asyncio
import fnmatch
import re
import shlex

from pydantic import BaseModel

from app.execution.workspace import resolve_workspace_path
from app.harness.tools.base import ToolContext, ToolExecutionError
from app.harness.tools.models import (
    CommandToolOutput,
    CreateFileInput,
    DirectoryEntry,
    EditFileInput,
    FileWriteOutput,
    GitDiffInput,
    GitDiffOutput,
    ListDirectoryInput,
    ListDirectoryOutput,
    ReadFileInput,
    ReadFileOutput,
    RunCommandInput,
    RunTestsInput,
    SearchCodeInput,
    SearchCodeOutput,
    SearchMatch,
    ToolName,
    ToolOutput,
    WriteFileInput,
)
from app.telemetry.events import FileModifiedEvent, TestExecutedEvent

_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}


def _expect(arguments: BaseModel, expected: type[BaseModel]) -> BaseModel:
    if not isinstance(arguments, expected):  # pragma: no cover - registry contract
        raise TypeError(f"expected {expected.__name__}")
    return arguments


class ListDirectoryTool:
    name = ToolName.LIST_DIRECTORY
    input_model = ListDirectoryInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, ListDirectoryInput)
        assert isinstance(request, ListDirectoryInput)
        root = context.workspace.host_path.resolve()
        directory = resolve_workspace_path(root, request.path, allow_root=True)
        if not await asyncio.to_thread(directory.is_dir):
            raise ToolExecutionError(f"not a directory: {request.path}")

        def scan() -> ListDirectoryOutput:
            iterator = directory.rglob("*") if request.recursive else directory.iterdir()
            entries: list[DirectoryEntry] = []
            truncated = False
            for path in sorted(iterator):
                relative = path.relative_to(root)
                if _IGNORED_DIRECTORY_NAMES.intersection(relative.parts):
                    continue
                if len(entries) >= request.max_entries:
                    truncated = True
                    break
                if path.is_symlink():
                    kind = "symlink"
                    size = None
                elif path.is_dir():
                    kind = "directory"
                    size = None
                elif path.is_file():
                    kind = "file"
                    size = path.stat().st_size
                else:
                    kind = "other"
                    size = None
                entries.append(DirectoryEntry(path=relative.as_posix(), kind=kind, size_bytes=size))
            return ListDirectoryOutput(
                path=request.path,
                entries=tuple(entries),
                truncated=truncated,
            )

        return await asyncio.to_thread(scan)


class ReadFileTool:
    name = ToolName.READ_FILE
    input_model = ReadFileInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, ReadFileInput)
        assert isinstance(request, ReadFileInput)
        try:
            content = await context.workspace.read_text(request.path, max_bytes=request.max_bytes)
        except UnicodeDecodeError as exc:
            raise ToolExecutionError(f"file is not UTF-8 text: {request.path}") from exc
        return ReadFileOutput(
            path=request.path,
            content=content,
            size_bytes=len(content.encode("utf-8")),
        )


class SearchCodeTool:
    name = ToolName.SEARCH_CODE
    input_model = SearchCodeInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, SearchCodeInput)
        assert isinstance(request, SearchCodeInput)
        root = context.workspace.host_path.resolve()
        search_root = resolve_workspace_path(root, request.path, allow_root=True)
        if not await asyncio.to_thread(search_root.exists):
            raise ToolExecutionError(f"search path does not exist: {request.path}")
        try:
            flags = 0 if request.case_sensitive else re.IGNORECASE
            expression = request.query if request.regex else re.escape(request.query)
            pattern = re.compile(expression, flags)
        except re.error as exc:
            raise ToolExecutionError(f"invalid search regular expression: {exc}") from exc

        def search() -> SearchCodeOutput:
            candidates = [search_root] if search_root.is_file() else search_root.rglob("*")
            matches: list[SearchMatch] = []
            truncated = False
            for path in sorted(candidates):
                relative = path.relative_to(root)
                if (
                    _IGNORED_DIRECTORY_NAMES.intersection(relative.parts)
                    or path.is_symlink()
                    or not path.is_file()
                    or (request.glob and not fnmatch.fnmatch(relative.as_posix(), request.glob))
                ):
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if pattern.search(line) is None:
                        continue
                    if len(matches) >= request.max_results:
                        truncated = True
                        break
                    matches.append(
                        SearchMatch(
                            path=relative.as_posix(),
                            line_number=line_number,
                            line=line,
                        )
                    )
                if truncated:
                    break
            return SearchCodeOutput(
                query=request.query,
                matches=tuple(matches),
                truncated=truncated,
            )

        return await asyncio.to_thread(search)


async def _write(
    *,
    path: str,
    content: str,
    operation: str,
    context: ToolContext,
) -> FileWriteOutput:
    size = len(content.encode("utf-8"))
    if size > context.limits.max_file_write_bytes:
        raise ToolExecutionError(
            f"file write is {size} bytes; limit is {context.limits.max_file_write_bytes}"
        )
    await context.workspace.write_text(path, content)
    output = FileWriteOutput(path=path, operation=operation, size_bytes=size)
    await context.recorder.emit(
        FileModifiedEvent,
        path=path,
        operation=operation,
        size_bytes=size,
    )
    return output


class WriteFileTool:
    name = ToolName.WRITE_FILE
    input_model = WriteFileInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, WriteFileInput)
        assert isinstance(request, WriteFileInput)
        path = resolve_workspace_path(context.workspace.host_path, request.path)
        operation = "written" if await asyncio.to_thread(path.exists) else "created"
        return await _write(
            path=request.path,
            content=request.content,
            operation=operation,
            context=context,
        )


class CreateFileTool:
    name = ToolName.CREATE_FILE
    input_model = CreateFileInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, CreateFileInput)
        assert isinstance(request, CreateFileInput)
        path = resolve_workspace_path(context.workspace.host_path, request.path)
        if await asyncio.to_thread(path.exists):
            raise ToolExecutionError(f"file already exists: {request.path}")
        return await _write(
            path=request.path,
            content=request.content,
            operation="created",
            context=context,
        )


class EditFileTool:
    name = ToolName.EDIT_FILE
    input_model = EditFileInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, EditFileInput)
        assert isinstance(request, EditFileInput)
        content = await context.workspace.read_text(request.path)
        replacements = content.count(request.old_text)
        if replacements != request.expected_replacements:
            raise ToolExecutionError(
                f"expected {request.expected_replacements} replacement(s) in {request.path}, "
                f"found {replacements}"
            )
        updated = content.replace(request.old_text, request.new_text)
        return await _write(
            path=request.path,
            content=updated,
            operation="edited",
            context=context,
        )


class RunCommandTool:
    name = ToolName.RUN_COMMAND
    input_model = RunCommandInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, RunCommandInput)
        assert isinstance(request, RunCommandInput)
        result = await context.run_isolated_command(
            request.command,
            timeout_seconds=request.timeout_seconds,
            purpose="agent_command",
        )
        output = CommandToolOutput.model_validate(result.model_dump())
        if result.timed_out:
            raise ToolExecutionError("command timed out", output=output)
        return output


class RunTestsTool:
    name = ToolName.RUN_TESTS
    input_model = RunTestsInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = _expect(arguments, RunTestsInput)
        assert isinstance(request, RunTestsInput)
        command = tuple(shlex.split(context.task.test_command))
        if not command:
            raise ToolExecutionError("task test command is empty")
        result = await context.run_isolated_command(
            command,
            timeout_seconds=request.timeout_seconds,
            purpose="task_tests",
        )
        await context.recorder.emit(
            TestExecutedEvent,
            command=result.command,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
        )
        output = CommandToolOutput.model_validate(result.model_dump())
        if result.timed_out:
            raise ToolExecutionError("test command timed out", output=output)
        return output


class GitDiffTool:
    name = ToolName.GIT_DIFF
    input_model = GitDiffInput

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        _expect(arguments, GitDiffInput)
        patch, files_changed = await context.snapshot.diff(context.workspace)
        return GitDiffOutput(diff=patch, files_changed=files_changed)


BUILTIN_TOOLS = (
    ListDirectoryTool(),
    ReadFileTool(),
    SearchCodeTool(),
    WriteFileTool(),
    EditFileTool(),
    CreateFileTool(),
    RunCommandTool(),
    RunTestsTool(),
    GitDiffTool(),
)
