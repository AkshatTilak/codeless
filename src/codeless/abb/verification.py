"""Two-Track Verification Runner and Manifest Engine for Codeless."""

from __future__ import annotations

import asyncio
import datetime
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeless.abb.hooks.frontmatter import parse_frontmatter
from codeless.abb.shadow import get_project_storage_dir
from codeless.utils.shell import create_shell_subprocess


@dataclass
class CommandReport:
    """Execution result for a single verification command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class VerificationManifest:
    """Manifest parsed from STACK.md frontmatter verification block."""

    track_1: list[str] = field(default_factory=list)
    track_2: list[str] = field(default_factory=list)
    lint: list[str] = field(default_factory=list)
    typecheck: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationManifest:
        def _normalize_list(val: Any) -> list[str]:
            if isinstance(val, str):
                val = val.strip()
                return [val] if val else []
            elif isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
            return []

        return cls(
            track_1=_normalize_list(data.get("track_1")),
            track_2=_normalize_list(data.get("track_2")),
            lint=_normalize_list(data.get("lint")),
            typecheck=_normalize_list(data.get("typecheck")),
        )


@dataclass
class VerificationReport:
    """Aggregated verification report for Track 1 and Track 2."""

    success: bool
    track_1_reports: list[CommandReport] = field(default_factory=list)
    track_2_reports: list[CommandReport] = field(default_factory=list)
    lint_reports: list[CommandReport] = field(default_factory=list)
    typecheck_reports: list[CommandReport] = field(default_factory=list)
    summary: str = ""

    def format_failure_diagnostic(self) -> str:
        """Format an actionable diagnostic error message for model remediation."""
        lines = [f"❌ Verification Failed: {self.summary}"]

        all_failed = (
            [("Track 1 (Unit)", r) for r in self.track_1_reports if not r.success]
            + [("Track 2 (System)", r) for r in self.track_2_reports if not r.success]
            + [("Lint", r) for r in self.lint_reports if not r.success]
            + [("Typecheck", r) for r in self.typecheck_reports if not r.success]
        )

        for stage, report in all_failed:
            lines.append(f"\n--- {stage}: `{report.command}` ---")
            if report.timed_out:
                lines.append(f"Timed out after {report.duration_seconds:.1f}s")
            else:
                lines.append(f"Exit Code: {report.exit_code}")
            if report.stderr.strip():
                lines.append(f"Stderr:\n{report.stderr.strip()[:2000]}")
            if report.stdout.strip():
                lines.append(f"Stdout:\n{report.stdout.strip()[:2000]}")

        return "\n".join(lines)


def parse_verification_manifest(stack_source: Path | str) -> VerificationManifest:
    """Parse verification manifest from STACK.md file or string content."""
    content: str
    if isinstance(stack_source, Path):
        if not stack_source.exists():
            return VerificationManifest()
        content = stack_source.read_text(encoding="utf-8")
    else:
        content = stack_source

    fm, _ = parse_frontmatter(content)
    ver_data = fm.get("verification")
    if isinstance(ver_data, dict):
        return VerificationManifest.from_dict(ver_data)
    return VerificationManifest()


async def run_command_async(
    command: str,
    cwd: Path | str,
    timeout_seconds: float = 120.0,
) -> CommandReport:
    """Run a single shell command asynchronously with timeout and output capture."""
    start_time = time.perf_counter()
    cwd_path = Path(cwd).resolve()

    try:
        proc = await create_shell_subprocess(
            command,
            cwd=cwd_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            duration = time.perf_counter() - start_time
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else 1

            return CommandReport(
                command=command,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_seconds=duration,
                timed_out=False,
            )
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            duration = time.perf_counter() - start_time
            return CommandReport(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds} seconds",
                duration_seconds=duration,
                timed_out=True,
            )
    except Exception as exc:
        duration = time.perf_counter() - start_time
        return CommandReport(
            command=command,
            exit_code=1,
            stdout="",
            stderr=f"Failed to spawn command: {exc}",
            duration_seconds=duration,
            timed_out=False,
        )


async def execute_verification_manifest(
    manifest: VerificationManifest,
    cwd: Path | str,
    tracks: tuple[int, ...] = (1, 2),
    include_lint: bool = False,
    include_typecheck: bool = False,
) -> VerificationReport:
    """Execute manifest commands for the specified tracks and quality checks."""
    t1_reports: list[CommandReport] = []
    t2_reports: list[CommandReport] = []
    lint_reports: list[CommandReport] = []
    tc_reports: list[CommandReport] = []
    overall_success = True

    # Track 1
    if 1 in tracks:
        for cmd in manifest.track_1:
            report = await run_command_async(cmd, cwd)
            t1_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Track 2 (only if Track 1 passes)
    if overall_success and 2 in tracks:
        for cmd in manifest.track_2:
            report = await run_command_async(cmd, cwd)
            t2_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Lint
    if overall_success and include_lint:
        for cmd in manifest.lint:
            report = await run_command_async(cmd, cwd)
            lint_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Typecheck
    if overall_success and include_typecheck:
        for cmd in manifest.typecheck:
            report = await run_command_async(cmd, cwd)
            tc_reports.append(report)
            if not report.success:
                overall_success = False
                break

    summary = (
        "All verification tracks passed."
        if overall_success
        else "One or more verification checks failed."
    )
    return VerificationReport(
        success=overall_success,
        track_1_reports=t1_reports,
        track_2_reports=t2_reports,
        lint_reports=lint_reports,
        typecheck_reports=tc_reports,
        summary=summary,
    )


def run_command_sync(
    command: str,
    cwd: Path | str,
    timeout_seconds: float = 120.0,
) -> CommandReport:
    """Run a single shell command synchronously with timeout and output capture."""
    start_time = time.perf_counter()
    cwd_path = Path(cwd).resolve()

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )

        duration = time.perf_counter() - start_time
        return CommandReport(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start_time
        stdout_str = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout.decode("utf-8", "replace") if exc.stdout else "")
        )
        stderr_str = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr.decode("utf-8", "replace") if exc.stderr else "")
        )
        return CommandReport(
            command=command,
            exit_code=-1,
            stdout=stdout_str,
            stderr=f"Command timed out after {timeout_seconds} seconds\n{stderr_str}",
            duration_seconds=duration,
            timed_out=True,
        )
    except Exception as exc:
        duration = time.perf_counter() - start_time
        return CommandReport(
            command=command,
            exit_code=1,
            stdout="",
            stderr=f"Failed to spawn command: {exc}",
            duration_seconds=duration,
            timed_out=False,
        )


def execute_verification_manifest_sync(
    manifest: VerificationManifest,
    cwd: Path | str,
    tracks: tuple[int, ...] = (1, 2),
    include_lint: bool = False,
    include_typecheck: bool = False,
) -> VerificationReport:
    """Execute manifest commands synchronously for the specified tracks and quality checks."""
    t1_reports: list[CommandReport] = []
    t2_reports: list[CommandReport] = []
    lint_reports: list[CommandReport] = []
    tc_reports: list[CommandReport] = []
    overall_success = True

    # Track 1
    if 1 in tracks:
        for cmd in manifest.track_1:
            report = run_command_sync(cmd, cwd)
            t1_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Track 2 (only if Track 1 passes)
    if overall_success and 2 in tracks:
        for cmd in manifest.track_2:
            report = run_command_sync(cmd, cwd)
            t2_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Lint
    if overall_success and include_lint:
        for cmd in manifest.lint:
            report = run_command_sync(cmd, cwd)
            lint_reports.append(report)
            if not report.success:
                overall_success = False
                break

    # Typecheck
    if overall_success and include_typecheck:
        for cmd in manifest.typecheck:
            report = run_command_sync(cmd, cwd)
            tc_reports.append(report)
            if not report.success:
                overall_success = False
                break

    summary = (
        "All verification tracks passed."
        if overall_success
        else "One or more verification checks failed."
    )
    return VerificationReport(
        success=overall_success,
        track_1_reports=t1_reports,
        track_2_reports=t2_reports,
        lint_reports=lint_reports,
        typecheck_reports=tc_reports,
        summary=summary,
    )


def verify_subtask_gate(
    task_id: str,
    project_root: Path,
    abb_ws: Path,
) -> tuple[bool, str, VerificationReport | None]:
    """
    Verification gate for transitioning a subtask to 'done'.
    Returns (passed, reason, optional_report).
    """
    stack_file = abb_ws / "STACK.md"
    manifest = parse_verification_manifest(stack_file)

    # If no verification commands declared in manifest, operate as soft gate with warning (C11)
    if not manifest.track_1 and not manifest.track_2:
        return True, "Soft gate: No manifest commands configured in STACK.md", None

    report = execute_verification_manifest_sync(manifest, project_root)
    if not report.success:
        log_path = record_verification_failure(project_root, task_id, report)
        diag = report.format_failure_diagnostic()
        reason = f"{diag}\nFailure details logged to: {log_path}"
        return False, reason, report

    return True, "Two-track verification passed", report


def record_verification_failure(
    project_root: Path,
    task_id: str,
    report: VerificationReport,
) -> Path:
    """Record verification failure diagnostic report to logs/failure/."""
    storage_dir = get_project_storage_dir(project_root)
    failure_dir = storage_dir / "logs" / "failure"
    failure_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = failure_dir / f"verification_{task_id}_{timestamp}.log"
    log_content = report.format_failure_diagnostic()
    log_file.write_text(log_content, encoding="utf-8")
    return log_file


def get_dag_snapshot(abb_ws: Path) -> dict[str, Any]:
    """Generate a structured topological DAG snapshot for session state and context compaction."""
    # Resolve tasks_dir whether abb_ws is repo root or direct ABB workspace
    tasks_dir = abb_ws / "tasks"
    if not tasks_dir.exists():
        if (abb_ws / ".codeless" / "abb_workspace" / "tasks").exists():
            tasks_dir = abb_ws / ".codeless" / "abb_workspace" / "tasks"
        else:
            try:
                tasks_dir = resolve_abb_workspace(abb_ws, auto_init=False) / "tasks"
            except Exception:
                pass

    snapshot: dict[str, Any] = {
        "goal": None,
        "goals": [],
        "base_tasks": [],
        "subtasks": [],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if not tasks_dir.exists():
        return snapshot

    # 1. Discover all goal files (versioned and flat)
    goals: list[dict[str, Any]] = []
    # Flat goal
    if (tasks_dir / "goal").exists():
        for gf in sorted((tasks_dir / "goal").glob("*.md")):
            try:
                fm, _ = parse_frontmatter(gf.read_text(encoding="utf-8"))
                if fm:
                    goals.append(fm)
            except Exception:
                pass

    # Versioned goals: tasks/<version>/goal/*.md
    for child in sorted(tasks_dir.iterdir()):
        if child.is_dir() and child.name != "_templates" and (child / "goal").exists():
            for gf in sorted((child / "goal").glob("*.md")):
                try:
                    fm, _ = parse_frontmatter(gf.read_text(encoding="utf-8"))
                    if fm:
                        fm.setdefault("_version_folder", child.name)
                        goals.append(fm)
                except Exception:
                    pass

    snapshot["goals"] = goals
    # Active goal: prefer in_progress, else latest
    active_goal = None
    for g in goals:
        if g.get("status") == "in_progress":
            active_goal = g
            break
    if not active_goal and goals:
        active_goal = goals[-1]
    snapshot["goal"] = active_goal

    # 2. Discover all base tasks (flat and versioned)
    base_tasks: list[dict[str, Any]] = []
    if (tasks_dir / "base").exists():
        for bfile in sorted((tasks_dir / "base").glob("*.md")):
            try:
                fm, _ = parse_frontmatter(bfile.read_text(encoding="utf-8"))
                if fm:
                    base_tasks.append(fm)
            except Exception:
                pass

    for child in sorted(tasks_dir.iterdir()):
        if child.is_dir() and child.name != "_templates" and (child / "base").exists():
            for bfile in sorted((child / "base").glob("*.md")):
                try:
                    fm, _ = parse_frontmatter(bfile.read_text(encoding="utf-8"))
                    if fm:
                        fm.setdefault("_version_folder", child.name)
                        base_tasks.append(fm)
                except Exception:
                    pass
    snapshot["base_tasks"] = base_tasks

    # 3. Discover all subtasks (flat and versioned)
    subtasks: list[dict[str, Any]] = []
    if (tasks_dir / "sub").exists():
        for sfile in sorted((tasks_dir / "sub").glob("*.md")):
            try:
                fm, _ = parse_frontmatter(sfile.read_text(encoding="utf-8"))
                if fm:
                    subtasks.append(fm)
            except Exception:
                pass

    for child in sorted(tasks_dir.iterdir()):
        if child.is_dir() and child.name != "_templates" and (child / "sub").exists():
            for sfile in sorted((child / "sub").glob("*.md")):
                try:
                    fm, _ = parse_frontmatter(sfile.read_text(encoding="utf-8"))
                    if fm:
                        fm.setdefault("_version_folder", child.name)
                        subtasks.append(fm)
                except Exception:
                    pass
    snapshot["subtasks"] = subtasks

    return snapshot

