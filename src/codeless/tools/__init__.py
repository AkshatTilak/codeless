"""Built-in tool registration."""

from codeless.tools.abb_task_tool import AbbTaskTool
from codeless.tools.abb_verify_tool import AbbVerifyTool
from codeless.tools.ask_user_question_tool import AskUserQuestionTool
from codeless.tools.agent_tool import AgentTool
from codeless.tools.bash_tool import BashTool
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from codeless.tools.brief_tool import BriefTool
from codeless.tools.config_tool import ConfigTool
from codeless.tools.cron_create_tool import CronCreateTool
from codeless.tools.cron_delete_tool import CronDeleteTool
from codeless.tools.cron_list_tool import CronListTool
from codeless.tools.cron_toggle_tool import CronToggleTool
from codeless.tools.enter_worktree_tool import EnterWorktreeTool
from codeless.tools.exit_worktree_tool import ExitWorktreeTool
from codeless.tools.file_edit_tool import FileEditTool
from codeless.tools.file_read_tool import FileReadTool
from codeless.tools.file_write_tool import FileWriteTool
from codeless.tools.glob_tool import GlobTool
from codeless.tools.grep_tool import GrepTool
from codeless.tools.image_generation_tool import ImageGenerationTool
from codeless.tools.image_to_text_tool import ImageToTextTool
from codeless.tools.list_mcp_resources_tool import ListMcpResourcesTool
from codeless.tools.lsp_tool import LspTool
from codeless.tools.mcp_auth_tool import McpAuthTool
from codeless.tools.mcp_tool import McpToolAdapter
from codeless.tools.notebook_edit_tool import NotebookEditTool
from codeless.tools.read_mcp_resource_tool import ReadMcpResourceTool
from codeless.tools.remote_trigger_tool import RemoteTriggerTool
from codeless.tools.send_message_tool import SendMessageTool
from codeless.tools.skill_tool import SkillTool
from codeless.tools.sleep_tool import SleepTool
from codeless.tools.job_create_tool import JobCreateTool
from codeless.tools.job_get_tool import JobGetTool
from codeless.tools.job_list_tool import JobListTool
from codeless.tools.job_output_tool import JobOutputTool
from codeless.tools.job_stop_tool import JobStopTool
from codeless.tools.job_update_tool import JobUpdateTool
from codeless.tools.todo_write_tool import TodoWriteTool
from codeless.tools.tool_search_tool import ToolSearchTool
from codeless.tools.web_fetch_tool import WebFetchTool
from codeless.tools.web_search_tool import WebSearchTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry."""
    registry = ToolRegistry()
    for tool in (
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
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
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
        AgentTool(),
        SendMessageTool(),
        AbbTaskTool(),
        AbbVerifyTool(),
    ):
        registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]

