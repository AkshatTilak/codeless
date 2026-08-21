"""Unit tests for shadow project listing, orphan detection, GC and CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codeless.abb.shadow import (
    bootstrap_shadow_workspace,
    clean_shadow_projects,
    get_dir_size_bytes,
    list_shadow_projects,
)
from codeless.cli import app

runner = CliRunner()


def test_get_dir_size_bytes(tmp_path: Path) -> None:
    test_dir = tmp_path / "size_test"
    test_dir.mkdir()
    (test_dir / "file1.txt").write_text("hello", encoding="utf-8")  # 5 bytes
    (test_dir / "sub").mkdir()
    (test_dir / "sub" / "file2.txt").write_text("world!", encoding="utf-8")  # 6 bytes

    size = get_dir_size_bytes(test_dir)
    assert size == 11


def test_list_and_clean_shadow_projects(tmp_path: Path, monkeypatch) -> None:
    codeless_home = tmp_path / "custom_home"
    monkeypatch.setenv("CODELESS_HOME", str(codeless_home))

    # Project 1: Real existing project
    real_proj = tmp_path / "real_project"
    real_proj.mkdir()
    ws1, meta1 = bootstrap_shadow_workspace(real_proj)

    # Project 2: Orphan project (create then delete)
    orphan_proj = tmp_path / "orphan_project"
    orphan_proj.mkdir()
    ws2, meta2 = bootstrap_shadow_workspace(orphan_proj)
    # Now remove the original orphan project folder from disk
    orphan_proj.rmdir()

    # List projects
    projects = list_shadow_projects()
    assert len(projects) == 2

    real_record = next(p for p in projects if p["project_name"] == "real_project")
    orphan_record = next(p for p in projects if p["project_name"] == "orphan_project")

    assert real_record["exists_on_disk"] is True
    assert real_record["is_orphan"] is False
    assert real_record["disk_size_bytes"] > 0

    assert orphan_record["exists_on_disk"] is False
    assert orphan_record["is_orphan"] is True
    assert orphan_record["disk_size_bytes"] > 0

    # Dry-run clean
    cleaned_dry = clean_shadow_projects(dry_run=True, clean_all=False)
    assert len(cleaned_dry) == 1
    assert cleaned_dry[0]["project_name"] == "orphan_project"
    assert Path(cleaned_dry[0]["storage_dir"]).exists()

    # Actual clean of orphans
    cleaned_actual = clean_shadow_projects(dry_run=False, clean_all=False)
    assert len(cleaned_actual) == 1
    assert not Path(cleaned_actual[0]["storage_dir"]).exists()

    # Verify list now only contains 1 project
    projects_after = list_shadow_projects()
    assert len(projects_after) == 1
    assert projects_after[0]["project_name"] == "real_project"

    # Clean all
    cleaned_all = clean_shadow_projects(dry_run=False, clean_all=True)
    assert len(cleaned_all) == 1
    assert len(list_shadow_projects()) == 0


def test_cli_projects_commands(tmp_path: Path, monkeypatch) -> None:
    codeless_home = tmp_path / "cli_home"
    monkeypatch.setenv("CODELESS_HOME", str(codeless_home))

    # Empty list
    res = runner.invoke(app, ["projects", "list"])
    assert res.exit_code == 0
    assert "No registered shadow workspaces found" in res.output

    # JSON empty list
    res_json = runner.invoke(app, ["projects", "list", "--json"])
    assert res_json.exit_code == 0
    assert json.loads(res_json.output) == []

    # Bootstrap one project
    proj = tmp_path / "my_cli_proj"
    proj.mkdir()
    bootstrap_shadow_workspace(proj)

    # CLI List
    res = runner.invoke(app, ["projects", "list"])
    assert res.exit_code == 0
    assert "my_cli_proj" in res.output
    assert "Registered Shadow Workspaces (1)" in res.output

    # CLI Clean dry-run
    res_clean_dry = runner.invoke(app, ["projects", "clean", "--dry-run"])
    assert res_clean_dry.exit_code == 0
    assert "No shadow workspaces to clean" in res_clean_dry.output

    # CLI Clean all with --dry-run
    res_clean_all_dry = runner.invoke(app, ["projects", "clean", "--dry-run", "--all"])
    assert res_clean_all_dry.exit_code == 0
    assert "Would remove 1 shadow workspace(s)" in res_clean_all_dry.output
