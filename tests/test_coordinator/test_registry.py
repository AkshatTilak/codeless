"""Tests verifying that removed legacy tools and registries are properly purged."""

from codeless.tools import create_default_tool_registry


def test_removed_tools_not_in_registry():
    registry = create_default_tool_registry()
    tool_names = set(registry._tools.keys())

    # Verify conflicting plan mode tools removed
    assert "enter_plan_mode" not in tool_names
    assert "exit_plan_mode" not in tool_names

    # Verify team tools removed
    assert "team_create" not in tool_names
    assert "team_delete" not in tool_names

    # Verify ABB tools added
    assert "abb_task" in tool_names
    assert "abb_verify" in tool_names
