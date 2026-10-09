"""Load the repo root as a package, the way Hermes imports a directory plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PACKAGE = "markitdown_docs_plugin"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def load_plugin():
    return sys.modules.get(PACKAGE) or _load_plugin()


def call(plugin, tool: str, args: dict):
    return json.loads(plugin.tools.HANDLERS[tool](args))
