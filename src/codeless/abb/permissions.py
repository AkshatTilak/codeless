"""4-Mode Permission Controller and Persona Composition Engine for Codeless."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.virtualization import is_abb_path
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
                "read_file",
                "glob",
                "grep",
                "lsp",
                "image_to_text",
                "ask_user_question",
                "skill",
                "tool_search",
                "brief",
                "sleep",
                "abb_task",
                "cron",
                "task",
                "worktree",
                "mcp_resource",
                "web",
                "web_search",
                "web_fetch",
                "web_crawl",
            }
        elif self._current_mode == TriMode.PLAN:
            return {
                "read_file",
                "write_file",
                "edit_file",
                "notebook_edit",
                "glob",
                "grep",
                "lsp",
                "image_to_text",
                "image_generation",
                "ask_user_question",
                "todo_write",
                "skill",
                "tool_search",
                "config",
                "brief",
                "sleep",
                "abb_task",
                "abb_verify",
                "cron",
                "task",
                "worktree",
                "mcp_resource",
                "web",
                "web_search",
                "web_fetch",
                "web_crawl",
            }
        # AGENT mode
        if all_tools:
            return set(all_tools)
        return {
            "bash",
            "read_file",
            "write_file",
            "edit_file",
            "notebook_edit",
            "glob",
            "grep",
            "lsp",
            "image_to_text",
            "image_generation",
            "ask_user_question",
            "todo_write",
            "skill",
            "tool_search",
            "config",
            "brief",
            "sleep",
            "agent",
            "send_message",
            "task",
            "task_stop",
            "task_output",
            "cron",
            "worktree",
            "mcp_resource",
            "web",
            "web_search",
            "web_fetch",
            "web_crawl",
            "abb_task",
            "abb_verify",
        }

    def evaluate_write_permission(
        self,
        target_path: str | Path,
        cwd: Path,
    ) -> tuple[bool, str]:
        """
        Evaluate write/edit permission for target path given the active TriMode.
        Returns (allowed, reason).
        """
        norm_path = str(target_path).replace("\\", "/").strip()
        is_abb = is_abb_path(norm_path)

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
