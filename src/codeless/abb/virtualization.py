"""Shadow path virtualization engine for Codeless.

Transparently maps Agent Buildable Base (ABB) domains (tasks, references,
workflows, design, features, skills, etc.) to the project's active shadow
or local workspace while mapping codebase source and tests to the repo root.
"""

from __future__ import annotations

from pathlib import Path

from codeless.abb.shadow import resolve_abb_workspace

# Set of top-level ABB files
ABB_TOP_LEVEL_FILES = frozenset(
    {
        "agent.md",
        "stack.md",
        "user_preferences.md",
        "conventions.md",
        "coding_philosophy.md",
        "changelog.md",
        "todo.md",
        "todos.md",
        "gemini.md",
        "agents.md",
    }
)

# Set of ABB domain directories
ABB_DOMAINS = frozenset(
    {
        "workflows",
        "design",
        "features",
        "tasks",
        "references",
        "skills",
        "assets",
        "rules",
    }
)


def find_project_root(start_dir: str | Path) -> Path:
    """Locate the project repository root starting from start_dir."""
    current = Path(start_dir).resolve()
    try:
        home = Path.home().resolve()
    except Exception:
        home = None

    for parent in [current, *current.parents]:
        if home is not None and parent == home:
            continue
        if (
            (parent / ".git").exists()
            or (parent / "pyproject.toml").exists()
            or (parent / "package.json").exists()
            or (parent / "Cargo.toml").exists()
            or (parent / "go.mod").exists()
            or (parent / ".codeless" / "abb_workspace").exists()
        ):
            return parent

    # When no explicit repo marker exists, back out of any ABB domain/sub folders
    abb_subfolders = ABB_DOMAINS | {
        ".codeless",
        "abb_workspace",
        "sub",
        "base",
        "goal",
        "temp",
        "structure",
        "logic",
        "tests",
        "tooling",
        "db",
        "deployment",
        "system",
        "ux",
    }
    candidate = current
    while candidate.name.lower() in abb_subfolders and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def is_abb_path(candidate: str | Path, project_root: Path | None = None) -> bool:
    """Return True if the given candidate path corresponds to an ABB file or domain."""
    if not candidate:
        return False
    path_str = str(candidate).replace("\\", "/").strip()
    if not path_str:
        return False

    # Check if candidate is an absolute path inside an active ABB workspace or repo
    p = Path(candidate)
    if p.is_absolute():
        parts_lower = [part.lower() for part in p.parts]
        if ".codeless" in parts_lower or "abb_workspace" in parts_lower:
            return True

        root = (
            Path(project_root).resolve()
            if project_root is not None
            else find_project_root(p.parent)
        )

        # Check if inside active shadow/local ABB workspace
        try:
            abb_ws = resolve_abb_workspace(root, auto_init=False)
            p.resolve().relative_to(abb_ws.resolve())
            return True
        except (ValueError, Exception):
            pass

        # Try relative to provided or discovered project root
        try:
            rel = p.resolve().relative_to(root.resolve())
            if str(rel) != str(p):
                return is_abb_path(rel, project_root=root)
        except (ValueError, Exception):
            pass

        # Check if any parent part is an ABB domain
        for i, part in enumerate(parts_lower):
            if part in ABB_DOMAINS:
                domain_rel = Path(*p.parts[i:])
                if is_abb_path(domain_rel):
                    return True

        return False

    parts = [part.lower() for part in Path(path_str).parts if part not in {".", ""}]
    if not parts:
        return False

    # Strip leading wildcards like '**'
    non_wildcard_parts = [part for part in parts if part not in {"**", "*"}]
    if not non_wildcard_parts:
        return False

    if ".codeless" in non_wildcard_parts or "abb_workspace" in non_wildcard_parts:
        return True

    first_part = non_wildcard_parts[0]
    if first_part in ABB_TOP_LEVEL_FILES:
        return True
    if first_part in ABB_DOMAINS:
        # Only documentation and specification formats (.md, .yaml, .yml, .json, .toml, .txt) or directory paths are ABB
        suffix = Path(path_str).suffix.lower()
        if suffix and suffix not in {".md", ".yaml", ".yml", ".json", ".toml", ".txt"}:
            return False
        return True
    return False


def resolve_virtual_path(
    cwd: str | Path,
    candidate: str | Path,
    *,
    auto_init: bool = True,
    location: str | None = None,
) -> Path:
    """
    Resolve a file path with shadow virtualization.

    If candidate exists at the repository root, returns the repo root path (repo-root priority).
    If candidate targets an ABB path and does not exist at repo root, returns the path inside the active ABB workspace.
    Otherwise returns the path resolved relative to cwd (codebase root).
    """
    cwd_path = Path(cwd).resolve()
    proj_root = find_project_root(cwd_path)
    abb_ws = resolve_abb_workspace(proj_root, auto_init=auto_init, location=location)

    cand_path = Path(candidate).expanduser()

    # 1. If already absolute
    if cand_path.is_absolute():
        resolved_cand = cand_path.resolve()
        # If it's already inside the active ABB workspace, return directly
        try:
            resolved_cand.relative_to(abb_ws.resolve())
            return resolved_cand
        except ValueError:
            pass

        # If it's inside proj_root:
        try:
            rel = resolved_cand.relative_to(proj_root.resolve())
            # If the file exists directly on disk in proj_root, prefer repo root
            if resolved_cand.exists():
                return resolved_cand

            if is_abb_path(rel, project_root=proj_root):
                clean_rel_parts = [p.lower() for p in rel.parts if p not in {".", "", ".."}]
                if (
                    len(clean_rel_parts) >= 2
                    and clean_rel_parts[0] == ".codeless"
                    and clean_rel_parts[1] == "abb_workspace"
                ):
                    rel = Path(*rel.parts[2:])
                elif len(clean_rel_parts) >= 1 and clean_rel_parts[0] == ".codeless":
                    rel = Path(*rel.parts[1:])
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
    repo_target = (cwd_path / rel_path).resolve()

    # Repo-root priority: if the file already exists at the repository root, return repo target
    if repo_target.exists():
        return repo_target

    if is_abb_path(rel_path, project_root=proj_root):
        parts = list(rel_path.parts)
        if (
            len(parts) >= 2
            and parts[0].lower() == ".codeless"
            and parts[1].lower() == "abb_workspace"
        ):
            rel_path = Path(*parts[2:])
        elif len(parts) >= 1 and parts[0].lower() == ".codeless":
            rel_path = Path(*parts[1:])
        return (abb_ws / rel_path).resolve()

    return repo_target


def unvirtualize_path(
    path: Path,
    project_root: Path | None = None,
    location: str | None = None,
) -> str:
    """
    Return a clean relative representation of a path for user display and logging.
    """
    p = Path(path).resolve()
    root = find_project_root(project_root or Path.cwd()).resolve()
    abb_ws = resolve_abb_workspace(root, auto_init=False, location=location).resolve()

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


def get_search_roots(
    project_root: str | Path,
    location: str | None = None,
) -> list[Path]:
    """Return all roots that should be searched for symbols, grep, and glob."""
    root = Path(project_root).resolve()
    abb_ws = resolve_abb_workspace(root, auto_init=True, location=location).resolve()

    roots = [root]
    # Only append abb_ws if it's outside the project root (i.e. AppData storage)
    try:
        abb_ws.relative_to(root)
    except ValueError:
        roots.append(abb_ws)

    return roots
