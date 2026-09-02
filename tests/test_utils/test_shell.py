"""Tests for shell resolution helpers."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from codeless.config.settings import Settings
from codeless.utils.shell import _bash_is_usable, create_shell_subprocess, resolve_shell_command


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


def test_resolve_shell_command_uses_powershell_on_windows(monkeypatch):
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


def test_resolve_shell_command_windows_skips_unusable_bash(monkeypatch):
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


def test_resolve_shell_command_windows_uses_usable_bash(monkeypatch):
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


def test_resolve_shell_command_windows_bash_uses_non_login_flag(monkeypatch):
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

    monkeypatch.setattr("codeless.utils.shell.shutil.which", fake_which)
    monkeypatch.setattr("codeless.utils.shell._bash_is_usable", lambda _: True)

    command = resolve_shell_command("echo hi", platform_name="windows")

    assert "-lc" not in command, (
        "Windows bash must NOT use -l (login) flag — it sources profile scripts "
        "that hang without a TTY"
    )
    assert command == ["C:/Program Files/Git/bin/bash.exe", "-c", "echo hi"]


def test_bash_is_usable_returns_true_for_zero_exit(monkeypatch):
    class _Result:
        returncode = 0

    monkeypatch.setattr("codeless.utils.shell.subprocess.run", lambda *args, **kwargs: _Result())

    assert _bash_is_usable("bash") is True


def test_bash_is_usable_returns_false_for_nonzero_exit(monkeypatch):
    class _Result:
        returncode = 1

    monkeypatch.setattr("codeless.utils.shell.subprocess.run", lambda *args, **kwargs: _Result())

    assert _bash_is_usable("bash") is False


def test_bash_is_usable_returns_false_for_spawn_errors(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="bash", timeout=5)

    monkeypatch.setattr("codeless.utils.shell.subprocess.run", raise_timeout)

    assert _bash_is_usable("bash") is False


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
