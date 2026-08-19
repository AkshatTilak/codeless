"""Auto roll-up engine: propagates subtask completions to parent base tasks and system goal."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.hooks.frontmatter import dump_with_frontmatter, parse_frontmatter


def rollup_task_completion(
    subtask_path: Path,
    tasks_dir: Path,
) -> list[str]:
    """
    Check if completing subtask_path completes its parent base task and system goal.
    Updates parent files on disk and returns log of actions taken.
    """
    actions: list[str] = []
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return actions

    task_index = index_tasks(tasks_dir)

    try:
        content = subtask_path.read_text(encoding="utf-8")
    except Exception:
        return actions

    sub_fm, _ = parse_frontmatter(content)
    if sub_fm.get("status") != "done":
        return actions

    parent_id = sub_fm.get("parent")
    sub_id = sub_fm.get("id", subtask_path.name)
    base_dir = tasks_dir / "base"
    sub_dir = tasks_dir / "sub"

    # 1. Locate parent base task
    base_file: Path | None = None
    base_fm: dict[str, Any] = {}
    base_body: str = ""

    if parent_id and str(parent_id) in task_index:
        base_file, base_fm = task_index[str(parent_id)]
    else:
        # Search in tasks/base/ for any base task referencing this subtask
        if base_dir.exists():
            for bf in base_dir.glob("*.md"):
                try:
                    b_content = bf.read_text(encoding="utf-8")
                    b_fm, b_b = parse_frontmatter(b_content)
                    if subtask_path.name in b_content or (parent_id and b_fm.get("id") == parent_id):
                        base_file = bf
                        base_fm = b_fm
                        base_body = b_b
                        break
                except Exception:
                    continue

    if not base_file or not base_file.exists():
        return actions

    if not base_body:
        _, base_body = parse_frontmatter(base_file.read_text(encoding="utf-8"))

    # Update checklist in base task body for this subtask
    sub_pattern = rf"- \[[ xX]\] `(?:sub/)?{re.escape(subtask_path.name)}`"
    new_sub_entry = f"- [x] `sub/{subtask_path.name}`"
    if re.search(sub_pattern, base_body):
        base_body = re.sub(sub_pattern, new_sub_entry, base_body)
        actions.append(f"Checked off `{subtask_path.name}` in parent `{base_file.name}`")

    # Check if all subtasks for this base task are done
    base_id = base_fm.get("id", base_file.name)
    all_subtasks_done = True
    sub_count = 0

    sub_dir = tasks_dir / "sub"
    if sub_dir.exists():
        for sf in sub_dir.glob("*.md"):
            try:
                s_content = sf.read_text(encoding="utf-8")
                s_fm, _ = parse_frontmatter(s_content)
                if s_fm.get("parent") == base_id or sf.name in base_body:
                    sub_count += 1
                    if s_fm.get("status") != "done":
                        all_subtasks_done = False
                        break
            except Exception:
                continue

    if sub_count > 0 and all_subtasks_done and base_fm.get("status") != "done":
        base_fm["status"] = "done"
        actions.append(f"All {sub_count} subtasks complete: Marked base task `{base_file.name}` as `status: done`")

    # Save updated base task
    updated_base_content = dump_with_frontmatter(base_fm, base_body)
    base_file.write_text(updated_base_content, encoding="utf-8")

    # 2. If base task is done, check goal roll-up
    if base_fm.get("status") == "done":
        goal_dir = tasks_dir / "goal"
        if goal_dir.exists():
            for gf in goal_dir.glob("*.md"):
                try:
                    g_content = gf.read_text(encoding="utf-8")
                    g_fm, g_body = parse_frontmatter(g_content)

                    # Update checklist in goal body
                    base_pat = rf"- \[[ xX]\] `(?:base/)?{re.escape(base_file.name)}`"
                    new_base_entry = f"- [x] `base/{base_file.name}`"
                    if re.search(base_pat, g_body):
                        g_body = re.sub(base_pat, new_base_entry, g_body)
                        actions.append(f"Checked off `{base_file.name}` in `{gf.name}`")

                    # Check if all base tasks are done
                    base_files = list(base_dir.glob("*.md")) if base_dir.exists() else []
                    all_base_done = True
                    for b_chk in base_files:
                        b_chk_fm, _ = parse_frontmatter(b_chk.read_text(encoding="utf-8"))
                        if b_chk_fm.get("status") != "done":
                            all_base_done = False
                            break

                    if base_files and all_base_done and g_fm.get("status") != "done":
                        g_fm["status"] = "done"
                        actions.append(f"All base tasks complete: Marked system goal `{gf.name}` as `status: done`!")

                    gf.write_text(dump_with_frontmatter(g_fm, g_body), encoding="utf-8")
                except Exception:
                    continue

    return actions
