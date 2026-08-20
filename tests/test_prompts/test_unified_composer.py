"""Unit tests for the Unified Prompt Composer."""

from __future__ import annotations

from pathlib import Path

from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.config.settings import Settings
from codeless.coordinator.coordinator_mode import (
    build_worker_system_prompt,
    get_coordinator_system_prompt,
)
from codeless.prompts.context import build_runtime_system_prompt
from codeless.prompts.system_prompt import _BASE_SYSTEM_PROMPT, get_base_system_prompt


def test_base_prompt_no_duplicated_guidance() -> None:
    prompt = get_base_system_prompt()
    # Verify legacy overlapping behavioral narratives are removed
    assert "# Doing tasks" not in prompt
    assert "# Executing actions with care" not in prompt
    # Verify mechanics and safety are preserved
    assert "# System" in prompt
    assert "# Using your tools" in prompt
    assert "# Tone and style" in prompt


def test_runtime_prompt_structure_and_persona(tmp_path: Path) -> None:
    settings = Settings()
    engine = get_mode_engine()
    engine.set_mode(TriMode.AGENT)

    rendered = build_runtime_system_prompt(settings, cwd=tmp_path)
    assert "# System" in rendered
    assert "# Active Mode & Tool Policy" in rendered
    assert "AGENT" in rendered
    assert "Claude Code" not in rendered


def test_runtime_prompt_modes(tmp_path: Path) -> None:
    settings = Settings()
    engine = get_mode_engine()

    for mode in [TriMode.PLAN, TriMode.AGENT, TriMode.ASK, TriMode.CODEBASE, TriMode.GOVERNANCE]:
        engine.set_mode(mode)
        rendered = build_runtime_system_prompt(settings, cwd=tmp_path)
        assert mode.value.upper() in rendered


def test_coordinator_overlay_composition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_COORDINATOR_MODE", "1")
    settings = Settings()
    rendered = build_runtime_system_prompt(settings, cwd=tmp_path)

    assert "# Coordinator Dispatch Overlay" in rendered
    assert "<task-notification>" in rendered
    assert "Claude Code" not in rendered
    # Retains standard base mechanics
    assert "# System" in rendered


def test_worker_system_prompt_composition(tmp_path: Path) -> None:
    settings = Settings()
    worker_prompt = build_worker_system_prompt(
        settings,
        cwd=tmp_path,
        assigned_skills=["tdd", "verification"],
        context_package="Refactor auth module",
    )
    assert "# System" in worker_prompt
    assert "# Assigned Skills" in worker_prompt
    assert "`tdd`" in worker_prompt
    assert "Refactor auth module" in worker_prompt
