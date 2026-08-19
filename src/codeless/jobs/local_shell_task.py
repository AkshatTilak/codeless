"""Local shell task facade."""

from __future__ import annotations

from pathlib import Path

from codeless.jobs.manager import get_task_manager
from codeless.jobs.types import TaskRecord


async def spawn_shell_task(command: str, description: str, cwd: str | Path) -> TaskRecord:
    """Spawn a local shell task."""
    return await get_task_manager().create_shell_task(
        command=command,
        description=description,
        cwd=cwd,
    )
