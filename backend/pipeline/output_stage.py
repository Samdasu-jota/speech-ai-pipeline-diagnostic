"""
Output Delivery Stage — formats and delivers the final corrected response.

In a real tutoring application this would send the response over a WebSocket
to the student's frontend. Here it records output telemetry and returns the
final structured result for the pipeline runner.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.llm_stage import LLMResult

logger = logging.getLogger(__name__)

_HEALTHY_LATENCY_MEAN_MS = 8.0


@dataclass
class PipelineResponse:
    corrected_text: str
    original_transcript: str
    corrections: list[str]
    delivery_latency_ms: float
    session_id: str
    request_id: str


class OutputStage:
    """Formats and delivers the final pipeline response."""

    def __init__(self) -> None:
        self.monitor = StageMonitor("output")
        self.registry = MetricsRegistry.instance()

    def deliver(
        self,
        llm_result: LLMResult,
        session_id: str = "-",
        request_id: str = "-",
    ) -> PipelineResponse:
        with self.monitor.track("deliver", session_id=session_id, request_id=request_id):
            latency_ms = _HEALTHY_LATENCY_MEAN_MS + random.gauss(0, 2)
            latency_ms = max(1.0, latency_ms)
            time.sleep(latency_ms / 1000)

            response = PipelineResponse(
                corrected_text=llm_result.corrected_text,
                original_transcript=llm_result.original_text,
                corrections=llm_result.corrections_made,
                delivery_latency_ms=latency_ms,
                session_id=session_id,
                request_id=request_id,
            )
            logger.debug(
                "output_delivered",
                extra={
                    "delivery_latency_ms": round(latency_ms, 2),
                    "session_id": session_id,
                    "request_id": request_id,
                },
            )
            return response
