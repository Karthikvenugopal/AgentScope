from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.execution import DockerWorkspace

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AGENTSCOPE_RUN_DOCKER_TESTS") != "1",
        reason="set AGENTSCOPE_RUN_DOCKER_TESTS=1 after building the runner image",
    ),
]


async def test_real_docker_workspace_lifecycle(source_repository: Path) -> None:
    workspace = await DockerWorkspace.create(source_repository)
    sandbox = workspace.host_path.parent
    try:
        result = await workspace.execute(("python", "--version"), timeout_seconds=10)
        await workspace.write_text("container-visible.txt", "visible\n")
        visible = await workspace.execute(
            ("python", "-c", "print(open('container-visible.txt').read().strip())"),
            timeout_seconds=10,
        )

        assert result.return_code == 0
        assert "Python 3.12" in (result.stdout + result.stderr)
        assert visible.stdout.strip() == "visible"
    finally:
        await workspace.close()

    assert not sandbox.exists()
