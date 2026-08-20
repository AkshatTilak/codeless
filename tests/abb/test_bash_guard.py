"""Tests for ABB bash mode guard intercepting write commands."""

from __future__ import annotations

from pathlib import Path
import pytest

from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.tools.bash_tool import BashTool, BashToolInput
from codeless.tools.base import ToolExecutionContext


@pytest.mark.asyncio
async def test_bash_guard_ask_mode_blocks_writes(tmp_path: Path):
    engine = get_mode_engine()
    engine.set_mode(TriMode.ASK)
    ctx = ToolExecutionContext(cwd=tmp_path)
    tool = BashTool()

    # Redirection write
    res = await tool.execute(BashToolInput(command="echo 'test' > file.txt"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output

    # File removal
    res = await tool.execute(BashToolInput(command="rm file.txt"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output

    # Package install
    res = await tool.execute(BashToolInput(command="npm install express"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output


@pytest.mark.asyncio
async def test_bash_guard_plan_mode_blocks_code_writes_allows_task_writes(tmp_path: Path):
    engine = get_mode_engine()
    engine.set_mode(TriMode.PLAN)
    ctx = ToolExecutionContext(cwd=tmp_path)
    tool = BashTool()

    # Code write blocked
    res = await tool.execute(BashToolInput(command="echo 'code' > src/main.py"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output

    # Read command allowed
    allowed, reason = pre_tool_use_abb_guard("bash", {"command": "git status"}, tmp_path)
    assert allowed


@pytest.mark.asyncio
async def test_bash_guard_agent_mode_allows_all(tmp_path: Path):
    engine = get_mode_engine()
    engine.set_mode(TriMode.AGENT)

    allowed, reason = pre_tool_use_abb_guard("bash", {"command": "echo 'ok' > file.txt"}, tmp_path)
    assert allowed
    assert reason == "OK"
