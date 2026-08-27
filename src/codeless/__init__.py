"""Codeless: Autonomous agent execution harness for Agent Buildable Base (ABB)."""

import warnings

# Suppress benign environment version mismatch warnings from upstream requests/urllib3
warnings.filterwarnings(
    "ignore", message="urllib3 .* or chardet .* doesn't match a supported version!"
)

__version__ = "1.2.0"
