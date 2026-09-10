"""Tests for Phase 2.8: Tool concurrency control and mutating tool serialization."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from codeless.config.settings import PermissionSettings
from codeless.engine.query import (
    QueryContext,
    _execute_tool_calls_partitioned,
    _is_tool_call_read_only,
)
from codeless.engine.stream_events import ToolExecutionCompleted, ToolExecutionStarted
from codeless.permissions import PermissionChecker, PermissionMode
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


class _SimpleInput(BaseModel):
    action: str = "read"
    value: str = ""


class _ReadOnlyTool(BaseTool):
    name = "read_only"
    description = "A pure read tool"
    input_model = _SimpleInput
    def is_read_only(self, arguments: _SimpleInput) -> bool: return True
    async def execute(self, arguments: _SimpleInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"read:{arguments.value}")


class _MutatingTool(BaseTool):
    name = "mutating"
    description = "A mutating tool"
    input_model = _SimpleInput
    def is_read_only(self, arguments: _SimpleInput) -> bool: return False
    async def execute(self, arguments: _SimpleInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"write:{arguments.value}")


class _SlowReadTool(BaseTool):
    name = "slow_read"
    description = "Slow read"
    input_model = _SimpleInput
    delay: float = 0.15
    def is_read_only(self, arguments: _SimpleInput) -> bool: return True
    async def execute(self, arguments: _SimpleInput, context: ToolExecutionContext) -> ToolResult:
        await asyncio.sleep(self.delay)
        return ToolResult(output=f"slow:{arguments.value}")


class _RaisingTool(BaseTool):
    name = "raising"
    description = "Always raises"
    input_model = _SimpleInput
    def is_read_only(self, arguments: _SimpleInput) -> bool: return False
    async def execute(self, arguments: _SimpleInput, context: ToolExecutionContext) -> ToolResult:
        raise RuntimeError("deliberate test failure")


@dataclass
class _Tc:
    name: str
    id: str
    input: dict[str, Any]


def _ctx(*tools: BaseTool) -> QueryContext:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
    return QueryContext(
        api_client=MagicMock(), tool_registry=reg, permission_checker=checker,
        cwd=Path("."), model="test", system_prompt="test", max_tokens=100, max_turns=None,
    )


class TestIsToolCallReadOnly:
    def test_unknown_returns_false(self):
        assert _is_tool_call_read_only(_ctx(), "nope", {}) is False

    def test_read_only_tool(self):
        assert _is_tool_call_read_only(_ctx(_ReadOnlyTool()), "read_only", {}) is True

    def test_mutating_tool(self):
        assert _is_tool_call_read_only(_ctx(_MutatingTool()), "mutating", {}) is False


class TestPartitionedExecution:
    @pytest.mark.asyncio
    async def test_single_read(self):
        results = await _execute_tool_calls_partitioned(
            _ctx(_ReadOnlyTool()), [_Tc("read_only", "id-1", {"value": "a"})]
        )
        assert len(results) == 1
        assert "read:a" in results[0].content

    @pytest.mark.asyncio
    async def test_single_mutating(self):
        results = await _execute_tool_calls_partitioned(
            _ctx(_MutatingTool()), [_Tc("mutating", "id-2", {"value": "b"})]
        )
        assert len(results) == 1
        assert "write:b" in results[0].content

    @pytest.mark.asyncio
    async def test_concurrent_reads_are_fast(self):
        t = _SlowReadTool()
        t.delay = 0.15
        tcs = [_Tc("slow_read", f"id-{i}", {"value": str(i)}) for i in range(3)]
        start = time.monotonic()
        results = await _execute_tool_calls_partitioned(_ctx(t), tcs)
        elapsed = time.monotonic() - start
        assert len(results) == 3
        assert elapsed < 0.40, f"Concurrent reads took {elapsed:.2f}s (expected < 0.40)"

    @pytest.mark.asyncio
    async def test_mutating_sequential_order(self):
        order: list[str] = []
        class OrderedTool(BaseTool):
            name = "mutating"
            description = "order tracking"
            input_model = _SimpleInput
            def is_read_only(self, a: _SimpleInput) -> bool: return False
            async def execute(self, a: _SimpleInput, ctx: ToolExecutionContext) -> ToolResult:
                order.append(a.value)
                return ToolResult(output=a.value)
        tcs = [_Tc("mutating", f"id-{i}", {"value": str(i)}) for i in range(3)]
        await _execute_tool_calls_partitioned(_ctx(OrderedTool()), tcs)
        assert order == ["0", "1", "2"]

    @pytest.mark.asyncio
    async def test_mixed_batch_order_preserved(self):
        results = await _execute_tool_calls_partitioned(
            _ctx(_ReadOnlyTool(), _MutatingTool()),
            [
                _Tc("read_only", "r1", {"value": "1"}),
                _Tc("read_only", "r2", {"value": "2"}),
                _Tc("mutating",  "w1", {"value": "X"}),
                _Tc("read_only", "r3", {"value": "3"}),
            ],
        )
        assert len(results) == 4
        assert "read:1" in results[0].content
        assert "read:2" in results[1].content
        assert "write:X" in results[2].content
        assert "read:3" in results[3].content

    @pytest.mark.asyncio
    async def test_exception_captured_not_raised(self):
        results = await _execute_tool_calls_partitioned(
            _ctx(_RaisingTool()), [_Tc("raising", "bad", {"value": "x"})]
        )
        assert results[0].is_error is True
        assert "deliberate test failure" in results[0].content

    @pytest.mark.asyncio
    async def test_sibling_reads_not_cancelled_by_one_failure(self):
        class SometimesRaising(BaseTool):
            name = "read_only"
            description = "sometimes raises"
            input_model = _SimpleInput
            def is_read_only(self, a: _SimpleInput) -> bool: return True
            async def execute(self, a: _SimpleInput, ctx: ToolExecutionContext) -> ToolResult:
                if a.value == "fail": raise RuntimeError("forced")
                return ToolResult(output=f"ok:{a.value}")
        tcs = [
            _Tc("read_only", "r1", {"value": "ok1"}),
            _Tc("read_only", "r2", {"value": "fail"}),
            _Tc("read_only", "r3", {"value": "ok3"}),
        ]
        results = await _execute_tool_calls_partitioned(_ctx(SometimesRaising()), tcs)
        assert len(results) == 3
        assert not results[0].is_error
        assert results[1].is_error
        assert not results[2].is_error

    @pytest.mark.asyncio
    async def test_tool_use_id_preserved(self):
        results = await _execute_tool_calls_partitioned(
            _ctx(_ReadOnlyTool(), _MutatingTool()),
            [
                _Tc("read_only", "uid-99", {"value": "x"}),
                _Tc("mutating",  "uid-42", {"value": "y"}),
            ],
        )
        assert results[0].tool_use_id == "uid-99"
        assert results[1].tool_use_id == "uid-42"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        assert await _execute_tool_calls_partitioned(_ctx(), []) == []


class TestStreamEventToolUseId:
    def test_started_has_tool_use_id(self):
        ev = ToolExecutionStarted(tool_name="file", tool_input={}, tool_use_id="abc-123")
        assert ev.tool_use_id == "abc-123"

    def test_started_defaults_none(self):
        ev = ToolExecutionStarted(tool_name="file", tool_input={})
        assert ev.tool_use_id is None

    def test_completed_has_tool_use_id(self):
        ev = ToolExecutionCompleted(tool_name="file", output="ok", tool_use_id="xyz-456")
        assert ev.tool_use_id == "xyz-456"

    def test_completed_defaults_none(self):
        ev = ToolExecutionCompleted(tool_name="file", output="ok")
        assert ev.tool_use_id is None


class TestOpenAIStreamingIndexDisambiguation:
    def _accumulate(self, deltas: list[dict]) -> dict[int, dict]:
        from uuid import uuid4
        collected: dict[int, dict] = {}
        for d in deltas:
            idx = d.get("index")
            if idx is None:
                idx = max(collected.keys()) + 1 if collected else 0
            if idx not in collected:
                fallback = d.get("id") or f"call_{uuid4().hex[:12]}"
                collected[idx] = {"id": fallback, "name": "", "arguments": ""}
            entry = collected[idx]
            if d.get("id"): entry["id"] = d["id"]
            if d.get("name"): entry["name"] += d["name"]
            if d.get("arguments"): entry["arguments"] += d["arguments"]
        return collected

    def test_normal_indexed(self):
        r = self._accumulate([
            {"index": 0, "id": "c1", "name": "file", "arguments": '{"p":'},
            {"index": 0, "id": "c1", "name": "", "arguments": '"f.py"}'},
            {"index": 1, "id": "c2", "name": "grep", "arguments": '{"q":"x"}'},
        ])
        assert len(r) == 2
        assert r[0]["arguments"] == '{"p":"f.py"}'

    def test_none_index_gets_sequential_slots(self):
        r = self._accumulate([
            {"index": None, "id": "ca", "name": "tool_a", "arguments": "{}"},
            {"index": None, "id": "cb", "name": "tool_b", "arguments": "{}"},
        ])
        assert len(r) == 2
        names = {v["name"] for v in r.values()}
        assert names == {"tool_a", "tool_b"}

    def test_missing_id_gets_fallback(self):
        r = self._accumulate([{"index": 0, "id": None, "name": "tool", "arguments": "{}"}])
        assert r[0]["id"].startswith("call_")

    def test_split_name_accumulates(self):
        r = self._accumulate([
            {"index": 0, "id": "c1", "name": "my_", "arguments": ""},
            {"index": 0, "id": "c1", "name": "tool", "arguments": "{}"},
        ])
        assert r[0]["name"] == "my_tool"
