"""Harness-only contract tests, installed after the candidate has been frozen."""

import importlib.util
from pathlib import Path


def load_candidate():
    path = Path(__file__).resolve().parents[1] / "candidate" / "app.py"
    spec = importlib.util.spec_from_file_location("candidate_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_public_payload():
    assert load_candidate().status_response() == {"status": "ok"}


def test_legacy_fields_absent():
    response = load_candidate().status_response()
    assert "state" not in response
    assert response.get("status") == "ok"


def test_calls_return_independent_payloads():
    app = load_candidate()
    first = app.status_response()
    first["status"] = "changed"
    assert app.status_response() == {"status": "ok"}
