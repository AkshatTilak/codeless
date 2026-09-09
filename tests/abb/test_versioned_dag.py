"""Tests for Versioned Task Hierarchy (Folder-Wise Base, Goal, Sub) and Numbered Base Tasks."""

from pathlib import Path

from codeless.abb.hooks.dag_guard import check_dag_dependencies, index_tasks
from codeless.abb.hooks.frontmatter import dump_with_frontmatter, parse_frontmatter
from codeless.abb.hooks.rollup import rollup_task_completion
from codeless.abb.verification import get_dag_snapshot
from codeless.coordinator.workers import find_ready_subtasks


def setup_versioned_workspace(tasks_dir: Path):
    """Create a mock multi-version tasks workspace (v1 and v2)."""
    # Version 1
    v1_goal_dir = tasks_dir / "v1" / "goal"
    v1_base_dir = tasks_dir / "v1" / "base"
    v1_sub_dir = tasks_dir / "v1" / "sub"
    v1_goal_dir.mkdir(parents=True, exist_ok=True)
    v1_base_dir.mkdir(parents=True, exist_ok=True)
    v1_sub_dir.mkdir(parents=True, exist_ok=True)

    # v1 Goal
    v1_goal = v1_goal_dir / "goal.md"
    v1_goal.write_text(
        dump_with_frontmatter(
            {"id": "goal_001", "version": "1.0.0", "status": "in_progress", "depends_on": []},
            "# Goal 001\n\n- [ ] `../base/01_foundation.md`\n",
        ),
        encoding="utf-8",
    )

    # v1 Base
    v1_base = v1_base_dir / "01_foundation.md"
    v1_base.write_text(
        dump_with_frontmatter(
            {
                "id": "base_001",
                "version": "1.0.0",
                "status": "pending",
                "parent": "goal_001",
                "depends_on": [],
            },
            "# Base 001\n\n- [ ] `../sub/01_subtask_a.md`\n- [ ] `../sub/02_subtask_b.md`\n",
        ),
        encoding="utf-8",
    )

    # v1 Sub 1
    v1_sub1 = v1_sub_dir / "01_subtask_a.md"
    v1_sub1.write_text(
        dump_with_frontmatter(
            {
                "id": "sub_001",
                "version": "1.0.0",
                "status": "pending",
                "parent": "base_001",
                "depends_on": [],
            },
            "# Subtask 1\n",
        ),
        encoding="utf-8",
    )

    # v1 Sub 2 (depends on sub_001)
    v1_sub2 = v1_sub_dir / "02_subtask_b.md"
    v1_sub2.write_text(
        dump_with_frontmatter(
            {
                "id": "sub_002",
                "version": "1.0.0",
                "status": "pending",
                "parent": "base_001",
                "depends_on": ["sub_001"],
            },
            "# Subtask 2\n",
        ),
        encoding="utf-8",
    )

    # Version 2
    v2_goal_dir = tasks_dir / "v2" / "goal"
    v2_base_dir = tasks_dir / "v2" / "base"
    v2_sub_dir = tasks_dir / "v2" / "sub"
    v2_goal_dir.mkdir(parents=True, exist_ok=True)
    v2_base_dir.mkdir(parents=True, exist_ok=True)
    v2_sub_dir.mkdir(parents=True, exist_ok=True)

    # v2 Goal
    v2_goal = v2_goal_dir / "goal.md"
    v2_goal.write_text(
        dump_with_frontmatter(
            {"id": "goal_002", "version": "2.0.0", "status": "not_started", "depends_on": []},
            "# Goal 002\n\n- [ ] `../base/01_swarm_scaling.md`\n",
        ),
        encoding="utf-8",
    )

    # v2 Base
    v2_base = v2_base_dir / "01_swarm_scaling.md"
    v2_base.write_text(
        dump_with_frontmatter(
            {
                "id": "base_002",
                "version": "1.0.0",
                "status": "pending",
                "parent": "goal_002",
                "depends_on": ["base_001"],
            },
            "# Base 002\n\n- [ ] `../sub/01_worker_pool.md`\n",
        ),
        encoding="utf-8",
    )

    # v2 Sub 1
    v2_sub1 = v2_sub_dir / "01_worker_pool.md"
    v2_sub1.write_text(
        dump_with_frontmatter(
            {
                "id": "sub_003",
                "version": "1.0.0",
                "status": "pending",
                "parent": "base_002",
                "depends_on": [],
            },
            "# Subtask 3\n",
        ),
        encoding="utf-8",
    )


def test_versioned_task_indexing(tmp_path):
    tasks_dir = tmp_path / "tasks"
    setup_versioned_workspace(tasks_dir)

    index = index_tasks(tasks_dir)

    # Indexed by task ID
    assert "goal_001" in index
    assert "base_001" in index
    assert "sub_001" in index
    assert "sub_002" in index
    assert "goal_002" in index
    assert "base_002" in index
    assert "sub_003" in index

    # Indexed by versioned path
    assert "v1/sub/01_subtask_a.md" in index
    assert "v2/base/01_swarm_scaling.md" in index

    # Indexed by filename
    assert "01_subtask_a.md" in index
    assert "01_swarm_scaling.md" in index

    # Version folder metadata
    _, sub1_fm = index["sub_001"]
    assert sub1_fm.get("_version_folder") == "v1"
    _, base2_fm = index["base_002"]
    assert base2_fm.get("_version_folder") == "v2"


def test_versioned_dependency_gating(tmp_path):
    tasks_dir = tmp_path / "tasks"
    setup_versioned_workspace(tasks_dir)

    # sub_002 depends on sub_001 (which is pending)
    allowed, reason = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert not allowed
    assert "Unsatisfied dependencies" in reason

    # Complete sub_001
    sub1_path = tasks_dir / "v1" / "sub" / "01_subtask_a.md"
    sub1_fm, sub1_body = parse_frontmatter(sub1_path.read_text(encoding="utf-8"))
    sub1_fm["status"] = "done"
    sub1_path.write_text(dump_with_frontmatter(sub1_fm, sub1_body), encoding="utf-8")

    # Now sub_002 should be unblocked
    allowed, _ = check_dag_dependencies("sub_002", ["sub_001"], "in_progress", tasks_dir)
    assert allowed


def test_versioned_rollup_isolation(tmp_path):
    tasks_dir = tmp_path / "tasks"
    setup_versioned_workspace(tasks_dir)

    sub1_path = tasks_dir / "v1" / "sub" / "01_subtask_a.md"
    sub2_path = tasks_dir / "v1" / "sub" / "02_subtask_b.md"
    base1_path = tasks_dir / "v1" / "base" / "01_foundation.md"
    goal1_path = tasks_dir / "v1" / "goal" / "goal.md"

    base2_path = tasks_dir / "v2" / "base" / "01_swarm_scaling.md"
    goal2_path = tasks_dir / "v2" / "goal" / "goal.md"

    # Complete subtask 1 in v1
    fm1, body1 = parse_frontmatter(sub1_path.read_text(encoding="utf-8"))
    fm1["status"] = "done"
    sub1_path.write_text(dump_with_frontmatter(fm1, body1), encoding="utf-8")

    actions1 = rollup_task_completion(sub1_path, tasks_dir)
    assert any("Checked off `01_subtask_a.md`" in a for a in actions1)

    # Base 1 is not done yet (subtask 2 is pending)
    base1_fm, base1_body = parse_frontmatter(base1_path.read_text(encoding="utf-8"))
    assert base1_fm["status"] == "pending"
    assert "- [x] `../sub/01_subtask_a.md`" in base1_body

    # Complete subtask 2 in v1
    fm2, body2 = parse_frontmatter(sub2_path.read_text(encoding="utf-8"))
    fm2["status"] = "done"
    sub2_path.write_text(dump_with_frontmatter(fm2, body2), encoding="utf-8")

    actions2 = rollup_task_completion(sub2_path, tasks_dir)
    assert any("Marked base task `01_foundation.md` as `status: done`" in a for a in actions2)
    assert any("Marked system goal `goal.md` as `status: done`" in a for a in actions2)

    # Verify v1 is done
    v1_goal_fm, v1_goal_body = parse_frontmatter(goal1_path.read_text(encoding="utf-8"))
    assert v1_goal_fm["status"] == "done"
    assert "- [x] `../base/01_foundation.md`" in v1_goal_body

    # Verify v2 is completely untouched!
    v2_base_fm, _ = parse_frontmatter(base2_path.read_text(encoding="utf-8"))
    v2_goal_fm, _ = parse_frontmatter(goal2_path.read_text(encoding="utf-8"))
    assert v2_base_fm["status"] == "pending"
    assert v2_goal_fm["status"] == "not_started"


def test_get_dag_snapshot_versioned(tmp_path):
    tasks_dir = tmp_path / "tasks"
    setup_versioned_workspace(tasks_dir)

    snapshot = get_dag_snapshot(tmp_path)

    # Active goal is goal_001 (in_progress)
    assert snapshot["goal"] is not None
    assert snapshot["goal"]["id"] == "goal_001"

    # Both goals tracked
    assert len(snapshot["goals"]) == 2
    goal_ids = {g["id"] for g in snapshot["goals"]}
    assert goal_ids == {"goal_001", "goal_002"}

    # Base tasks across versions
    assert len(snapshot["base_tasks"]) == 2
    base_versions = {b.get("_version_folder") for b in snapshot["base_tasks"]}
    assert base_versions == {"v1", "v2"}

    # Subtasks across versions
    assert len(snapshot["subtasks"]) == 3
    sub_versions = {s.get("_version_folder") for s in snapshot["subtasks"]}
    assert sub_versions == {"v1", "v2"}


def test_find_ready_subtasks_versioned(tmp_path):
    tasks_dir = tmp_path / "tasks"
    setup_versioned_workspace(tasks_dir)

    # Initially, sub_001 (v1) and sub_003 (v2) have no dependencies and are pending
    ready = find_ready_subtasks(tasks_dir)
    ready_names = {p.name for p in ready}
    assert "01_subtask_a.md" in ready_names
    assert "01_worker_pool.md" in ready_names
    # 02_subtask_b depends on sub_001, so it is not ready
    assert "02_subtask_b.md" not in ready_names


def test_backward_compatibility_flat_layout(tmp_path):
    """Verify that legacy flat tasks/ layout still functions completely."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "goal").mkdir(parents=True)
    (tasks_dir / "base").mkdir(parents=True)
    (tasks_dir / "sub").mkdir(parents=True)

    goal_file = tasks_dir / "goal" / "goal.md"
    goal_file.write_text(
        dump_with_frontmatter(
            {"id": "goal_001", "version": "1.0.0", "status": "in_progress", "depends_on": []},
            "# Flat Goal\n\n- [ ] `base/01_base.md`\n",
        ),
        encoding="utf-8",
    )

    base_file = tasks_dir / "base" / "01_base.md"
    base_file.write_text(
        dump_with_frontmatter(
            {
                "id": "base_001",
                "version": "1.0.0",
                "status": "pending",
                "parent": "goal_001",
                "depends_on": [],
            },
            "# Flat Base\n\n- [ ] `sub/01_sub.md`\n",
        ),
        encoding="utf-8",
    )

    sub_file = tasks_dir / "sub" / "01_sub.md"
    sub_file.write_text(
        dump_with_frontmatter(
            {
                "id": "sub_001",
                "version": "1.0.0",
                "status": "done",
                "parent": "base_001",
                "depends_on": [],
            },
            "# Flat Sub\n",
        ),
        encoding="utf-8",
    )

    # Indexing
    index = index_tasks(tasks_dir)
    assert "sub_001" in index
    assert "base_001" in index
    assert "goal_001" in index

    # Roll-up
    actions = rollup_task_completion(sub_file, tasks_dir)
    assert any("Checked off `01_sub.md`" in a for a in actions)
    assert any("Marked base task `01_base.md` as `status: done`" in a for a in actions)
    assert any("Marked system goal `goal.md` as `status: done`" in a for a in actions)

    # Snapshot
    snapshot = get_dag_snapshot(tmp_path)
    assert snapshot["goal"]["status"] == "done"
    assert len(snapshot["base_tasks"]) == 1
    assert len(snapshot["subtasks"]) == 1
