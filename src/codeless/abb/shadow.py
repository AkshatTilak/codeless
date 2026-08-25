"""Shadow workspace bootstrapper, location manager, and path resolver for Codeless."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal

AbbLocation = Literal["shadow", "local"]


def get_project_hash(project_root: str | Path) -> str:
    """Calculate the canonical SHA-256 hash for a given project directory path."""
    canonical_path = os.path.realpath(os.path.abspath(str(project_root)))
    # On Windows, path casing should be normalized for stable hashing
    if os.name == "nt":
        canonical_path = canonical_path.lower()
    return hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()


def get_global_codeless_dir() -> Path:
    """Return the global Codeless configuration and project storage directory."""
    if "CODELESS_HOME" in os.environ:
        return Path(os.environ["CODELESS_HOME"]).expanduser().resolve()
    return Path.home() / ".codeless"


def get_project_storage_dir(project_root: str | Path) -> Path:
    """Return the project-specific storage directory in global AppData/home."""
    proj_hash = get_project_hash(project_root)
    return get_global_codeless_dir() / "projects" / proj_hash


def get_abb_template_dir() -> Path:
    """Locate the vendored agent_buildable_base template directory."""
    # 1. Check relative to repository root (development environment)
    package_dir = Path(__file__).resolve().parent  # src/codeless/abb
    src_dir = package_dir.parent.parent  # src
    repo_root = src_dir.parent
    dev_template = repo_root / "templates" / "agent_buildable_base"
    if dev_template.is_dir() and (dev_template / "agent.md").exists():
        return dev_template

    # 2. Check bundled package directory
    bundled_template = package_dir / "templates" / "agent_buildable_base"
    if bundled_template.is_dir() and (bundled_template / "agent.md").exists():
        return bundled_template

    # 3. Check local .codeless/abb_workspace in repo as fallback
    local_abb = repo_root / ".codeless" / "abb_workspace"
    if local_abb.is_dir() and (local_abb / "agent.md").exists():
        return local_abb

    # Fallback to dev_template path
    return dev_template


def get_template_version(template_dir: Path | None = None) -> str:
    """Read the version string from the ABB template VERSION file."""
    if template_dir is None:
        template_dir = get_abb_template_dir()
    version_file = template_dir / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "1.0.0"


def ensure_gitignore_has_codeless(project_root: str | Path) -> bool:
    """Ensure that .codeless/ is in the project's .gitignore file."""
    proj_path = Path(project_root).resolve()
    gitignore_file = proj_path / ".gitignore"

    if not gitignore_file.exists():
        gitignore_file.write_text(".codeless/\n", encoding="utf-8")
        return True

    try:
        content = gitignore_file.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines()]
        if any(line.rstrip("/") in {".codeless", "/.codeless"} for line in lines):
            return True

        if content and not content.endswith("\n"):
            new_content = content + "\n.codeless/\n"
        else:
            new_content = content + ".codeless/\n"
        gitignore_file.write_text(new_content, encoding="utf-8")
        return True
    except Exception:
        return False


def get_configured_abb_location(project_root: str | Path) -> str | None:
    """Check environment or persisted metadata to determine configured ABB location."""
    if "CODELESS_ABB_LOCATION" in os.environ:
        val = os.environ["CODELESS_ABB_LOCATION"].strip().lower()
        if val in {"local", "shadow"}:
            return val

    proj_root_path = Path(project_root).resolve()

    # Check local in-project metadata.json
    local_meta = proj_root_path / ".codeless" / "metadata.json"
    if local_meta.exists():
        try:
            data = json.loads(local_meta.read_text(encoding="utf-8"))
            loc = data.get("abb_location")
            if loc in {"local", "shadow"}:
                return loc
        except Exception:
            pass

    # Check shadow metadata.json in global AppData/home
    shadow_meta = get_project_storage_dir(proj_root_path) / "metadata.json"
    if shadow_meta.exists():
        try:
            data = json.loads(shadow_meta.read_text(encoding="utf-8"))
            loc = data.get("abb_location")
            if loc in {"local", "shadow"}:
                return loc
        except Exception:
            pass

    return None


def set_configured_abb_location(project_root: str | Path, location: str) -> None:
    """Persist the configured ABB location in metadata."""
    loc = location.strip().lower()
    if loc not in {"local", "shadow"}:
        raise ValueError(f"Invalid ABB location: '{location}'. Must be 'local' or 'shadow'.")

    proj_root_path = Path(project_root).resolve()
    shadow_meta_file = get_project_storage_dir(proj_root_path) / "metadata.json"
    local_meta_file = proj_root_path / ".codeless" / "metadata.json"

    for meta_file in [shadow_meta_file, local_meta_file]:
        if meta_file.parent.exists():
            meta: dict[str, Any] = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            meta["abb_location"] = loc
            meta["last_active"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def bootstrap_workspace(
    project_root: str | Path,
    location: str = "shadow",
    force: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """
    Bootstrap the ABB workspace either in shadow store (AppData/user home) or local in-project.

    Creates:
    - Target abb_workspace/ layout populated from vendored template
    - Subdirectories: logs/{dev, docker, failure, test}, sessions/, checkpoints/, cache/
    - metadata.json describing project metadata and abb_location
    - .gitignore containing .codeless/ (when location is 'local')
    """
    proj_root_path = Path(project_root).resolve()
    loc = location.strip().lower()
    if loc not in {"local", "shadow"}:
        loc = "shadow"

    template_dir = get_abb_template_dir()
    template_ver = get_template_version(template_dir)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    proj_hash = get_project_hash(proj_root_path)

    if loc == "local":
        codeless_dir = proj_root_path / ".codeless"
        abb_workspace = codeless_dir / "abb_workspace"
        metadata_file = codeless_dir / "metadata.json"
        storage_base = codeless_dir
        ensure_gitignore_has_codeless(proj_root_path)
    else:
        storage_dir = get_project_storage_dir(proj_root_path)
        abb_workspace = storage_dir / "abb_workspace"
        metadata_file = storage_dir / "metadata.json"
        storage_base = storage_dir

    storage_base.mkdir(parents=True, exist_ok=True)

    # Subdirectories for runtime
    for sub in [
        "logs/dev",
        "logs/docker",
        "logs/failure",
        "logs/test",
        "sessions",
        "checkpoints",
        "cache",
    ]:
        (storage_base / sub).mkdir(parents=True, exist_ok=True)

    metadata: dict[str, Any] = {}
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    # Populate or copy abb_workspace
    if force or not abb_workspace.exists() or not (abb_workspace / "agent.md").exists():
        if abb_workspace.exists() and force:
            shutil.rmtree(abb_workspace)

        if template_dir.exists():
            shutil.copytree(
                template_dir,
                abb_workspace,
                ignore=shutil.ignore_patterns(".git", ".github", "__pycache__", ".pytest_cache"),
                dirs_exist_ok=True,
            )

    # Update metadata
    metadata.update(
        {
            "project_name": proj_root_path.name,
            "project_root": str(proj_root_path),
            "project_hash": proj_hash,
            "abb_location": loc,
            "template_version": template_ver,
            "last_active": now_iso,
        }
    )
    if "created_at" not in metadata:
        metadata["created_at"] = now_iso

    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Also maintain project index in global shadow store if local
    if loc == "local":
        shadow_dir = get_project_storage_dir(proj_root_path)
        shadow_dir.mkdir(parents=True, exist_ok=True)
        shadow_meta_file = shadow_dir / "metadata.json"
        shadow_meta: dict[str, Any] = {}
        if shadow_meta_file.exists():
            try:
                shadow_meta = json.loads(shadow_meta_file.read_text(encoding="utf-8"))
            except Exception:
                shadow_meta = {}
        shadow_meta.update(
            {
                "project_name": proj_root_path.name,
                "project_root": str(proj_root_path),
                "project_hash": proj_hash,
                "abb_location": "local",
                "template_version": template_ver,
                "last_active": now_iso,
            }
        )
        if "created_at" not in shadow_meta:
            shadow_meta["created_at"] = now_iso
        shadow_meta_file.write_text(json.dumps(shadow_meta, indent=2), encoding="utf-8")

    return abb_workspace, metadata


def bootstrap_shadow_workspace(
    project_root: str | Path, force: bool = False
) -> tuple[Path, dict[str, Any]]:
    """Legacy alias: bootstrap shadow workspace in AppData/user home."""
    return bootstrap_workspace(project_root, location="shadow", force=force)


def resolve_abb_workspace(
    project_root: str | Path,
    auto_init: bool = True,
    location: str | None = None,
) -> Path:
    """
    Resolve the active ABB workspace path for a project.

    Priority:
    0. Container/custom env override: $CODELESS_ABB_ROOT
    1. Explicit location parameter: 'local' or 'shadow'
    2. Configured location in CODELESS_ABB_LOCATION or metadata.json
    3. Dev-mode / existing in-repo workspace: <project_root>/.codeless/abb_workspace/
    4. Shadow workspace in AppData/home: ~/.codeless/projects/<hash>/abb_workspace/ (Default)
    """
    if "CODELESS_ABB_ROOT" in os.environ and os.environ["CODELESS_ABB_ROOT"].strip():
        env_root = Path(os.environ["CODELESS_ABB_ROOT"]).resolve()
        if env_root.exists() and (env_root / "agent.md").exists():
            return env_root

    proj_root_path = Path(project_root).resolve()

    effective_loc = location or get_configured_abb_location(proj_root_path)

    # 1. Explicitly configured as local
    if effective_loc == "local":
        local_ws = proj_root_path / ".codeless" / "abb_workspace"
        if auto_init and (not local_ws.exists() or not (local_ws / "agent.md").exists()):
            bootstrap_workspace(proj_root_path, location="local")
        return local_ws

    # 2. Explicitly configured as shadow
    if effective_loc == "shadow":
        storage_dir = get_project_storage_dir(proj_root_path)
        shadow_ws = storage_dir / "abb_workspace"
        if auto_init and (not shadow_ws.exists() or not (shadow_ws / "agent.md").exists()):
            bootstrap_workspace(proj_root_path, location="shadow")
        return shadow_ws

    # 3. Dev-mode in-repo override if already present and valid
    dev_override = proj_root_path / ".codeless" / "abb_workspace"
    if dev_override.exists() and (dev_override / "agent.md").exists():
        return dev_override

    # 4. Default fallback: Shadow workspace in AppData/home
    storage_dir = get_project_storage_dir(proj_root_path)
    shadow_ws = storage_dir / "abb_workspace"

    if auto_init and (not shadow_ws.exists() or not (shadow_ws / "agent.md").exists()):
        bootstrap_workspace(proj_root_path, location="shadow")

    return shadow_ws


def migrate_abb_workspace(
    project_root: str | Path,
    target_location: str,
    force: bool = False,
) -> tuple[Path, Path]:
    """
    Migrate an ABB workspace between 'local' and 'shadow' locations.

    Parameters:
    - project_root: Root directory of the target project
    - target_location: 'local' (in-repo) or 'shadow' (AppData/user home)
    - force: Overwrite destination if it already exists

    Returns:
    - (source_workspace_path, dest_workspace_path)
    """
    target_loc = target_location.strip().lower()
    if target_loc not in {"local", "shadow"}:
        raise ValueError(
            f"Invalid target location: '{target_location}'. Must be 'local' or 'shadow'."
        )

    proj_root_path = Path(project_root).resolve()
    local_ws = proj_root_path / ".codeless" / "abb_workspace"
    shadow_ws = get_project_storage_dir(proj_root_path) / "abb_workspace"

    if target_loc == "local":
        source_ws = shadow_ws
        dest_ws = local_ws
    else:
        source_ws = local_ws
        dest_ws = shadow_ws

    if not source_ws.exists() or not (source_ws / "agent.md").exists():
        # If source does not exist, bootstrap dest directly
        bootstrap_workspace(proj_root_path, location=target_loc, force=force)
        return source_ws, dest_ws

    if (
        dest_ws.exists()
        and any(dest_ws.iterdir())
        and not force
        and dest_ws.resolve() != source_ws.resolve()
    ):
        raise FileExistsError(
            f"Destination ABB workspace '{dest_ws}' already exists. Use force=True to overwrite."
        )

    # Copy from source to destination
    dest_ws.parent.mkdir(parents=True, exist_ok=True)
    if dest_ws.exists() and force:
        shutil.rmtree(dest_ws)

    shutil.copytree(
        source_ws,
        dest_ws,
        ignore=shutil.ignore_patterns(".git", ".github", "__pycache__", ".pytest_cache"),
        dirs_exist_ok=True,
    )

    if target_loc == "local":
        ensure_gitignore_has_codeless(proj_root_path)
        bootstrap_workspace(proj_root_path, location="local", force=False)
    else:
        bootstrap_workspace(proj_root_path, location="shadow", force=False)
        # Clean up local .codeless when migrating to shadow if force is True
        if force and local_ws.parent.exists():
            shutil.rmtree(local_ws.parent, ignore_errors=True)

    set_configured_abb_location(proj_root_path, target_loc)
    return source_ws, dest_ws


def get_dir_size_bytes(directory: Path) -> int:
    """Calculate the total disk size of a directory in bytes."""
    total = 0
    if not directory.exists():
        return 0
    if directory.is_file():
        return directory.stat().st_size
    for root, _, files in os.walk(directory):
        for f in files:
            fp = Path(root) / f
            try:
                if not fp.is_symlink():
                    total += fp.stat().st_size
            except OSError:
                pass
    return total


def list_shadow_projects() -> list[dict[str, Any]]:
    """
    List all shadow workspaces registered under global Codeless storage.

    Returns a list of dicts with:
    - project_hash: SHA-256 hash string
    - storage_dir: Absolute path to the shadow project directory
    - project_root: Original project root directory (if available in metadata)
    - project_name: Project name
    - abb_location: 'shadow' or 'local'
    - exists_on_disk: Boolean indicating if the project_root exists on disk
    - is_orphan: True if project_root is missing or no longer exists on disk
    - disk_size_bytes: Total disk usage in bytes
    - template_version: Version of the ABB template used
    - last_active: ISO timestamp of last activity
    - created_at: ISO timestamp of creation
    """
    projects_base = get_global_codeless_dir() / "projects"
    if not projects_base.is_dir():
        return []

    results = []
    for entry in projects_base.iterdir():
        if not entry.is_dir():
            continue
        proj_hash = entry.name
        metadata_file = entry / "metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}

        raw_root = metadata.get("project_root")
        exists_on_disk = False
        if raw_root:
            try:
                exists_on_disk = Path(raw_root).exists()
            except Exception:
                exists_on_disk = False

        size_bytes = get_dir_size_bytes(entry)
        results.append(
            {
                "project_hash": proj_hash,
                "storage_dir": str(entry),
                "project_root": raw_root,
                "project_name": metadata.get("project_name", entry.name),
                "abb_location": metadata.get("abb_location", "shadow"),
                "exists_on_disk": exists_on_disk,
                "is_orphan": not exists_on_disk,
                "disk_size_bytes": size_bytes,
                "template_version": metadata.get("template_version", "unknown"),
                "last_active": metadata.get("last_active"),
                "created_at": metadata.get("created_at"),
            }
        )

    results.sort(
        key=lambda x: (x.get("last_active") or "", x.get("project_name") or ""), reverse=True
    )
    return results


def clean_shadow_projects(dry_run: bool = False, clean_all: bool = False) -> list[dict[str, Any]]:
    """
    Prune shadow workspaces.

    If clean_all is True, removes all shadow workspaces.
    Otherwise, removes only orphaned workspaces (whose original project_root no longer exists).

    Returns the list of removed (or candidate) shadow workspace metadata records.
    """
    projects = list_shadow_projects()
    targets = []
    for proj in projects:
        if clean_all or proj["is_orphan"]:
            targets.append(proj)

    if not dry_run:
        for proj in targets:
            storage_path = Path(proj["storage_dir"])
            if storage_path.exists() and storage_path.is_dir():
                shutil.rmtree(storage_path, ignore_errors=True)

    return targets
