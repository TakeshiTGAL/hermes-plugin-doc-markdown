"""Tool handlers: always return JSON strings; never raise out of handlers."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from . import convert, settings
from .errors import PluginError

logger = logging.getLogger(__name__)


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _as_handler(fetch: Callable[[dict], dict]) -> Callable:
    def handler(args: Optional[dict] = None, **kwargs: Any) -> str:
        try:
            return _dump(fetch(dict(args or {})))
        except PluginError as error:
            return _dump(error.to_dict())
        except Exception as error:  # never crash the agent loop
            logger.exception("doc-markdown tool failed")
            return _dump(
                {
                    "error": f"Unexpected error: {type(error).__name__}",
                    "error_type": "internal",
                    "next_step": (
                        "Retry once. If it repeats, tell the user conversion failed "
                        "without pasting file contents."
                    ),
                }
            )

    return handler


def make_handlers() -> Dict[str, Callable]:
    def convert_file(args: dict) -> dict:
        max_chars = args.get("max_chars")
        if max_chars is not None:
            if isinstance(max_chars, bool) or not isinstance(max_chars, int):
                raise PluginError(
                    "bad_argument",
                    "max_chars must be an integer.",
                    "Retry with an integer max_chars or omit it.",
                )
        # File size always uses the plugin config. No tool argument can raise it.
        return convert.convert_local_file(
            args.get("path"),
            max_chars=max_chars,
            max_bytes=settings.max_file_bytes(),
        )

    return {"doc_convert": _as_handler(convert_file)}


HANDLERS = make_handlers()
