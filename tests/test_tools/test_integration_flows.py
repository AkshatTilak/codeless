"""Higher-level integration flows across canonical built-in tools."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from codeless.jobs.manager import get_task_manager
from codeless.tools import create_default_tool_registry
from codeless.tools.base import ToolExecutionContext


async def _wait_for_terminal_task(task_id: str, *, timeout_seconds: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    manager = get_task_manager()
    while asyncio.get_running_loop().time() < deadline:
        task = manager.get_task(task_id)
        if task is not None and task.status in {"completed", "failed", "killed"}:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not reach a terminal status in time")


@pytest.mark.asyncio
async def test_search_edit_flow_across_registry(tmp_path: Path):
    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    file_tool = registry.get("file")
    glob = registry.get("glob")
    grep = registry.get("grep")

    await file_tool.execute(
        file_tool.input_model(action="write", path="src/demo.py", content="alpha\nbeta\n"),
        context,
    )
    glob_result = await glob.execute(glob.input_model(pattern="**/*.py"), context)
    assert "src/demo.py" in glob_result.output.replace("\\", "/")

    grep_result = await grep.execute(
        grep.input_model(pattern="beta", file_glob="**/*.py"),
        context,
    )
    assert "src/demo.py:2:beta" in grep_result.output.replace("\\", "/")

    await file_tool.execute(
        file_tool.input_model(action="edit", path="src/demo.py", old_str="beta", new_str="gamma"),
        context,
    )
    read_result = await file_tool.execute(
        file_tool.input_model(action="read", path="src/demo.py"), context
    )
    assert "gamma" in read_result.output
    assert "beta" not in (tmp_path / "src" / "demo.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_task_and_todo_flow_across_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    tool_search = registry.get("tool_search")
    todo_write = registry.get("todo_write")
    task = registry.get("task")

    search_result = await tool_search.execute(tool_search.input_model(query="task"), context)
    assert "task" in search_result.output

    await todo_write.execute(todo_write.input_model(item="integration flow item"), context)
    assert "integration flow item" in (tmp_path / "TODO.md").read_text(encoding="utf-8")

    create_result = await task.execute(
        task.input_model(
            action="create",
            type="local_bash",
            description="integration flow task",
            command="printf 'INTEGRATION_TASK_OK'",
        ),
        context,
    )
    task_id = create_result.output.split()[2]
    update_result = await task.execute(
        task.input_model(
            action="update",
            task_id=task_id,
            description="renamed integration task",
        ),
        context,
    )
    assert "Updated task" in update_result.output

    task_detail = await task.execute(task.input_model(action="get", task_id=task_id), context)
    assert "renamed integration task" in task_detail.output

    for _ in range(20):
        output = await task.execute(task.input_model(action="output", task_id=task_id), context)
        if "INTEGRATION_TASK_OK" in output.output:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("task output did not become available in time")

    assert "INTEGRATION_TASK_OK" in output.output


@pytest.mark.asyncio
async def test_skill_and_config_flow_across_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_CONFIG_DIR", str(tmp_path / "config"))
    skills_dir = tmp_path / "config" / "skills"
    skills_dir.mkdir(parents=True)
    pytest_dir = skills_dir / "pytest"
    pytest_dir.mkdir()
    (pytest_dir / "SKILL.md").write_text(
        "# Pytest\nPytest fixtures help reuse setup.\n",
        encoding="utf-8",
    )

    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    config = registry.get("config")
    skill = registry.get("skill")

    set_result = await config.execute(
        config.input_model(action="set", key="theme", value="night-owl"),
        context,
    )
    assert set_result.output == "Updated theme"

    show_result = await config.execute(config.input_model(action="show"), context)
    assert "night-owl" in show_result.output

    skill_result = await skill.execute(skill.input_model(name="Pytest"), context)
    assert "fixtures" in skill_result.output


@pytest.mark.asyncio
async def test_agent_send_message_flow_restarts_completed_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    agent = registry.get("agent")
    task = registry.get("task")

    create_result = await agent.execute(
        agent.input_model(
            action="spawn",
            description="echo agent",
            prompt="ready",
            command="python -u -c \"import sys; print('AGENT_ECHO:' + sys.stdin.readline().strip())\"",
        ),
        context,
    )
    match = re.search(r"task_id=(\S+?)[,)]", create_result.output)
    assert match, create_result.output
    task_id = match.group(1)

    for _ in range(80):
        output = await task.execute(task.input_model(action="output", task_id=task_id), context)
        if "AGENT_ECHO:ready" in output.output:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("initial agent output did not become available in time")

    send_result = await agent.execute(
        agent.input_model(action="message", task_id=task_id, message="agent ping"),
        context,
    )
    assert send_result.is_error is False

    await asyncio.sleep(0.2)
    for _ in range(150):
        output = await task.execute(task.input_model(action="output", task_id=task_id), context)
        if "AGENT_ECHO:agent ping" in output.output:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError(
            f"agent follow-up output did not become available in time. Output: {output.output}"
        )

    assert "AGENT_ECHO:ready" in output.output
    assert "AGENT_ECHO:agent ping" in output.output
    await _wait_for_terminal_task(task_id)


@pytest.mark.asyncio
async def test_ask_user_question_flow_across_registry(tmp_path: Path):
    registry = create_default_tool_registry()

    async def _answer(question: str) -> str:
        assert "favorite color" in question
        return "green"

    context = ToolExecutionContext(
        cwd=tmp_path,
        metadata={"tool_registry": registry, "ask_user_prompt": _answer},
    )
    ask_user = registry.get("ask_user_question")
    file_tool = registry.get("file")

    answer_result = await ask_user.execute(
        ask_user.input_model(question="What is your favorite color?"),
        context,
    )
    assert answer_result.output == "green"

    await file_tool.execute(
        file_tool.input_model(action="write", path="answer.txt", content=answer_result.output),
        context,
    )
    read_result = await file_tool.execute(
        file_tool.input_model(action="read", path="answer.txt"), context
    )
    assert "green" in read_result.output


@pytest.mark.asyncio
async def test_notebook_and_cron_flow_across_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODELESS_DATA_DIR", str(tmp_path / "data"))
    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    file_tool = registry.get("file")
    cron = registry.get("cron")

    notebook_result = await file_tool.execute(
        file_tool.input_model(
            action="notebook_edit",
            path="nb/demo.ipynb",
            cell_index=0,
            new_source="print('flow ok')\n",
        ),
        context,
    )
    assert notebook_result.is_error is False
    assert "flow ok" in (tmp_path / "nb" / "demo.ipynb").read_text(encoding="utf-8")

    await cron.execute(
        cron.input_model(
            action="create", name="flow", schedule="0 0 * * *", command="printf 'FLOW_CRON_OK'"
        ),
        context,
    )
    list_result = await cron.execute(cron.input_model(action="list"), context)
    assert "flow" in list_result.output

    delete_result = await cron.execute(cron.input_model(action="delete", name="flow"), context)
    assert delete_result.is_error is False


@pytest.mark.asyncio
async def test_lsp_flow_across_registry(tmp_path: Path):
    registry = create_default_tool_registry()
    context = ToolExecutionContext(cwd=tmp_path, metadata={"tool_registry": registry})

    file_tool = registry.get("file")
    lsp = registry.get("lsp")

    await file_tool.execute(
        file_tool.input_model(
            action="write",
            path="pkg/utils.py",
            content='def greet(name):\n    """Return a greeting."""\n    return f"hi {name}"\n',
        ),
        context,
    )
    await file_tool.execute(
        file_tool.input_model(
            action="write",
            path="pkg/app.py",
            content="from pkg.utils import greet\n\nprint(greet('world'))\n",
        ),
        context,
    )

    symbol_result = await lsp.execute(
        lsp.input_model(operation="workspace_symbol", query="greet"),
        context,
    )
    assert "function greet" in symbol_result.output

    definition_result = await lsp.execute(
        lsp.input_model(operation="go_to_definition", file_path="pkg/app.py", symbol="greet"),
        context,
    )
    assert "pkg/utils.py:1:1" in definition_result.output.replace("\\", "/")

    hover_result = await lsp.execute(
        lsp.input_model(operation="hover", file_path="pkg/app.py", symbol="greet"),
        context,
    )
    assert "Return a greeting." in hover_result.output
