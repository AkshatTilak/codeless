"""Tests for five TriMode operational states and slash command integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codeless.abb.commands import _mode_handler
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.commands.registry import CommandContext


@pytest.mark.asyncio
async def test_mode_slash_command_switches_all_five_modes(tmp_path: Path):
    engine = get_mode_engine()
    ctx = CommandContext(engine=MagicMock(), cwd=str(tmp_path))

    # 1. plan
    res = await _mode_handler("plan", ctx)
    assert "PLAN" in res.message
    assert engine.current_mode == TriMode.PLAN

    # 2. agent
    res = await _mode_handler("agent", ctx)
    assert "AGENT" in res.message
    assert engine.current_mode == TriMode.AGENT

    # 3. ask
    res = await _mode_handler("ask", ctx)
    assert "ASK" in res.message
    assert engine.current_mode == TriMode.ASK

    # 4. codebase
    res = await _mode_handler("codebase", ctx)
    assert "CODEBASE" in res.message
    assert engine.current_mode == TriMode.CODEBASE

    # 5. governance (and abb alias)
    res = await _mode_handler("governance", ctx)
    assert "GOVERNANCE" in res.message
    assert engine.current_mode == TriMode.GOVERNANCE

    res_abb = await _mode_handler("abb", ctx)
    assert "GOVERNANCE" in res_abb.message
    assert engine.current_mode == TriMode.GOVERNANCE


@pytest.mark.asyncio
async def test_mode_slash_command_invalid_input(tmp_path: Path):
    ctx = CommandContext(engine=MagicMock(), cwd=str(tmp_path))
    res = await _mode_handler("invalid_mode", ctx)
    assert "Operational Modes & Domain Write Boundaries" in res.message
    assert "Usage:" in res.message
