"""Shadow path virtualization engine for Codeless.

Transparently maps Agent Buildable Base (ABB) domains (tasks, references,
workflows, design, features, skills, etc.) to the project's active shadow
workspace while mapping codebase source and tests to the repo root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from codeless.abb.shadow import resolve_abb_workspace

# Set of top-level ABB files
ABB_TOP_LEVEL_FILES = frozenset({
    "agent.md",
    "stack.md",
    "user_preferences.md",
    "conventions.md",
    "coding_philosophy.md",
    "version",
})

# Set of ABB domain directories
ABB_DOMAINS = frozenset({
    "workflows",
    "design",
    "features",
    "tasks",
    "references",
    "skills",
})


def find_project_root(start_dir: str | Path) -> Path:
    """Locate the project repository root starting from start_dir."""
    current = Path(start_dir).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return current


def is_abb_path(candidate: str | Path, project_root: Optional[Path] = None) -> bool:
    """Return True if the given candidate path corresponds to an ABB file or domain."""
    path_str = str(candidate).replace("\\", "/").strip()
    if not path_str:
        return False

    # Check if candidate is an absolute path inside an active ABB workspace
    p = Path(candidate)
    if p.is_absolute():
        if ".codeless" in p.parts:
            return True
        if project_root is not None:
            try:
                rel = p.relative_to(project_root)
                return is_abb_path(rel)
            except ValueError:
                pass
        return False

    parts = [part.lower() for part in Path(path_str).parts if part not in {".", ""}]
    if not parts:
        return False

    # Strip leading wildcards like '**'
    non_wildcard_parts = [part for part in parts if part not in {"**", "*"}]
    if not non_wildcard_parts:
        return False

    first_part = non_wildcard_parts[0]
    if first_part in ABB_TOP_LEVEL_FILES:
        return True
    if first_part in ABB_DOMAINS:
        return True

    return False


def resolve_virtual_path(
    cwd: str | Path,
    candidate: str | Path,
    *,
    auto_init: bool = True,
) -> Path:
    """
    Resolve a file path with shadow virtualization.

    If candidate targets an ABB path, returns the path inside the active ABB workspace.
    Otherwise returns the path resolved relative to cwd (codebase root).
    """
    cwd_path = Path(cwd).resolve()
    proj_root = find_project_root(cwd_path)
    abb_ws = resolve_abb_workspace(proj_root, auto_init=auto_init)

    cand_path = Path(candidate).expanduser()

    # 1. If already absolute
    if cand_path.is_absolute():
        resolved_cand = cand_path.resolve()
        # If it's already inside the active shadow workspace, return directly
        try:
            resolved_cand.relative_to(abb_ws.resolve())
            return resolved_cand
        except ValueError:
            pass

        # If it's inside proj_root, check if it points to an ABB path
        try:
            rel = resolved_cand.relative_to(proj_root.resolve())
            if is_abb_path(rel):
                return (abb_ws / rel).resolve()
        except ValueError:
            pass

        return resolved_cand

    # 2. Relative candidate
    path_str = str(candidate).replace("\\", "/").strip()
    clean_parts = [part for part in Path(path_str).parts if part not in {".", ""}]
    if not clean_parts:
        return cwd_path

    rel_path = Path(*clean_parts)
    if is_abb_path(rel_path):
        return (abb_ws / rel_path).resolve()

    return (cwd_path / rel_path).resolve()


def unvirtualize_path(path: Path, project_root: Optional[Path] = None) -> str:
    """
    Return a clean relative representation of a path for user display and logging.
    """
    p = Path(path).resolve()
    root = find_project_root(project_root or Path.cwd()).resolve()
    abb_ws = resolve_abb_workspace(root, auto_init=False).resolve()

    try:
        rel_abb = p.relative_to(abb_ws)
        return str(rel_abb).replace("\\", "/")
    except ValueError:
        pass

    try:
        rel_root = p.relative_to(root)
        return str(rel_root).replace("\\", "/")
    except ValueError:
        pass

    return str(p)


def get_search_roots(project_root: str | Path) -> list[Path]:
    """Return all roots that should be searched for symbols, grep, and glob."""
    root = Path(project_root).resolve()
    abb_ws = resolve_abb_workspace(root, auto_init=True).resolve()

    roots = [root]
    # Only append abb_ws if it's outside the project root (i.e. AppData storage)
    try:
        abb_ws.relative_to(root)
    except ValueError:
        roots.append(abb_ws)

    return roots
