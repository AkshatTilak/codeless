"""Unified local agent task management and communication tool."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from codeless.coordinator.agent_definitions import get_agent_definition
from codeless.hooks import HookEvent
from codeless.jobs import get_task_manager
from codeless.swarm.registry import get_backend_registry
from codeless.swarm.types import TeammateMessage, TeammateSpawnConfig
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent lifecycle and messaging."""

    action: Literal["spawn", "message", "status", "stop"] = Field(
        default="spawn",
        description="Agent operation: 'spawn' to launch a delegated agent, 'message' to send input/instructions to a running agent, 'status' to check agent state, or 'stop' to terminate.",
    )
    description: str | None = Field(
        default=None, description="Short description of the delegated work (for 'spawn')"
    )
    prompt: str | None = Field(
        default=None, description="Full prompt for the local agent (for 'spawn')"
    )
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker', 'abb-governance', 'task-planner')",
    )
    model: str | None = Field(default=None, description="Model override for agent (for 'spawn')")
    command: str | None = Field(default=None, description="Override spawn command (for 'spawn')")
    team: str | None = Field(
        default=None, description="Optional team to attach the agent to (for 'spawn')"
    )
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate (for 'spawn')",
    )

    # Messaging and lifecycle parameters
    task_id: str | None = Field(
        default=None,
        description="Target local agent task_id or swarm agent_id (required for 'message', 'status', 'stop')",
    )
    message: str | None = Field(
        default=None, description="Follow-up message or instruction (required for 'message')"
    )


class AgentTool(BaseTool):
    """Spawn, manage, and communicate with local background agents."""

    name = "agent"
    description = (
        "Spawn and interact with background AI agents. Actions:\n"
        "- 'spawn': Launch a delegated subagent task.\n"
        "- 'message': Send follow-up instructions/input to a running agent.\n"
        "- 'status': Check the execution status of an agent task.\n"
        "- 'stop': Cancel or terminate a running agent task."
    )
    input_model = AgentToolInput

    def is_read_only(self, arguments: AgentToolInput) -> bool:
        return arguments.action == "status"

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.action == "spawn":
            return await self._execute_spawn(arguments, context)
        elif arguments.action == "message":
            return await self._execute_message(arguments)
        elif arguments.action == "status":
            return self._execute_status(arguments)
        elif arguments.action == "stop":
            return await self._execute_stop(arguments)
        return ToolResult(output=f"Unsupported agent action: {arguments.action}", is_error=True)

    async def _execute_spawn(
        self, arguments: AgentToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if not arguments.prompt or not arguments.description:
            return ToolResult(
                output="Agent 'spawn' requires both 'prompt' and 'description'.", is_error=True
            )
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )

        # Look up agent definition if subagent_type is specified
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)
            if agent_def and agent_def.modes:
                try:
                    from codeless.abb.permissions import get_mode_engine

                    current_mode = get_mode_engine().current_mode.value
                    if current_mode not in agent_def.modes:
                        allowed_str = ", ".join(agent_def.modes)
                        return ToolResult(
                            output=f"Agent '{arguments.subagent_type}' cannot be spawned in active mode '{current_mode}'. Required mode(s): {allowed_str}.",
                            is_error=True,
                        )
                except Exception:
                    pass

        # Resolve team and agent name for the swarm backend
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"

        registry = get_backend_registry()
        executor = registry.get_executor("subprocess")

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id="main",
            model=arguments.model or (agent_def.model if agent_def else None),
            command=arguments.command,
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
            task_type=arguments.mode,
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if context.hook_executor is not None:
            manager = get_task_manager()
            unregister = None

            async def _emit_subagent_stop(task_record) -> None:
                nonlocal unregister
                if task_record.id != result.task_id:
                    return
                if unregister is not None:
                    unregister()
                    unregister = None
                await context.hook_executor.execute(
                    HookEvent.SUBAGENT_STOP,
                    {
                        "event": HookEvent.SUBAGENT_STOP.value,
                        "agent_id": result.agent_id,
                        "task_id": result.task_id,
                        "backend_type": result.backend_type,
                        "status": task_record.status,
                        "return_code": task_record.return_code,
                        "description": arguments.description,
                        "subagent_type": arguments.subagent_type or "agent",
                        "team": team,
                        "mode": arguments.mode,
                    },
                )

            unregister = manager.register_completion_listener(_emit_subagent_stop)
            task_record = manager.get_task(result.task_id)
            if task_record is not None and task_record.status in {"completed", "failed", "killed"}:
                await _emit_subagent_stop(task_record)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            ),
            metadata={
                "agent_id": result.agent_id,
                "task_id": result.task_id,
                "backend_type": result.backend_type,
                "description": arguments.description,
            },
        )

    async def _execute_message(self, arguments: AgentToolInput) -> ToolResult:
        if not arguments.task_id or not arguments.message:
            return ToolResult(
                output="Agent 'message' requires both 'task_id' and 'message'.", is_error=True
            )
        if "@" in arguments.task_id:
            registry = get_backend_registry()
            executor = registry.get_executor("subprocess")
            teammate_msg = TeammateMessage(text=arguments.message, from_agent="coordinator")
            try:
                await executor.send_message(arguments.task_id, teammate_msg)
            except Exception as exc:
                logger.error("Failed to send message to %s: %s", arguments.task_id, exc)
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=f"Sent message to agent {arguments.task_id}")

        try:
            await get_task_manager().write_to_task(arguments.task_id, arguments.message)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to task {arguments.task_id}")

    def _execute_status(self, arguments: AgentToolInput) -> ToolResult:
        if not arguments.task_id:
            return ToolResult(output="Agent 'status' requires 'task_id'.", is_error=True)
        task = get_task_manager().get_task(arguments.task_id)
        if task is None:
            return ToolResult(
                output=f"No agent task found with ID: {arguments.task_id}", is_error=True
            )
        return ToolResult(output=f"Agent [{task.id}] {task.status.upper()}: {task.description}")

    async def _execute_stop(self, arguments: AgentToolInput) -> ToolResult:
        if not arguments.task_id:
            return ToolResult(output="Agent 'stop' requires 'task_id'.", is_error=True)
        try:
            task = await get_task_manager().stop_task(arguments.task_id)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Stopped agent task {task.id}")
