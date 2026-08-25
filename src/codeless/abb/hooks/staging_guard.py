"""Staging directory hook and validator for pull-adapt-delete workflow."""

from __future__ import annotations

from pathlib import Path


def check_skill_staging_guard(
    raw_path: str | Path,
    abb_ws: Path,
) -> tuple[bool, str]:
    """
    Enforce pull-adapt-delete: prevent writing to skills.md if _staging/ is not empty.

    Parameters:
    - raw_path: Path being written/edited
    - abb_ws: Active ABB workspace root

    Returns:
    - (allowed, reason)
    """
    path_str = str(raw_path).replace("\\", "/").strip()
    if not (path_str.endswith("skills/skills.md") or path_str == "skills.md"):
        return True, "OK"

    staging_dir = abb_ws / "skills" / "_staging"
    if staging_dir.exists() and staging_dir.is_dir():
        staged_files = [
            f
            for f in staging_dir.rglob("*")
            if f.is_file() and f.name not in {".gitkeep", ".gitignore"}
        ]
        if staged_files:
            file_names = ", ".join(f.name for f in staged_files[:5])
            count = len(staged_files)
            return (
                False,
                f"ABB Skill Staging Blocked: 'skills/_staging/' contains {count} unpurged artifact(s) ({file_names}). "
                "Pull-adapt-delete workflow requires purging '_staging/' before updating the skills index.",
            )

    return True, "OK"
