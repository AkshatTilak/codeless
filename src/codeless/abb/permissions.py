"""Tri-Mode / 5-Mode Permission Controller and Persona Composition Engine for Codeless."""

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
    GOVERNANCE = "governance"


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
            clean = mode.lower().strip()
            if clean in {"abb"}:
                clean = "governance"
            mode = TriMode(clean)
        self._current_mode = mode
        return self._current_mode

    def get_mode_description(self) -> str:
        descriptions = {
            TriMode.AGENT: "Full autonomous execution — code editing, testing, task completion.",
            TriMode.PLAN: "Architecture & Task Planning — writes restricted to tasks/ and design/.",
            TriMode.ASK: "Read-only Q&A — all file modifications blocked.",
            TriMode.CODEBASE: "Codebase exploration & memory queries — all file modifications blocked.",
            TriMode.GOVERNANCE: "ABB Meta-Spec Governance — writes restricted to STACK.md, agent.md, features/, references/, workflows/, skills/, conventions.",
        }
        return descriptions.get(self._current_mode, "Unknown mode policy")

    def get_upstream_permission_mode(self) -> PermissionMode:
        """Map TriMode to upstream PermissionMode."""
        if self._current_mode in {TriMode.PLAN, TriMode.ASK, TriMode.CODEBASE, TriMode.GOVERNANCE}:
            return PermissionMode.PLAN
        return PermissionMode.DEFAULT

    def get_allowed_tools(self, all_tools: list[str] | None = None) -> set[str]:
        """Return allowed tool names for active mode."""
        if self._current_mode in {TriMode.ASK, TriMode.CODEBASE}:
            return {
                "read_file", "glob", "grep", "lsp",
                "image_to_text", "ask_user_question",
                "skill", "abb_task",
            }
        elif self._current_mode in {TriMode.PLAN, TriMode.GOVERNANCE}:
            return {
                "read_file", "write_file", "edit_file", "glob", "grep", "lsp",
                "image_to_text", "ask_user_question", "todo_write",
                "skill", "abb_task", "abb_verify",
            }
        # AGENT mode
        if all_tools:
            return set(all_tools)
        return {
            "bash", "read_file", "write_file", "edit_file", "glob", "grep", "lsp",
            "image_to_text", "ask_user_question", "todo_write", "skill",
            "agent", "send_message", "task_stop", "task_output",
            "abb_task", "abb_verify",
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
            return False, f"{mode_name} Mode is strictly read-only; all file writes to '{norm_path}' are blocked."

        # 2. PLAN Mode: Write allowed ONLY to tasks/ and design/
        if self._current_mode == TriMode.PLAN:
            if is_abb:
                norm_lower = norm_path.lower()
                plan_prefixes = ("tasks/", "tasks", "design/", "design")
                if any(norm_lower.startswith(p) or f"/{p}" in norm_lower for p in plan_prefixes):
                    return True, "Plan mode permitted write to architecture & task workspace."
                return False, f"Plan Mode blocks meta-spec writes to '{norm_path}'. Use Governance mode (`/mode governance`) for meta specs."
            return False, f"Plan Mode blocks project code modifications to '{norm_path}'. Switch to Agent mode (`/mode agent`) to execute changes."

        # 3. GOVERNANCE Mode: Write allowed ONLY to meta-specs (STACK, agent, features, references, skills, workflows, conventions)
        if self._current_mode == TriMode.GOVERNANCE:
            if is_abb:
                norm_lower = norm_path.lower()
                gov_prefixes = (
                    "features/", "features", "references/", "references",
                    "skills/", "skills", "workflows/", "workflows",
                    "stack.md", "user_preferences.md", "agent.md", "conventions.md",
                    "coding_philosophy.md", "changelog.md", "readme.md"
                )
                if any(norm_lower.startswith(p) or f"/{p}" in norm_lower or norm_lower.endswith(p) for p in gov_prefixes):
                    return True, "Governance mode permitted write to ABB meta-specifications."
                plan_prefixes = ("tasks/", "tasks", "design/", "design")
                if any(norm_lower.startswith(p) or f"/{p}" in norm_lower for p in plan_prefixes):
                    return False, f"Governance Mode blocks task/design writes to '{norm_path}'. Switch to Plan mode (`/mode plan`) to update tasks."
            return False, f"Governance Mode blocks project code modifications to '{norm_path}'. Switch to Agent mode (`/mode agent`) to execute changes."


        # 4. AGENT Mode: Write allowed everywhere
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

        elif self._current_mode == TriMode.GOVERNANCE:
            gov_md = abb_ws / "workflows" / "planning" / "governance.md"
            parts = ["# Persona: ABB Meta-Specification Governance", *core_parts]
            if gov_md.exists():
                parts.append(gov_md.read_text(encoding="utf-8"))
            return "\n\n".join(parts)

        else:  # AGENT mode
            work_principle = abb_ws / "workflows" / "execution" / "work_principle.md"
            parts = ["# Persona: Deterministic Task Execution & Verification", *core_parts]
            if work_principle.exists():
                parts.append(work_principle.read_text(encoding="utf-8"))
            return "\n\n".join(parts)


# Global instance for runtime session
_ACTIVE_MODE_ENGINE = ModeEngine(default_mode=TriMode.AGENT)


def get_mode_engine() -> ModeEngine:
    """Get singleton ModeEngine instance."""
    return _ACTIVE_MODE_ENGINE

