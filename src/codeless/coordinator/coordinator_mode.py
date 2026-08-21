"""Coordinator mode detection and orchestration support."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape, unescape

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TaskNotification:
    """Structured result from a completed agent task."""

    task_id: str
    status: str
    summary: str
    result: Optional[str] = None
    usage: Optional[dict[str, int]] = None


@dataclass
class WorkerConfig:
    """Configuration for a spawned worker agent."""

    agent_id: str
    name: str
    prompt: str
    model: Optional[str] = None
    color: Optional[str] = None
    team: Optional[str] = None


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

_USAGE_FIELDS = ("total_tokens", "tool_uses", "duration_ms")


def format_task_notification(n: TaskNotification) -> str:
    """Serialize a TaskNotification to the canonical XML envelope."""
    parts = [
        "<task-notification>",
        f"<task-id>{escape(n.task_id)}</task-id>",
        f"<status>{escape(n.status)}</status>",
        f"<summary>{escape(n.summary)}</summary>",
    ]
    if n.result is not None:
        parts.append(f"<result>{escape(n.result)}</result>")
    if n.usage:
        parts.append("<usage>")
        for key in _USAGE_FIELDS:
            if key in n.usage:
                parts.append(f"  <{key}>{n.usage[key]}</{key}>")
        parts.append("</usage>")
    parts.append("</task-notification>")
    return "\n".join(parts)


def parse_task_notification(xml: str) -> TaskNotification:
    """Parse a <task-notification> XML string into a TaskNotification."""

    def _extract(tag: str) -> Optional[str]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
        return unescape(m.group(1).strip()) if m else None

    task_id = _extract("task-id") or ""
    status = _extract("status") or ""
    summary = _extract("summary") or ""
    result = _extract("result")

    usage: Optional[dict[str, int]] = None
    usage_block = re.search(r"<usage>(.*?)</usage>", xml, re.DOTALL)
    if usage_block:
        usage = {}
        for key in _USAGE_FIELDS:
            m = re.search(rf"<{key}>(\d+)</{key}>", usage_block.group(1))
            if m:
                usage[key] = int(m.group(1))

    return TaskNotification(
        task_id=task_id,
        status=status,
        summary=summary,
        result=result,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# CoordinatorMode
# ---------------------------------------------------------------------------

_AGENT_TOOL_NAME = "agent"
_SEND_MESSAGE_TOOL_NAME = "send_message"
_TASK_STOP_TOOL_NAME = "task_stop"

_WORKER_TOOLS = [
    "bash",
    "read_file",
    "edit_file",
    "write_file",
    "glob",
    "grep",
    "web_fetch",
    "web_search",
    "task_create",
    "task_get",
    "task_list",
    "task_output",
    "skill",
    "abb_task",
    "abb_verify",
]

_SIMPLE_WORKER_TOOLS = ["bash", "read_file", "edit_file"]


def is_coordinator_mode() -> bool:
    """Return True when the process is running in coordinator mode."""
    val = os.environ.get("CLAUDE_CODE_COORDINATOR_MODE", "")
    return val.lower() in {"1", "true", "yes"}


def match_session_mode(session_mode: Optional[str]) -> Optional[str]:
    """Align the env-var coordinator flag with a resumed session's stored mode.

    Returns a warning string if the mode was switched, or None if no change.
    """
    if not session_mode:
        return None

    current_is_coordinator = is_coordinator_mode()
    session_is_coordinator = session_mode == "coordinator"

    if current_is_coordinator == session_is_coordinator:
        return None

    if session_is_coordinator:
        os.environ["CLAUDE_CODE_COORDINATOR_MODE"] = "1"
    else:
        os.environ.pop("CLAUDE_CODE_COORDINATOR_MODE", None)

    if session_is_coordinator:
        return "Entered coordinator mode to match resumed session."
    return "Exited coordinator mode to match resumed session."


def get_coordinator_tools() -> list[str]:
    """Return the tool names reserved for the coordinator."""
    return [_AGENT_TOOL_NAME, _SEND_MESSAGE_TOOL_NAME, _TASK_STOP_TOOL_NAME]


def get_coordinator_user_context(
    mcp_clients: list[dict[str, str]] | None = None,
    scratchpad_dir: Optional[str] = None,
) -> dict[str, str]:
    """Build the workerToolsContext injected into the coordinator's user turn."""
    if not is_coordinator_mode():
        return {}

    is_simple = os.environ.get("CLAUDE_CODE_SIMPLE", "").lower() in {"1", "true", "yes"}
    tools = sorted(_SIMPLE_WORKER_TOOLS if is_simple else _WORKER_TOOLS)
    worker_tools_str = ", ".join(tools)

    content = (
        f"Workers spawned via the {_AGENT_TOOL_NAME} tool have access to these tools: "
        f"{worker_tools_str}"
    )

    if mcp_clients:
        server_names = ", ".join(c["name"] for c in mcp_clients)
        content += (
            f"\n\nWorkers also have access to MCP tools from connected MCP servers: {server_names}"
        )

    if scratchpad_dir:
        content += (
            f"\n\nScratchpad directory: {scratchpad_dir}\n"
            "Workers can read and write here without permission prompts. "
            "Use this for durable cross-worker knowledge — structure files however fits the work."
        )

    return {"workerToolsContext": content}


def get_coordinator_system_prompt() -> str:
    """Return the coordinator dispatch overlay injected when running in coordinator mode."""
    return f"""# Coordinator Dispatch Overlay

You are operating in **Coordinator Mode**. You orchestrate tasks across multiple workers rather than performing low-level edits directly.

## 1. Coordinator Role & Protocol
- Direct workers to research, implement, and verify changes.
- Synthesize worker findings and communicate with the user.
- Answer questions directly when possible without unneeded delegation.
- Messages you produce are addressed to the user. Worker results and system notifications are internal signals.

## 2. Tools
- **{_AGENT_TOOL_NAME}** - Spawn a new worker
- **{_SEND_MESSAGE_TOOL_NAME}** - Continue an existing worker (send a follow-up to its `to` agent ID)
- **{_TASK_STOP_TOOL_NAME}** - Stop a running worker

### {_AGENT_TOOL_NAME} Notifications
Worker results arrive as user-role messages containing `<task-notification>` XML:
```xml
<task-notification>
<task-id>{{agentId}}</task-id>
<status>completed|failed|killed</status>
<summary>{{human-readable status summary}}</summary>
<result>{{agent's final text response}}</result>
<usage>
  <total_tokens>N</total_tokens>
  <tool_uses>N</tool_uses>
  <duration_ms>N</duration_ms>
</usage>
</task-notification>
```
Use {_SEND_MESSAGE_TOOL_NAME} with that `<task-id>` value as `to` to continue that worker.

## 3. Concurrency & Synthesis Rules
- **Parallelism**: Launch independent workers concurrently when researching across multiple angles.
- **Synthesis**: Always synthesize worker research before giving implementation instructions. Include specific file paths, line numbers, and exact requirements.
- **Context Reuse**: Continue workers when follow-up edits overlap with their existing context; spawn fresh workers for independent tasks or unbiased verification."""


def build_worker_system_prompt(
    settings: Any,
    cwd: str | Path,
    subagent_type: str = "worker",
    assigned_skills: list[str] | None = None,
    context_package: str | None = None,
) -> str:
    """Compose a focused prompt for a subagent worker."""
    from codeless.prompts.system_prompt import build_system_prompt

    sections = [build_system_prompt(cwd=str(cwd))]

    try:
        from codeless.abb.permissions import get_mode_engine

        mode_engine = get_mode_engine()
        persona = mode_engine.get_persona_instructions(Path(cwd))
        if persona:
            sections.append(persona)
    except Exception:
        pass

    if assigned_skills:
        skill_lines = ["# Assigned Skills"]
        for s in assigned_skills:
            skill_lines.append(f"- `{s}`")
        sections.append("\n".join(skill_lines))

    if context_package:
        sections.append(f"# Task Context\n\n{context_package}")

    return "\n\n".join(s for s in sections if s.strip())
