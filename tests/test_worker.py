"""The worker's own failures: load errors by kind, and the stdin body mode."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys

import pytest

from helpers import PLUGIN_DIR

_PLUGIN_FILES = (
    "__init__.py",
    "charset_util.py",
    "convert.py",
    "convert_worker.py",
    "errors.py",
    "paths.py",
    "schemas.py",
    "settings.py",
    "tools.py",
    "version.py",
)


def _worker_module():
    spec = importlib.util.spec_from_file_location(
        "doc_markdown_worker_under_test", PLUGIN_DIR / "convert_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_worker_from_copy(tmp_path, mutate):
    """Copy the plugin, break it, and read the worker's first stdout line."""
    root = tmp_path / "copy"
    root.mkdir()
    for name in _PLUGIN_FILES:
        shutil.copy(PLUGIN_DIR / name, root / name)
    mutate(root)
    proc = subprocess.run(
        [sys.executable, str(root / "convert_worker.py"), "--", str(tmp_path / "x.txt"), "100"],
        capture_output=True,
        timeout=120,
    )
    return json.loads(proc.stdout.splitlines()[0].decode("utf-8"))


@pytest.mark.parametrize(
    "exc,error_type,needle",
    [
        (ModuleNotFoundError("no markitdown", name="markitdown"), "dependency_missing",
         "markitdown is not installed"),
        (ModuleNotFoundError("no numpy", name="numpy.linalg"), "dependency_missing",
         "could not import numpy"),
        (ModuleNotFoundError("own", name="markitdown_docs_plugin.schemas"),
         "plugin_load_failed", "this plugin's own module markitdown_docs_plugin.schemas"),
        (ImportError("circular"), "dependency_missing", "could not import a module"),
        (SyntaxError("bad token"), "plugin_load_failed", "could not compile"),
        (FileNotFoundError("gone"), "plugin_load_failed", "could not read"),
        (PermissionError("denied"), "plugin_load_failed", "could not read"),
        (RuntimeError("plugin loader unavailable"), "plugin_load_failed",
         "could not load this plugin"),
    ],
)
def test_load_failure_text_depends_on_the_exception(exc, error_type, needle):
    payload = _worker_module()._load_failure(exc)
    assert payload["error_type"] == error_type, payload
    assert needle in payload["error"], payload
    assert payload["reason"] == type(exc).__name__
    assert payload["next_step"]
    assert payload["ok"] is False
    if error_type != "dependency_missing":
        assert "markitdown is not installed" not in payload["error"]


def test_every_load_failure_has_its_own_sentence():
    module = _worker_module()
    messages = {
        module._load_failure(exc)["error"]
        for exc in (
            ModuleNotFoundError("a", name="markitdown"),
            ModuleNotFoundError("b", name="numpy"),
            ModuleNotFoundError("c", name="markitdown_docs_plugin.tools"),
            SyntaxError("d"),
            FileNotFoundError("e"),
            RuntimeError("f"),
        )
    }
    assert len(messages) == 6, messages


def test_broken_plugin_file_is_not_reported_as_a_missing_package(tmp_path):
    def _break(root):
        (root / "__init__.py").write_text("def (\n", encoding="utf-8")

    payload = _run_worker_from_copy(tmp_path, _break)
    assert payload["error_type"] == "plugin_load_failed", payload
    assert "could not compile" in payload["error"]
    assert "markitdown is not installed" not in payload["error"]


def test_missing_plugin_file_is_not_reported_as_a_missing_package(tmp_path):
    def _remove(root):
        (root / "schemas.py").unlink()

    payload = _run_worker_from_copy(tmp_path, _remove)
    assert payload["error_type"] == "plugin_load_failed", payload
    assert "this plugin's own module" in payload["error"]
    assert "markitdown is not installed" not in payload["error"]


def test_worker_rejects_body_mode(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_DIR / "convert_worker.py"), "--bytes", ".html", ""],
        capture_output=True,
        input=b"<html><body><p>stdin body</p></body></html>",
        timeout=30,
    )
    payload = json.loads(proc.stdout.splitlines()[0].decode("utf-8"))
    assert payload["ok"] is False
    assert payload["error_type"] == "internal"
    assert "file path" in payload["error"]
