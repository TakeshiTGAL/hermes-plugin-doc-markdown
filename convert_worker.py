"""Worker process for one local-file conversion.

The parent starts this file with ``start_new_session`` and a minimal
environment. This process reports ready after the converters load, then
converts. On Linux it sets ``RLIMIT_AS`` before converting. The parent stops
the process group if loading, conversion time, or (on macOS) RSS exceeds its
limit. This process is not a sandbox.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


PACKAGE_NAME = "markitdown_docs_plugin"

_REINSTALL = (
    "Run `hermes plugins validate <plugin-dir> --install-deps` "
    "or reinstall the plugin so python_dependencies are prepared."
)
_REINSTALL_PLUGIN = (
    "Reinstall the plugin so all of its files come from one release, then retry."
)


def _load_failure(exc: BaseException) -> dict:
    """Say why the plugin would not load. Each kind of failure gets its own text."""
    name = type(exc).__name__
    error_type = "plugin_load_failed"
    next_step = "Reinstall the plugin, then retry."
    if isinstance(exc, ImportError):
        # ModuleNotFoundError names the module; "cannot import name" names the
        # package it was imported from. Either way, our own name means our files.
        missing = getattr(exc, "name", "") or ""
        root = missing.split(".")[0]
        if root == PACKAGE_NAME:
            message = f"The worker could not import this plugin's own module {missing}."
            next_step = _REINSTALL_PLUGIN
        elif root == "markitdown":
            message = "markitdown is not installed in this Hermes environment."
            error_type, next_step = "dependency_missing", _REINSTALL
        elif root:
            message = f"The worker could not import {root}, which this plugin needs."
            error_type, next_step = "dependency_missing", _REINSTALL
        else:
            message = f"The worker could not import a module this plugin needs ({name})."
            error_type, next_step = "dependency_missing", _REINSTALL
    elif isinstance(exc, SyntaxError):
        message = f"The worker could not compile this plugin's own files ({name})."
        next_step = _REINSTALL_PLUGIN
    elif isinstance(exc, OSError):
        message = f"The worker could not read this plugin's own files ({name})."
        next_step = "Check that the plugin directory is present and readable, then retry."
    else:
        message = f"The worker could not load this plugin ({name})."
    return {
        "ok": False,
        "error": message,
        "error_type": error_type,
        "next_step": next_step,
        "reason": name,
    }


def _load_plugin():
    root = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("plugin loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _bad_start(message: str) -> int:
    _emit(
        {
            "ok": False,
            "error": message,
            "error_type": "internal",
            "next_step": "Retry the conversion.",
        }
    )
    return 2


def main() -> int:
    argv = sys.argv[1:]
    limit_bytes = 0
    if len(argv) == 3 and argv[0] == "--":
        target = argv[1]
        try:
            limit_bytes = int(argv[2])
        except ValueError:
            return _bad_start("The conversion worker was started without a size limit.")
    else:
        return _bad_start("The conversion worker was started without a file path.")
    subject = "file"
    try:
        plugin = _load_plugin()
    except Exception as exc:  # noqa: BLE001 — typed JSON on stdout, no file bytes
        _emit(_load_failure(exc))
        return 0

    def _failed(exc: BaseException) -> dict:
        return {
            "ok": False,
            "error": (
                f"MarkItDown could not convert this {subject} ({type(exc).__name__})."
            ),
            "error_type": "conversion_failed",
            "next_step": plugin.convert.CONVERT_NEXT_STEP[subject],
        }

    try:
        plugin.convert.warm_converters()
    except plugin.errors.PluginError as exc:
        payload = exc.to_dict()
        payload["ok"] = False
        _emit(payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit(_failed(exc))
        return 0
    _emit({"ready": True})
    try:
        plugin.convert.apply_linux_address_limit()
        text = plugin.convert.convert_file_with_one_converter(target, limit_bytes)
    except MemoryError:
        limit = plugin.convert.CONVERT_MEMORY_LIMIT_BYTES
        _emit(
            {
                "ok": False,
                "error": (
                    f"Conversion hit the memory limit of {limit} bytes "
                    "and the worker process was stopped."
                ),
                "error_type": "conversion_memory",
                "next_step": (
                    "Retry with a smaller file. This memory limit is fixed "
                    "and is not raised by max_file_bytes."
                ),
                "memory_limit_bytes": limit,
            }
        )
        return 0
    except plugin.errors.PluginError as exc:
        payload = exc.to_dict()
        payload["ok"] = False
        _emit(payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit(_failed(exc))
        return 0
    _emit({"ok": True, "text": text})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
