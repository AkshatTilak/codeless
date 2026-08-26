"""Tests for five-mode tool provisioning and domain write boundaries."""

from __future__ import annotations

from pathlib import Path

from codeless.abb.permissions import ModeEngine, TriMode


def test_five_modes_allowed_tools():
    engine = ModeEngine()

    # ASK mode: strictly read-only tools
    engine.set_mode(TriMode.ASK)
    ask_tools = engine.get_allowed_tools()
    assert "file" in ask_tools
    assert "grep" in ask_tools
    assert "abb" in ask_tools
    assert "bash" not in ask_tools
    assert "agent" not in ask_tools

    # PLAN mode: read-only + planning tools
    engine.set_mode(TriMode.PLAN)
    plan_tools = engine.get_allowed_tools()
    assert "file" in plan_tools
    assert "todo_write" in plan_tools
    assert "abb" in plan_tools
    assert "bash" not in plan_tools
    assert "agent" not in plan_tools

    # AGENT mode: all tools allowed
    engine.set_mode(TriMode.AGENT)
    agent_tools = engine.get_allowed_tools()
    assert "bash" in agent_tools
    assert "file" in agent_tools
    assert "agent" in agent_tools

    # CODEBASE mode: codebase exploration & memory queries (read-only)
    engine.set_mode(TriMode.CODEBASE)
    cb_tools = engine.get_allowed_tools()
    assert "file" in cb_tools
    assert "grep" in cb_tools
    assert "bash" not in cb_tools
    assert "agent" not in cb_tools


def test_domain_write_boundaries(tmp_path: Path):
    engine = ModeEngine()
    abb_ws = tmp_path / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)

    # 1. ASK mode blocks all writes
    engine.set_mode(TriMode.ASK)
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "strictly read-only" in reason.lower()
    allowed, _ = engine.evaluate_write_permission("STACK.md", tmp_path)
    assert not allowed

    # 2. PLAN mode allows full ABB workspace (tasks, design, features, STACK.md, references)
    engine.set_mode(TriMode.PLAN)
    # Inside local .codeless/abb_workspace
    allowed, _ = engine.evaluate_write_permission(abb_ws / "tasks" / "sub" / "01.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission(abb_ws / "design" / "arch.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission(abb_ws / "STACK.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission(
        abb_ws / "workflows" / "planning" / "planning.md", tmp_path
    )
    assert allowed

    # Virtual / relative ABB files
    allowed, _ = engine.evaluate_write_permission("STACK.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("stack.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("agent.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("CHANGELOG.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("tasks/goal/goal.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("features/auth_rbac/spec.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission("references/references.md", tmp_path)
    assert allowed

    # Absolute project paths to ABB files
    allowed, _ = engine.evaluate_write_permission(tmp_path / "STACK.md", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission(tmp_path / "tasks" / "tasks.md", tmp_path)
    assert allowed

    # External project code blocked in PLAN mode
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "plan mode blocks" in reason.lower()
    allowed, reason = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert not allowed
    assert "plan mode blocks" in reason.lower()

    # 3. CODEBASE mode is strictly read-only codebase exploration
    engine.set_mode(TriMode.CODEBASE)
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "strictly read-only" in reason.lower()

    # 4. AGENT mode allows writes to project code and ABB
    engine.set_mode(TriMode.AGENT)
    allowed, _ = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert allowed
    allowed, _ = engine.evaluate_write_permission(tmp_path / "STACK.md", tmp_path)
    assert allowed


def test_permission_checker_plan_mode_abb_file_writes(tmp_path: Path):
    from codeless.abb.permissions import get_mode_engine
    from codeless.config.settings import PermissionSettings
    from codeless.permissions.checker import PermissionChecker
    from codeless.permissions.modes import PermissionMode

    mode_engine = get_mode_engine()
    mode_engine.set_mode(TriMode.PLAN)

    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.PLAN))

    # STACK.md write allowed in PLAN mode
    decision = checker.evaluate(
        "file",
        is_read_only=False,
        file_path=str(tmp_path / "STACK.md"),
    )
    assert decision.allowed is True

    # Virtual STACK.md write allowed in PLAN mode
    decision = checker.evaluate(
        "file",
        is_read_only=False,
        file_path="STACK.md",
    )
    assert decision.allowed is True

    # Task file write allowed in PLAN mode
    decision = checker.evaluate(
        "file",
        is_read_only=False,
        file_path=str(tmp_path / "tasks" / "sub" / "45_file_tool.md"),
    )
    assert decision.allowed is True

    # Project code write BLOCKED in PLAN mode
    decision = checker.evaluate(
        "file",
        is_read_only=False,
        file_path=str(tmp_path / "src" / "main.py"),
    )
    assert decision.allowed is False
    assert "plan mode blocks" in decision.reason.lower()

    # Project code read ALLOWED in PLAN mode
    decision = checker.evaluate(
        "file",
        is_read_only=True,
        file_path=str(tmp_path / "src" / "main.py"),
    )
    assert decision.allowed is True
