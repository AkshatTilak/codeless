"""Tests for SkillStagingHook (pull-adapt-delete workflow validator)."""

from pathlib import Path

from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.shadow import bootstrap_workspace


def test_staging_guard_blocks_skills_write_when_staging_nonempty(tmp_path: Path):
    """Test that pre_tool_use_abb_guard blocks writing skills.md if _staging/ contains files."""
    project_root = tmp_path / "project_staging"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Create non-empty _staging directory
    staging_dir = ws_path / "skills" / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staging_dir / "external_skill.md"
    staged_file.write_text("# External Skill Staged Content", encoding="utf-8")

    # Attempt to write skills.md
    allowed, reason = pre_tool_use_abb_guard(
        tool_name="write_file",
        arguments={"path": "skills/skills.md", "content": "# Updated Skills Index"},
        cwd=project_root,
    )
    assert allowed is False
    assert "ABB Skill Staging Blocked" in reason
    assert "_staging" in reason


def test_staging_guard_allows_skills_write_when_staging_empty(tmp_path: Path):
    """Test that pre_tool_use_abb_guard allows writing skills.md when _staging/ is empty."""
    project_root = tmp_path / "project_clean"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Clean staging directory (only .gitkeep or empty)
    staging_dir = ws_path / "skills" / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / ".gitkeep").write_text("", encoding="utf-8")

    allowed, reason = pre_tool_use_abb_guard(
        tool_name="write_file",
        arguments={"path": "skills/skills.md", "content": "# Updated Skills Index"},
        cwd=project_root,
    )
    assert allowed is True
    assert reason == "OK"
