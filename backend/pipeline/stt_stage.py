"""
Speech-to-Text Stage.

Supports three backends (controlled by PIPELINE_STT_BACKEND env var):
  - mock    : deterministic simulation, no external calls
  - whisper : OpenAI Whisper API
  - deepgram: Deepgram streaming API

The mock backend is the default — it reads injected fault values from the
MetricsRegistry so the diagnostics engine can be exercised without any API keys.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field

from monitoring.metrics_registry import MetricsRegistry
from monitoring.stage_monitor import StageMonitor
from pipeline.audio_stage import AudioFrame

logger = logging.getLogger(__name__)

_BACKEND = os.getenv("PIPELINE_STT_BACKEND", "mock")

# Healthy baseline values
_HEALTHY_WER = 0.06
_HEALTHY_CONFIDENCE = 0.88
_HEALTHY_LATENCY_MEAN_MS = 320.0

_SAMPLE_TRANSCRIPTS = [
    "The quick brown fox jumps over the lazy dog.",
    "Can you help me understand this grammar rule?",
    "I would like to practice my English pronunciation.",
    "Please correct my sentence if it is wrong.",
    "How do I use the present perfect tense correctly?",
]


@dataclass
class STTResult:
    transcript: str
    confidence: float
    word_error_rate: float
    latency_ms: float
    backend: str
    words: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.words = self.transcript.split()


class STTStage:
    """Speech-to-text processing with automatic fault injection support."""

    def __init__(self) -> None:
        self.monitor = StageMonitor("stt")
        self.registry = MetricsRegistry.instance()

    def transcribe(
        self,
        frame: AudioFrame,
        session_id: str = "-",
        request_id: str = "-",
    ) -> STTResult:
        with self.monitor.track("transcribe", session_id=session_id, request_id=request_id):
            if _BACKEND == "whisper":
                return self._call_whisper(frame, session_id, request_id)
            elif _BACKEND == "deepgram":
                return self._call_deepgram(frame, session_id, request_id)
            else:
                return self._mock_transcribe(frame, session_id, request_id)

    # ------------------------------------------------------------------
    # Mock backend
    # ------------------------------------------------------------------

    def _mock_transcribe(
        self,
        frame: AudioFrame,
        session_id: str,
        request_id: str,
    ) -> STTResult:
        # Read injected WER from registry (set by FailureSimulator)
        injected_wer = self.registry.snapshot().get("stt_word_error_rate", _HEALTHY_WER)

        # Simulate latency (higher WER → worse conditions → more jitter)
        noise_factor = max(1.0, (_HEALTHY_WER / max(injected_wer, 0.001)) ** -0.5)
        latency_ms = _HEALTHY_LATENCY_MEAN_MS * noise_factor + random.gauss(0, 30)
        latency_ms = max(50.0, latency_ms)
        time.sleep(latency_ms / 1000)

        # Confidence inversely correlated with WER
        confidence = max(0.1, _HEALTHY_CONFIDENCE - (injected_wer * 3.0) + random.gauss(0, 0.02))

        # Pick transcript; if WER is very high, mangle some words
        transcript = random.choice(_SAMPLE_TRANSCRIPTS)
        if injected_wer > 0.25:
            words = transcript.split()
            n_corrupt = int(len(words) * injected_wer)
            for i in random.sample(range(len(words)), min(n_corrupt, len(words))):
                words[i] = "???"
            transcript = " ".join(words)

        wer = injected_wer + random.gauss(0, 0.01)
        wer = max(0.0, min(1.0, wer))

        # Push to Prometheus
        self.registry.set_metric("stt_word_error_rate", wer)
        self.registry.stt_confidence_score.observe(confidence)
        self.registry.stt_api_latency_ms.observe(latency_ms)
        if not transcript.strip():
            self.registry.stt_empty_transcript_total.inc()

        result = STTResult(
            transcript=transcript,
            confidence=confidence,
            word_error_rate=wer,
            latency_ms=latency_ms,
            backend="mock",
        )
        logger.debug(
            "stt_transcribed",
            extra={
                "wer": round(wer, 3),
                "confidence": round(confidence, 3),
                "latency_ms": round(latency_ms, 2),
                "session_id": session_id,
                "backend": "mock",
            },
        )
        return result

    # ------------------------------------------------------------------
    # Real backends (stubs — implement when API keys are available)
    # ------------------------------------------------------------------

    def _call_whisper(self, frame: AudioFrame, session_id: str, request_id: str) -> STTResult:
        raise NotImplementedError("Whisper backend not yet implemented")

    def _call_deepgram(self, frame: AudioFrame, session_id: str, request_id: str) -> STTResult:
        raise NotImplementedError("Deepgram backend not yet implemented")
