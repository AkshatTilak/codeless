"""Tests for shadow workspace resolution and auto-initialization."""

import json
from pathlib import Path

from codeless.abb.shadow import (
    bootstrap_shadow_workspace,
    get_project_hash,
    get_project_storage_dir,
    resolve_abb_workspace,
)


def test_get_project_hash_deterministic(tmp_path: Path) -> None:
    hash1 = get_project_hash(tmp_path)
    hash2 = get_project_hash(tmp_path)
    assert hash1 == hash2
    assert len(hash1) == 64


def test_bootstrap_shadow_workspace(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "fake_home"
    monkeypatch.setenv("CODELESS_HOME", str(fake_home / ".codeless"))

    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()

    abb_ws, metadata = bootstrap_shadow_workspace(proj_dir)

    assert abb_ws.exists()
    assert (abb_ws / "agent.md").exists()
    assert (abb_ws / "workflows" / "router.md").exists()
    assert (abb_ws / "tasks" / "tasks.md").exists()
    assert (abb_ws / "references" / "references.md").exists()

    storage_dir = get_project_storage_dir(proj_dir)
    assert (storage_dir / "logs" / "failure").exists()
    assert (storage_dir / "sessions").exists()
    assert (storage_dir / "checkpoints").exists()

    metadata_file = storage_dir / "metadata.json"
    assert metadata_file.exists()
    data = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert data["project_name"] == "my_project"
    assert data["template_version"] != ""


def test_resolve_abb_workspace_dev_override(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "fake_home"
    monkeypatch.setenv("CODELESS_HOME", str(fake_home / ".codeless"))

    proj_dir = tmp_path / "override_project"
    proj_dir.mkdir()

    # Create in-repo dev override
    override_dir = proj_dir / ".codeless" / "abb_workspace"
    override_dir.mkdir(parents=True)
    (override_dir / "agent.md").write_text("# Override Agent", encoding="utf-8")

    resolved = resolve_abb_workspace(proj_dir)
    assert resolved == override_dir
    assert (resolved / "agent.md").read_text(encoding="utf-8") == "# Override Agent"


def test_resolve_abb_workspace_auto_init(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "fake_home"
    monkeypatch.setenv("CODELESS_HOME", str(fake_home / ".codeless"))

    proj_dir = tmp_path / "auto_init_project"
    proj_dir.mkdir()

    resolved = resolve_abb_workspace(proj_dir, auto_init=True)
    assert resolved.exists()
    assert (resolved / "agent.md").exists()
