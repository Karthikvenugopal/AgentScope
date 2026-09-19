"""Tiny service used by the AgentScope Phase 1 benchmark."""


def status_response() -> dict[str, str]:
    """Return the public health-check payload."""
    return {"state": "healthy"}

