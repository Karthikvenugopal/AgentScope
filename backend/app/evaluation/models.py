"""Official verification outcomes, separate from agent test results."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerificationErrorCode(StrEnum):
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    INFRASTRUCTURE = "infrastructure"
    INVALID_REPORT = "invalid_report"


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    exit_code: int | None = None
    passed_tests: int | None = Field(default=None, ge=0)
    failed_tests: int | None = Field(default=None, ge=0)
    skipped_tests: int | None = Field(default=None, ge=0)
    total_tests: int | None = Field(default=None, ge=0)
    duration_ms: float = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    failure_reason: str | None = None
    error_code: VerificationErrorCode | None = None

    @model_validator(mode="after")
    def coherent_outcome(self) -> "VerificationResult":
        if self.passed and (self.timed_out or self.exit_code != 0 or self.error_code is not None):
            raise ValueError("passed verification requires exit 0 and no timeout/error")
        if self.passed and self.failed_tests not in {0, None}:
            raise ValueError("passed verification cannot contain failed tests")
        return self
