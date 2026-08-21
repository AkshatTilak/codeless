"""Tool abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from codeless.hooks.executor import HookExecutor


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""

    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    hook_executor: HookExecutor | None = None


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all Codeless tools."""

    name: str
    description: str
    input_model: type[BaseModel]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema expected by the Anthropic Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._aliases: set[str] = set()

    def register(self, tool: BaseTool, *, is_alias: bool = False) -> None:
        """Register a tool instance, optionally tagging it as a backward-compatibility alias."""
        self._tools[tool.name] = tool
        if is_alias:
            self._aliases.add(tool.name)

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self, *, include_aliases: bool = False) -> list[BaseTool]:
        """Return all registered tools, omitting aliases by default."""
        if include_aliases:
            return list(self._tools.values())
        return [tool for name, tool in self._tools.items() if name not in self._aliases]

    def to_api_schema(
        self, allowed_names: set[str] | list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return tool schemas in API format, omitting aliases unless explicitly allowed."""
        if allowed_names:
            allowed = set(allowed_names)
            return [tool.to_api_schema() for tool in self._tools.values() if tool.name in allowed]
        return [tool.to_api_schema() for tool in self.list_tools(include_aliases=False)]
