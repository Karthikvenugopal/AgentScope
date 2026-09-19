"""Small API helper used by the benchmark fixture."""


def status_response() -> dict[str, str]:
    """Return the public status payload promised by the API contract."""

    return {"status": "ok"}
