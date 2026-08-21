"""Unified local cron job management tool."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from codeless.services.cron import (
    delete_cron_job,
    load_cron_jobs,
    set_job_enabled,
    upsert_cron_job,
    validate_cron_expression,
    validate_timezone,
)
from codeless.services.cron_scheduler import is_scheduler_running
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class CronToolInput(BaseModel):
    """Arguments for cron operations."""

    action: Literal["create", "list", "delete", "toggle"] = Field(
        default="list",
        description="Cron operation to perform: 'create', 'list', 'delete', or 'toggle'.",
    )
    name: str | None = Field(
        default=None, description="Unique cron job name (required for create, delete, toggle)."
    )
    schedule: str | None = Field(
        default=None,
        description="Cron schedule expression (e.g. '*/5 * * * *', '0 9 * * 1-5') (required for create).",
    )
    command: str | None = Field(
        default=None, description="Shell command to run when triggered (for create)."
    )
    message: str | None = Field(
        default=None, description="Instruction for an agent_turn cron job (for create)."
    )
    timezone: str | None = Field(
        default=None, description="IANA timezone for interpreting cron schedule (for create)."
    )
    cwd: str | None = Field(
        default=None, description="Optional working directory override (for create)."
    )
    enabled: bool | None = Field(
        default=True, description="Whether the job is active (for create, toggle)."
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Optional payload for agent_turn jobs.",
    )
    notify: dict[str, Any] | None = Field(
        default=None,
        description="Optional notification target (e.g. {'type': 'feishu_dm', 'user_open_id': 'ou_xxx'}).",
    )


class CronTool(BaseTool):
    """Manage local cron-style jobs with actions: create, list, delete, toggle."""

    name = "cron"
    description = (
        "Manage scheduled cron jobs. Actions:\n"
        "- 'list': List all configured cron jobs with next run time and status (read-only).\n"
        "- 'create': Create or replace a cron job (requires name, schedule, and command or message).\n"
        "- 'delete': Delete an existing cron job by name.\n"
        "- 'toggle': Enable or disable a cron job by name (requires enabled=True/False)."
    )
    input_model = CronToolInput

    def is_read_only(self, arguments: CronToolInput) -> bool:
        return arguments.action == "list"

    async def execute(self, arguments: CronToolInput, context: ToolExecutionContext) -> ToolResult:
        action = arguments.action

        if action == "list":
            return self._execute_list()

        if action == "create":
            return self._execute_create(arguments, context)

        if action == "delete":
            return self._execute_delete(arguments)

        if action == "toggle":
            return self._execute_toggle(arguments)

        return ToolResult(output=f"Unsupported cron action: {action}", is_error=True)

    def _execute_list(self) -> ToolResult:
        jobs = load_cron_jobs()
        if not jobs:
            return ToolResult(output="No cron jobs configured.")

        scheduler = "running" if is_scheduler_running() else "stopped"
        lines = [f"Scheduler: {scheduler}", ""]

        for job in jobs:
            enabled = "on" if job.get("enabled", True) else "off"
            last_run = job.get("last_run", "never")
            if last_run != "never":
                last_run = last_run[:19]
            next_run = job.get("next_run", "n/a")
            if next_run != "n/a":
                next_run = next_run[:19]
            last_status = job.get("last_status", "")
            status_str = f" ({last_status})" if last_status else ""
            notify = job.get("notify")
            notify_line = ""
            if isinstance(notify, dict):
                notify_type = notify.get("type", "?")
                target = (
                    notify.get("user_open_id")
                    or notify.get("open_id")
                    or notify.get("chat_id")
                    or "?"
                )
                notify_line = f"\n     notify: {notify_type} -> {target}"
            timezone = f" ({job['timezone']})" if job.get("timezone") else ""
            payload = job.get("payload")
            payload_line = ""
            if isinstance(payload, dict):
                payload_line = f"\n     payload: {payload.get('kind', 'agent_turn')} -> {payload.get('channel', '?')}:{payload.get('to', '?')}"
            command = job.get("command") or "(agent_turn)"
            lines.append(
                f"[{enabled}] {job['name']}  {job.get('schedule', '?')}{timezone}\n"
                f"     cmd: {command}"
                f"{payload_line}"
                f"{notify_line}\n"
                f"     last: {last_run}{status_str}  next: {next_run}"
            )
        return ToolResult(output="\n".join(lines))

    def _execute_create(
        self, arguments: CronToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if not arguments.name:
            return ToolResult(output="Cron create requires 'name'.", is_error=True)
        if not arguments.schedule:
            return ToolResult(output="Cron create requires 'schedule'.", is_error=True)
        if not validate_cron_expression(arguments.schedule):
            return ToolResult(
                output=(
                    f"Invalid cron expression: {arguments.schedule!r}\n"
                    "Use standard 5-field format: minute hour day month weekday\n"
                    "Examples: '*/5 * * * *' (every 5 min), '0 9 * * 1-5' (weekdays 9am)"
                ),
                is_error=True,
            )
        if not validate_timezone(arguments.timezone):
            return ToolResult(output=f"Invalid timezone: {arguments.timezone!r}", is_error=True)

        payload = dict(arguments.payload or {})
        if arguments.message:
            payload.setdefault("kind", "agent_turn")
            payload.setdefault("message", arguments.message)
        if arguments.notify is not None:
            payload.setdefault("deliver", True)
            if str(arguments.notify.get("type") or "").strip().lower() == "feishu_dm":
                payload.setdefault("channel", "feishu")
                payload.setdefault(
                    "to", arguments.notify.get("user_open_id") or arguments.notify.get("open_id")
                )

        if payload and not payload.get("message") and not arguments.command:
            return ToolResult(
                output="Cron job requires payload.message, message, or command.", is_error=True
            )
        if not payload and not arguments.command:
            return ToolResult(output="Cron job requires command or message.", is_error=True)

        is_enabled = arguments.enabled if arguments.enabled is not None else True
        job = {
            "name": arguments.name,
            "schedule": arguments.schedule,
            "cwd": arguments.cwd or str(context.cwd),
            "enabled": is_enabled,
        }
        if arguments.timezone:
            job["timezone"] = arguments.timezone
        if arguments.command is not None:
            job["command"] = arguments.command
        if payload:
            payload.setdefault("kind", "agent_turn")
            job["payload"] = payload
        if arguments.notify is not None:
            job["notify"] = arguments.notify

        upsert_cron_job(job)
        status = "enabled" if is_enabled else "disabled"
        return ToolResult(
            output=f"Created cron job '{arguments.name}' [{arguments.schedule}] ({status})"
        )

    def _execute_delete(self, arguments: CronToolInput) -> ToolResult:
        if not arguments.name:
            return ToolResult(output="Cron delete requires 'name'.", is_error=True)
        if not delete_cron_job(arguments.name):
            return ToolResult(output=f"Cron job not found: {arguments.name}", is_error=True)
        return ToolResult(output=f"Deleted cron job {arguments.name}")

    def _execute_toggle(self, arguments: CronToolInput) -> ToolResult:
        if not arguments.name:
            return ToolResult(output="Cron toggle requires 'name'.", is_error=True)
        if arguments.enabled is None:
            return ToolResult(
                output="Cron toggle requires 'enabled' (True or False).", is_error=True
            )
        if not set_job_enabled(arguments.name, arguments.enabled):
            return ToolResult(output=f"Cron job not found: {arguments.name}", is_error=True)
        state = "enabled" if arguments.enabled else "disabled"
        return ToolResult(output=f"Cron job '{arguments.name}' is now {state}")
