"""Denial paths: typed JSON errors, no exception crash."""

from __future__ import annotations

import json
import sys
import types

import pytest

from helpers import call


def test_allowed_extensions_exact(plugin):
    assert plugin.paths.ALLOWED_EXTENSIONS == frozenset(
        {
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            ".xls",
            ".html",
            ".htm",
            ".csv",
            ".json",
            ".txt",
            ".md",
        }
    )


def test_hidden_path_denied(plugin, tmp_path):
    hidden_dir = tmp_path / ".secrets"
    hidden_dir.mkdir()
    target = hidden_dir / "notes.txt"
    target.write_text("secret-should-not-leak\n", encoding="utf-8")
    out = call(plugin, "doc_convert", {"path": str(target)})
    assert out.get("error_type") == "path_not_allowed"
    assert "starts with '.'" in out["error"]
    assert "dot-segment" not in out["error"]
    assert "next_step" in out
    assert "secret-should-not-leak" not in out["error"]


def test_hermes_home_denied(plugin, hermes_home):
    target = hermes_home / "notes.txt"
    target.write_text("inside-home\n", encoding="utf-8")
    out = call(plugin, "doc_convert", {"path": str(target)})
    assert out.get("error_type") == "path_not_allowed"
    assert "next_step" in out
    assert "inside-home" not in out["error"]


def test_symlink_escape_to_hidden_denied(plugin, tmp_path):
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    real = hidden_dir / "payload.txt"
    real.write_text("payload-body\n", encoding="utf-8")
    link = tmp_path / "visible.txt"
    link.symlink_to(real)
    out = call(plugin, "doc_convert", {"path": str(link)})
    assert out.get("error_type") == "path_not_allowed"
    assert "payload-body" not in out["error"]


def test_oversized_denied(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hh"))
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 1000)
    # Force a tiny limit through settings by binding config.
    plugin.settings.bind_config(lambda key, default=None: 100 if key == "max_file_bytes" else default)
    try:
        out = call(plugin, "doc_convert", {"path": str(big)})
    finally:
        plugin.settings.bind_config(None)
    assert out.get("error_type") == "file_too_large"
    assert "next_step" in out


def test_corrupt_and_unsupported(plugin, tmp_path):
    # Built at runtime (not checked in) so the catalog security scan stays clean.
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"%PDF-1.4\n%\x00\x01not-a-real-pdf\xff\xfe")
    corrupt = call(plugin, "doc_convert", {"path": str(corrupt_path)})
    assert corrupt.get("error_type") in {"unsupported_type", "conversion_failed", "empty_output"}
    assert "next_step" in corrupt

    odd = tmp_path / "file.unknownext"
    odd.write_text("hello", encoding="utf-8")
    unsupported = call(plugin, "doc_convert", {"path": str(odd)})
    assert unsupported.get("error_type") == "unsupported_type"
    assert "next_step" in unsupported


def test_relative_and_url_denied(plugin, fixtures_dir):
    rel = call(plugin, "doc_convert", {"path": "report.pdf"})
    assert rel.get("error_type") == "bad_path"
    url = call(plugin, "doc_convert", {"path": "https://example.com/"})
    assert url.get("error_type") == "url_not_allowed"
    assert "next_step" in url


@pytest.mark.parametrize(
    "url",
    [
        "HTTPS://example.com/a.pdf",
        "HttPs://example.com/a.pdf",
        "HTTP://example.com/a.pdf",
        "FILE:///tmp/CASE.TXT",
        "File:///tmp/CASE.TXT",
    ],
)
def test_url_scheme_match_ignores_case(plugin, url):
    """A URL scheme is case-insensitive, so these are not local paths."""
    out = call(plugin, "doc_convert", {"path": url})
    assert out.get("error_type") == "url_not_allowed", out
    assert out.get("ok") is not True
    assert "next_step" in out


def test_missing_file(plugin, tmp_path):
    out = call(plugin, "doc_convert", {"path": str(tmp_path / "missing.pdf")})
    assert out.get("error_type") == "file_not_found"
    assert "next_step" in out


def test_missing_or_directory_under_home_hides_existence(plugin, hermes_home):
    missing = call(plugin, "doc_convert", {"path": str(hermes_home / "missing.txt")})
    assert missing.get("error_type") == "path_not_allowed"
    folder = hermes_home / "docs"
    folder.mkdir()
    directory = call(plugin, "doc_convert", {"path": str(folder)})
    assert directory.get("error_type") == "path_not_allowed"
    hidden = call(plugin, "doc_convert", {"path": str(hermes_home.parent / ".gone" / "missing.txt")})
    assert hidden.get("error_type") == "path_not_allowed"


def test_path_object_home_allows_outside_file(plugin, tmp_path, monkeypatch):
    from pathlib import Path

    stub = tmp_path / "stub-home"
    stub.mkdir()
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: Path(stub)
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)
    outside = tmp_path / "outside.txt"
    outside.write_text("path-home-ok\n", encoding="utf-8")
    allowed = call(plugin, "doc_convert", {"path": str(outside)})
    assert allowed.get("ok") is True, allowed
    assert "path-home-ok" in allowed["markdown"]
    inside = stub / "secret.txt"
    inside.write_text("path-home-secret\n", encoding="utf-8")
    denied = call(plugin, "doc_convert", {"path": str(inside)})
    assert denied["error_type"] == "path_not_allowed"
    assert "could not determine" not in denied["error"].lower()
    assert "path-home-secret" not in json.dumps(denied)
    missing = call(plugin, "doc_convert", {"path": str(stub / "nope.txt")})
    assert missing["error_type"] == "path_not_allowed"


def test_directory_is_not_a_file(plugin, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    out = call(plugin, "doc_convert", {"path": str(folder)})
    assert out.get("error_type") == "not_a_file"


def test_case_txt_and_file_scheme(plugin, tmp_path):
    target = tmp_path / "CASE.TXT"
    target.write_text("case-ok\n", encoding="utf-8")
    out = call(plugin, "doc_convert", {"path": str(target)})
    assert out.get("ok") is True, out
    assert "case-ok" in out["markdown"]
    file_url = call(plugin, "doc_convert", {"path": "file:///tmp/CASE.TXT"})
    assert file_url.get("error_type") == "url_not_allowed"


def test_symlink_inside_home_to_outside_is_readable(plugin, hermes_home, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-body\n", encoding="utf-8")
    link = hermes_home / "link.txt"
    link.symlink_to(outside)
    out = call(plugin, "doc_convert", {"path": str(link)})
    assert out.get("ok") is True, out
    assert "outside-body" in out["markdown"]


def test_symlink_outside_into_home_denied(plugin, hermes_home, tmp_path):
    inside = hermes_home / "secret.txt"
    inside.write_text("inside-secret\n", encoding="utf-8")
    link = tmp_path / "looks-outside.txt"
    link.symlink_to(inside)
    out = call(plugin, "doc_convert", {"path": str(link)})
    assert out.get("error_type") == "path_not_allowed"
    assert "inside-secret" not in json.dumps(out)


def test_env_home_is_not_the_boundary(plugin, tmp_path, monkeypatch):
    env_home = tmp_path / "env-home"
    env_home.mkdir()
    stub_home = tmp_path / "stub-home"
    stub_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: str(stub_home)
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)
    inside_env = env_home / "notes.txt"
    inside_env.write_text("env-home-text\n", encoding="utf-8")
    allowed = call(plugin, "doc_convert", {"path": str(inside_env)})
    assert allowed.get("ok") is True, allowed
    assert "env-home-text" in allowed["markdown"]
    inside_stub = stub_home / "notes.txt"
    inside_stub.write_text("stub-home-text\n", encoding="utf-8")
    denied = call(plugin, "doc_convert", {"path": str(inside_stub)})
    assert denied["error_type"] == "path_not_allowed"
    assert "stub-home-text" not in json.dumps(denied)


def _outside_file(tmp_path):
    path = tmp_path / "outside.txt"
    path.write_text("outside-visible\n", encoding="utf-8")
    return path


def _assert_home_unknown(out):
    assert out["error_type"] == "path_not_allowed"
    assert "could not determine" in out["error"].lower()
    assert "outside-visible" not in json.dumps(out)
    assert "next_step" in out


def test_home_import_failure_refuses_outside_file(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unused-env-home"))
    monkeypatch.setitem(sys.modules, "hermes_constants", None)
    out = call(plugin, "doc_convert", {"path": str(_outside_file(tmp_path))})
    _assert_home_unknown(out)


def test_home_exception_refuses_outside_file(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unused-env-home"))
    mod = types.ModuleType("hermes_constants")

    def boom():
        raise RuntimeError("home unavailable")

    mod.get_hermes_home = boom
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)
    out = call(plugin, "doc_convert", {"path": str(_outside_file(tmp_path))})
    _assert_home_unknown(out)


def test_home_renamed_refuses_outside_file(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "unused-env-home"))
    mod = types.ModuleType("hermes_constants")
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)
    out = call(plugin, "doc_convert", {"path": str(_outside_file(tmp_path))})
    _assert_home_unknown(out)


def test_removed_extensions_unsupported(plugin, tmp_path):
    """Former allowlist types now return unsupported_type."""
    removed = [
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".tif",
        ".tiff",
        ".bmp",
        ".rtf",
        ".xml",
        ".tsv",
        ".markdown",
        ".epub",
        ".zip",
    ]
    for ext in removed:
        path = tmp_path / f"sample{ext}"
        path.write_bytes(b"not-a-real-payload")
        out = call(plugin, "doc_convert", {"path": str(path)})
        assert out.get("error_type") == "unsupported_type", (ext, out)
        assert "next_step" in out
