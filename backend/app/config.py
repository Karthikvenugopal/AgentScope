"""Validated environment configuration; secrets never appear in repr output."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.providers.runtime import DEFAULT_IMAGE

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    database_url: SecretStr
    artifact_root: Path = ROOT / "artifacts"
    benchmark_root: Path = ROOT / "benchmarks"
    max_concurrent_runs: int = Field(default=2, ge=1, le=16)
    max_parallel_implementers: int = Field(default=3, ge=2, le=3)
    max_pending_runs: int = Field(default=100, ge=1, le=10000)
    max_request_bytes: int = Field(default=16384, ge=1024, le=1048576)
    shutdown_grace_seconds: float = Field(default=30, gt=0, le=300)
    environment: Literal["development", "test", "production"] = "development"
    runner_image: str = Field(default="agentscope-runner:py312", min_length=1)
    provider_image: str = DEFAULT_IMAGE
    codex_auth_file: Path | None = None
    claude_auth_file: Path | None = None

    @field_validator("database_url")
    @classmethod
    def postgres_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.database:
                raise ValueError
        except Exception:
            raise ValueError(
                "DATABASE_URL must use postgresql+psycopg and name a database"
            ) from None
        return value
