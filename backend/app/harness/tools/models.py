"""Typed inputs and outputs for harness-controlled agent tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.execution.results import CommandResult

RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=4_096)]


class ToolName(StrEnum):
    LIST_DIRECTORY = "list_directory"
    READ_FILE = "read_file"
    SEARCH_CODE = "search_code"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    CREATE_FILE = "create_file"
    RUN_COMMAND = "run_command"
    RUN_TESTS = "run_tests"
    GIT_DIFF = "git_diff"


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ListDirectoryInput(ToolModel):
    path: RelativePath = "."
    recursive: bool = False
    max_entries: int = Field(default=500, ge=1, le=5_000)


class DirectoryEntry(ToolModel):
    path: str
    kind: str
    size_bytes: int | None = Field(default=None, ge=0)


class ListDirectoryOutput(ToolModel):
    path: str
    entries: tuple[DirectoryEntry, ...]
    truncated: bool


class ReadFileInput(ToolModel):
    path: RelativePath
    max_bytes: int = Field(default=2_000_000, ge=1, le=10_000_000)


class ReadFileOutput(ToolModel):
    path: str
    content: str
    size_bytes: int = Field(ge=0)


class SearchCodeInput(ToolModel):
    query: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    path: RelativePath = "."
    glob: str | None = None
    regex: bool = False
    case_sensitive: bool = True
    max_results: int = Field(default=100, ge=1, le=1_000)


class SearchMatch(ToolModel):
    path: str
    line_number: int = Field(ge=1)
    line: str


class SearchCodeOutput(ToolModel):
    query: str
    matches: tuple[SearchMatch, ...]
    truncated: bool


class WriteFileInput(ToolModel):
    path: RelativePath
    content: str


class CreateFileInput(ToolModel):
    path: RelativePath
    content: str


class EditFileInput(ToolModel):
    path: RelativePath
    old_text: Annotated[str, StringConstraints(min_length=1)]
    new_text: str
    expected_replacements: int = Field(default=1, ge=1)


class FileWriteOutput(ToolModel):
    path: str
    operation: str
    size_bytes: int = Field(ge=0)


class RunCommandInput(ToolModel):
    command: tuple[str, ...] = Field(min_length=1, max_length=256)
    timeout_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def reject_empty_arguments(self) -> RunCommandInput:
        if any(not argument for argument in self.command):
            raise ValueError("command arguments must not be empty")
        return self


class RunTestsInput(ToolModel):
    timeout_seconds: float | None = Field(default=None, gt=0)


class CommandToolOutput(CommandResult):
    pass


class GitDiffInput(ToolModel):
    pass


class GitDiffOutput(ToolModel):
    diff: str
    files_changed: tuple[str, ...]


ToolInput = (
    ListDirectoryInput
    | ReadFileInput
    | SearchCodeInput
    | WriteFileInput
    | CreateFileInput
    | EditFileInput
    | RunCommandInput
    | RunTestsInput
    | GitDiffInput
)
ToolOutput = (
    ListDirectoryOutput
    | ReadFileOutput
    | SearchCodeOutput
    | FileWriteOutput
    | CommandToolOutput
    | GitDiffOutput
)


class ToolExecutionResult(ToolModel):
    tool: str
    success: bool
    output: ToolOutput | None = None
    error: str | None = None
    duration_ms: float = Field(ge=0)


class ToolDefinition(ToolModel):
    name: ToolName
    input_schema: dict[str, object]
