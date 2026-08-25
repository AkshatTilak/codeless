"""Unified background task management and execution tool."""

from __future__ import annotations

import asyncio
import os
from typing import Literal

from pydantic import BaseModel, Field

from codeless.jobs.manager import get_task_manager
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskToolInput(BaseModel):
    """Arguments for background task and execution operations."""

    action: Literal["create", "get", "list", "stop", "output", "update", "sleep"] = Field(
        default="list",
        description="Task operation: 'create', 'get', 'list', 'stop', 'output', 'update', or 'sleep'.",
    )
    task_id: str | None = Field(
        default=None, description="Task identifier (required for get, stop, output, update)."
    )
    type: str = Field(
        default="local_bash", description="Task type for creation: 'local_bash' or 'local_agent'."
    )
    description: str | None = Field(
        default=None, description="Short task description (for create or update)."
    )
    command: str | None = Field(
        default=None, description="Shell command for local_bash task (for create)."
    )
    prompt: str | None = Field(
        default=None, description="Prompt for local_agent task (for create)."
    )
    model: str | None = Field(
        default=None, description="Model override for local_agent task (for create)."
    )
    max_bytes: int = Field(
        default=12000, ge=1, le=100000, description="Max log bytes to read (for output)."
    )
    status: str | None = Field(default=None, description="Updated status string (for update).")
    seconds: float = Field(
        default=1.0, ge=0.0, le=60.0, description="Duration in seconds (for action='sleep')."
    )


class TaskTool(BaseTool):
    """Manage background tasks and paused execution."""

    name = "task"
    description = (
        "Manage background tasks, agent jobs, and pauses. Actions:\n"
        "- 'list': List all active and recent background tasks (read-only).\n"
        "- 'get': Get full status and details for a specific task_id (read-only).\n"
        "- 'output': Read log output for a specific task_id (read-only).\n"
        "- 'create': Spawn a background shell or local agent task.\n"
        "- 'stop': Cancel or terminate a running task.\n"
        "- 'update': Update task metadata or status.\n"
        "- 'sleep': Pause execution briefly for N seconds (read-only)."
    )
    input_model = TaskToolInput

    def is_read_only(self, arguments: TaskToolInput) -> bool:
        return arguments.action in {"get", "list", "output", "sleep"}

    async def execute(self, arguments: TaskToolInput, context: ToolExecutionContext) -> ToolResult:
        action = arguments.action
        manager = get_task_manager()

        if action == "sleep":
            await asyncio.sleep(arguments.seconds)
            return ToolResult(output=f"Slept for {arguments.seconds} seconds")

        if action == "list":
            tasks = manager.list_tasks()
            if not tasks:
                return ToolResult(output="No background tasks found.")
            lines = [f"Background tasks ({len(tasks)}):", ""]
            for t in tasks:
                lines.append(f"- [{t.id}] {t.status.upper()}: {t.description} (type: {t.type})")
            return ToolResult(output="\n".join(lines))

        if action == "get":
            if not arguments.task_id:
                return ToolResult(output="Task 'get' requires 'task_id'.", is_error=True)
            task = manager.get_task(arguments.task_id)
            if task is None:
                return ToolResult(
                    output=f"No task found with ID: {arguments.task_id}", is_error=True
                )
            return ToolResult(output=str(task))

        if action == "output":
            if not arguments.task_id:
                return ToolResult(output="Task 'output' requires 'task_id'.", is_error=True)
            try:
                output = manager.read_task_output(arguments.task_id, max_bytes=arguments.max_bytes)
            except ValueError as exc:
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=output or "(no output)")

        if action == "create":
            if not arguments.description:
                return ToolResult(output="Task 'create' requires 'description'.", is_error=True)
            if arguments.type == "local_bash":
                if not arguments.command:
                    return ToolResult(
                        output="command is required for local_bash tasks", is_error=True
                    )
                task = await manager.create_shell_task(
                    command=arguments.command,
                    description=arguments.description,
                    cwd=context.cwd,
                )
            elif arguments.type == "local_agent":
                if not arguments.prompt:
                    return ToolResult(
                        output="prompt is required for local_agent tasks", is_error=True
                    )
                try:
                    task = await manager.create_agent_task(
                        prompt=arguments.prompt,
                        description=arguments.description,
                        cwd=context.cwd,
                        model=arguments.model,
                        api_key=os.environ.get("ANTHROPIC_API_KEY"),
                    )
                except ValueError as exc:
                    return ToolResult(output=str(exc), is_error=True)
            else:
                return ToolResult(output=f"Unsupported task type: {arguments.type}", is_error=True)
            return ToolResult(output=f"Created task {task.id} ({task.type})")

        if action == "stop":
            if not arguments.task_id:
                return ToolResult(output="Task 'stop' requires 'task_id'.", is_error=True)
            try:
                task = await manager.stop_task(arguments.task_id)
            except ValueError as exc:
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=f"Stopped task {task.id}")

        if action == "update":
            if not arguments.task_id:
                return ToolResult(output="Task 'update' requires 'task_id'.", is_error=True)
            task = manager.get_task(arguments.task_id)
            if task is None:
                return ToolResult(
                    output=f"No task found with ID: {arguments.task_id}", is_error=True
                )
            if arguments.description:
                task.description = arguments.description
            if arguments.status:
                task.status = arguments.status
            return ToolResult(output=f"Updated task {task.id}")

        return ToolResult(output=f"Unsupported task action: {action}", is_error=True)
