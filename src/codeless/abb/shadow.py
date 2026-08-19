"""Shadow workspace bootstrapper and path resolver for Codeless."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


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

    # Fallback to dev_template path
    return dev_template


def get_template_version(template_dir: Optional[Path] = None) -> str:
    """Read the version string from the ABB template VERSION file."""
    if template_dir is None:
        template_dir = get_abb_template_dir()
    version_file = template_dir / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "1.0.0"


def bootstrap_shadow_workspace(
    project_root: str | Path, force: bool = False
) -> Tuple[Path, Dict[str, Any]]:
    """
    Bootstrap the shadow workspace and project support folders.
    
    Creates:
    - ~/.codeless/projects/<project_hash>/metadata.json
    - ~/.codeless/projects/<project_hash>/abb_workspace/ (from template)
    - ~/.codeless/projects/<project_hash>/logs/{dev, docker, failure, test}
    - ~/.codeless/projects/<project_hash>/sessions/
    - ~/.codeless/projects/<project_hash>/checkpoints/
    - ~/.codeless/projects/<project_hash>/cache/
    """
    proj_root_path = Path(project_root).resolve()
    storage_dir = get_project_storage_dir(proj_root_path)
    abb_workspace = storage_dir / "abb_workspace"
    metadata_file = storage_dir / "metadata.json"
    template_dir = get_abb_template_dir()
    template_ver = get_template_version(template_dir)

    storage_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectories for runtime
    for sub in ["logs/dev", "logs/docker", "logs/failure", "logs/test", "sessions", "checkpoints", "cache"]:
        (storage_dir / sub).mkdir(parents=True, exist_ok=True)

    metadata: Dict[str, Any] = {}
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

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
    metadata.update({
        "project_name": proj_root_path.name,
        "project_root": str(proj_root_path),
        "project_hash": get_project_hash(proj_root_path),
        "template_version": template_ver,
        "last_active": now_iso,
    })
    if "created_at" not in metadata:
        metadata["created_at"] = now_iso

    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return abb_workspace, metadata


def resolve_abb_workspace(project_root: str | Path, auto_init: bool = True) -> Path:
    """
    Resolve the active ABB workspace path for a project.
    
    Priority:
    1. Dev-mode override: <project_root>/.codeless/abb_workspace/
    2. Shadow workspace in AppData/home: ~/.codeless/projects/<hash>/abb_workspace/
    """
    proj_root_path = Path(project_root).resolve()

    # 1. Dev-mode in-repo override
    dev_override = proj_root_path / ".codeless" / "abb_workspace"
    if dev_override.exists() and (dev_override / "agent.md").exists():
        return dev_override

    # 2. Shadow workspace
    storage_dir = get_project_storage_dir(proj_root_path)
    abb_workspace = storage_dir / "abb_workspace"

    if auto_init and (not abb_workspace.exists() or not (abb_workspace / "agent.md").exists()):
        bootstrap_shadow_workspace(proj_root_path)

    return abb_workspace
