"""pytest plugin (loaded with -p from pytest.ini); Hermes never imports this file.

The repo root is the plugin package itself: Hermes loads ``__init__.py``, which uses
relative imports. pytest 8 would import that ``__init__.py`` as a standalone module
(the directory name has hyphens) and fail, so collect the root as a plain directory.
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.hookimpl(tryfirst=True)
def pytest_collect_directory(path, parent):
    if Path(path).resolve() == _REPO_ROOT:
        return pytest.Dir.from_parent(parent, path=Path(path))
    return None
