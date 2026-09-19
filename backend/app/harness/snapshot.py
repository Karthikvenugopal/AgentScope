"""Harness-owned repository baseline and deterministic Git-style patches."""

from __future__ import annotations

import asyncio
import difflib
from pathlib import Path

from app.execution.workspace import Workspace

_IGNORED_PARTS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}


class RepositorySnapshot:
    """Capture source bytes outside the agent-visible container mount."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    @classmethod
    async def capture(cls, workspace: Workspace) -> RepositorySnapshot:
        return cls(await asyncio.to_thread(_read_tree, workspace.host_path))

    async def diff(self, workspace: Workspace) -> tuple[str, tuple[str, ...]]:
        current = await asyncio.to_thread(_read_tree, workspace.host_path)
        changed = tuple(
            sorted(
                path
                for path in self._files.keys() | current.keys()
                if self._files.get(path) != current.get(path)
            )
        )
        patch = await asyncio.to_thread(_build_patch, self._files, current, changed)
        return patch, changed


def _read_tree(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (
            _IGNORED_PARTS.intersection(relative.parts)
            or path.suffix in {".pyc", ".pyo"}
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


def _build_patch(
    before: dict[str, bytes],
    after: dict[str, bytes],
    changed: tuple[str, ...],
) -> str:
    sections: list[str] = []
    for path in changed:
        old = before.get(path)
        new = after.get(path)
        old_name = f"a/{path}" if old is not None else "/dev/null"
        new_name = f"b/{path}" if new is not None else "/dev/null"
        header = f"diff --git a/{path} b/{path}\n"
        if _is_binary(old) or _is_binary(new):
            sections.append(header + f"Binary files {old_name} and {new_name} differ\n")
            continue
        old_lines = old.decode("utf-8").splitlines(keepends=True) if old is not None else []
        new_lines = new.decode("utf-8").splitlines(keepends=True) if new is not None else []
        unified = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
            lineterm="\n",
        )
        sections.append(header + "".join(unified))
    return "".join(sections)


def _is_binary(content: bytes | None) -> bool:
    if content is None:
        return False
    if b"\x00" in content:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False
