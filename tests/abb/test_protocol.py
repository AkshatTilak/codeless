"""Tests for ABB UI protocol models and backend events (C12)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from codeless.ui.protocol import (
    AbbDagSnapshotPayload,
    AbbModePayload,
    AbbTaskPayload,
    AbbVerificationPayload,
    AbbWorkflowPayload,
    BackendEvent,
)


def test_abb_task_payload_serialization():
    task = AbbTaskPayload(
        id="sub_013",
        title="Ink TUI ABB Panels",
        status="in_progress",
        parent="base_002",
        complexity="Medium",
        depends_on=["sub_012", "sub_004"],
        dependencies_satisfied=True,
    )
    assert task.id == "sub_013"
    assert task.status == "in_progress"
    assert len(task.depends_on) == 2


def test_abb_dag_snapshot_event():
    snapshot = AbbDagSnapshotPayload(
        goal={"id": "goal_001", "status": "in_progress"},
        base_tasks=[
            AbbTaskPayload(id="base_001", status="done"),
            AbbTaskPayload(id="base_002", status="in_progress"),
        ],
        subtasks=[
            AbbTaskPayload(id="sub_012", status="done", parent="base_002"),
            AbbTaskPayload(id="sub_013", status="in_progress", parent="base_002"),
        ],
        active_subtask_id="sub_013",
    )
    event = BackendEvent.abb_dag_snapshot(snapshot)
    assert event.type == "abb_dag_snapshot"
    assert event.abb_dag is not None
    assert len(event.abb_dag.base_tasks) == 2
    assert event.abb_dag.active_subtask_id == "sub_013"

    # JSON roundtrip
    serialized = event.model_dump_json()
    data = json.loads(serialized)
    assert data["type"] == "abb_dag_snapshot"
    assert data["abb_dag"]["active_subtask_id"] == "sub_013"


def test_abb_workflow_event():
    event = BackendEvent.abb_active_workflow(
        workflow_id="planning",
        title="Planning Workflow",
        path="workflows/planning/planning.md",
    )
    assert event.type == "abb_active_workflow"
    assert event.abb_workflow is not None
    assert event.abb_workflow.workflow_id == "planning"
    assert event.abb_workflow.path == "workflows/planning/planning.md"


def test_abb_verification_progress_event():
    event = BackendEvent.abb_verification_progress(
        subtask_id="sub_013",
        track=1,
        command="uv run pytest -q",
        status="passed",
        output="1063 passed",
    )
    assert event.type == "abb_verification_progress"
    assert event.abb_verification is not None
    assert event.abb_verification.track == 1
    assert event.abb_verification.status == "passed"


def test_abb_mode_change_event():
    event = BackendEvent.abb_mode_change(
        mode="plan",
        allowed_tools=["view_file", "list_dir", "grep_search"],
        path_rules={"tasks/": "shadow", "src/": "read_only"},
    )
    assert event.type == "abb_mode_change"
    assert event.abb_mode is not None
    assert event.abb_mode.mode == "plan"
    assert "view_file" in event.abb_mode.allowed_tools
