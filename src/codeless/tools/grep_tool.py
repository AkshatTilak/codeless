"""Content search tool with a pure-Python fallback."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.virtualization import is_abb_path, resolve_virtual_path
from codeless.tools.base import BaseTool, ToolExecutionContext, ToolResult
from codeless.utils.rg import find_ripgrep

_IGNORED_FALLBACK_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    ".cache",
    ".codeless",
    ".gemini",
    ".idea",
    ".vscode",
}


def _resolve_rg() -> str | None:
    """Resolve ripgrep binary, checking PATH before scanning candidates."""
    which = shutil.which("rg")
    if which:
        return which
    return find_ripgrep()


class GrepToolInput(BaseModel):
    """Arguments for the grep tool."""

    pattern: str = Field(description="Regular expression to search for")
    root: str | None = Field(
        default=None,
        description="Search root directory or file. For multiple roots, call grep separately per root.",
    )
    file_glob: str = Field(default="**/*")
    case_sensitive: bool = Field(default=True)
    limit: int = Field(default=200, ge=1, le=2000)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class GrepTool(BaseTool):
    """Search text files for a regex pattern."""

    name = "grep"
    description = "Search file contents with a regular expression."
    input_model = GrepToolInput

    def is_read_only(self, arguments: GrepToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GrepToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.root:
            root = resolve_virtual_path(context.cwd, arguments.root)
        elif arguments.file_glob and is_abb_path(arguments.file_glob, project_root=context.cwd):
            first_part = (
                Path(arguments.file_glob).parts[0] if Path(arguments.file_glob).parts else ""
            )
            if first_part and (context.cwd / first_part).exists():
                root = context.cwd
            else:
                root = resolve_abb_workspace(context.cwd)
        else:
            root = context.cwd
        if not root.exists():
            return ToolResult(
                output=(
                    f"Search root does not exist: {root}\n"
                    "If you intended multiple roots, call grep separately for each root."
                ),
                is_error=True,
            )
        if root.is_file():
            display_base = _display_base(root, context.cwd)
            matches = await _rg_grep_file(
                path=root,
                pattern=arguments.pattern,
                case_sensitive=arguments.case_sensitive,
                limit=arguments.limit,
                display_base=display_base,
                timeout_seconds=arguments.timeout_seconds,
            )
            if matches is not None:
                return _format_rg_result(matches, arguments.timeout_seconds)

            try:
                output = await asyncio.wait_for(
                    asyncio.to_thread(
                        _python_grep_files,
                        paths=[root],
                        pattern=arguments.pattern,
                        case_sensitive=arguments.case_sensitive,
                        limit=arguments.limit,
                        display_base=display_base,
                    ),
                    timeout=arguments.timeout_seconds,
                )
                return ToolResult(output=output)
            except asyncio.TimeoutError:
                return ToolResult(
                    output=f"[grep timed out after {arguments.timeout_seconds} seconds]",
                    is_error=True,
                )

        # Prefer ripgrep for performance; fallback to Python when unavailable.
        matches = await _rg_grep(
            root=root,
            pattern=arguments.pattern,
            file_glob=arguments.file_glob,
            case_sensitive=arguments.case_sensitive,
            limit=arguments.limit,
            timeout_seconds=arguments.timeout_seconds,
        )
        if matches is not None:
            return _format_rg_result(matches, arguments.timeout_seconds)

        # Python fallback (kept for portability).
        try:
            output = await asyncio.wait_for(
                asyncio.to_thread(
                    _python_grep_dir,
                    root=root,
                    file_glob=arguments.file_glob,
                    pattern=arguments.pattern,
                    case_sensitive=arguments.case_sensitive,
                    limit=arguments.limit,
                    display_base=root,
                ),
                timeout=arguments.timeout_seconds,
            )
            return ToolResult(output=output)
        except asyncio.TimeoutError:
            return ToolResult(
                output=f"[grep timed out after {arguments.timeout_seconds} seconds]",
                is_error=True,
            )


def _display_base(path: Path, cwd: Path) -> Path:
    try:
        path.relative_to(cwd)
    except ValueError:
        return path.parent
    return cwd


def _find_fallback_files(root: Path, file_glob: str) -> list[Path]:
    """Collect candidate files for Python fallback search, skipping heavy directories."""
    if root.is_file():
        return [root]

    files: list[Path] = []
    is_recursive = "**" in file_glob or not file_glob or file_glob in {"*", "**/*"}
    if is_recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in _IGNORED_FALLBACK_DIRS and not d.startswith(".")
            ]
            dp = Path(dirpath)
            for fname in filenames:
                candidate = dp / fname
                if file_glob in {"*", "**/*", ""} or candidate.match(file_glob):
                    files.append(candidate)
    else:
        for p in root.glob(file_glob):
            if any(part in _IGNORED_FALLBACK_DIRS for part in p.parts):
                continue
            if p.is_file():
                files.append(p)

    return files


def _python_grep_dir(
    *,
    root: Path,
    file_glob: str,
    pattern: str,
    case_sensitive: bool,
    limit: int,
    display_base: Path,
) -> str:
    paths = _find_fallback_files(root, file_glob)
    return _python_grep_files(
        paths=paths,
        pattern=pattern,
        case_sensitive=case_sensitive,
        limit=limit,
        display_base=display_base,
    )


def _python_grep_files(
    *,
    paths,
    pattern: str,
    case_sensitive: bool,
    limit: int,
    display_base: Path,
) -> str:
    # Python fallback (kept for portability).
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return f"(invalid regex pattern '{pattern}': {exc})"
    collected: list[str] = []

    for path in paths:
        if len(collected) >= limit:
            break
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                collected.append(f"{_format_path(path, display_base)}:{line_no}:{line}")
                if len(collected) >= limit:
                    break

    if not collected:
        return "(no matches)"
    return "\n".join(collected)


def _resolve_path(base: Path, candidate: str | None) -> Path:
    path = Path(candidate or ".").expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _format_rg_result(matches: list[str], timeout_seconds: int) -> ToolResult:
    timed_out = bool(matches and matches[-1] == _timeout_marker(timeout_seconds))
    rendered = matches[:-1] if timed_out else matches
    output = "\n".join(rendered) if rendered else "(no matches)"
    if timed_out:
        output = (
            f"{output}\n\n[grep timed out after {timeout_seconds} seconds]"
            if output != "(no matches)"
            else f"[grep timed out after {timeout_seconds} seconds]"
        )
    return ToolResult(output=output, is_error=timed_out)


async def _rg_grep(
    *,
    root: Path,
    pattern: str,
    file_glob: str,
    case_sensitive: bool,
    limit: int,
    timeout_seconds: int,
) -> list[str] | None:
    """Return matches using ripgrep, or None if ripgrep is unavailable."""
    rg = _resolve_rg()
    if not rg:
        return None

    include_hidden = (root / ".git").exists() or (root / ".gitignore").exists()
    cmd: list[str] = [
        rg,
        "--no-heading",
        "--line-number",
        "--color",
        "never",
    ]
    if include_hidden:
        cmd.append("--hidden")
    if not case_sensitive:
        cmd.append("-i")
    if file_glob and file_glob not in {"**/*", "*", "**"}:
        cmd.extend(["--glob", file_glob])
    # `--` ensures patterns like `-foo` aren't parsed as flags.
    cmd.extend(["--", pattern, "."])

    from codeless.sandbox.session import get_docker_sandbox

    session = get_docker_sandbox()
    if session is not None and session.is_running:
        process = await session.exec_command(
            cmd,
            cwd=root,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(root),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,  # 8 MB per line — avoids LimitOverrunError on long lines
        )

    matches: list[str] = []
    try:
        await asyncio.wait_for(
            _collect_rg_matches(process, matches, limit=limit),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        matches.append(_timeout_marker(timeout_seconds))
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    finally:
        if len(matches) >= limit and process.returncode is None:
            await _terminate_process(process)
        elif process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                await _terminate_process(process)

    # rg exits 0 when matches are found, 1 when none are found.
    # Any other return code indicates an error; fall back to Python.
    if process.returncode in {0, 1, -15, -9}:
        return matches
    return None


async def _rg_grep_file(
    *,
    path: Path,
    pattern: str,
    case_sensitive: bool,
    limit: int,
    display_base: Path,
    timeout_seconds: int,
) -> list[str] | None:
    rg = _resolve_rg()
    if not rg:
        return None

    cmd: list[str] = [
        rg,
        "--no-heading",
        "--line-number",
        "--color",
        "never",
    ]
    if not case_sensitive:
        cmd.append("-i")
    cmd.extend(["--", pattern, path.name])

    from codeless.sandbox.session import get_docker_sandbox

    session = get_docker_sandbox()
    if session is not None and session.is_running:
        process = await session.exec_command(
            cmd,
            cwd=path.parent,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(path.parent),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,  # 8 MB per line — avoids LimitOverrunError on long lines
        )

    matches: list[str] = []
    try:
        await asyncio.wait_for(
            _collect_rg_file_matches(
                process,
                matches,
                limit=limit,
                path=path,
                display_base=display_base,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        matches.append(_timeout_marker(timeout_seconds))
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    finally:
        if len(matches) >= limit and process.returncode is None:
            await _terminate_process(process)
        elif process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                await _terminate_process(process)

    if process.returncode in {0, 1, -15, -9}:
        return matches
    return None


def _timeout_marker(timeout_seconds: int) -> str:
    return f"__CODELESS_GREP_TIMEOUT__:{timeout_seconds}"


async def _collect_rg_matches(
    process: asyncio.subprocess.Process,
    matches: list[str],
    *,
    limit: int,
) -> None:
    assert process.stdout is not None
    while len(matches) < limit:
        try:
            raw = await process.stdout.readline()
        except ValueError:
            # Line exceeded the stream buffer limit; skip it and continue.
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if line:
            matches.append(line)


async def _collect_rg_file_matches(
    process: asyncio.subprocess.Process,
    matches: list[str],
    *,
    limit: int,
    path: Path,
    display_base: Path,
) -> None:
    assert process.stdout is not None
    while len(matches) < limit:
        try:
            raw = await process.stdout.readline()
        except ValueError:
            # Line exceeded the stream buffer limit; skip it and continue.
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line:
            continue
        matches.append(f"{_format_path(path, display_base)}:{line}")


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
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
    return None


def _format_path(path: Path, display_base: Path) -> str:
    try:
        return str(path.relative_to(display_base))
    except ValueError:
        return str(path)
