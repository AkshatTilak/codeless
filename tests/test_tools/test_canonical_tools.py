"""Tests for canonical multi-action tools (agent, task with sleep, abb, mcp, image)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from codeless.tools.abb_tool import AbbTool, AbbToolInput
from codeless.tools.agent_tool import AgentTool, AgentToolInput
from codeless.tools.base import ToolExecutionContext
from codeless.tools.image_tool import ImageTool, ImageToolInput
from codeless.tools.mcp_tool import McpTool, McpToolInput
from codeless.tools.task_tool import TaskTool, TaskToolInput


@pytest.mark.asyncio
async def test_task_tool_sleep(tmp_path: Path):
    tool = TaskTool()
    assert tool.is_read_only(TaskToolInput(action="sleep", seconds=0.05)) is True

    context = ToolExecutionContext(cwd=tmp_path)
    start = time.perf_counter()
    res = await tool.execute(TaskToolInput(action="sleep", seconds=0.05), context)
    elapsed = time.perf_counter() - start

    assert not res.is_error
    assert "Slept for 0.05 seconds" in res.output
    assert elapsed >= 0.04


@pytest.mark.asyncio
async def test_agent_tool_message_and_status(tmp_path: Path):
    tool = AgentTool()
    assert tool.is_read_only(AgentToolInput(action="status", task_id="t1")) is True
    assert (
        tool.is_read_only(AgentToolInput(action="message", task_id="t1", message="hello")) is False
    )

    context = ToolExecutionContext(cwd=tmp_path)
    # Message missing arguments
    res_err = await tool.execute(AgentToolInput(action="message"), context)
    assert res_err.is_error
    assert "requires both 'task_id' and 'message'" in res_err.output


@pytest.mark.asyncio
async def test_mcp_tool_actions(tmp_path: Path):
    manager = MagicMock()
    mock_resource = MagicMock()
    mock_resource.server_name = "test_server"
    mock_resource.uri = "resource://test"
    mock_resource.description = "Test Resource"
    manager.list_resources.return_value = [mock_resource]
    manager.read_resource = AsyncMock(return_value="Resource Content")

    tool = McpTool(manager)
    assert tool.is_read_only(McpToolInput(action="list")) is True
    assert tool.is_read_only(McpToolInput(action="read", server="s", uri="u")) is True
    assert (
        tool.is_read_only(McpToolInput(action="auth", server="s", mode="bearer", value="val"))
        is False
    )

    context = ToolExecutionContext(cwd=tmp_path)
    res_list = await tool.execute(McpToolInput(action="list"), context)
    assert not res_list.is_error
    assert "test_server:resource://test" in res_list.output

    res_read = await tool.execute(
        McpToolInput(action="read", server="test_server", uri="resource://test"), context
    )
    assert not res_read.is_error
    assert res_read.output == "Resource Content"


@pytest.mark.asyncio
async def test_image_tool_describe(tmp_path: Path):
    tool = ImageTool()
    assert tool.is_read_only(ImageToolInput(action="describe", image_data="base64")) is True
    assert tool.is_read_only(ImageToolInput(action="generate", prompt="Draw a cat")) is False

    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(ImageToolInput(action="describe", image_data="dGVzdA=="), context)
    assert not res.is_error
    assert "Visual inspection ready" in res.output


@pytest.mark.asyncio
async def test_abb_tool_dags_and_verify(tmp_path: Path):
    tool = AbbTool()
    assert tool.is_read_only(AbbToolInput(action="list")) is True
    assert tool.is_read_only(AbbToolInput(action="verify")) is True

    context = ToolExecutionContext(cwd=tmp_path)
    # When no ABB workspace is present
    res = await tool.execute(AbbToolInput(action="list"), context)
    assert res.is_error
    assert "No ABB workspace found" in res.output
