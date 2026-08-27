"""Tests for glob, grep, and file tool output disambiguation."""

from pathlib import Path

import pytest

from codeless.tools.base import ToolExecutionContext
from codeless.tools.file_tool import FileTool, FileToolInput
from codeless.tools.glob_tool import GlobTool, GlobToolInput


@pytest.mark.asyncio
async def test_glob_tool_abb_origin_markers(tmp_path: Path):
    """Glob tool should prefix ABB workspace matches with [abb]."""
    proj_root = tmp_path / "project"
    proj_root.mkdir()
    (proj_root / ".git").mkdir()

    # Create a codebase file
    (proj_root / "src").mkdir()
    (proj_root / "src" / "app.py").write_text("# App\n", encoding="utf-8")

    # Create an ABB workspace with tasks
    abb_ws = proj_root / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# Agent\n", encoding="utf-8")
    (abb_ws / "tasks").mkdir()
    (abb_ws / "tasks" / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    tool = GlobTool()
    context = ToolExecutionContext(cwd=proj_root)

    # Search for all markdown files
    res = await tool.execute(GlobToolInput(pattern="**/*.md"), context)
    assert not res.is_error
    assert "[abb]" in res.output
    assert (
        "[abb] agent.md" in res.output
        or "[abb] tasks/tasks.md" in res.output
        or "[abb] tasks\\tasks.md" in res.output
    )


@pytest.mark.asyncio
async def test_file_tool_read_header(tmp_path: Path):
    """File tool read output should contain # File: <path> header."""
    sample = tmp_path / "sample.txt"
    sample.write_text("hello world\n", encoding="utf-8")

    tool = FileTool()
    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(FileToolInput(action="read", path=str(sample)), context)
    assert not res.is_error
    assert res.output.startswith(f"# File: {sample.resolve()}")
    assert "hello world" in res.output
