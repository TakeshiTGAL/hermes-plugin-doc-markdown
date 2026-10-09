"""Hermes v0.21.6+ hands dependency paths to children through PYTHONPATH; the worker must keep it."""
from helpers import load_plugin


def test_pythonpath_is_passed_to_the_worker():
    assert "PYTHONPATH" in load_plugin().convert._CHILD_ENV_ALLOW


def test_credentials_are_still_not_passed():
    allow = load_plugin().convert._CHILD_ENV_ALLOW
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HERMES_HOME", "GITHUB_TOKEN"):
        assert name not in allow
