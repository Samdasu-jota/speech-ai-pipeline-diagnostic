"""
Prometheus metrics registry — singleton that owns all instruments.

All pipeline stages and the diagnostics engine read/write metrics through here,
ensuring a single consistent namespace and preventing duplicate registration errors.

Pipeline stages (aligned with Self English Tutor app):
  1. Preprocessing  — audio capture, VAD, noise reduction
  2. Transcription  — OpenAI Whisper API
  3. Storage/Queue  — S3 upload + Celery queue
  4. Feedback       — GPT-4o structured feedback generation
"""

from __future__ import annotations

import threading
from typing import Dict

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Histogram buckets tuned for millisecond latency measurements
_LATENCY_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 10000)


class MetricsRegistry:
    """
    Central Prometheus metrics registry.

    Usage:
        registry = MetricsRegistry.instance()
        registry.record_latency("stt", "transcribe", 320.5)
        snapshot = registry.snapshot()
    """

    _instance: MetricsRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._registry = CollectorRegistry()
        self._current_values: Dict[str, float] = {}
        self._cv_lock = threading.Lock()
        self._setup_instruments()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "MetricsRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Instrument setup
    # ------------------------------------------------------------------

    def _setup_instruments(self) -> None:
        r = self._registry

        # ── Preprocessing Stage ───────────────────────────────────────
        self.audio_snr_db = Gauge(
            "audio_snr_db", "Signal-to-noise ratio in dB", registry=r
        )
        self.audio_noise_floor_dbfs = Gauge(
            "audio_noise_floor_dbfs", "Noise floor in dBFS", registry=r
        )
        self.audio_speech_ratio = Gauge(
            "audio_speech_ratio",
            "Fraction of audio containing speech (VAD output, 0-1)",
            registry=r,
        )
        self.audio_buffer_overflow_total = Counter(
            "audio_buffer_overflow_total", "Audio buffer overflow events", registry=r
        )
        self.audio_capture_latency_ms = Histogram(
            "audio_capture_latency_ms",
            "Audio capture + preprocessing latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )

        # ── Transcription Stage (Whisper) ─────────────────────────────
        self.stt_word_error_rate = Gauge(
            "stt_word_error_rate", "Current word error rate (0-1)", registry=r
        )
        self.stt_confidence_score = Gauge(
            "stt_confidence_score",
            "Current Whisper avg confidence score (0-1)",
            registry=r,
        )
        self.stt_confidence_hist = Histogram(
            "stt_confidence_hist",
            "Whisper confidence score distribution per utterance",
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=r,
        )
        self.stt_word_count = Gauge(
            "stt_word_count", "Word count of latest transcript", registry=r
        )
        self.stt_api_latency_ms = Histogram(
            "stt_api_latency_ms",
            "STT API call latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.stt_api_error_total = Counter(
            "stt_api_error_total",
            "STT API errors",
            ["error_type"],
            registry=r,
        )
        self.stt_empty_transcript_total = Counter(
            "stt_empty_transcript_total", "Empty STT transcripts returned", registry=r
        )

        # ── Storage / Queue Stage (S3 + Celery) ──────────────────────
        self.storage_upload_latency_ms = Gauge(
            "storage_upload_latency_ms", "S3 upload latency in ms", registry=r
        )
        self.celery_queue_depth = Gauge(
            "celery_queue_depth", "Pending Celery task queue depth", registry=r
        )

        # ── Feedback Stage (GPT-4o) ───────────────────────────────────
        self.feedback_api_latency_ms = Histogram(
            "feedback_api_latency_ms",
            "Feedback API (GPT-4o) latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.feedback_tokens_per_second = Gauge(
            "feedback_tokens_per_second",
            "Feedback API throughput in tokens/s",
            registry=r,
        )
        self.feedback_api_error_total = Counter(
            "feedback_api_error_total",
            "Feedback API errors",
            ["error_code"],
            registry=r,
        )
        self.feedback_error_rate_429 = Gauge(
            "feedback_error_rate_429",
            "Feedback API (GPT-4o) 429 rate-limit error rate (fraction)",
            registry=r,
        )
        self.feedback_grammar_score = Gauge(
            "feedback_grammar_score", "GPT-4o grammar score (0-10)", registry=r
        )
        self.feedback_fluency_score = Gauge(
            "feedback_fluency_score", "GPT-4o fluency score (0-10)", registry=r
        )
        self.feedback_overall_score = Gauge(
            "feedback_overall_score", "GPT-4o overall score (0-10)", registry=r
        )

        # ── System ───────────────────────────────────────────────────
        self.system_cpu_percent = Gauge(
            "system_cpu_percent", "System CPU utilisation %", registry=r
        )
        self.system_memory_percent = Gauge(
            "system_memory_percent", "System memory utilisation %", registry=r
        )

        # ── Pipeline ─────────────────────────────────────────────────
        self.pipeline_e2e_latency_ms = Histogram(
            "pipeline_e2e_latency_ms",
            "End-to-end pipeline latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.pipeline_request_total = Counter(
            "pipeline_request_total", "Total pipeline requests processed", registry=r
        )
        self.pipeline_failure_total = Counter(
            "pipeline_failure_total",
            "Pipeline failures by stage",
            ["stage"],
            registry=r,
        )

        # ── Diagnostics ──────────────────────────────────────────────
        self.diagnostics_report_total = Counter(
            "diagnostics_report_total", "Diagnostic reports generated", registry=r
        )
        self.diagnostics_alert_total = Counter(
            "diagnostics_alert_total",
            "Diagnostic alerts fired",
            ["rule_id", "severity"],
            registry=r,
        )

        # P99 gauges (computed rolling, for rule evaluation)
        self.feedback_api_latency_p99_ms = Gauge(
            "feedback_api_latency_p99_ms",
            "Feedback API P99 latency (rolling, ms)",
            registry=r,
        )
        self.pipeline_e2e_latency_p99_ms = Gauge(
            "pipeline_e2e_latency_p99_ms",
            "Pipeline end-to-end P99 latency (rolling, ms)",
            registry=r,
        )

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_latency(self, stage: str, operation: str, latency_ms: float) -> None:
        hist_map = {
            "audio": self.audio_capture_latency_ms,
            "stt": self.stt_api_latency_ms,
            "feedback": self.feedback_api_latency_ms,
            "pipeline": self.pipeline_e2e_latency_ms,
        }
        hist = hist_map.get(stage)
        if hist:
            hist.observe(latency_ms)
        self._set("pipeline_e2e_latency_ms_last", latency_ms)

    def record_error(self, stage: str, error_type: str) -> None:
        self.pipeline_failure_total.labels(stage=stage).inc()
        if stage == "stt":
            self.stt_api_error_total.labels(error_type=error_type).inc()
        elif stage == "feedback":
            self.feedback_api_error_total.labels(error_code=error_type).inc()

    def _set(self, key: str, value: float) -> None:
        with self._cv_lock:
            self._current_values[key] = value

    def set_metric(self, name: str, value: float) -> None:
        """Set a named scalar metric (used by failure simulator and stage monitors)."""
        with self._cv_lock:
            self._current_values[name] = value

        # Also update the live Prometheus gauge if it exists
        gauge_map: dict[str, Gauge] = {
            "audio_snr_db": self.audio_snr_db,
            "audio_noise_floor_dbfs": self.audio_noise_floor_dbfs,
            "audio_speech_ratio": self.audio_speech_ratio,
            "stt_word_error_rate": self.stt_word_error_rate,
            "stt_confidence_score": self.stt_confidence_score,
            "stt_word_count": self.stt_word_count,
            "storage_upload_latency_ms": self.storage_upload_latency_ms,
            "celery_queue_depth": self.celery_queue_depth,
            "feedback_tokens_per_second": self.feedback_tokens_per_second,
            "feedback_error_rate_429": self.feedback_error_rate_429,
            "feedback_grammar_score": self.feedback_grammar_score,
            "feedback_fluency_score": self.feedback_fluency_score,
            "feedback_overall_score": self.feedback_overall_score,
            "system_cpu_percent": self.system_cpu_percent,
            "system_memory_percent": self.system_memory_percent,
            "feedback_api_latency_p99_ms": self.feedback_api_latency_p99_ms,
            "pipeline_e2e_latency_p99_ms": self.pipeline_e2e_latency_p99_ms,
        }
        if name in gauge_map:
            gauge_map[name].set(value)

    # ------------------------------------------------------------------
    # Snapshot for diagnostics engine
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, float]:
        """Return a point-in-time snapshot of all named scalar metrics."""
        with self._cv_lock:
            base = dict(self._current_values)

        # Pull live gauge values into snapshot
        base["audio_snr_db"] = self.audio_snr_db._value.get()  # type: ignore[attr-defined]
        base["audio_noise_floor_dbfs"] = self.audio_noise_floor_dbfs._value.get()  # type: ignore[attr-defined]
        base["audio_speech_ratio"] = self.audio_speech_ratio._value.get()  # type: ignore[attr-defined]
        base["stt_word_error_rate"] = self.stt_word_error_rate._value.get()  # type: ignore[attr-defined]
        base["stt_confidence_score"] = self.stt_confidence_score._value.get()  # type: ignore[attr-defined]
        base["stt_word_count"] = self.stt_word_count._value.get()  # type: ignore[attr-defined]
        base["storage_upload_latency_ms"] = self.storage_upload_latency_ms._value.get()  # type: ignore[attr-defined]
        base["celery_queue_depth"] = self.celery_queue_depth._value.get()  # type: ignore[attr-defined]
        base["feedback_tokens_per_second"] = self.feedback_tokens_per_second._value.get()  # type: ignore[attr-defined]
        base["feedback_error_rate_429"] = self.feedback_error_rate_429._value.get()  # type: ignore[attr-defined]
        base["feedback_grammar_score"] = self.feedback_grammar_score._value.get()  # type: ignore[attr-defined]
        base["feedback_fluency_score"] = self.feedback_fluency_score._value.get()  # type: ignore[attr-defined]
        base["feedback_overall_score"] = self.feedback_overall_score._value.get()  # type: ignore[attr-defined]
        base["system_cpu_percent"] = self.system_cpu_percent._value.get()  # type: ignore[attr-defined]
        base["system_memory_percent"] = self.system_memory_percent._value.get()  # type: ignore[attr-defined]
        base["feedback_api_latency_p99_ms"] = self.feedback_api_latency_p99_ms._value.get()  # type: ignore[attr-defined]
        base["pipeline_e2e_latency_p99_ms"] = self.pipeline_e2e_latency_p99_ms._value.get()  # type: ignore[attr-defined]
        return base

    # ------------------------------------------------------------------
    # Prometheus exposition
    # ------------------------------------------------------------------

    def exposition_data(self) -> tuple[bytes, str]:
        """Return (body_bytes, content_type) for the /metrics endpoint."""
        return generate_latest(self._registry), CONTENT_TYPE_LATEST
