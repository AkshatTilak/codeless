"""End-to-end verification suite for Phase 1.5 Agent Surface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from codeless.abb.commands import _mode_handler
from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.commands.registry import CommandContext
from codeless.config import Settings
from codeless.prompts.context import build_runtime_system_prompt
from codeless.sandbox.adapter import build_sandbox_runtime_config
from codeless.sandbox.docker_backend import DockerSandboxSession
from codeless.tools import create_default_tool_registry
from codeless.tools.abb_task_tool import AbbTaskTool
from codeless.tools.abb_verify_tool import AbbVerifyTool
from codeless.tools.agent_tool import AgentTool, AgentToolInput
from codeless.tools.bash_tool import BashTool, BashToolInput
from codeless.tools.base import ToolExecutionContext


@pytest.fixture
def e2e_abb_workspace(tmp_path: Path):
    ws = tmp_path / ".codeless" / "abb_workspace"
    ws.mkdir(parents=True)
    (ws / "agent.md").write_text("# Agent Persona\n", encoding="utf-8")
    (ws / "STACK.md").write_text(
        "---\nverification:\n  track_1: [\"python -c 'print(1)'\"]\n  track_2: []\n---\n# STACK\n",
        encoding="utf-8",
    )
    tasks_sub = ws / "tasks" / "sub"
    tasks_sub.mkdir(parents=True)
    (tasks_sub / "01_init.md").write_text(
        "---\nid: sub_001\nversion: 1.0.0\nstatus: done\ndepends_on: []\n---\n# Init\n",
        encoding="utf-8",
    )
    (tasks_sub / "02_second.md").write_text(
        "---\nid: sub_002\nversion: 1.0.0\nstatus: not_started\ndepends_on: [sub_001]\n---\n# Second\n",
        encoding="utf-8",
    )
    return tmp_path


def test_scenario_1_prompt_audit(e2e_abb_workspace: Path, monkeypatch):
    """Scenario 1: Prompt Audit across all 5 modes and coordinator overlay."""
    monkeypatch.setenv("CODELESS_DATA_DIR", str(e2e_abb_workspace / "data"))
    engine = get_mode_engine()

    for mode in (TriMode.PLAN, TriMode.AGENT, TriMode.ASK, TriMode.CODEBASE, TriMode.GOVERNANCE):
        engine.set_mode(mode)
        prompt = build_runtime_system_prompt(
            Settings(),
            cwd=e2e_abb_workspace,
            latest_user_prompt="audit test",
        )
        # Verify no old Claude Code identity string exists
        assert "You are Claude Code" not in prompt
        # Verify mode section is included
        assert "Active Mode & Tool Policy" in prompt or "Active Mode" in prompt

    # Coordinator overlay
    monkeypatch.setenv("CLAUDE_CODE_COORDINATOR_MODE", "1")
    coord_prompt = build_runtime_system_prompt(
        Settings(),
        cwd=e2e_abb_workspace,
        latest_user_prompt="coord test",
    )
    assert "Coordinator Dispatch Overlay" in coord_prompt
    assert "You are Claude Code" not in coord_prompt


@pytest.mark.asyncio
async def test_scenario_2_mode_matrix_and_bash_guard(e2e_abb_workspace: Path):
    """Scenario 2: Mode Matrix & Domain Write Boundaries across file tools and bash."""
    engine = get_mode_engine()
    ctx = ToolExecutionContext(cwd=e2e_abb_workspace)
    bash = BashTool()
    abb_ws = e2e_abb_workspace / ".codeless" / "abb_workspace"

    # ASK mode: all writes blocked
    engine.set_mode(TriMode.ASK)
    res = await bash.execute(BashToolInput(command="echo 'data' > file.txt"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output

    # PLAN mode: code blocked, tasks allowed
    engine.set_mode(TriMode.PLAN)
    code_res = await bash.execute(BashToolInput(command="echo 'code' > src/main.py"), ctx)
    assert code_res.is_error
    assert "ABB Mode Permission Blocked" in code_res.output

    # GOVERNANCE mode: code blocked, meta specs allowed
    engine.set_mode(TriMode.GOVERNANCE)
    allowed_meta, _ = pre_tool_use_abb_guard(
        "write_file",
        {"path": ".codeless/abb_workspace/STACK.md", "content": "# STACK\n"},
        e2e_abb_workspace,
    )
    assert allowed_meta

    blocked_code, _ = pre_tool_use_abb_guard(
        "write_file",
        {"path": "src/main.py", "content": "print(1)\n"},
        e2e_abb_workspace,
    )
    assert not blocked_code


@pytest.mark.asyncio
async def test_scenario_3_tools_inventory_and_abb_tools(e2e_abb_workspace: Path):
    """Scenario 3: Registry state and ABB tool execution."""
    registry = create_default_tool_registry()
    tool_names = set(registry._tools.keys())

    # Conflicting / bloat tools removed
    assert "enter_plan_mode" not in tool_names
    assert "exit_plan_mode" not in tool_names
    assert "team_create" not in tool_names
    assert "team_delete" not in tool_names

    # ABB tools present
    assert "abb_task" in tool_names
    assert "abb_verify" in tool_names

    # Execute abb_task ready
    ctx = ToolExecutionContext(cwd=e2e_abb_workspace)
    task_tool = AbbTaskTool()
    ready_res = await task_tool.execute(ctx, action="ready")
    assert not ready_res.is_error
    assert "sub_002" in ready_res.output

    # Execute abb_verify dry-run
    verify_tool = AbbVerifyTool()
    verify_res = await verify_tool.execute(ctx, dry_run=True)
    assert not verify_res.is_error
    assert "python -c 'print(1)'" in verify_res.output


@pytest.mark.asyncio
async def test_scenario_4_agent_mode_filtering(e2e_abb_workspace: Path, monkeypatch):
    """Scenario 4: Agent spawning filtered by mode."""
    monkeypatch.setenv("CODELESS_DATA_DIR", str(e2e_abb_workspace / "data"))
    engine = get_mode_engine()
    ctx = ToolExecutionContext(cwd=e2e_abb_workspace)

    # In ASK mode: Explore is allowed, abb-governance is rejected
    engine.set_mode(TriMode.ASK)
    explore_res = await AgentTool().execute(
        AgentToolInput(
            description="explore",
            prompt="search",
            subagent_type="Explore",
            command="python -u -c \"import sys; print(sys.stdin.readline().strip())\"",
        ),
        ctx,
    )
    assert not explore_res.is_error

    gov_res = await AgentTool().execute(
        AgentToolInput(
            description="gov",
            prompt="update",
            subagent_type="abb-governance",
            command="python -u -c \"import sys; print(sys.stdin.readline().strip())\"",
        ),
        ctx,
    )
    assert gov_res.is_error
    assert "cannot be spawned in active mode 'ask'" in gov_res.output


def test_scenario_5_sandbox_abb_coherence(e2e_abb_workspace: Path):
    """Scenario 5: Docker sandbox mount, env passthrough, and srt configuration."""
    settings = Settings()
    settings.sandbox.enabled = True
    settings.sandbox.backend = "docker"

    session = DockerSandboxSession(settings=settings, session_id="phase1_5_e2e", cwd=e2e_abb_workspace)
    argv = session._build_run_argv()

    # Assert CODELESS_ABB_ROOT in Docker env
    env_flags = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
    assert any(e.startswith("CODELESS_ABB_ROOT=") for e in env_flags)

    # Assert srt configuration includes shadow workspace
    srt_config = build_sandbox_runtime_config(settings, cwd=e2e_abb_workspace)
    abb_ws = resolve_abb_workspace(e2e_abb_workspace)
    assert str(abb_ws.resolve()) in srt_config["filesystem"]["allowRead"]
    assert str(abb_ws.resolve()) in srt_config["filesystem"]["allowWrite"]
