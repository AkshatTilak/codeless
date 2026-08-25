"""Tests for Subagent Workers, Context Sandboxing, and Concurrency Cap."""

import asyncio
from pathlib import Path

import pytest

from codeless.abb.shadow import bootstrap_workspace
from codeless.coordinator.workers import (
    MAX_CONCURRENT_WORKERS,
    SubagentCoordinator,
    WorkerContextPackage,
    build_worker_context_package,
    find_ready_subtasks,
)


def test_build_worker_context_package_sandboxing(tmp_path: Path):
    """Test that context package contains ONLY the target subtask, linked files, and location info."""
    project_root = tmp_path / "proj_sandbox"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)

    # Create target subtask with links
    sub1 = sub_dir / "01_target_task.md"
    sub1.write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: pending\nlinks:\n  - ../../references/references.md\n---\n# Target Task\nDo something.\n",
        encoding="utf-8",
    )

    # Create an unrelated subtask
    sub2 = sub_dir / "02_unrelated_task.md"
    sub2.write_text(
        "---\nid: sub_002\nversion: 1.0.0\nstatus: pending\n---\n# Unrelated Secret Task\nClassified info.\n",
        encoding="utf-8",
    )

    pkg = build_worker_context_package(sub1, project_root, ws_path)

    assert isinstance(pkg, WorkerContextPackage)
    assert pkg.subtask_id == "sub_001"
    assert "Do something." in pkg.subtask_content
    assert pkg.abb_location in {"local", "shadow"}
    assert "references.md" in "".join(pkg.linked_files.keys())

    rendered = pkg.render_prompt()
    assert "Target Task" in rendered
    # Must NOT leak unrelated subtask
    assert "Unrelated Secret Task" not in rendered
    assert "sub_002" not in rendered


def test_find_ready_subtasks_dag_dependency(tmp_path: Path):
    """Test finding ready subtasks whose dependencies are all done."""
    project_root = tmp_path / "proj_dag"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)

    # Task A is done
    (sub_dir / "01_task_a.md").write_text(
        "---\nid: sub_a\nversion: 1.0.0\nstatus: done\n---\n# Task A\n",
        encoding="utf-8",
    )

    # Task B depends on A (should be ready)
    (sub_dir / "02_task_b.md").write_text(
        "---\nid: sub_b\nversion: 1.0.0\nstatus: pending\ndepends_on:\n  - sub_a\n---\n# Task B\n",
        encoding="utf-8",
    )

    # Task C depends on B (B is pending, so C should NOT be ready)
    (sub_dir / "03_task_c.md").write_text(
        "---\nid: sub_c\nversion: 1.0.0\nstatus: pending\ndepends_on:\n  - sub_b\n---\n# Task C\n",
        encoding="utf-8",
    )

    ready = find_ready_subtasks(ws_path / "tasks")
    ready_ids = [p.name for p in ready]
    assert "02_task_b.md" in ready_ids
    assert "03_task_c.md" not in ready_ids


@pytest.mark.asyncio
async def test_concurrency_cap_max_3_workers(tmp_path: Path):
    """Phase 2 Concurrency Test: Dispatch 5 ready subtasks, assert <= 3 run concurrently."""
    project_root = tmp_path / "proj_concurrency"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)

    subtask_paths: list[Path] = []
    for i in range(1, 6):
        p = sub_dir / f"0{i}_task.md"
        p.write_text(
            f"---\nid: sub_00{i}\nversion: 1.0.0\nstatus: pending\n---\n# Task {i}\n",
            encoding="utf-8",
        )
        subtask_paths.append(p)

    coordinator = SubagentCoordinator(max_concurrent=3)
    assert coordinator.max_concurrent == MAX_CONCURRENT_WORKERS
    assert MAX_CONCURRENT_WORKERS == 3

    current_concurrent = 0
    max_observed_concurrent = 0

    async def mock_worker_runner(pkg: WorkerContextPackage):
        nonlocal current_concurrent, max_observed_concurrent
        current_concurrent += 1
        max_observed_concurrent = max(max_observed_concurrent, current_concurrent)
        await asyncio.sleep(0.05)  # Simulate worker work
        current_concurrent -= 1
        return {"subtask_id": pkg.subtask_id, "status": "completed"}

    results = await coordinator.dispatch_subtasks(
        project_root=project_root,
        subtask_paths=subtask_paths,
        worker_runner=mock_worker_runner,
    )

    assert len(results) == 5
    assert all(r["status"] == "completed" for r in results)
    assert max_observed_concurrent <= 3
    assert max_observed_concurrent >= 2  # Verify concurrency actually happened
