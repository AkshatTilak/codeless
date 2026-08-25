"""Tests for 4-mode operational switching and domain write boundary evaluation."""

from pathlib import Path

from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.config.settings import PermissionSettings
from codeless.permissions.checker import PermissionChecker
from codeless.permissions.modes import PermissionMode


def test_mode_engine_write_boundaries(tmp_path: Path):
    """Test ModeEngine boundary evaluation across modes."""
    engine = get_mode_engine()

    # 1. PLAN Mode
    engine.set_mode(TriMode.PLAN)
    # Allowed in PLAN (all ABB workspace specs, tasks, features, memory bank)
    ok, _ = engine.evaluate_write_permission("tasks/sub/01_task.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("design/architecture.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("features/auth/spec.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("references/db/models.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("STACK.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("CONVENTIONS.md", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("TODO.md", tmp_path)
    assert ok is True
    # Blocked in PLAN (external project source code)
    ok, reason = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert ok is False
    assert "Plan Mode blocks project code modifications" in reason

    # 2. ASK Mode
    engine.set_mode(TriMode.ASK)
    ok, _ = engine.evaluate_write_permission("references/db/models.md", tmp_path)
    assert ok is False
    ok, _ = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert ok is False

    # 4. AGENT Mode
    engine.set_mode(TriMode.AGENT)
    ok, _ = engine.evaluate_write_permission("src/main.py", tmp_path)
    assert ok is True
    ok, _ = engine.evaluate_write_permission("tasks/sub/01_task.md", tmp_path)
    assert ok is True


def test_permission_checker_with_mode_engine(tmp_path: Path):
    """Test that PermissionChecker respects ModeEngine in PLAN mode."""
    engine = get_mode_engine()
    settings = PermissionSettings(mode=PermissionMode.PLAN)
    checker = PermissionChecker(settings)

    # When in PLAN mode:
    engine.set_mode(TriMode.PLAN)
    # Writing to tasks and design should be allowed
    dec = checker.evaluate("write_file", is_read_only=False, file_path="tasks/sub/01.md")
    assert dec.allowed is True
    # Writing to references and STACK should be allowed in PLAN
    dec = checker.evaluate("write_file", is_read_only=False, file_path="references/db/models.md")
    assert dec.allowed is True
    dec = checker.evaluate("write_file", is_read_only=False, file_path="STACK.md")
    assert dec.allowed is True

    # Writing to src/main.py should be blocked
    dec = checker.evaluate("write_file", is_read_only=False, file_path="src/main.py")
    assert dec.allowed is False
    assert "Plan Mode blocks" in dec.reason

    # Mutating command without file (like bash) should be blocked in plan mode
    dec = checker.evaluate("bash", is_read_only=False, file_path=None, command="rm -rf /")
    assert dec.allowed is False

    # todo_write tool should be allowed in PLAN mode
    dec = checker.evaluate("todo_write", is_read_only=False, file_path="TODO.md")
    assert dec.allowed is True
    dec = checker.evaluate("todo_write", is_read_only=False, file_path=None)
    assert dec.allowed is True


def test_ui_state_payload_reflects_mode():
    """Test that UI state payload reflects the active operational mode from ModeEngine."""
    from codeless.abb.permissions import TriMode, get_mode_engine
    from codeless.state.app_state import AppState
    from codeless.ui.protocol import _state_payload

    engine = get_mode_engine()
    state = AppState(model="gpt-5.4", theme="dark", permission_mode="plan")

    engine.set_mode(TriMode.PLAN)
    payload = _state_payload(state)
    assert payload["mode"] == "PLAN"
    assert payload["permission_mode"] == "PLAN"

    engine.set_mode(TriMode.AGENT)
    payload = _state_payload(state)
    assert payload["mode"] == "AGENT"
    assert payload["permission_mode"] == "AGENT"

