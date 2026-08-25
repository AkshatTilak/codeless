"""Tests for five-mode tool provisioning and domain write boundaries."""

from __future__ import annotations

from pathlib import Path

from codeless.abb.permissions import ModeEngine, TriMode


def test_five_modes_allowed_tools():
    engine = ModeEngine()

    # ASK mode: strictly read-only tools
    engine.set_mode(TriMode.ASK)
    ask_tools = engine.get_allowed_tools()
    assert "read_file" in ask_tools
    assert "grep" in ask_tools
    assert "abb_task" in ask_tools
    assert "write_file" not in ask_tools
    assert "edit_file" not in ask_tools

    # PLAN mode: read-only + planning tools
    engine.set_mode(TriMode.PLAN)
    plan_tools = engine.get_allowed_tools()
    assert "read_file" in plan_tools
    assert "todo_write" in plan_tools
    assert "abb_task" in plan_tools
    assert "abb_verify" in plan_tools

    # AGENT mode: all tools allowed
    engine.set_mode(TriMode.AGENT)
    agent_tools = engine.get_allowed_tools()
    assert "bash" in agent_tools
    assert "write_file" in agent_tools
    assert "agent" in agent_tools

    # CODEBASE mode: codebase exploration & memory queries (read-only)
    engine.set_mode(TriMode.CODEBASE)
    cb_tools = engine.get_allowed_tools()
    assert "read_file" in cb_tools
    assert "grep" in cb_tools
    assert "write_file" not in cb_tools
    assert "edit_file" not in cb_tools




def test_domain_write_boundaries(tmp_path: Path):
    engine = ModeEngine()
    abb_ws = tmp_path / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)

    # 1. ASK mode blocks all writes
    engine.set_mode(TriMode.ASK)
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "strictly read-only" in reason.lower()

    # 2. PLAN mode allows full ABB workspace (tasks, design, features, STACK.md, references)
    engine.set_mode(TriMode.PLAN)
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
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "plan mode blocks" in reason.lower()

    # 3. CODEBASE mode is strictly read-only codebase exploration
    engine.set_mode(TriMode.CODEBASE)
    allowed, reason = engine.evaluate_write_permission(tmp_path / "src" / "main.py", tmp_path)
    assert not allowed
    assert "strictly read-only" in reason.lower()
