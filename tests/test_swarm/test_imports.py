"""Import regression tests for swarm startup."""

from __future__ import annotations

import importlib
import sys


def test_create_default_tool_registry_does_not_import_mailbox_eagerly():
    saved_modules = {}
    codeless_mod = sys.modules.get("codeless")
    saved_tools_attr = getattr(codeless_mod, "tools", None) if codeless_mod else None

    for module_name in list(sys.modules):
        if module_name == "codeless.tools" or module_name.startswith("codeless.tools."):
            saved_modules[module_name] = sys.modules.pop(module_name, None)
        if module_name == "codeless.swarm" or module_name.startswith("codeless.swarm."):
            saved_modules[module_name] = sys.modules.pop(module_name, None)

    try:
        tools = importlib.import_module("codeless.tools")
        registry = tools.create_default_tool_registry()

        assert registry.get("bash") is not None
        assert "codeless.swarm.mailbox" not in sys.modules
        assert "codeless.swarm.lockfile" not in sys.modules
    finally:
        for module_name in list(sys.modules):
            if (
                module_name == "codeless.tools"
                or module_name.startswith("codeless.tools.")
                or module_name == "codeless.swarm"
                or module_name.startswith("codeless.swarm.")
            ) and module_name not in saved_modules:
                sys.modules.pop(module_name, None)

        for module_name, mod in saved_modules.items():
            if mod is not None:
                sys.modules[module_name] = mod

        if codeless_mod is not None:
            if saved_tools_attr is not None:
                setattr(codeless_mod, "tools", saved_tools_attr)
            elif hasattr(codeless_mod, "tools"):
                delattr(codeless_mod, "tools")

        tools_mod = sys.modules.get("codeless.tools")
        if tools_mod is not None:
            for module_name, mod in saved_modules.items():
                if module_name.startswith("codeless.tools."):
                    subname = module_name.split("codeless.tools.")[1]
                    if "." not in subname:
                        setattr(tools_mod, subname, mod)
