"""Phase 1 E2E Verification & Self-Hosting Test Suite (sub_015 / plan §14.2).

Validates all 6 core Phase 1 requirements:
1. Shadow workspace auto-init and path virtualization.
2. /init command initialization of project governance.
3. DAG dependency gating and blocked state enforcement.
4. Two-track verification gating on subtask completion.
5. Automatic base task rollup when all subtasks finish.
6. Tri-mode permissions and slash command execution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeless.abb.commands import (
    _init_handler,
)
from codeless.abb.dry_run import audit_abb_readiness
from codeless.abb.hooks.dag_guard import check_dag_dependencies
from codeless.abb.hooks.rollup import rollup_task_completion
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.abb.shadow import (
    resolve_abb_workspace,
)
from codeless.abb.verification import (
    verify_subtask_gate,
)
from codeless.abb.virtualization import resolve_virtual_path
from codeless.commands.registry import CommandContext


@pytest.mark.asyncio
async def test_e2e_step1_shadow_workspace_auto_init(tmp_path: Path):
    """Step 1: Launch on a sample repo -> assert shadow auto-init and template presence."""
    project_root = tmp_path / "sample_project"
    project_root.mkdir()
    (project_root / "sample.py").write_text("print('hello')", encoding="utf-8")

    ws = resolve_abb_workspace(project_root, auto_init=True)
    assert ws.exists()
    assert (ws / "agent.md").exists()
    assert (ws / "VERSION").exists()

    # Path virtualization
    resolved = resolve_virtual_path(project_root, "agent.md")
    assert resolved == ws / "agent.md"


@pytest.mark.asyncio
async def test_e2e_step2_init_command_creates_governance(tmp_path: Path):
    """Step 2: /init initializes project memory, CLAUDE.md, and ABB structure."""
    from unittest.mock import MagicMock

    ctx = CommandContext(engine=MagicMock(), cwd=str(tmp_path))
    res = await _init_handler(args="", context=ctx)
    assert "Initialized project" in res.message or "Project already initialized" in res.message
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".codeless" / "memory" / "MEMORY.md").exists()


def test_e2e_step3_dag_dependency_gating(tmp_path: Path):
    """Step 3: DAG blocking — subtask 02 blocked if dependency subtask 01 is pending."""
    tasks_dir = tmp_path / "tasks"
    base_dir = tasks_dir / "base"
    sub_dir = tasks_dir / "sub"
    base_dir.mkdir(parents=True)
    sub_dir.mkdir(parents=True)

    (base_dir / "01_core.md").write_text(
        "---\nid: base_001\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: pending\ndepends_on: []\nlinks: []\n---\n# Base 1\n",
        encoding="utf-8",
    )
    (sub_dir / "01_sub.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: pending\nparent: base_001\ndepends_on: []\nlinks: []\n---\n# Sub 1\n",
        encoding="utf-8",
    )
    (sub_dir / "02_sub.md").write_text(
        "---\nid: sub_002\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: pending\nparent: base_001\ndepends_on: [sub_001]\nlinks: []\n---\n# Sub 2\n",
        encoding="utf-8",
    )

    # Validate sub_002 cannot transition to in_progress because sub_001 is pending
    allowed, reason = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert not allowed
    assert "sub_001" in reason

    # Once sub_001 is marked done, sub_002 can transition to in_progress
    (sub_dir / "01_sub.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: done\nparent: base_001\ndepends_on: []\nlinks: []\n---\n# Sub 1\n",
        encoding="utf-8",
    )
    allowed_resolved, _ = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert allowed_resolved


def test_e2e_step4_two_track_verification_gate(tmp_path: Path):
    """Step 4: Subtask completion gate blocks on failing tests and passes on green tests."""
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent\n", encoding="utf-8")

    # 1. Failing manifest
    (ws / "STACK.md").write_text(
        '---\nverification:\n  track_1:\n    - python -c "import sys; sys.exit(1)"\n---\n# STACK\n',
        encoding="utf-8",
    )
    subtask_path = ws / "sub_001.md"
    subtask_path.write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: in_progress\nparent: base_001\ndepends_on: []\n---\n# Sub 1\n",
        encoding="utf-8",
    )

    allowed, reason, report = verify_subtask_gate("sub_001", tmp_path, ws)
    assert not allowed
    assert "Verification Failed" in reason or "failed" in reason.lower()

    # 2. Passing manifest
    (ws / "STACK.md").write_text(
        '---\nverification:\n  track_1:\n    - python -c "import sys; sys.exit(0)"\n---\n# STACK\n',
        encoding="utf-8",
    )
    allowed_green, reason_green, report_green = verify_subtask_gate("sub_001", tmp_path, ws)
    assert allowed_green
    assert "passed" in reason_green


def test_e2e_step5_auto_rollup_hierarchy(tmp_path: Path):
    """Step 5: When all sibling subtasks are done, the parent base task automatically rolls up to done."""
    tasks_dir = tmp_path / "tasks"
    base_dir = tasks_dir / "base"
    sub_dir = tasks_dir / "sub"
    base_dir.mkdir(parents=True)
    sub_dir.mkdir(parents=True)

    base_file = base_dir / "01_core.md"
    base_file.write_text(
        "---\nid: base_001\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: in_progress\ndepends_on: []\nlinks: []\n---\n# Base 1\n",
        encoding="utf-8",
    )
    (sub_dir / "01_sub.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: done\nparent: base_001\ndepends_on: []\nlinks: []\n---\n# Sub 1\n",
        encoding="utf-8",
    )
    sub_file_2 = sub_dir / "02_sub.md"
    sub_file_2.write_text(
        "---\nid: sub_002\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: done\nparent: base_001\ndepends_on: []\nlinks: []\n---\n# Sub 2\n",
        encoding="utf-8",
    )

    actions = rollup_task_completion(sub_file_2, tasks_dir)
    assert len(actions) > 0
    assert any("01_core.md" in a or "base" in a for a in actions)

    # Verify file was updated to status: done
    content = base_file.read_text(encoding="utf-8")
    assert "status: done" in content


def test_e2e_step6_tri_mode_permissions_and_dry_run(tmp_path: Path):
    """Step 6: Tri-mode controller and Dry-run auditor operate seamlessly."""
    engine = get_mode_engine()

    # Plan mode permissions: blocks project code write, allows architecture write
    engine.set_mode(TriMode.PLAN)
    assert engine.current_mode == TriMode.PLAN
    allowed_code, _ = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert not allowed_code
    allowed_arch, _ = engine.evaluate_write_permission("tasks/sub/01.md", tmp_path)
    assert allowed_arch

    # Agent mode permissions: allows code writes
    engine.set_mode(TriMode.AGENT)
    assert engine.current_mode == TriMode.AGENT
    allowed_agent_code, _ = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert allowed_agent_code

    # Dry-Run audit
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent\n", encoding="utf-8")
    (ws / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (ws / "STACK.md").write_text(
        "---\nverification:\n  track_1:\n    - pytest\n---\n# STACK\n",
        encoding="utf-8",
    )

    report = audit_abb_readiness(tmp_path)
    assert report.overall_status in ("ready", "warning")
    assert report.format_report()
