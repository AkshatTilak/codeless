"""Ripgrep binary discovery and probe helpers."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

from codeless.platforms import PlatformName, get_platform

# Process-wide cache for discovered ripgrep binary.
# None = not resolved yet, "" = resolved but no usable ripgrep found.
_windows_rg_cache: str | None = None

_RG_PROBE_TIMEOUT_SECONDS = 3.0


def find_ripgrep(*, platform_name: PlatformName | None = None) -> str | None:
    """Find a usable ripgrep executable.

    Checks PATH first; on Windows, falls back to common candidate directories
    (such as Antigravity IDE, VS Code, Cursor, Cargo, Scoop, Chocolatey).
    Results on Windows are cached process-wide.
    """
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "windows":
        global _windows_rg_cache
        if _windows_rg_cache is not None:
            return _windows_rg_cache or None
        resolved = _find_windows_rg_uncached()
        _windows_rg_cache = resolved or ""
        return resolved

    # On non-Windows platforms, PATH lookup is standard.
    which = shutil.which("rg")
    if which and _rg_is_usable(which):
        return which
    return None


def _find_windows_rg_uncached() -> str | None:
    """Scan candidate locations for ripgrep on Windows."""
    which = shutil.which("rg")
    if which and _rg_is_usable(which):
        return which

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    user_profile = os.environ.get("USERPROFILE", "")
    program_data = os.environ.get("ProgramData", "C:\\ProgramData")

    candidate_paths: list[Path] = []

    # Common package managers / user tools
    if user_profile:
        candidate_paths.append(Path(user_profile) / ".cargo" / "bin" / "rg.exe")
        candidate_paths.append(Path(user_profile) / "scoop" / "shims" / "rg.exe")
        candidate_paths.append(
            Path(user_profile) / "scoop" / "apps" / "ripgrep" / "current" / "rg.exe"
        )
    if program_data:
        candidate_paths.append(Path(program_data) / "chocolatey" / "bin" / "rg.exe")

    # IDE installations where ripgrep is bundled
    candidate_dirs: list[Path] = []
    if local_app_data:
        candidate_dirs.append(Path(local_app_data) / "Programs")
    candidate_dirs.append(Path(program_files))
    candidate_dirs.append(Path(program_files_x86))

    ide_names = ["Antigravity IDE", "Microsoft VS Code", "Cursor", "cursor", "Windsurf", "windsurf"]
    for cdir in candidate_dirs:
        if not cdir.exists():
            continue
        for ide in ide_names:
            ide_dir = cdir / ide
            if not ide_dir.exists():
                continue
            candidate_paths.extend(
                [
                    ide_dir / "bin" / "rg.exe",
                    ide_dir
                    / "resources"
                    / "app"
                    / "node_modules"
                    / "@vscode"
                    / "ripgrep"
                    / "bin"
                    / "rg.exe",
                    ide_dir
                    / "resources"
                    / "app"
                    / "node_modules.asar.unpacked"
                    / "@vscode"
                    / "ripgrep-universal"
                    / "bin"
                    / "win32-x64"
                    / "rg.exe",
                    ide_dir
                    / "resources"
                    / "app"
                    / "node_modules.asar.unpacked"
                    / "@vscode"
                    / "ripgrep"
                    / "bin"
                    / "win32-x64"
                    / "rg.exe",
                ]
            )
            # VS Code often has commit/version-hash subdirectories (e.g. 08d4889f9e)
            try:
                for sub in ide_dir.iterdir():
                    if sub.is_dir() and (sub / "resources").exists():
                        candidate_paths.extend(
                            [
                                sub
                                / "resources"
                                / "app"
                                / "node_modules.asar.unpacked"
                                / "@vscode"
                                / "ripgrep-universal"
                                / "bin"
                                / "win32-x64"
                                / "rg.exe",
                                sub
                                / "resources"
                                / "app"
                                / "node_modules.asar.unpacked"
                                / "@vscode"
                                / "ripgrep"
                                / "bin"
                                / "win32-x64"
                                / "rg.exe",
                            ]
                        )
            except OSError:
                pass

    for candidate in candidate_paths:
        if candidate.exists() and _rg_is_usable(str(candidate)):
            return str(candidate)

    return None


def _rg_is_usable(rg_path: str) -> bool:
    """Return True when the ripgrep binary runs cleanly without hanging."""
    try:
        process = subprocess.Popen(
            [rg_path, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, OSError):
        return False

    try:
        process.communicate(timeout=_RG_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        return False
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()

    return process.returncode == 0
