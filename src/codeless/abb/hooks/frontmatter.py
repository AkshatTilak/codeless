"""YAML frontmatter parser and strict schema validator for ABB task files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
VALID_STATUSES = frozenset(
    {
        "not_started",
        "pending",
        "in_progress",
        "done",
        "blocked",
        "failed",
    }
)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML frontmatter from markdown content.
    Returns (frontmatter_dict, markdown_body).
    """
    content = content.lstrip("\ufeff")  # Handle UTF-8 BOM if present
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_raw = parts[1]
    body = parts[2].lstrip("\r\n")

    try:
        data = yaml.safe_load(frontmatter_raw)
        if isinstance(data, dict):
            return data, body
        return {}, body
    except yaml.YAMLError:
        return {}, body


def dump_with_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a frontmatter dict and markdown body into standard document format."""
    yaml_str = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{yaml_str}\n---\n\n{body.lstrip()}"


def validate_task_frontmatter(
    data: dict[str, Any],
    task_path: Path | None = None,
) -> list[str]:
    """
    Validate frontmatter data against strict ABB task specification.
    Returns a list of error strings (empty if valid).
    """
    errors: list[str] = []

    if not data:
        return ["Missing YAML frontmatter (enclosed within '---' delimiters)."]

    # 1. Validate ID
    task_id = data.get("id")
    if not task_id or not isinstance(task_id, str):
        errors.append("Field 'id' is required and must be a non-empty string.")

    # 2. Validate Version
    version = data.get("version")
    if not version or not isinstance(version, str):
        errors.append("Field 'version' is required (e.g. '1.0.0').")
    elif not SEMVER_REGEX.match(version.strip()):
        errors.append(
            f"Field 'version' ('{version}') must follow semantic versioning (e.g. '1.0.0')."
        )

    # 3. Validate Status
    status = data.get("status")
    if not status or not isinstance(status, str):
        errors.append(f"Field 'status' is required and must be one of: {sorted(VALID_STATUSES)}.")
    elif status.strip() not in VALID_STATUSES:
        errors.append(f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}.")

    # 4. Validate Depends On
    depends_on = data.get("depends_on")
    if depends_on is None:
        errors.append("Field 'depends_on' is required (can be empty list '[]').")
    elif not isinstance(depends_on, list):
        errors.append("Field 'depends_on' must be a list of task IDs or paths.")

    # 5. Validate Parent (if subtask)
    is_subtask = "sub" in (str(task_path).replace("\\", "/").lower() if task_path else "")
    if is_subtask and "parent" not in data:
        errors.append(
            "Subtasks must define a 'parent' field linking to their base task ID (e.g. 'base_001')."
        )

    # 6. Validate Links
    if "links" in data and not isinstance(data["links"], list):
        errors.append("Field 'links' must be a list.")

    # 7. Validate SRS Refs (optional traceability field)
    if "srs_refs" in data and not isinstance(data["srs_refs"], list):
        errors.append("Field 'srs_refs' must be a list of requirement IDs (e.g. ['FR-001']).")

    return errors
