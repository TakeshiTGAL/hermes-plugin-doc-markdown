"""Path guards for local file reads: resolve first, then deny."""

from __future__ import annotations

import os
from typing import Tuple

from .errors import PluginError

# Local tool allowlist (declared extras + core text/html/csv/json/md).
ALLOWED_EXTENSIONS = frozenset(
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

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MiB


def _home_unknown(reason: str) -> PluginError:
    """Fail closed. HERMES_HOME and ~/.hermes are not fallbacks."""
    return PluginError(
        "path_not_allowed",
        "Could not determine the Hermes home, so the file was not read.",
        "Use a Hermes build that provides hermes_constants.get_hermes_home, then retry.",
        details={"reason": reason},
    )


def hermes_home() -> str:
    """Return only hermes_constants.get_hermes_home(), as a path string.

    A str or a path object (pathlib.Path on current Hermes) is accepted.
    Import failure, a raised exception, a missing or renamed function, or a
    return that is not a path refuses the read. The HERMES_HOME environment
    variable is not consulted.
    """
    try:
        import hermes_constants
    except Exception as exc:
        raise _home_unknown(type(exc).__name__) from None
    getter = getattr(hermes_constants, "get_hermes_home", None)
    if not callable(getter):
        raise _home_unknown("get_hermes_home_missing")
    try:
        home = getter()
    except Exception as exc:
        raise _home_unknown(type(exc).__name__) from None
    if isinstance(home, os.PathLike):
        home = os.fspath(home)
    if not isinstance(home, str) or not home.strip():
        raise _home_unknown("unusable_home")
    return home


def resolve_readable_file(path: str, *, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> Tuple[str, int]:
    """Return (realpath, size) for a readable local file, or raise PluginError.

    Judgement is after resolve: hidden path segments, Hermes home, missing
    files, directories, and oversize files are refused. Symlink escapes that
    land under a denied location are refused because the check uses realpath.
    """
    if path is None or not str(path).strip():
        raise PluginError(
            "bad_path",
            "path is required.",
            "Call again with an absolute local file path, for example path='/home/me/docs/report.pdf'.",
        )
    raw = str(path).strip()
    # URL schemes are case-insensitive, so HTTPS://… is a URL, not a bad path.
    if raw.lower().startswith(("http://", "https://", "file://")):
        raise PluginError(
            "url_not_allowed",
            "The doc_convert tool reads local files only.",
            "Pass a local absolute path. This tool does not fetch http, https, or file URLs.",
        )
    expanded = os.path.expanduser(raw)
    if not os.path.isabs(expanded):
        raise PluginError(
            "bad_path",
            f"{raw!r} is not an absolute path.",
            "Pass the full path (for example /home/me/docs/report.pdf).",
        )
    try:
        real = os.path.realpath(expanded)
    except OSError as exc:
        raise PluginError(
            "bad_path",
            "Could not resolve the path.",
            "Check that the path exists and is readable, then retry.",
            details={"reason": type(exc).__name__},
        ) from None

    # Home and any component that starts with "." before exists/isfile, so a
    # missing path or a directory inside the home does not reveal that it exists.
    # realpath has already removed "." and ".." ; every remaining component
    # that starts with "." (".git", ".secrets", and so on) is refused.
    home = os.path.realpath(hermes_home())
    parts = [p for p in real.split(os.sep) if p not in ("", ".", "..")]
    hidden = any(part.startswith(".") for part in parts)
    under_home = real == home or real.startswith(home + os.sep)
    if hidden or under_home:
        if hidden and under_home:
            message = (
                "Any path component that starts with '.' is refused, "
                "and files inside the Hermes home folder are not read."
            )
        elif hidden:
            message = "Any path component that starts with '.' is refused."
        else:
            message = "Files inside the Hermes home folder are not read."
        raise PluginError(
            "path_not_allowed",
            message,
            "Copy the file to a normal folder (for example Documents) and pass that path.",
        )

    if not os.path.exists(real):
        raise PluginError(
            "file_not_found",
            "No file at the given path.",
            "Check the path; list the folder first if unsure.",
        )
    if not os.path.isfile(real):
        raise PluginError(
            "not_a_file",
            "The path is not a regular file.",
            "Pass a file path, not a directory.",
        )

    ext = os.path.splitext(real)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise PluginError(
            "unsupported_type",
            f"Extension {ext or '(none)'} is not in this plugin's supported set.",
            "Convert with a supported type (pdf, docx, pptx, xlsx, xls, html, htm, csv, json, txt, md) or export first.",
            details={"extension": ext},
        )

    try:
        size = os.path.getsize(real)
    except OSError:
        raise PluginError(
            "io_error",
            "Could not read the file size.",
            "Check permissions and retry.",
        ) from None
    if size > max_bytes:
        raise PluginError(
            "file_too_large",
            f"The file is {size} bytes (limit {max_bytes}).",
            "Split the file into smaller files, or raise max_file_bytes in the plugin config if appropriate. A .zip is not accepted.",
            details={"size_bytes": size, "limit_bytes": max_bytes},
        )
    return real, size
