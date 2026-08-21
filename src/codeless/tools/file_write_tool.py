"""File writing tool."""

from __future__ import annotations

import difflib
from pathlib import Path

from pydantic import BaseModel, Field

from codeless.abb.virtualization import resolve_virtual_path
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class FileWriteToolInput(BaseModel):
    """Arguments for the file write tool."""

    path: str = Field(description="Path of the file to write")
    content: str = Field(description="Full file contents")
    create_directories: bool = Field(default=True)


class FileWriteTool(BaseTool):
    """Write complete file contents."""

    name = "write_file"
    description = "Create or overwrite a text file in the local repository."
    input_model = FileWriteToolInput

    async def execute(
        self,
        arguments: FileWriteToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)

        from codeless.sandbox.session import is_docker_sandbox_active

        if is_docker_sandbox_active():
            from codeless.sandbox.path_validator import validate_sandbox_path

            allowed, reason = validate_sandbox_path(path, context.cwd)
            if not allowed:
                return ToolResult(output=f"Sandbox: {reason}", is_error=True)

        from codeless.abb.hooks.bridge import (
            post_tool_use_abb_handler,
            pre_tool_use_abb_guard,
        )

        allowed, reason = pre_tool_use_abb_guard("write_file", arguments.model_dump(), context.cwd)
        if not allowed:
            return ToolResult(output=reason, is_error=True)

        approval_prompt = context.metadata.get("edit_approval_prompt") if context.metadata else None
        if approval_prompt is not None:
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            diff_text, added, removed = _compute_diff(str(path), original, arguments.content)
            reply = await approval_prompt(str(path), diff_text, added, removed)
            if reply == "reject":
                return ToolResult(output=f"Write rejected by user: {path}", is_error=True)
            if arguments.create_directories:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments.content, encoding="utf-8")
            stats = f"  ({_ANSI_GREEN}+{added}{_ANSI_RESET} {_ANSI_RED}-{removed}{_ANSI_RESET})"
            result = ToolResult(output=f"Wrote {path}{stats}")
            post_tool_use_abb_handler("write_file", arguments.model_dump(), result, context.cwd)
            return result

        if arguments.create_directories:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments.content, encoding="utf-8")
        result = ToolResult(output=f"Wrote {path}")
        post_tool_use_abb_handler("write_file", arguments.model_dump(), result, context.cwd)
        return result


def _resolve_path(base: Path, candidate: str) -> Path:
    return resolve_virtual_path(base, candidate)


def _compute_diff(filename: str, original: str, updated: str) -> tuple[str, int, int]:
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=filename,
            tofile=filename,
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return "".join(diff_lines), added, removed


_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"
