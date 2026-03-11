"""
StageMonitor — context manager that wraps each pipeline stage.

Automatically records latency, catches exceptions, emits structured JSON logs,
and propagates correlation IDs (session_id, request_id) through every event.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Generator

from .metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)


class StageMonitor:
    """
    Wraps a pipeline stage operation with timing and error telemetry.

    Usage:
        monitor = StageMonitor("stt")
        with monitor.track("transcribe", session_id="sess-1", request_id="req-42"):
            result = call_stt_api(audio)
    """

    def __init__(self, stage_name: str) -> None:
        self.stage = stage_name
        self.registry = MetricsRegistry.instance()

    @contextmanager
    def track(
        self,
        operation: str = "process",
        session_id: str = "-",
        request_id: str = "-",
    ) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
            latency_ms = (time.monotonic() - start) * 1000
            self.registry.record_latency(self.stage, operation, latency_ms)
            logger.info(
                "stage_completed",
                extra={
                    "stage": self.stage,
                    "operation": operation,
                    "latency_ms": round(latency_ms, 2),
                    "session_id": session_id,
                    "request_id": request_id,
                },
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            error_type = type(exc).__name__
            self.registry.record_error(self.stage, error_type)
            logger.error(
                "stage_failed",
                extra={
                    "stage": self.stage,
                    "operation": operation,
                    "latency_ms": round(latency_ms, 2),
                    "error_type": error_type,
                    "error_msg": str(exc),
                    "session_id": session_id,
                    "request_id": request_id,
                },
                exc_info=True,
            )
            raise
