"""Tests for shell resolution helpers."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from codeless.config.settings import Settings
from codeless.utils.shell import _bash_is_usable, create_shell_subprocess, resolve_shell_command


@pytest.fixture(autouse=True)
def _reset_windows_bash_cache(monkeypatch):
    """The Windows bash resolution is cached process-wide; reset it per test."""
    monkeypatch.setattr("codeless.utils.shell._windows_bash_cache", None)


class _FakeProbeProcess:
    """Minimal subprocess.Popen stand-in for _bash_is_usable tests."""

    def __init__(self, returncode, *, timeout_on_communicate: bool = False):
        self.returncode = returncode
        self.stdout = None
        self.stderr = None
        self.killed = False
        self.communicate_calls = 0
        self._timeout_on_communicate = timeout_on_communicate

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self._timeout_on_communicate:
            raise subprocess.TimeoutExpired(cmd="bash", timeout=timeout)
        return (b"", b"")

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _isolate_windows_candidate_dirs(monkeypatch, tmp_path: Path) -> None:
    """Point Git Bash candidate lookups at a nonexistent dir.

    Keeps tests deterministic on machines that actually have Git for Windows
    installed in one of the scanned locations.
    """
    missing = str(tmp_path / "no-such-dir")
    monkeypatch.setenv("LOCALAPPDATA", missing)
    monkeypatch.setenv("ProgramFiles", missing)
    monkeypatch.setenv("ProgramFiles(x86)", missing)


def test_resolve_shell_command_prefers_bash_on_linux(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.shell.shutil.which",
        lambda name: "/usr/bin/bash" if name == "bash" else None,
    )

    command = resolve_shell_command("echo hi", platform_name="linux")

    assert command == ["/usr/bin/bash", "-lc", "echo hi"]


def test_resolve_shell_command_wraps_with_script_when_pty_requested(monkeypatch):
    def fake_which(name: str) -> str | None:
        mapping = {
            "bash": "/usr/bin/bash",
            "script": "/usr/bin/script",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)

    command = resolve_shell_command("echo hi", platform_name="linux", prefer_pty=True)

    assert command == ["/usr/bin/script", "-qefc", "echo hi", "/dev/null"]


def test_resolve_shell_command_uses_powershell_on_windows(monkeypatch, tmp_path: Path):
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)

    def fake_which(name: str) -> str | None:
        mapping = {
            "pwsh": "C:/Program Files/PowerShell/7/pwsh.exe",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)
    monkeypatch.setattr("codeless.utils.shell._bash_is_usable", lambda _: False)

    command = resolve_shell_command("Write-Output hi", platform_name="windows")

    assert command == [
        "C:/Program Files/PowerShell/7/pwsh.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Write-Output hi",
    ]


def test_resolve_shell_command_skips_script_on_macos(monkeypatch):
    def fake_which(name: str) -> str | None:
        mapping = {
            "bash": "/bin/bash",
            "script": "/usr/bin/script",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)

    command = resolve_shell_command("echo hi", platform_name="macos", prefer_pty=True)

    assert command == ["/bin/bash", "-lc", "echo hi"]


def test_resolve_shell_command_linux_without_script_falls_back(monkeypatch):
    def fake_which(name: str) -> str | None:
        mapping = {
            "bash": "/usr/bin/bash",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)

    command = resolve_shell_command("echo hi", platform_name="linux", prefer_pty=True)

    assert command == ["/usr/bin/bash", "-lc", "echo hi"]


def test_resolve_shell_command_windows_skips_unusable_bash(monkeypatch, tmp_path: Path):
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)

    def fake_which(name: str) -> str | None:
        mapping = {
            "bash": "C:/Windows/System32/bash.exe",
            "powershell": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)
    monkeypatch.setattr("codeless.utils.shell._bash_is_usable", lambda _: False)

    command = resolve_shell_command("Write-Output hi", platform_name="windows")

    assert command == [
        "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Write-Output hi",
    ]


def test_resolve_shell_command_windows_uses_usable_bash(monkeypatch, tmp_path: Path):
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)

    def fake_which(name: str) -> str | None:
        mapping = {
            "bash": "C:/Program Files/Git/bin/bash.exe",
            "powershell": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        }
        return mapping.get(name)

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)
    monkeypatch.setattr("codeless.utils.shell._bash_is_usable", lambda _: True)

    command = resolve_shell_command("echo hi", platform_name="windows")

    # Must be -c (non-login), NOT -lc — login shell sources ~/.bash_profile
    # which can hang when there is no controlling TTY (see bash_tool stdin=DEVNULL).
    assert command == ["C:/Program Files/Git/bin/bash.exe", "-c", "echo hi"]


def test_resolve_shell_command_windows_bash_uses_non_login_flag(monkeypatch, tmp_path: Path):
    """Windows Git Bash must be invoked with -c, not -lc.

    The login flag (-l) causes bash to source /etc/profile and ~/.bash_profile.
    On Windows / Git Bash those scripts frequently invoke conda init, nvm, or
    winpty hooks that block without a controlling TTY.  Since the bash tool
    always spawns with stdin=DEVNULL and no PTY, the login sourcing phase
    hangs indefinitely until the 600-second timeout fires.

    Using -c (non-login) skips profile sourcing; the Windows process $PATH is
    inherited from the parent so tools like uv/git remain reachable.
    """

    def fake_which(name: str) -> str | None:
        return "C:/Program Files/Git/bin/bash.exe" if name == "bash" else None

    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)
    monkeypatch.setattr("codeless.utils.shell._bash_is_usable", lambda _: True)

    command = resolve_shell_command("echo hi", platform_name="windows")

    assert "-lc" not in command, (
        "Windows bash must NOT use -l (login) flag — it sources profile scripts "
        "that hang without a TTY"
    )
    assert command == ["C:/Program Files/Git/bin/bash.exe", "-c", "echo hi"]


def test_bash_is_usable_returns_true_for_zero_exit(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.shell.subprocess.Popen", lambda *args, **kwargs: _FakeProbeProcess(0)
    )

    assert _bash_is_usable("bash") is True


def test_bash_is_usable_returns_false_for_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.shell.subprocess.Popen", lambda *args, **kwargs: _FakeProbeProcess(1)
    )

    assert _bash_is_usable("bash") is False


def test_bash_is_usable_returns_false_for_spawn_errors(monkeypatch):
    def raise_oserror(*args, **kwargs):
        raise OSError("missing binary")

    monkeypatch.setattr("codeless.utils.shell.subprocess.Popen", raise_oserror)

    assert _bash_is_usable("bash") is False


def test_bash_is_usable_timeout_kills_without_recommunicating(monkeypatch):
    """Regression test for the agent-mode bash stall on Windows.

    subprocess.run(timeout=...) kills a timed-out child and then calls
    communicate() again with NO timeout; MSYS2/WSL launchers spawn helpers
    that keep the captured pipes open, so that second communicate() hangs
    forever and freezes the event loop. The Popen-based probe must kill and
    never block on the pipes again.
    """
    process = _FakeProbeProcess(None, timeout_on_communicate=True)
    monkeypatch.setattr("codeless.utils.shell.subprocess.Popen", lambda *a, **k: process)

    assert _bash_is_usable("bash") is False
    assert process.killed is True
    assert process.communicate_calls == 1


@pytest.mark.asyncio
async def test_create_shell_subprocess_defaults_stdin_to_devnull(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        class _FakeProcess:
            returncode = 0

            async def wait(self):
                return 0

        return _FakeProcess()

    monkeypatch.setattr(
        "codeless.utils.shell.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "codeless.utils.shell.wrap_command_for_sandbox",
        lambda argv, settings=None: (argv, None),
    )
    monkeypatch.setattr(
        "codeless.utils.shell.resolve_shell_command",
        lambda cmd, **kwargs: ["/usr/bin/bash", "-lc", cmd],
    )

    await create_shell_subprocess(
        "echo hi",
        cwd=tmp_path,
        settings=Settings(),
    )

    assert captured["args"] == ("/usr/bin/bash", "-lc", "echo hi")
    assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
