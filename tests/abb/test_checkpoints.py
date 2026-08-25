"""Tests for Git Checkpoints and Rollback Engine."""

import subprocess
from pathlib import Path

from codeless.abb.checkpoints import (
    create_checkpoint,
    list_checkpoints,
    restore_checkpoint,
)
from codeless.abb.shadow import bootstrap_workspace


def _init_git_repo(path: Path):
    """Helper to initialize a git repo with initial commit."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestUser"], cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    readme = path / "README.md"
    readme.write_text("# Initial Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True, check=True
    )


def test_create_and_list_checkpoints(tmp_path: Path):
    """Test creating snapshots and listing them from project checkpoints directory."""
    project_root = tmp_path / "proj_cp"
    project_root.mkdir()
    _init_git_repo(project_root)
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Create a code file
    src_file = project_root / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('v1')", encoding="utf-8")

    cp = create_checkpoint(project_root, name="before_refactor", description="Initial code state")
    assert cp.checkpoint_id is not None
    assert cp.name == "before_refactor"
    assert cp.description == "Initial code state"

    checkpoints = list_checkpoints(project_root)
    assert len(checkpoints) >= 1
    assert any(c.checkpoint_id == cp.checkpoint_id for c in checkpoints)


def test_restore_checkpoint_code_and_abb(tmp_path: Path):
    """Test restoring a checkpoint restores both codebase working tree and ABB workspace state."""
    project_root = tmp_path / "proj_restore"
    project_root.mkdir()
    _init_git_repo(project_root)
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # 1. State 1: app.py has v1, subtask 01 has pending
    src_file = project_root / "src" / "main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("x = 1\n", encoding="utf-8")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    sub1 = sub_dir / "01_test.md"
    sub1.write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: pending\n---\n# Sub 1\n", encoding="utf-8"
    )

    cp1 = create_checkpoint(project_root, name="state_1")

    # 2. State 2: Mutate code to v2, mark subtask done
    src_file.write_text("x = 2; y = 999\n", encoding="utf-8")
    sub1.write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: done\n---\n# Sub 1\n", encoding="utf-8"
    )

    assert src_file.read_text(encoding="utf-8") == "x = 2; y = 999\n"
    assert "status: done" in sub1.read_text(encoding="utf-8")

    # 3. Restore State 1
    success, msg = restore_checkpoint(project_root, checkpoint_id=cp1.checkpoint_id, force=True)
    assert success is True
    assert "restored" in msg.lower()

    # Code restored
    assert src_file.read_text(encoding="utf-8") == "x = 1\n"
    # ABB workspace restored
    assert "status: pending" in sub1.read_text(encoding="utf-8")


def test_restore_dirty_warning_without_force(tmp_path: Path):
    """Test that restore without force requires confirmation or warns when tree is modified."""
    project_root = tmp_path / "proj_dirty"
    project_root.mkdir()
    _init_git_repo(project_root)
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    src_file = project_root / "src" / "clean.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("clean = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=project_root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "commit clean"], cwd=project_root, capture_output=True, check=True
    )

    cp = create_checkpoint(project_root, name="clean_checkpoint")

    # Modify file making it dirty
    src_file.write_text("clean = False; dirty = True\n", encoding="utf-8")

    success, msg = restore_checkpoint(project_root, checkpoint_id=cp.checkpoint_id, force=False)
    # If not forced and working tree has uncommitted modifications, returns warning / confirmation requirement
    assert "uncommitted" in msg.lower() or "force" in msg.lower()
