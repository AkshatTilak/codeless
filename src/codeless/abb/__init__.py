"""Codeless ABB (Agent Buildable Base) runtime bridge package."""

from codeless.abb.shadow import (
    bootstrap_shadow_workspace,
    get_abb_template_dir,
    get_global_codeless_dir,
    get_project_hash,
    get_project_storage_dir,
    resolve_abb_workspace,
)
from codeless.abb.virtualization import (
    get_search_roots,
    is_abb_path,
    resolve_virtual_path,
    unvirtualize_path,
)

__all__ = [
    "bootstrap_shadow_workspace",
    "get_abb_template_dir",
    "get_global_codeless_dir",
    "get_project_hash",
    "get_project_storage_dir",
    "get_search_roots",
    "is_abb_path",
    "resolve_abb_workspace",
    "resolve_virtual_path",
    "unvirtualize_path",
]
