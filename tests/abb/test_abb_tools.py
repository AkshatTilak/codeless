"""Tests for read-only abb tool and agent mode filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.tools.abb_tool import AbbTool, AbbToolInput
from codeless.tools.agent_tool import AgentTool, AgentToolInput
from codeless.tools.base import ToolExecutionContext


@pytest.fixture
def sample_abb_workspace(tmp_path: Path):
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent\n", encoding="utf-8")
    (ws / "STACK.md").write_text(
        "---\nverification:\n  track_1: [\"python -c 'print(1)'\"]\n  track_2: []\n---\n# Stack\n",
        encoding="utf-8",
    )
    tasks_sub = ws / "tasks" / "sub"
    tasks_sub.mkdir(parents=True)
    (tasks_sub / "01_init.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: done\ndepends_on: []\n---\n# Init Subtask\n",
        encoding="utf-8",
    )
    (tasks_sub / "02_second.md").write_text(
        "---\nid: sub_002\nversion: 1.0.0\nstatus: not_started\ndepends_on: [sub_001]\n---\n# Second Subtask\n",
        encoding="utf-8",
    )
    (tasks_sub / "03_third.md").write_text(
        "---\nid: sub_003\nversion: 1.0.0\nstatus: not_started\ndepends_on: [sub_002]\n---\n# Third Subtask\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_abb_task_list(sample_abb_workspace: Path):
    tool = AbbTool()
    ctx = ToolExecutionContext(cwd=sample_abb_workspace)
    res = await tool.execute(AbbToolInput(action="list"), ctx)
    assert not res.is_error
    assert "sub_001" in res.output
    assert "sub_002" in res.output
    assert "sub_003" in res.output


@pytest.mark.asyncio
async def test_abb_task_show(sample_abb_workspace: Path):
    tool = AbbTool()
    ctx = ToolExecutionContext(cwd=sample_abb_workspace)
    res = await tool.execute(AbbToolInput(action="show", target="sub_001"), ctx)
    assert not res.is_error
    assert "# Init Subtask" in res.output


@pytest.mark.asyncio
async def test_abb_task_ready_and_blocked(sample_abb_workspace: Path):
    tool = AbbTool()
    ctx = ToolExecutionContext(cwd=sample_abb_workspace)
    # sub_002 depends on sub_001 (which is done), so sub_002 should be ready
    ready_res = await tool.execute(AbbToolInput(action="ready"), ctx)
    assert not ready_res.is_error
    assert "sub_002" in ready_res.output
    assert "sub_003" not in ready_res.output  # blocked by sub_002

    # sub_003 blocked-by sub_002
    blocked_res = await tool.execute(AbbToolInput(action="blocked-by", target="sub_003"), ctx)
    assert not blocked_res.is_error
    assert "sub_002" in blocked_res.output


@pytest.mark.asyncio
async def test_abb_verify_dry_run_and_execution(sample_abb_workspace: Path):
    tool = AbbTool()
    ctx = ToolExecutionContext(cwd=sample_abb_workspace)
    # dry run
    dry_res = await tool.execute(AbbToolInput(action="verify", dry_run=True), ctx)
    assert not dry_res.is_error
    assert "Two-Track Verification Manifest (Dry-Run Preview)" in dry_res.output
    assert "python -c 'print(1)'" in dry_res.output

    # live execution
    live_res = await tool.execute(AbbToolInput(action="verify", dry_run=False), ctx)
    assert not live_res.is_error
    assert "PASSED" in live_res.output


@pytest.mark.asyncio
async def test_agent_tool_mode_filtering(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    ctx = ToolExecutionContext(cwd=tmp_path)
    engine = get_mode_engine()

    # In PLAN mode: task-planner is allowed, worker is not
    engine.set_mode(TriMode.PLAN)
    planner_res = await AgentTool().execute(
        AgentToolInput(
            action="spawn",
            description="plan something",
            prompt="outline tasks",
            subagent_type="task-planner",
            command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
        ),
        ctx,
    )
    assert not planner_res.is_error

    worker_res = await AgentTool().execute(
        AgentToolInput(
            action="spawn",
            description="write code",
            prompt="implement feature",
            subagent_type="worker",
            command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
        ),
        ctx,
    )
    assert worker_res.is_error
    assert "cannot be spawned in active mode 'plan'" in worker_res.output
