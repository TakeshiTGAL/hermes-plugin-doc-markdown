"""Manifest declarations must match what register() wires."""

from __future__ import annotations

from pathlib import Path

import yaml

from helpers import PLUGIN_DIR


def test_manifest_matches_registrations(plugin):
    manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "doc-markdown"
    assert manifest["manifest_version"] == 2
    assert manifest["requires_hermes"] == ">=0.21.4"
    assert manifest["kind"] == "backend"
    assert manifest["provides_tools"] == ["doc_convert"]
    assert "provides_web_providers" not in manifest
    assert manifest["platforms"] == ["linux", "macos"]

    tools = []

    class Ctx:
        def get_config(self, key, default=None):
            return default

        def register_tool(self, name, toolset, schema, handler, **kwargs):
            assert toolset == "doc_markdown"
            assert schema["name"] == name
            assert callable(handler)
            tools.append(name)

        def register_web_search_provider(self, provider):
            raise AssertionError("v0.1 does not register a web provider")

    plugin.register(Ctx())
    assert tools == manifest["provides_tools"]


def test_tool_description_first_sentence_length(plugin):
    desc = plugin.schemas.CONVERT["description"]
    first = desc.split(". ")[0] + "."
    # Guidance: ~60 chars with what + arg example.
    assert "path=" in first
    assert 40 <= len(first) <= 80
    assert "built on Microsoft's MarkItDown" in desc
    assert "starts with '.'" in desc
    assert "dot-segment" not in desc
    assert "relative path" in desc
    assert "missing file" in desc
    assert "directory" in desc
    assert "only Hermes home" not in desc


def test_manifest_states_trademark_footnote():
    text = (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
    assert "built on Microsoft's MarkItDown" in text
    # The footnote names both marks and Microsoft as owner; the exact wording may change.
    assert "MarkItDown" in text and "trademarks of" in text and "Microsoft" in text
    assert "922746880" in text
    assert "Windows was not tested" in text
    assert "dot-segment" not in text
    assert "relative path" in text
    assert "missing file" in text
    assert "Only the Hermes home" not in text


def test_convert_timeout_matches_manifest():
    manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
    schema = manifest["config_schema"]["convert_timeout_seconds"]
    from helpers import load_plugin

    plugin = load_plugin()
    assert schema["default"] == plugin.settings.DEFAULT_CONVERT_TIMEOUT
    assert schema["default"] == 8
    readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    assert "convert_timeout_seconds" in readme
    assert "defaults to 8" in readme
    assert "既定は 8" in readme
    assert plugin.settings.DEFAULT_WORKER_LOAD_TIMEOUT == 60
    assert "60 seconds" in readme
    assert "60 秒" in readme
    assert "922746880" in readme
    assert "Windows was not tested" in readme
    assert "Windows は試していません" in readme
    assert "dot-segment" not in readme


def test_python_dependencies_have_upper_bound():
    manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
    deps = manifest["python_dependencies"]
    assert any(d.startswith("markitdown[") and "<0.2" in d for d in deps)
