"""Tests for repo-root priority and disambiguation in ABB virtualization."""

from pathlib import Path

from codeless.abb.virtualization import is_abb_path, resolve_virtual_path


def test_resolve_virtual_path_repo_root_priority(tmp_path: Path):
    """When a file exists at both the repo root and ABB workspace, repo root must take priority."""
    proj_root = tmp_path / "project"
    proj_root.mkdir()
    (proj_root / ".git").mkdir()

    # Create ABB workspace
    abb_ws = proj_root / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# ABB Agent\n", encoding="utf-8")
    (abb_ws / "STACK.md").write_text("# ABB Stack\n", encoding="utf-8")
    (abb_ws / "tasks").mkdir()
    (abb_ws / "tasks" / "tasks.md").write_text("# ABB Tasks\n", encoding="utf-8")

    # 1. When repo root does NOT have tasks/tasks.md, resolves to ABB workspace
    resolved = resolve_virtual_path(proj_root, "tasks/tasks.md")
    assert resolved == (abb_ws / "tasks" / "tasks.md").resolve()

    # 2. When repo root DOES have tasks/tasks.md, repo root takes priority
    repo_tasks = proj_root / "tasks" / "tasks.md"
    repo_tasks.parent.mkdir(parents=True)
    repo_tasks.write_text("# Repo Tasks\n", encoding="utf-8")

    resolved_repo = resolve_virtual_path(proj_root, "tasks/tasks.md")
    assert resolved_repo == repo_tasks.resolve()

    # 3. Absolute path resolution with repo-root priority
    resolved_abs = resolve_virtual_path(proj_root, str(repo_tasks))
    assert resolved_abs == repo_tasks.resolve()


def test_resolve_virtual_path_code_files_not_virtualized(tmp_path: Path):
    """Source code files (.py, .ts, etc.) inside domain directories should resolve to repo root."""
    proj_root = tmp_path / "project"
    proj_root.mkdir()
    (proj_root / ".git").mkdir()

    abb_ws = proj_root / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# ABB Agent\n", encoding="utf-8")

    # A python script inside tasks/ directory
    script_path = resolve_virtual_path(proj_root, "tasks/helper.py")
    assert script_path == (proj_root / "tasks" / "helper.py").resolve()

    # A typescript file inside design/ directory
    ts_path = resolve_virtual_path(proj_root, "design/types.ts")
    assert ts_path == (proj_root / "design" / "types.ts").resolve()


def test_is_abb_path_negative_common_names():
    """Verify common repo files are not falsely classified as ABB."""
    assert not is_abb_path("VERSION")
    assert not is_abb_path("LICENSE")
    assert not is_abb_path("tasks/worker.py")
    assert not is_abb_path("design/component.tsx")
    assert not is_abb_path("assets/icon.png")
    assert not is_abb_path("rules/custom.js")
    assert not is_abb_path("scripts/deploy.sh")
