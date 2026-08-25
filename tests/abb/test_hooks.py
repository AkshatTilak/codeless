"""Tests for ABB Lifecycle Hooks, Frontmatter Validator, DAG Guard, and Rollup."""

from pathlib import Path

import pytest

from codeless.abb.hooks.dag_guard import check_dag_dependencies
from codeless.abb.hooks.frontmatter import (
    parse_frontmatter,
    validate_task_frontmatter,
)
from codeless.abb.hooks.rollup import rollup_task_completion
from codeless.tools.base import ToolExecutionContext
from codeless.tools.file_tool import FileTool, FileToolInput


def test_frontmatter_parser():
    content = """---
id: sub_001
version: 1.0.0
status: pending
parent: base_001
depends_on: []
---

# Subtask Title
Some body text.
"""
    fm, body = parse_frontmatter(content)
    assert fm["id"] == "sub_001"
    assert fm["version"] == "1.0.0"
    assert fm["status"] == "pending"
    assert "Subtask Title" in body


def test_frontmatter_validator():
    # Valid
    valid_data = {
        "id": "sub_001",
        "version": "1.0.0",
        "status": "pending",
        "parent": "base_001",
        "depends_on": [],
    }
    assert validate_task_frontmatter(valid_data, Path("tasks/sub/01.md")) == []

    # Missing fields
    errors = validate_task_frontmatter({}, Path("tasks/sub/01.md"))
    assert len(errors) > 0

    # Invalid status
    invalid_status = dict(valid_data, status="unknown_status")
    errors = validate_task_frontmatter(invalid_status, Path("tasks/sub/01.md"))
    assert any("Invalid status" in e for e in errors)

    # Invalid semver
    invalid_ver = dict(valid_data, version="v1-final")
    errors = validate_task_frontmatter(invalid_ver, Path("tasks/sub/01.md"))
    assert any("semantic versioning" in e for e in errors)

    # Subtask missing parent
    missing_parent = dict(valid_data)
    del missing_parent["parent"]
    errors = validate_task_frontmatter(missing_parent, Path("tasks/sub/01.md"))
    assert any("parent" in e for e in errors)


def test_dag_dependency_guard(tmp_path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "sub").mkdir(parents=True)
    (tasks_dir / "base").mkdir(parents=True)

    # Create dep1: pending
    dep1 = tasks_dir / "sub" / "01_dep.md"
    dep1.write_text(
        """---
id: sub_001
version: 1.0.0
status: pending
parent: base_001
depends_on: []
---
# Dep 1
""",
        encoding="utf-8",
    )

    # Check task2 depending on dep1 when transitioning to in_progress
    allowed, reason = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert not allowed
    assert "Unsatisfied dependencies" in reason
    assert "sub_001" in reason

    # Mark dep1 as done
    dep1.write_text(
        """---
id: sub_001
version: 1.0.0
status: done
parent: base_001
depends_on: []
---
# Dep 1
""",
        encoding="utf-8",
    )

    # Now task2 should be allowed
    allowed, reason = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert allowed


def test_auto_rollup(tmp_path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "sub").mkdir(parents=True)
    (tasks_dir / "base").mkdir(parents=True)
    (tasks_dir / "goal").mkdir(parents=True)

    # Base task
    base_file = tasks_dir / "base" / "01_base.md"
    base_file.write_text(
        """---
id: base_001
version: 1.0.0
status: in_progress
depends_on: []
---
# Base 1
## Subtask Registry
- [ ] `sub/01_sub.md`
- [ ] `sub/02_sub.md`
""",
        encoding="utf-8",
    )

    # Goal
    goal_file = tasks_dir / "goal" / "goal.md"
    goal_file.write_text(
        """---
id: goal_001
version: 1.0.0
status: in_progress
depends_on: []
---
# Goal
## Base Task Registry
- [ ] `base/01_base.md`
""",
        encoding="utf-8",
    )

    # Subtask 1 done
    sub1 = tasks_dir / "sub" / "01_sub.md"
    sub1.write_text(
        """---
id: sub_001
version: 1.0.0
status: done
parent: base_001
depends_on: []
---
# Sub 1
""",
        encoding="utf-8",
    )

    # Subtask 2 not done
    sub2 = tasks_dir / "sub" / "02_sub.md"
    sub2.write_text(
        """---
id: sub_002
version: 1.0.0
status: in_progress
parent: base_001
depends_on: []
---
# Sub 2
""",
        encoding="utf-8",
    )

    # Trigger rollup for sub1
    actions = rollup_task_completion(sub1, tasks_dir)
    assert any("Checked off `01_sub.md`" in a for a in actions)

    # Base task should still be in_progress because sub2 is not done
    base_fm, _ = parse_frontmatter(base_file.read_text(encoding="utf-8"))
    assert base_fm["status"] == "in_progress"

    # Now mark sub2 as done
    sub2.write_text(
        """---
id: sub_002
version: 1.0.0
status: done
parent: base_001
depends_on: []
---
# Sub 2
""",
        encoding="utf-8",
    )

    actions = rollup_task_completion(sub2, tasks_dir)
    assert any("Marked base task" in a for a in actions)

    # Base task should now be done
    base_fm, _ = parse_frontmatter(base_file.read_text(encoding="utf-8"))
    assert base_fm["status"] == "done"

    # Goal should now be done
    goal_fm, _ = parse_frontmatter(goal_file.read_text(encoding="utf-8"))
    assert goal_fm["status"] == "done"


@pytest.mark.asyncio
async def test_tool_hook_integration(tmp_path, monkeypatch):
    storage_root = tmp_path / ".codeless"
    monkeypatch.setattr("codeless.abb.shadow.get_global_codeless_dir", lambda: storage_root)

    project_root = tmp_path / "my_app"
    project_root.mkdir()
    (project_root / ".git").mkdir()

    ctx = ToolExecutionContext(cwd=project_root)
    file_tool = FileTool()

    # 1. Attempt writing task with invalid frontmatter (missing id/version)
    bad_task = """---
status: pending
---
# Missing ID
"""
    res = await file_tool.execute(
        FileToolInput(action="write", path="tasks/sub/bad_task.md", content=bad_task),
        ctx,
    )
    assert res.is_error
    assert "Frontmatter Validation Failed" in res.output

    # 2. Attempt setting task to in_progress with missing dependency
    dep_blocked_task = """---
id: sub_999
version: 1.0.0
status: in_progress
parent: base_001
depends_on:
  - sub_nonexistent
---
# Blocked
"""
    res = await file_tool.execute(
        FileToolInput(action="write", path="tasks/sub/999_blocked.md", content=dep_blocked_task),
        ctx,
    )
    assert res.is_error
    assert "DAG Dependency Blocked" in res.output
