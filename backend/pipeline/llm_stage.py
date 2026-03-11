"""
LLM Grammar Correction Stage.

Supports three backends (PIPELINE_LLM_BACKEND env var):
  - mock   : deterministic simulation
  - claude : Anthropic Claude API
  - openai : OpenAI GPT API

The mock backend supports full fault injection via MetricsRegistry overrides,
enabling the diagnostics engine to detect rate limits, latency spikes, etc.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.nlp_stage import NLPResult

logger = logging.getLogger(__name__)

_BACKEND = os.getenv("PIPELINE_LLM_BACKEND", "mock")

_HEALTHY_LATENCY_MEAN_MS = 800.0
_HEALTHY_TOKENS_PER_SECOND = 45.0

_CORRECTIONS = {
    "I would like to practice my English pronunciation.":
        "I would like to practice my English pronunciation. (Grammatically correct!)",
    "Can you help me understand this grammar rule?":
        "Can you help me understand this grammar rule? (Grammatically correct!)",
}


@dataclass
class LLMResult:
    corrected_text: str
    original_text: str
    corrections_made: list[str]
    latency_ms: float
    tokens_generated: int
    backend: str


class LLMStage:
    """LLM grammar correction with fault injection support."""

    def __init__(self) -> None:
        self.monitor = StageMonitor("llm")
        self.registry = MetricsRegistry.instance()
        self._recent_latencies: list[float] = []
        self._error_window: list[bool] = []  # True = 429 error

    def correct(
        self,
        nlp_result: NLPResult,
        session_id: str = "-",
        request_id: str = "-",
    ) -> LLMResult:
        with self.monitor.track("correct", session_id=session_id, request_id=request_id):
            if _BACKEND == "claude":
                return self._call_claude(nlp_result, session_id, request_id)
            elif _BACKEND == "openai":
                return self._call_openai(nlp_result, session_id, request_id)
            else:
                return self._mock_correct(nlp_result, session_id, request_id)

    # ------------------------------------------------------------------
    # Mock backend
    # ------------------------------------------------------------------

    def _mock_correct(
        self,
        nlp_result: NLPResult,
        session_id: str,
        request_id: str,
    ) -> LLMResult:
        snapshot = self.registry.snapshot()

        # Read injected latency multiplier and error rate from registry
        injected_p99 = snapshot.get("llm_api_latency_p99_ms", 0.0)
        injected_error_rate = snapshot.get("llm_error_rate_429", 0.0)

        # Simulate 429 rate limit errors
        if random.random() < injected_error_rate:
            self.registry.llm_api_error_total.labels(error_code="429").inc()
            self._track_error_rate(is_429=True)
            raise RuntimeError("LLM API rate limit exceeded (429)")

        # Simulate latency spike
        if injected_p99 > 0:
            latency_ms = injected_p99 * random.uniform(0.7, 1.1)
        else:
            latency_ms = _HEALTHY_LATENCY_MEAN_MS + random.gauss(0, 80)
        latency_ms = max(100.0, latency_ms)
        time.sleep(latency_ms / 1000)

        # Compute tokens/s
        tokens = max(10, int(nlp_result.token_count * 1.5))
        tps = tokens / (latency_ms / 1000) if latency_ms > 0 else _HEALTHY_TOKENS_PER_SECOND

        # Grammar correction
        corrected = _CORRECTIONS.get(
            nlp_result.original_text,
            nlp_result.original_text + " [Grammar checked — no issues found.]",
        )
        corrections = nlp_result.grammar_hints

        # Update metrics
        self._track_latency(latency_ms)
        self._track_error_rate(is_429=False)
        self.registry.set_metric("llm_tokens_per_second", tps)
        self.registry.llm_api_latency_ms.observe(latency_ms)

        result = LLMResult(
            corrected_text=corrected,
            original_text=nlp_result.original_text,
            corrections_made=corrections,
            latency_ms=latency_ms,
            tokens_generated=tokens,
            backend="mock",
        )
        logger.debug(
            "llm_corrected",
            extra={
                "latency_ms": round(latency_ms, 2),
                "tokens": tokens,
                "tps": round(tps, 1),
                "session_id": session_id,
            },
        )
        return result

    def _track_latency(self, latency_ms: float) -> None:
        self._recent_latencies.append(latency_ms)
        if len(self._recent_latencies) > 100:
            self._recent_latencies.pop(0)
        if len(self._recent_latencies) >= 10:
            sorted_vals = sorted(self._recent_latencies)
            p99_idx = int(len(sorted_vals) * 0.99)
            p99 = sorted_vals[min(p99_idx, len(sorted_vals) - 1)]
            self.registry.set_metric("llm_api_latency_p99_ms", p99)

    def _track_error_rate(self, is_429: bool) -> None:
        self._error_window.append(is_429)
        if len(self._error_window) > 50:
            self._error_window.pop(0)
        if self._error_window:
            rate = sum(self._error_window) / len(self._error_window)
            self.registry.set_metric("llm_error_rate_429", rate)

    # ------------------------------------------------------------------
    # Real backends (stubs)
    # ------------------------------------------------------------------

    def _call_claude(self, nlp_result: NLPResult, session_id: str, request_id: str) -> LLMResult:
        import anthropic
        client = anthropic.Anthropic()
        start = time.monotonic()
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Correct any grammar errors in the following English sentence. "
                        f"Return only the corrected sentence.\n\n{nlp_result.original_text}"
                    ),
                }
            ],
        )
        latency_ms = (time.monotonic() - start) * 1000
        corrected = message.content[0].text if message.content else nlp_result.original_text
        tokens = message.usage.output_tokens if message.usage else 0
        tps = tokens / (latency_ms / 1000) if latency_ms > 0 else 0
        self._track_latency(latency_ms)
        self.registry.set_metric("llm_tokens_per_second", tps)
        return LLMResult(
            corrected_text=corrected,
            original_text=nlp_result.original_text,
            corrections_made=[],
            latency_ms=latency_ms,
            tokens_generated=tokens,
            backend="claude",
        )

    def _call_openai(self, nlp_result: NLPResult, session_id: str, request_id: str) -> LLMResult:
        raise NotImplementedError("OpenAI backend not yet implemented")
