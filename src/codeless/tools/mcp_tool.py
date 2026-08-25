"""Unified Model Context Protocol (MCP) management and resource tool."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from codeless.config.settings import load_settings, save_settings
from codeless.mcp.client import McpClientManager, McpServerNotConnectedError, McpToolInfo
from codeless.mcp.types import McpHttpServerConfig, McpStdioServerConfig, McpWebSocketServerConfig
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class McpToolInput(BaseModel):
    """Arguments for MCP operations."""

    action: Literal["list", "read", "auth", "status"] = Field(
        default="list",
        description="MCP operation: 'list' (enumerate resources), 'read' (read resource content), 'auth' (configure server credentials), or 'status' (server connection status).",
    )
    server: str | None = Field(
        default=None, description="MCP server name (required for 'read', 'auth', 'status')."
    )
    uri: str | None = Field(default=None, description="Resource URI (required for 'read').")
    mode: str | None = Field(
        default=None, description="Auth mode: 'bearer', 'header', or 'env' (required for 'auth')."
    )
    value: str | None = Field(
        default=None, description="Secret token or key value to persist (required for 'auth')."
    )
    key: str | None = Field(
        default=None, description="Header or environment variable key override (for 'auth')."
    )


class McpTool(BaseTool):
    """Inspect, read, configure, and authenticate with Model Context Protocol (MCP) servers."""

    name = "mcp"
    description = (
        "Manage MCP resources and server authentication. Actions:\n"
        "- 'list': Enumerate all available resources across connected MCP servers (read-only).\n"
        "- 'read': Read content of a specific resource by server name and URI (read-only).\n"
        "- 'status': Check connection and tool status for MCP servers (read-only).\n"
        "- 'auth': Configure authentication credentials for an MCP server."
    )
    input_model = McpToolInput

    def __init__(self, manager: McpClientManager | None = None) -> None:
        self._manager = manager

    def is_read_only(self, arguments: McpToolInput) -> bool:
        return arguments.action in {"list", "read", "status"}

    async def execute(self, arguments: McpToolInput, context: ToolExecutionContext) -> ToolResult:
        manager = self._manager or (
            context.metadata.get("mcp_manager") if hasattr(context, "metadata") else None
        )

        if arguments.action == "list":
            if manager is None:
                return ToolResult(output="(no MCP manager available)")
            resources = manager.list_resources()
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
                    output="MCP 'read' requires both 'server' and 'uri'.", is_error=True
                )
            if manager is None:
                return ToolResult(output="No MCP manager connected.", is_error=True)
            try:
                output = await manager.read_resource(arguments.server, arguments.uri)
            except McpServerNotConnectedError as exc:
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=output)

        if arguments.action == "status":
            if manager is None:
                return ToolResult(output="No MCP manager active.")
            tools = manager.list_tools()
            resources = manager.list_resources()
            return ToolResult(
                output=f"MCP Status: {len(tools)} tools registered, {len(resources)} resources available."
            )

        if arguments.action == "auth":
            return await self._execute_auth(arguments, manager)

        return ToolResult(output=f"Unsupported mcp action: {arguments.action}", is_error=True)

    async def _execute_auth(
        self, arguments: McpToolInput, manager: McpClientManager | None
    ) -> ToolResult:
        if not arguments.server or not arguments.mode or arguments.value is None:
            return ToolResult(
                output="MCP 'auth' requires 'server', 'mode', and 'value'.", is_error=True
            )

        settings = load_settings()
        config = settings.mcp_servers.get(arguments.server)
        if config is None and manager is not None:
            getter = getattr(manager, "get_server_config", None)
            if callable(getter):
                config = getter(arguments.server)
        if config is None:
            return ToolResult(output=f"Unknown MCP server: {arguments.server}", is_error=True)

        if isinstance(config, McpStdioServerConfig):
            if arguments.mode not in {"env", "bearer"}:
                return ToolResult(
                    output="stdio MCP auth supports 'env' or 'bearer' modes", is_error=True
                )
            env_key = arguments.key or "MCP_AUTH_TOKEN"
            env = dict(config.env or {})
            env[env_key] = (
                f"Bearer {arguments.value}" if arguments.mode == "bearer" else arguments.value
            )
            updated = config.model_copy(update={"env": env})
        elif isinstance(config, (McpHttpServerConfig, McpWebSocketServerConfig)):
            if arguments.mode not in {"header", "bearer"}:
                return ToolResult(
                    output="http/ws MCP auth supports 'header' or 'bearer' modes", is_error=True
                )
            header_key = arguments.key or "Authorization"
            headers = dict(config.headers)
            headers[header_key] = (
                f"Bearer {arguments.value}"
                if arguments.mode == "bearer" and header_key == "Authorization"
                else arguments.value
            )
            updated = config.model_copy(update={"headers": headers})
        else:
            return ToolResult(output="Unsupported MCP server config type", is_error=True)

        settings.mcp_servers[arguments.server] = updated
        save_settings(settings)

        if manager is not None:
            try:
                manager.update_server_config(arguments.server, updated)
                await manager.reconnect_all()
            except Exception as exc:
                return ToolResult(
                    output=f"Saved MCP auth for {arguments.server}, but reconnect failed: {exc}",
                    is_error=True,
                )

        return ToolResult(output=f"Saved MCP auth for {arguments.server}")


def _json_type_to_python(schema: dict[str, Any]) -> Any:
    """Map a JSON Schema type descriptor to a Python type annotation."""
    js_type = schema.get("type")
    if js_type == "string":
        return str
    if js_type == "integer":
        return int
    if js_type == "number":
        return float
    if js_type == "boolean":
        return bool
    if js_type == "array":
        return list
    if js_type == "object":
        return dict
    return Any


def _input_model_from_schema(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    """Generate a Pydantic model dynamically from an MCP tool's JSON Schema."""
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        py_type = _json_type_to_python(prop_schema)
        description = prop_schema.get("description", "")
        if prop_name in required_fields:
            field_definitions[prop_name] = (py_type, Field(..., description=description))
        else:
            field_definitions[prop_name] = (py_type | None, Field(None, description=description))

    clean_name = "".join(part.capitalize() for part in tool_name.replace("-", "_").split("_"))
    return create_model(f"{clean_name}Input", **field_definitions)


class McpToolAdapter(BaseTool):
    """Adapter wrapping an MCP server tool into a Codeless BaseTool."""

    def __init__(self, manager: McpClientManager, tool_info: McpToolInfo) -> None:
        self._manager = manager
        self._server_name = tool_info.server_name
        self._tool_name = tool_info.name
        clean_server = tool_info.server_name.replace(":", "_")
        self.name = f"mcp__{clean_server}__{tool_info.name}"
        self.description = tool_info.description or f"MCP tool from {tool_info.server_name}"
        self.input_model = _input_model_from_schema(tool_info.name, tool_info.input_schema)

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        del context
        args_dict = arguments.model_dump(mode="json", exclude_none=True)
        try:
            output = await self._manager.call_tool(self._server_name, self._tool_name, args_dict)
            return ToolResult(output=output)
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)
