import asyncio
from pathlib import Path

import pytest

from codeless.tools.grep_tool import GrepTool, GrepToolInput


class _FakeStdout:
    async def readline(self):
        await asyncio.sleep(60)
        return b""


class _ValueErrorThenEofStdout:
    def __init__(self):
        self.calls = 0

    async def readline(self):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("Separator is not found, and chunk exceed the limit")
        return b""


class _FakeProcess:
    def __init__(self, stdout=None):
        self.stdout = stdout or _FakeStdout()
        self.stderr = None
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_grep_tool_returns_timeout_error(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")
    fake_process = _FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_process

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await tool.execute(
        GrepToolInput(pattern="foo", timeout_seconds=1),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is True
    assert "grep timed out after 1 seconds" in result.output
    assert fake_process.terminated or fake_process.killed


@pytest.mark.asyncio
async def test_grep_tool_uses_large_stream_limit_and_skips_valueerror(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")
    fake_process = _FakeProcess(stdout=_ValueErrorThenEofStdout())
    seen_kwargs = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_kwargs.update(kwargs)
        fake_process.returncode = 1
        return fake_process

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await tool.execute(
        GrepToolInput(pattern="foo"),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is False
    assert result.output == "(no matches)"
    assert seen_kwargs["limit"] == 8 * 1024 * 1024


@pytest.mark.asyncio
async def test_grep_tool_discards_rg_stderr_for_directory_search(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")
    fake_process = _FakeProcess(stdout=_ValueErrorThenEofStdout())
    seen_kwargs = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_kwargs.update(kwargs)
        fake_process.returncode = 1
        return fake_process

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await tool.execute(
        GrepToolInput(pattern="foo"),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is False
    assert seen_kwargs["stderr"] is asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_grep_tool_discards_rg_stderr_for_file_search(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello\n", encoding="utf-8")
    fake_process = _FakeProcess(stdout=_ValueErrorThenEofStdout())
    seen_kwargs = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_kwargs.update(kwargs)
        fake_process.returncode = 1
        return fake_process

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await tool.execute(
        GrepToolInput(pattern="foo", root=str(file_path)),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is False
    assert seen_kwargs["stderr"] is asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_grep_tool_python_fallback_reports_invalid_regex(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: None)
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello\n", encoding="utf-8")

    result = await tool.execute(
        GrepToolInput(pattern="hello(", root=str(file_path)),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is False
    assert "invalid regex pattern 'hello('" in result.output
    assert "unterminated subpattern" in result.output


@pytest.mark.asyncio
async def test_grep_tool_reports_missing_root_before_spawning_rg(monkeypatch, tmp_path: Path):
    tool = GrepTool()
    src_root = tmp_path / "src"
    tests_root = tmp_path / "tests"
    src_root.mkdir()
    tests_root.mkdir()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")

    async def fail_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        raise AssertionError("rg should not be spawned for a missing root")

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fail_create_subprocess_exec,
    )

    result = await tool.execute(
        GrepToolInput(pattern="continue", root=f"{src_root} {tests_root}"),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is True
    assert "Search root does not exist" in result.output
    assert "call grep separately for each root" in result.output


@pytest.mark.asyncio
async def test_grep_tool_python_fallback_prunes_ignored_directories(monkeypatch, tmp_path: Path):
    """Python fallback must skip heavy/ignored directories like node_modules and .git."""
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: None)
    monkeypatch.setattr("codeless.tools.grep_tool.find_ripgrep", lambda: None)

    # Valid codebase file
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("target_token = 1\n", encoding="utf-8")

    # Files inside directories that should be pruned
    node_modules = tmp_path / "node_modules" / "some_pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("target_token = 2\n", encoding="utf-8")

    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "hook.sh").write_text("target_token = 3\n", encoding="utf-8")

    result = await tool.execute(
        GrepToolInput(pattern="target_token"),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is False
    assert "app.py:1:target_token = 1" in result.output
    assert "node_modules" not in result.output
    assert ".git" not in result.output


@pytest.mark.asyncio
async def test_grep_tool_python_fallback_respects_timeout(monkeypatch, tmp_path: Path):
    """Python fallback must not hang indefinitely if searching takes too long."""
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: None)
    monkeypatch.setattr("codeless.tools.grep_tool.find_ripgrep", lambda: None)

    def slow_search(*args, **kwargs):
        import time

        time.sleep(2)
        return "done"

    monkeypatch.setattr("codeless.tools.grep_tool._python_grep_dir", slow_search)

    result = await tool.execute(
        GrepToolInput(pattern="foo", timeout_seconds=1),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert result.is_error is True
    assert "grep timed out after 1 seconds" in result.output


@pytest.mark.asyncio
async def test_grep_tool_passes_devnull_stdin_to_subprocess(monkeypatch, tmp_path: Path):
    """Subprocess must receive stdin=DEVNULL to avoid hanging on inherited console stdin."""
    tool = GrepTool()
    monkeypatch.setattr("codeless.tools.grep_tool.shutil.which", lambda _: "/usr/bin/rg")
    seen_kwargs = {}

    class _QuickProcess:
        stdout = _ValueErrorThenEofStdout()
        returncode = 1

    async def fake_create_subprocess_exec(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return _QuickProcess()

    monkeypatch.setattr(
        "codeless.tools.grep_tool.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await tool.execute(
        GrepToolInput(pattern="foo"),
        type("Ctx", (), {"cwd": tmp_path})(),
    )

    assert seen_kwargs.get("stdin") is asyncio.subprocess.DEVNULL
