"""Built-in tool registration."""

from __future__ import annotations

from codeless.tools.abb_task_tool import AbbTaskTool
from codeless.tools.abb_verify_tool import AbbVerifyTool
from codeless.tools.agent_tool import AgentTool
from codeless.tools.ask_user_question_tool import AskUserQuestionTool
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from codeless.tools.bash_tool import BashTool
from codeless.tools.brief_tool import BriefTool
from codeless.tools.config_tool import ConfigTool
from codeless.tools.cron_create_tool import CronCreateTool
from codeless.tools.cron_delete_tool import CronDeleteTool
from codeless.tools.cron_list_tool import CronListTool
from codeless.tools.cron_toggle_tool import CronToggleTool
from codeless.tools.cron_tool import CronTool
from codeless.tools.enter_worktree_tool import EnterWorktreeTool
from codeless.tools.exit_worktree_tool import ExitWorktreeTool
from codeless.tools.file_edit_tool import FileEditTool
from codeless.tools.file_read_tool import FileReadTool
from codeless.tools.file_write_tool import FileWriteTool
from codeless.tools.glob_tool import GlobTool
from codeless.tools.grep_tool import GrepTool
from codeless.tools.image_generation_tool import ImageGenerationTool
from codeless.tools.image_to_text_tool import ImageToTextTool
from codeless.tools.job_create_tool import JobCreateTool
from codeless.tools.job_get_tool import JobGetTool
from codeless.tools.job_list_tool import JobListTool
from codeless.tools.job_output_tool import JobOutputTool
from codeless.tools.job_stop_tool import JobStopTool
from codeless.tools.job_update_tool import JobUpdateTool
from codeless.tools.list_mcp_resources_tool import ListMcpResourcesTool
from codeless.tools.lsp_tool import LspTool
from codeless.tools.mcp_auth_tool import McpAuthTool
from codeless.tools.mcp_resource_tool import McpResourceTool
from codeless.tools.mcp_tool import McpToolAdapter
from codeless.tools.notebook_edit_tool import NotebookEditTool
from codeless.tools.read_mcp_resource_tool import ReadMcpResourceTool
from codeless.tools.remote_trigger_tool import RemoteTriggerTool
from codeless.tools.send_message_tool import SendMessageTool
from codeless.tools.skill_tool import SkillTool
from codeless.tools.sleep_tool import SleepTool
from codeless.tools.task_tool import TaskTool
from codeless.tools.todo_write_tool import TodoWriteTool
from codeless.tools.tool_search_tool import ToolSearchTool
from codeless.tools.web_fetch_tool import WebFetchTool
from codeless.tools.web_search_tool import WebSearchTool
from codeless.tools.web_tool import WebTool
from codeless.tools.worktree_tool import WorktreeTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry with consolidated primary tools and backward-compatible aliases."""
    registry = ToolRegistry()

    # Primary consolidated & core tools exposed to LLM agents
    primary_tools = (
        BashTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        NotebookEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        ImageToTextTool(),
        ImageGenerationTool(),
        SkillTool(),
        ToolSearchTool(),
        WebTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        WorktreeTool(),
        TodoWriteTool(),
        CronTool(),
        TaskTool(),
        AgentTool(),
        SendMessageTool(),
        AbbTaskTool(),
        AbbVerifyTool(),
    )
    for tool in primary_tools:
        registry.register(tool)

    # Backward-compatible alias tools (accessible via registry.get(), excluded from API schema)
    alias_tools = (
        WebFetchTool(),
        WebSearchTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
        CronToggleTool(),
        RemoteTriggerTool(),
        JobCreateTool(),
        JobGetTool(),
        JobListTool(),
        JobStopTool(),
        JobOutputTool(),
        JobUpdateTool(),
    )
    for tool in alias_tools:
        registry.register(tool, is_alias=True)

    if mcp_manager is not None:
        registry.register(McpResourceTool(mcp_manager))
        registry.register(ListMcpResourcesTool(mcp_manager), is_alias=True)
        registry.register(ReadMcpResourceTool(mcp_manager), is_alias=True)
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "BaseTool",
    "CronTool",
    "McpResourceTool",
    "TaskTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "WebTool",
    "WorktreeTool",
    "create_default_tool_registry",
]
