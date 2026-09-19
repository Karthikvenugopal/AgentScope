"""Explicit credential loading and sanitization before any event is retained."""

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.providers.models import ProviderFailure, ProviderName

_SECRET_KEYS = re.compile(
    r"^(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"password|secret|credentials|codex_api_key|openai_api_key|anthropic_api_key|"
    r"claude_code_oauth_token)$",
    re.I,
)


@dataclass(repr=False)
class Credentials:
    environment: dict[str, str] = field(default_factory=dict)
    codex_auth: dict[str, Any] | None = None
    claude_auth: dict[str, Any] | None = None

    def wire(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "codex_auth": self.codex_auth,
            "claude_auth": self.claude_auth,
        }

    def redactor(self) -> "Redactor":
        def strings(value: Any) -> list[str]:
            if isinstance(value, dict):
                result: list[str] = []
                for key, item in value.items():
                    if _SECRET_KEYS.fullmatch(key) and isinstance(item, str) and item:
                        result.append(item)
                    elif isinstance(item, dict):
                        result.extend(strings(item))
                return result
            return []

        return Redactor(tuple(strings(self.wire())))


@dataclass(repr=False)
class Redactor:
    secrets: tuple[str, ...] = ()

    def text(self, value: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        value = re.sub(
            r"""(?i)((?:CODEX_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH_TOKEN|access[_-]?token|refresh[_-]?token|id[_-]?token|password)["']?\s*[:=]\s*["']?)([^\s,"'}]+)""",
            r"\1[REDACTED]",
            value,
        )
        return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", value)

    def payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {
                self.text(str(k)): "[REDACTED]" if _SECRET_KEYS.match(str(k)) else self.payload(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.payload(v) for v in value]
        return value


def load_credentials(provider: ProviderName, path: Path | None = None) -> Credentials:
    """No implicit HOME/keychain scanning. Operators explicitly configure a minimum auth file."""
    key_names = (
        ("CODEX_API_KEY", "OPENAI_API_KEY")
        if provider == ProviderName.CODEX
        else ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    )
    for name in key_names:
        if value := os.environ.get(name):
            target = "CODEX_API_KEY" if provider == ProviderName.CODEX else name
            return Credentials(environment={target: value})
    if path is not None:
        try:
            if path.stat().st_size > 65536:
                raise ValueError
            data = json.loads(path.read_text())
            if provider == ProviderName.CODEX and isinstance(data.get("tokens"), dict):
                tokens = data["tokens"]
                if not tokens.get("access_token"):
                    raise ValueError
                return Credentials(
                    codex_auth={
                        "auth_mode": "chatgpt",
                        "tokens": tokens,
                        "last_refresh": data.get("last_refresh"),
                    }
                )
            oauth = data.get("claudeAiOauth", {})
            token = oauth.get("accessToken")
            if provider == ProviderName.CLAUDE and isinstance(token, str) and token:
                if (
                    isinstance(oauth.get("expiresAt"), (int, float))
                    and oauth["expiresAt"] <= time.time() * 1000
                ):
                    raise ProviderFailure("authentication_expired")
                return Credentials(
                    claude_auth={
                        "claudeAiOauth": {
                            key: oauth[key]
                            for key in (
                                "accessToken",
                                "refreshToken",
                                "expiresAt",
                                "scopes",
                                "subscriptionType",
                                "rateLimitTier",
                            )
                            if key in oauth
                        }
                    }
                )
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    raise ProviderFailure("authentication_unavailable")
