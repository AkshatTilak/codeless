"""ABB Lifecycle Hook Bridge for intercepting tool execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeless.abb.hooks.dag_guard import check_dag_dependencies
from codeless.abb.hooks.frontmatter import parse_frontmatter, validate_task_frontmatter
from codeless.abb.hooks.rollup import rollup_task_completion
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import verify_subtask_gate
from codeless.abb.virtualization import is_abb_path, resolve_virtual_path


def _extract_bash_write_targets(command: str) -> list[str]:
    """
    Extract file/dir paths being modified by a bash command.
    Detects redirects (>, >>), rm, mv, cp, mkdir, touch, tee.
    """
    import re

    targets: list[str] = []
    # Match redirects > or >>
    redirect_matches = re.findall(r"(?:>>?)\s*([^\s;&|]+)", command)
    for m in redirect_matches:
        clean = m.strip("'\"")
        if clean and clean not in {"/dev/null", "&1", "&2"}:
            targets.append(clean)

    # Match commands like touch, rm, mkdir, cp, mv, tee
    for part in re.split(r"[;&|]+", command):
        tokens = part.strip().split()
        if not tokens:
            continue
        cmd = tokens[0].lower()
        if cmd in {"touch", "mkdir", "rm", "rmdir"}:
            for tok in tokens[1:]:
                if not tok.startswith("-"):
                    targets.append(tok.strip("'\""))
        elif cmd in {"cp", "mv"}:
            args = [tok.strip("'\"") for tok in tokens[1:] if not tok.startswith("-")]
            if args:
                targets.append(args[-1])
        elif cmd == "tee":
            for tok in tokens[1:]:
                if not tok.startswith("-"):
                    targets.append(tok.strip("'\""))
    return targets


def _is_general_state_mutation(command: str) -> bool:
    """Detect non-file-targeted state modifications like package managers or git commit/push."""
    import re

    mutation_patterns = [
        r"\bgit\s+(add|commit|push|merge|rebase|reset|restore)\b",
        r"\b(npm|pnpm|yarn|bun)\s+(install|add|remove|uninstall|update)\b",
        r"\b(pip|uv|poetry|cargo)\s+(install|add|remove)\b",
    ]
    for pat in mutation_patterns:
        if re.search(pat, command, re.IGNORECASE):
            return True
    return False


def pre_tool_use_abb_guard(
    tool_name: str,
    arguments: dict[str, Any],
    cwd: Path,
) -> tuple[bool, str]:
    """
    Validate tool invocations before execution.
    Returns (allowed, error_reason).
    """
    if tool_name == "bash":
        command = str(arguments.get("command", "")).strip()
        if not command:
            return True, "OK"

        engine = get_mode_engine()
        mode = engine.current_mode

        if mode == TriMode.AGENT:
            return True, "OK"

        # Check general mutations (git commit, npm install, etc.)
        if _is_general_state_mutation(command):
            if mode in {TriMode.ASK, TriMode.PLAN, TriMode.GOVERNANCE}:
                return (
                    False,
                    f"ABB Mode Permission Blocked: Bash command alters repository/package state, which is disallowed in {mode.value.upper()} mode.",
                )

        # Extract file write targets
        write_targets = _extract_bash_write_targets(command)
        if mode == TriMode.ASK and write_targets:
            return (
                False,
                f"ABB Mode Permission Blocked: ASK mode is strictly read-only; bash command writes to {', '.join(write_targets)}.",
            )

        for target in write_targets:
            target_str = str(target).strip()
            # Only ignore external OS temp files if they are not inside the active project workspace
            if target_str.startswith("/tmp/") or target_str.startswith("/var/tmp/"):
                try:
                    target_p = Path(target_str).resolve()
                    cwd_p = Path(cwd).resolve()
                    if not target_p.is_relative_to(cwd_p):
                        continue
                except Exception:
                    pass

            allowed, reason = engine.evaluate_write_permission(target, cwd)
            if not allowed:
                return False, f"ABB Mode Permission Blocked: {reason}"

        return True, "OK"

    if tool_name not in {"write_file", "edit_file"}:
        return True, "OK"

    raw_path = arguments.get("path")
    if not raw_path:
        return True, "OK"

    path_str = str(raw_path).replace("\\", "/").strip()

    # 0. Mode Permission Check
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
