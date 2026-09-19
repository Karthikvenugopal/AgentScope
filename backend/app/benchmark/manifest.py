"""Generate the frozen, hash-addressed benchmark catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from app.evaluation.verifier import source_digest
from app.harness.task_catalog import TaskCatalog
from app.models.task import TaskSource


def task_content_hash(task_id: str, version: str, environment: str, verifier: str) -> str:
    value = json.dumps(
        [task_id, version, environment, verifier], separators=(",", ":")
    ).encode()
    return hashlib.sha256(value).hexdigest()


def freeze_manifest(benchmark_root: Path | str) -> dict[str, object]:
    root = Path(benchmark_root).resolve()
    # This command is the one explicit authoring boundary allowed to replace hashes.
    catalog = TaskCatalog(root, validate_hashes=False)
    entries: list[dict[str, object]] = []
    for task in catalog.list_tasks():
        repository = catalog.resolve_repository(task)
        verification = catalog.resolve_verification(task)
        environment_hash = source_digest(repository)
        verifier_hash = source_digest(verification)
        task_hash = (
            task.provenance.task_hash
            if task.provenance.source is TaskSource.HARBOR
            and task.provenance.task_hash is not None
            else task_content_hash(task.id, task.version, environment_hash, verifier_hash)
        )
        manifest_path = root / "tasks" / task.id / "task.yaml"
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        provenance = payload.setdefault("provenance", {})
        provenance.update(
            task_hash=task_hash,
            environment_hash=environment_hash,
            verifier_hash=verifier_hash,
        )
        manifest_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        entries.append(
            {
                "id": task.id,
                "version": task.version,
                "language": task.language,
                "difficulty": task.difficulty.value,
                "tags": list(task.tags),
                "source": task.provenance.source.value,
                "dataset": task.provenance.dataset,
                "dataset_version": task.provenance.dataset_version,
                "task_hash": task_hash,
                "environment_hash": environment_hash,
                "verifier_hash": verifier_hash,
            }
        )
    native = [entry for entry in entries if entry["source"] == "agentscope"]
    result: dict[str, object] = {
        "schema_version": "1",
        "benchmark": {"name": "AgentScope Benchmark", "version": "0.1", "frozen": True},
        "task_count": len(native),
        "tasks": native,
        "interoperability_tasks": [
            entry for entry in entries if entry["source"] != "agentscope"
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
