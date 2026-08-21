#!/usr/bin/env python3
"""Run ruff formatting and autofixes across the repository."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    paths = ["src", "tests", "scripts"]
    print("Running ruff check --fix...")
    res1 = subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", *paths])
    print("Running ruff format...")
    res2 = subprocess.run([sys.executable, "-m", "ruff", "format", *paths])
    if res1.returncode != 0:
        return res1.returncode
    return res2.returncode


if __name__ == "__main__":
    sys.exit(main())
