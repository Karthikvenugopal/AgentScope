"""Versioned, provider-neutral benchmark task definitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

TaskId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RepositoryType(StrEnum):
    """Repository transports understood by the task format."""

    LOCAL = "local"
    GIT = "git"


class TaskSource(StrEnum):
    AGENTSCOPE = "agentscope"
    HARBOR = "harbor"
    EXTERNAL = "external"


class TaskDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RepositorySpec(BaseModel):
    """A repository source plus enough provenance to reproduce it later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: RepositoryType = RepositoryType.LOCAL
    source: NonEmptyString
    revision: str | None = None
    subdirectory: str | None = None

    @field_validator("revision", "subdirectory")
    @classmethod
    def reject_blank_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("subdirectory")
    @classmethod
    def require_relative_subdirectory(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("must be a safe relative path")
        return value


class VerificationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NonEmptyString
    timeout_seconds: float = Field(default=60, gt=0, le=3600)
    kind: Literal["pytest", "harbor"] = "pytest"
    command: str | None = None


class TaskEnvironment(BaseModel):
    """Agent-visible execution environment; Harbor source paths remain private."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agentscope", "harbor"] = "agentscope"
    image: str | None = None
    workdir: str = "/workspace"
    build_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    network_mode: Literal["no-network", "public", "allowlist"] = "no-network"


class TaskProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: TaskSource = TaskSource.AGENTSCOPE
    dataset: str = "AgentScope Benchmark"
    dataset_version: str = "0.1"
    source_task_id: str | None = None
    source_version: str | None = None
    task_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    environment_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verifier_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    imported_at: str | None = None
    agentscope_commit: str | None = None
    harbor_version: str | None = None
    harbor_schema_version: str | None = None
    source_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Task(BaseModel):
    """Portable benchmark task manifest.

    Commands remain data here. They are not executed by the loader; the harness
    will apply command policy and limits in later phases.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: TaskId
    title: NonEmptyString
    description: NonEmptyString
    repository: RepositorySpec
    setup_command: str | None = None
    test_command: NonEmptyString
    timeout_seconds: int = Field(ge=1, le=86_400)
    expected_behavior: NonEmptyString
    version: NonEmptyString = "1"
    tags: tuple[str, ...] = ()
    language: NonEmptyString = "Python"
    difficulty: TaskDifficulty = TaskDifficulty.EASY
    provenance: TaskProvenance = Field(default_factory=TaskProvenance)
    environment: TaskEnvironment = Field(default_factory=TaskEnvironment)
    verification: VerificationSpec | None = None

    @field_validator("repository", mode="before")
    @classmethod
    def normalize_repository(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        source = value.strip()
        repository_type = (
            RepositoryType.GIT
            if source.startswith(("https://", "ssh://", "git@"))
            else RepositoryType.LOCAL
        )
        return {"type": repository_type, "source": source}

    @field_validator("setup_command")
    @classmethod
    def normalize_setup_command(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(tag.strip() for tag in value if tag.strip())
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("tags must be unique")
        return cleaned
