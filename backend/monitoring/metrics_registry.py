"""
Prometheus metrics registry — singleton that owns all instruments.

All pipeline stages and the diagnostics engine read/write metrics through here,
ensuring a single consistent namespace and preventing duplicate registration errors.
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

        # ── Audio Stage ──────────────────────────────────────────────
        self.audio_snr_db = Gauge(
            "audio_snr_db", "Signal-to-noise ratio in dB", registry=r
        )
        self.audio_noise_floor_dbfs = Gauge(
            "audio_noise_floor_dbfs", "Noise floor in dBFS", registry=r
        )
        self.audio_buffer_overflow_total = Counter(
            "audio_buffer_overflow_total", "Audio buffer overflow events", registry=r
        )
        self.audio_capture_latency_ms = Histogram(
            "audio_capture_latency_ms",
            "Audio capture latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )

        # ── STT Stage ────────────────────────────────────────────────
        self.stt_word_error_rate = Gauge(
            "stt_word_error_rate", "Current word error rate (0-1)", registry=r
        )
        self.stt_confidence_score = Histogram(
            "stt_confidence_score",
            "STT confidence score per utterance",
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
            registry=r,
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

        # ── NLP Stage ────────────────────────────────────────────────
        self.nlp_processing_latency_ms = Histogram(
            "nlp_processing_latency_ms",
            "NLP processing latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.nlp_token_count = Histogram(
            "nlp_token_count",
            "Token count per NLP request",
            buckets=(10, 50, 100, 200, 500, 1000, 2000),
            registry=r,
        )
        self.nlp_parse_error_total = Counter(
            "nlp_parse_error_total", "NLP parse errors", registry=r
        )

        # ── LLM Stage ────────────────────────────────────────────────
        self.llm_api_latency_ms = Histogram(
            "llm_api_latency_ms",
            "LLM API latency in ms",
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.llm_tokens_per_second = Gauge(
            "llm_tokens_per_second", "LLM throughput in tokens/s", registry=r
        )
        self.llm_api_error_total = Counter(
            "llm_api_error_total",
            "LLM API errors",
            ["error_code"],
            registry=r,
        )
        self.llm_retry_total = Counter(
            "llm_retry_total", "LLM API retry attempts", registry=r
        )
        self.llm_context_overflow_total = Counter(
            "llm_context_overflow_total", "LLM context window overflow events", registry=r
        )
        self.llm_error_rate_429 = Gauge(
            "llm_error_rate_429", "LLM 429 error rate (fraction)", registry=r
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

        # LLM P99 latency (computed and stored as gauge for rule evaluation)
        self.llm_api_latency_p99_ms = Gauge(
            "llm_api_latency_p99_ms",
            "LLM API P99 latency (rolling, ms)",
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
            "nlp": self.nlp_processing_latency_ms,
            "llm": self.llm_api_latency_ms,
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
        elif stage == "llm":
            self.llm_api_error_total.labels(error_code=error_type).inc()

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
            "stt_word_error_rate": self.stt_word_error_rate,
            "llm_tokens_per_second": self.llm_tokens_per_second,
            "system_cpu_percent": self.system_cpu_percent,
            "system_memory_percent": self.system_memory_percent,
            "llm_api_latency_p99_ms": self.llm_api_latency_p99_ms,
            "pipeline_e2e_latency_p99_ms": self.pipeline_e2e_latency_p99_ms,
            "llm_error_rate_429": self.llm_error_rate_429,
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
        base["stt_word_error_rate"] = self.stt_word_error_rate._value.get()  # type: ignore[attr-defined]
        base["llm_tokens_per_second"] = self.llm_tokens_per_second._value.get()  # type: ignore[attr-defined]
        base["system_cpu_percent"] = self.system_cpu_percent._value.get()  # type: ignore[attr-defined]
        base["system_memory_percent"] = self.system_memory_percent._value.get()  # type: ignore[attr-defined]
        base["llm_api_latency_p99_ms"] = self.llm_api_latency_p99_ms._value.get()  # type: ignore[attr-defined]
        base["pipeline_e2e_latency_p99_ms"] = self.pipeline_e2e_latency_p99_ms._value.get()  # type: ignore[attr-defined]
        base["llm_error_rate_429"] = self.llm_error_rate_429._value.get()  # type: ignore[attr-defined]
        return base

    # ------------------------------------------------------------------
    # Prometheus exposition
    # ------------------------------------------------------------------

    def exposition_data(self) -> tuple[bytes, str]:
        """Return (body_bytes, content_type) for the /metrics endpoint."""
        return generate_latest(self._registry), CONTENT_TYPE_LATEST
