"""Shared fixtures: isolated Hermes home and Hermes-style plugin load."""

from __future__ import annotations

import sys
import types

import pytest

from helpers import FIXTURES, load_plugin


@pytest.fixture(scope="session")
def plugin():
    return load_plugin()


@pytest.fixture(autouse=True)
def hermes_home(tmp_path, monkeypatch):
    """Stub hermes_constants.get_hermes_home. HERMES_HOME is not the boundary."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: str(home)
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)
    return home


@pytest.fixture
def fixtures_dir():
    return FIXTURES
