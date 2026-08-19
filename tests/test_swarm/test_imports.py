"""Import regression tests for swarm startup."""

from __future__ import annotations

import importlib
import sys


def test_create_default_tool_registry_does_not_import_mailbox_eagerly():
    for module_name in list(sys.modules):
        if module_name == "codeless.tools" or module_name.startswith("codeless.tools."):
            sys.modules.pop(module_name, None)
        if module_name == "codeless.swarm" or module_name.startswith("codeless.swarm."):
            sys.modules.pop(module_name, None)

    tools = importlib.import_module("codeless.tools")
    registry = tools.create_default_tool_registry()

    assert registry.get("bash") is not None
    assert "codeless.swarm.mailbox" not in sys.modules
    assert "codeless.swarm.lockfile" not in sys.modules
