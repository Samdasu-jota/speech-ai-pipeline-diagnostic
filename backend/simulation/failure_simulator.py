"""
FailureSimulator — injects fault conditions into the pipeline metrics
to exercise the DiagnosticsEngine and validate fault detection coverage.

Each scenario overrides specific MetricsRegistry gauges, causing pipeline
stages to behave as if a real fault is occurring. The diagnostic engine
then runs its normal detection loop and should fire the expected alerts
and generate root cause reports.

This mirrors fault injection testing in automotive diagnostics where
individual sensor signals are overridden to verify ECU fault detection.

Scenarios aligned with Self English Tutor app failure modes:

  high_background_noise   — degrades audio SNR + Whisper confidence
  feedback_rate_limit     — simulates GPT-4o API 429 rate limiting
  stt_timeout             — simulates Whisper API timeout / high latency
  cpu_spike               — simulates high CPU (Celery workers overloaded)
  cascading_failure       — noisy audio → bad transcript → poor feedback scores
  gradual_quality_drift   — slowly drifts Whisper confidence downward
  memory_pressure         — simulates high memory (VAD/torch buffers)
  celery_queue_backup     — Celery queue depth spikes, E2E latency climbs
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Optional

from monitoring.metrics_registry import MetricsRegistry

logger = logging.getLogger(__name__)


class FailureScenario(str, Enum):
    HIGH_BACKGROUND_NOISE = "high_background_noise"
    FEEDBACK_RATE_LIMIT = "feedback_rate_limit"
    STT_TIMEOUT = "stt_timeout"
    CPU_SPIKE = "cpu_spike"
    CASCADING_FAILURE = "cascading_failure"
    GRADUAL_QUALITY_DRIFT = "gradual_quality_drift"
    MEMORY_PRESSURE = "memory_pressure"
    CELERY_QUEUE_BACKUP = "celery_queue_backup"


# Scenario parameter definitions
_SCENARIOS: dict[str, dict] = {
    FailureScenario.HIGH_BACKGROUND_NOISE: {
        "description": (
            "High background noise degrading audio SNR and Whisper transcription confidence. "
            "Expected DTCs: AUD-001, STT-001, STT-003"
        ),
        "overrides": {
            "audio_snr_db": 5.0,
            "audio_noise_floor_dbfs": -20.0,
            "stt_word_error_rate": 0.28,
            "stt_confidence_score": 0.52,
        },
    },
    FailureScenario.FEEDBACK_RATE_LIMIT: {
        "description": (
            "GPT-4o API rate limiting — >10% of feedback requests returning 429. "
            "Expected DTCs: FBK-002"
        ),
        "overrides": {
            "feedback_error_rate_429": 0.45,
            "feedback_api_latency_p99_ms": 5500.0,
        },
    },
    FailureScenario.STT_TIMEOUT: {
        "description": (
            "Whisper API timeouts causing high transcription latency and low confidence. "
            "Expected DTCs: STT-001, STT-003, SYS-003"
        ),
        "overrides": {
            "stt_word_error_rate": 0.22,
            "stt_confidence_score": 0.61,
            "pipeline_e2e_latency_p99_ms": 9000.0,
        },
    },
    FailureScenario.CPU_SPIKE: {
        "description": (
            "CPU spike causing Celery worker throttling and GPT-4o latency degradation. "
            "Expected DTCs: SYS-001, FBK-001"
        ),
        "overrides": {
            "system_cpu_percent": 92.0,
            "feedback_api_latency_p99_ms": 5200.0,
        },
    },
    FailureScenario.CASCADING_FAILURE: {
        "description": (
            "Cascading failure — noisy audio degrades Whisper confidence, "
            "which causes GPT-4o to produce low-quality feedback. "
            "Expected DTCs: AUD-001, STT-001, STT-003, FBK-003"
        ),
        "overrides": {
            "audio_snr_db": 4.5,
            "stt_word_error_rate": 0.31,
            "stt_confidence_score": 0.48,
            "feedback_overall_score": 4.2,
            "feedback_grammar_score": 3.8,
            "pipeline_e2e_latency_p99_ms": 8500.0,
        },
    },
    FailureScenario.GRADUAL_QUALITY_DRIFT: {
        "description": (
            "Gradual Whisper confidence drift — statistical anomaly detection scenario. "
            "Confidence drifts from 0.88 → 0.45 over the scenario duration."
        ),
        "overrides": {},  # Applied incrementally in _gradual_drift_thread
    },
    FailureScenario.MEMORY_PRESSURE: {
        "description": (
            "High memory utilisation approaching OOM — pydub / torch VAD buffers leaking. "
            "Expected DTCs: SYS-002"
        ),
        "overrides": {
            "system_memory_percent": 93.0,
            "system_cpu_percent": 78.0,
        },
    },
    FailureScenario.CELERY_QUEUE_BACKUP: {
        "description": (
            "Celery task queue backup — jobs accumulating faster than workers can process. "
            "Expected DTCs: SYS-003 (E2E latency spike)"
        ),
        "overrides": {
            "celery_queue_depth": 25.0,
            "pipeline_e2e_latency_p99_ms": 12000.0,
            "storage_upload_latency_ms": 800.0,
        },
    },
}

# Healthy baseline values to restore on stop
_HEALTHY_BASELINES = {
    "audio_snr_db": 22.0,
    "audio_noise_floor_dbfs": -60.0,
    "audio_speech_ratio": 0.82,
    "stt_word_error_rate": 0.06,
    "stt_confidence_score": 0.88,
    "stt_word_count": 45.0,
    "feedback_error_rate_429": 0.0,
    "feedback_api_latency_p99_ms": 0.0,
    "feedback_grammar_score": 7.5,
    "feedback_fluency_score": 7.2,
    "feedback_overall_score": 7.4,
    "celery_queue_depth": 0.0,
    "storage_upload_latency_ms": 120.0,
    "pipeline_e2e_latency_p99_ms": 0.0,
    "system_cpu_percent": 30.0,
    "system_memory_percent": 40.0,
}


class FailureSimulator:
    """
    Injects fault conditions into the metrics registry.

    Usage:
        simulator = FailureSimulator()
        simulator.start("high_background_noise", duration_seconds=30)
        ...
        simulator.stop()
    """

    def __init__(self) -> None:
        self.registry = MetricsRegistry.instance()
        self._active_scenario: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def available_scenarios(self) -> list[dict]:
        return [
            {"id": k, "description": v["description"]}
            for k, v in _SCENARIOS.items()
        ]

    def start(self, scenario_id: str, duration_seconds: int = 30) -> str:
        if scenario_id not in _SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario_id}'. "
                f"Available: {list(_SCENARIOS.keys())}"
            )

        # Stop any currently running simulation first
        if self._active_scenario:
            self.stop()

        self._active_scenario = scenario_id
        self._stop_event.clear()
        scenario = _SCENARIOS[scenario_id]

        if scenario_id == FailureScenario.GRADUAL_QUALITY_DRIFT:
            self._thread = threading.Thread(
                target=self._gradual_drift_thread,
                args=(duration_seconds,),
                daemon=True,
                name=f"Simulator-{scenario_id}",
            )
        else:
            self._thread = threading.Thread(
                target=self._fixed_override_thread,
                args=(scenario["overrides"], duration_seconds),
                daemon=True,
                name=f"Simulator-{scenario_id}",
            )

        self._thread.start()
        msg = f"Scenario '{scenario_id}' started for {duration_seconds}s: {scenario['description']}"
        logger.info(
            "failure_simulation_started",
            extra={"scenario": scenario_id, "duration_s": duration_seconds},
        )
        return msg

    def stop(self) -> None:
        if not self._active_scenario:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._restore_baselines()
        logger.info(
            "failure_simulation_stopped",
            extra={"scenario": self._active_scenario},
        )
        self._active_scenario = None

    # ------------------------------------------------------------------
    # Simulation threads
    # ------------------------------------------------------------------

    def _fixed_override_thread(
        self, overrides: dict[str, float], duration_seconds: int
    ) -> None:
        deadline = time.monotonic() + duration_seconds
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            for metric, value in overrides.items():
                self.registry.set_metric(metric, value)
            self._stop_event.wait(timeout=1.0)
        self._restore_baselines()
        self._active_scenario = None

    def _gradual_drift_thread(self, duration_seconds: int) -> None:
        """Slowly decreases Whisper confidence from healthy to degraded over duration."""
        start_confidence = 0.88
        target_confidence = 0.45
        start_time = time.monotonic()
        deadline = start_time + duration_seconds

        while not self._stop_event.is_set() and time.monotonic() < deadline:
            elapsed = time.monotonic() - start_time
            progress = min(1.0, elapsed / duration_seconds)
            current_confidence = start_confidence + (target_confidence - start_confidence) * progress
            # Also drift WER upward as confidence drops
            current_wer = 0.06 + (0.24 * progress)
            self.registry.set_metric("stt_confidence_score", current_confidence)
            self.registry.set_metric("stt_word_error_rate", current_wer)
            self._stop_event.wait(timeout=2.0)

        self._restore_baselines()
        self._active_scenario = None

    def _restore_baselines(self) -> None:
        for metric, value in _HEALTHY_BASELINES.items():
            self.registry.set_metric(metric, value)
        logger.info("failure_simulation_metrics_restored")
