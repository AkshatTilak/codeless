"""Tests for ABB workspace migration command and helper functions."""

from pathlib import Path

from typer.testing import CliRunner

from codeless.abb.shadow import (
    bootstrap_workspace,
    get_configured_abb_location,
    migrate_abb_workspace,
)
from codeless.cli import app

runner = CliRunner()


def test_migrate_shadow_to_local(tmp_path: Path):
    """Test migrating from shadow store to local repository."""
    project_root = tmp_path / "proj_mig_1"
    project_root.mkdir()

    # Initially in shadow mode
    shadow_ws, _ = bootstrap_workspace(project_root, location="shadow")
    assert shadow_ws.exists()
    assert not (project_root / ".codeless").exists()

    # Perform migration to local
    src, dst = migrate_abb_workspace(project_root, target_location="local")
    assert dst == project_root / ".codeless" / "abb_workspace"
    assert dst.exists()
    assert (dst / "agent.md").exists()
    assert (project_root / ".gitignore").exists()
    assert get_configured_abb_location(project_root) == "local"


def test_migrate_local_to_shadow(tmp_path: Path):
    """Test migrating from local repository to shadow store."""
    project_root = tmp_path / "proj_mig_2"
    project_root.mkdir()

    # Initially in local mode
    local_ws, _ = bootstrap_workspace(project_root, location="local")
    assert local_ws.exists()

    # Perform migration to shadow
    src, dst = migrate_abb_workspace(project_root, target_location="shadow")
    assert dst.exists()
    assert (dst / "agent.md").exists()
    assert get_configured_abb_location(project_root) == "shadow"


def test_migrate_cli_commands(tmp_path: Path):
    """Test `codeless abb migrate local` and `codeless abb migrate shadow` via CLI."""
    project_root = tmp_path / "proj_cli_mig"
    project_root.mkdir()

    # Initialize shadow
    bootstrap_workspace(project_root, location="shadow")

    # Migrate to local via CLI
    res = runner.invoke(
        app,
        ["abb", "migrate", "local", "--project-root", str(project_root)],
    )
    assert res.exit_code == 0
    assert "Migrated ABB workspace to 'local'" in res.output
    assert (project_root / ".codeless" / "abb_workspace" / "agent.md").exists()

    # Migrate to shadow via CLI
    res2 = runner.invoke(
        app,
        ["abb", "migrate", "shadow", "--project-root", str(project_root), "--force"],
    )
    assert res2.exit_code == 0
    assert "Migrated ABB workspace to 'shadow'" in res2.output
