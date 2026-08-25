"""Tests for task and agent tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codeless.jobs import get_task_manager
from codeless.tools.agent_tool import AgentTool, AgentToolInput
from codeless.tools.base import ToolExecutionContext
from codeless.tools.task_tool import TaskTool, TaskToolInput


async def _wait_for_terminal_task(task_id: str, *, timeout_seconds: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    manager = get_task_manager()
    while asyncio.get_running_loop().time() < deadline:
        task = manager.get_task(task_id)
        if task is not None and task.status in {"completed", "failed", "killed"}:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not reach a terminal status in time")


@pytest.mark.asyncio
async def test_job_update_tool_updates_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    create_result = await TaskTool().execute(
        TaskToolInput(
            action="create",
            type="local_bash",
            description="updatable",
            command="printf 'tool task'",
        ),
        context,
    )
    task_id = create_result.output.split()[2]

    update_result = await TaskTool().execute(
        TaskToolInput(
            action="update",
            task_id=task_id,
            description="renamed task",
        ),
        context,
    )
    assert update_result.is_error is False

    task = get_task_manager().get_task(task_id)
    assert task is not None
    assert task.description == "renamed task"


@pytest.mark.asyncio
async def test_agent_tool_uses_subprocess_backend_and_task_is_pollable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    result = await AgentTool().execute(
        AgentToolInput(
            action="spawn",
            description="backend regression check",
            prompt="hello",
            subagent_type="test-worker",
            command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
        ),
        context,
    )

    assert not result.is_error, f"AgentTool failed: {result.output}"
    assert "backend=subprocess" in result.output
    assert "in_process_" not in result.output

    import re

    m = re.search(r"task_id=(\S+?)[,)]", result.output)
    assert m, f"Could not parse task_id from output: {result.output}"
    task_id = m.group(1)

    manager = get_task_manager()
    record = manager.get_task(task_id)
    assert record is not None
    assert record.command == 'python -u -c "import sys; print(sys.stdin.readline().strip())"'
    assert record.type == "local_agent"
    await _wait_for_terminal_task(task_id)


@pytest.mark.asyncio
async def test_agent_message_swarm_path_uses_subprocess_backend(tmp_path: Path, monkeypatch):
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    from codeless.swarm.registry import get_backend_registry

    executor = get_backend_registry().get_executor("subprocess")
    with patch.object(
        executor,
        "send_message",
        new_callable=AsyncMock,
    ) as mock_send:
        await AgentTool().execute(
            AgentToolInput(
                action="message",
                task_id="worker@default",
                message="ping",
            ),
            context,
        )

    mock_send.assert_called_once()
    agent_id_arg = mock_send.call_args[0][0]
    assert agent_id_arg == "worker@default"


@pytest.mark.asyncio
async def test_agent_tool_supports_remote_and_teammate_modes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    for i, mode in enumerate(("remote_agent", "in_process_teammate")):
        result = await AgentTool().execute(
            AgentToolInput(
                action="spawn",
                description=f"{mode} smoke",
                prompt="ready",
                mode=mode,
                subagent_type=f"test-worker-{i}",
                command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
            ),
            context,
        )
        assert result.is_error is False
        import re

        match = re.search(r"task_id=(\S+?)[,)]", result.output)
        assert match, result.output
        task_id = match.group(1)
        record = get_task_manager().get_task(task_id)
        assert record is not None
        assert record.type == mode
        await _wait_for_terminal_task(task_id)
