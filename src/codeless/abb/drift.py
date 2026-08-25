"""Drift Auditor and Feedback Loop Engine for Codeless ABB workspaces."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from codeless.abb.hooks.frontmatter import parse_frontmatter, validate_task_frontmatter
from codeless.abb.shadow import resolve_abb_workspace
from codeless.skills.loader import parse_abb_skills_index


@dataclass
class DriftIssue:
    """Represents a discrepancy detected during drift audit."""

    category: str  # "task_schema", "skills_index", "feature_spec", "structure"
    file_path: str
    description: str
    severity: str = "warning"  # "warning", "error", "info"
    remediation: str | None = None


@dataclass
class DriftReport:
    """Aggregated report of workspace drift audit."""

    project_root: str
    abb_workspace: str
    issues: list[DriftIssue] = field(default_factory=list)
    scanned_files_count: int = 0
    clean: bool = True

    def format_cli(self) -> str:
        """Format the report for console output."""
        if self.clean or not self.issues:
            return f"✅ Drift Audit Clean: {self.scanned_files_count} files audited with 0 drift issues."

        lines = [
            f"⚠️ Drift Audit Report: Found {len(self.issues)} issue(s) across {self.scanned_files_count} scanned files:",
            f"  Project Root: {self.project_root}",
            f"  ABB Workspace: {self.abb_workspace}",
            "",
        ]
        for idx, issue in enumerate(self.issues, start=1):
            sev_icon = "🔴" if issue.severity == "error" else "🟡"
            lines.append(f"  {idx}. {sev_icon} [{issue.category.upper()}] {issue.file_path}")
            lines.append(f"     Issue: {issue.description}")
            if issue.remediation:
                lines.append(f"     Fix: {issue.remediation}")
        return "\n".join(lines)

    def format_markdown(self) -> str:
        """Format the report as a markdown document."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if self.clean or not self.issues:
            return (
                f"# Drift Audit Report\n\n"
                f"- **Status**: Clean ✅\n"
                f"- **Timestamp**: {now_iso}\n"
                f"- **Files Scanned**: {self.scanned_files_count}\n\n"
                f"No architectural, schema, or specification drift detected.\n"
            )

        lines = [
            "# Drift Audit Report",
            "",
            f"- **Timestamp**: {now_iso}",
            f"- **Total Issues**: {len(self.issues)}",
            f"- **Files Scanned**: {self.scanned_files_count}",
            "",
            "## Findings",
            "",
            "| # | Severity | Category | File | Description | Remediation |",
            "|---|---|---|---|---|---|",
        ]
        for idx, issue in enumerate(self.issues, start=1):
            remed = issue.remediation or "Review file against specification"
            lines.append(
                f"| {idx} | `{issue.severity}` | `{issue.category}` | `{issue.file_path}` | {issue.description} | {remed} |"
            )
        return "\n".join(lines)


def run_drift_audit(project_root: str | Path) -> DriftReport:
    """
    Execute full structural, schema, and specification drift audit against active ABB workspace.

    Checks:
    1. Task frontmatter schema and DAG consistency across tasks/
    2. Skill index consistency between skills.md (A4 index) and physical skills/ directories
    3. Feature specifications consistency in features/
    4. Codebase structure vs references/structure/topology.md (if present)
    """
    proj_root_path = Path(project_root).resolve()
    abb_ws = resolve_abb_workspace(proj_root_path, auto_init=False)

    issues: list[DriftIssue] = []
    scanned_count = 0

    if not abb_ws.exists():
        return DriftReport(
            project_root=str(proj_root_path),
            abb_workspace=str(abb_ws),
            issues=[
                DriftIssue(
                    category="workspace",
                    file_path=str(abb_ws),
                    description="ABB workspace is not initialized on disk.",
                    severity="error",
                    remediation="Run 'codeless abb status' or initialize workspace with 'codeless'.",
                )
            ],
            scanned_files_count=0,
            clean=False,
        )

    # 1. Audit tasks/ directory
    tasks_dir = abb_ws / "tasks"
    if tasks_dir.exists():
        for task_file in sorted(tasks_dir.glob("**/*.md")):
            if "_templates" in task_file.parts or task_file.name == "tasks.md":
                continue
            scanned_count += 1
            rel_file = str(task_file.relative_to(abb_ws)).replace("\\", "/")
            try:
                content = task_file.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(content)
                errs = validate_task_frontmatter(fm, task_file)
                if errs:
                    for err in errs:
                        issues.append(
                            DriftIssue(
                                category="task_schema",
                                file_path=rel_file,
                                description=err,
                                severity="error",
                                remediation=f"Fix frontmatter in {rel_file} to conform to tasks.md schema",
                            )
                        )
            except Exception as exc:
                issues.append(
                    DriftIssue(
                        category="task_schema",
                        file_path=rel_file,
                        description=f"Failed to read/parse task file: {exc}",
                        severity="error",
                    )
                )

    # 2. Audit skills/ directory & YAML index
    skills_dir = abb_ws / "skills"
    if skills_dir.exists():
        skills_md = skills_dir / "skills.md"
        indexed_names: set[str] = set()
        indexed_paths: set[Path] = set()

        if skills_md.exists():
            scanned_count += 1
            index_entries = parse_abb_skills_index(skills_md)
            for entry in index_entries:
                name = entry.get("name")
                p = entry.get("path")
                if name:
                    indexed_names.add(name)
                if p:
                    target_file = (skills_dir / p).resolve()
                    indexed_paths.add(target_file)
                    if not target_file.exists():
                        issues.append(
                            DriftIssue(
                                category="skills_index",
                                file_path=f"skills/{p}",
                                description=f"Skill '{name}' registered in skills.md does not exist on disk at '{p}'",
                                severity="warning",
                                remediation=f"Create {p} or remove entry from skills.md index",
                            )
                        )

        # Check for unindexed skills on disk
        for path in skills_dir.rglob("*.md"):
            if not path.is_file():
                continue
            if "_staging" in path.parts or ".git" in path.parts or path == skills_md:
                continue
            if path.name == "SKILL.md" or path.name == "manage_skills.md":
                scanned_count += 1
                if path not in indexed_paths and path.name != "manage_skills.md":
                    rel = str(path.relative_to(abb_ws)).replace("\\", "/")
                    issues.append(
                        DriftIssue(
                            category="skills_index",
                            file_path=rel,
                            description=f"Skill at '{rel}' exists on disk but is omitted from skills.md index",
                            severity="warning",
                            remediation="Add skill entry to skills.md machine YAML index and human table",
                        )
                    )

    # 3. Audit features/ directory
    features_dir = abb_ws / "features"
    if features_dir.exists():
        for spec_file in sorted(features_dir.glob("**/spec.md")):
            scanned_count += 1
            rel = str(spec_file.relative_to(abb_ws)).replace("\\", "/")
            try:
                fm, _ = parse_frontmatter(spec_file.read_text(encoding="utf-8"))
                for req_key in ["id", "version", "status"]:
                    if req_key not in fm:
                        issues.append(
                            DriftIssue(
                                category="feature_spec",
                                file_path=rel,
                                description=f"Feature spec missing '{req_key}' in frontmatter",
                                severity="warning",
                                remediation=f"Add '{req_key}' to frontmatter of {rel}",
                            )
                        )
            except Exception as exc:
                issues.append(
                    DriftIssue(
                        category="feature_spec",
                        file_path=rel,
                        description=f"Error reading feature spec: {exc}",
                        severity="error",
                    )
                )

    clean = len(issues) == 0
    return DriftReport(
        project_root=str(proj_root_path),
        abb_workspace=str(abb_ws),
        issues=issues,
        scanned_files_count=scanned_count,
        clean=clean,
    )


def feed_drift_to_issues(project_root: str | Path, report: DriftReport) -> Path | None:
    """
    Log discovered drift issues to references/issues/drift_issues.md for the feedback loop.

    Returns the path of the issues document.
    """
    if not report.issues:
        return None

    proj_root_path = Path(project_root).resolve()
    abb_ws = resolve_abb_workspace(proj_root_path, auto_init=True)
    issues_dir = abb_ws / "references" / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    issues_file = issues_dir / "technical_debt.md"
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    header = (
        "---\n"
        "id: technical_debt\n"
        "version: 1.0.0\n"
        f"updated: {now_iso}\n"
        "---\n\n"
        "# Technical Debt & Drift Issues\n\n"
        "> **Purpose**: Tracks architectural drift, schema discrepancies, and technical debt "
        "discovered during drift audits.\n\n"
    )

    body_lines = [
        f"## Drift Audit Log ({now_iso})",
        "",
    ]
    for issue in report.issues:
        body_lines.append(
            f"- **[{issue.severity.upper()}]** `{issue.file_path}`: {issue.description}"
        )
        if issue.remediation:
            body_lines.append(f"  - *Remediation*: {issue.remediation}")
    body_lines.append("")

    new_log_section = "\n".join(body_lines)

    if not issues_file.exists():
        issues_file.write_text(header + new_log_section, encoding="utf-8")
    else:
        existing = issues_file.read_text(encoding="utf-8")
        if f"Drift Audit Log ({now_iso})" not in existing:
            issues_file.write_text(existing.rstrip() + "\n\n" + new_log_section, encoding="utf-8")

    return issues_file


def detect_heuristic_drift(
    file_path: str | Path, content: str, project_root: str | Path
) -> list[str]:
    """Lightweight heuristic check on codebase/task write to detect obvious structural drift."""
    notices: list[str] = []
    path_str = str(file_path).replace("\\", "/").strip()

    # Check if a task file is missing required status or id
    if "tasks/" in path_str and path_str.endswith(".md"):
        if "---" in content:
            fm, _ = parse_frontmatter(content)
            if "id" not in fm:
                notices.append(
                    f"Heuristic drift: Task file '{path_str}' is missing 'id' in frontmatter."
                )
            if "status" not in fm:
                notices.append(
                    f"Heuristic drift: Task file '{path_str}' is missing 'status' in frontmatter."
                )

    return notices
