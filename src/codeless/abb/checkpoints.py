"""Git Checkpoints and Rollback Engine for Codeless & ABB workspaces."""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from codeless.abb.shadow import get_project_storage_dir, resolve_abb_workspace

_IGNORE_PATTERNS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".coverage",
}


@dataclass
class CheckpointMetadata:
    """Metadata describing a saved codebase + ABB workspace checkpoint."""

    checkpoint_id: str
    name: str
    description: str
    timestamp: str
    git_commit: str | None
    abb_location: str
    files_count: int


def get_checkpoints_dir(project_root: str | Path) -> Path:
    """Return the dedicated checkpoints directory for the given project."""
    storage_dir = get_project_storage_dir(project_root)
    cp_dir = storage_dir / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    return cp_dir


def _get_git_commit(cwd: Path) -> str | None:
    """Retrieve current git commit hash if within a git repo."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return None


def _is_git_dirty(cwd: Path) -> bool:
    """Check if the git repository has unstaged or staged changes."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(res.stdout.strip())
    except Exception:
        return False


def create_checkpoint(
    project_root: str | Path,
    name: str | None = None,
    description: str = "",
) -> CheckpointMetadata:
    """
    Create a coherent snapshot of the project codebase and active ABB workspace.

    Snapshots are saved to global AppData project storage under checkpoints/.
    """
    p_root = Path(project_root).resolve()
    abb_ws = resolve_abb_workspace(p_root, auto_init=False)
    cp_dir = get_checkpoints_dir(p_root)

    now = datetime.datetime.now(datetime.timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    cp_id = f"cp_{ts_str}_{rand_suffix}"

    cp_name = name or cp_id
    target_dir = cp_dir / cp_id
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot Codebase
    code_dest = target_dir / "code"
    code_dest.mkdir(parents=True, exist_ok=True)
    files_copied = 0

    for item in p_root.iterdir():
        if item.name in _IGNORE_PATTERNS or item.name == ".codeless":
            continue
        if item.is_file():
            shutil.copy2(item, code_dest / item.name)
            files_copied += 1
        elif item.is_dir():
            shutil.copytree(
                item,
                code_dest / item.name,
                ignore=shutil.ignore_patterns(*_IGNORE_PATTERNS, ".codeless"),
                dirs_exist_ok=True,
            )
            files_copied += sum(1 for _ in (code_dest / item.name).rglob("*") if _.is_file())

    # 2. Snapshot ABB Workspace
    abb_dest = target_dir / "abb"
    abb_dest.mkdir(parents=True, exist_ok=True)
    if abb_ws.exists():
        for sub_item in abb_ws.iterdir():
            if sub_item.name in _IGNORE_PATTERNS or sub_item.name.startswith("."):
                continue
            if sub_item.is_file():
                shutil.copy2(sub_item, abb_dest / sub_item.name)
                files_copied += 1
            elif sub_item.is_dir():
                shutil.copytree(
                    sub_item,
                    abb_dest / sub_item.name,
                    ignore=shutil.ignore_patterns(*_IGNORE_PATTERNS),
                    dirs_exist_ok=True,
                )
                files_copied += sum(1 for _ in (abb_dest / sub_item.name).rglob("*") if _.is_file())

    # Determine ABB location mode
    try:
        location = "local" if abb_ws.resolve().is_relative_to(p_root.resolve()) else "shadow"
    except Exception:
        location = "shadow"

    commit = _get_git_commit(p_root)

    metadata = CheckpointMetadata(
        checkpoint_id=cp_id,
        name=cp_name,
        description=description,
        timestamp=now.isoformat(),
        git_commit=commit,
        abb_location=location,
        files_count=files_copied,
    )

    meta_file = target_dir / "metadata.json"
    meta_file.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")

    return metadata


def list_checkpoints(project_root: str | Path) -> list[CheckpointMetadata]:
    """Return all saved checkpoints for the project sorted by timestamp descending."""
    p_root = Path(project_root).resolve()
    cp_dir = get_checkpoints_dir(p_root)
    checkpoints: list[CheckpointMetadata] = []

    if not cp_dir.exists():
        return checkpoints

    for child in sorted(cp_dir.iterdir(), reverse=True):
        meta_file = child / "metadata.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                checkpoints.append(CheckpointMetadata(**data))
            except Exception:
                continue

    return sorted(checkpoints, key=lambda c: c.timestamp, reverse=True)


def get_checkpoint(project_root: str | Path, checkpoint_query: str) -> CheckpointMetadata | None:
    """Retrieve checkpoint metadata by exact ID or name."""
    checkpoints = list_checkpoints(project_root)
    for cp in checkpoints:
        if cp.checkpoint_id == checkpoint_query or cp.name == checkpoint_query:
            return cp
    return None


def restore_checkpoint(
    project_root: str | Path,
    checkpoint_id: str,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Restore codebase and ABB workspace state from a saved checkpoint snapshot.

    If force is False and uncommitted git changes exist, returns a safety warning.
    """
    p_root = Path(project_root).resolve()
    cp_dir = get_checkpoints_dir(p_root)
    abb_ws = resolve_abb_workspace(p_root, auto_init=False)

    meta = get_checkpoint(p_root, checkpoint_id)
    if not meta:
        return False, f"Checkpoint '{checkpoint_id}' not found."

    target_dir = cp_dir / meta.checkpoint_id
    if not target_dir.exists():
        return False, f"Checkpoint directory missing for '{meta.checkpoint_id}'."

    # Safety check on working tree
    if not force and _is_git_dirty(p_root):
        return (
            False,
            "Working tree has uncommitted modifications. Restoring will overwrite these changes. "
            "Use '--force' to proceed with restore.",
        )

    # 1. Restore Codebase
    code_source = target_dir / "code"
    if code_source.exists():
        for item in code_source.iterdir():
            dest = p_root / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)

    # 2. Restore ABB Workspace
    abb_source = target_dir / "abb"
    if abb_source.exists() and abb_ws.exists():
        for item in abb_source.iterdir():
            dest = abb_ws / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)

    return True, f"Successfully restored checkpoint '{meta.name}' ({meta.checkpoint_id})."
