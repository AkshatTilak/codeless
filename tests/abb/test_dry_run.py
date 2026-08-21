"""Tests for ABB Dry-Run Preview and Readiness Auditor (C14)."""

from __future__ import annotations

from pathlib import Path

from codeless.abb.dry_run import audit_abb_readiness
from codeless.cli import _build_dry_run_preview, _format_dry_run_preview


def test_audit_abb_readiness_valid_workspace(tmp_path: Path):
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent\n", encoding="utf-8")
    (ws / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (ws / "STACK.md").write_text(
        "---\nverification:\n  track_1:\n    - uv run pytest\n---\n# STACK\n",
        encoding="utf-8",
    )
    tasks_dir = ws / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "task_1.md").write_text(
        "---\nid: task_1\nversion: 1.0.0\nupdated: 2026-08-19\nstatus: pending\ndepends_on: []\nlinks: []\n---\n# Task 1\n",
        encoding="utf-8",
    )

    report = audit_abb_readiness(tmp_path)
    assert report.overall_status in ("ready", "warning")
    assert report.workspace_path == tmp_path.resolve()
    assert any("Shadow Workspace" in c.name and c.status == "ok" for c in report.checks)
    assert any("STACK.md" in c.name and c.status == "ok" for c in report.checks)
    assert any("Task Frontmatter Schema" in c.name and c.status == "ok" for c in report.checks)

    formatted = report.format_report()
    assert "Codeless ABB Dry-Run Pre-Flight Audit" in formatted
    assert "READY" in formatted or "WARNING" in formatted


def test_audit_abb_readiness_missing_workspace(tmp_path: Path, monkeypatch):
    # Ensure no AppData or in-repo workspace exists
    monkeypatch.setenv("CODELESS_HOME", str(tmp_path / "global_codeless"))
    report = audit_abb_readiness(tmp_path)
    assert report.overall_status == "blocked"
    assert any(c.status == "blocked" for c in report.checks)


def test_cli_dry_run_preview_includes_abb_readiness(tmp_path: Path):
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent\n", encoding="utf-8")
    (ws / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (ws / "STACK.md").write_text(
        "---\nverification:\n  track_1:\n    - pytest\n---\n# STACK\n",
        encoding="utf-8",
    )

    preview = _build_dry_run_preview(
        prompt="test prompt",
        cwd=str(tmp_path),
        model=None,
        max_turns=None,
        base_url=None,
        system_prompt=None,
        append_system_prompt=None,
        api_key=None,
        api_format=None,
        permission_mode=None,
        effort=None,
    )
    assert "abb_readiness" in preview
    assert preview["abb_readiness"]["status"] in ("ready", "warning")

    formatted = _format_dry_run_preview(preview)
    assert "ABB Governance Readiness" in formatted
    assert "Shadow Workspace" in formatted
