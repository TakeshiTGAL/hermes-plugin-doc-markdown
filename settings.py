"""Plugin config readers (defaults match plugin.yaml config_schema)."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .paths import DEFAULT_MAX_FILE_BYTES

_get_config: Optional[Callable[[str, Any], Any]] = None

DEFAULT_MAX_OUTPUT_CHARS = 200_000
# Wall clock for one local conversion after the worker has loaded.
# The worker process group is stopped.
DEFAULT_CONVERT_TIMEOUT = 8
# A worker that never finishes importing converters is stopped at this many seconds.
DEFAULT_WORKER_LOAD_TIMEOUT = 60


def bind_config(getter: Optional[Callable[[str, Any], Any]]) -> None:
    """Called from register(ctx) so settings are read at call time."""
    global _get_config
    _get_config = getter


def _cfg(key: str, default: Any) -> Any:
    if _get_config is None:
        return default
    try:
        value = _get_config(key, default)
    except Exception:
        return default
    return default if value is None else value


def _as_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def max_file_bytes() -> int:
    return _as_int(_cfg("max_file_bytes", DEFAULT_MAX_FILE_BYTES), DEFAULT_MAX_FILE_BYTES)


def max_output_chars() -> int:
    return _as_int(_cfg("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS), DEFAULT_MAX_OUTPUT_CHARS)


def convert_timeout_seconds() -> int:
    return _as_int(
        _cfg("convert_timeout_seconds", DEFAULT_CONVERT_TIMEOUT),
        DEFAULT_CONVERT_TIMEOUT,
    )
