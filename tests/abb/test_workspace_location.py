"""Tests for configurable ABB workspace location (shadow vs local)."""

from pathlib import Path

from codeless.abb.shadow import (
    bootstrap_workspace,
    ensure_gitignore_has_codeless,
    get_configured_abb_location,
    resolve_abb_workspace,
)
from codeless.abb.virtualization import (
    get_search_roots,
    resolve_virtual_path,
)


def test_ensure_gitignore_has_codeless_creates_gitignore(tmp_path: Path):
    """Test that ensure_gitignore_has_codeless creates .gitignore if absent."""
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    gitignore = project_root / ".gitignore"

    assert not gitignore.exists()
    assert ensure_gitignore_has_codeless(project_root) is True
    assert gitignore.exists()
    content = gitignore.read_text(encoding="utf-8")
    assert ".codeless/" in content


def test_ensure_gitignore_has_codeless_appends_when_missing(tmp_path: Path):
    """Test that ensure_gitignore_has_codeless appends to existing .gitignore."""
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    gitignore = project_root / ".gitignore"
    gitignore.write_text("node_modules/\n*.pyc\n", encoding="utf-8")

    assert ensure_gitignore_has_codeless(project_root) is True
    content = gitignore.read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert ".codeless/" in content


def test_ensure_gitignore_has_codeless_no_duplicate(tmp_path: Path):
    """Test that ensure_gitignore_has_codeless doesn't add duplicate entries."""
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    gitignore = project_root / ".gitignore"
    gitignore.write_text(".codeless/\n", encoding="utf-8")

    assert ensure_gitignore_has_codeless(project_root) is True
    content = gitignore.read_text(encoding="utf-8")
    assert content.count(".codeless") == 1


def test_bootstrap_workspace_shadow(tmp_path: Path):
    """Test bootstrapping in default shadow mode."""
    project_root = tmp_path / "proj_shadow"
    project_root.mkdir()

    ws_path, meta = bootstrap_workspace(project_root, location="shadow")
    assert ws_path.exists()
    assert (ws_path / "agent.md").exists()
    assert meta["abb_location"] == "shadow"
    # Ensure it did NOT create .codeless in project_root
    assert not (project_root / ".codeless").exists()


def test_bootstrap_workspace_local(tmp_path: Path):
    """Test bootstrapping in local mode."""
    project_root = tmp_path / "proj_local"
    project_root.mkdir()

    ws_path, meta = bootstrap_workspace(project_root, location="local")
    assert ws_path.exists()
    assert ws_path == project_root / ".codeless" / "abb_workspace"
    assert (ws_path / "agent.md").exists()
    assert meta["abb_location"] == "local"
    assert (project_root / ".gitignore").exists()


def test_resolve_abb_workspace_respects_explicit_parameter(tmp_path: Path):
    """Test resolve_abb_workspace with explicit location parameter."""
    project_root = tmp_path / "proj_param"
    project_root.mkdir()

    local_ws = resolve_abb_workspace(project_root, auto_init=True, location="local")
    assert local_ws == project_root / ".codeless" / "abb_workspace"

    shadow_ws = resolve_abb_workspace(project_root, auto_init=True, location="shadow")
    assert shadow_ws != project_root / ".codeless" / "abb_workspace"
    assert "projects" in str(shadow_ws)


def test_resolve_abb_workspace_reads_persisted_metadata(tmp_path: Path):
    """Test resolve_abb_workspace reads persisted location setting."""
    project_root = tmp_path / "proj_persisted"
    project_root.mkdir()

    # Bootstrap locally
    bootstrap_workspace(project_root, location="local")
    assert get_configured_abb_location(project_root) == "local"

    # Resolving without specifying location should find local
    resolved = resolve_abb_workspace(project_root, auto_init=False)
    assert resolved == project_root / ".codeless" / "abb_workspace"


def test_virtualization_with_local_workspace(tmp_path: Path):
    """Test resolve_virtual_path and search roots when workspace is local."""
    project_root = tmp_path / "proj_virt"
    project_root.mkdir()
    bootstrap_workspace(project_root, location="local")

    # Virtual path for ABB file
    resolved_task = resolve_virtual_path(project_root, "tasks/goal/goal.md")
    assert (
        resolved_task == project_root / ".codeless" / "abb_workspace" / "tasks" / "goal" / "goal.md"
    )

    # Virtual path for .codeless/abb_workspace/... relative path
    resolved_nested = resolve_virtual_path(project_root, ".codeless/abb_workspace/agent.md")
    assert resolved_nested == project_root / ".codeless" / "abb_workspace" / "agent.md"

    # Search roots should only have project_root since abb_workspace is inside it
    roots = get_search_roots(project_root)
    assert len(roots) == 1
    assert roots[0] == project_root
