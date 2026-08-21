"""Tests for Tri-Mode permissions controller, path rules, and persona injection."""

from pathlib import Path

from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.permissions import ModeEngine, TriMode, get_mode_engine
from codeless.permissions.modes import PermissionMode


def test_mode_engine_initial_state():
    engine = ModeEngine(default_mode=TriMode.AGENT)
    assert engine.current_mode == TriMode.AGENT
    assert engine.get_upstream_permission_mode() == PermissionMode.DEFAULT


def test_mode_engine_mode_switch():
    engine = ModeEngine()

    engine.set_mode("plan")
    assert engine.current_mode == TriMode.PLAN
    assert engine.get_upstream_permission_mode() == PermissionMode.PLAN

    engine.set_mode("ask")
    assert engine.current_mode == TriMode.ASK
    assert engine.get_upstream_permission_mode() == PermissionMode.PLAN

    engine.set_mode("agent")
    assert engine.current_mode == TriMode.AGENT
    assert engine.get_upstream_permission_mode() == PermissionMode.DEFAULT


def test_plan_mode_path_rules(tmp_path: Path):
    engine = ModeEngine(default_mode=TriMode.PLAN)

    # Shadow architecture paths allowed in Plan mode
    allowed, _ = engine.evaluate_write_permission("tasks/sub/01_test.md", tmp_path)
    assert allowed

    allowed, _ = engine.evaluate_write_permission("design/system/architecture.md", tmp_path)
    assert allowed

    # Feature specs are LLD design artifacts — allowed in Plan mode
    allowed, _ = engine.evaluate_write_permission("features/auth/spec.md", tmp_path)
    assert allowed

    # Meta-specs belong to Governance mode, not Plan mode
    allowed, reason = engine.evaluate_write_permission("STACK.md", tmp_path)
    assert not allowed
    assert "Plan Mode blocks meta-spec writes" in reason

    # Root project source files blocked in Plan mode
    allowed, reason = engine.evaluate_write_permission("src/codeless/main.py", tmp_path)
    assert not allowed
    assert "Plan Mode blocks project code modifications" in reason

    allowed, reason = engine.evaluate_write_permission("tests/test_app.py", tmp_path)
    assert not allowed


def test_ask_mode_path_rules(tmp_path: Path):
    engine = ModeEngine(default_mode=TriMode.ASK)

    # Ask mode blocks ALL writes
    allowed, reason = engine.evaluate_write_permission("src/codeless/main.py", tmp_path)
    assert not allowed
    assert "strictly read-only" in reason

    allowed, reason = engine.evaluate_write_permission("tasks/sub/01_test.md", tmp_path)
    assert not allowed


def test_agent_mode_path_rules(tmp_path: Path):
    engine = ModeEngine(default_mode=TriMode.AGENT)

    # Agent mode allows project writes
    allowed, _ = engine.evaluate_write_permission("src/codeless/main.py", tmp_path)
    assert allowed

    allowed, _ = engine.evaluate_write_permission("tasks/sub/01_test.md", tmp_path)
    assert allowed


def test_persona_instructions_loading(tmp_path: Path):
    abb_ws = tmp_path / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# Base Agent Persona", encoding="utf-8")
    (abb_ws / "workflows" / "planning").mkdir(parents=True)
    (abb_ws / "workflows" / "planning" / "planning.md").write_text(
        "# Planning Workflow", encoding="utf-8"
    )
    (abb_ws / "references").mkdir(parents=True)
    (abb_ws / "references" / "references.md").write_text("# Reference Index", encoding="utf-8")

    engine = ModeEngine()

    engine.set_mode(TriMode.PLAN)
    plan_persona = engine.get_persona_instructions(tmp_path)
    assert "Architecture & Planning Mode" in plan_persona
    assert "Base Agent Persona" in plan_persona

    engine.set_mode(TriMode.ASK)
    ask_persona = engine.get_persona_instructions(tmp_path)
    assert "Knowledge Query & Memory Bank" in ask_persona
    assert "Reference Index" in ask_persona


def test_pre_tool_use_abb_guard_mode_enforcement(tmp_path: Path):
    global_engine = get_mode_engine()

    # 1. Switch to PLAN mode
    global_engine.set_mode(TriMode.PLAN)
    allowed, reason = pre_tool_use_abb_guard(
        "write_file", {"path": "src/app.py", "content": "print()"}, tmp_path
    )
    assert not allowed
    assert "Plan Mode blocks project code modifications" in reason

    # 2. Switch to AGENT mode
    global_engine.set_mode(TriMode.AGENT)
    allowed, _ = pre_tool_use_abb_guard(
        "write_file", {"path": "src/app.py", "content": "print()"}, tmp_path
    )
    assert allowed

    # 3. Switch to ASK mode
    global_engine.set_mode(TriMode.ASK)
    allowed, reason = pre_tool_use_abb_guard(
        "write_file", {"path": "src/app.py", "content": "print()"}, tmp_path
    )
    assert not allowed
    assert "strictly read-only" in reason

    # Reset to default AGENT
    global_engine.set_mode(TriMode.AGENT)
