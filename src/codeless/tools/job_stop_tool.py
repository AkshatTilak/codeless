"""Tool for stopping tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeless.jobs.manager import get_task_manager
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class JobStopToolInput(BaseModel):
    """Arguments for stopping a task."""

    task_id: str = Field(description="Task identifier")


class JobStopTool(BaseTool):
    """Stop a background task."""

    name = "task_stop"
    description = "Stop a background task."
    input_model = JobStopToolInput

    async def execute(self, arguments: JobStopToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            task = await get_task_manager().stop_task(arguments.task_id)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Stopped task {task.id}")
