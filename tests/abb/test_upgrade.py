"""Tests for ABB workspace upgrade engine and CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.upgrade import (
    apply_upgrade,
    compute_base_task_numbering,
    detect_workspace_task_layout,
    plan_upgrade,
)
from codeless.cli import app
from tests.abb.test_links_and_structure import _validate_workspace_links

runner = CliRunner()


def _create_mock_legacy_workspace(ws_path: Path) -> None:
    """Populate a mock workspace with legacy flat tasks and external cross-links."""
    ws_path.mkdir(parents=True, exist_ok=True)

    # Core workspace files
    (ws_path / "agent.md").write_text("# Agent Instructions\n", encoding="utf-8")
    (ws_path / "STACK.md").write_text("# Tech Stack\n", encoding="utf-8")
    (ws_path / "CONVENTIONS.md").write_text("# Conventions\n", encoding="utf-8")
    (ws_path / "references").mkdir(parents=True, exist_ok=True)
    (ws_path / "references" / "references.md").write_text("# References\n", encoding="utf-8")
    for wf in [
        "execution/work_principle.md",
        "execution/work_verification.md",
        "planning/extend_goal.md",
    ]:
        wf_p = ws_path / "workflows" / wf
        wf_p.parent.mkdir(parents=True, exist_ok=True)
        wf_p.write_text("# Workflow\n", encoding="utf-8")

    # Features and design docs
    features_dir = ws_path / "features" / "auth"
    features_dir.mkdir(parents=True, exist_ok=True)
    (features_dir / "spec.md").write_text(
        "---\n"
        "id: feat_auth\n"
        "links:\n"
        "  - ../../tasks/base/auth_service.md\n"
        "  - ../../tasks/sub/01_jwt_tokens.md\n"
        "---\n"
        "# Auth Spec\n"
        "See [Base Task](../../tasks/base/auth_service.md) and [Subtask](../../tasks/sub/01_jwt_tokens.md).\n",
        encoding="utf-8",
    )

    design_dir = ws_path / "design" / "system"
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / "arch.md").write_text(
        "---\nlinks:\n  - ../../tasks/base/auth_service.md\n---\n# Architecture\n",
        encoding="utf-8",
    )

    # Legacy flat tasks
    tasks_dir = ws_path / "tasks"
    base_dir = tasks_dir / "base"
    sub_dir = tasks_dir / "sub"
    goal_dir = tasks_dir / "goal"
    base_dir.mkdir(parents=True, exist_ok=True)
    sub_dir.mkdir(parents=True, exist_ok=True)
    goal_dir.mkdir(parents=True, exist_ok=True)

    (goal_dir / "goal.md").write_text(
        "---\n"
        "id: goal_001\n"
        "links:\n"
        "  - ../../design/system/arch.md\n"
        "---\n"
        "# Goal SRS\n"
        "- [ ] `base/auth_service.md`\n",
        encoding="utf-8",
    )

    # Base task with numeric frontmatter id
    (base_dir / "auth_service.md").write_text(
        "---\n"
        "id: base_002\n"
        "parent: goal_001\n"
        "links:\n"
        "  - ../../tasks/goal/goal.md\n"
        "  - ../../STACK.md\n"
        "---\n"
        "# Base Task: Auth Service\n"
        "## Subtask Registry\n"
        "- [ ] sub/01_jwt_tokens.md\n",
        encoding="utf-8",
    )

    # Base task without numeric id
    (base_dir / "unassigned_module.md").write_text(
        "---\n"
        "id: base_xyz\n"
        "parent: goal_001\n"
        "links:\n"
        "  - ../../tasks/goal/goal.md\n"
        "---\n"
        "# Base Task: Unassigned Module\n",
        encoding="utf-8",
    )

    # Subtask
    (sub_dir / "01_jwt_tokens.md").write_text(
        "---\n"
        "id: sub_001\n"
        "parent: base_002\n"
        "links:\n"
        "  - ../../tasks/base/auth_service.md\n"
        "  - ../../agent.md\n"
        "---\n"
        "# Subtask: JWT Tokens\n"
        "## Parent Link\n"
        "`base/auth_service.md`\n",
        encoding="utf-8",
    )


def test_detect_workspace_task_layout(tmp_path: Path):
    """Test layout detection for empty, legacy flat, and versioned workspaces."""
    ws = tmp_path / "ws_layout"
    ws.mkdir()

    # 1. No tasks dir
    layout1 = detect_workspace_task_layout(ws)
    assert not layout1["exists"]

    # 2. Legacy flat tasks
    (ws / "tasks" / "base").mkdir(parents=True)
    (ws / "tasks" / "sub").mkdir(parents=True)
    layout2 = detect_workspace_task_layout(ws)
    assert layout2["is_legacy_flat"]
    assert not layout2["is_versioned"]

    # 3. Versioned tasks
    (ws / "tasks" / "v1" / "base").mkdir(parents=True)
    (ws / "tasks" / "base").rmdir()
    (ws / "tasks" / "sub").rmdir()
    layout3 = detect_workspace_task_layout(ws)
    assert not layout3["is_legacy_flat"]
    assert layout3["is_versioned"]
    assert "v1" in layout3["version_folders"]


def test_compute_base_task_numbering(tmp_path: Path):
    """Test extracting numbers from frontmatter ID, preserving existing prefixes, and sequencing."""
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    # Pre-numbered
    p1 = base_dir / "01_foundation.md"
    p1.write_text("id: base_001\n", encoding="utf-8")

    # Frontmatter ID has base_013
    p2 = base_dir / "readme_docs.md"
    p2.write_text("id: base_013\n", encoding="utf-8")

    # No numeric ID
    p3 = base_dir / "unassigned.md"
    p3.write_text("id: base_unknown\n", encoding="utf-8")

    rename_map = compute_base_task_numbering([p1, p2, p3])
    assert rename_map["01_foundation.md"] == "01_foundation.md"
    assert rename_map["readme_docs.md"] == "13_readme_docs.md"
    # Unassigned gets next free number (e.g. 02_unassigned.md)
    assert rename_map["unassigned.md"].endswith("_unassigned.md")
    assert rename_map["unassigned.md"] == "02_unassigned.md"


def test_plan_upgrade_dry_run(tmp_path: Path):
    """Test plan formulation in dry-run mode without modifying disk."""
    ws = tmp_path / "ws_plan"
    _create_mock_legacy_workspace(ws)

    plan = plan_upgrade(ws, target_version="v1")
    assert plan.has_changes
    assert plan.is_legacy_flat
    assert len(plan.goals_to_move) == 1
    assert len(plan.base_tasks_to_move) == 2
    assert len(plan.subtasks_to_move) == 1
    assert plan.base_task_rename_map["auth_service.md"] == "02_auth_service.md"

    # Verify no files were moved yet on disk
    assert (ws / "tasks" / "base" / "auth_service.md").exists()
    assert not (ws / "tasks" / "v1").exists()


def test_apply_upgrade_full_lifecycle(tmp_path: Path):
    """Test executing full upgrade, verifying file relocation, backup, and link integrity."""
    ws = tmp_path / "ws_full"
    _create_mock_legacy_workspace(ws)

    plan = plan_upgrade(ws, target_version="v1")
    result = apply_upgrade(ws, plan, create_backup=True)

    assert result.success
    assert result.backup_dir is not None
    assert result.backup_dir.exists()
    assert result.moved_goals == 1
    assert result.moved_base_tasks == 2
    assert result.moved_subtasks == 1

    # Verify new versioned layout exists
    v1_dir = ws / "tasks" / "v1"
    assert (v1_dir / "goal" / "goal.md").exists()
    assert (v1_dir / "base" / "02_auth_service.md").exists()
    assert (v1_dir / "sub" / "01_jwt_tokens.md").exists()

    # Verify old flat folders are removed
    assert not (ws / "tasks" / "base").exists()
    assert not (ws / "tasks" / "sub").exists()
    assert not (ws / "tasks" / "goal").exists()

    # Verify link integrity across the entire upgraded workspace (ZERO broken links)
    scanned_files, scanned_links, broken_links = _validate_workspace_links(ws)
    assert len(broken_links) == 0, "Broken links found after upgrade:\n" + "\n".join(broken_links)

    # Verify runtime DAG guard indexing on the upgraded workspace
    task_index = index_tasks(ws / "tasks")
    assert len(task_index) >= 1
    # Found by task_id and relative paths
    assert "sub_001" in task_index
    assert task_index["sub_001"][1]["_version_folder"] == "v1"


def test_cli_upgrade_dry_run_and_apply(tmp_path: Path):
    """Test CLI `codeless abb upgrade` in dry-run and apply modes."""
    project_root = tmp_path / "cli_proj"
    project_root.mkdir()
    ws = project_root / ".codeless" / "abb_workspace"
    _create_mock_legacy_workspace(ws)

    # 1. Dry run via CLI
    res_dry = runner.invoke(
        app,
        ["abb", "upgrade", "--project-root", str(project_root), "--dry-run"],
    )
    assert res_dry.exit_code == 0
    assert "[Dry-Run Mode]" in res_dry.output
    assert "02_auth_service.md" in res_dry.output
    # Files still in flat layout
    assert (ws / "tasks" / "base").exists()

    # 2. Apply via CLI
    res_apply = runner.invoke(
        app,
        ["abb", "upgrade", "--project-root", str(project_root), "--apply"],
    )
    assert res_apply.exit_code == 0
    assert "ABB workspace upgrade completed successfully!" in res_apply.output
    assert (ws / "tasks" / "v1" / "base" / "02_auth_service.md").exists()

    # 3. Running upgrade again on already upgraded project
    res_again = runner.invoke(
        app,
        ["abb", "upgrade", "--project-root", str(project_root)],
    )
    assert res_again.exit_code == 0
    assert (
        "already versioned" in res_again.output.lower() or "no changes" in res_again.output.lower()
    )
