"""Unified git worktree management tool."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult

_GIT_TIMEOUT_SECONDS = 30.0


def _resolve_git() -> str:
    """Find a usable git executable, including common Windows install locations."""
    which = shutil.which("git")
    if which:
        return which

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    candidates = [
        Path(local_app_data) / "Programs" / "Git" / "cmd" / "git.exe",
        Path(local_app_data) / "Programs" / "Git" / "bin" / "git.exe",
        Path(program_files) / "Git" / "cmd" / "git.exe",
        Path(program_files) / "Git" / "bin" / "git.exe",
        Path(program_files_x86) / "Git" / "cmd" / "git.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "git"


def _run_git_safe(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute git safely with DEVNULL stdin and bounded timeout."""
    git_bin = _resolve_git()
    try:
        return subprocess.run(
            [git_bin, *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=[git_bin, *args],
            returncode=-1,
            stdout="",
            stderr=f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_SECONDS} seconds",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=[git_bin, *args],
            returncode=-1,
            stdout="",
            stderr=f"Failed to execute git: {exc}",
        )


class WorktreeToolInput(BaseModel):
    """Arguments for worktree operations."""

    action: Literal["enter", "exit", "list"] = Field(
        default="list",
        description="Worktree operation: 'enter' (create/enter worktree), 'exit' (remove worktree), or 'list'.",
    )
    branch: str | None = Field(
        default=None, description="Target branch name for the worktree (for enter)."
    )
    path: str | None = Field(default=None, description="Worktree path (for enter or exit).")
    create_branch: bool = Field(
        default=True, description="Whether to create the branch if it does not exist (for enter)."
    )
    base_ref: str = Field(
        default="HEAD", description="Base ref when creating a new branch (for enter)."
    )


class WorktreeTool(BaseTool):
    """Manage git worktrees with actions: enter, exit, list."""

    name = "worktree"
    description = (
        "Manage git worktrees for isolated parallel feature development. Actions:\n"
        "- 'list': List all active git worktrees (read-only).\n"
        "- 'enter': Create or enter an isolated worktree for a branch.\n"
        "- 'exit': Remove an existing worktree by path."
    )
    input_model = WorktreeToolInput

    def is_read_only(self, arguments: WorktreeToolInput) -> bool:
        return arguments.action == "list"

    async def execute(
        self, arguments: WorktreeToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        return await asyncio.to_thread(self._execute_sync, arguments, context)

    def _execute_sync(
        self, arguments: WorktreeToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        action = arguments.action

        if action == "list":
            return self._execute_list(context.cwd)

        if action == "enter":
            return self._execute_enter(arguments, context)

        if action == "exit":
            return self._execute_exit(arguments, context)

        return ToolResult(output=f"Unsupported worktree action: {action}", is_error=True)

    def _execute_list(self, cwd: Path) -> ToolResult:
        top_level = _git_output(cwd, "rev-parse", "--show-toplevel")
        if top_level is None:
            return ToolResult(output="worktree requires a git repository", is_error=True)
        res = _run_git_safe(["worktree", "list"], cwd=Path(top_level))
        if res.returncode != 0:
            return ToolResult(output=(res.stderr or res.stdout).strip(), is_error=True)
        return ToolResult(output=(res.stdout or "(no worktrees)").strip())

    def _execute_enter(
        self, arguments: WorktreeToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if not arguments.branch:
            return ToolResult(output="Worktree enter requires 'branch'.", is_error=True)
        top_level = _git_output(context.cwd, "rev-parse", "--show-toplevel")
        if top_level is None:
            return ToolResult(output="enter_worktree requires a git repository", is_error=True)

        repo_root = Path(top_level)
        worktree_path = _resolve_worktree_path(repo_root, arguments.branch, arguments.path)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["worktree", "add"]
        if arguments.create_branch:
            cmd.extend(["-b", arguments.branch, str(worktree_path), arguments.base_ref])
        else:
            cmd.extend([str(worktree_path), arguments.branch])
        result = _run_git_safe(cmd, cwd=repo_root)
        output = (result.stdout or result.stderr).strip() or f"Created worktree {worktree_path}"
        if result.returncode != 0:
            return ToolResult(output=output, is_error=True)
        return ToolResult(output=f"{output}\nPath: {worktree_path}")

    def _execute_exit(
        self, arguments: WorktreeToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        if not arguments.path:
            return ToolResult(output="Worktree exit requires 'path'.", is_error=True)
        path = Path(arguments.path).expanduser()
        if not path.is_absolute():
            path = (context.cwd / path).resolve()
        result = _run_git_safe(
            ["worktree", "remove", "--force", str(path)],
            cwd=context.cwd,
        )
        output = (result.stdout or result.stderr).strip() or f"Removed worktree {path}"
        return ToolResult(output=output, is_error=result.returncode != 0)


def _git_output(cwd: Path, *args: str) -> str | None:
    result = _run_git_safe(list(args), cwd=cwd)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _resolve_worktree_path(repo_root: Path, branch: str, path: str | None) -> Path:
    if path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = repo_root / resolved
        return resolved.resolve()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "worktree"
    return (repo_root / ".codeless" / "worktrees" / slug).resolve()
