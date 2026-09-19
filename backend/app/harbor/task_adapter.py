"""Read current Harbor task packages without depending on Harbor at runtime."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from app.evaluation.verifier import source_digest
from app.models.task import (
    RepositorySpec,
    Task,
    TaskDifficulty,
    TaskEnvironment,
    TaskProvenance,
    TaskSource,
    VerificationSpec,
)

SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "1.3", "1.4"}
_CANARY = re.compile(r"^(?:<!--.*canary.*-->|#.*canary.*)$", re.IGNORECASE)


class HarborImportError(ValueError):
    """A local package cannot be mapped without changing its semantics."""


def _strip_canary(text: str) -> str:
    lines = text.splitlines()
    while lines and (_CANARY.match(lines[0].strip()) or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def _safe_id(source_id: str) -> str:
    value = source_id.lower().replace("/", ".")
    value = re.sub(r"[^a-z0-9._-]+", "-", value).strip("._-")
    if not value or len(value) > 80:
        raise HarborImportError(f"Harbor task id cannot be normalized safely: {source_id!r}")
    return value


def _hash_tree(path: Path) -> str:
    return source_digest(path)


class HarborTaskAdapter:
    """Map a Harbor 0.23 task directory onto AgentScope's task abstraction.

    The original package is never modified. ``materialize_repository`` copies only
    environment build-context files and explicitly excludes the Dockerfile itself.
    """

    def __init__(
        self,
        task_dir: Path | str,
        *,
        dataset: str,
        dataset_version: str,
        imported_at: str | None = None,
        harbor_version: str = "0.23.0",
        agentscope_commit: str | None = None,
    ) -> None:
        self.task_dir = Path(task_dir).expanduser().resolve()
        self.dataset = dataset
        self.dataset_version = dataset_version
        self.imported_at = imported_at or datetime.now(UTC).isoformat()
        self.harbor_version = harbor_version
        self.agentscope_commit = agentscope_commit

    def load(self, *, repository_source: str, verification_source: str) -> Task:
        raw = self._read_config()
        instruction_path = self.task_dir / "instruction.md"
        environment_dir = self.task_dir / "environment"
        tests_dir = self.task_dir / "tests"
        if not instruction_path.is_file():
            raise HarborImportError("Harbor task is missing instruction.md")
        if not environment_dir.is_dir():
            raise HarborImportError("Harbor task is missing environment/")
        if not tests_dir.is_dir() or not any(tests_dir.iterdir()):
            raise HarborImportError("Harbor task is missing verifier material in tests/")

        package = raw.get("task") or {}
        metadata = raw.get("metadata") or {}
        environment = raw.get("environment") or {}
        verifier = raw.get("verifier") or {}
        source_id = str(package.get("name") or self.task_dir.name)
        schema_version = str(raw.get("schema_version", raw.get("version", "1.0")))
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise HarborImportError(
                f"unsupported Harbor task schema {schema_version!r}; supported: "
                + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
            )
        image = environment.get("docker_image")
        if image is not None and not isinstance(image, str):
            raise HarborImportError("[environment].docker_image must be a string")
        dockerfile = environment_dir / "Dockerfile"
        if not image and not dockerfile.is_file():
            raise HarborImportError("Harbor environment needs docker_image or Dockerfile")
        difficulty = str(metadata.get("difficulty", "medium")).lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        tags = metadata.get("tags") or package.get("keywords") or []
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise HarborImportError("Harbor tags must be a string array")
        language = self._language(tags, instruction_path.read_text(encoding="utf-8"))
        workdir = self._docker_workdir(dockerfile) if dockerfile.is_file() else "/app"
        instruction = _strip_canary(instruction_path.read_text(encoding="utf-8"))
        portable_instruction = instruction.replace(workdir, "/workspace")
        task_hash = _hash_tree(self.task_dir)
        return Task(
            id=_safe_id(source_id),
            title=str(package.get("description") or source_id).strip(),
            description=portable_instruction
            + "\n\nAgentScope path mapping: Harbor's "
            + f"{workdir} is the agent-visible /workspace directory.",
            repository=RepositorySpec(source=repository_source),
            test_command=self._visible_test_command(language),
            timeout_seconds=min(int((raw.get("agent") or {}).get("timeout_sec", 600)), 86_400),
            expected_behavior=str(package.get("description") or instruction).strip(),
            version=str(package.get("version") or schema_version),
            tags=tuple(dict.fromkeys([*tags, "harbor", self.dataset])),
            language=language,
            difficulty=TaskDifficulty(difficulty),
            provenance=TaskProvenance(
                source=TaskSource.HARBOR,
                dataset=self.dataset,
                dataset_version=self.dataset_version,
                source_task_id=source_id,
                source_version=str(package.get("version") or self.dataset_version),
                task_hash=task_hash,
                environment_hash=_hash_tree(environment_dir),
                verifier_hash=_hash_tree(tests_dir),
                imported_at=self.imported_at,
                agentscope_commit=self.agentscope_commit,
                harbor_version=self.harbor_version,
                harbor_schema_version=schema_version,
                source_metadata=metadata,
            ),
            environment=TaskEnvironment(
                kind="harbor",
                image=image,
                workdir=workdir,
                build_timeout_seconds=float(environment.get("build_timeout_sec", 600)),
                network_mode=cast(
                    "Literal['no-network', 'public', 'allowlist']",
                    self._network_mode(environment),
                ),
            ),
            verification=VerificationSpec(
                source=verification_source,
                timeout_seconds=float(verifier.get("timeout_sec", 600)),
                kind="harbor",
                command=self._test_script(tests_dir),
            ),
        )

    def materialize_repository(self, target: Path | str) -> Path:
        target_path = Path(target)
        if target_path.exists():
            raise HarborImportError(f"target already exists: {target_path}")
        target_path.mkdir(parents=True)
        environment = self.task_dir / "environment"
        for source in sorted(environment.rglob("*")):
            relative = source.relative_to(environment)
            if source.is_symlink():
                raise HarborImportError("Harbor environment must not contain symlinks")
            if relative == Path("Dockerfile"):
                continue
            destination = target_path / relative
            if source.is_dir():
                destination.mkdir(exist_ok=True)
            elif source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        marker = {
            "source_task": self.task_dir.name,
            "dataset": self.dataset,
            "dataset_version": self.dataset_version,
        }
        (target_path / ".agentscope-harbor.json").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target_path

    def import_to_catalog(self, benchmark_root: Path | str) -> Task:
        """Copy the immutable package and generate an AgentScope catalog entry."""
        root = Path(benchmark_root).expanduser().resolve()
        raw = self._read_config()
        package = raw.get("task") or {}
        source_id = str(package.get("name") or self.task_dir.name)
        task_id = _safe_id(source_id)
        dataset_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", self.dataset).strip("-")
        package_target = root / "harbor" / dataset_slug / self.task_dir.name
        repository_target = root / "fixtures" / task_id
        manifest_target = root / "tasks" / task_id / "task.yaml"
        for target in (package_target, repository_target, manifest_target.parent):
            if target.exists():
                raise HarborImportError(f"catalog target already exists: {target}")
        package_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.task_dir, package_target)
        self.materialize_repository(repository_target)
        repository_source = repository_target.relative_to(root).as_posix()
        verification_source = (package_target / "tests").relative_to(root).as_posix()
        imported = HarborTaskAdapter(
            package_target,
            dataset=self.dataset,
            dataset_version=self.dataset_version,
            imported_at=self.imported_at,
            harbor_version=self.harbor_version,
            agentscope_commit=self.agentscope_commit,
        ).load(
            repository_source=repository_source,
            verification_source=verification_source,
        )
        manifest_target.parent.mkdir(parents=True)
        import yaml

        manifest_target.write_text(
            yaml.safe_dump(
                imported.model_dump(mode="json", exclude_none=True),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        return imported

    def _read_config(self) -> dict[str, Any]:
        path = self.task_dir / "task.toml"
        if not path.is_file():
            raise HarborImportError("Harbor task is missing task.toml")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise HarborImportError(f"invalid Harbor task.toml: {exc}") from exc
        if not isinstance(raw, dict):
            raise HarborImportError("Harbor task.toml must contain a mapping")
        return raw

    @staticmethod
    def _docker_workdir(path: Path) -> str:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("WORKDIR "):
                return line.strip().split(maxsplit=1)[1]
        return "/app"

    @staticmethod
    def _network_mode(environment: dict[str, Any]) -> str:
        if "network_mode" in environment:
            return str(environment["network_mode"])
        return "public" if environment.get("allow_internet", True) else "no-network"

    @staticmethod
    def _language(tags: list[str], instruction: str) -> str:
        joined = " ".join(tags).lower() + " " + instruction.lower()
        if any(token in joined for token in ("typescript", "javascript", "node", "html")):
            return "TypeScript/JavaScript"
        if any(token in joined for token in ("c++", "cpp", "g++")):
            return "C++"
        if "java" in joined and "javascript" not in joined:
            return "Java"
        if "sql" in joined:
            return "SQL"
        return "Python"

    @staticmethod
    def _visible_test_command(language: str) -> str:
        if language == "TypeScript/JavaScript":
            return "node --test"
        return "python -m pytest -q"

    @staticmethod
    def _test_script(tests_dir: Path) -> str:
        for name in ("test.sh", "test.ps1", "test.cmd", "test.bat"):
            if (tests_dir / name).is_file():
                return name
        raise HarborImportError("Harbor task has no supported verifier entrypoint")
