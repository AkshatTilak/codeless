"""Tests for shadow path virtualization."""

import pytest

from codeless.abb.shadow import (
    resolve_abb_workspace,
)
from codeless.abb.virtualization import (
    is_abb_path,
    resolve_virtual_path,
    unvirtualize_path,
)
from codeless.tools.base import ToolExecutionContext
from codeless.tools.file_tool import FileTool, FileToolInput
from codeless.tools.glob_tool import GlobTool, GlobToolInput
from codeless.tools.grep_tool import GrepTool, GrepToolInput


def test_is_abb_path():
    # Top-level files
    assert is_abb_path("agent.md")
    assert is_abb_path("./agent.md")
    assert is_abb_path("STACK.md")
    assert is_abb_path("stack.md")
    assert is_abb_path("USER_PREFERENCES.md")
    assert is_abb_path("CONVENTIONS.md")
    assert is_abb_path("CODING_PHILOSOPHY.md")
    assert is_abb_path("VERSION")

    # Domain directories
    assert is_abb_path("tasks/goal/goal.md")
    assert is_abb_path("tasks/base/01_task.md")
    assert is_abb_path("tasks/sub/01_subtask.md")
    assert is_abb_path("workflows/router.md")
    assert is_abb_path("references/structure/topology.md")
    assert is_abb_path("design/system/architecture.md")
    assert is_abb_path("features/01_feature.md")
    assert is_abb_path("skills/qa/backend/SKILL.md")

    # Codebase paths (NOT ABB)
    assert not is_abb_path("src/codeless/cli.py")
    assert not is_abb_path("tests/test_cli.py")
    assert not is_abb_path("pyproject.toml")
    assert not is_abb_path("README.md")
    assert not is_abb_path("package.json")


def test_resolve_virtual_path_with_dev_override(tmp_path):
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    # With .codeless/abb_workspace in repo
    local_abb = project_root / ".codeless" / "abb_workspace"
    local_abb.mkdir(parents=True)
    (local_abb / "agent.md").write_text("# Local Agent\n", encoding="utf-8")

    resolved = resolve_virtual_path(project_root, "agent.md")
    assert resolved == local_abb / "agent.md"

    resolved_subtask = resolve_virtual_path(project_root, "tasks/sub/01.md")
    assert resolved_subtask == local_abb / "tasks" / "sub" / "01.md"


def test_resolve_virtual_path_shadow(tmp_path, monkeypatch):
    storage_root = tmp_path / ".codeless"
    monkeypatch.setattr("codeless.abb.shadow.get_global_codeless_dir", lambda: storage_root)

    project_root = tmp_path / "repo_without_local_abb"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    # Should resolve to shadow workspace
    resolved = resolve_virtual_path(project_root, "agent.md")
    assert "projects" in str(resolved)
    assert resolved.name == "agent.md"

    # Non-ABB paths must resolve to repo
    code_file = resolve_virtual_path(project_root, "src/main.py")
    assert code_file == project_root / "src" / "main.py"


@pytest.mark.asyncio
async def test_file_tools_virtualization_integration(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setattr("codeless.abb.shadow.get_global_codeless_dir", lambda: storage_root)

    project_root = tmp_path / "app"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    ctx = ToolExecutionContext(cwd=project_root)
    file_tool = FileTool()

    # 1. Read agent.md via FileTool
    res = await file_tool.execute(FileToolInput(action="read", path="agent.md"), ctx)
    assert not res.is_error
    assert "System Architect" in res.output

    # 2. Write a new subtask via FileTool (with valid frontmatter)
    valid_subtask = """---
id: sub_099
version: 1.0.0
status: pending
parent: base_001
depends_on: []
---
# Subtask 99
Body text
"""
    res = await file_tool.execute(
        FileToolInput(
            action="write",
            path="tasks/sub/99_test.md",
            content=valid_subtask,
        ),
        ctx,
    )
    assert not res.is_error
    # Must NOT pollute project_root/tasks
    assert not (project_root / "tasks").exists()

    # 3. Edit subtask via FileTool
    res = await file_tool.execute(
        FileToolInput(
            action="edit",
            path="tasks/sub/99_test.md",
            old_str="# Subtask 99",
            new_str="# Subtask 99 (Edited)",
        ),
        ctx,
    )
    assert not res.is_error

    # 4. Read back subtask
    res = await file_tool.execute(FileToolInput(action="read", path="tasks/sub/99_test.md"), ctx)
    assert not res.is_error
    assert "Subtask 99 (Edited)" in res.output

    # 5. Glob ABB tasks
    glob_tool = GlobTool()
    res = await glob_tool.execute(GlobToolInput(pattern="tasks/sub/*.md"), ctx)
    assert not res.is_error
    assert "99_test.md" in res.output

    # 6. Grep ABB tasks
    grep_tool = GrepTool()
    res = await grep_tool.execute(GrepToolInput(pattern="Subtask 99", root="tasks/sub"), ctx)
    assert not res.is_error
    assert "99_test.md" in res.output


def test_unvirtualize_path(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setattr("codeless.abb.shadow.get_global_codeless_dir", lambda: storage_root)

    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    abb_ws = resolve_abb_workspace(project_root)
    shadow_task = abb_ws / "tasks" / "goal" / "goal.md"

    unvirt = unvirtualize_path(shadow_task, project_root)
    assert unvirt == "tasks/goal/goal.md"

    code_file = project_root / "src" / "index.js"
    assert unvirtualize_path(code_file, project_root) == "src/index.js"
