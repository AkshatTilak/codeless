"""Unified MCP resource management tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from codeless.mcp.client import McpClientManager, McpServerNotConnectedError
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class McpResourceToolInput(BaseModel):
    """Arguments for MCP resource operations."""

    action: Literal["list", "read"] = Field(
        default="list",
        description="Operation to perform: 'list' to enumerate resources or 'read' to fetch resource content.",
    )
    server: str | None = Field(default=None, description="MCP server name (required for 'read').")
    uri: str | None = Field(default=None, description="Resource URI (required for 'read').")


class McpResourceTool(BaseTool):
    """Inspect and read MCP resources from connected MCP servers."""

    name = "mcp_resource"
    description = (
        "Manage MCP resources. Actions:\n"
        "- 'list': Enumerate all available resources across connected MCP servers.\n"
        "- 'read': Read content of a specific resource by server name and URI."
    )
    input_model = McpResourceToolInput

    def __init__(self, manager: McpClientManager) -> None:
        self._manager = manager

    def is_read_only(self, arguments: McpResourceToolInput) -> bool:
        del arguments
        return True

    async def execute(
        self, arguments: McpResourceToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        del context
        if arguments.action == "list":
            resources = self._manager.list_resources()
            if not resources:
                return ToolResult(output="(no MCP resources)")
            return ToolResult(
                output="\n".join(
                    f"{item.server_name}:{item.uri} {item.description}".strip()
                    for item in resources
                )
            )

        if arguments.action == "read":
            if not arguments.server or not arguments.uri:
                return ToolResult(
                    output="MCP resource 'read' requires both 'server' and 'uri'.", is_error=True
                )
            try:
                output = await self._manager.read_resource(arguments.server, arguments.uri)
            except McpServerNotConnectedError as exc:
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=output)

        return ToolResult(
            output=f"Unsupported mcp_resource action: {arguments.action}", is_error=True
        )
