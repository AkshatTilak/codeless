"""Subagent Workers, Context Sandboxing, and Concurrency Dispatch Engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.hooks.frontmatter import parse_frontmatter
from codeless.abb.shadow import resolve_abb_workspace

MAX_CONCURRENT_WORKERS: int = 3


@dataclass
class WorkerContextPackage:
    """Hermetic context sandbox package delivered to a headless worker."""

    subtask_id: str
    subtask_file: str
    subtask_content: str
    linked_files: dict[str, str] = field(default_factory=dict)
    assigned_skills: dict[str, str] = field(default_factory=dict)
    abb_location: str = "shadow"
    abb_workspace_path: str = ""
    project_root: str = ""

    def render_prompt(self) -> str:
        """Render the complete, isolated context package as markdown for the worker."""
        sections = [
            f"# Worker Assignment: Subtask `{self.subtask_id}`",
            "",
            "## Target Subtask Specification",
            f"**File**: `{self.subtask_file}`",
            "",
            "```markdown",
            self.subtask_content.strip(),
            "```",
        ]

        if self.linked_files:
            sections.append("\n## Linked Specifications & Memory Bank References")
            for link_path, link_content in self.linked_files.items():
                sections.append(f"\n### `{link_path}`\n```markdown\n{link_content.strip()}\n```")

        if self.assigned_skills:
            sections.append("\n## Assigned Job Skills")
            for skill_name, skill_body in self.assigned_skills.items():
                sections.append(
                    f"\n### Skill: `{skill_name}`\n```markdown\n{skill_body.strip()}\n```"
                )

        sections.extend(
            [
                "\n## Workspace Environment",
                f"- **Project Root**: `{self.project_root}`",
                f"- **ABB Workspace Location**: `{self.abb_location}` (`{self.abb_workspace_path}`)",
                "",
                "## Worker Instructions",
                "1. Implement the requested code changes strictly within the perimeter of this subtask.",
                "2. Do not mutate tasks outside your assigned subtask.",
                "3. Perform Two-Track verification and report completion summary.",
            ]
        )

        return "\n".join(sections)


def build_worker_context_package(
    subtask_file: str | Path,
    project_root: str | Path,
    abb_ws: Path | None = None,
) -> WorkerContextPackage:
    """
    Construct a hermetic, sandboxed context package for a target subtask.

    Collects:
    1. Target subtask file content & frontmatter
    2. Explicitly linked files in frontmatter links
    3. Assigned skills in frontmatter skills
    4. Active ABB workspace location mode
    """
    p_sub = Path(subtask_file).resolve()
    p_root = Path(project_root).resolve()

    if abb_ws is None:
        abb_ws = resolve_abb_workspace(p_root, auto_init=False)

    if not p_sub.exists():
        raise FileNotFoundError(f"Subtask file does not exist: {p_sub}")

    content = p_sub.read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(content)
    subtask_id = str(fm.get("id", p_sub.stem))

    # Determine ABB location mode (local if inside project root, else shadow)
    try:
        if abb_ws.resolve().is_relative_to(p_root.resolve()):
            location = "local"
        else:
            location = "shadow"
    except Exception:
        location = "shadow"

    # Collect linked files
    linked_files: dict[str, str] = {}
    links = fm.get("links", [])
    if isinstance(links, list):
        for link in links:
            link_str = str(link).strip()
            # Try relative to subtask file first
            resolved_link = (p_sub.parent / link_str).resolve()
            if not resolved_link.exists():
                # Try relative to abb_ws
                resolved_link = (abb_ws / link_str).resolve()
            if resolved_link.exists() and resolved_link.is_file():
                try:
                    rel_name = str(resolved_link.relative_to(abb_ws)).replace("\\", "/")
                except Exception:
                    rel_name = resolved_link.name
                linked_files[rel_name] = resolved_link.read_text(encoding="utf-8")

    # Collect assigned skills
    assigned_skills: dict[str, str] = {}
    skills_field = fm.get("skills", [])
    if isinstance(skills_field, list):
        for skill_ref in skills_field:
            skill_name = str(skill_ref).strip()
            skill_dir = abb_ws / "skills" / skill_name
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                assigned_skills[skill_name] = skill_file.read_text(encoding="utf-8")

    rel_subtask = (
        str(p_sub.relative_to(abb_ws)).replace("\\", "/")
        if p_sub.is_relative_to(abb_ws)
        else p_sub.name
    )

    return WorkerContextPackage(
        subtask_id=subtask_id,
        subtask_file=rel_subtask,
        subtask_content=content,
        linked_files=linked_files,
        assigned_skills=assigned_skills,
        abb_location=location,
        abb_workspace_path=str(abb_ws),
        project_root=str(p_root),
    )


def find_ready_subtasks(tasks_dir: Path) -> list[Path]:
    """
    Inspect the tasks DAG and return all subtasks ready for execution.

    A subtask is ready if:
    - Status is 'pending'
    - All tasks listed in 'depends_on' have status 'done'
    """
    if not tasks_dir.exists():
        return []

    task_index = index_tasks(tasks_dir)
    ready_subtasks: list[Path] = []

    sub_dir = tasks_dir / "sub"
    if not sub_dir.exists():
        return []

    for path in sorted(sub_dir.glob("*.md")):
        if path.name.startswith("_") or path.is_dir():
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            status = str(fm.get("status", "pending")).strip().lower()
            if status != "pending":
                continue

            depends_on = fm.get("depends_on", [])
            deps_satisfied = True
            if isinstance(depends_on, list):
                for dep in depends_on:
                    dep_str = str(dep).strip()
                    entry = task_index.get(dep_str)
                    if entry is None:
                        deps_satisfied = False
                        break
                    _, dep_fm = entry
                    if str(dep_fm.get("status", "pending")).strip().lower() != "done":
                        deps_satisfied = False
                        break

            if deps_satisfied:
                ready_subtasks.append(path)
        except Exception:
            continue

    return ready_subtasks


class SubagentCoordinator:
    """Orchestrates concurrent headless worker execution with strict concurrency bounds."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_WORKERS) -> None:
        self.max_concurrent = max(1, min(max_concurrent, MAX_CONCURRENT_WORKERS))

    async def dispatch_subtasks(
        self,
        project_root: str | Path,
        subtask_paths: list[Path],
        worker_runner: Callable[[WorkerContextPackage], Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        Dispatch workers across ready subtasks, capping concurrent execution to max_concurrent.
        """
        p_root = Path(project_root).resolve()
        abb_ws = resolve_abb_workspace(p_root, auto_init=False)
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _run_guarded(subtask_path: Path) -> dict[str, Any]:
            async with semaphore:
                pkg = build_worker_context_package(subtask_path, p_root, abb_ws)
                return await worker_runner(pkg)

        tasks = [_run_guarded(p) for p in subtask_paths]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)
