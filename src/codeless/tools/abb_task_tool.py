"""Read-only ABB task query and DAG inspection tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.shadow import resolve_abb_workspace
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class AbbTaskToolInput(BaseModel):
    action: str = Field(
        ...,
        description="Action to perform: 'list', 'show', 'ready', 'blocked-by'",
    )
    target: str | None = Field(
        None,
        description="Task ID or relative path (required for 'show' and 'blocked-by')",
    )


class AbbTaskTool(BaseTool):
    """Tool for programmatically querying ABB tasks and DAG state."""

    name = "abb_task"
    description = (
        "Query and inspect the Agent Buildable Base (ABB) task DAG. "
        "Supported actions: 'list' (all tasks and statuses), 'show' (task details by id or path), "
        "'ready' (subtasks ready for execution with satisfied dependencies), 'blocked-by' (unmet dependencies for a task)."
    )
    input_model = AbbTaskToolInput


    async def execute(
        self,
        context: ToolExecutionContext,
        action: str,
        target: str | None = None,
    ) -> ToolResult:
        cwd = Path(context.cwd).resolve()
        try:
            abb_ws = resolve_abb_workspace(cwd, auto_init=False)
            if not abb_ws.exists() or not (abb_ws / "agent.md").exists():
                return ToolResult(
                    error="No ABB workspace found for this project. Initialize with ABB template first."
                )
        except Exception as exc:
            return ToolResult(error=f"Failed to resolve ABB workspace: {exc}")

        tasks_dir = abb_ws / "tasks"
        raw_index = index_tasks(tasks_dir)
        # Deduplicate to primary IDs
        tasks_index: dict[str, dict[str, Any]] = {}
        for key, (path, fm) in raw_index.items():
            tid = str(fm.get("id", "")).strip()
            if tid and key == tid:
                try:
                    rel_path = str(path.relative_to(abb_ws)).replace("\\", "/")
                except ValueError:
                    rel_path = str(path)
                tasks_index[tid] = {
                    "id": tid,
                    "path": path,
                    "rel_path": rel_path,
                    "status": fm.get("status", "unknown"),
                    "version": fm.get("version", "1.0.0"),
                    "depends_on": fm.get("depends_on", []) or [],
                    "frontmatter": fm,
                }

        act = action.lower().strip()

        if act == "list":
            if not tasks_index:
                return ToolResult(output="No tasks found in ABB workspace.")
            lines = [f"ABB Tasks Index ({len(tasks_index)}):"]
            for tid, tinfo in sorted(tasks_index.items()):
                status = tinfo.get("status", "unknown")
                version = tinfo.get("version", "1.0.0")
                deps = tinfo.get("depends_on", [])
                deps_str = f" [depends_on: {', '.join(deps)}]" if deps else ""
                lines.append(f"  • {tid} (v{version}) - {status}{deps_str} -> {tinfo.get('rel_path')}")
            return ToolResult(output="\n".join(lines))

        elif act == "show":
            if not target:
                return ToolResult(error="Action 'show' requires 'target' (task ID, e.g. 'sub_001').")
            clean_target = target.strip()
            # Lookup by ID
            tinfo = tasks_index.get(clean_target)
            if not tinfo:
                # Lookup by relative path substring
                for tid, info in tasks_index.items():
                    if clean_target in info.get("rel_path", ""):
                        tinfo = info
                        break

            if not tinfo:
                return ToolResult(error=f"Task '{clean_target}' not found in ABB index.")

            full_path: Path = tinfo["path"]
            if not full_path.exists():
                return ToolResult(error=f"Task file '{full_path}' does not exist.")

            content = full_path.read_text(encoding="utf-8")
            return ToolResult(output=f"# Task: {tinfo['id']} ({tinfo['rel_path']})\n\n{content}")

        elif act == "ready":
            # Subtasks whose status is not 'done' and all depends_on are 'done'
            ready_tasks = []
            for tid, tinfo in sorted(tasks_index.items()):
                if tid.startswith("sub_") and tinfo.get("status") != "done":
                    deps = tinfo.get("depends_on", [])
                    deps_satisfied = all(
                        tasks_index.get(dep, {}).get("status") == "done"
                        for dep in deps
                    )
                    if deps_satisfied:
                        ready_tasks.append((tid, tinfo))

            if not ready_tasks:
                return ToolResult(output="No subtasks are currently in 'ready' state.")

            lines = [f"Ready Subtasks ({len(ready_tasks)}):"]
            for tid, tinfo in ready_tasks:
                lines.append(f"  • {tid} ({tinfo.get('rel_path')}) - status: {tinfo.get('status')}")
            return ToolResult(output="\n".join(lines))


        elif act in {"blocked-by", "blocked_by"}:
            if not target:
                return ToolResult(error="Action 'blocked-by' requires 'target' (task ID).")
            clean_target = target.strip()
            tinfo = tasks_index.get(clean_target)
            if not tinfo:
                return ToolResult(error=f"Task '{clean_target}' not found in ABB index.")

            deps = tinfo.get("depends_on", [])
            if not deps:
                return ToolResult(output=f"Task '{clean_target}' has no dependencies (not blocked).")

            unmet = []
            for dep in deps:
                dep_info = tasks_index.get(dep)
                if not dep_info:
                    unmet.append(f"{dep} (missing from index)")
                elif dep_info.get("status") != "done":
                    unmet.append(f"{dep} (current status: {dep_info.get('status')})")

            if not unmet:
                return ToolResult(output=f"Task '{clean_target}' dependencies are all satisfied (not blocked).")

            lines = [f"Task '{clean_target}' is blocked by:"]
            for u in unmet:
                lines.append(f"  • {u}")
            return ToolResult(output="\n".join(lines))

        else:
            return ToolResult(
                error=f"Unknown action '{action}'. Supported actions: 'list', 'show', 'ready', 'blocked-by'"
            )
