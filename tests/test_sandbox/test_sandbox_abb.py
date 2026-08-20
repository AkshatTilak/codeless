"""Tests for Sandbox–ABB integration (Docker mount, srt config, env passthrough)."""

from __future__ import annotations

from pathlib import Path
import pytest

from codeless.config import Settings
from codeless.sandbox.adapter import build_sandbox_runtime_config
from codeless.sandbox.docker_backend import DockerSandboxSession
from codeless.sandbox.path_validator import validate_sandbox_path


def test_docker_sandbox_session_mounts_abb_workspace(tmp_path: Path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    abb_ws = project_dir / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# Agent\n", encoding="utf-8")

    settings = Settings()
    settings.sandbox.enabled = True
    settings.sandbox.backend = "docker"

    session = DockerSandboxSession(settings=settings, session_id="test_session_123", cwd=project_dir)
    argv = session._build_run_argv()

    # Verify CODELESS_ABB_ROOT is passed via -e
    env_flags = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
    abb_env = next((e for e in env_flags if e.startswith("CODELESS_ABB_ROOT=")), None)
    assert abb_env is not None
    assert str(abb_ws.resolve()) in abb_env


def test_build_sandbox_runtime_config_includes_abb_workspace(tmp_path: Path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    abb_ws = project_dir / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# Agent\n", encoding="utf-8")

    settings = Settings()
    config = build_sandbox_runtime_config(settings, cwd=project_dir)

    allow_read = config["filesystem"]["allowRead"]
    allow_write = config["filesystem"]["allowWrite"]

    assert str(abb_ws.resolve()) in allow_read
    assert str(abb_ws.resolve()) in allow_write


def test_validate_sandbox_path_allows_abb_workspace(tmp_path: Path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    abb_ws = project_dir / ".codeless" / "abb_workspace"
    abb_ws.mkdir(parents=True)
    (abb_ws / "agent.md").write_text("# Agent\n", encoding="utf-8")

    target = abb_ws / "tasks" / "goal" / "goal.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    allowed, reason = validate_sandbox_path(target, cwd=project_dir)
    assert allowed is True
    assert reason == ""
