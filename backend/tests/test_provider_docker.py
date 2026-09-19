"""Real container/DB tests with a deterministic diagnostic process, never a model call."""

import asyncio
import os
import uuid
from pathlib import Path

import pytest

from app.agents.external import CodexAgent
from app.harness.artifacts import ArtifactStore
from app.harness.limits import RunLimits
from app.harness.single_agent import SingleAgentHarness
from app.harness.task_catalog import TaskCatalog
from app.providers.runtime import ProviderRuntime
from app.providers.security import Credentials
from app.storage.repository import PostgresRunRepository

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENTSCOPE_RUN_PROVIDER_DOCKER_TESTS") != "1"
        or not os.environ.get("TEST_DATABASE_URL"),
        reason="requires provider image, opt-in Docker flag, and TEST_DATABASE_URL",
    ),
]

AUDIT = """
import os, json
from pathlib import Path
assert "DATABASE_URL" not in os.environ
assert not Path("/var/run/docker.sock").exists()
assert not Path("/run/secrets/codex-auth.json").exists()
assert not Path("/workspace/test_official.py").exists()
assert not any("verification" in str(p) for p in Path("/workspace").rglob("*"))
assert not Path("/benchmarks").exists()
for forbidden in ("/etc/agentscope-write-probe", "/opt/agentscope/write-probe"):
    try:
        Path(forbidden).write_text("must not write")
    except OSError:
        pass
    else:
        raise RuntimeError("root filesystem is writable")
print(json.dumps({"type":"thread.started", "thread_id":"offline-security-test"}), flush=True)
print(json.dumps({"type":"audit.checked", "message":os.environ["CODEX_API_KEY"]}), flush=True)
"""


@pytest.mark.parametrize("fix", [False, True])
async def test_real_provider_isolation_freeze_verification_and_postgres(monkeypatch, tmp_path, fix):
    import app.providers.runtime as module

    fake_secret = "offline-diagnostic-secret-not-a-real-key"
    monkeypatch.setattr(
        module,
        "load_credentials",
        lambda *a: Credentials(environment={"CODEX_API_KEY": fake_secret}),
    )
    script = AUDIT
    if fix:
        script += (
            '\np=Path("app.py"); p.write_text(p.read_text().replace('
            '\'{"state": "healthy"}\', \'{"status": "ok"}\'))\n'
        )
    script += '\nprint(json.dumps({"type":"turn.completed"}), flush=True)\n'
    monkeypatch.setattr(module, "provider_argv", lambda *a: ["python", "-c", script])
    repository = PostgresRunRepository.from_url(os.environ["TEST_DATABASE_URL"])
    harness = SingleAgentHarness(
        catalog=TaskCatalog(ROOT / "benchmarks"),
        provider_runtime=ProviderRuntime(),
        artifact_store=ArtifactStore(tmp_path),
        repository=repository,
        limits=RunLimits(overall_timeout_seconds=30),
    )
    result = await harness.run(
        "incorrect_api_response", CodexAgent(), run_id=f"offline-provider-{uuid.uuid4().hex}"
    )
    assert result.status.value == ("completed" if fix else "verification_failed"), (
        result.failure_reason
    )
    assert result.verification and result.verification.passed_tests == (3 if fix else 0)
    assert not await asyncio.to_thread(Path(result.workspace.host_path).exists)
    stored = await asyncio.to_thread(repository.get, result.run_id)
    assert stored and stored.events == result.events
    assert stored.metrics.inference.input_tokens is None
    assert (
        "audit.checked" in stored.model_dump_json() and fake_secret not in stored.model_dump_json()
    )
    for artifact in result.artifact_metadata:
        assert fake_secret not in await asyncio.to_thread(Path(artifact.path).read_text)
    assert (
        '{"state": "healthy"}'
        in (ROOT / "benchmarks/fixtures/incorrect_api_response/app.py").read_text()
    )
