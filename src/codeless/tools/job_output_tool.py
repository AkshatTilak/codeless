"""Tool for reading task output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeless.jobs.manager import get_task_manager
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class JobOutputToolInput(BaseModel):
    """Arguments for task output retrieval."""

    task_id: str = Field(description="Task identifier")
    max_bytes: int = Field(default=12000, ge=1, le=100000)


class JobOutputTool(BaseTool):
    """Read the output of a background task."""

    name = "task_output"
    description = "Read the output log for a background task."
    input_model = JobOutputToolInput

    def is_read_only(self, arguments: JobOutputToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: JobOutputToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            output = get_task_manager().read_task_output(arguments.task_id, max_bytes=arguments.max_bytes)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=output or "(no output)")
