"""Minimal structured telemetry for model routing and agent operations.

Logs are JSON so they can be collected by the deployment's existing log/OTEL
pipeline without adding a hard dependency on a specific observability vendor.
Never log prompts, attachment contents, API keys, or model responses.
"""
import json
import logging
import time
from typing import Any

_logger = logging.getLogger("rdi.telemetry")


def emit(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "ts_ms": int(time.time() * 1000),
        **{k: v for k, v in fields.items() if v is not None},
    }
    _logger.info(json.dumps(payload, separators=(",", ":"), default=str))


class Timer:
    def __init__(self, event: str, **fields: Any):
        self.event = event
        self.fields = fields
        self.started = time.perf_counter()

    def finish(self, **extra: Any) -> None:
        emit(
            self.event,
            duration_ms=round((time.perf_counter() - self.started) * 1000, 2),
            **self.fields,
            **extra,
        )
