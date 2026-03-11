"""
Language Processing Stage.

Performs lightweight NLP analysis on the STT transcript:
- Token count
- Basic grammar check (heuristic)
- Prepare context for LLM stage

This stage is kept intentionally simple; its telemetry still flows through
the monitoring layer so it appears on dashboards.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.stt_stage import STTResult

logger = logging.getLogger(__name__)

_HEALTHY_LATENCY_MEAN_MS = 25.0


@dataclass
class NLPResult:
    original_text: str
    token_count: int
    has_grammar_errors: bool
    grammar_hints: list[str]
    latency_ms: float


class NLPStage:
    """Language processing stage — tokenisation and grammar pre-check."""

    def __init__(self) -> None:
        self.monitor = StageMonitor("nlp")
        self.registry = MetricsRegistry.instance()

    def process(
        self,
        stt_result: STTResult,
        session_id: str = "-",
        request_id: str = "-",
    ) -> NLPResult:
        with self.monitor.track("process", session_id=session_id, request_id=request_id):
            latency_ms = _HEALTHY_LATENCY_MEAN_MS + random.gauss(0, 5)
            latency_ms = max(5.0, latency_ms)
            time.sleep(latency_ms / 1000)

            text = stt_result.transcript
            tokens = text.split()
            token_count = len(tokens)

            # Simple heuristic grammar hints
            hints: list[str] = []
            if not text.strip().endswith("."):
                hints.append("Sentence may be missing a period.")
            if text and not text[0].isupper():
                hints.append("Sentence should begin with a capital letter.")

            has_errors = len(hints) > 0

            # Push metrics
            self.registry.nlp_processing_latency_ms.observe(latency_ms)
            self.registry.nlp_token_count.observe(token_count)

            result = NLPResult(
                original_text=text,
                token_count=token_count,
                has_grammar_errors=has_errors,
                grammar_hints=hints,
                latency_ms=latency_ms,
            )
            logger.debug(
                "nlp_processed",
                extra={
                    "token_count": token_count,
                    "has_errors": has_errors,
                    "latency_ms": round(latency_ms, 2),
                    "session_id": session_id,
                },
            )
            return result
