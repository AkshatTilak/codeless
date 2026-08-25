"""Phase 2 End-to-End Verification Suite (v0.5.0 / v1.1.0 Exit Criteria).

Verifies:
1. Skill Bridge & Pull-Adapt-Delete Lifecycle (A4 YAML index + staging hook).
2. Drift Auditor & Feedback Loop Engine (/drift detecting schema discrepancy).
3. Subagent Worker Concurrency Cap (5 ready subtasks -> max 3 concurrent).
4. Workspace Location & Migration Engine (local -> .gitignore -> shadow migration).
5. Git Checkpoint & Rollback Engine (code + ABB synchronized restoration).
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from codeless.abb.checkpoints import create_checkpoint, restore_checkpoint
from codeless.abb.drift import feed_drift_to_issues, run_drift_audit
from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.shadow import (
    bootstrap_workspace,
    migrate_abb_workspace,
    resolve_abb_workspace,
)
from codeless.coordinator.workers import (
    MAX_CONCURRENT_WORKERS,
    SubagentCoordinator,
    WorkerContextPackage,
    find_ready_subtasks,
)
from codeless.skills.loader import load_abb_skills


def _init_git_repo(path: Path):
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestUser"], cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    readme = path / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True, check=True
    )


def test_e2e_item_1_skill_bridge_and_staging_lifecycle(tmp_path: Path):
    """E2E 1: Skill import -> _staging/ -> adapt -> register in YAML index -> _staging/ purged."""
    project_root = tmp_path / "e2e_skills"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Step 1: Pull external skill into _staging/
    staging_dir = ws_path / "skills" / "_staging" / "remote_skill"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "external_source.md").write_text(
        "# Remote Skill Raw\nInstructions", encoding="utf-8"
    )

    # Attempting to edit skills.md while _staging has unpurged artifacts is blocked by hook
    allowed, reason = pre_tool_use_abb_guard(
        tool_name="write_file",
        arguments={"path": "skills/skills.md", "content": "# Index"},
        cwd=project_root,
    )
    assert allowed is False
    assert "ABB Skill Staging Blocked" in reason

    # Step 2: Adapt to proper domain folder
    adapted_dir = ws_path / "skills" / "qa" / "remote_adapter"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    (adapted_dir / "SKILL.md").write_text(
        "---\nid: qa_remote_adapter\nversion: 1.0.0\n---\n# Adapted Remote Skill\nClean steps.\n",
        encoding="utf-8",
    )

    # Step 3: Purge staging directory
    for f in (ws_path / "skills" / "_staging").rglob("*"):
        if f.is_file():
            f.unlink()

    # Step 4: Register in skills.md with YAML index
    skills_md = ws_path / "skills" / "skills.md"
    skills_md_content = """---
version: 2.0.0
id: skills
---
# Skills
## 3. Index
| Skill | Path | Purpose |
|---|---|---|
| Remote Adapter | qa/remote_adapter/SKILL.md | Adapted skill |

```yaml
skills:
  - name: qa_remote_adapter
    path: qa/remote_adapter/SKILL.md
    description: Adapted remote skill
    version: 1.0.0
    aliases: ["qa/remote_adapter"]
```
"""
    skills_md.write_text(skills_md_content, encoding="utf-8")

    # Verify write is now allowed
    allowed, reason = pre_tool_use_abb_guard(
        tool_name="write_file",
        arguments={"path": "skills/skills.md", "content": skills_md_content},
        cwd=project_root,
    )
    assert allowed is True

    # Verify skill loader picks up adapted skill
    loaded = load_abb_skills(project_root)
    names = [s.name for s in loaded]
    assert "qa_remote_adapter" in names


def test_e2e_item_2_drift_audit_and_feedback_loop(tmp_path: Path):
    """E2E 2: Drift: manual schema discrepancy -> /drift report detects delta -> logged to issues."""
    project_root = tmp_path / "e2e_drift"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Ingest schema discrepancy
    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    bad_sub = sub_dir / "99_discrepancy_task.md"
    bad_sub.write_text(
        "---\nversion: 1.0.0\nstatus: invalid_status\n---\n# Discrepancy\n", encoding="utf-8"
    )

    report = run_drift_audit(project_root)
    assert report.clean is False
    assert any("99_discrepancy_task.md" in issue.file_path for issue in report.issues)

    issues_doc = feed_drift_to_issues(project_root, report)
    assert issues_doc is not None
    assert issues_doc.exists()
    assert "99_discrepancy_task.md" in issues_doc.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_e2e_item_3_subagent_worker_concurrency_cap(tmp_path: Path):
    """E2E 3: Subagent concurrency: 5 ready subtasks -> strictly <= 3 concurrent workers."""
    project_root = tmp_path / "e2e_concurrency"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    sub_dir = ws_path / "tasks" / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)

    tasks_to_run: list[Path] = []
    for i in range(1, 6):
        t = sub_dir / f"0{i}_ready_task.md"
        t.write_text(
            f"---\nid: sub_00{i}\nversion: 1.0.0\nstatus: pending\n---\n# Task {i}\n",
            encoding="utf-8",
        )
        tasks_to_run.append(t)

    ready = find_ready_subtasks(ws_path / "tasks")
    assert len(ready) == 5

    coordinator = SubagentCoordinator(max_concurrent=MAX_CONCURRENT_WORKERS)
    assert MAX_CONCURRENT_WORKERS == 3

    current = 0
    max_concurrent_seen = 0

    async def worker_job(pkg: WorkerContextPackage):
        nonlocal current, max_concurrent_seen
        current += 1
        max_concurrent_seen = max(max_concurrent_seen, current)
        await asyncio.sleep(0.04)
        current -= 1
        return {"subtask_id": pkg.subtask_id, "status": "completed"}

    results = await coordinator.dispatch_subtasks(project_root, tasks_to_run, worker_job)
    assert len(results) == 5
    assert max_concurrent_seen <= 3
    assert max_concurrent_seen >= 2


def test_e2e_item_4_workspace_location_migration_and_gitignore(tmp_path: Path):
    """E2E 4: Workspace Location & Migration: local + .gitignore -> shadow migration with zero data loss."""
    project_root = tmp_path / "e2e_location"
    project_root.mkdir()
    _init_git_repo(project_root)

    # Initialize local workspace
    ws_path, is_new = bootstrap_workspace(project_root, location="local")
    assert ws_path.exists()
    assert (project_root / ".gitignore").exists()
    assert ".codeless/" in (project_root / ".gitignore").read_text(encoding="utf-8")

    # Add a custom task in local workspace
    custom_task = ws_path / "tasks" / "sub" / "88_custom.md"
    custom_task.parent.mkdir(parents=True, exist_ok=True)
    custom_task.write_text(
        "---\nid: sub_088\nversion: 1.0.0\nstatus: pending\n---\n# Custom Task\n", encoding="utf-8"
    )

    # Migrate from local to shadow
    source_ws, dest_ws = migrate_abb_workspace(project_root, target_location="shadow", force=True)
    assert dest_ws.exists()

    # Verify custom task transferred cleanly to shadow
    shadow_custom_task = dest_ws / "tasks" / "sub" / "88_custom.md"
    assert shadow_custom_task.exists()
    assert "sub_088" in shadow_custom_task.read_text(encoding="utf-8")

    # Verify resolver defaults to shadow
    resolved = resolve_abb_workspace(project_root, auto_init=False)
    assert resolved.resolve() == dest_ws.resolve()


def test_e2e_item_5_checkpoint_rollback_roundtrip(tmp_path: Path):
    """E2E 5: Checkpoint save/restore roundtrips a coherent code + task pair."""
    project_root = tmp_path / "e2e_cp"
    project_root.mkdir()
    _init_git_repo(project_root)
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    # Base state
    src_file = project_root / "calculator.py"
    src_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    sub_file = ws_path / "tasks" / "sub" / "01_math.md"
    sub_file.parent.mkdir(parents=True, exist_ok=True)
    sub_file.write_text(
        "---\nid: sub_math\nversion: 1.0.0\nstatus: pending\n---\n# Math Task\n", encoding="utf-8"
    )

    cp = create_checkpoint(project_root, name="clean_state")

    # Mutate both code and task
    src_file.write_text("def add(a, b): return 0 # Broken\n", encoding="utf-8")
    sub_file.write_text(
        "---\nid: sub_math\nversion: 1.0.0\nstatus: done\n---\n# Math Task\n", encoding="utf-8"
    )

    # Restore checkpoint
    ok, msg = restore_checkpoint(project_root, cp.checkpoint_id, force=True)
    assert ok is True

    # Assert both codebase and ABB state reverted perfectly
    assert "return a + b" in src_file.read_text(encoding="utf-8")
    assert "status: pending" in sub_file.read_text(encoding="utf-8")
