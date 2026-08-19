"""Filesystem globbing tool."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field

from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult


class GlobToolInput(BaseModel):
    """Arguments for the glob tool."""

    pattern: str = Field(
        description="Glob pattern relative to the working directory",
        validation_alias=AliasChoices("pattern", "path"),
    )
    root: str | None = Field(default=None, description="Optional search root")
    limit: int = Field(default=200, ge=1, le=5000)


class GlobTool(BaseTool):
    """List files matching a glob pattern."""

    name = "glob"
    description = "List files matching a glob pattern."
    input_model = GlobToolInput

    def is_read_only(self, arguments: GlobToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GlobToolInput, context: ToolExecutionContext) -> ToolResult:
        root, pattern = _resolve_glob_request(context.cwd, arguments.root, arguments.pattern)
        matches = await _glob(root, pattern, limit=arguments.limit)

        # If searching root and shadow workspace exists, merge ABB shadow workspace matches
        if not arguments.root:
            abb_ws = resolve_abb_workspace(context.cwd, auto_init=True)
            if abb_ws.exists() and abb_ws.resolve() != context.cwd.resolve():
                abb_matches = await _glob(abb_ws, pattern, limit=arguments.limit)
                if abb_matches:
                    seen = set(matches)
                    for m in abb_matches:
                        if m not in seen:
                            matches.append(m)
                            seen.add(m)
                    matches.sort()
                    matches = matches[:arguments.limit]

        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(matches))


from codeless.abb.virtualization import is_abb_path, resolve_virtual_path
from codeless.abb.shadow import resolve_abb_workspace


def _resolve_path(base: Path, candidate: str | None) -> Path:
    if not candidate or candidate == ".":
        return base.resolve()
    return resolve_virtual_path(base, candidate)


def _resolve_glob_request(base: Path, root_arg: str | None, pattern: str) -> tuple[Path, str]:
    """Return a concrete search root plus a root-relative glob pattern."""
    if root_arg:
        return (_resolve_path(base, root_arg), pattern)

    if not pattern.strip():
        return (base, pattern)

    candidate = Path(pattern).expanduser()
    if not candidate.is_absolute():
        if is_abb_path(candidate):
            abb_ws = resolve_abb_workspace(base)
            return (abb_ws, pattern)
        return (base, pattern)

    parts = candidate.parts
    first_glob_index = next(
        (index for index, part in enumerate(parts) if _has_glob_magic(part)),
        None,
    )
    if first_glob_index is None:
        return candidate.parent.resolve(), candidate.name

    root_parts = parts[:first_glob_index]
    root = Path(*root_parts).resolve() if root_parts else Path(candidate.anchor or "/").resolve()
    relative_pattern = str(Path(*parts[first_glob_index:]))
    return root, relative_pattern


def _has_glob_magic(value: str) -> bool:
    return any(char in value for char in "*?[")


def _looks_like_git_repo(path: Path) -> bool:
    """Heuristic: determine whether we should include hidden paths when searching.

    For codebases, hidden dirs like `.github/` are relevant; for arbitrary dirs
    (like a user's home), searching hidden paths can explode the search space.
    """
    current = path
    for _ in range(6):
        git_dir = current / ".git"
        if git_dir.exists():
            return True
        if current.parent == current:
            break
        current = current.parent
    return False


_GLOB_RG_TIMEOUT_SECONDS = 30.0


async def _glob(root: Path, pattern: str, *, limit: int) -> list[str]:
    """Fast glob implementation.

    Uses ripgrep's file walker when available (respects .gitignore and can skip
    heavy directories like `.venv/`), with a Python fallback.
    """
    if not root.exists() or not root.is_dir():
        return []

    rg = shutil.which("rg")
    # `Path.glob("**/*")` will traverse hidden and ignored paths (like `.venv/`)
    # and can be very slow on real workspaces. Prefer `rg --files`.
    if rg and ("**" in pattern or "/" in pattern):
        include_hidden = _looks_like_git_repo(root)
        cmd = [rg, "--files"]
        if include_hidden:
            cmd.append("--hidden")
        cmd.extend(["--glob", pattern, "."])

        from codeless.sandbox.session import get_docker_sandbox

        session = get_docker_sandbox()
        if session is not None and session.is_running:
            process = await session.exec_command(
                cmd,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

        lines: list[str] = []

        async def _read_stdout() -> None:
            assert process.stdout is not None
            while len(lines) < limit:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)

        try:
            try:
                await asyncio.wait_for(_read_stdout(), timeout=_GLOB_RG_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                pass
        finally:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()

        # Sorting keeps unit tests and user output deterministic for small results.
        lines.sort()
        return lines

    # Fallback: non-recursive patterns are usually cheap; keep Python semantics.
    return sorted(
        str(path.relative_to(root))
        for path in root.glob(pattern)
    )[:limit]
