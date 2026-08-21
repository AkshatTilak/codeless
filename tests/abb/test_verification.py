"""Tests for Two-Track Verification runner, manifest parser, and completion gate."""

from pathlib import Path

from codeless.abb.verification import (
    CommandReport,
    VerificationManifest,
    VerificationReport,
    execute_verification_manifest_sync,
    get_dag_snapshot,
    parse_verification_manifest,
    record_verification_failure,
    run_command_sync,
    verify_subtask_gate,
)


def test_parse_verification_manifest_string():
    stack_content = """---
version: 1.0.0
id: stack
verification:
  track_1:
    - python -m unittest
  track_2:
    - python -c "print('ok')"
  lint: ruff check .
  typecheck: mypy src
---

# STACK
"""
    manifest = parse_verification_manifest(stack_content)
    assert manifest.track_1 == ["python -m unittest"]
    assert manifest.track_2 == ["python -c \"print('ok')\""]
    assert manifest.lint == ["ruff check ."]
    assert manifest.typecheck == ["mypy src"]


def test_parse_verification_manifest_empty():
    manifest = parse_verification_manifest("")
    assert manifest.track_1 == []
    assert manifest.track_2 == []


def test_run_command_sync_success(tmp_path: Path):
    report = run_command_sync("python -c \"print('hello world')\"", tmp_path)
    assert report.success
    assert report.exit_code == 0
    assert "hello world" in report.stdout


def test_run_command_sync_failure(tmp_path: Path):
    report = run_command_sync('python -c "import sys; sys.exit(42)"', tmp_path)
    assert not report.success
    assert report.exit_code == 42


def test_run_command_sync_timeout(tmp_path: Path):
    report = run_command_sync(
        'python -c "import time; time.sleep(2)"', tmp_path, timeout_seconds=0.2
    )
    assert not report.success
    assert report.timed_out
    assert "timed out" in report.stderr


def test_execute_verification_manifest_passing(tmp_path: Path):
    manifest = VerificationManifest(
        track_1=["python -c \"print('T1 pass')\""],
        track_2=["python -c \"print('T2 pass')\""],
    )
    report = execute_verification_manifest_sync(manifest, tmp_path)
    assert report.success
    assert len(report.track_1_reports) == 1
    assert len(report.track_2_reports) == 1


def test_execute_verification_manifest_failing(tmp_path: Path):
    manifest = VerificationManifest(
        track_1=['python -c "import sys; sys.exit(1)"'],
        track_2=["python -c \"print('should not run')\""],
    )
    report = execute_verification_manifest_sync(manifest, tmp_path)
    assert not report.success
    assert len(report.track_1_reports) == 1
    # Track 2 shouldn't run if Track 1 fails
    assert len(report.track_2_reports) == 0


def test_record_verification_failure(tmp_path: Path):
    report = VerificationReport(
        success=False,
        track_1_reports=[
            CommandReport(
                command="pytest -q",
                exit_code=1,
                stdout="1 failed",
                stderr="AssertionError",
                duration_seconds=0.5,
            )
        ],
        summary="Unit tests failed",
    )
    log_file = record_verification_failure(tmp_path, "sub_010", report)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Track 1 (Unit)" in content
    assert "AssertionError" in content


def test_get_dag_snapshot(tmp_path: Path):
    abb_ws = tmp_path / "abb_ws"
    (abb_ws / "tasks" / "goal").mkdir(parents=True)
    (abb_ws / "tasks" / "base").mkdir(parents=True)
    (abb_ws / "tasks" / "sub").mkdir(parents=True)

    (abb_ws / "tasks" / "goal" / "goal.md").write_text(
        "---\nid: goal_001\nversion: 1.0.0\nstatus: in_progress\n---\n# Goal",
        encoding="utf-8",
    )
    (abb_ws / "tasks" / "base" / "01.md").write_text(
        "---\nid: base_001\nversion: 1.0.0\nstatus: done\nparent: goal_001\ndepends_on: []\n---\n# Base",
        encoding="utf-8",
    )
    (abb_ws / "tasks" / "sub" / "01.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: done\nparent: base_001\ndepends_on: []\n---\n# Sub",
        encoding="utf-8",
    )

    snapshot = get_dag_snapshot(abb_ws)
    assert snapshot["goal"]["id"] == "goal_001"
    assert len(snapshot["base_tasks"]) == 1
    assert snapshot["base_tasks"][0]["id"] == "base_001"
    assert len(snapshot["subtasks"]) == 1
    assert snapshot["subtasks"][0]["id"] == "sub_001"


def test_verify_subtask_gate_integration(tmp_path: Path):
    abb_ws = tmp_path / "abb_ws"
    tasks_dir = abb_ws / "tasks"
    (tasks_dir / "sub").mkdir(parents=True)

    # Write STACK.md with a failing command
    stack_content = """---
version: 1.0.0
id: stack
verification:
  track_1:
    - python -c "import sys; sys.exit(2)"
---
# STACK
"""
    (abb_ws / "STACK.md").write_text(stack_content, encoding="utf-8")

    subtask_file = tasks_dir / "sub" / "01_test.md"
    subtask_content = """---
id: sub_001
version: 1.0.0
status: done
parent: base_001
depends_on: []
---
# Subtask 1
"""
    subtask_file.write_text(subtask_content, encoding="utf-8")

    passed, reason, report = verify_subtask_gate("sub_001", tmp_path, abb_ws)
    assert not passed
    assert "Verification Failed" in reason
    assert report is not None
