"""No live model calls: structured fixtures and a test-only subprocess replay."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.external import ClaudeCodeAgent, CodexAgent
from app.execution.results import CommandResult
from app.harness.limits import RunLimits
from app.providers.events import EventParser
from app.providers.models import ProviderFailure, ProviderName
from app.providers.runtime import ProviderRuntime, _audit_candidate, isolation_flags, provider_argv
from app.providers.security import Credentials, Redactor, load_credentials
from app.telemetry.events import ProviderTraceEvent
from app.telemetry.provider_metrics import provider_metrics
from app.telemetry.recorder import TraceRecorder

CODEX = [
    {"type": "thread.started", "thread_id": "test-session"},
    {"type": "turn.started"},
    {
        "type": "item.started",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "command": "python -m pytest",
            "status": "in_progress",
        },
    },
    {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "exit_code": 0,
            "status": "completed",
        },
    },
    {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 31,
            "cached_input_tokens": 12,
            "output_tokens": 7,
            "reasoning_output_tokens": 2,
        },
    },
]
CLAUDE = [
    {"type": "system", "subtype": "init", "session_id": "test-session", "model": "test-model"},
    {
        "type": "assistant",
        "message": {
            "id": "msg-1",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Read",
                    "input": {"file_path": "app.py"},
                },
            ],
        },
    },
    {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "source",
                    "is_error": False,
                },
            ]
        },
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "usage": {
            "input_tokens": 3,
            "output_tokens": 7,
            "cache_read_input_tokens": 12,
            "cache_creation_input_tokens": 4,
        },
    },
]


@pytest.mark.parametrize(
    ("provider", "fixture", "total", "tool"),
    [
        (ProviderName.CODEX, CODEX, 38, "run_command"),
        (ProviderName.CLAUDE, CLAUDE, 26, "read_file"),
    ],
)
async def test_structured_usage_and_tools_preserve_semantics(provider, fixture, total, tool):
    parser = EventParser(provider, Redactor())
    recorder = TraceRecorder("test")
    for raw in fixture:
        for observation in parser.parse(json.dumps(raw).encode()):
            await recorder.emit(
                ProviderTraceEvent,
                provider=provider.value,
                event_type=observation.event_type,
                native_type=observation.native_type,
                payload=observation.payload,
            )
    metrics, tools, successful, failed = provider_metrics(recorder.events)
    assert metrics.total_tokens == total
    assert metrics.output_tokens == 7
    assert metrics.provenance["output_tokens"].provenance == "measured"
    assert metrics.provenance["total_tokens"].provenance == "derived"
    assert metrics.model_calls is metrics.mean_ttft_ms is metrics.mean_itl_ms is None
    assert metrics.output_tokens_per_second is metrics.model_latency_ms is None
    assert tools == {tool: 1} and successful == 1 and failed == 0
    assert parser.completed and parser.session_id == "test-session"
    assert [e.sequence_number for e in recorder.events] == list(range(1, len(recorder.events) + 1))
    assert json.loads(recorder.events[-1].model_dump_json())["event_type"] == "provider_usage"


@pytest.mark.parametrize(
    "line",
    [b"not json", b"[]", b'{"type":2}', b'{"type":"turn.completed","usage":{"input_tokens":true}}'],
)
def test_malformed_events_fail_without_echoing_input(line):
    with pytest.raises(ProviderFailure, match="^malformed_provider_event$"):
        EventParser(ProviderName.CODEX, Redactor()).parse(line)


def test_unknown_event_and_missing_usage_are_not_fabricated():
    parser = EventParser(ProviderName.CODEX, Redactor())
    event = parser.parse(b'{"type":"future.event","new_field":42}')[0]
    assert event.native_type == "future.event" and event.payload["native"]["new_field"] == 42
    event = parser.parse(b'{"type":"turn.completed"}')[0]
    assert all(v is None for v in event.payload["usage"].values())
    metrics, _, _, _ = provider_metrics(())
    assert all(v is None for k, v in metrics.model_dump().items() if k != "provenance")
    assert all(v.provenance == "unavailable" for v in metrics.provenance.values())


def test_secrets_redacted_before_native_event_retention():
    redactor = Credentials(environment={"CODEX_API_KEY": "sensitive-test-value"}).redactor()
    raw = {
        "type": "future.event",
        "access_token": "another-value",
        "text": "sensitive-test-value",
        "nested": [{"authorization": "Bearer abc"}],
        "usage": {"input_tokens": 0},
    }
    result = EventParser(ProviderName.CODEX, redactor).parse(json.dumps(raw).encode())[0]
    encoded = json.dumps(result.payload)
    assert "sensitive-test-value" not in encoded and "another-value" not in encoded
    assert result.payload["native"]["usage"]["input_tokens"] == 0


def test_oauth_metadata_is_not_treated_as_candidate_secret(tmp_path):
    credentials = Credentials(
        claude_auth={
            "claudeAiOauth": {
                "accessToken": "actual-sensitive-token",
                "refreshToken": "actual-refresh-token",
                "subscriptionType": "pro",
                "scopes": ["read", "write"],
            }
        }
    )
    redactor = credentials.redactor()
    assert set(redactor.secrets) == {"actual-sensitive-token", "actual-refresh-token"}
    (tmp_path / "app.py").write_text("def process(): return 'read and write'\n")
    _audit_candidate(tmp_path, redactor.secrets, 1000)
    assert "actual-sensitive-token" not in redactor.text("actual-sensitive-token")


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("401 invalid API key", "authentication_unavailable"),
        ("429 rate limit", "provider_rate_limit"),
        ("invalid model", "provider_model_error"),
        ("upstream unavailable", "provider_api_failure"),
    ],
)
def test_provider_failures_have_safe_codes(message, code):
    parser = EventParser(ProviderName.CODEX, Redactor())
    event = parser.parse(json.dumps({"type": "error", "message": message}).encode())[0]
    assert event.payload == {"error_code": code} and parser.failure == code


def test_credentials_are_explicit_and_not_arbitrary_environment(monkeypatch, tmp_path):
    for name in ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "secret-database-value")
    with pytest.raises(ProviderFailure, match="authentication_unavailable"):
        load_credentials(ProviderName.CODEX)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    credentials = load_credentials(ProviderName.CODEX)
    assert credentials.environment == {"CODEX_API_KEY": "test-key"}
    assert "test-key" not in repr(credentials)
    assert "DATABASE_URL" not in json.dumps(credentials.wire())


def test_isolation_and_bounded_flags():
    flags = isolation_flags(10001, 10001)
    assert "--read-only" in flags and "ALL" in flags and "no-new-privileges" in flags
    assert "--privileged" not in flags and "--volume" not in flags
    assert "--json" in provider_argv(ProviderName.CODEX, "task", None)
    claude = provider_argv(ProviderName.CLAUDE, "task", "test-model")
    assert "stream-json" in claude and "--safe-mode" in claude and "dontAsk" in claude
    assert claude[-3:] == ["--model", "test-model", "task"]
    assert CodexAgent().name == "codex" and ClaudeCodeAgent().name == "claude-code"


def test_candidate_rejects_symlinks_secret_material_and_excess_size(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("secret-value")
    with pytest.raises(ProviderFailure, match="credential_contamination"):
        _audit_candidate(tmp_path, ("secret-value",), 100)
    with pytest.raises(ProviderFailure, match="candidate_size_limit"):
        _audit_candidate(tmp_path, (), 3)
    target.unlink()
    target.symlink_to("/etc/passwd")
    with pytest.raises(ProviderFailure, match="unsafe_candidate_path"):
        _audit_candidate(tmp_path, (), 100)


def replay_runtime(monkeypatch, tmp_path, lines, *, delay=0, exit_code=0):
    import app.providers.runtime as module

    original = asyncio.create_subprocess_exec
    commands = []

    async def command(argv, **kwargs):
        commands.append(argv)
        stdout = "codex-cli 0.154.0" if "--version" in argv else "sha256:test"
        if "{{json .State}}" in argv:
            stdout = json.dumps({"ExitCode": exit_code, "OOMKilled": False, "Running": False})
        return CommandResult(
            command=tuple(argv),
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_ms=1,
            timed_out=False,
        )

    async def process(*argv, **kwargs):
        assert argv[:4] == ("docker", "start", "--attach", "--interactive")
        script = (
            "import sys,json,time; json.loads(sys.stdin.readline()); "
            f"time.sleep({delay}); "
            f"print({lines!r},flush=True); sys.exit({exit_code})"
        )
        return await original(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(module, "_run_process", command)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", process)
    monkeypatch.setattr(
        module,
        "load_credentials",
        lambda *a: Credentials(environment={"CODEX_API_KEY": "test-secret-value"}),
    )
    return ProviderRuntime(), commands


async def test_streaming_lifecycle_cleanup_and_measured_first_output(monkeypatch, tmp_path, task):
    lines = "\n".join(json.dumps(e) for e in CODEX)
    runtime, commands = replay_runtime(monkeypatch, tmp_path, lines)
    recorder = TraceRecorder("stream")
    metadata = await runtime.execute(
        ProviderName.CODEX,
        None,
        task,
        SimpleNamespace(host_path=tmp_path, run_id="stream"),
        RunLimits(),
        recorder,
    )
    assert metadata.exit_code == 0 and metadata.time_to_first_provider_output_ms is not None
    assert commands[-1][:3] == ["docker", "rm", "--force"]
    create = next(c for c in commands if "create" in c)
    assert create.count("--mount") == 1 and "bridge" in create
    assert not any("test-secret-value" in str(c) for c in commands)
    assert recorder.events[-1].event_type == "provider_session_completed"


@pytest.mark.parametrize(
    ("lines", "delay", "exit_code", "limits", "error"),
    [
        ("broken", 0, 0, {}, "malformed_provider_event"),
        ("", 0, 3, {}, "provider_process_crash"),
        ("x" * 100, 0, 0, {"max_captured_output_bytes": 10}, "provider_output_limit"),
        ("", 1, 0, {"overall_timeout_seconds": 0.01}, None),
    ],
)
async def test_stream_failures_cleanup(
    monkeypatch, tmp_path, task, lines, delay, exit_code, limits, error
):
    runtime, commands = replay_runtime(
        monkeypatch, tmp_path, lines, delay=delay, exit_code=exit_code
    )
    recorder = TraceRecorder("failure")
    with pytest.raises(ProviderFailure if error else TimeoutError, match=error):
        await runtime.execute(
            ProviderName.CODEX,
            None,
            task,
            SimpleNamespace(host_path=tmp_path, run_id="failure"),
            RunLimits(**limits),
            recorder,
        )
    assert commands[-1][:3] == ["docker", "rm", "--force"]
    assert recorder.events[-1].event_type == "provider_process_failed"


async def test_discovery_distinguishes_binary_and_auth_unavailable(monkeypatch):
    import app.providers.runtime as module

    async def absent(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module, "_run_process", absent)
    assert not (await ProviderRuntime().probe(ProviderName.CODEX)).available

    async def installed(argv, **kwargs):
        return CommandResult(
            command=tuple(argv),
            exit_code=0,
            stdout="codex-cli 0.154.0",
            stderr="",
            duration_ms=1,
            timed_out=False,
        )

    def no_auth(*args):
        raise ProviderFailure("authentication_unavailable")

    monkeypatch.setattr(module, "_run_process", installed)
    monkeypatch.setattr(module, "load_credentials", no_auth)
    availability = await ProviderRuntime().probe(ProviderName.CODEX)
    assert availability.version == "codex-cli 0.154.0"
    assert availability.reason == "authentication_unavailable" and not availability.available


def test_recorded_claude_stream_from_real_verified_run():
    path = Path(__file__).parent / "fixtures/providers/claude-2.1.220-success.jsonl"
    parser = EventParser(ProviderName.CLAUDE, Redactor())
    observations = [o for line in path.read_bytes().splitlines() for o in parser.parse(line)]
    assert parser.completed and parser.session_id == "recorded-session"
    usage = next(o.payload["usage"] for o in observations if o.event_type == "provider_usage")
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 510
    assert usage["cached_input_tokens"] == 64569
    assert usage["cache_creation_input_tokens"] == 933
    assert sum(o.event_type == "provider_tool_call_started" for o in observations) == 5


def test_recorded_codex_stream_from_real_verified_run():
    path = Path(__file__).parent / "fixtures/providers/codex-0.154.0-success.jsonl"
    parser = EventParser(ProviderName.CODEX, Redactor())
    observations = [o for line in path.read_bytes().splitlines() for o in parser.parse(line)]
    assert parser.completed and parser.session_id == "recorded-session"
    actual = next(o.payload["usage"] for o in observations if o.event_type == "provider_usage")
    assert actual["input_tokens"] == 60677 and actual["output_tokens"] == 274
    assert actual["cache_creation_input_tokens"] == 0


@pytest.mark.parametrize(
    ("records", "limits", "code"),
    [
        (
            CODEX + [{"type": "item.started", "item": {"id": "second", "type": "file_change"}}],
            {"max_tool_calls": 1},
            "provider_tool_limit",
        ),
        (
            [{"type": "turn.started"}, {"type": "turn.started"}],
            {"max_agent_turns": 1},
            "provider_turn_limit",
        ),
    ],
)
async def test_native_observation_limits_terminate_and_cleanup(
    monkeypatch, tmp_path, task, records, limits, code
):
    runtime, commands = replay_runtime(
        monkeypatch, tmp_path, "\n".join(json.dumps(e) for e in records)
    )
    recorder = TraceRecorder("limited")
    with pytest.raises(ProviderFailure, match=code):
        await runtime.execute(
            ProviderName.CODEX,
            None,
            task,
            SimpleNamespace(host_path=tmp_path, run_id="limited"),
            RunLimits(**limits),
            recorder,
        )
    assert commands[-1][:3] == ["docker", "rm", "--force"]
    assert recorder.events[-1].payload["error_code"] == code


def test_expired_claude_auth_is_not_advertised_ready(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "test-secret", "expiresAt": 1}}))
    with pytest.raises(ProviderFailure, match="authentication_expired"):
        load_credentials(ProviderName.CLAUDE, path)
