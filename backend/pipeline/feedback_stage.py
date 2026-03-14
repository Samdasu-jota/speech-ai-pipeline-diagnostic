"""
Feedback Generation Stage — mirrors the Self English Tutor app's FEEDBACK stage.

In the real app this calls GPT-4o with a structured JSON prompt and returns:
  - transcript_corrected, natural_version
  - mistakes (list), vocabulary_suggestions, slang_alternatives
  - pronunciation_notes, fluency_notes, overall_summary
  - scores: grammar (0-10), fluency (0-10), pronunciation (0-10), overall (0-10)

Supports three backends (PIPELINE_LLM_BACKEND env var):
  - mock   : deterministic simulation, no external calls
  - openai : OpenAI GPT-4o API (real app backend)
  - claude : Anthropic Claude API

The mock backend supports full fault injection via MetricsRegistry overrides,
enabling diagnostics to detect rate limits (FBK-002), latency spikes (FBK-001),
and poor feedback quality (FBK-003).
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.stt_stage import STTResult

logger = logging.getLogger(__name__)

_BACKEND = os.getenv("PIPELINE_LLM_BACKEND", "mock")

# Healthy baseline values (aligned with tutor app GPT-4o performance)
_HEALTHY_LATENCY_MEAN_MS = 1800.0     # GPT-4o averages ~1.8s for feedback
_HEALTHY_TOKENS_PER_SECOND = 40.0
_HEALTHY_GRAMMAR_SCORE = 7.5
_HEALTHY_FLUENCY_SCORE = 7.2
_HEALTHY_OVERALL_SCORE = 7.4


@dataclass
class FeedbackResult:
    transcript_corrected: str
    natural_version: str
    mistakes: list[dict]
    overall_summary: str
    grammar_score: float
    fluency_score: float
    pronunciation_score: float
    overall_score: float
    latency_ms: float
    tokens_generated: int
    backend: str
    original_text: str = ""


class FeedbackStage:
    """
    Feedback generation stage (GPT-4o) with fault injection support.

    Tracks rolling P99 latency and 429 error rate for diagnostic rules
    FBK-001 (latency spike) and FBK-002 (rate limit).
    """

    def __init__(self) -> None:
        self.monitor = StageMonitor("feedback")
        self.registry = MetricsRegistry.instance()
        self._recent_latencies: list[float] = []
        self._error_window: list[bool] = []  # True = 429 error

    def generate(
        self,
        stt_result: STTResult,
        session_id: str = "-",
        request_id: str = "-",
    ) -> FeedbackResult:
        with self.monitor.track("generate", session_id=session_id, request_id=request_id):
            if _BACKEND == "openai":
                return self._call_openai(stt_result, session_id, request_id)
            elif _BACKEND == "claude":
                return self._call_claude(stt_result, session_id, request_id)
            else:
                return self._mock_generate(stt_result, session_id, request_id)

    # ------------------------------------------------------------------
    # Mock backend
    # ------------------------------------------------------------------

    def _mock_generate(
        self,
        stt_result: STTResult,
        session_id: str,
        request_id: str,
    ) -> FeedbackResult:
        snap = self.registry.snapshot()

        # Read injected latency and 429 rate from registry
        injected_p99 = snap.get("feedback_api_latency_p99_ms", 0.0)
        injected_error_rate = snap.get("feedback_error_rate_429", 0.0)

        # Simulate 429 rate limit errors
        if random.random() < injected_error_rate:
            self.registry.feedback_api_error_total.labels(error_code="429").inc()
            self._track_error_rate(is_429=True)
            raise RuntimeError("Feedback API rate limit exceeded (429)")

        # Simulate latency
        if injected_p99 > 0:
            latency_ms = injected_p99 * random.uniform(0.7, 1.1)
        else:
            latency_ms = _HEALTHY_LATENCY_MEAN_MS + random.gauss(0, 150)
        latency_ms = max(300.0, latency_ms)
        time.sleep(latency_ms / 1000)

        tokens = max(80, int(stt_result.word_count * 4.5))
        tps = tokens / (latency_ms / 1000) if latency_ms > 0 else _HEALTHY_TOKENS_PER_SECOND

        # Quality scores — degrade when transcription confidence is low
        confidence_penalty = max(0.0, (_HEALTHY_OVERALL_SCORE - 3.0) * (0.88 - stt_result.confidence))
        # Also check for injected score degradation
        injected_grammar = snap.get("feedback_grammar_score", 0.0)
        injected_overall = snap.get("feedback_overall_score", 0.0)

        if injected_grammar > 0:
            grammar_score = max(0.0, injected_grammar + random.gauss(0, 0.2))
        else:
            grammar_score = max(0.5, _HEALTHY_GRAMMAR_SCORE - confidence_penalty + random.gauss(0, 0.3))

        fluency_score = max(0.5, _HEALTHY_FLUENCY_SCORE - confidence_penalty * 0.8 + random.gauss(0, 0.3))
        pronunciation_score = max(0.5, 7.0 - confidence_penalty * 0.6 + random.gauss(0, 0.3))

        if injected_overall > 0:
            overall_score = max(0.0, injected_overall + random.gauss(0, 0.2))
        else:
            overall_score = round(
                (grammar_score + fluency_score + pronunciation_score) / 3.0, 2
            )

        corrected = stt_result.cleaned_text + " [Grammar checked by GPT-4o.]"
        mistakes = []
        if stt_result.word_error_rate > 0.1:
            mistakes.append({
                "original": "buyed",
                "corrected": "bought",
                "explanation": "Irregular past tense",
                "category": "grammar",
            })

        # Push to Prometheus
        self._track_latency(latency_ms)
        self._track_error_rate(is_429=False)
        self.registry.set_metric("feedback_tokens_per_second", tps)
        self.registry.set_metric("feedback_grammar_score", round(grammar_score, 2))
        self.registry.set_metric("feedback_fluency_score", round(fluency_score, 2))
        self.registry.set_metric("feedback_overall_score", round(overall_score, 2))
        self.registry.feedback_api_latency_ms.observe(latency_ms)

        result = FeedbackResult(
            transcript_corrected=corrected,
            natural_version=stt_result.cleaned_text,
            mistakes=mistakes,
            overall_summary=f"Score: {overall_score:.1f}/10 — Keep practising!",
            grammar_score=round(grammar_score, 2),
            fluency_score=round(fluency_score, 2),
            pronunciation_score=round(pronunciation_score, 2),
            overall_score=round(overall_score, 2),
            latency_ms=latency_ms,
            tokens_generated=tokens,
            backend="mock",
            original_text=stt_result.transcript,
        )
        logger.debug(
            "feedback_generated",
            extra={
                "latency_ms": round(latency_ms, 2),
                "grammar_score": round(grammar_score, 2),
                "overall_score": round(overall_score, 2),
                "tokens": tokens,
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
            self.registry.set_metric("feedback_api_latency_p99_ms", p99)

    def _track_error_rate(self, is_429: bool) -> None:
        self._error_window.append(is_429)
        if len(self._error_window) > 50:
            self._error_window.pop(0)
        if self._error_window:
            rate = sum(self._error_window) / len(self._error_window)
            self.registry.set_metric("feedback_error_rate_429", rate)

    # ------------------------------------------------------------------
    # Real backends
    # ------------------------------------------------------------------

    def _call_openai(self, stt_result: STTResult, session_id: str, request_id: str) -> FeedbackResult:
        import openai
        client = openai.OpenAI()
        start = time.monotonic()
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an English language tutor. Analyse the student's spoken English "
                        "and return a JSON object with keys: transcript_corrected, natural_version, "
                        "mistakes (list), overall_summary, grammar_score (0-10), fluency_score (0-10), "
                        "pronunciation_score (0-10), overall_score (0-10)."
                    ),
                },
                {"role": "user", "content": stt_result.cleaned_text},
            ],
        )
        latency_ms = (time.monotonic() - start) * 1000
        import json
        payload = json.loads(response.choices[0].message.content or "{}")
        tokens = response.usage.completion_tokens if response.usage else 0
        tps = tokens / (latency_ms / 1000) if latency_ms > 0 else 0
        self._track_latency(latency_ms)
        self.registry.set_metric("feedback_tokens_per_second", tps)
        grammar = float(payload.get("grammar_score", 7.0))
        fluency = float(payload.get("fluency_score", 7.0))
        pronunciation = float(payload.get("pronunciation_score", 7.0))
        overall = float(payload.get("overall_score", 7.0))
        self.registry.set_metric("feedback_grammar_score", grammar)
        self.registry.set_metric("feedback_fluency_score", fluency)
        self.registry.set_metric("feedback_overall_score", overall)
        return FeedbackResult(
            transcript_corrected=payload.get("transcript_corrected", stt_result.cleaned_text),
            natural_version=payload.get("natural_version", stt_result.cleaned_text),
            mistakes=payload.get("mistakes", []),
            overall_summary=payload.get("overall_summary", ""),
            grammar_score=grammar,
            fluency_score=fluency,
            pronunciation_score=pronunciation,
            overall_score=overall,
            latency_ms=latency_ms,
            tokens_generated=tokens,
            backend="openai",
            original_text=stt_result.transcript,
        )

    def _call_claude(self, stt_result: STTResult, session_id: str, request_id: str) -> FeedbackResult:
        import anthropic
        client = anthropic.Anthropic()
        start = time.monotonic()
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Analyse this English learner's speech and provide structured feedback. "
                        f"Return JSON with: transcript_corrected, natural_version, mistakes (list), "
                        f"overall_summary, grammar_score (0-10), fluency_score (0-10), "
                        f"pronunciation_score (0-10), overall_score (0-10).\n\n{stt_result.cleaned_text}"
                    ),
                }
            ],
        )
        latency_ms = (time.monotonic() - start) * 1000
        import json
        raw = message.content[0].text if message.content else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        tokens = message.usage.output_tokens if message.usage else 0
        tps = tokens / (latency_ms / 1000) if latency_ms > 0 else 0
        self._track_latency(latency_ms)
        self.registry.set_metric("feedback_tokens_per_second", tps)
        grammar = float(payload.get("grammar_score", 7.0))
        fluency = float(payload.get("fluency_score", 7.0))
        overall = float(payload.get("overall_score", 7.0))
        self.registry.set_metric("feedback_grammar_score", grammar)
        self.registry.set_metric("feedback_overall_score", overall)
        return FeedbackResult(
            transcript_corrected=payload.get("transcript_corrected", stt_result.cleaned_text),
            natural_version=payload.get("natural_version", stt_result.cleaned_text),
            mistakes=payload.get("mistakes", []),
            overall_summary=payload.get("overall_summary", ""),
            grammar_score=grammar,
            fluency_score=fluency,
            pronunciation_score=float(payload.get("pronunciation_score", 7.0)),
            overall_score=overall,
            latency_ms=latency_ms,
            tokens_generated=tokens,
            backend="claude",
            original_text=stt_result.transcript,
        )
