"""Tests for ABB Slash Command Pack registration and execution."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from codeless.commands.registry import CommandContext, create_default_command_registry


@pytest.fixture
def mock_context(tmp_path: Path) -> CommandContext:
    # Create minimal ABB workspace structure in tmp_path
    dev_abb = tmp_path / ".codeless" / "abb_workspace"
    (dev_abb / "tasks" / "goal").mkdir(parents=True)
    (dev_abb / "tasks" / "base").mkdir(parents=True)
    (dev_abb / "tasks" / "sub").mkdir(parents=True)
    (dev_abb / "skills" / "qa" / "backend").mkdir(parents=True)
    (dev_abb / "features" / "test_feature").mkdir(parents=True)
    (dev_abb / "references" / "code").mkdir(parents=True)

    (dev_abb / "agent.md").write_text("# Base Architect Persona\n", encoding="utf-8")
    (dev_abb / "STACK.md").write_text(
        "---\nversion: 1.0.0\nid: stack\nverification:\n  track_1: [python -c 'pass']\n---\n# STACK",
        encoding="utf-8",
    )
    (dev_abb / "USER_PREFERENCES.md").write_text(
        "# USER PREFERENCES\n",
        encoding="utf-8",
    )
    (dev_abb / "tasks" / "goal" / "goal.md").write_text(
        "---\nid: goal_001\nversion: 1.0.0\nstatus: in_progress\n---\n# Build Codeless Runtime\n",
        encoding="utf-8",
    )
    (dev_abb / "tasks" / "base" / "01_foundation.md").write_text(
        "---\nid: base_001\nversion: 1.0.0\nstatus: done\nparent: goal_001\ndepends_on: []\n---\n# Foundation\n",
        encoding="utf-8",
    )
    (dev_abb / "tasks" / "sub" / "01_sub.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: done\nparent: base_001\ndepends_on: []\n---\n# Sub 1\n",
        encoding="utf-8",
    )
    (dev_abb / "skills" / "qa" / "backend" / "SKILL.md").write_text(
        "---\nid: skill_qa_backend\nversion: 1.0.0\n---\n# QA Backend\n",
        encoding="utf-8",
    )
    (dev_abb / "features" / "test_feature" / "spec.md").write_text(
        "---\nid: feature_test\nversion: 1.0.0\nstatus: active\n---\n# Feature Test\n",
        encoding="utf-8",
    )

    mock_engine = MagicMock()
    return CommandContext(engine=mock_engine, cwd=str(tmp_path))


@pytest.mark.asyncio
async def test_abb_commands_registered():
    registry = create_default_command_registry()
    
    # Check all 14 commands and aliases
    expected_commands = [
        ("plan", "p"),
        ("skills", "s"),
        ("init", "i"),
        ("route", "r"),
        ("goal", "g"),
        ("task", "t"),
        ("verify", "v"),
        ("drift", "d"),
        ("feature", "f"),
        ("references", "ref"),
        ("checkpoint", "cp"),
        ("mode", "m"),
        ("stack", "st"),
        ("prefs", "pr"),
    ]

    for name, alias in expected_commands:
        lookup_name = registry.lookup(f"/{name}")
        assert lookup_name is not None, f"Command /{name} should be registered"
        assert lookup_name[0].name == name

        lookup_alias = registry.lookup(f"/{alias}")
        assert lookup_alias is not None, f"Alias /{alias} should resolve"
        assert lookup_alias[0].name == name


@pytest.mark.asyncio
async def test_plan_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/plan Build Auth")
    res = await cmd.handler(args, mock_context)
    assert "Plan Mode Active" in res.message
    assert "Build Auth" in res.submit_prompt


@pytest.mark.asyncio
async def test_route_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/route plan new authentication system")
    res = await cmd.handler(args, mock_context)
    assert "Router Classification" in res.message
    assert "ROUTE: workflows/planning/planning.md" in res.message


@pytest.mark.asyncio
async def test_goal_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/goal")
    res = await cmd.handler(args, mock_context)
    assert "Build Codeless Runtime" in res.message
    assert "goal_001" in res.message


@pytest.mark.asyncio
async def test_task_command_dag(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/task")
    res = await cmd.handler(args, mock_context)
    assert "ABB Task Hierarchy & DAG" in res.message
    assert "base_001" in res.message
    assert "sub_001" in res.message


@pytest.mark.asyncio
async def test_verify_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/verify")
    res = await cmd.handler(args, mock_context)
    assert "Verification Passed" in res.message


@pytest.mark.asyncio
async def test_feature_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/feature")
    res = await cmd.handler(args, mock_context)
    assert "Registered Features" in res.message
    assert "feature_test" in res.message


@pytest.mark.asyncio
async def test_mode_command(mock_context: CommandContext):
    registry = create_default_command_registry()
    cmd, args = registry.lookup("/mode agent")
    res = await cmd.handler(args, mock_context)
    assert "Operational Mode switched to: AGENT" in res.message
