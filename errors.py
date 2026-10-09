"""Typed errors that become JSON tool results (never raised out of handlers)."""

from __future__ import annotations

from typing import Any, Dict, Optional


class PluginError(Exception):
    """Fail closed with a stable error_type and a next_step for the model."""

    def __init__(
        self,
        error_type: str,
        message: str,
        next_step: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.next_step = next_step
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "error": self.message,
            "error_type": self.error_type,
            "next_step": self.next_step,
        }
        for key, value in self.details.items():
            if key not in payload and value not in (None, ""):
                payload[key] = value
        return payload
