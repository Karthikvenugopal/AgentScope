"""Opt-in paid tests: never enabled by ordinary CI or the Docker integration flag."""

import os
import uuid
from pathlib import Path

import pytest

from app.agents.external import ClaudeCodeAgent, CodexAgent
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.providers.runtime import ProviderRuntime
from app.storage.repository import PostgresRunRepository

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("flag", "agent"),
    [
        ("RUN_CODEX_LIVE_TESTS", CodexAgent),
        ("RUN_CLAUDE_LIVE_TESTS", ClaudeCodeAgent),
    ],
)
async def test_live_provider_verified_and_persisted(flag, agent, tmp_path):
    if os.environ.get(flag) != "1":
        pytest.skip(f"opt-in paid test: set {flag}=1")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("live tests require a migrated TEST_DATABASE_URL")
    repository = PostgresRunRepository.from_url(url)
    runtime = ProviderRuntime(
        codex_auth_file=Path(os.environ["CODEX_AUTH_FILE"])
        if os.environ.get("CODEX_AUTH_FILE")
        else None,
        claude_auth_file=Path(os.environ["CLAUDE_AUTH_FILE"])
        if os.environ.get("CLAUDE_AUTH_FILE")
        else None,
    )
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        provider_runtime=runtime,
        repository=repository,
        artifact_store=ArtifactStore(tmp_path),
        limits=RunLimits(overall_timeout_seconds=120, max_tool_calls=12, max_agent_turns=12),
    )
    run = await harness.run("incorrect_api_response", agent(), run_id=f"live-{uuid.uuid4().hex}")
    assert run.status.value == "completed", run.failure_reason
    stored = repository.get(run.run_id)
    assert stored and stored.verification and stored.verification.passed_tests == 3
    assert stored.metrics.inference.mean_ttft_ms is None
    assert stored.metrics.inference.mean_itl_ms is None
    assert stored.metrics.inference.output_tokens_per_second is None
    assert stored.events == run.events and stored.summary["provenance"]["provider"]["version"]
