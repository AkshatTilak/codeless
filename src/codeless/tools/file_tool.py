"""Unified multi-action file operations tool."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from codeless.abb.virtualization import resolve_virtual_path
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class FileToolInput(BaseModel):
    """Arguments for file operations."""

    action: Literal["read", "write", "edit", "notebook_edit"] = Field(
        default="read",
        description="File operation: 'read' (read text file), 'write' (create/overwrite file), 'edit' (replace string in file), or 'notebook_edit' (edit Jupyter cell).",
    )
    path: str = Field(description="Target file path")

    # Read parameters
    offset: int = Field(default=0, ge=0, description="Zero-based starting line for read")
    limit: int = Field(default=200, ge=1, le=2000, description="Max lines to return for read")

    # Write parameters
    content: str | None = Field(default=None, description="Full file contents for write")
    create_directories: bool = Field(
        default=True, description="Auto-create parent directories on write"
    )

    # Edit parameters
    old_str: str | None = Field(default=None, description="Existing text to replace for edit")
    new_str: str | None = Field(default=None, description="Replacement text for edit")
    replace_all: bool = Field(default=False, description="Replace all occurrences if True for edit")

    # Notebook edit parameters
    cell_index: int = Field(default=0, ge=0, description="Zero-based cell index for notebook_edit")
    new_source: str | None = Field(default=None, description="Source code/text for notebook cell")
    cell_type: Literal["code", "markdown"] = Field(
        default="code", description="Cell type for notebook_edit"
    )
    mode: Literal["replace", "append"] = Field(
        default="replace", description="Cell edit mode: replace or append"
    )
    create_if_missing: bool = Field(
        default=True, description="Create notebook if missing on notebook_edit"
    )


class FileTool(BaseTool):
    """Unified tool for reading, writing, editing, and notebook-modifying files."""

    name = "file"
    description = (
        "Perform file operations in the local repository. Actions:\n"
        "- 'read': Read a UTF-8 text file with line numbers (read-only).\n"
        "- 'write': Create or overwrite a text file.\n"
        "- 'edit': Edit an existing file by replacing a specific string.\n"
        "- 'notebook_edit': Create or edit a Jupyter notebook (.ipynb) cell."
    )
    input_model = FileToolInput

    def is_read_only(self, arguments: FileToolInput) -> bool:
        return arguments.action == "read"

    async def execute(
        self,
        arguments: FileToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        path = resolve_virtual_path(context.cwd, arguments.path)

        from codeless.sandbox.session import is_docker_sandbox_active

        if is_docker_sandbox_active():
            from codeless.sandbox.path_validator import validate_sandbox_path

            allowed, reason = validate_sandbox_path(path, context.cwd)
            if not allowed:
                return ToolResult(output=f"Sandbox: {reason}", is_error=True)

        if arguments.action == "read":
            return self._execute_read(path, arguments)
        elif arguments.action == "write":
            return await self._execute_write(path, arguments, context)
        elif arguments.action == "edit":
            return await self._execute_edit(path, arguments, context)
        elif arguments.action == "notebook_edit":
            return await self._execute_notebook_edit(path, arguments, context)
        return ToolResult(output=f"Unsupported file action: {arguments.action}", is_error=True)

    def _execute_read(self, path: Path, arguments: FileToolInput) -> ToolResult:
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        if path.is_dir():
            return ToolResult(output=f"Cannot read directory: {path}", is_error=True)

        raw = path.read_bytes()
        if b"\x00" in raw:
            return ToolResult(output=f"Binary file cannot be read as text: {path}", is_error=True)

        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[arguments.offset : arguments.offset + arguments.limit]
        numbered = [
            f"{arguments.offset + index + 1:>6}\t{line}" for index, line in enumerate(selected)
        ]
        header = f"# File: {path}"
        if not numbered:
            return ToolResult(output=f"{header}\n(no content in selected range for {path})")
        return ToolResult(output=f"{header}\n" + "\n".join(numbered))

    async def _execute_write(
        self, path: Path, arguments: FileToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if arguments.content is None:
            return ToolResult(output="File 'write' action requires 'content'.", is_error=True)

        from codeless.abb.hooks.bridge import (
            post_tool_use_abb_handler,
            pre_tool_use_abb_guard,
        )

        allowed, reason = pre_tool_use_abb_guard("file", arguments.model_dump(), context.cwd)
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
            post_tool_use_abb_handler("file", arguments.model_dump(), result, context.cwd)
            return result

        if arguments.create_directories:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments.content, encoding="utf-8")
        result = ToolResult(output=f"Wrote {path}")
        post_tool_use_abb_handler("file", arguments.model_dump(), result, context.cwd)
        return result

    async def _execute_edit(
        self, path: Path, arguments: FileToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if arguments.old_str is None or arguments.new_str is None:
            return ToolResult(
                output="File 'edit' action requires both 'old_str' and 'new_str'.",
                is_error=True,
            )
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)

        original = path.read_text(encoding="utf-8")
        if arguments.old_str not in original:
            return ToolResult(output="old_str was not found in the file", is_error=True)

        if arguments.replace_all:
            updated = original.replace(arguments.old_str, arguments.new_str)
        else:
            updated = original.replace(arguments.old_str, arguments.new_str, 1)

        from codeless.abb.hooks.bridge import (
            post_tool_use_abb_handler,
            pre_tool_use_abb_guard,
        )

        allowed, reason = pre_tool_use_abb_guard("file", arguments.model_dump(), context.cwd)
        if not allowed:
            return ToolResult(output=reason, is_error=True)

        approval_prompt = context.metadata.get("edit_approval_prompt") if context.metadata else None
        if approval_prompt is not None:
            diff_text, added, removed = _compute_diff(str(path), original, updated)
            reply = await approval_prompt(str(path), diff_text, added, removed)
            if reply == "reject":
                return ToolResult(output=f"Edit rejected by user: {path}", is_error=True)
            path.write_text(updated, encoding="utf-8")
            stats = f"  ({_ANSI_GREEN}+{added}{_ANSI_RESET} {_ANSI_RED}-{removed}{_ANSI_RESET})"
            result = ToolResult(output=f"Updated {path}{stats}")
            post_tool_use_abb_handler("file", arguments.model_dump(), result, context.cwd)
            return result

        path.write_text(updated, encoding="utf-8")
        result = ToolResult(output=f"Updated {path}")
        post_tool_use_abb_handler("file", arguments.model_dump(), result, context.cwd)
        return result

    async def _execute_notebook_edit(
        self, path: Path, arguments: FileToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if arguments.new_source is None:
            return ToolResult(
                output="File 'notebook_edit' action requires 'new_source'.", is_error=True
            )

        from codeless.abb.hooks.bridge import (
            post_tool_use_abb_handler,
            pre_tool_use_abb_guard,
        )

        allowed, reason = pre_tool_use_abb_guard("file", arguments.model_dump(), context.cwd)
        if not allowed:
            return ToolResult(output=reason, is_error=True)

        notebook = _load_notebook(path, create_if_missing=arguments.create_if_missing)
        if notebook is None:
            return ToolResult(output=f"Notebook not found: {path}", is_error=True)

        cells = notebook.setdefault("cells", [])
        while len(cells) <= arguments.cell_index:
            cells.append(_empty_cell(arguments.cell_type))

        cell = cells[arguments.cell_index]
        cell["cell_type"] = arguments.cell_type
        cell.setdefault("metadata", {})
        if arguments.cell_type == "code":
            cell.setdefault("outputs", [])
            cell.setdefault("execution_count", None)

        existing = _normalize_source(cell.get("source", ""))
        updated = (
            arguments.new_source
            if arguments.mode == "replace"
            else f"{existing}{arguments.new_source}"
        )
        cell["source"] = updated

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")
        result = ToolResult(output=f"Updated notebook cell {arguments.cell_index} in {path}")
        post_tool_use_abb_handler("file", arguments.model_dump(), result, context.cwd)
        return result


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


def _load_notebook(path: Path, *, create_if_missing: bool) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not create_if_missing:
        return None
    return {
        "cells": [],
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _empty_cell(cell_type: str) -> dict:
    if cell_type == "markdown":
        return {"cell_type": "markdown", "metadata": {}, "source": ""}
    return {
        "cell_type": "code",
        "metadata": {},
        "source": "",
        "outputs": [],
        "execution_count": None,
    }


def _normalize_source(source: str | list[str]) -> str:
    if isinstance(source, list):
        return "".join(source)
    return str(source)


_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"
