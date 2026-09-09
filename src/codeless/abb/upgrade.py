"""ABB workspace upgrade engine.

Migrates legacy flat ABB workspaces (tasks/base, tasks/sub, tasks/goal) to the
versioned task architecture (tasks/<version>/) with numbered base tasks,
automated link preservation & healing, safety backups, and dry-run preview capabilities.
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeless.abb.shadow import get_abb_template_dir
from codeless.abb.virtualization import find_project_root


@dataclass
class UpgradePlan:
    """Detailed plan for upgrading an ABB workspace."""

    abb_ws: Path
    target_version: str
    is_legacy_flat: bool
    is_already_versioned: bool
    goals_to_move: list[tuple[Path, Path]] = field(default_factory=list)  # (src, dst)
    base_tasks_to_move: list[tuple[Path, Path]] = field(default_factory=list)  # (src, dst)
    subtasks_to_move: list[tuple[Path, Path]] = field(default_factory=list)  # (src, dst)
    base_task_rename_map: dict[str, str] = field(default_factory=dict)  # old_name -> new_name
    files_with_links_to_update: list[Path] = field(default_factory=list)
    template_files_to_sync: list[tuple[Path, Path]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.goals_to_move
            or self.base_tasks_to_move
            or self.subtasks_to_move
            or self.template_files_to_sync
        )


@dataclass
class UpgradeResult:
    """Outcome of applying an upgrade plan."""

    success: bool
    target_version: str
    backup_dir: Path | None
    moved_goals: int
    moved_base_tasks: int
    moved_subtasks: int
    updated_files: int
    healed_links: int
    error: str | None = None


def detect_workspace_task_layout(abb_ws: Path) -> dict[str, Any]:
    """Inspect tasks directory structure to determine layout status."""
    tasks_dir = abb_ws / "tasks"
    if not tasks_dir.exists():
        return {
            "exists": False,
            "is_legacy_flat": False,
            "is_versioned": False,
            "version_folders": [],
            "flat_folders": [],
        }

    flat_folders = []
    for sub in ["base", "sub", "goal"]:
        if (tasks_dir / sub).is_dir():
            flat_folders.append(sub)

    version_folders = []
    for child in tasks_dir.iterdir():
        if child.is_dir() and child.name not in {"base", "sub", "goal", "_templates"}:
            if (child / "base").exists() or (child / "sub").exists() or (child / "goal").exists():
                version_folders.append(child.name)

    is_legacy_flat = len(flat_folders) > 0
    is_versioned = len(version_folders) > 0

    return {
        "exists": True,
        "is_legacy_flat": is_legacy_flat,
        "is_versioned": is_versioned,
        "version_folders": sorted(version_folders),
        "flat_folders": sorted(flat_folders),
    }


def compute_base_task_numbering(base_task_files: list[Path]) -> dict[str, str]:
    """
    Compute numbered filenames for base tasks.

    Preserves existing 2-digit prefixes (e.g. 01_foo.md).
    Extracts number from frontmatter id (e.g. id: base_013 -> 13_name.md).
    Falls back to deterministic sequencing.
    """
    rename_map: dict[str, str] = {}
    used_numbers: set[int] = set()
    unassigned: list[tuple[Path, str]] = []

    # First pass: check existing number prefixes
    for p in sorted(base_task_files, key=lambda x: x.name):
        m = re.match(r"^(\d{2})_(.*\.md)$", p.name)
        if m:
            num = int(m.group(1))
            used_numbers.add(num)
            rename_map[p.name] = p.name

    # Second pass: check frontmatter IDs
    for p in sorted(base_task_files, key=lambda x: x.name):
        if p.name in rename_map:
            continue

        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            content = ""

        # Check for id: base_013 or id: base_13 or id: 13
        m_id = re.search(r"(?m)^id:\s*(?:base_)?0*(\d+)\s*$", content)
        if m_id:
            num = int(m_id.group(1))
            if num > 0 and num not in used_numbers:
                used_numbers.add(num)
                new_name = f"{num:02d}_{p.name}"
                rename_map[p.name] = new_name
                continue

        unassigned.append((p, p.name))

    # Third pass: assign remaining unassigned deterministically
    next_num = 1
    for p, old_name in unassigned:
        while next_num in used_numbers:
            next_num += 1
        used_numbers.add(next_num)
        new_name = f"{next_num:02d}_{old_name}"
        rename_map[old_name] = new_name

    return rename_map


def create_workspace_backup(abb_ws: Path) -> Path:
    """Create a full safety backup of the ABB workspace before applying migration."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    parent_dir = abb_ws.parent
    backup_base = parent_dir / "backups"
    backup_base.mkdir(parents=True, exist_ok=True)

    backup_dir = backup_base / f"upgrade-{now_str}"
    shutil.copytree(
        abb_ws,
        backup_dir,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    return backup_dir


def plan_upgrade(abb_ws: Path, target_version: str = "v1") -> UpgradePlan:
    """
    Analyze workspace and formulate a complete upgrade plan without touching disk.
    """
    layout = detect_workspace_task_layout(abb_ws)
    tasks_dir = abb_ws / "tasks"
    target_v_dir = tasks_dir / target_version

    plan = UpgradePlan(
        abb_ws=abb_ws,
        target_version=target_version,
        is_legacy_flat=layout["is_legacy_flat"],
        is_already_versioned=layout["is_versioned"] and not layout["is_legacy_flat"],
    )

    if not layout["exists"]:
        plan.notes.append("No tasks directory found in workspace.")
        return plan

    if plan.is_already_versioned:
        plan.notes.append(
            f"Workspace is already versioned ({', '.join(layout['version_folders'])}). "
            f"No legacy flat tasks to upgrade."
        )
        return plan

    if not plan.is_legacy_flat:
        plan.notes.append("No legacy flat tasks (base, sub, goal) detected.")
        return plan

    # 1. Base tasks
    legacy_base = tasks_dir / "base"
    base_files = list(legacy_base.glob("*.md")) if legacy_base.is_dir() else []
    rename_map = compute_base_task_numbering(base_files)
    plan.base_task_rename_map = rename_map

    target_base_dir = target_v_dir / "base"
    for src in sorted(base_files, key=lambda x: x.name):
        new_name = rename_map.get(src.name, src.name)
        dst = target_base_dir / new_name
        plan.base_tasks_to_move.append((src, dst))

    # 2. Subtasks
    legacy_sub = tasks_dir / "sub"
    sub_files = list(legacy_sub.glob("*.md")) if legacy_sub.is_dir() else []
    target_sub_dir = target_v_dir / "sub"
    for src in sorted(sub_files, key=lambda x: x.name):
        dst = target_sub_dir / src.name
        plan.subtasks_to_move.append((src, dst))

    # 3. Goal
    legacy_goal = tasks_dir / "goal"
    goal_files = list(legacy_goal.glob("*.md")) if legacy_goal.is_dir() else []
    target_goal_dir = target_v_dir / "goal"
    for src in sorted(goal_files, key=lambda x: x.name):
        dst = target_goal_dir / src.name
        plan.goals_to_move.append((src, dst))

    # 4. Template synchronization (tasks/_templates and tasks/tasks.md)
    template_src_dir = get_abb_template_dir()
    if template_src_dir.exists():
        tpl_tasks_md = template_src_dir / "tasks" / "tasks.md"
        if tpl_tasks_md.exists():
            plan.template_files_to_sync.append((tpl_tasks_md, tasks_dir / "tasks.md"))

        tpl_subtemplates = template_src_dir / "tasks" / "_templates"
        if tpl_subtemplates.exists():
            for t_file in tpl_subtemplates.glob("*.md"):
                plan.template_files_to_sync.append((t_file, tasks_dir / "_templates" / t_file.name))

    # 5. Files with links that will need updating
    for p in abb_ws.rglob("*.md"):
        plan.files_with_links_to_update.append(p)

    return plan


def apply_upgrade(
    abb_ws: Path,
    plan: UpgradePlan,
    create_backup: bool = True,
) -> UpgradeResult:
    """
    Execute the upgrade plan:
    1. Safety backup
    2. Move files to tasks/<version>/
    3. Remove old empty directories
    4. Update all links and references across all markdown files
    5. Run automated link validator & auto-heal
    6. Sync templates & standards
    """
    if not plan.has_changes:
        return UpgradeResult(
            success=True,
            target_version=plan.target_version,
            backup_dir=None,
            moved_goals=0,
            moved_base_tasks=0,
            moved_subtasks=0,
            updated_files=0,
            healed_links=0,
            error="No changes required",
        )

    backup_dir: Path | None = None
    if create_backup:
        try:
            backup_dir = create_workspace_backup(abb_ws)
        except Exception as e:
            return UpgradeResult(
                success=False,
                target_version=plan.target_version,
                backup_dir=None,
                moved_goals=0,
                moved_base_tasks=0,
                moved_subtasks=0,
                updated_files=0,
                healed_links=0,
                error=f"Failed to create safety backup: {e}",
            )

    try:
        tasks_dir = abb_ws / "tasks"
        target_v_dir = tasks_dir / plan.target_version
        target_goal_dir = target_v_dir / "goal"
        target_base_dir = target_v_dir / "base"
        target_sub_dir = target_v_dir / "sub"

        target_goal_dir.mkdir(parents=True, exist_ok=True)
        target_base_dir.mkdir(parents=True, exist_ok=True)
        target_sub_dir.mkdir(parents=True, exist_ok=True)

        # 1. Move goal files
        for src, dst in plan.goals_to_move:
            shutil.move(str(src), str(dst))

        # 2. Move base task files (with numbering)
        for src, dst in plan.base_tasks_to_move:
            shutil.move(str(src), str(dst))

        # 3. Move subtask files
        for src, dst in plan.subtasks_to_move:
            shutil.move(str(src), str(dst))

        # 4. Remove old empty directories
        for old_sub in ["base", "sub", "goal"]:
            d = tasks_dir / old_sub
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except Exception:
                    pass

        # 5. Link updates across all files in workspace
        ver = plan.target_version
        updated_files_count = 0

        for p in abb_ws.rglob("*.md"):
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue

            orig_content = content
            is_in_versioned_tasks = (
                f"tasks/{ver}/base" in p.as_posix()
                or f"tasks/{ver}/sub" in p.as_posix()
                or f"tasks/{ver}/goal" in p.as_posix()
            )

            # Rule A: In tasks/<ver>/* files, links pointing to workspace root files/dirs
            # previously had depth 2 (../../), now require depth 3 (../../../)
            if is_in_versioned_tasks:
                # Update ../../skills, ../../STACK.md, ../../agent.md, ../../design, ../../features, ../../references
                content = re.sub(
                    r"(?<=\s|\(|\"|\')\.\./\.\./(skills/|STACK\.md|agent\.md|features/|design/|references/|USER_PREFERENCES\.md|CHANGELOG\.md|CONVENTIONS\.md|CODING_PHILOSOPHY\.md)",
                    r"../../../\1",
                    content,
                )
                # Repo root links: ../../../README.md -> ../../../../README.md
                content = re.sub(
                    r"(?<=\s|\(|\"|\')\.\./\.\./\.\./(README\.md|templates/)",
                    r"../../../../\1",
                    content,
                )

                # Parent links in subtasks:
                # e.g. base/foo.md or ../base/foo.md or ../../tasks/base/foo.md
                for old_base, new_base in plan.base_task_rename_map.items():
                    content = content.replace(f"../../tasks/base/{old_base}", f"../base/{new_base}")
                    content = content.replace(f"../base/{old_base}", f"../base/{new_base}")
                    content = content.replace(f"`base/{old_base}`", f"`../base/{new_base}`")
                    content = content.replace(f"base/{old_base}", f"../base/{new_base}")

                # Goal links: ../../tasks/goal/goal.md -> ../goal/goal.md
                content = content.replace("../../tasks/goal/goal.md", "../goal/goal.md")

                # Subtask checklist references:
                # sub/01_foo.md -> ../sub/01_foo.md
                content = re.sub(
                    r"(\s|\- \[[ xX]\] )sub/(\d{2}_.*\.md)",
                    r"\1../sub/\2",
                    content,
                )

            else:
                # Rule B: Files outside tasks/ (features/, design/, references/, agent.md, etc.)
                # Update links pointing into tasks/base/, tasks/sub/, tasks/goal/
                for old_base, new_base in plan.base_task_rename_map.items():
                    content = content.replace(
                        f"tasks/base/{old_base}", f"tasks/{ver}/base/{new_base}"
                    )

                # General tasks/base, tasks/sub, tasks/goal references
                content = re.sub(
                    r"((?:\.\./)*)tasks/(base|sub|goal)/",
                    rf"\1tasks/{ver}/\2/",
                    content,
                )

            if content != orig_content:
                p.write_text(content, encoding="utf-8")
                updated_files_count += 1

        # 6. Automated Link Healing (Safety Net Pass)
        healed_count = _heal_workspace_markdown_links(abb_ws)

        # 7. Sync latest templates & standards
        for src, dst in plan.template_files_to_sync:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        return UpgradeResult(
            success=True,
            target_version=plan.target_version,
            backup_dir=backup_dir,
            moved_goals=len(plan.goals_to_move),
            moved_base_tasks=len(plan.base_tasks_to_move),
            moved_subtasks=len(plan.subtasks_to_move),
            updated_files=updated_files_count,
            healed_links=healed_count,
            error=None,
        )

    except Exception as e:
        return UpgradeResult(
            success=False,
            target_version=plan.target_version,
            backup_dir=backup_dir,
            moved_goals=0,
            moved_base_tasks=0,
            moved_subtasks=0,
            updated_files=0,
            healed_links=0,
            error=f"Upgrade failed during execution: {e}",
        )


def _heal_workspace_markdown_links(abb_ws: Path) -> int:
    """
    Validate every relative markdown link across the workspace and automatically
    heal broken links by calculating precise graph relative paths.
    """
    healed = 0
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    fm_link_pattern = re.compile(
        r"^\s*-\s+([^\s#]+(?:\.md|\.json|\.yml|\.yaml|\.txt|\.py|\.ts)?)(?:#.*)?$"
    )

    for p in abb_ws.rglob("*.md"):
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = txt.splitlines()
        changed = False

        for i, line in enumerate(lines):
            # Check markdown links [text](path)
            def _replace_match(m: re.Match) -> str:
                nonlocal changed, healed
                text, target = m.group(1), m.group(2)
                # Skip external URLs or anchors
                if (
                    target.startswith("http://")
                    or target.startswith("https://")
                    or target.startswith("#")
                    or target.startswith("mailto:")
                ):
                    return m.group(0)

                clean_target = target.split("#")[0]
                target_path = (p.parent / clean_target).resolve()
                if target_path.exists():
                    return m.group(0)

                # Link is broken! Find candidate in workspace
                cand = _find_best_candidate(abb_ws, clean_target)
                if cand and cand.exists():
                    correct_rel = os.path.relpath(cand, p.parent).replace("\\", "/")
                    if "#" in target:
                        correct_rel += "#" + target.split("#", 1)[1]
                    changed = True
                    healed += 1
                    return f"[{text}]({correct_rel})"
                return m.group(0)

            new_line = link_pattern.sub(_replace_match, line)

            # Check YAML frontmatter link lines
            fm_m = fm_link_pattern.match(new_line)
            if fm_m:
                target = fm_m.group(1)
                if not (
                    target.startswith("http://")
                    or target.startswith("https://")
                    or target.startswith("#")
                ):
                    clean_target = target.split("#")[0]
                    target_path = (p.parent / clean_target).resolve()
                    if not target_path.exists():
                        cand = _find_best_candidate(abb_ws, clean_target)
                        if cand and cand.exists():
                            correct_rel = os.path.relpath(cand, p.parent).replace("\\", "/")
                            if "#" in target:
                                correct_rel += "#" + target.split("#", 1)[1]
                            new_line = re.sub(re.escape(target), correct_rel, new_line, count=1)
                            changed = True
                            healed += 1

            if new_line != line:
                lines[i] = new_line

        if changed:
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return healed


def _find_best_candidate(abb_ws: Path, target_str: str) -> Path | None:
    """Find the best matching file candidate for a broken relative path."""
    target_name = Path(target_str).name
    if not target_name:
        return None

    candidates = list(abb_ws.rglob(target_name))
    if not candidates:
        # Check project root / repo root
        proj_root = find_project_root(abb_ws)
        if proj_root and proj_root != abb_ws:
            candidates = [
                c
                for c in proj_root.rglob(target_name)
                if ".git" not in c.parts
                and ".venv" not in c.parts
                and "node_modules" not in c.parts
            ]

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Rank by matching tail parts
    target_parts = Path(target_str).parts
    best_cand = candidates[0]
    best_score = -1
    for cand in candidates:
        cand_parts = cand.parts
        score = 0
        for p1, p2 in zip(reversed(target_parts), reversed(cand_parts)):
            if p1 == p2:
                score += 1
            else:
                break
        if score > best_score:
            best_score = score
            best_cand = cand

    return best_cand


def format_plan_summary(plan: UpgradePlan) -> str:
    """Generate human-readable summary of the upgrade plan."""
    lines = []
    lines.append(f"ABB Workspace Upgrade Plan (Target: {plan.target_version})")
    lines.append(f"Workspace Path: {plan.abb_ws}")
    lines.append("")

    if not plan.has_changes:
        lines.append("Status: No changes required.")
        for note in plan.notes:
            lines.append(f"  • {note}")
        return "\n".join(lines)

    lines.append("Planned Actions:")
    lines.append(f"  • Goals to move ({len(plan.goals_to_move)}):")
    for src, dst in plan.goals_to_move:
        lines.append(f"    - {src.name} -> {dst.relative_to(plan.abb_ws)}")

    lines.append(f"  • Base tasks to rename & move ({len(plan.base_tasks_to_move)}):")
    for src, dst in plan.base_tasks_to_move:
        renamed = f" (renamed to '{dst.name}')" if src.name != dst.name else ""
        lines.append(f"    - {src.name} -> {dst.relative_to(plan.abb_ws)}{renamed}")

    lines.append(f"  • Subtasks to move ({len(plan.subtasks_to_move)}):")
    for src, dst in plan.subtasks_to_move:
        lines.append(f"    - {src.name} -> {dst.relative_to(plan.abb_ws)}")

    lines.append(f"  • Templates to synchronize ({len(plan.template_files_to_sync)}):")
    for src, dst in plan.template_files_to_sync:
        lines.append(f"    - {dst.relative_to(plan.abb_ws)}")

    lines.append("")
    lines.append(
        f"Link updates & healing will be applied across {len(plan.files_with_links_to_update)} markdown file(s)."
    )
    return "\n".join(lines)
