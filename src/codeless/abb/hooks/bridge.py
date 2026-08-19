"""ABB Lifecycle Hook Bridge for intercepting tool execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeless.abb.hooks.dag_guard import check_dag_dependencies
from codeless.abb.hooks.frontmatter import parse_frontmatter, validate_task_frontmatter
from codeless.abb.hooks.rollup import rollup_task_completion
from codeless.abb.permissions import get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import verify_subtask_gate
from codeless.abb.virtualization import is_abb_path, resolve_virtual_path


def pre_tool_use_abb_guard(
    tool_name: str,
    arguments: dict[str, Any],
    cwd: Path,
) -> tuple[bool, str]:
    """
    Validate tool invocations before execution.
    Returns (allowed, error_reason).
    """
    if tool_name not in {"write_file", "edit_file"}:
        return True, "OK"

    raw_path = arguments.get("path")
    if not raw_path:
        return True, "OK"

    path_str = str(raw_path).replace("\\", "/").strip()

    # 0. Mode Permission Check (Plan / Agent / Ask)
    mode_allowed, mode_reason = get_mode_engine().evaluate_write_permission(raw_path, cwd)
    if not mode_allowed:
        return False, f"ABB Mode Permission Blocked: {mode_reason}"

    # Check if target is a task file
    if not is_abb_path(path_str) or ("tasks/" not in path_str and not path_str.startswith("tasks")):
        return True, "OK"

    # Skip template files
    if "_templates" in path_str:
        return True, "OK"

    resolved = resolve_virtual_path(cwd, raw_path)
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    tasks_dir = abb_ws / "tasks"

    # Get proposed content
    proposed_content: str = ""
    if tool_name == "write_file":
        proposed_content = arguments.get("content", "")
    elif tool_name == "edit_file":
        if not resolved.exists():
            return True, "File does not exist yet"
        original = resolved.read_text(encoding="utf-8")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")
        if old_str not in original:
            return True, "Old string not found; tool will handle error"
        proposed_content = original.replace(old_str, new_str, 1)

    if not proposed_content.strip():
        return True, "OK"

    # 1. Validate frontmatter schema
    fm, _ = parse_frontmatter(proposed_content)
    schema_errors = validate_task_frontmatter(fm, resolved)
    if schema_errors:
        bullet_list = "\n".join(f"  - {err}" for err in schema_errors)
        return False, f"ABB Task Frontmatter Validation Failed for '{raw_path}':\n{bullet_list}"

    # 2. Check DAG dependencies
    new_status = fm.get("status", "pending")
    task_id = fm.get("id", resolved.name)
    depends_on = fm.get("depends_on", [])
    allowed, dag_reason = check_dag_dependencies(task_id, depends_on, new_status, tasks_dir)
    if not allowed:
        return False, f"ABB DAG Dependency Blocked: {dag_reason}"

    # 3. Two-Track Verification Gate (when transitioning a subtask to 'done')
    if new_status == "done" and "tasks/sub" in str(resolved).replace("\\", "/"):
        ver_passed, ver_reason, _ = verify_subtask_gate(task_id, cwd, abb_ws)
        if not ver_passed:
            return False, f"ABB Verification Gate Blocked: {ver_reason}"

    return True, "OK"


def post_tool_use_abb_handler(
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    cwd: Path,
) -> list[str]:
    """
    Handle post-tool-use lifecycle actions such as task completion roll-up.
    Returns list of action messages.
    """
    if tool_name not in {"write_file", "edit_file"}:
        return []

    # If tool failed, do nothing
    if getattr(result, "is_error", False):
        return []

    raw_path = arguments.get("path")
    if not raw_path:
        return []

    path_str = str(raw_path).replace("\\", "/").strip()
    if not is_abb_path(path_str):
        return []

    resolved = resolve_virtual_path(cwd, raw_path)
    abb_ws = resolve_abb_workspace(cwd, auto_init=False)
    tasks_dir = abb_ws / "tasks"

    actions: list[str] = []
    # If a subtask was written or edited, trigger roll-up
    if "tasks/sub" in str(resolved).replace("\\", "/"):
        actions = rollup_task_completion(resolved, tasks_dir)

    return actions
