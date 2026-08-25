"""Built-in tool registration and canonical tool suite."""

from __future__ import annotations

from codeless.tools.abb_tool import AbbTool
from codeless.tools.agent_tool import AgentTool
from codeless.tools.ask_user_question_tool import AskUserQuestionTool
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from codeless.tools.bash_tool import BashTool
from codeless.tools.config_tool import ConfigTool
from codeless.tools.cron_tool import CronTool
from codeless.tools.file_tool import FileTool
from codeless.tools.glob_tool import GlobTool
from codeless.tools.grep_tool import GrepTool
from codeless.tools.image_tool import ImageTool
from codeless.tools.lsp_tool import LspTool
from codeless.tools.mcp_tool import McpTool, McpToolAdapter
from codeless.tools.skill_tool import SkillTool
from codeless.tools.task_tool import TaskTool
from codeless.tools.todo_write_tool import TodoWriteTool
from codeless.tools.tool_search_tool import ToolSearchTool
from codeless.tools.web_tool import WebTool
from codeless.tools.worktree_tool import WorktreeTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the canonical tool registry containing multi-action powerhouses."""
    registry = ToolRegistry()

    canonical_tools = (
        BashTool(),
        FileTool(),
        GlobTool(),
        GrepTool(),
        LspTool(),
        WebTool(),
        TaskTool(),
        CronTool(),
        WorktreeTool(),
        AgentTool(),
        AbbTool(),
        ImageTool(),
        McpTool(mcp_manager),
        AskUserQuestionTool(),
        SkillTool(),
        TodoWriteTool(),
        ToolSearchTool(),
        ConfigTool(),
    )
    for tool in canonical_tools:
        registry.register(tool)

    if mcp_manager is not None:
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "AbbTool",
    "AgentTool",
    "AskUserQuestionTool",
    "BaseTool",
    "BashTool",
    "ConfigTool",
    "CronTool",
    "FileTool",
    "GlobTool",
    "GrepTool",
    "ImageTool",
    "LspTool",
    "McpTool",
    "SkillTool",
    "TaskTool",
    "TodoWriteTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSearchTool",
    "WebTool",
    "WorktreeTool",
    "create_default_tool_registry",
]
