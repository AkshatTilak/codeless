"""Installer regressions for Windows command aliases."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


def test_pyproject_exposes_codeless_console_script():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["codeless"] == "codeless.cli:app"
    assert scripts["clh"] == "codeless.cli:app"


def test_powershell_installer_references():
    script = Path("scripts/install.ps1").read_text(encoding="utf-8")
    assert "codeless" in script.lower()

