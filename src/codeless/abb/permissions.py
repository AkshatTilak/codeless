"""4-Mode Permission Controller and Persona Composition Engine for Codeless."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.virtualization import find_project_root, is_abb_path
from codeless.permissions.modes import PermissionMode


class TriMode(str, Enum):
    """Operational permission modes."""

    PLAN = "plan"
    AGENT = "agent"
    ASK = "ask"
    CODEBASE = "codebase"


class ModeEngine:
    """Controls operational mode, composed path permissions, and persona injection."""

    def __init__(self, default_mode: TriMode = TriMode.AGENT) -> None:
        self._current_mode: TriMode = default_mode

    @property
    def current_mode(self) -> TriMode:
        return self._current_mode

    def set_mode(self, mode: TriMode | str) -> TriMode:
        """Switch operational mode."""
        if isinstance(mode, str):
            mode = TriMode(mode.lower().strip())
        self._current_mode = mode
        return self._current_mode

    def get_mode_description(self) -> str:
        descriptions = {
            TriMode.AGENT: "Full autonomous execution — code editing, testing, task completion.",
            TriMode.PLAN: "Architecture & Task Planning — full read/write in ABB workspace; external codebase is strictly read-only.",
            TriMode.ASK: "Read-only Q&A — all file modifications blocked.",
            TriMode.CODEBASE: "Codebase exploration & memory queries — all file modifications blocked.",
        }
        return descriptions.get(self._current_mode, "Unknown mode policy")

    def get_upstream_permission_mode(self) -> PermissionMode:
        """Map TriMode to upstream PermissionMode."""
        if self._current_mode in {TriMode.PLAN, TriMode.ASK, TriMode.CODEBASE}:
            return PermissionMode.PLAN
        return PermissionMode.DEFAULT

    def get_allowed_tools(self, all_tools: list[str] | None = None) -> set[str]:
        """Return allowed tool names for active mode."""
        if self._current_mode in {TriMode.ASK, TriMode.CODEBASE}:
            return {
                "file",
                "glob",
                "grep",
                "lsp",
                "image",
                "ask_user_question",
                "skill",
                "tool_search",
                "abb",
                "cron",
                "task",
                "worktree",
                "mcp",
                "web",
                "config",
            }
        elif self._current_mode == TriMode.PLAN:
            return {
                "file",
                "glob",
                "grep",
                "lsp",
                "image",
                "ask_user_question",
                "todo_write",
                "skill",
                "tool_search",
                "config",
                "abb",
                "cron",
                "task",
                "worktree",
                "mcp",
                "web",
            }
        # AGENT mode
        if all_tools:
            return set(all_tools)
        return {
            "bash",
            "file",
            "glob",
            "grep",
            "lsp",
            "image",
            "ask_user_question",
            "todo_write",
            "skill",
            "tool_search",
            "config",
            "agent",
            "task",
            "cron",
            "worktree",
            "mcp",
            "web",
            "abb",
        }

    def evaluate_write_permission(
        self,
        target_path: str | Path,
        cwd: Path | str | None = None,
    ) -> tuple[bool, str]:
        """
        Evaluate write/edit permission for target path given the active TriMode.
        Returns (allowed, reason).
        """
        norm_path = str(target_path).replace("\\", "/").strip()
        cwd_p = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        proj_root = find_project_root(cwd_p)

        target_p = Path(target_path)
        target_root = find_project_root(target_p.parent) if target_p.is_absolute() else proj_root

        from codeless.abb.virtualization import resolve_virtual_path

        resolved = resolve_virtual_path(target_root, target_path)
        abb_ws = resolve_abb_workspace(target_root, auto_init=False)
        is_inside_abb = False
        if abb_ws.exists():
            try:
                resolved.resolve().relative_to(abb_ws.resolve())
                is_inside_abb = True
            except ValueError:
                is_inside_abb = False

        is_abb = is_inside_abb or (
            not abb_ws.exists() and is_abb_path(target_path, project_root=target_root)
        )

        # 1. ASK & CODEBASE: Strictly read-only everywhere
        if self._current_mode in {TriMode.ASK, TriMode.CODEBASE}:
            mode_name = self._current_mode.value.capitalize()
            return (
                False,
                f"{mode_name} Mode is strictly read-only; all file writes to '{norm_path}' are blocked.",
            )

        # Planning & task checklist files (TODO.md, etc.)
        norm_name = Path(norm_path).name.lower()
        if norm_name in {"todo.md", "todos.md"}:
            if self._current_mode in {TriMode.PLAN, TriMode.AGENT}:
                return True, "Permitted write to task planning file (TODO.md)."

        # 2. PLAN Mode: Write allowed to all ABB workspace files; external codebase is strictly read-only
        if self._current_mode == TriMode.PLAN:
            if is_abb:
                return (
                    True,
                    "Plan mode permitted write to ABB architecture, design & task workspace.",
                )
            return (
                False,
                f"Plan Mode blocks project code modifications to '{norm_path}'. Switch to Agent mode (`/mode agent`) to execute changes.",
            )

        # 3. AGENT Mode: Write allowed everywhere
        if self._current_mode == TriMode.AGENT:
            return True, "Agent mode allows project code and task modifications."

        return True, "OK"

    def get_persona_instructions(self, cwd: Path) -> str:
        """Retrieve dynamic persona markdown for active mode."""
        abb_ws = resolve_abb_workspace(cwd, auto_init=True)
        agent_md = abb_ws / "agent.md"
        router_md = abb_ws / "workflows" / "router.md"
        agent_text = agent_md.read_text(encoding="utf-8") if agent_md.exists() else ""
        router_text = router_md.read_text(encoding="utf-8") if router_md.exists() else ""

        core_parts = []
        if agent_text:
            core_parts.append(agent_text)
        if router_text:
            core_parts.append(router_text)

        if self._current_mode == TriMode.PLAN:
            planning_md = abb_ws / "workflows" / "planning" / "planning.md"
            parts = ["# Persona: Architecture & Planning Mode", *core_parts]
            if planning_md.exists():
                parts.append(planning_md.read_text(encoding="utf-8"))
            return "\n\n".join(parts)

        elif self._current_mode == TriMode.ASK:
            refs_index = abb_ws / "references" / "references.md"
            parts = ["# Persona: Knowledge Query & Memory Bank", *core_parts]
            if refs_index.exists():
                parts.append(refs_index.read_text(encoding="utf-8"))
            return "\n\n".join(parts)

        elif self._current_mode == TriMode.CODEBASE:
            refs_index = abb_ws / "references" / "references.md"
            parts = ["# Persona: Codebase Exploration & Comprehension", *core_parts]
            if refs_index.exists():
                parts.append(refs_index.read_text(encoding="utf-8"))
            return "\n\n".join(parts)

        else:  # AGENT mode
            work_principle = abb_ws / "workflows" / "execution" / "work_principle.md"
            parts = ["# Persona: Deterministic Task Execution & Verification", *core_parts]
            if work_principle.exists():
                parts.append(work_principle.read_text(encoding="utf-8"))
            return "\n\n".join(parts)


# Global instance for runtime session
_ACTIVE_MODE_ENGINE = ModeEngine(default_mode=TriMode.PLAN)


def get_mode_engine() -> ModeEngine:
    """Get singleton ModeEngine instance."""
    return _ACTIVE_MODE_ENGINE
