"""Tests for the unified FileTool (read, write, edit, notebook_edit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeless.tools.base import ToolExecutionContext
from codeless.tools.file_tool import FileTool, FileToolInput


@pytest.mark.asyncio
async def test_file_tool_read(tmp_path: Path):
    sample = tmp_path / "hello.txt"
    sample.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

    tool = FileTool()
    assert tool.is_read_only(FileToolInput(action="read", path=str(sample))) is True

    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(FileToolInput(action="read", path=str(sample)), context)
    assert not res.is_error
    assert "line 1" in res.output
    assert "line 2" in res.output


@pytest.mark.asyncio
async def test_file_tool_read_offset_and_limit(tmp_path: Path):
    sample = tmp_path / "multiline.txt"
    sample.write_text("\n".join(f"line {i}" for i in range(10)), encoding="utf-8")

    tool = FileTool()
    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(
        FileToolInput(action="read", path=str(sample), offset=2, limit=3), context
    )
    assert not res.is_error
    assert "line 2" in res.output
    assert "line 4" in res.output
    assert "line 0" not in res.output
    assert "line 6" not in res.output


@pytest.mark.asyncio
async def test_file_tool_read_missing_file(tmp_path: Path):
    tool = FileTool()
    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(FileToolInput(action="read", path="nonexistent.txt"), context)
    assert res.is_error
    assert "File not found" in res.output


@pytest.mark.asyncio
async def test_file_tool_write(tmp_path: Path):
    target = tmp_path / "subdir" / "output.txt"
    tool = FileTool()
    assert (
        tool.is_read_only(FileToolInput(action="write", path=str(target), content="Hello World"))
        is False
    )

    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(
        FileToolInput(action="write", path=str(target), content="Hello World"), context
    )
    assert not res.is_error
    assert "Wrote" in res.output
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "Hello World"


@pytest.mark.asyncio
async def test_file_tool_write_requires_content(tmp_path: Path):
    tool = FileTool()
    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(FileToolInput(action="write", path="test.txt"), context)
    assert res.is_error
    assert "requires 'content'" in res.output


@pytest.mark.asyncio
async def test_file_tool_edit(tmp_path: Path):
    target = tmp_path / "edit_me.txt"
    target.write_text("apple banana apple", encoding="utf-8")

    tool = FileTool()
    assert (
        tool.is_read_only(
            FileToolInput(action="edit", path=str(target), old_str="apple", new_str="orange")
        )
        is False
    )

    context = ToolExecutionContext(cwd=tmp_path)
    # Test single replace
    res = await tool.execute(
        FileToolInput(action="edit", path=str(target), old_str="apple", new_str="orange"), context
    )
    assert not res.is_error
    assert target.read_text(encoding="utf-8") == "orange banana apple"

    # Test replace all
    res_all = await tool.execute(
        FileToolInput(
            action="edit", path=str(target), old_str="apple", new_str="orange", replace_all=True
        ),
        context,
    )
    assert not res_all.is_error
    assert target.read_text(encoding="utf-8") == "orange banana orange"


@pytest.mark.asyncio
async def test_file_tool_edit_not_found(tmp_path: Path):
    target = tmp_path / "test.txt"
    target.write_text("sample content", encoding="utf-8")

    tool = FileTool()
    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(
        FileToolInput(action="edit", path=str(target), old_str="missing", new_str="replacement"),
        context,
    )
    assert res.is_error
    assert "old_str was not found" in res.output


@pytest.mark.asyncio
async def test_file_tool_notebook_edit(tmp_path: Path):
    nb_path = tmp_path / "test.ipynb"
    tool = FileTool()
    assert (
        tool.is_read_only(
            FileToolInput(action="notebook_edit", path=str(nb_path), new_source="print('hello')")
        )
        is False
    )

    context = ToolExecutionContext(cwd=tmp_path)
    res = await tool.execute(
        FileToolInput(
            action="notebook_edit",
            path=str(nb_path),
            cell_index=0,
            new_source="print('hello')",
            cell_type="code",
        ),
        context,
    )
    assert not res.is_error
    assert nb_path.exists()
    data = json.loads(nb_path.read_text(encoding="utf-8"))
    assert len(data["cells"]) == 1
    assert data["cells"][0]["source"] == "print('hello')"
