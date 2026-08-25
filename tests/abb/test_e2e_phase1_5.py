"""End-to-end verification suite for Phase 1.5 Agent Surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeless.abb.hooks.bridge import pre_tool_use_abb_guard
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.config import Settings
from codeless.prompts.context import build_runtime_system_prompt
from codeless.sandbox.adapter import build_sandbox_runtime_config
from codeless.sandbox.docker_backend import DockerSandboxSession
from codeless.tools import create_default_tool_registry
from codeless.tools.abb_tool import AbbTool, AbbToolInput
from codeless.tools.agent_tool import AgentTool, AgentToolInput
from codeless.tools.base import ToolExecutionContext
from codeless.tools.bash_tool import BashTool, BashToolInput


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
    """Scenario 1: Prompt Audit across all 4 modes and coordinator overlay."""
    monkeypatch.setenv("CODELESS_DATA_DIR", str(e2e_abb_workspace / "data"))
    engine = get_mode_engine()

    for mode in (TriMode.PLAN, TriMode.AGENT, TriMode.ASK, TriMode.CODEBASE):
        engine.set_mode(mode)
        prompt = build_runtime_system_prompt(
            Settings(),
            cwd=e2e_abb_workspace,
            latest_user_prompt="audit test",
        )
        assert "You are Claude Code" not in prompt
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

    # ASK mode: all writes blocked
    engine.set_mode(TriMode.ASK)
    res = await bash.execute(BashToolInput(command="echo 'data' > file.txt"), ctx)
    assert res.is_error
    assert "ABB Mode Permission Blocked" in res.output

    # PLAN mode: code blocked, ABB workspace allowed
    engine.set_mode(TriMode.PLAN)
    code_res = await bash.execute(BashToolInput(command="echo 'code' > src/main.py"), ctx)
    assert code_res.is_error
    assert "ABB Mode Permission Blocked" in code_res.output

    # PLAN mode: meta specs and tasks allowed
    allowed_meta, _ = pre_tool_use_abb_guard(
        "file",
        {"action": "write", "path": ".codeless/abb_workspace/STACK.md", "content": "# STACK\n"},
        e2e_abb_workspace,
    )
    assert allowed_meta

    blocked_code, _ = pre_tool_use_abb_guard(
        "file",
        {"action": "write", "path": "src/main.py", "content": "print(1)\n"},
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

    # ABB canonical tool present
    assert "abb" in tool_names

    # Execute abb ready
    ctx = ToolExecutionContext(cwd=e2e_abb_workspace)
    abb_tool = AbbTool()
    ready_res = await abb_tool.execute(AbbToolInput(action="ready"), ctx)
    assert not ready_res.is_error
    assert "sub_002" in ready_res.output

    # Execute abb verify dry-run
    verify_res = await abb_tool.execute(AbbToolInput(action="verify", dry_run=True), ctx)
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
            action="spawn",
            description="explore",
            prompt="search",
            subagent_type="Explore",
            command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
        ),
        ctx,
    )
    assert not explore_res.is_error

    gov_res = await AgentTool().execute(
        AgentToolInput(
            action="spawn",
            description="gov",
            prompt="update",
            subagent_type="abb-governance",
            command='python -u -c "import sys; print(sys.stdin.readline().strip())"',
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

    session = DockerSandboxSession(
        settings=settings, session_id="phase1_5_e2e", cwd=e2e_abb_workspace
    )
    argv = session._build_run_argv()

    env_flags = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
    assert any(e.startswith("CODELESS_ABB_ROOT=") for e in env_flags)

    srt_config = build_sandbox_runtime_config(settings, cwd=e2e_abb_workspace)
    abb_ws = resolve_abb_workspace(e2e_abb_workspace)
    assert str(abb_ws.resolve()) in srt_config["filesystem"]["allowRead"]
    assert str(abb_ws.resolve()) in srt_config["filesystem"]["allowWrite"]
