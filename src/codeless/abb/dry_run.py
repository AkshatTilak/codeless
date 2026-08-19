"""ABB Dry-Run Preview and Readiness Auditor (C14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from codeless.abb.hooks.dag_guard import check_dag_dependencies, index_tasks
from codeless.abb.hooks.frontmatter import parse_frontmatter, validate_task_frontmatter
from codeless.abb.permissions import get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import parse_verification_manifest


@dataclass
class DryRunCheckItem:
    name: str
    status: Literal["ok", "warning", "blocked"]
    detail: str
    hint: str | None = None


@dataclass
class DryRunReport:
    overall_status: Literal["ready", "warning", "blocked"]
    workspace_path: Path
    abb_workspace_path: Path
    checks: list[DryRunCheckItem] = field(default_factory=list)

    def format_report(self) -> str:
        symbol_map = {
            "ok": "✅",
            "warning": "⚠️",
            "blocked": "🚫",
        }
        verdict_badge = {
            "ready": "🟢 READY",
            "warning": "🟡 WARNING",
            "blocked": "🔴 BLOCKED",
        }

        lines = [
            f"=== Codeless ABB Dry-Run Pre-Flight Audit ===",
            f"Verdict: {verdict_badge[self.overall_status]}",
            f"Project Root: {self.workspace_path}",
            f"ABB Workspace: {self.abb_workspace_path}",
            "",
            "Readiness Checks:",
        ]

        for check in self.checks:
            badge = symbol_map.get(check.status, "❓")
            lines.append(f"  {badge} [{check.status.upper():<7}] {check.name}: {check.detail}")
            if check.hint:
                lines.append(f"             Hint: {check.hint}")

        lines.append("")
        if self.overall_status == "ready":
            lines.append("All ABB subsystems ready for autonomous task execution.")
        elif self.overall_status == "warning":
            lines.append("Environment operational with non-critical warnings. See hints above.")
        else:
            lines.append("Environment blocked. Please resolve required items before running.")

        return "\n".join(lines)


def audit_abb_readiness(cwd: Path | str) -> DryRunReport:
    """Audit project for ABB shadow workspace, STACK manifest, DAG integrity, and hooks."""
    project_root = Path(cwd).resolve()
    checks: list[DryRunCheckItem] = []

    # 1. Shadow Workspace Check
    abb_ws = resolve_abb_workspace(project_root, auto_init=False)
    if not abb_ws.exists():
        checks.append(
            DryRunCheckItem(
                name="Shadow Workspace",
                status="blocked",
                detail=f"No ABB workspace found at {abb_ws}",
                hint="Run 'codeless' in dev mode or configure .codeless/abb_workspace",
            )
        )
        return DryRunReport(
            overall_status="blocked",
            workspace_path=project_root,
            abb_workspace_path=abb_ws,
            checks=checks,
        )

    # Check VERSION
    version_file = abb_ws / "VERSION"
    if version_file.exists():
        v_str = version_file.read_text(encoding="utf-8").strip()
        checks.append(
            DryRunCheckItem(
                name="Shadow Workspace & Template Version",
                status="ok",
                detail=f"Found workspace (Template version {v_str})",
            )
        )
    else:
        checks.append(
            DryRunCheckItem(
                name="Shadow Workspace",
                status="ok",
                detail=f"Found workspace at {abb_ws}",
            )
        )

    # 2. STACK.md & Verification Manifest Check
    stack_file = abb_ws / "STACK.md"
    if not stack_file.exists():
        checks.append(
            DryRunCheckItem(
                name="STACK.md Manifest",
                status="warning",
                detail="Missing STACK.md",
                hint="Create STACK.md with verification commands for automated quality gates",
            )
        )
    else:
        manifest = parse_verification_manifest(stack_file)
        if manifest.track_1 or manifest.track_2:
            t1_count = len(manifest.track_1)
            t2_count = len(manifest.track_2)
            checks.append(
                DryRunCheckItem(
                    name="STACK.md Verification Manifest",
                    status="ok",
                    detail=f"Configured with {t1_count} Track 1 and {t2_count} Track 2 command(s)",
                )
            )
        else:
            checks.append(
                DryRunCheckItem(
                    name="STACK.md Verification Manifest",
                    status="warning",
                    detail="STACK.md exists but has no verification commands defined",
                    hint="Add 'verification: track_1: [...] track_2: [...]' to frontmatter",
                )
            )

    # 3. DAG Graph & Dependency Integrity Check
    tasks_dir = abb_ws / "tasks"
    if not tasks_dir.exists():
        checks.append(
            DryRunCheckItem(
                name="Task DAG",
                status="warning",
                detail="No tasks/ directory found in ABB workspace",
                hint="Use `/plan <goal>` to decompose initial architecture",
            )
        )
    else:
        task_index = index_tasks(tasks_dir)
        missing_deps: list[str] = []
        schema_errs: list[str] = []

        for tid, (path, fm) in task_index.items():
            errs = validate_task_frontmatter(fm, path)
            if errs:
                schema_errs.append(f"{tid} ({len(errs)} schema error(s))")

            deps = fm.get("depends_on", [])
            for dep in deps:
                if dep not in task_index:
                    missing_deps.append(f"{tid} -> missing dependency '{dep}'")

        if schema_errs:
            checks.append(
                DryRunCheckItem(
                    name="Task Frontmatter Schema",
                    status="warning",
                    detail=f"{len(schema_errs)} task(s) have frontmatter issues: {', '.join(schema_errs[:3])}",
                    hint="Run '/drift' to inspect frontmatter schema issues",
                )
            )
        else:
            checks.append(
                DryRunCheckItem(
                    name="Task Frontmatter Schema",
                    status="ok",
                    detail=f"All {len(task_index)} task frontmatter headers valid",
                )
            )

        if missing_deps:
            checks.append(
                DryRunCheckItem(
                    name="Task DAG Integrity",
                    status="warning",
                    detail=f"Broken dependencies found: {'; '.join(missing_deps[:3])}",
                    hint="Ensure all referenced task IDs exist in tasks/base/ or tasks/sub/",
                )
            )
        else:
            checks.append(
                DryRunCheckItem(
                    name="Task DAG Integrity",
                    status="ok",
                    detail=f"DAG graph consistent ({len(task_index)} total tasks indexed, 0 broken links)",
                )
            )

    # 4. Hooks & Mode Engine
    mode_engine = get_mode_engine()
    checks.append(
        DryRunCheckItem(
            name="Tri-Mode Controller",
            status="ok",
            detail=f"Active mode: {mode_engine.current_mode.value.upper()}",
        )
    )

    # Determine overall status
    if any(c.status == "blocked" for c in checks):
        overall = "blocked"
    elif any(c.status == "warning" for c in checks):
        overall = "warning"
    else:
        overall = "ready"

    return DryRunReport(
        overall_status=overall,
        workspace_path=project_root,
        abb_workspace_path=abb_ws,
        checks=checks,
    )
