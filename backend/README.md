# AgentScope backend

This package contains the Python 3.12 backend for AgentScope, a coding-agent
harness and inference benchmarking platform. Phase 4 adds a typed FastAPI service
with bounded PostgreSQL-backed run management, isolated single/staged/parallel
strategies, independent verification, deterministic metrics, Harbor-compatible
tasks, resumable experiments, migrations, and artifact integrity.
Start with `uvicorn app.main:create_app --factory --workers 1` after applying
Alembic migrations; see the repository research report and phase documentation.
See the repository-level README for setup and architecture documentation.
