"""DAG Dependency Gating hook for ABB task transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeless.abb.hooks.frontmatter import parse_frontmatter


def index_tasks(tasks_dir: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """
    Index all task markdown files within tasks/ directory.
    Returns mapping from task ID and relative path to (path, frontmatter).
    """
    index: dict[str, tuple[Path, dict[str, Any]]] = {}
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return index

    for md_file in tasks_dir.rglob("*.md"):
        # Skip template files
        if "_templates" in md_file.parts:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(content)
            if not fm:
                continue
            task_id = fm.get("id")
            if task_id:
                index[str(task_id).strip()] = (md_file, fm)

            # Also index by relative path (e.g. "v1/sub/01_task.md" and "sub/01_task.md")
            try:
                rel_parts = md_file.relative_to(tasks_dir).parts
                rel = "/".join(rel_parts)
                index[rel] = (md_file, fm)
                index[md_file.name] = (md_file, fm)
                if len(rel_parts) > 1:
                    # e.g., "sub/01_task.md" if inside "v1/sub/01_task.md"
                    sub_rel = "/".join(rel_parts[1:])
                    index.setdefault(sub_rel, (md_file, fm))
                    fm["_version_folder"] = rel_parts[0]
            except ValueError:
                pass
        except Exception:
            continue

    return index



def check_dag_dependencies(
    target_task_id: str,
    target_depends_on: list[str],
    new_status: str,
    tasks_dir: Path,
) -> tuple[bool, str]:
    """
    Validate whether target task can transition to new_status based on DAG dependencies.

    Returns (allowed, reason).
    """
    # Only gating transitions to in_progress or done
    if new_status not in {"in_progress", "done"}:
        return True, "Status transition not gated."

    if not target_depends_on:
        return True, "No dependencies required."

    task_index = index_tasks(tasks_dir)

    unsatisfied: list[str] = []
    missing: list[str] = []

    for dep in target_depends_on:
        dep_key = str(dep).strip()
        if not dep_key:
            continue

        entry = task_index.get(dep_key)
        if entry is None:
            missing.append(dep_key)
            continue

        dep_path, dep_fm = entry
        dep_status = str(dep_fm.get("status", "pending")).strip()
        if dep_status != "done":
            dep_id = dep_fm.get("id", dep_key)
            unsatisfied.append(f"'{dep_id}' (currently '{dep_status}', file: {dep_path.name})")

    if missing:
        return False, f"Missing dependency task(s): {', '.join(missing)}."

    if unsatisfied:
        return False, (
            f"Cannot set task '{target_task_id}' to '{new_status}': "
            f"Unsatisfied dependencies: {', '.join(unsatisfied)}. "
            f"All dependencies must be 'done' first."
        )

    return True, "All dependencies satisfied."
