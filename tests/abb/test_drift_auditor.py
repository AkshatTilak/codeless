"""Tests for Drift Auditor & Feedback Loop Engine."""

from pathlib import Path

from codeless.abb.drift import feed_drift_to_issues, run_drift_audit
from codeless.abb.shadow import bootstrap_workspace


def test_drift_audit_clean_workspace(tmp_path: Path):
    """Test that a freshly bootstrapped workspace passes drift audit."""
    project_root = tmp_path / "proj_clean"
    project_root.mkdir()
    bootstrap_workspace(project_root, location="local")

    report = run_drift_audit(project_root)
    assert report.clean is True
    assert len(report.issues) == 0


def test_drift_audit_detects_schema_discrepancy(tmp_path: Path):
    """Test drift audit detects manual frontmatter / schema discrepancy in a task file."""
    project_root = tmp_path / "proj_schema_err"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Inject invalid task frontmatter (missing id and invalid status)
    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    bad_task = sub_dir / "99_broken_task.md"
    bad_task.write_text(
        "---\nversion: 1.0.0\nstatus: not_a_real_status\n---\n# Broken Task\n",
        encoding="utf-8",
    )

    report = run_drift_audit(project_root)
    assert report.clean is False
    assert any("99_broken_task.md" in issue.file_path for issue in report.issues)
    assert any(
        "id" in issue.description.lower() or "status" in issue.description.lower()
        for issue in report.issues
    )


def test_drift_audit_detects_unindexed_skill(tmp_path: Path):
    """Test drift audit detects a skill on disk that is omitted from skills.md index."""
    project_root = tmp_path / "proj_unindexed_skill"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Create unindexed skill
    unindexed_dir = ws_path / "skills" / "custom" / "my_secret_skill"
    unindexed_dir.mkdir(parents=True, exist_ok=True)
    (unindexed_dir / "SKILL.md").write_text("# My Secret Skill\nDoes things.\n", encoding="utf-8")

    report = run_drift_audit(project_root)
    assert report.clean is False
    assert any(
        "my_secret_skill" in issue.file_path or "my_secret_skill" in issue.description
        for issue in report.issues
    )


def test_feed_drift_to_issues(tmp_path: Path):
    """Test feed_drift_to_issues logs drift findings into references/issues/."""
    project_root = tmp_path / "proj_feed"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    bad_task = sub_dir / "98_error_task.md"
    bad_task.write_text(
        "---\nversion: 1.0.0\nstatus: invalid_state\n---\n# Bad Task\n",
        encoding="utf-8",
    )

    report = run_drift_audit(project_root)
    assert report.clean is False

    issues_file = feed_drift_to_issues(project_root, report)
    assert issues_file is not None
    assert issues_file.exists()
    content = issues_file.read_text(encoding="utf-8")
    assert "98_error_task.md" in content
    assert "Technical Debt & Drift Issues" in content
