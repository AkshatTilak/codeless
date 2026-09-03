"""Tests for ripgrep discovery and usability probing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codeless.utils.rg import _rg_is_usable, find_ripgrep


@pytest.fixture(autouse=True)
def _reset_windows_rg_cache(monkeypatch):
    """Reset the process-wide cache for Windows ripgrep resolution per test."""
    monkeypatch.setattr("codeless.utils.rg._windows_rg_cache", None)


class _FakeProbeProcess:
    """Minimal subprocess.Popen stand-in for _rg_is_usable tests."""

    def __init__(self, returncode: int, *, timeout_on_communicate: bool = False):
        self.returncode = returncode
        self.stdout = None
        self.stderr = None
        self.killed = False
        self.communicate_calls = 0
        self._timeout_on_communicate = timeout_on_communicate

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self._timeout_on_communicate:
            raise subprocess.TimeoutExpired(cmd="rg", timeout=timeout)
        return (b"ripgrep 14.1.0", b"")

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _isolate_windows_candidate_dirs(monkeypatch, tmp_path: Path) -> None:
    """Point candidate lookups at a nonexistent dir."""
    missing = str(tmp_path / "no-such-dir")
    monkeypatch.setenv("LOCALAPPDATA", missing)
    monkeypatch.setenv("ProgramFiles", missing)
    monkeypatch.setenv("ProgramFiles(x86)", missing)
    monkeypatch.setenv("USERPROFILE", missing)
    monkeypatch.setenv("ProgramData", missing)


def test_find_ripgrep_uses_path_when_available(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.rg.shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None
    )
    monkeypatch.setattr("codeless.utils.rg._rg_is_usable", lambda _: True)

    resolved = find_ripgrep(platform_name="linux")
    assert resolved == "/usr/bin/rg"


def test_find_ripgrep_windows_uses_path_first(monkeypatch, tmp_path: Path):
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "codeless.utils.rg.shutil.which",
        lambda name: "C:\\Tools\\rg.exe" if name == "rg" else None,
    )
    monkeypatch.setattr("codeless.utils.rg._rg_is_usable", lambda _: True)

    resolved = find_ripgrep(platform_name="windows")
    assert resolved == "C:\\Tools\\rg.exe"


def test_find_ripgrep_windows_finds_candidate_when_not_on_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("codeless.utils.rg.shutil.which", lambda _: None)
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)

    # Simulate Antigravity IDE installation
    app_data = tmp_path / "AppData" / "Local"
    ide_rg = (
        app_data
        / "Programs"
        / "Antigravity IDE"
        / "resources"
        / "app"
        / "node_modules"
        / "@vscode"
        / "ripgrep"
        / "bin"
        / "rg.exe"
    )
    ide_rg.parent.mkdir(parents=True)
    ide_rg.write_bytes(b"")

    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    monkeypatch.setattr("codeless.utils.rg._rg_is_usable", lambda path: str(ide_rg) in path)

    resolved = find_ripgrep(platform_name="windows")
    assert resolved == str(ide_rg)


def test_find_ripgrep_windows_caches_result(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("codeless.utils.rg.shutil.which", lambda _: None)
    _isolate_windows_candidate_dirs(monkeypatch, tmp_path)

    calls = 0

    def fake_probe(path: str) -> bool:
        nonlocal calls
        calls += 1
        return True

    user_profile = tmp_path / "Users" / "Test"
    cargo_rg = user_profile / ".cargo" / "bin" / "rg.exe"
    cargo_rg.parent.mkdir(parents=True)
    cargo_rg.write_bytes(b"")

    monkeypatch.setenv("USERPROFILE", str(user_profile))
    monkeypatch.setattr("codeless.utils.rg._rg_is_usable", fake_probe)

    first = find_ripgrep(platform_name="windows")
    assert first == str(cargo_rg)
    assert calls == 1

    # Second call should use cache
    second = find_ripgrep(platform_name="windows")
    assert second == str(cargo_rg)
    assert calls == 1


def test_rg_is_usable_returns_true_for_zero_exit(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.rg.subprocess.Popen",
        lambda *args, **kwargs: _FakeProbeProcess(0),
    )
    assert _rg_is_usable("rg") is True


def test_rg_is_usable_returns_false_for_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        "codeless.utils.rg.subprocess.Popen",
        lambda *args, **kwargs: _FakeProbeProcess(1),
    )
    assert _rg_is_usable("rg") is False


def test_rg_is_usable_returns_false_for_spawn_errors(monkeypatch):
    def raise_oserror(*args, **kwargs):
        raise OSError("missing binary")

    monkeypatch.setattr("codeless.utils.rg.subprocess.Popen", raise_oserror)
    assert _rg_is_usable("rg") is False


def test_rg_is_usable_timeout_kills_cleanly(monkeypatch):
    process = _FakeProbeProcess(None, timeout_on_communicate=True)
    monkeypatch.setattr("codeless.utils.rg.subprocess.Popen", lambda *a, **k: process)

    assert _rg_is_usable("rg") is False
    assert process.killed is True
    assert process.communicate_calls == 1
