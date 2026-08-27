"""Tests for PLAN mode write guard path verification and misclassification prevention."""

from pathlib import Path

from codeless.abb.permissions import ModeEngine, TriMode


def test_plan_mode_blocks_codebase_writes_under_abb_named_dirs(tmp_path: Path):
    """In PLAN mode, writes to codebase files (even under tasks/ or design/) must be blocked."""
    proj_root = tmp_path / "project"
    proj_root.mkdir()
    (proj_root / ".git").mkdir()

    abb_ws = proj_root / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# ABB Agent\n", encoding="utf-8")

    engine = ModeEngine(default_mode=TriMode.PLAN)

    # 1. Code file under tasks/ directory (codebase write -> blocked in PLAN mode)
    allowed, reason = engine.evaluate_write_permission("tasks/my_script.py", cwd=proj_root)
    assert not allowed
    assert "Plan Mode blocks project code modifications" in reason

    # 2. Existing codebase file in repo root under tasks/
    repo_task_file = proj_root / "tasks" / "existing.md"
    repo_task_file.parent.mkdir(parents=True, exist_ok=True)
    repo_task_file.write_text("# Existing in repo\n", encoding="utf-8")

    allowed_repo, reason_repo = engine.evaluate_write_permission("tasks/existing.md", cwd=proj_root)
    assert not allowed_repo
    assert "Plan Mode blocks project code modifications" in reason_repo

    # 3. Legitimate ABB workspace specification write -> allowed in PLAN mode
    allowed_abb, reason_abb = engine.evaluate_write_permission("tasks/goal/goal.md", cwd=proj_root)
    assert allowed_abb
    assert "Plan mode permitted write" in reason_abb

    # 4. Explicit ABB workspace path -> allowed in PLAN mode
    explicit_abb_path = str(abb_ws / "tasks" / "tasks.md")
    allowed_exp, reason_exp = engine.evaluate_write_permission(explicit_abb_path, cwd=proj_root)
    assert allowed_exp
    assert "Plan mode permitted write" in reason_exp
