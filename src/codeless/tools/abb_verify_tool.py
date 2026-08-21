"""Read-only ABB Two-Track verification runner tool."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import (
    execute_verification_manifest,
    parse_verification_manifest,
)
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class AbbVerifyToolInput(BaseModel):
    dry_run: bool = Field(
        False,
        description="If True, returns the list of verification commands that would execute without running them.",
    )
    include_lint: bool = Field(
        False,
        description="Whether to also run the lint track commands.",
    )
    include_typecheck: bool = Field(
        False,
        description="Whether to also run the typecheck track commands.",
    )


class AbbVerifyTool(BaseTool):
    """Tool for programmatically executing Two-Track verification."""

    name = "abb_verify"
    description = (
        "Run the Two-Track verification manifest defined in STACK.md. "
        "Executes Track 1 (unit) and Track 2 (system/E2E) tests. "
        "This tool is read-only and reports test results without mutating task statuses."
    )
    input_model = AbbVerifyToolInput

    async def execute(
        self,
        arguments: AbbVerifyToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        dry_run = arguments.dry_run
        include_lint = arguments.include_lint
        include_typecheck = arguments.include_typecheck
        cwd = Path(context.cwd).resolve()
        try:
            abb_ws = resolve_abb_workspace(cwd, auto_init=False)
            stack_file = abb_ws / "STACK.md"
            if not stack_file.exists():
                return ToolResult(
                    output="No STACK.md found in ABB workspace. Cannot run verification.",
                    is_error=True,
                )
        except Exception as exc:
            return ToolResult(output=f"Failed to resolve ABB workspace: {exc}", is_error=True)

        manifest = parse_verification_manifest(stack_file)
        if not manifest.track_1 and not manifest.track_2:
            return ToolResult(
                output="No verification manifest commands configured under 'verification:' in STACK.md."
            )

        if dry_run:
            lines = ["# Two-Track Verification Manifest (Dry-Run Preview)", ""]
            lines.append(f"**Track 1 (Unit)**: {len(manifest.track_1)} command(s)")
            for cmd in manifest.track_1:
                lines.append(f"  • `{cmd}`")
            lines.append(f"\n**Track 2 (System/E2E)**: {len(manifest.track_2)} command(s)")
            for cmd in manifest.track_2:
                lines.append(f"  • `{cmd}`")
            if manifest.lint:
                lines.append(f"\n**Lint Track**: {len(manifest.lint)} command(s)")
                for cmd in manifest.lint:
                    lines.append(f"  • `{cmd}`")
            if manifest.typecheck:
                lines.append(f"\n**Typecheck Track**: {len(manifest.typecheck)} command(s)")
                for cmd in manifest.typecheck:
                    lines.append(f"  • `{cmd}`")
            return ToolResult(output="\n".join(lines))

        report = await execute_verification_manifest(
            manifest,
            cwd=cwd,
            include_lint=include_lint,
            include_typecheck=include_typecheck,
        )

        status_str = "PASSED ✅" if report.success else "FAILED ❌"
        lines = [f"# Verification Report: {status_str}", f"Summary: {report.summary}", ""]

        def _format_reports(title: str, reports):
            if not reports:
                return
            lines.append(f"### {title}")
            for r in reports:
                r_status = "✅ Pass" if r.success else f"❌ Fail (exit {r.exit_code})"
                lines.append(f"- `{r.command}`: {r_status} ({r.duration_seconds:.2f}s)")
                if not r.success:
                    if r.stderr.strip():
                        lines.append(f"  **Stderr**:\n```\n{r.stderr.strip()[:1500]}\n```")
                    if r.stdout.strip():
                        lines.append(f"  **Stdout**:\n```\n{r.stdout.strip()[:1500]}\n```")

        _format_reports("Track 1 (Unit Tests)", report.track_1_reports)
        _format_reports("Track 2 (System Tests)", report.track_2_reports)
        _format_reports("Lint Checks", report.lint_reports)
        _format_reports("Type Checks", report.typecheck_reports)

        return ToolResult(output="\n".join(lines))
