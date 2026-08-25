"""Unified Agent Buildable Base (ABB) task and verification tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import execute_verification_manifest, parse_verification_manifest
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class AbbToolInput(BaseModel):
    """Arguments for ABB task DAG queries and verification."""

    action: Literal["list", "show", "ready", "blocked_by", "blocked-by", "verify"] = Field(
        default="list",
        description="ABB operation: 'list' (all tasks and statuses), 'show' (task details by id/path), 'ready' (unblocked tasks ready for execution), 'blocked_by' (unmet dependencies for a task), or 'verify' (run Two-Track test verification).",
    )
    target: str | None = Field(
        default=None,
        description="Task ID or relative path (required for 'show' and 'blocked_by').",
    )
    dry_run: bool = Field(
        default=False,
        description="Preview verification commands without executing (for 'verify').",
    )
    include_lint: bool = Field(
        default=False,
        description="Whether to also run lint track commands (for 'verify').",
    )
    include_typecheck: bool = Field(
        default=False,
        description="Whether to also run typecheck track commands (for 'verify').",
    )


class AbbTool(BaseTool):
    """Unified tool for querying ABB tasks DAG and executing Two-Track verification."""

    name = "abb"
    description = (
        "Query ABB task DAG state and run Two-Track test verification. Actions:\n"
        "- 'list': Enumerate all tasks, statuses, versions, and dependencies.\n"
        "- 'show': Display full markdown content and details for a specific task ID.\n"
        "- 'ready': List subtasks ready for execution whose dependencies are satisfied.\n"
        "- 'blocked_by': List unmet blocker dependencies for a specific task.\n"
        "- 'verify': Run Track 1 (unit) and Track 2 (system) verification from STACK.md."
    )
    input_model = AbbToolInput

    def is_read_only(self, arguments: AbbToolInput) -> bool:
        return True

    async def execute(
        self,
        arguments: AbbToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        cwd = Path(context.cwd).resolve()
        try:
            abb_ws = resolve_abb_workspace(cwd, auto_init=False)
            if not abb_ws.exists() or not (abb_ws / "agent.md").exists():
                return ToolResult(
                    output="No ABB workspace found for this project. Initialize with ABB template first.",
                    is_error=True,
                )
        except Exception as exc:
            return ToolResult(output=f"Failed to resolve ABB workspace: {exc}", is_error=True)

        act = arguments.action.lower().strip()

        if act == "verify":
            return await self._execute_verify(abb_ws, cwd, arguments)
        else:
            return self._execute_task_query(abb_ws, act, arguments.target)

    def _execute_task_query(self, abb_ws: Path, action: str, target: str | None) -> ToolResult:
        tasks_dir = abb_ws / "tasks"
        raw_index = index_tasks(tasks_dir)
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

        if action == "list":
            if not tasks_index:
                return ToolResult(output="No tasks found in ABB workspace.")
            lines = [f"ABB Tasks Index ({len(tasks_index)}):"]
            for tid, tinfo in sorted(tasks_index.items()):
                status = tinfo.get("status", "unknown")
                version = tinfo.get("version", "1.0.0")
                deps = tinfo.get("depends_on", [])
                deps_str = f" [depends_on: {', '.join(deps)}]" if deps else ""
                lines.append(
                    f"  • {tid} (v{version}) - {status}{deps_str} -> {tinfo.get('rel_path')}"
                )
            return ToolResult(output="\n".join(lines))

        elif action == "show":
            if not target:
                return ToolResult(
                    output="Action 'show' requires 'target' (task ID, e.g. 'sub_001').",
                    is_error=True,
                )
            clean_target = target.strip()
            tinfo = tasks_index.get(clean_target)
            if not tinfo:
                for tid, info in tasks_index.items():
                    if clean_target in info.get("rel_path", ""):
                        tinfo = info
                        break

            if not tinfo:
                return ToolResult(
                    output=f"Task '{clean_target}' not found in ABB index.", is_error=True
                )

            full_path: Path = tinfo["path"]
            if not full_path.exists():
                return ToolResult(output=f"Task file '{full_path}' does not exist.", is_error=True)

            content = full_path.read_text(encoding="utf-8")
            return ToolResult(output=f"# Task: {tinfo['id']} ({tinfo['rel_path']})\n\n{content}")

        elif action == "ready":
            ready_tasks = []
            for tid, tinfo in sorted(tasks_index.items()):
                if tid.startswith("sub_") and tinfo.get("status") != "done":
                    deps = tinfo.get("depends_on", [])
                    deps_satisfied = all(
                        tasks_index.get(dep, {}).get("status") == "done" for dep in deps
                    )
                    if deps_satisfied:
                        ready_tasks.append((tid, tinfo))

            if not ready_tasks:
                return ToolResult(output="No subtasks are currently in 'ready' state.")

            lines = [f"Ready Subtasks ({len(ready_tasks)}):"]
            for tid, tinfo in ready_tasks:
                lines.append(f"  • {tid} ({tinfo.get('rel_path')}) - status: {tinfo.get('status')}")
            return ToolResult(output="\n".join(lines))

        elif action in {"blocked_by", "blocked-by"}:
            if not target:
                return ToolResult(
                    output="Action 'blocked_by' requires 'target' (task ID).", is_error=True
                )
            clean_target = target.strip()
            tinfo = tasks_index.get(clean_target)
            if not tinfo:
                return ToolResult(
                    output=f"Task '{clean_target}' not found in ABB index.", is_error=True
                )

            deps = tinfo.get("depends_on", [])
            if not deps:
                return ToolResult(
                    output=f"Task '{clean_target}' has no dependencies (not blocked)."
                )

            unmet = []
            for dep in deps:
                dep_info = tasks_index.get(dep)
                if not dep_info:
                    unmet.append(f"{dep} (missing from index)")
                elif dep_info.get("status") != "done":
                    unmet.append(f"{dep} (current status: {dep_info.get('status')})")

            if not unmet:
                return ToolResult(
                    output=f"Task '{clean_target}' dependencies are all satisfied (not blocked)."
                )

            lines = [f"Task '{clean_target}' is blocked by:"]
            for u in unmet:
                lines.append(f"  • {u}")
            return ToolResult(output="\n".join(lines))

        return ToolResult(
            output=f"Unknown ABB action '{action}'. Supported: 'list', 'show', 'ready', 'blocked_by', 'verify'",
            is_error=True,
        )

    async def _execute_verify(self, abb_ws: Path, cwd: Path, arguments: AbbToolInput) -> ToolResult:
        stack_file = abb_ws / "STACK.md"
        if not stack_file.exists():
            return ToolResult(
                output="No STACK.md found in ABB workspace. Cannot run verification.",
                is_error=True,
            )

        manifest = parse_verification_manifest(stack_file)
        if not manifest.track_1 and not manifest.track_2:
            return ToolResult(
                output="No verification manifest commands configured under 'verification:' in STACK.md."
            )

        if arguments.dry_run:
            lines = ["# Two-Track Verification Manifest (Dry-Run Preview)", ""]
            lines.append(f"**Track 1 (Unit)**: {len(manifest.track_1)} command(s)")
            for cmd in manifest.track_1:
                lines.append(f"  • `{cmd}`")
            lines.append(f"\n**Track 2 (System/E2E)**: {len(manifest.track_2)} command(s)")
            for cmd in manifest.track_2:
                lines.append(f"  • `{cmd}`")
            if manifest.lint:
                lines.append(f"\n**Lint Track**: {len(manifest.lint)} command(s)")
                for cmd in manifest.lint:
                    lines.append(f"  • `{cmd}`")
            if manifest.typecheck:
                lines.append(f"\n**Typecheck Track**: {len(manifest.typecheck)} command(s)")
                for cmd in manifest.typecheck:
                    lines.append(f"  • `{cmd}`")
            return ToolResult(output="\n".join(lines))

        report = await execute_verification_manifest(
            manifest,
            cwd=cwd,
            include_lint=arguments.include_lint,
            include_typecheck=arguments.include_typecheck,
        )

        status_str = "PASSED ✅" if report.success else "FAILED ❌"
        lines = [f"# Verification Report: {status_str}", f"Summary: {report.summary}", ""]

        def _format_reports(title: str, reports):
            if not reports:
                return
            lines.append(f"### {title}")
            for r in reports:
                r_status = "✅ Pass" if r.success else f"❌ Fail (exit {r.exit_code})"
                lines.append(f"- `{r.command}`: {r_status} ({r.duration_seconds:.2f}s)")
                if not r.success:
                    if r.stderr.strip():
                        lines.append(f"  **Stderr**:\n```\n{r.stderr.strip()[:1500]}\n```")
                    if r.stdout.strip():
                        lines.append(f"  **Stdout**:\n```\n{r.stdout.strip()[:1500]}\n```")

        _format_reports("Track 1 (Unit Tests)", report.track_1_reports)
        _format_reports("Track 2 (System Tests)", report.track_2_reports)
        _format_reports("Lint Checks", report.lint_reports)
        _format_reports("Type Checks", report.typecheck_reports)

        return ToolResult(output="\n".join(lines))
