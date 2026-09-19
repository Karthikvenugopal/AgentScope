from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.execution.workspace import LocalWorkspace, WorkspaceError


async def test_local_workspace_copies_source_without_mutating_it(
    source_repository: Path,
) -> None:
    workspace = await LocalWorkspace.create(source_repository, run_id="copy-test")
    try:
        await workspace.write_text("app.py", "VALUE = 'after'\n")

        assert await workspace.read_text("app.py") == "VALUE = 'after'\n"
        assert (source_repository / "app.py").read_text() == "VALUE = 'before'\n"
    finally:
        await workspace.close()


async def test_workspace_creates_missing_parent_directories(source_repository: Path) -> None:
    async with await LocalWorkspace.create(source_repository) as workspace:
        await workspace.write_text("new/deep/file.txt", "created")

        assert await workspace.read_text("new/deep/file.txt") == "created"


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt"])
async def test_workspace_rejects_paths_outside_root(source_repository: Path, path: str) -> None:
    async with await LocalWorkspace.create(source_repository) as workspace:
        with pytest.raises(ValueError, match="workspace path"):
            await workspace.write_text(path, "unsafe")


async def test_workspace_rejects_symlink_escape(source_repository: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = await LocalWorkspace.create(source_repository)
    try:
        (workspace.host_path / "link").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="escapes root"):
            await workspace.write_text("link/escaped.txt", "unsafe")
    finally:
        await workspace.close()


async def test_workspace_enforces_read_size_limit(source_repository: Path) -> None:
    async with await LocalWorkspace.create(source_repository) as workspace:
        with pytest.raises(WorkspaceError, match="read limit"):
            await workspace.read_text("app.py", max_bytes=2)


async def test_local_execute_captures_process_output(source_repository: Path) -> None:
    async with await LocalWorkspace.create(source_repository) as workspace:
        result = await workspace.execute(
            (sys.executable, "-c", "print('workspace-ok')"), timeout_seconds=5
        )

        assert result.return_code == 0
        assert result.stdout.strip() == "workspace-ok"
        assert result.timed_out is False
        assert result.duration_ms >= 0


async def test_local_execute_returns_structured_timeout(source_repository: Path) -> None:
    async with await LocalWorkspace.create(source_repository) as workspace:
        result = await workspace.execute(
            (sys.executable, "-c", "import time; time.sleep(2)"),
            timeout_seconds=0.01,
        )

        assert result.timed_out is True
        assert result.return_code != 0


async def test_close_removes_workspace_and_is_idempotent(source_repository: Path) -> None:
    workspace = await LocalWorkspace.create(source_repository)
    sandbox = workspace.host_path.parent

    await workspace.close()
    await workspace.close()

    assert not sandbox.exists()
    with pytest.raises(WorkspaceError, match="closed"):
        await workspace.read_text("app.py")


async def test_keep_workspace_preserves_files(source_repository: Path) -> None:
    workspace = await LocalWorkspace.create(
        source_repository,
        workspace_base=source_repository.parent,
        keep_workspace=True,
    )
    sandbox = workspace.host_path.parent

    await workspace.close()

    assert sandbox.exists()


async def test_invalid_run_id_is_rejected(source_repository: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        await LocalWorkspace.create(source_repository, run_id="bad/id")


async def test_generated_run_ids_are_unique(source_repository: Path) -> None:
    first = await LocalWorkspace.create(source_repository)
    second = await LocalWorkspace.create(source_repository)
    try:
        assert first.run_id != second.run_id
        assert first.host_path != second.host_path
    finally:
        await first.close()
        await second.close()
