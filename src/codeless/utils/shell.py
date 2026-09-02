"""Shared shell and subprocess helpers."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from codeless.config import Settings, load_settings
from codeless.platforms import PlatformName, get_platform
from codeless.sandbox import wrap_command_for_sandbox


def resolve_shell_command(
    command: str,
    *,
    platform_name: PlatformName | None = None,
    prefer_pty: bool = False,
) -> list[str]:
    """Return argv for the best available shell on the current platform."""
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "windows":
        bash = _find_windows_bash()
        if bash:
            # Use -c (non-login) instead of -lc to avoid sourcing
            # /etc/profile and ~/.bash_profile on startup. On Windows / Git
            # Bash those profile scripts often invoke conda, nvm, winpty or
            # other hooks that require a controlling TTY. Since we spawn with
            # stdin=DEVNULL and no terminal the login sourcing phase hangs
            # indefinitely. The Windows process $PATH is inherited directly so
            # tools like uv / git remain reachable without -l.
            return [bash, "-c", command]
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            return [powershell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shutil.which("cmd.exe") or "cmd.exe", "/d", "/s", "/c", command]

    bash = shutil.which("bash")
    if bash:
        argv = [bash, "-lc", command]
        if prefer_pty:
            wrapped = _wrap_command_with_script(argv, platform_name=resolved_platform)
            if wrapped is not None:
                return wrapped
        return argv
    shell = shutil.which("sh") or os.environ.get("SHELL") or "/bin/sh"
    argv = [shell, "-lc", command]
    if prefer_pty:
        wrapped = _wrap_command_with_script(argv, platform_name=resolved_platform)
        if wrapped is not None:
            return wrapped
    return argv


async def create_shell_subprocess(
    command: str,
    *,
    cwd: str | Path,
    settings: Settings | None = None,
    prefer_pty: bool = False,
    stdin: int | None = asyncio.subprocess.DEVNULL,
    stdout: int | None = None,
    stderr: int | None = None,
    env: Mapping[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Spawn a shell command with platform-aware shell selection and sandboxing."""
    resolved_settings = settings or load_settings()

    # Docker backend: route through docker exec
    if resolved_settings.sandbox.enabled and resolved_settings.sandbox.backend == "docker":
        from codeless.sandbox.session import get_docker_sandbox

        session = get_docker_sandbox()
        if session is not None and session.is_running:
            argv = resolve_shell_command(command)
            return await session.exec_command(
                argv,
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                env=dict(env) if env is not None else None,
            )
        if resolved_settings.sandbox.fail_if_unavailable:
            from codeless.sandbox import SandboxUnavailableError

            raise SandboxUnavailableError("Docker sandbox session is not running")

    # Existing srt path
    argv = resolve_shell_command(command, prefer_pty=prefer_pty)
    argv, cleanup_path = wrap_command_for_sandbox(argv, settings=resolved_settings)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(Path(cwd).resolve()),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=dict(env) if env is not None else None,
        )
    except Exception:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)
        raise

    if cleanup_path is not None:
        asyncio.create_task(_cleanup_after_exit(process, cleanup_path))
    return process


def _wrap_command_with_script(
    argv: list[str],
    *,
    platform_name: PlatformName | None = None,
) -> list[str] | None:
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "macos":
        return None
    script = shutil.which("script")
    if script is None:
        return None
    if len(argv) >= 3 and argv[1] == "-lc":
        return [script, "-qefc", argv[2], "/dev/null"]
    return None


def _find_windows_bash() -> str | None:
    """Find a working bash binary on Windows, including Git Bash installations."""
    bash = shutil.which("bash")
    if bash and _bash_is_usable(bash):
        return bash

    git_path = shutil.which("git")
    candidate_paths: list[Path] = []
    if git_path:
        git_dir = Path(git_path).resolve().parent
        candidate_paths.extend(
            [
                git_dir / "bash.exe",
                git_dir.parent / "bin" / "bash.exe",
                git_dir.parent / "usr" / "bin" / "bash.exe",
            ]
        )

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")

    if local_app_data:
        candidate_paths.append(Path(local_app_data) / "Programs" / "Git" / "bin" / "bash.exe")
        candidate_paths.append(
            Path(local_app_data) / "Programs" / "Git" / "usr" / "bin" / "bash.exe"
        )
    candidate_paths.append(Path(program_files) / "Git" / "bin" / "bash.exe")
    candidate_paths.append(Path(program_files) / "Git" / "usr" / "bin" / "bash.exe")
    candidate_paths.append(Path(program_files_x86) / "Git" / "bin" / "bash.exe")
    candidate_paths.append(Path(program_files_x86) / "Git" / "usr" / "bin" / "bash.exe")

    for p in candidate_paths:
        if p.exists() and _bash_is_usable(str(p)):
            return str(p)
    return None


def _bash_is_usable(bash_path: str) -> bool:
    """Return True when a discovered bash executable can run commands."""
    try:
        result = subprocess.run(
            [bash_path, "-c", "exit 0"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


async def _cleanup_after_exit(process: asyncio.subprocess.Process, cleanup_path: Path) -> None:
    try:
        await process.wait()
    finally:
        cleanup_path.unlink(missing_ok=True)
